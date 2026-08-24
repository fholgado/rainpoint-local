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
            "void WifiTransport::authenticate", 1
        )[0]
        self.assertIn('type == "routine_ack_configure"', command_boundary)
        self.assertIn('type == "routine_ack_revoke"', command_boundary)

    def test_firmware_has_one_standard_build_environment(self) -> None:
        platformio = (
            ROOT / "firmware" / "rainpoint_bridge" / "platformio.ini"
        ).read_text()
        self.assertEqual(1, platformio.count("[env:"))
        self.assertIn("[env:rainpoint_bridge]", platformio)
        self.assertIn("default_envs = rainpoint_bridge", platformio)
        self.assertNotIn("single_bench", platformio)
        self.assertNotIn("candidate]", platformio)
        self.assertNotIn("-DRAINPOINT_RESEARCH_BENCH=1", platformio)
        build_profile = (
            ROOT
            / "firmware"
            / "rainpoint_bridge"
            / "tools"
            / "build_profile.py"
        ).read_text()
        self.assertIn(
            'os.environ.get("RAINPOINT_RESEARCH_BENCH", "0")',
            build_profile,
        )
        self.assertIn(
            'os.environ.get("RAINPOINT_HTV145_TX_CANDIDATE", "0")',
            build_profile,
        )

    def test_ack_owner_prioritizes_the_validated_telemetry_channel(self) -> None:
        source = (
            ROOT / "firmware" / "rainpoint_bridge" / "src" / "main.cpp"
        ).read_text()
        self.assertIn("kHcs026TelemetryChannel = 0", source)
        self.assertIn("routineAckAuthorizations.activeCount() > 0", source)
        self.assertIn("selectChannel(kHcs026TelemetryChannel)", source)
        self.assertIn("parseHexFactoryEndpoint", source)

    def test_valve_pairing_candidate_cannot_control_watering(self) -> None:
        source = (
            ROOT / "firmware" / "rainpoint_bridge" / "src" / "main.cpp"
        ).read_text()
        transport = (
            ROOT / "firmware" / "rainpoint_bridge" / "src" / "wifi_transport.cpp"
        ).read_text()
        self.assertIn("kAutomaticHtv405ProfileId", source)
        self.assertIn('\\"valve_control_available\\":false', source)
        self.assertIn("valve_pairing_tx_candidate", transport)
        self.assertIn("#if RAINPOINT_RESEARCH_BENCH == 1", transport)
        self.assertIn("valve_control_tx_candidate", transport)
        for forbidden in (
            'type == "valve_open"',
            'type == "valve_close"',
            'type == "watering_start"',
        ):
            self.assertNotIn(forbidden, source)

    def test_htv145_control_is_compile_gated_and_has_no_public_api(self) -> None:
        source = (
            ROOT / "firmware" / "rainpoint_bridge" / "src" / "main.cpp"
        ).read_text()
        build_profile = (
            ROOT
            / "firmware"
            / "rainpoint_bridge"
            / "tools"
            / "build_profile.py"
        ).read_text()
        http_source = (
            ROOT / "rainpointd_addon" / "rainpointd" / "http.py"
        ).read_text()
        self.assertIn("RAINPOINT_HTV145_TX_CANDIDATE == 1", source)
        self.assertIn("htv145_control_candidate", source)
        self.assertIn(
            "RAINPOINT_HTV145_TX_CANDIDATE requires "
            "RAINPOINT_RESEARCH_BENCH=1",
            build_profile,
        )
        self.assertNotIn("htv145_control", http_source)

    def test_home_assistant_forms_use_labels_and_native_area_selectors(self) -> None:
        source = (
            ROOT / "custom_components" / "rainpoint_local" / "config_flow.py"
        ).read_text()
        self.assertIn("node.get('name') or node['node_id']", source)
        self.assertEqual(3, source.count("selector.AreaSelector()"))
        self.assertNotIn('vol.Optional("area", default=""): str', source)


if __name__ == "__main__":
    unittest.main()
