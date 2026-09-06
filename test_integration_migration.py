#!/usr/bin/env python3

from __future__ import annotations

import ast
import importlib.util
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, call
from pathlib import Path

ROOT = Path(__file__).parent
PACKAGE = ROOT / "custom_components" / "rainpoint_local"

# Load the pure migration module without importing Home Assistant.
package = types.ModuleType("rainpoint_local")
package.__path__ = [str(PACKAGE)]
sys.modules.setdefault("rainpoint_local", package)
for module_name in ("const", "migration", "api_models"):
    spec = importlib.util.spec_from_file_location(
        f"rainpoint_local.{module_name}", PACKAGE / f"{module_name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

from rainpoint_local.migration import migrate_entry_payload
from rainpoint_local.api_models import multi_zone_numbers, unsupported_device_entity_ids


def _integration_function(filename, name, namespace):
    """Exercise the actual HA callback with registry/entity APIs stubbed."""
    tree = ast.parse((PACKAGE / filename).read_text())
    function = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    module = ast.parse("from __future__ import annotations")
    module.body.append(function)
    exec(compile(module, str(PACKAGE / filename), "exec"), namespace)
    return namespace[name]


class ValveCommandRefreshTest(unittest.IsolatedAsyncioTestCase):
    async def test_command_publishes_new_transaction_despite_refresh_cooldown(self):
        """Replay the old sync snapshot that caused a confirmed run to alert.

        HA's debounced request can return without fetching during its cooldown.
        The valve service must publish the authoritative post-command snapshot
        before returning, including when that snapshot is not yet confirmed.
        """
        for method, action in (("async_open_valve", "open_htv405_zone"),
                               ("async_close_valve", "close_htv405_zone")):
            for outcome in ("waiting_for_confirmation", "watering_confirmed", "failed"):
                with self.subTest(method=method, outcome=outcome):
                    old_id = "previous-synchronization"
                    snapshot = {"rf_control_start_available": True,
                                "rf_control_transaction_id": old_id,
                                "rf_control_transaction_state": "completed"}
                    gateway_snapshot = {**snapshot,
                                        "rf_control_transaction_id": "new-command",
                                        "rf_control_transaction_state": outcome}
                    async def refresh():
                        snapshot.clear()
                        snapshot.update(gateway_snapshot)
                    coordinator = types.SimpleNamespace(
                        htv405_run_minutes={("four", 1): 15},
                        client=types.SimpleNamespace(**{action: AsyncMock()}),
                        # A throttled request returns before the next refresh.
                        async_request_refresh=AsyncMock(),
                        async_refresh=AsyncMock(side_effect=refresh),
                    )
                    entity = types.SimpleNamespace(coordinator=coordinator,
                        decoded_state=snapshot, device_id="four", _zone=1, _token="test-token")
                    callback = _integration_function("valve.py", method, {
                        "HomeAssistantError": RuntimeError,
                        "RainPointLocalError": ValueError,
                        "DEFAULT_BOUNDED_RUN_MINUTES": 1,
                    })
                    await callback(entity)
                    # Run Now's five-second new-ID guard must not mistake the
                    # previous completed sync for this command's result.
                    self.assertNotEqual(old_id, snapshot["rf_control_transaction_id"])
                    self.assertEqual(outcome, snapshot["rf_control_transaction_state"])
                    coordinator.async_refresh.assert_awaited_once()
                    getattr(coordinator.client, action).assert_awaited_once()


class IntegrationMigrationTest(unittest.TestCase):
    def test_one_zone_counter_capability_creates_only_retained_restore_button(self):
        constructor = Mock()
        add = Mock()
        coordinator = types.SimpleNamespace(nodes={}, data={
            "one": {"capabilities": ["retained_counter_restore"]},
            "unqualified": {"capabilities": ["forget"]},
        })
        factory = _integration_function("button.py", "async_add_missing_entities", {
            "callback": lambda fn: fn, "known": set(), "coordinator": coordinator,
            "entry": types.SimpleNamespace(data={}, options={}), "CONF_TOKEN": "token",
            "RainPointRestoreRetainedCounterButton": constructor, "async_add_entities": add,
        })
        factory()
        constructor.assert_called_once_with(coordinator, "one", "")
        add.assert_called_once_with([constructor.return_value])
        factory()
        self.assertEqual(1, constructor.call_count)

    def test_known_sensor_details_use_ha_customizations_and_exact_identity(self):
        entry = types.SimpleNamespace(name_by_user="Right Bed", name="Old name", area_id="garden")
        registry = Mock()
        registry.async_get_device.return_value = entry
        areas = Mock()
        areas.async_get_area_by_name.return_value = types.SimpleNamespace(id="yard")
        resolve = _integration_function("config_flow.py", "_known_device_details", {
            "DOMAIN": "rainpoint_local",
            "dr": types.SimpleNamespace(async_get=lambda _: registry),
            "ar": types.SimpleNamespace(async_get=lambda _: areas),
        })
        devices = [{"device_id": "saved-sensor", "name": "Gateway name", "area": "Yard",
                    "state": {"rf_paired_endpoint": "12345624"}}]
        self.assertEqual({"name": "Right Bed", "area": "garden"}, resolve(None, devices, "12345624"))
        registry.async_get_device.assert_called_with(identifiers={("rainpoint_local", "saved-sensor")})
        self.assertEqual({}, resolve(None, devices, "99995624"))
        entry.area_id = None
        self.assertEqual({"name": "Right Bed"}, resolve(None, devices, "12345624"))
        registry.async_get_device.return_value = None
        self.assertEqual({"name": "Gateway name", "area": "yard"}, resolve(None, devices, "12345624"))

    def test_single_zone_factory_ignores_legacy_four_zone_keys(self):
        constructor = Mock()
        namespace = {name: constructor for name in (
            "RainPointWateringBinarySensor", "RainPointZoneWateringBinarySensor",
            "RainPointReportingBinarySensor", "RainPointControlStartAvailableBinarySensor",
        )}
        namespace["multi_zone_numbers"] = multi_zone_numbers
        factory = _integration_function("binary_sensor.py", "_entities_for_device", namespace)
        state = {"is_watering": False, **{f"zone_{z}_is_watering": None for z in range(1, 5)}}
        entities = factory(None, "single", {"model": "HTV145FRF", "state": state})
        self.assertEqual(["watering"], [key for key, _entity in entities])
        entities = factory(None, "four", {"model": "HTV405FRF", "state": state})
        self.assertEqual(5, len(entities))

    def test_registry_removes_only_unsupported_single_zone_entities(self):
        entity_registry = Mock()
        unique_ids = ["single_watering", "single_last_usage", "single_zone_1_watering",
                      "single_zone_4_watering", "four_zone_4_watering", "four_last_usage"]
        entries = [types.SimpleNamespace(unique_id=uid, entity_id=f"binary_sensor.{uid}",
                                         device_id=uid.split("_")[0], disabled_by=None)
                   for uid in unique_ids]
        registry_devices = [types.SimpleNamespace(id=uid, identifiers={("rainpoint_local", uid)})
                            for uid in ("single", "four")]
        namespace = {
            "DOMAIN": "rainpoint_local", "unsupported_device_entity_ids": unsupported_device_entity_ids,
            "dr": types.SimpleNamespace(async_get=lambda _h: object(), async_entries_for_config_entry=lambda *_: registry_devices),
            "er": types.SimpleNamespace(async_get=lambda _h: entity_registry, async_entries_for_config_entry=lambda *_: entries,
                                         RegistryEntryDisabler=types.SimpleNamespace(INTEGRATION="integration")),
        }
        reconcile = _integration_function("coordinator.py", "_async_reconcile_entity_registry", namespace)
        reconcile(types.SimpleNamespace(hass=None, config_entry_id="entry"), {"single", "four"},
                  {"single": {"model": "HTV145FRF"}, "four": {"model": "HTV405FRF"}})
        self.assertEqual([
            call("binary_sensor.single_zone_1_watering"),
            call("binary_sensor.single_zone_4_watering"),
            call("binary_sensor.four_last_usage"),
        ], entity_registry.async_remove.call_args_list)
        entity_registry.async_update_entity.assert_not_called()

    def test_v1_moves_management_token_from_options(self) -> None:
        version, data, options = migrate_entry_payload(
            1,
            {"host": " gateway.local ", "port": "8787"},
            {"registry_write_token": "secret", "unrelated": True},
        )
        self.assertEqual(2, version)
        self.assertEqual("gateway.local", data["host"])
        self.assertEqual(8787, data["port"])
        self.assertEqual("secret", data["registry_write_token"])
        self.assertEqual({"unrelated": True}, options)

    def test_current_payload_is_idempotent(self) -> None:
        original_data = {"host": "gateway.local", "port": 8787}
        original_options = {"unrelated": True}
        version, data, options = migrate_entry_payload(
            2, original_data, original_options
        )
        self.assertEqual((2, original_data, original_options), (version, data, options))


if __name__ == "__main__":
    unittest.main()
