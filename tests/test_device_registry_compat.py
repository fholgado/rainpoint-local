import types
import unittest
from unittest.mock import Mock

from tests.test_integration_migration import device_for_entry


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


if __name__ == "__main__":
    unittest.main()
