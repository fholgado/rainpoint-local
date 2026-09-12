"""Public discovery interfaces must not infer hardware from friendly names."""
import unittest
import tempfile
from pathlib import Path

from tests.test_api_models import api_models
from rainpointd.device_catalog import DeviceCatalog, SensorDefinition, ValveDefinition
from rainpointd.gateway import Gateway
from rainpointd.product_identity import hcs02x_identity, GENERIC_HCS02X_MODEL


class DiscoveryContractTest(unittest.TestCase):
    def test_current_gateway_catalog_parses_in_ha_without_installation(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        gateway = Gateway(storage_path=str(Path(temporary.name) / "registry.sqlite3"))
        self.addCleanup(gateway.close)
        profiles = api_models.pairing_profiles(gateway.pairing())
        self.assertEqual({"HCS026FRF", "HTV145FRF", "HTV405FRF"}, {p.model for p in profiles})
        self.assertTrue(all(p.automatic_discovery and p.user_pairing_supported for p in profiles))
        self.assertEqual([], gateway.devices())
        self.assertEqual([], gateway.nodes())

    def test_family_code_is_not_exact_model_or_control_permission(self):
        for decoded in ({}, {"product_code": 0x48}, {"product_code": 0x48, "model_code": 0xFFFF},
                        {"product_code": 0x1F, "model_code": 0x013D}):
            with self.subTest(decoded=decoded):
                identity = hcs02x_identity(decoded)
                self.assertEqual(GENERIC_HCS02X_MODEL, identity.model)
                self.assertFalse(identity.exact_model)
                self.assertNotIn("water_control", identity.catalog_capabilities)
        self.assertEqual("rf_identifier_conflict", hcs02x_identity(
            {"product_code": 0x1F, "model_code": 0x013D}, trusted_model="HCS026FRF").source)

    def test_names_cannot_change_routes_or_zone_topology(self):
        for name in ("HTV405FRF", "Left Bed", "Valve 4 zones", "HCS026FRF", ""):
            catalog = DeviceCatalog(
                sensors=(SensorDefinition("91abcd24", "soil", name),),
                valves=(ValveDefinition("81234580", "91abcd8f", "valve", name),))
            self.assertEqual("soil", catalog.sensor("91ABCD24").device_id)
            self.assertEqual("valve", catalog.valve_link("91ABCD8F", "81234580").device_id)
            self.assertEqual((), api_models.multi_zone_numbers({"name": name, "model": "HTV145FRF"}))
            self.assertEqual((1, 2, 3, 4), api_models.multi_zone_numbers({"name": name, "model": "HTV405FRF"}))


if __name__ == "__main__":
    unittest.main()
