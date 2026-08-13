#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parent
PACKAGE = ROOT / "custom_components" / "rainpoint_local"

# Load the pure migration module without importing Home Assistant.
package = types.ModuleType("rainpoint_local")
package.__path__ = [str(PACKAGE)]
sys.modules.setdefault("rainpoint_local", package)
for module_name in ("const", "migration"):
    spec = importlib.util.spec_from_file_location(
        f"rainpoint_local.{module_name}", PACKAGE / f"{module_name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

from rainpoint_local.migration import migrate_entry_payload


class IntegrationMigrationTest(unittest.TestCase):
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
