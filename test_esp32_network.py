#!/usr/bin/env python3

from __future__ import annotations

import binascii
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
from rainpointd.valve_protocol import ValveLink, build_htv405_close_frame


FRAME = (
    "79f4882f28b42d008f9ce580240784830701800544200000"
    "000000000000000000000000308a"
)
NODE_A = "rp-001122334455"
NODE_B = "rp-aabbccddeeff"
NODE_C = "rp-102030405060"
TOKEN_A = "01" * 32
TOKEN_B = "ab" * 32


def _replace_frame_endpoint(
    frame_hex: str, *, offset: int, endpoint: str
) -> str:
    """Substitute one endpoint while preserving the frame's CRC residue."""
    frame = bytearray.fromhex(frame_hex)
    residue = binascii.crc_hqx(frame[:-2], 0) ^ int.from_bytes(
        frame[-2:], "big"
    )
    frame[offset : offset + 4] = bytes.fromhex(endpoint)
    trailer = binascii.crc_hqx(frame[:-2], 0) ^ residue
    frame[-2:] = trailer.to_bytes(2, "big")
    return frame.hex()


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
        hello_fields: dict[str, Any] | None = None,
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
        hello.update(hello_fields or {})
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

    def test_v2_node_reports_firmware_compatibility_contract(self) -> None:
        connection, stream, response = self._connect(
            NODE_A,
            TOKEN_A,
            protocol_version=2,
            capabilities=["rx", "sensor_pairing_tx", "firmware_update_trial"],
            hello_fields={
                "hardware_profile": "esp32dev-cc1101-v1",
                "firmware_channel": "experimental",
                "gateway_host": "192.168.9.80",
            },
        )
        self.assertEqual("node_authenticated", response["type"])
        for _ in range(50):
            node = self.gateway.nodes()[0]
            if node.get("gateway_host"):
                break
            time.sleep(0.01)
        self.assertEqual("esp32dev-cc1101-v1", node["hardware_profile"])
        self.assertEqual("experimental", node["firmware_channel"])
        self.assertEqual("192.168.9.80", node["gateway_host"])
        stream.close()
        connection.close()

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
                    "routine_ack_authorized_sensors": 1,
                    "routine_ack_transmissions": 12,
                    "routine_ack_failures": 0,
                    "sensor_recovery_transmissions": 3,
                    "sensor_recovery_failures": 0,
                    "sensor_recovery_completions": 1,
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
        self.assertEqual(1, node["routine_ack_authorized_sensors"])
        self.assertEqual(12, node["routine_ack_transmissions"])
        self.assertEqual(3, node["sensor_recovery_transmissions"])

        stream.write(
            json.dumps(
                {
                    "type": "routine_ack_status",
                    "node_id": NODE_A,
                    "state": "transmitted",
                    "paired_endpoint": "95a98024",
                    "assigned_channel": 4,
                    "channel_center_hz": 433516500,
                    "authorized_sensor_count": 1,
                    "transmissions": 13,
                    "failures": 0,
                }
            ).encode()
            + b"\n"
        )
        for _ in range(50):
            node = self.gateway.nodes()[0]
            if node.get("routine_ack_transmissions") == 13:
                break
            time.sleep(0.01)
        self.assertEqual("transmitted", node["routine_ack_state"])
        self.assertEqual("95a98024", node["routine_ack_endpoint"])
        self.assertEqual(4, node["routine_ack_assigned_channel"])

        stream.write(
            json.dumps(
                {
                    "type": "sensor_recovery_status",
                    "node_id": NODE_A,
                    "state": "reply_transmitted",
                    "phase": "paired_message_1",
                    "paired_endpoint": "95a98024",
                    "transmissions": 4,
                    "failures": 0,
                    "completions": 1,
                }
            ).encode()
            + b"\n"
        )
        for _ in range(50):
            node = self.gateway.nodes()[0]
            if node.get("rf_recovery_transmissions") == 4:
                break
            time.sleep(0.01)
        self.assertEqual("reply_transmitted", node["rf_recovery_state"])
        self.assertEqual("paired_message_1", node["rf_recovery_phase"])
        self.assertEqual("95a98024", node["sensor_recovery_endpoint"])

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
                    "assigned_channel": 5,
                    "counter_offset": 1,
                    "counter_offset_known": True,
                    "selector2_configuration_transmitted": True,
                    "selector2_configuration_sequence": 3,
                    "reply_marker_repeat": True,
                    "htv145_later_sweep_branch": True,
                    "htv145_factory_sweep_observed": True,
                    "htv145_last_factory_sweep_counter": 3,
                    "htv145_assignment_locked": True,
                    "htv145_accepted_factory_counter": 0,
                    "htv145_stage0_accepted": False,
                    "htv145_stage0_rejected": True,
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
        self.assertEqual(
            5, self.gateway.nodes()[0]["pairing_assigned_channel"]
        )
        self.assertEqual(1, self.gateway.nodes()[0]["pairing_counter_offset"])
        self.assertIs(
            True,
            self.gateway.nodes()[0]["pairing_counter_offset_known"],
        )
        self.assertIs(
            True,
            self.gateway.nodes()[0][
                "pairing_selector2_configuration_transmitted"
            ],
        )
        self.assertEqual(
            3,
            self.gateway.nodes()[0][
                "pairing_selector2_configuration_sequence"
            ],
        )
        self.assertIs(
            True,
            self.gateway.nodes()[0]["pairing_htv145_assignment_locked"],
        )
        self.assertEqual(
            0,
            self.gateway.nodes()[0][
                "pairing_htv145_accepted_factory_counter"
            ],
        )
        self.assertIs(
            False,
            self.gateway.nodes()[0]["pairing_htv145_stage0_accepted"],
        )
        self.assertIs(
            True,
            self.gateway.nodes()[0]["pairing_htv145_stage0_rejected"],
        )
        self.assertIs(
            True,
            self.gateway.nodes()[0]["pairing_reply_marker_repeat"],
        )
        self.assertIs(
            True,
            self.gateway.nodes()[0]["pairing_htv145_later_sweep_branch"],
        )
        self.assertIs(
            True,
            self.gateway.nodes()[0][
                "pairing_htv145_factory_sweep_observed"
            ],
        )
        self.assertEqual(
            3,
            self.gateway.nodes()[0][
                "pairing_htv145_last_factory_sweep_counter"
            ],
        )
        stream.close()
        connection.close()

    def test_v2_node_completes_bounded_pairing_and_registry_flow(self) -> None:
        connection, stream, response = self._connect(
            NODE_A,
            TOKEN_A,
            protocol_version=2,
            capabilities=[
                "rx",
                "sensor_pairing_tx",
                "routine_sensor_ack_tx",
                "configurable_rf_controller_identity",
            ],
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
            [
                "hcs026_auto_v1",
                "htv145_auto_candidate_v1",
                "htv405_auto_candidate_v1",
            ],
            [item["profile_id"] for item in started["supported_profiles"]],
        )
        self.assertTrue(started["supported_profiles"][0]["automatic_discovery"])
        command = json.loads(stream.readline())
        self.assertEqual("pairing_start", command["type"])
        self.assertEqual("hcs026_auto_v1", command["profile"])
        self.assertNotIn("factory_endpoint", command)
        self.assertEqual(
            self.gateway.rf_identity.controller_endpoint,
            command["controller_endpoint"],
        )
        self.assertEqual(
            self.gateway.rf_identity.companion_endpoint,
            command["companion_endpoint"],
        )
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
        terminal = _replace_frame_endpoint(
            "79f4882f28b984028095a9802403028102008000000000000000000000000000000000000f0f",
            offset=5,
            endpoint=self.gateway.rf_identity.controller_endpoint,
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
                    "assigned_channel": 4,
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
        ack_configuration = json.loads(stream.readline())
        self.assertEqual("routine_ack_configure", ack_configuration["type"])
        self.assertEqual("95a98024", ack_configuration["paired_endpoint"])
        self.assertEqual(
            self.gateway.rf_identity.controller_endpoint,
            ack_configuration["controller_endpoint"],
        )
        self.assertEqual(
            self.gateway.rf_identity.companion_endpoint,
            ack_configuration["companion_endpoint"],
        )
        self.assertEqual(NODE_A, self.gateway.ack_assignments()[0]["node_id"])
        cancel = json.loads(stream.readline())
        self.assertEqual("pairing_cancel", cancel["type"])
        self.assertEqual(command["command_id"], cancel["command_id"])

        # Recovering a sensor already enrolled in this gateway does not create
        # a new enrollment record. The radio node's command-scoped completion
        # identity must still let Home Assistant finish the flow successfully.
        restarted = self.gateway.start_pairing(120, node_id=NODE_A)
        self.assertEqual([], restarted["new_records"])
        recovery_command = json.loads(stream.readline())
        stream.write(
            json.dumps(
                {
                    "type": "pairing_tx_status",
                    "node_id": NODE_A,
                    "command_id": recovery_command["command_id"],
                    "state": "completed",
                    "completed_steps": 4,
                    "step_count": 4,
                    "assigned_channel": 4,
                    "factory_endpoint": "15a98024",
                    "paired_endpoint": "95a98024",
                    "awaiting_terminal_confirmation": False,
                    "tx_armed": False,
                }
            ).encode()
            + b"\n"
        )
        deadline = time.monotonic() + 2
        while self.gateway.nodes()[0].get("pairing_state") != "completed":
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)

        # A known sensor can emit a valid recovery sequence for its retained
        # stock identity while a custom-identity enrollment is active. The
        # node's completion status alone must not let that unrelated exchange
        # transfer its persistent ACK owner.
        stream.write(
            json.dumps(
                {
                    "type": "rainpoint_rf",
                    "node_id": NODE_A,
                    "frame": _replace_frame_endpoint(
                        terminal,
                        offset=5,
                        endpoint="b9840280",
                    ),
                }
            ).encode()
            + b"\n"
        )
        deadline = time.monotonic() + 2
        while True:
            recovered = self.gateway.pairing()
            if recovered["sensor_controller_identity_mismatch_observed"]:
                break
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        self.assertEqual("controller_identity_mismatch", recovered["stage"])
        self.assertIsNone(recovered["completed_endpoint"])
        with self.assertRaisesRegex(RuntimeError, "active RF controller"):
            self.gateway.complete_hcs026_pairing(
                endpoint="95a98024", name="Test Sensor B", area="Garden"
            )

        stream.write(
            json.dumps(
                {"type": "rainpoint_rf", "node_id": NODE_A, "frame": terminal}
            ).encode()
            + b"\n"
        )
        deadline = time.monotonic() + 2
        while True:
            recovered = self.gateway.pairing()
            if recovered.get("completed_endpoint"):
                break
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        self.assertEqual([], recovered["new_records"])
        self.assertEqual("95a98024", recovered["completed_endpoint"])
        self.assertTrue(recovered["completed_existing_record"])
        self.assertEqual("paired_identity_observed", recovered["stage"])
        stream.close()
        connection.close()

    def test_v2_node_automatically_discovers_htv405_identity(self) -> None:
        connection, stream, _response = self._connect(
            NODE_A,
            TOKEN_A,
            protocol_version=2,
            capabilities=[
                "rx",
                "sensor_pairing_tx",
                "valve_pairing_tx_candidate",
                "htv405_auto_identity_pairing",
                "configurable_rf_controller_identity",
            ],
        )
        started = self.gateway.start_pairing(
            120,
            node_id=NODE_A,
            profile_id="htv405_auto_candidate_v1",
        )
        self.assertEqual(
            "htv405_auto_candidate_v1", started["active_profile_id"]
        )
        command = json.loads(stream.readline())
        self.assertEqual("pairing_start", command["type"])
        self.assertEqual("htv405_auto_candidate_v1", command["profile"])
        self.assertNotIn("factory_endpoint", command)
        self.assertEqual(
            self.gateway.rf_identity.controller_endpoint,
            command["valve_route"],
        )
        self.assertEqual(
            self.gateway.rf_identity.companion_endpoint,
            command["companion_endpoint"],
        )

        stream.write(
            json.dumps(
                {
                    "type": "pairing_tx_status",
                    "node_id": NODE_A,
                    "command_id": command["command_id"],
                    "profile": "htv405_auto_candidate_v1",
                    "state": "armed",
                    "completed_steps": 1,
                    "step_count": 18,
                    "factory_endpoint": "14a98013",
                    "paired_endpoint": "94a98013",
                    "tx_armed": True,
                }
            ).encode()
            + b"\n"
        )
        deadline = time.monotonic() + 2
        while True:
            node = self.gateway.nodes()[0]
            if node.get("pairing_paired_endpoint") == "94a98013":
                break
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)

        local_route = command["valve_route"]
        confirmation_frame = build_htv405_close_frame(
            ValveLink(
                controller_endpoint=bytes.fromhex(local_route),
                valve_endpoint=bytes.fromhex("94a98013"),
            ),
            sequence=11,
            zone=1,
            selector=0x05,
            repeat=False,
            residue=0xC713,
        ).hex()
        self.gateway.observe_rf_frame(
            frame=confirmation_frame,
            state={
                "rf_endpoint_a": local_route,
                "rf_endpoint_b": "94a98013",
                "rf_receiver_id": NODE_A,
            },
        )
        progress = self.gateway.pairing()
        self.assertEqual("valve_pairing_completed", progress["stage"])
        self.assertEqual("94a98013", progress["completed_endpoint"])
        node = self.gateway.nodes()[0]
        self.assertEqual("completed", node["pairing_outcome"])
        self.assertEqual(
            "gateway_terminal_evidence", node["pairing_completion_source"]
        )
        self.assertEqual("active", node["pairing_tail_state"])
        self.assertEqual("armed", node["pairing_state"])
        self.assertTrue(node["tx_armed"])
        control = next(
            item
            for item in self.gateway._store.valve_registry()
            if item["valve_endpoint"] == "94a98013"
        )
        self.assertEqual(1, control["control_next_sequence"])
        self.assertEqual(
            "counter_synchronized:fresh_generated_identity_pairing",
            control["control_last_result"],
        )
        self.gateway._store.synchronize_htv405_control_counter(
            valve_endpoint="94a98013",
            node_id=NODE_A,
            next_sequence=2,
            source="authenticated_command_response",
            observed_at=datetime.now().astimezone().isoformat(),
        )
        self.gateway.observe_rf_frame(
            frame=build_htv405_close_frame(
                ValveLink(
                    controller_endpoint=bytes.fromhex(local_route),
                    valve_endpoint=bytes.fromhex("94a98013"),
                ),
                sequence=12,
                zone=1,
                selector=0x05,
                repeat=False,
                residue=0xC713,
            ).hex(),
            state={
                "rf_endpoint_a": local_route,
                "rf_endpoint_b": "94a98013",
                "rf_receiver_id": NODE_A,
            },
        )
        control = next(
            item
            for item in self.gateway._store.valve_registry()
            if item["valve_endpoint"] == "94a98013"
        )
        self.assertEqual(2, control["control_next_sequence"])
        registered = self.gateway.complete_pairing(
            endpoint="94a98013",
            name="Automatically discovered valve",
            area="Garden",
        )
        self.assertEqual("htv405-94a98013", registered["device_id"])
        # This is the exact live beta.10 outcome: the valve has already moved
        # into authenticated ordinary traffic, while two optional stock-tail
        # rows never arrive before the node's bounded timer expires. Preserve
        # the literal node result without exposing it as the pairing outcome.
        stream.write(
            json.dumps(
                {
                    "type": "pairing_tx_status",
                    "node_id": NODE_A,
                    "command_id": command["command_id"],
                    "profile": "htv405_auto_candidate_v1",
                    "state": "failed",
                    "completed_steps": 16,
                    "step_count": 18,
                    "factory_endpoint": "14a98013",
                    "paired_endpoint": "94a98013",
                    "failure_reason": "session_timeout",
                    "detail": "state_changed",
                    "tx_armed": False,
                }
            ).encode()
            + b"\n"
        )
        deadline = time.monotonic() + 2
        while self.gateway.nodes()[0].get("pairing_node_state") != "failed":
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        node = self.gateway.nodes()[0]
        self.assertEqual("completed", node["pairing_state"])
        self.assertEqual("none", node["pairing_failure_reason"])
        self.assertEqual("completed", node["pairing_outcome"])
        self.assertEqual("failed", node["pairing_node_state"])
        self.assertEqual(
            "session_timeout", node["pairing_node_failure_reason"]
        )
        self.assertEqual("optional_tail_timeout", node["pairing_tail_state"])
        self.assertFalse(node["tx_armed"])
        connection.settimeout(0.1)
        with self.assertRaises((TimeoutError, socket.timeout)):
            connection.recv(1)
        stream.close()
        connection.close()

    def test_preterminal_valve_pairing_timeout_remains_failed(self) -> None:
        connection, stream, _response = self._connect(
            NODE_A,
            TOKEN_A,
            protocol_version=2,
            capabilities=[
                "rx",
                "sensor_pairing_tx",
                "htv405_auto_identity_pairing",
                "configurable_rf_controller_identity",
            ],
        )
        self.gateway.start_pairing(
            120,
            node_id=NODE_A,
            profile_id="htv405_auto_candidate_v1",
        )
        command = json.loads(stream.readline())
        stream.write(
            json.dumps(
                {
                    "type": "pairing_tx_status",
                    "node_id": NODE_A,
                    "command_id": command["command_id"],
                    "profile": "htv405_auto_candidate_v1",
                    "state": "failed",
                    "completed_steps": 1,
                    "step_count": 18,
                    "factory_endpoint": "14a98013",
                    "paired_endpoint": "94a98013",
                    "failure_reason": "session_timeout",
                    "detail": "state_changed",
                    "tx_armed": False,
                }
            ).encode()
            + b"\n"
        )
        deadline = time.monotonic() + 2
        while self.gateway.nodes()[0].get("pairing_state") != "failed":
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        node = self.gateway.nodes()[0]
        self.assertEqual("failed", node["pairing_state"])
        self.assertEqual("failed", node["pairing_outcome"])
        self.assertEqual("session_timeout", node["pairing_failure_reason"])
        self.assertEqual("failed", node["pairing_tail_state"])
        self.assertFalse(node["tx_armed"])
        stream.close()
        connection.close()

    def test_v2_node_accepts_explicit_bounded_valve_pairing(self) -> None:
        connection, stream, _response = self._connect(
            NODE_A,
            TOKEN_A,
            protocol_version=2,
            capabilities=[
                "rx",
                "sensor_pairing_tx",
                "valve_pairing_tx_candidate",
            ],
        )
        with self.assertRaisesRegex(ValueError, "does not support"):
            self.gateway.start_pairing(
                120,
                node_id=NODE_A,
                profile_id="htv405_auto_candidate_v1",
            )
        pairing_started_at = datetime.now().astimezone()
        started = self.gateway.start_pairing(
            120,
            node_id=NODE_A,
            profile_id="htv405_auto_candidate_v1",
            factory_endpoint="14a98013",
            valve_route="b9840280",
            companion_endpoint="39840280",
            now=pairing_started_at,
        )
        self.assertEqual(
            "htv405_auto_candidate_v1", started["active_profile_id"]
        )
        command = json.loads(stream.readline())
        self.assertEqual("pairing_start", command["type"])
        self.assertEqual("htv405_auto_candidate_v1", command["profile"])
        self.assertEqual("14a98013", command["factory_endpoint"])
        self.assertEqual("b9840280", command["valve_route"])
        self.assertEqual("39840280", command["companion_endpoint"])
        self.assertNotIn("known_rejoin", command)
        self.assertEqual(97_154, command["frequency_offset_hz"])
        encoded_clock = datetime.strptime(command["local_clock"], "%Y%m%d%H%M%S")
        expected_clock = pairing_started_at.replace(tzinfo=None, microsecond=0)
        self.assertLessEqual(abs((encoded_clock - expected_clock).total_seconds()), 1)
        self.assertNotIn("open", json.dumps(command))
        self.assertNotIn("zone", json.dumps(command))
        stream.write(
            json.dumps(
                {
                    "type": "pairing_tx_status",
                    "node_id": NODE_A,
                    "command_id": command["command_id"],
                    "profile": "htv405_auto_candidate_v1",
                    "state": "completed",
                    "completed_steps": 18,
                    "step_count": 18,
                    "factory_endpoint": "14a98013",
                    "paired_endpoint": "94a98013",
                    "tx_armed": False,
                }
            ).encode()
            + b"\n"
        )
        deadline = time.monotonic() + 2
        while True:
            progress = self.gateway.pairing()
            if progress.get("stage") == "waiting_for_terminal_confirmation":
                break
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        self.assertIsNone(progress["completed_endpoint"])
        confirmation_frame = build_htv405_close_frame(
            ValveLink(
                controller_endpoint=bytes.fromhex("b9840280"),
                valve_endpoint=bytes.fromhex("94a98013"),
            ),
            sequence=11,
            zone=1,
            selector=0x05,
            repeat=False,
            residue=0xC713,
        ).hex()
        self.gateway.observe_rf_frame(
            frame=confirmation_frame,
            state={
                "rf_endpoint_a": "b9840280",
                "rf_endpoint_b": "94a98013",
                "rf_receiver_id": "local-sdr",
            },
        )
        progress = self.gateway.pairing()
        self.assertEqual("valve_pairing_completed", progress["stage"])
        self.assertEqual("94a98013", progress["completed_endpoint"])
        registered = self.gateway.complete_pairing(
            endpoint="94a98013",
            name="Back garden valve",
            area="Garden",
        )
        self.assertEqual("htv405-94a98013", registered["device_id"])
        self.assertEqual("Back garden valve", registered["name"])
        self.assertEqual("Garden", registered["area"])
        self.assertEqual(1, len(self.gateway._store.valve_registry()))
        connection.settimeout(0.1)
        with self.assertRaises((TimeoutError, socket.timeout)):
            connection.recv(1)
        self.assertEqual([], progress["new_records"])
        stream.close()
        connection.close()

    def test_explicit_valve_repair_clears_suppression_without_duplicate(self) -> None:
        valve_endpoint = "94a98013"
        valve_frame = build_htv405_close_frame(
            ValveLink(
                controller_endpoint=bytes.fromhex("b9840280"),
                valve_endpoint=bytes.fromhex(valve_endpoint),
            ),
            sequence=11,
            zone=1,
            selector=0x05,
            repeat=False,
            residue=0xC713,
        ).hex()
        self.assertIsNotNone(
            self.gateway.register_observed_htv405_link(
                controller_endpoint="b9840280",
                valve_endpoint=valve_endpoint,
                frame=valve_frame,
                observed_at="2026-08-25T20:00:00+00:00",
            )
        )
        forgotten = self.gateway.forget_registry_device(
            f"htv405-{valve_endpoint}"
        )
        self.assertEqual(valve_endpoint, forgotten["endpoint"])
        self.assertTrue(self.gateway.endpoint_suppressed(valve_endpoint))

        connection, stream, _response = self._connect(
            NODE_A,
            TOKEN_A,
            protocol_version=2,
            capabilities=[
                "rx",
                "sensor_pairing_tx",
                "valve_pairing_tx_candidate",
            ],
        )
        self.gateway.start_pairing(
            120,
            node_id=NODE_A,
            profile_id="htv405_auto_candidate_v1",
            factory_endpoint="14a98013",
            valve_route="b9840280",
            companion_endpoint="39840280",
        )
        command = json.loads(stream.readline())
        stream.write(
            json.dumps(
                {
                    "type": "pairing_tx_status",
                    "node_id": NODE_A,
                    "command_id": command["command_id"],
                    "profile": "htv405_auto_candidate_v1",
                    "state": "armed",
                    "completed_steps": 1,
                    "step_count": 18,
                    "factory_endpoint": "14a98013",
                    "paired_endpoint": valve_endpoint,
                    "tx_armed": True,
                }
            ).encode()
            + b"\n"
        )
        deadline = time.monotonic() + 2
        while self.gateway.nodes()[0].get("pairing_completed_steps") != 1:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)

        self.gateway.observe_rf_frame(
            frame=valve_frame,
            state={
                "rf_endpoint_a": "b9840280",
                "rf_endpoint_b": valve_endpoint,
                "rf_receiver_id": "local-sdr",
            },
        )
        self.assertEqual(
            "valve_pairing_completed", self.gateway.pairing()["stage"]
        )
        registered = self.gateway.complete_pairing(
            endpoint=valve_endpoint,
            name="Repaired valve",
            area="Vegetable Garden",
        )

        self.assertFalse(self.gateway.endpoint_suppressed(valve_endpoint))
        self.assertEqual("htv405-94a98013", registered["device_id"])
        self.assertEqual("Repaired valve", registered["name"])
        self.assertEqual(1, len(self.gateway._store.valve_registry()))
        devices = [
            device
            for device in self.gateway.devices()
            if device["device_id"] == "htv405-94a98013"
        ]
        self.assertEqual(1, len(devices))
        self.assertEqual("Repaired valve", devices[0]["name"])
        connection.settimeout(0.1)
        with self.assertRaises((TimeoutError, socket.timeout)):
            connection.recv(1)
        stream.close()
        connection.close()

    def test_v2_valve_pairing_defaults_to_persistent_local_rf_identity(self) -> None:
        connection, stream, _response = self._connect(
            NODE_A,
            TOKEN_A,
            protocol_version=2,
            capabilities=[
                "rx",
                "sensor_pairing_tx",
                "valve_pairing_tx_candidate",
                "configurable_rf_controller_identity",
            ],
        )
        self.gateway.start_pairing(
            120,
            node_id=NODE_A,
            profile_id="htv405_auto_candidate_v1",
            factory_endpoint="14a98013",
        )
        command = json.loads(stream.readline())
        self.assertEqual(
            self.gateway.rf_identity.controller_endpoint,
            command["valve_route"],
        )
        self.assertEqual(
            self.gateway.rf_identity.companion_endpoint,
            command["companion_endpoint"],
        )
        self.assertNotEqual("b9840280", command["valve_route"])
        self.gateway.stop_pairing()
        cancel = json.loads(stream.readline())
        self.assertEqual("pairing_cancel", cancel["type"])
        stream.close()
        connection.close()

    def test_same_route_valve_repair_preserves_authenticated_counter(self) -> None:
        valve_endpoint = "94a98013"
        controller_endpoint = self.gateway.rf_identity.controller_endpoint
        companion_endpoint = self.gateway.rf_identity.companion_endpoint
        valve_frame = build_htv405_close_frame(
            ValveLink(
                controller_endpoint=bytes.fromhex(controller_endpoint),
                valve_endpoint=bytes.fromhex(valve_endpoint),
            ),
            sequence=11,
            zone=1,
            selector=0x05,
            repeat=False,
            residue=0xC713,
        ).hex()
        self.assertIsNotNone(
            self.gateway.register_observed_htv405_link(
                controller_endpoint=controller_endpoint,
                valve_endpoint=valve_endpoint,
                frame=valve_frame,
                observed_at="2026-08-26T15:00:00+00:00",
            )
        )
        connection, stream, _response = self._connect(
            NODE_A,
            TOKEN_A,
            protocol_version=2,
            capabilities=[
                "rx",
                "sensor_pairing_tx",
                "valve_pairing_tx_candidate",
                "configurable_rf_controller_identity",
            ],
        )
        self.gateway.start_pairing(
            120,
            node_id=NODE_A,
            profile_id="htv405_auto_candidate_v1",
            factory_endpoint="14a98013",
        )
        command = json.loads(stream.readline())
        assert self.gateway._store is not None
        self.gateway._store.update_valve_control_profile(
            valve_endpoint=valve_endpoint,
            node_id=NODE_A,
            companion_endpoint=companion_endpoint,
            selector=0x05,
            frequency_offset_hz=int(command["frequency_offset_hz"]),
            observed_at="2026-08-26T15:00:01+00:00",
        )
        self.gateway._store.synchronize_htv405_control_counter(
            valve_endpoint=valve_endpoint,
            node_id=NODE_A,
            next_sequence=7,
            source="authenticated_command_response",
            observed_at="2026-08-26T15:00:02+00:00",
        )
        stream.write(
            json.dumps(
                {
                    "type": "pairing_tx_status",
                    "node_id": NODE_A,
                    "command_id": command["command_id"],
                    "profile": "htv405_auto_candidate_v1",
                    "state": "armed",
                    "completed_steps": 1,
                    "step_count": 18,
                    "factory_endpoint": "14a98013",
                    "paired_endpoint": valve_endpoint,
                    "tx_armed": True,
                }
            ).encode()
            + b"\n"
        )
        deadline = time.monotonic() + 2
        while self.gateway.nodes()[0].get("pairing_completed_steps") != 1:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)

        self.gateway.observe_rf_frame(
            frame=valve_frame,
            state={
                "rf_endpoint_a": controller_endpoint,
                "rf_endpoint_b": valve_endpoint,
                "rf_receiver_id": "local-sdr",
            },
        )

        registration = self.gateway._store.valve_registry()[0]
        self.assertEqual(7, registration["control_next_sequence"])
        self.assertEqual(
            "counter_synchronized:authenticated_command_response",
            registration["control_last_result"],
        )
        self.assertEqual(
            "valve_pairing_completed", self.gateway.pairing()["stage"]
        )
        stream.close()
        connection.close()

    def test_valve_confirmation_requires_the_active_controller_identity(self) -> None:
        connection, stream, _response = self._connect(
            NODE_A,
            TOKEN_A,
            protocol_version=2,
            capabilities=[
                "rx",
                "sensor_pairing_tx",
                "valve_pairing_tx_candidate",
                "configurable_rf_controller_identity",
            ],
        )
        self.gateway.start_pairing(
            120,
            node_id=NODE_A,
            profile_id="htv405_auto_candidate_v1",
            factory_endpoint="14a98013",
        )
        command = json.loads(stream.readline())
        stream.write(
            json.dumps(
                {
                    "type": "pairing_tx_status",
                    "node_id": NODE_A,
                    "command_id": command["command_id"],
                    "profile": "htv405_auto_candidate_v1",
                    "state": "armed",
                    "completed_steps": 1,
                    "step_count": 18,
                    "factory_endpoint": "14a98013",
                    "paired_endpoint": "94a98013",
                    "tx_armed": True,
                }
            ).encode()
            + b"\n"
        )
        deadline = time.monotonic() + 2
        while self.gateway.nodes()[0].get("pairing_completed_steps") != 1:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)

        stock_frame = build_htv405_close_frame(
            ValveLink(
                controller_endpoint=bytes.fromhex("b9840280"),
                valve_endpoint=bytes.fromhex("94a98013"),
            ),
            sequence=11,
            zone=1,
            selector=0x05,
            repeat=False,
            residue=0xC713,
        ).hex()
        self.gateway.observe_rf_frame(
            frame=stock_frame,
            state={
                "rf_endpoint_a": "b9840280",
                "rf_endpoint_b": "94a98013",
                "rf_receiver_id": "local-sdr",
            },
        )
        self.assertIsNone(self.gateway.pairing()["completed_endpoint"])
        self.assertEqual([], self.gateway._store.valve_registry())

        local_route = self.gateway.rf_identity.controller_endpoint
        local_frame = build_htv405_close_frame(
            ValveLink(
                controller_endpoint=bytes.fromhex(local_route),
                valve_endpoint=bytes.fromhex("94a98013"),
            ),
            sequence=11,
            zone=1,
            selector=0x05,
            repeat=False,
            residue=0xC713,
        ).hex()
        self.gateway.observe_rf_frame(
            frame=local_frame,
            state={
                "rf_endpoint_a": local_route,
                "rf_endpoint_b": "94a98013",
                "rf_receiver_id": "local-sdr",
            },
        )
        self.assertEqual(
            "94a98013", self.gateway.pairing()["completed_endpoint"]
        )
        self.assertEqual(1, len(self.gateway._store.valve_registry()))
        self.gateway.stop_pairing()
        cancel = json.loads(stream.readline())
        self.assertEqual("pairing_cancel", cancel["type"])
        stream.close()
        connection.close()

    def test_htv145_pairing_probe_requires_its_distinct_capability(self) -> None:
        connection, stream, _response = self._connect(
            NODE_A,
            TOKEN_A,
            protocol_version=2,
            capabilities=[
                "rx",
                "sensor_pairing_tx",
                "htv145_pairing_tx_candidate",
            ],
        )
        started = self.gateway.start_pairing(
            120,
            node_id=NODE_A,
            profile_id="htv145_auto_candidate_v1",
            factory_endpoint="342d008f",
            valve_route="b9840280",
            companion_endpoint="39840280",
        )
        self.assertEqual(
            "htv145_auto_candidate_v1", started["active_profile_id"]
        )
        command = json.loads(stream.readline())
        self.assertEqual("htv145_auto_candidate_v1", command["profile"])
        self.assertEqual("342d008f", command["factory_endpoint"])
        self.assertEqual("b9840280", command["valve_route"])
        self.assertEqual("39840280", command["companion_endpoint"])
        self.assertEqual(97_154, command["frequency_offset_hz"])
        self.assertNotIn("known_rejoin", command)
        stream.close()
        connection.close()

    def test_old_node_firmware_rejects_generated_identity_pairing(self) -> None:
        connection, stream, _response = self._connect(
            NODE_A,
            TOKEN_A,
            protocol_version=2,
            capabilities=["rx", "sensor_pairing_tx"],
        )
        with self.assertRaisesRegex(ValueError, "does not support"):
            self.gateway.start_pairing(120, node_id=NODE_A)
        self.assertFalse(self.gateway.pairing()["active"])
        stream.close()
        connection.close()

    def test_v2_node_accepts_bounded_known_valve_rejoin(self) -> None:
        connection, stream, _response = self._connect(
            NODE_A,
            TOKEN_A,
            protocol_version=2,
            capabilities=[
                "rx",
                "sensor_pairing_tx",
                "valve_pairing_tx_candidate",
            ],
        )
        started = self.gateway.start_pairing(
            120,
            node_id=NODE_A,
            profile_id="htv405_auto_candidate_v1",
            factory_endpoint="14a98013",
            valve_route="b9840280",
            companion_endpoint="39840280",
            known_rejoin=True,
        )
        self.assertEqual(
            "htv405_auto_candidate_v1", started["active_profile_id"]
        )
        command = json.loads(stream.readline())
        self.assertEqual("pairing_start", command["type"])
        self.assertTrue(command["known_rejoin"])
        self.assertEqual("14a98013", command["factory_endpoint"])
        self.assertEqual("b9840280", command["valve_route"])
        self.assertEqual("39840280", command["companion_endpoint"])
        self.assertEqual(120, command["duration_seconds"])
        stream.close()
        connection.close()

    def test_existing_valve_link_does_not_complete_new_pairing_session(self) -> None:
        self.assertIsNotNone(
            self.gateway.register_observed_htv405_link(
                controller_endpoint="b9840280",
                valve_endpoint="94a98013",
                frame=build_htv405_close_frame(
                    ValveLink(
                        controller_endpoint=bytes.fromhex("b9840280"),
                        valve_endpoint=bytes.fromhex("94a98013"),
                    ),
                    sequence=10,
                    zone=1,
                    selector=0x05,
                    repeat=False,
                    residue=0xC713,
                ).hex(),
                observed_at="2026-08-19T16:48:32+00:00",
            )
        )
        connection, stream, _response = self._connect(
            NODE_A,
            TOKEN_A,
            protocol_version=2,
            capabilities=[
                "rx",
                "sensor_pairing_tx",
                "valve_pairing_tx_candidate",
            ],
        )
        started = self.gateway.start_pairing(
            120,
            node_id=NODE_A,
            profile_id="htv405_auto_candidate_v1",
            factory_endpoint="14a98013",
            valve_route="b9840280",
            companion_endpoint="39840280",
        )
        command = json.loads(stream.readline())
        pre_reply_frame = build_htv405_close_frame(
            ValveLink(
                controller_endpoint=bytes.fromhex("b9840280"),
                valve_endpoint=bytes.fromhex("94a98013"),
            ),
            sequence=10,
            zone=1,
            selector=0x05,
            repeat=False,
            residue=0xC713,
        ).hex()
        self.gateway.observe_rf_frame(
            frame=pre_reply_frame,
            state={
                "rf_endpoint_a": "b9840280",
                "rf_endpoint_b": "94a98013",
                "rf_receiver_id": "local-sdr",
            },
        )
        self.assertNotEqual(
            "valve_pairing_completed", self.gateway.pairing()["stage"]
        )
        stream.write(
            json.dumps(
                {
                    "type": "pairing_tx_status",
                    "node_id": NODE_A,
                    "command_id": command["command_id"],
                    "profile": "htv405_auto_candidate_v1",
                    "state": "armed",
                    "completed_steps": 1,
                    "step_count": 18,
                    "factory_endpoint": "14a98013",
                    "paired_endpoint": "94a98013",
                    "tx_armed": True,
                }
            ).encode()
            + b"\n"
        )
        deadline = time.monotonic() + 2
        while True:
            progress = self.gateway.pairing()
            if progress.get("stage") == "pairing_exchange_in_progress":
                break
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        self.assertIsNone(progress["completed_endpoint"])
        self.assertNotEqual("valve_pairing_completed", progress["stage"])
        post_reply_frame = build_htv405_close_frame(
            ValveLink(
                controller_endpoint=bytes.fromhex("b9840280"),
                valve_endpoint=bytes.fromhex("94a98013"),
            ),
            sequence=11,
            zone=1,
            selector=0x05,
            repeat=False,
            residue=0xC713,
        ).hex()
        self.gateway.observe_rf_frame(
            frame=post_reply_frame,
            state={
                "rf_endpoint_a": "b9840280",
                "rf_endpoint_b": "94a98013",
                "rf_receiver_id": "local-sdr",
            },
        )
        awaiting_exchange = self.gateway.pairing()
        self.assertEqual(
            "valve_pairing_completed", awaiting_exchange["stage"]
        )
        self.assertEqual(
            "94a98013", awaiting_exchange["completed_endpoint"]
        )
        self.assertEqual(
            "local-sdr", awaiting_exchange["valve_confirmation_receiver"]
        )
        stream.write(
            json.dumps(
                {
                    "type": "pairing_tx_status",
                    "node_id": NODE_A,
                    "command_id": command["command_id"],
                    "profile": "htv405_auto_candidate_v1",
                    "state": "completed",
                    "completed_steps": 18,
                    "step_count": 18,
                    "factory_endpoint": "14a98013",
                    "paired_endpoint": "94a98013",
                    "tx_armed": False,
                }
            ).encode()
            + b"\n"
        )
        deadline = time.monotonic() + 2
        while True:
            completed = self.gateway.pairing()
            if completed.get("stage") == "valve_pairing_completed":
                break
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        self.assertEqual("valve_pairing_completed", completed["stage"])
        self.assertEqual("94a98013", completed["completed_endpoint"])
        self.assertEqual(
            "local-sdr", completed["valve_confirmation_receiver"]
        )
        self.assertIsNotNone(completed["valve_confirmation_observed_at"])
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

    def test_v2_rf_maintenance_is_bounded_observable_and_rebootable(self) -> None:
        connection, stream, response = self._connect(
            NODE_A,
            TOKEN_A,
            protocol_version=2,
            capabilities=[
                "rx",
                "sensor_pairing_tx",
                "rf_maintenance",
                "node_reboot",
            ],
        )
        self.assertEqual("node_authenticated", response["type"])

        requested = self.gateway.set_radio_node_rf_mode(
            NODE_A, "receive_only", 900
        )
        command = json.loads(stream.readline())
        self.assertEqual("rf_mode_set", command["type"])
        self.assertEqual("receive_only", command["mode"])
        self.assertEqual(900, command["duration_seconds"])
        self.assertEqual(requested["command_id"], command["command_id"])
        stream.write(
            json.dumps(
                {
                    "type": "rf_maintenance_status",
                    "node_id": NODE_A,
                    "command_id": command["command_id"],
                    "requested_mode": "receive_only",
                    "effective_mode": "receive_only",
                    "remaining_seconds": 899,
                    "changed_uptime_ms": 12_000,
                    "blocked_transmit_count": 2,
                    "rejected_command_count": 1,
                    "reboot_pending": False,
                    "detail": "receive_only_started",
                }
            ).encode()
            + b"\n"
        )
        deadline = time.monotonic() + 2
        while self.gateway.nodes()[0].get("rf_mode") != "receive_only":
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        node = self.gateway.nodes()[0]
        self.assertEqual(899, node["rf_mode_remaining_seconds"])
        self.assertEqual(2, node["rf_blocked_transmit_count"])
        self.assertEqual(1, node["rf_rejected_command_count"])
        first_changed_at = node["rf_mode_changed_at"]
        stream.write(
            json.dumps(
                {
                    "type": "rf_maintenance_status",
                    "node_id": NODE_A,
                    "requested_mode": "receive_only",
                    "effective_mode": "receive_only",
                    "remaining_seconds": 898,
                    "changed_uptime_ms": 12_000,
                    "blocked_transmit_count": 2,
                    "rejected_command_count": 1,
                    "reboot_pending": False,
                    "detail": "status_replay",
                }
            ).encode()
            + b"\n"
        )
        deadline = time.monotonic() + 2
        while self.gateway.nodes()[0].get("rf_mode_remaining_seconds") != 898:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        self.assertEqual(
            first_changed_at, self.gateway.nodes()[0]["rf_mode_changed_at"]
        )
        readiness = self.gateway.radio_node_capture_readiness(60)
        self.assertFalse(readiness["ready"])
        self.assertEqual(NODE_B, readiness["blockers"][0]["node_id"])
        self.assertEqual("offline", readiness["blockers"][0]["reason"])
        self.gateway.update_node(
            NODE_B,
            connected=True,
            authenticated=True,
            rf_mode="receive_only",
            rf_mode_remaining_seconds=899,
        )
        self.assertTrue(
            self.gateway.radio_node_capture_readiness(60)["ready"]
        )

        reboot = self.gateway.reboot_radio_node(NODE_A)
        reboot_command = json.loads(stream.readline())
        self.assertEqual("node_reboot", reboot_command["type"])
        self.assertEqual(reboot["command_id"], reboot_command["command_id"])
        self.assertEqual("normal", reboot["rf_mode_after_reboot"])
        self.assertTrue(self.gateway.nodes()[0]["node_reboot_pending"])
        stream.close()
        connection.close()

        replacement, replacement_stream, _ = self._connect(
            NODE_A,
            TOKEN_A,
            protocol_version=2,
            capabilities=[
                "rx",
                "sensor_pairing_tx",
                "rf_maintenance",
                "node_reboot",
            ],
        )
        deadline = time.monotonic() + 2
        while self.gateway.nodes()[0].get("node_last_reboot_result") != (
            "reconnected"
        ):
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        reconnected_node = self.gateway.nodes()[0]
        self.assertFalse(reconnected_node["node_reboot_pending"])
        self.assertIsNotNone(reconnected_node["node_last_reboot_at"])
        replacement_stream.close()
        replacement.close()

    def test_rf_maintenance_rejects_invalid_duration_and_missing_capability(
        self,
    ) -> None:
        connection, stream, _ = self._connect(
            NODE_A, TOKEN_A, protocol_version=2
        )
        with self.assertRaisesRegex(ValueError, "between 60 and 3600"):
            self.gateway.set_radio_node_rf_mode(
                NODE_A, "receive_only", 59
            )
        with self.assertRaisesRegex(ValueError, "RF maintenance"):
            self.gateway.set_radio_node_rf_mode(
                NODE_A, "receive_only", 900
            )
        with self.assertRaisesRegex(ValueError, "remote reboot"):
            self.gateway.reboot_radio_node(NODE_A)
        stream.close()
        connection.close()

    def test_v2_routine_ack_candidate_capability_authenticates(self) -> None:
        connection, stream, response = self._connect(
            NODE_A,
            TOKEN_A,
            protocol_version=2,
            capabilities=[
                "rx",
                "sensor_pairing_tx",
                "identify",
                "routine_sensor_ack_tx",
                "htv405_routine_ack_tx",
            ],
        )
        self.assertEqual("node_authenticated", response["type"])
        node = self.gateway.nodes()[0]
        self.assertIn("routine_sensor_ack_tx", node["capabilities"])
        configure = {
            "type": "routine_ack_configure",
            "command_id": "34" * 16,
            "paired_endpoint": "9bce0024",
            "assigned_channel": 4,
            "frequency_offset_hz": 45_000,
            "power_dbm": 10,
            "invert": False,
        }
        self.server.send_command(NODE_A, configure)
        self.assertEqual(configure, json.loads(stream.readline()))
        revoke = {
            "type": "routine_ack_revoke",
            "command_id": "56" * 16,
            "paired_endpoint": "9bce0024",
        }
        self.server.send_command(NODE_A, revoke)
        self.assertEqual(revoke, json.loads(stream.readline()))
        valve_configure = {
            "type": "htv405_routine_ack_configure",
            "command_id": "78" * 16,
            "controller_endpoint": "ee86de80",
            "valve_endpoint": "94a98013",
            "companion_endpoint": "6e86de80",
            "frequency_offset_hz": 97_154,
            "power_dbm": 10,
            "invert": False,
        }
        self.server.send_command(NODE_A, valve_configure)
        self.assertEqual(valve_configure, json.loads(stream.readline()))
        valve_revoke = {
            "type": "htv405_routine_ack_revoke",
            "command_id": "9a" * 16,
            "valve_endpoint": "94a98013",
        }
        self.server.send_command(NODE_A, valve_revoke)
        self.assertEqual(valve_revoke, json.loads(stream.readline()))
        stream.close()
        connection.close()

    def test_v2_bench_valve_control_commands_require_explicit_capability(
        self,
    ) -> None:
        connection, stream, response = self._connect(
            NODE_A,
            TOKEN_A,
            protocol_version=2,
            capabilities=[
                "rx",
                "sensor_pairing_tx",
                "valve_control_tx_candidate",
            ],
        )
        self.assertEqual("node_authenticated", response["type"])
        commands = [
            {
                "type": "valve_control_configure",
                "command_id": "61" * 16,
                "controller_endpoint": "b9840280",
                "valve_endpoint": "94a98013",
                "companion_endpoint": "39840280",
                "selector": 0x05,
                "frequency_offset_hz": 97_154,
            },
            {
                "type": "valve_control_sync",
                "command_id": "62" * 16,
                "next_sequence": 7,
            },
            {
                "type": "valve_control_close",
                "command_id": "63" * 16,
                "zone": 1,
                "expected_sequence": 7,
            },
        ]
        for command in commands:
            self.server.send_command(NODE_A, command)
            self.assertEqual(command, json.loads(stream.readline()))
        stream.close()
        connection.close()

        legacy_connection, legacy_stream, _ = self._connect(
            NODE_A, TOKEN_A, protocol_version=2
        )
        with self.assertRaisesRegex(ValueError, "valve_control_tx_candidate"):
            self.server.send_command(NODE_A, commands[-1])
        legacy_stream.close()
        legacy_connection.close()

    def test_htv145_candidate_commands_require_distinct_capability(self) -> None:
        connection, stream, response = self._connect(
            NODE_A,
            TOKEN_A,
            protocol_version=2,
            capabilities=[
                "rx",
                "sensor_pairing_tx",
                "htv145_control_tx_candidate",
            ],
        )
        self.assertEqual("node_authenticated", response["type"])
        commands = [
            {
                "type": "htv145_control_configure",
                "command_id": "71" * 16,
                "controller_endpoint": "b42d008f",
                "valve_endpoint": "b9840280",
                "center_hz": 433_920_000,
                "power_dbm": 10,
                "invert": False,
                "trailer_residual": 0xC713,
            },
            {
                "type": "htv145_control_sync",
                "command_id": "72" * 16,
                "next_sequence": 0x8D,
            },
            {
                "type": "htv145_control_open",
                "command_id": "73" * 16,
                "expected_sequence": 0x8D,
                "duration_seconds": 600,
            },
        ]
        for command in commands:
            self.server.send_command(NODE_A, command)
            self.assertEqual(command, json.loads(stream.readline()))
        stream.close()
        connection.close()

        legacy_connection, legacy_stream, _ = self._connect(
            NODE_A, TOKEN_A, protocol_version=2
        )
        with self.assertRaisesRegex(
            ValueError, "htv145_control_tx_candidate"
        ):
            self.server.send_command(NODE_A, commands[-1])
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

    def test_ota_trial_command_requires_explicit_candidate_capability(self) -> None:
        connection, stream, _ = self._connect(
            NODE_A,
            TOKEN_A,
            protocol_version=2,
            capabilities=[
                "rx",
                "sensor_pairing_tx",
                "firmware_update_trial",
            ],
        )
        command = {
            "type": "firmware_update_start",
            "command_id": "12" * 16,
            "url": "http://192.0.2.1:8787/firmware/test.bin",
            "version": "0.9.0-test.2",
            "size_bytes": 900_000,
            "sha256": "ab" * 32,
        }
        self.server.send_command(NODE_A, command)
        self.assertEqual(command, json.loads(stream.readline()))
        stream.close()
        connection.close()

        connection, stream, _ = self._connect(
            NODE_B,
            TOKEN_B,
            protocol_version=2,
            capabilities=["rx", "sensor_pairing_tx"],
        )
        with self.assertRaisesRegex(ValueError, "firmware_update_trial"):
            self.server.send_command(NODE_B, command)
        stream.close()
        connection.close()

    def test_authenticated_replacement_supersedes_stale_session(self) -> None:
        first_connection, first, first_response = self._connect(NODE_A, TOKEN_A)
        second_connection, second, second_response = self._connect(NODE_A, TOKEN_A)
        self.assertEqual("node_authenticated", first_response["type"])
        self.assertEqual("node_authenticated", second_response["type"])
        deadline = time.monotonic() + 2
        while self.gateway.nodes()[0].get("connected") is not True:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        first_connection.settimeout(1)
        self.assertEqual(b"", first.readline())
        self.assertTrue(self.gateway.nodes()[0]["connected"])
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
