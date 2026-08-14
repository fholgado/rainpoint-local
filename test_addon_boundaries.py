#!/usr/bin/env python3

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).parent


class AddonBoundaryTest(unittest.TestCase):
    def test_installable_addon_excludes_research_controls(self) -> None:
        config = (ROOT / "rainpointd_addon" / "config.yaml").read_text()
        run_script = (ROOT / "rainpointd_addon" / "run.sh").read_text()
        for research_control in (
            "replay_interval",
            "research_capture_minutes",
            "--signal-capture-seconds",
        ):
            self.assertNotIn(research_control, config)
            self.assertNotIn(research_control, run_script)
        self.assertNotIn("|replay", config)
        self.assertIn("share:ro", config)
        self.assertNotIn("share:rw", config)

    def test_unified_firmware_accepts_gateway_owned_ack_commands(self) -> None:
        source = (
            ROOT / "firmware" / "rainpoint_bridge" / "src" / "wifi_transport.cpp"
        ).read_text()
        command_boundary = source.split("if (authenticated_ &&", 1)[1].split(
            "pendingCommand_ = line;", 1
        )[0]
        self.assertIn('type == "routine_ack_configure"', command_boundary)
        self.assertIn('type == "routine_ack_revoke"', command_boundary)

    def test_ack_owner_prioritizes_the_validated_telemetry_channel(self) -> None:
        source = (
            ROOT / "firmware" / "rainpoint_bridge" / "src" / "main.cpp"
        ).read_text()
        self.assertIn("kHcs026TelemetryChannel = 0", source)
        self.assertIn("routineAckAuthorizations.activeCount() > 0", source)
        self.assertIn("selectChannel(kHcs026TelemetryChannel)", source)
        self.assertIn("parseHexFactoryEndpoint", source)

    def test_home_assistant_forms_use_labels_and_native_area_selectors(self) -> None:
        source = (
            ROOT / "custom_components" / "rainpoint_local" / "config_flow.py"
        ).read_text()
        self.assertIn("node.get('name') or node['node_id']", source)
        self.assertEqual(3, source.count("selector.AreaSelector()"))
        self.assertNotIn('vol.Optional("area", default=""): str', source)


if __name__ == "__main__":
    unittest.main()
