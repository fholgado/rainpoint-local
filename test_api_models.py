#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

MODULE = (
    Path(__file__).parent
    / "custom_components"
    / "rainpoint_local"
    / "api_models.py"
)
spec = importlib.util.spec_from_file_location("rainpoint_api_models", MODULE)
assert spec and spec.loader
api_models = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api_models
spec.loader.exec_module(api_models)


class APIModelsTest(unittest.TestCase):
    def test_gateway_metadata_parses_capability_contract(self) -> None:
        metadata = api_models.GatewayMetadata.from_payload(
            {
                "api_version": "v1",
                "gateway_id": "rainpoint-local",
                "capabilities": ["event_long_poll"],
                "latest_event_id": 42,
            }
        )
        self.assertEqual("rainpoint-local", metadata.gateway_id)
        self.assertEqual(frozenset({"event_long_poll"}), metadata.capabilities)
        self.assertEqual(42, metadata.latest_event_id)

    def test_collection_rejects_missing_stable_identity(self) -> None:
        with self.assertRaises(api_models.APIModelError):
            api_models.validate_object_list(
                {"devices": [{"name": "missing ID"}]},
                "devices",
                "device_id",
            )


if __name__ == "__main__":
    unittest.main()
