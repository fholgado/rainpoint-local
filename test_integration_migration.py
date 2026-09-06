#!/usr/bin/env python3

from __future__ import annotations

import ast
import importlib.util
import sys
import types
import unittest
from unittest.mock import Mock, call
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
    function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    module = ast.parse("from __future__ import annotations")
    module.body.append(function)
    exec(compile(module, str(PACKAGE / filename), "exec"), namespace)
    return namespace[name]


class IntegrationMigrationTest(unittest.TestCase):
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
