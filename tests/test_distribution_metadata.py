"""Offline distribution structure checks, not HACS/HA OS acceptance."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DistributionMetadataTest(unittest.TestCase):
    def test_hacs_installs_one_separate_integration(self):
        integrations = sorted(p.name for p in (ROOT / "custom_components").iterdir()
                              if p.is_dir() and not p.name.startswith("."))
        self.assertEqual(["rainpoint_local"], integrations)
        manifest = json.loads((ROOT / "custom_components/rainpoint_local/manifest.json").read_text())
        for key in ("name", "version", "documentation", "issue_tracker", "codeowners"):
            self.assertTrue(manifest[key], key)
        self.assertEqual("rainpoint_local", manifest["domain"])
        self.assertTrue(all(re.fullmatch(r"@[A-Za-z0-9-]+", owner) for owner in manifest["codeowners"]))
        self.assertEqual([], manifest["requirements"])
        self.assertTrue(manifest["config_flow"])
        hacs = json.loads((ROOT / "hacs.json").read_text())
        self.assertFalse(hacs.get("content_in_root", False))
        self.assertFalse(hacs.get("zip_release", False))
        self.assertEqual(manifest["name"], hacs["name"])
        addon = (ROOT / "rainpointd_addon/config.yaml").read_text()
        minimum = re.search(r"^homeassistant: (\S+)$", addon, re.M).group(1)
        self.assertEqual(minimum, hacs["homeassistant"])

    def test_alpha_support_and_license_are_present(self):
        self.assertTrue((ROOT / "LICENSE").read_text().startswith("MIT License"))
        template = (ROOT / ".github/ISSUE_TEMPLATE/alpha_feedback.yml").read_text()
        for text in ("HTV145FRF", "HTV405FRF", "HCS02x", "timezone", "credentials"):
            self.assertIn(text, template)
        self.assertTrue((ROOT / "repository.yaml").exists())
        guide = (ROOT / "GETTING_STARTED.md").read_text()
        self.assertIn("not RF coexistence validation", guide)


if __name__ == "__main__":
    unittest.main()
