import types
import unittest
import asyncio
from unittest.mock import AsyncMock, Mock

from tests.test_integration_migration import device_for_entry, _integration_function, PACKAGE


class DeviceRegistryCompatTest(unittest.TestCase):
    def test_modern_lookup_is_scoped_and_never_calls_legacy(self):
        identifier = ("rainpoint_local", "same-local-id")
        first, second = object(), object()
        lookup = Mock(side_effect=lambda key, entry: {"first": first, "second": second}.get(entry))
        registry = types.SimpleNamespace(async_get_device_by_identifier=lookup,
            async_get_device=Mock(side_effect=AssertionError("deprecated call")))
        self.assertIs(first, device_for_entry(registry, "first", identifier))
        self.assertIs(second, device_for_entry(registry, "second", identifier))
        self.assertIsNone(device_for_entry(registry, "other", identifier))
        lookup.assert_called_with(identifier, "other")

    def test_minimum_ha_fallback_checks_ownership(self):
        device = types.SimpleNamespace(config_entries={"first"})
        registry = types.SimpleNamespace(async_get_device=Mock(return_value=device))
        identifier = ("rainpoint_local", "same-local-id")
        self.assertIs(device, device_for_entry(registry, "first", identifier))
        self.assertIsNone(device_for_entry(registry, "second", identifier))
        registry.async_get_device.return_value = None
        self.assertIsNone(device_for_entry(registry, "first", identifier))

    def test_pairing_completion_updates_only_its_entry_device(self):
        device = types.SimpleNamespace(id="owned-device", name_by_user=None)
        registry = types.SimpleNamespace(async_get_device_by_identifier=Mock(return_value=device),
            async_update_device=Mock(), async_get_device=Mock(side_effect=AssertionError("unscoped lookup")))
        callback = _integration_function("config_flow.py", "async_step_device_details", {
            "DOMAIN": "rainpoint_local", "_selected_area": lambda *_: ("area-id", "Garden"),
            "dr": types.SimpleNamespace(async_get=lambda _: registry),
        }, classname="RainPointLocalOptionsFlow")
        client = types.SimpleNamespace(complete_pairing=AsyncMock(return_value={"device": {"device_id": "local-id"}}))
        flow = types.SimpleNamespace(_paired_endpoint="91234524", _token="test-only",
            _entry=types.SimpleNamespace(entry_id="owner-entry"), _pairing_profile=None,
            hass=types.SimpleNamespace(data={}), _client=lambda: client,
            async_create_entry=Mock(return_value={"type": "create_entry"}))
        self.assertEqual({"type": "create_entry"}, asyncio.run(callback(flow, {"name": "New name"})))
        registry.async_get_device_by_identifier.assert_called_once_with(("rainpoint_local", "local-id"), "owner-entry")
        registry.async_update_device.assert_called_once_with("owned-device", name="New name", name_by_user=None, area_id="area-id")

    def test_legacy_lookup_is_confined_to_compatibility_helper(self):
        for path in PACKAGE.glob("*.py"):
            if path.name != "registry.py":
                self.assertNotIn(".async_get_device(", path.read_text(), str(path))


if __name__ == "__main__":
    unittest.main()
