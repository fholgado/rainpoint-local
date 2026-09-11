"""Snapshot-driven notifications are observations, never actuator commands."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock
from unittest.mock import patch
import types

PATH = Path(__file__).resolve().parents[1] / "custom_components/rainpoint_local/notifications.py"
SPEC = importlib.util.spec_from_file_location("watering_notifications", PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class WateringNotificationTest(unittest.TestCase):
    def setUp(self):
        self.publish = Mock()
        self.reporter = module.WateringNotifications("entry", self.publish)

    def snapshot(self, watering=False, **state):
        self.reporter.observe({"valve": {"model": "HTV405FRF", "name": "Garden",
            "state": {"is_watering": watering, **state}}})

    def test_requested_21_minutes_not_default_20_and_no_duplicates(self):
        self.snapshot()
        values = {"active_zone": 2, "rf_control_transaction_id": "run1",
            "rf_control_transaction_state": "watering_confirmed",
            "rf_control_transaction_duration_seconds": 1260}
        self.snapshot(True, **values)
        self.assertIn("21 minutes", self.publish.call_args.args[0])
        self.assertIn("zone 2", self.publish.call_args.args[0])
        self.snapshot(True, **values)
        self.assertEqual(1, self.publish.call_count)
        self.snapshot(False, **values)
        self.assertEqual(2, self.publish.call_count)
        self.assertIn("reported that watering stopped", self.publish.call_args.args[0])
        self.assertEqual("rainpoint_local_entry_valve_run", self.publish.call_args.kwargs["notification_id"])

    def test_pending_failed_unknown_and_stale_idle_never_claim_open_or_stop(self):
        self.snapshot(None)
        self.snapshot(False, rf_control_transaction_state="waiting_for_confirmation")
        self.publish.assert_not_called()
        self.snapshot(None, rf_control_transaction_state="failed", rf_control_transaction_id="bad")
        self.assertEqual(1, self.publish.call_count)
        self.assertIn("may have flowed", self.publish.call_args.args[0])
        self.snapshot(False, rf_control_transaction_state="failed", rf_control_transaction_id="bad")
        self.assertEqual(1, self.publish.call_count)

    def test_unknown_during_run_waits_for_observed_idle(self):
        self.snapshot(True)
        self.publish.reset_mock()
        self.snapshot(None)
        self.publish.assert_not_called()
        self.snapshot(False)
        self.assertIn("watering stopped", self.publish.call_args.kwargs["title"])

    def test_failure_recurs_only_for_new_transaction_and_recovery_does_not_dismiss(self):
        self.snapshot(False, rf_control_transaction_state="failed", rf_control_transaction_id="bad1")
        self.snapshot(False)
        self.snapshot(False, rf_control_transaction_state="failed", rf_control_transaction_id="bad1")
        self.assertEqual(1, self.publish.call_count)
        self.snapshot(False, rf_control_transaction_state="failed", rf_control_transaction_id="bad2")
        self.assertEqual(2, self.publish.call_count)
        self.assertEqual("rainpoint_local_entry_valve_problem", self.publish.call_args.kwargs["notification_id"])

    def test_overdue_and_local_request_failure_need_no_mobile_configuration(self):
        self.snapshot(True, rf_control_overdue=True)
        count = self.publish.call_count
        self.snapshot(True, rf_control_overdue=True)
        self.assertEqual(count, self.publish.call_count)
        self.reporter.command_failed("valve", "Garden", "close")
        self.assertIn("close request", self.publish.call_args.args[0])
        self.assertIn("does not confirm", self.publish.call_args.args[0])

    def test_new_manual_run_does_not_reuse_old_requested_duration(self):
        values = {"rf_control_transaction_id": "old", "rf_control_transaction_state": "confirmed",
                  "rf_control_transaction_duration_seconds": 1260}
        self.snapshot(True, **values)
        self.snapshot(False, **values)
        self.snapshot(True, **values)
        self.assertNotIn("Requested duration", self.publish.call_args.args[0])

    def test_multiple_gateways_and_unknown_devices_are_isolated(self):
        self.reporter.observe({"sensor": {"model": "HCS026FRF", "state": {"is_watering": True}}})
        self.publish.assert_not_called()
        self.snapshot(True)
        other = Mock()
        module.WateringNotifications("other", other).observe({"valve": {
            "model": "HTV145FRF", "state": {"is_watering": True}}})
        self.assertNotEqual(self.publish.call_args.kwargs["notification_id"], other.call_args.kwargs["notification_id"])

    def test_single_zone_confirmed_request_duration_is_used(self):
        self.reporter.observe({"valve": {"model": "HTV145FRF", "state": {
            "is_watering": True, "rf_control_transaction_id": "one",
            "rf_control_transaction_action": "open", "rf_control_transaction_state": "confirmed",
            "rf_control_transaction_duration_seconds": 120}}})
        self.assertIn("2 minutes", self.publish.call_args.args[0])

    def test_ha_setup_subscribes_by_default_and_emits_mobile_opt_in_event(self):
        persistent = types.SimpleNamespace(async_create=Mock())
        hass = types.SimpleNamespace(bus=types.SimpleNamespace(async_fire=Mock()))
        entry = types.SimpleNamespace(entry_id="entry", async_on_unload=Mock())
        coordinator = types.SimpleNamespace(data={}, last_update_success=True,
            async_add_listener=Mock(return_value="unsubscribe"))
        with patch.dict("sys.modules", {
            "homeassistant.components": types.SimpleNamespace(persistent_notification=persistent),
            "homeassistant.core": types.SimpleNamespace(callback=lambda fn: fn),
        }):
            module.setup_notifications(hass, entry, coordinator)
        entry.async_on_unload.assert_called_once_with("unsubscribe")
        updated = coordinator.async_add_listener.call_args.args[0]
        coordinator.data = {"v": {"name": "Valve", "model": "HTV145FRF",
            "state": {"is_watering": True}}}
        coordinator.last_update_success = False
        updated()
        persistent.async_create.assert_not_called()
        coordinator.last_update_success = True
        updated()
        persistent.async_create.assert_called_once()
        self.assertIs(hass, persistent.async_create.call_args.args[0])
        self.assertEqual("rainpoint_local_watering_notification", hass.bus.async_fire.call_args.args[0])
        self.assertIn("message", hass.bus.async_fire.call_args.args[1])
        updated()
        self.assertEqual(1, persistent.async_create.call_count)

    def test_local_failure_uses_device_name_without_exception_payload(self):
        entity = types.SimpleNamespace(device_id="valve", coordinator=types.SimpleNamespace(
            notifications=self.reporter, data={"valve": {"name": "Garden"}}))
        module.notify_command_failure(entity, "close")
        self.assertEqual("Garden: watering command failed", self.publish.call_args.kwargs["title"])


if __name__ == "__main__":
    unittest.main()
