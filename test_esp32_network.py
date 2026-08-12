#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import hmac
import json
import socket
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
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
NODE_C = "rp-102030405060"
TOKEN_A = "01" * 32
TOKEN_B = "ab" * 32


class ESP32NetworkTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        storage = Path(self.temporary_directory.name) / "rainpoint.sqlite3"
        self.gateway = Gateway(transport="rtl433", storage_path=str(storage))
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
        self.temporary_directory.cleanup()

    def _connect(
        self,
        node_id: str,
        token: str,
        *,
        capabilities: list[str] | None = None,
        tx_armed: bool = False,
        protocol_version: int = 1,
    ) -> tuple[socket.socket, Any, dict[str, Any]]:
        connection = socket.create_connection(
            ("127.0.0.1", self.server.server_port), timeout=2
        )
        stream = connection.makefile("rwb", buffering=0)
        challenge = json.loads(stream.readline())
        payload = (
            f"rainpoint-node-v{protocol_version}\n"
            f"{challenge['nonce']}\n{node_id}".encode()
        )
        proof = hmac.new(token.encode(), payload, hashlib.sha256).hexdigest()
        hello = {
            "type": "node_hello",
            "protocol_version": protocol_version,
            "node_id": node_id,
            "firmware_version": "test",
            "mode": (
                "local_radio_node"
                if protocol_version == 2
                else "receive_only"
            ),
            "capabilities": capabilities
            or (
                ["rx", "sensor_pairing_tx"]
                if protocol_version == 2
                else ["rx", "pairing_plan"]
            ),
            "tx_armed": tx_armed,
            "proof": proof,
        }
        stream.write(json.dumps(hello).encode() + b"\n")
        response = json.loads(stream.readline())
        if protocol_version == 2 and response.get("type") == "node_authenticated":
            expected_server_proof = hmac.new(
                token.encode(),
                f"rainpoint-gateway-v2\n{challenge['nonce']}\n{node_id}".encode(),
                hashlib.sha256,
            ).hexdigest()
            self.assertTrue(
                hmac.compare_digest(
                    expected_server_proof, response.get("server_proof", "")
                )
            )
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

    def test_authenticated_node_health_is_validated(self) -> None:
        connection, stream, _ = self._connect(NODE_A, TOKEN_A)
        stream.write(
            json.dumps(
                {
                    "type": "node_health",
                    "node_id": NODE_A,
                    "uptime_seconds": 60,
                    "free_heap_bytes": 210000,
                    "minimum_free_heap_bytes": 190000,
                    "largest_free_block_bytes": 150000,
                    "cpu_frequency_mhz": 240,
                    "device_temperature_c": 43.5,
                    "maximum_loop_gap_ms": 4,
                    "reset_reason_code": 1,
                    "ip_address": "192.168.9.210",
                    "wifi_rssi_dbm": -61,
                    "network_bytes_sent": 1234,
                    "network_bytes_received": 567,
                    "wifi_reconnects": 1,
                    "gateway_connect_attempts": 2,
                    "gateway_authentications": 1,
                }
            ).encode()
            + b"\n"
        )
        for _ in range(50):
            node = self.gateway.nodes()[0]
            if node.get("uptime_seconds") == 60:
                break
            time.sleep(0.01)
        self.assertEqual("192.168.9.210", node["ip_address"])
        self.assertEqual(-61, node["wifi_rssi_dbm"])
        self.assertEqual(43.5, node["device_temperature_c"])
        self.assertEqual(1234, node["network_bytes_sent"])
        self.assertEqual(1, node["gateway_authentications"])

        stream.write(
            json.dumps(
                {
                    "type": "node_health",
                    "node_id": NODE_A,
                    "ip_address": "not-an-address",
                    "wifi_rssi_dbm": 40,
                    "device_temperature_c": 500,
                }
            ).encode()
            + b"\n"
        )
        time.sleep(0.02)
        node = self.gateway.nodes()[0]
        self.assertEqual("192.168.9.210", node["ip_address"])
        self.assertEqual(-61, node["wifi_rssi_dbm"])
        self.assertEqual(43.5, node["device_temperature_c"])
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

    def test_v1_node_may_advertise_disarmed_pairing_bench_firmware(self) -> None:
        connection, stream, response = self._connect(
            NODE_A,
            TOKEN_A,
            capabilities=["rx", "pairing_plan", "pairing_tx_bench"],
        )
        self.assertEqual("node_authenticated", response["type"])
        self.assertEqual(
            ["rx", "pairing_plan", "pairing_tx_bench"],
            self.gateway.nodes()[0]["capabilities"],
        )
        stream.write(
            json.dumps(
                {
                    "type": "pairing_tx_status",
                    "node_id": NODE_A,
                    "state": "armed",
                    "completed_steps": 1,
                    "tx_armed": True,
                    "detail": "reply_transmitted",
                }
            ).encode()
            + b"\n"
        )
        deadline = time.monotonic() + 2
        while not self.gateway.nodes()[0].get("tx_armed"):
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        self.assertEqual("armed", self.gateway.nodes()[0]["pairing_state"])
        self.assertEqual(1, self.gateway.nodes()[0]["pairing_completed_steps"])
        stream.close()
        connection.close()

    def test_v2_node_completes_bounded_pairing_and_registry_flow(self) -> None:
        connection, stream, response = self._connect(
            NODE_A, TOKEN_A, protocol_version=2
        )
        self.assertEqual("node_authenticated", response["type"])
        pairing_started_at = datetime.now().astimezone()
        started = self.gateway.start_pairing(
            120,
            node_id=NODE_A,
            now=pairing_started_at,
        )
        self.assertTrue(started["transmitter_available"])
        self.assertEqual(NODE_A, started["selected_node_id"])
        self.assertEqual(
            ["hcs026_15a98024_v1"],
            [item["profile_id"] for item in started["supported_profiles"]],
        )
        command = json.loads(stream.readline())
        self.assertEqual("pairing_start", command["type"])
        self.assertEqual("hcs026_15a98024_v1", command["profile"])
        self.assertEqual("15a98024", command["factory_endpoint"])
        encoded_clock = datetime.strptime(command["local_clock"], "%Y%m%d%H%M%S")
        expected_clock = (
            pairing_started_at + timedelta(seconds=240)
        ).replace(tzinfo=None, microsecond=0)
        self.assertLessEqual(abs((encoded_clock - expected_clock).total_seconds()), 1)
        self.assertEqual(45_000, command["frequency_offset_hz"])
        self.assertEqual(10, command["power_dbm"])
        self.assertNotIn("valve", json.dumps(command))

        factory = (
            "79f4882f288000000015a98024010083827fa41e8080848000000000000000000000000022f1"
        )
        terminal = (
            "79f4882f28b984028095a9802403028102008000000000000000000000000000000000000f0f"
        )
        for frame in (factory, terminal):
            stream.write(
                json.dumps(
                    {"type": "rainpoint_rf", "node_id": NODE_A, "frame": frame}
                ).encode()
                + b"\n"
            )

        deadline = time.monotonic() + 2
        while True:
            progress = self.gateway.pairing()
            if progress["new_records"]:
                break
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        self.assertEqual(
            "95a98024", progress["new_records"][0]["paired_endpoint"]
        )
        stream.write(
            json.dumps(
                {
                    "type": "pairing_tx_status",
                    "node_id": NODE_A,
                    "command_id": command["command_id"],
                    "state": "completed",
                    "completed_steps": 3,
                    "tx_armed": False,
                }
            ).encode()
            + b"\n"
        )
        deadline = time.monotonic() + 2
        while self.gateway.nodes()[0].get("pairing_state") != "completed":
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        registered = self.gateway.complete_hcs026_pairing(
            endpoint="95a98024", name="Test Sensor B", area="Garden"
        )
        self.assertEqual("hcs026-95a98024", registered["device_id"])
        cancel = json.loads(stream.readline())
        self.assertEqual("pairing_cancel", cancel["type"])
        self.assertEqual(command["command_id"], cancel["command_id"])
        stream.close()
        connection.close()

    def test_pairing_rejects_unknown_protocol_profile(self) -> None:
        connection, stream, _response = self._connect(
            NODE_A, TOKEN_A, protocol_version=2
        )
        with self.assertRaisesRegex(ValueError, "unsupported pairing profile"):
            self.gateway.start_pairing(
                120,
                node_id=NODE_A,
                profile_id="uncaptured_profile",
            )
        self.assertFalse(self.gateway.pairing()["active"])
        stream.close()
        connection.close()

    def test_v2_identify_is_bounded_and_requires_capability(self) -> None:
        connection, stream, response = self._connect(
            NODE_A,
            TOKEN_A,
            protocol_version=2,
            capabilities=["rx", "sensor_pairing_tx", "identify"],
        )
        self.assertEqual("node_authenticated", response["type"])
        result = self.gateway.identify_radio_node(NODE_A, 15)
        command = json.loads(stream.readline())
        self.assertEqual("identify_start", command["type"])
        self.assertEqual(15, command["duration_seconds"])
        self.assertEqual(result["command_id"], command["command_id"])
        self.assertNotIn("pairing", json.dumps(command))
        self.assertNotIn("valve", json.dumps(command))
        stream.write(
            json.dumps(
                {
                    "type": "identify_status",
                    "node_id": NODE_A,
                    "command_id": command["command_id"],
                    "active": False,
                }
            ).encode()
            + b"\n"
        )
        deadline = time.monotonic() + 2
        while self.gateway.nodes()[0].get("identify_active") is not False:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        stream.close()
        connection.close()

        legacy_connection, legacy_stream, _ = self._connect(
            NODE_A, TOKEN_A, protocol_version=2
        )
        with self.assertRaisesRegex(ValueError, "identification"):
            self.gateway.identify_radio_node(NODE_A)
        legacy_stream.close()
        legacy_connection.close()

    def test_pending_adoption_authenticates_once_then_becomes_managed(self) -> None:
        adoption = self.gateway.start_radio_node_adoption(
            node_id=NODE_C,
            name="Front Garden Radio",
            area="Front Garden",
        )
        self.assertEqual(
            adoption["node_token"],
            self.gateway.pending_radio_node_credential(NODE_C),
        )
        connection, stream, response = self._connect(
            NODE_C,
            adoption["node_token"],
            protocol_version=2,
            capabilities=["rx", "sensor_pairing_tx", "identify"],
        )
        self.assertEqual("node_authenticated", response["type"])
        self.assertEqual("adopted", self.gateway.radio_node_adoption(NODE_C)["state"])
        self.assertEqual(
            adoption["node_token"], self.gateway.radio_node_credential(NODE_C)
        )
        self.assertIsNone(self.gateway.pending_radio_node_credential(NODE_C))
        managed = next(
            node for node in self.gateway.nodes() if node["node_id"] == NODE_C
        )
        self.assertEqual("Front Garden Radio", managed["name"])
        self.assertNotIn("token", managed)
        stream.close()
        connection.close()

    def test_command_boundary_rejects_unbounded_rf_actions(self) -> None:
        connection, stream, _ = self._connect(
            NODE_A, TOKEN_A, protocol_version=2
        )
        with self.assertRaises(ValueError):
            self.server.send_command(
                NODE_A,
                {"type": "valve_open", "duration_seconds": 60},
            )
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

    def test_option_credentials_migrate_once_to_managed_registry(self) -> None:
        managed = {item["node_id"]: item for item in self.gateway.nodes()}
        self.assertTrue(managed[NODE_A]["managed"])
        self.assertTrue(managed[NODE_B]["managed"])
        self.assertEqual(TOKEN_A, self.gateway.radio_node_credential(NODE_A))

        self.gateway.register_radio_node(
            node_id=NODE_A,
            token="cd" * 32,
            name="Renamed Node",
            area="Garden",
        )
        self.gateway.import_node_credentials({NODE_A: TOKEN_A})
        self.assertEqual("cd" * 32, self.gateway.radio_node_credential(NODE_A))
        managed = {item["node_id"]: item for item in self.gateway.nodes()}
        self.assertEqual("Renamed Node", managed[NODE_A]["name"])


if __name__ == "__main__":
    unittest.main()
