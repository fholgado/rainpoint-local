#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import hmac
import json
import socket
import sys
import time
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "rainpointd_addon"))

from rainpointd.esp32_network import ESP32NetworkServer, load_node_tokens
from rainpointd.gateway import Gateway


FRAME = (
    "79f4882f28b42d008f9ce580240784830701800544200000"
    "000000000000000000000000308a"
)
NODE_A = "rp-001122334455"
NODE_B = "rp-aabbccddeeff"
TOKEN_A = "01" * 32
TOKEN_B = "ab" * 32


class ESP32NetworkTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gateway = Gateway(transport="rtl433")
        self.server = ESP32NetworkServer(
            self.gateway,
            host="127.0.0.1",
            port=0,
            node_tokens={NODE_A: TOKEN_A, NODE_B: TOKEN_B},
        )
        self.server.start()

    def tearDown(self) -> None:
        self.server.stop()
        self.gateway.close()

    def _connect(
        self,
        node_id: str,
        token: str,
        *,
        capabilities: list[str] | None = None,
        tx_armed: bool = False,
    ) -> tuple[socket.socket, Any, dict[str, Any]]:
        connection = socket.create_connection(
            ("127.0.0.1", self.server.server_port), timeout=2
        )
        stream = connection.makefile("rwb", buffering=0)
        challenge = json.loads(stream.readline())
        payload = (
            f"rainpoint-node-v1\n{challenge['nonce']}\n{node_id}".encode()
        )
        proof = hmac.new(token.encode(), payload, hashlib.sha256).hexdigest()
        hello = {
            "type": "node_hello",
            "protocol_version": 1,
            "node_id": node_id,
            "firmware_version": "test",
            "mode": "receive_only",
            "capabilities": capabilities or ["rx", "pairing_plan"],
            "tx_armed": tx_armed,
            "proof": proof,
        }
        stream.write(json.dumps(hello).encode() + b"\n")
        response = json.loads(stream.readline())
        return connection, stream, response

    def test_authenticated_node_publishes_frame_with_provenance(self) -> None:
        connection, stream, response = self._connect(NODE_A, TOKEN_A)
        self.assertEqual("node_authenticated", response["type"])
        stream.write(
            json.dumps(
                {
                    "type": "rainpoint_rf",
                    "node_id": NODE_B,
                    "frame": FRAME,
                }
            ).encode()
            + b"\n"
        )
        stream.write(
            json.dumps(
                {
                    "type": "rainpoint_rf",
                    "node_id": NODE_A,
                    "radio": "primary",
                    "channel": 11,
                    "rssi_dbm": -71.5,
                    "frame": FRAME,
                }
            ).encode()
            + b"\n"
        )
        for _ in range(50):
            right_bed = next(
                item
                for item in self.gateway.devices()
                if item["device_id"] == "soil-right-bed"
            )
            if right_bed["available"]:
                break
            time.sleep(0.01)
        self.assertEqual(NODE_A, right_bed["state"]["rf_node_id"])
        self.assertEqual(64, right_bed["state"]["soil_moisture_percent"])
        self.assertTrue(self.gateway.nodes()[0]["authenticated"])
        self.assertEqual(
            ["rx", "pairing_plan"], self.gateway.nodes()[0]["capabilities"]
        )
        self.assertFalse(self.gateway.nodes()[0]["tx_armed"])
        self.assertEqual(1, self.gateway.nodes()[0]["received_frames"])
        self.assertEqual(1, self.gateway.nodes()[0]["invalid_messages"])
        stream.close()
        connection.close()

    def test_invalid_proof_is_rejected(self) -> None:
        connection, stream, response = self._connect(NODE_A, TOKEN_B)
        self.assertEqual("node_rejected", response["type"])
        stream.close()
        connection.close()

    def test_v1_node_cannot_claim_transmit_capability_or_armed_state(self) -> None:
        for capabilities, tx_armed in ((["rx", "tx"], False), (["rx"], True)):
            with self.subTest(capabilities=capabilities, tx_armed=tx_armed):
                connection, stream, response = self._connect(
                    NODE_A,
                    TOKEN_A,
                    capabilities=capabilities,
                    tx_armed=tx_armed,
                )
                self.assertEqual("node_rejected", response["type"])
                stream.close()
                connection.close()

    def test_second_session_for_same_node_is_rejected(self) -> None:
        first_connection, first, first_response = self._connect(NODE_A, TOKEN_A)
        second_connection, second, second_response = self._connect(NODE_A, TOKEN_A)
        self.assertEqual("node_authenticated", first_response["type"])
        self.assertEqual("node_rejected", second_response["type"])
        self.assertEqual("already_connected", second_response["reason"])
        first.close()
        second.close()
        first_connection.close()
        second_connection.close()

    def test_same_frame_from_second_node_is_deduplicated(self) -> None:
        first_connection, first, _ = self._connect(NODE_A, TOKEN_A)
        second_connection, second, _ = self._connect(NODE_B, TOKEN_B)
        message = json.dumps({"type": "rainpoint_rf", "frame": FRAME}).encode()
        first.write(message + b"\n")
        time.sleep(0.02)
        second.write(message + b"\n")
        time.sleep(0.02)
        first.write(message + b"\n")
        for _ in range(50):
            nodes = {item["node_id"]: item for item in self.gateway.nodes()}
            observations = [
                event
                for event in self.gateway.events()
                if event["event_type"] == "device_observation"
            ]
            if (
                nodes.get(NODE_B, {}).get("duplicate_frames") == 1
                and len(observations) == 2
            ):
                break
            time.sleep(0.01)
        self.assertEqual(2, len(observations))
        self.assertEqual(1, nodes[NODE_B]["duplicate_frames"])
        first.close()
        second.close()
        first_connection.close()
        second_connection.close()

    def test_node_token_configuration_is_strict(self) -> None:
        self.assertEqual({}, load_node_tokens(""))
        self.assertEqual(
            {NODE_A: TOKEN_A}, load_node_tokens(json.dumps({NODE_A: TOKEN_A}))
        )
        for value in ("[]", '{"bad":"' + TOKEN_A + '"}', "not-json"):
            with self.assertRaises(ValueError):
                load_node_tokens(value)


if __name__ == "__main__":
    unittest.main()
