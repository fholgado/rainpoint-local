"""Recovery must preserve the operator-selected outlet through the real API."""
from datetime import datetime, timedelta
import binascii
from urllib.error import HTTPError
import unittest

from tests import test_rainpointd as fixtures


class RecoveryOutletTest(unittest.TestCase):
    NODE_ID = fixtures.ValveControlHTTPAPITest.NODE_ID
    SECOND_NODE_ID = fixtures.ValveControlHTTPAPITest.SECOND_NODE_ID
    DEVICE_ID = fixtures.ValveControlHTTPAPITest.DEVICE_ID
    VALVE_ENDPOINT = fixtures.ValveControlHTTPAPITest.VALVE_ENDPOINT
    setUp = fixtures.ValveControlHTTPAPITest.setUp
    tearDown = fixtures.ValveControlHTTPAPITest.tearDown
    post_json = fixtures.ValveControlHTTPAPITest.post_json

    def break_counter(self):
        gateway = self.server.gateway
        gateway._store.confirm_valve_control_response(
            valve_endpoint=self.VALVE_ENDPOINT, node_id=self.NODE_ID,
            sequence=6, next_sequence=6, zone=2, watering=False,
            center_hz=433_518_527, observed_at="2026-08-24T20:00:02+00:00", frame="00")
        pending = gateway.request_htv405_control(
            device_id=self.DEVICE_ID, action="open", zone=2,
            duration_seconds=60, now=datetime.fromisoformat("2026-08-24T20:00:20+00:00"))
        gateway._store.fail_htv405_command(
            valve_endpoint=self.VALVE_ENDPOINT, node_id=self.NODE_ID,
            command_id=pending["command_id"],
            reason="gateway_command_response_timeout_counter_unsynchronized",
            observed_at="2026-08-24T20:00:22+00:00")
        self.commands.clear()

    def test_selected_outlet_is_persisted_and_sent_without_open(self):
        self.break_counter()
        result = self.post_json(
            f"/api/v1/devices/{self.DEVICE_ID}/valve/probe-idle-close", {"zone": 2})["control"]
        self.assertEqual(2, result["zone"])
        self.assertEqual("valve_control_close", self.commands[-1][1]["type"])
        self.assertEqual(2, self.commands[-1][1]["zone"])
        self.assertNotIn("duration_seconds", self.commands[-1][1])
        row = self.server.gateway._store.valve_registry()[0]
        self.assertEqual(2, row["control_pending_zone"])

    def test_timeout_retry_keeps_selected_outlet(self):
        self.break_counter()
        result = self.post_json(
            f"/api/v1/devices/{self.DEVICE_ID}/valve/probe-idle-close", {"zone": 2})["control"]
        gateway = self.server.gateway
        row = gateway._store.valve_registry()[0]
        failed_at = datetime.fromisoformat(row["control_pending_started_at"]) + timedelta(seconds=3)
        failed = gateway._store.fail_htv405_command(
            valve_endpoint=self.VALVE_ENDPOINT, node_id=self.NODE_ID,
            command_id=result["command_id"],
            reason="gateway_command_response_timeout_counter_unsynchronized",
            observed_at=failed_at.isoformat())
        self.assertEqual(2, failed["control_recovery_zone"])
        self.commands.clear()
        self.assertEqual(1, gateway.advance_htv405_idle_close_resync(
            device_id=self.DEVICE_ID, now=failed_at+timedelta(seconds=16)))
        self.assertEqual(2, self.commands[-1][1]["zone"])
        self.assertEqual(2, gateway._store.valve_registry()[0]["control_pending_zone"])

    def test_invalid_outlet_does_not_reserve_or_dispatch(self):
        self.break_counter()
        for zone in (0, 5, True, "2"):
            with self.subTest(zone=zone):
                with self.assertRaises(HTTPError) as error:
                    self.post_json(
                        f"/api/v1/devices/{self.DEVICE_ID}/valve/probe-idle-close", {"zone": zone})
                self.assertEqual(400, error.exception.code)
                error.exception.close()
        self.assertEqual([], self.commands)

    def test_authenticated_recovery_restores_morning_readiness(self):
        gateway = self.server.gateway
        gateway.update_node(self.NODE_ID, capabilities=["rx", "valve_control_tx_candidate", "htv405_bounded_sync_wait"])
        gateway.configure_htv405_morning_sync(
            device_id=self.DEVICE_ID, settings={"enabled": True, "timezone": "UTC"},
            now=datetime.fromisoformat("2026-08-24T20:00:03+00:00"))
        self.break_counter()
        gateway.request_htv405_idle_close_probe(
            device_id=self.DEVICE_ID, zone=2,
            now=datetime.fromisoformat("2026-08-24T20:00:37+00:00"))
        response = bytearray.fromhex(fixtures.ValveControlHTTPAPITest.HTV405_CLOSE_RESPONSE_SEQUENCE_0)
        residual = binascii.crc_hqx(response[:-2], 0) ^ int.from_bytes(response[-2:], "big")
        response[17] = (response[17] & 0x0f) | 0x20
        response[-2:] = (binascii.crc_hqx(response[:-2], 0) ^ residual).to_bytes(2, "big")
        accepted = gateway.observe_valve_control_air_response(
            self.NODE_ID, response.hex(),
            observed_at="2026-08-24T20:00:38+00:00")
        self.assertIsNotNone(accepted)
        status = gateway._morning_sync_status_locked(
            gateway._store.valve_registry()[0],
            datetime.fromisoformat("2026-08-24T20:00:39+00:00"))
        self.assertEqual("Ready", status["status"])
        self.assertEqual("2026-08-24", status["last_success_date"])
        before = len(self.commands)
        gateway._morning_sync_status_locked(gateway._store.valve_registry()[0],
            datetime.fromisoformat("2026-08-24T20:00:40+00:00"))
        self.assertEqual(before, len(self.commands))
        tomorrow = gateway._morning_sync_status_locked(gateway._store.valve_registry()[0],
            datetime.fromisoformat("2026-08-25T20:00:40+00:00"))
        self.assertEqual("Needs sync", tomorrow["status"])

    def test_later_external_command_is_not_overridden_by_old_recovery(self):
        self.test_authenticated_recovery_restores_morning_readiness()
        store = self.server.gateway._store
        row = store.valve_registry()[0]
        data = store.morning_sync(self.VALVE_ENDPOINT)
        data.update(ready=False, reason="external_control_observed",
            external_command_at="2026-08-24T20:00:41+00:00")
        store.save_morning_sync(self.VALVE_ENDPOINT, data)
        status = self.server.gateway._morning_sync_status_locked(row,
            datetime.fromisoformat("2026-08-24T20:00:42+00:00"))
        self.assertEqual("Needs sync", status["status"])
