#!/usr/bin/env python3

from __future__ import annotations

import json
import re
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

    def test_htv405_control_requires_both_build_and_gateway_gates(self) -> None:
        source = (
            ROOT / "firmware" / "rainpoint_bridge" / "src" / "main.cpp"
        ).read_text()
        transport = (
            ROOT / "firmware" / "rainpoint_bridge" / "src" / "wifi_transport.cpp"
        ).read_text()
        platformio = (
            ROOT / "firmware" / "rainpoint_bridge" / "platformio.ini"
        ).read_text()
        addon_config = (ROOT / "rainpointd_addon" / "config.yaml").read_text()
        self.assertIn("kAutomaticHtv405ProfileId", source)
        self.assertIn('\\"valve_control_available\\":false', source)
        self.assertIn("valve_pairing_tx_candidate", transport)
        self.assertIn("#if RAINPOINT_RESEARCH_BENCH == 1", transport)
        self.assertIn("valve_control_tx_candidate", transport)
        self.assertIn("#if RAINPOINT_RESEARCH_BENCH == 1", source)
        self.assertIn('type == "valve_control_open"', source)
        self.assertNotIn("-DRAINPOINT_RESEARCH_BENCH=1", platformio)
        self.assertIn("supervised_htv405_control: false", addon_config)
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
        main_source = (
            ROOT / "rainpointd_addon" / "rainpointd" / "__main__.py"
        ).read_text()
        self.assertIn("RAINPOINT_HTV145_TX_CANDIDATE == 1", source)
        self.assertIn("htv145_control_candidate", source)
        self.assertIn(
            "RAINPOINT_HTV145_TX_CANDIDATE requires "
            "RAINPOINT_RESEARCH_BENCH=1",
            build_profile,
        )
        self.assertNotIn("htv145_control", http_source)
        self.assertNotIn("htv145_acceptance", http_source)
        self.assertNotIn("htv145_acceptance", main_source)

    def test_home_assistant_forms_use_labels_and_native_area_selectors(self) -> None:
        source = (
            ROOT / "custom_components" / "rainpoint_local" / "config_flow.py"
        ).read_text()
        self.assertIn("node.get('name') or node['node_id']", source)
        self.assertEqual(3, source.count("selector.AreaSelector()"))
        self.assertNotIn('vol.Optional("area", default=""): str', source)

    def test_htv405_duration_entities_preserve_the_supervised_boundary(self) -> None:
        const_source = (
            ROOT / "custom_components" / "rainpoint_local" / "const.py"
        ).read_text()
        coordinator_source = (
            ROOT / "custom_components" / "rainpoint_local" / "coordinator.py"
        ).read_text()
        number_source = (
            ROOT / "custom_components" / "rainpoint_local" / "number.py"
        ).read_text()
        valve_source = (
            ROOT / "custom_components" / "rainpoint_local" / "valve.py"
        ).read_text()
        self.assertIn('"number"', const_source)
        self.assertIn("MAXIMUM_RUN_MINUTES = 60", number_source)
        self.assertIn("_attr_native_min_value = 1", number_source)
        self.assertIn("htv405_run_minutes", coordinator_source)
        self.assertIn("run_minutes * 60", valve_source)
        self.assertNotIn("DEFAULT_BOUNDED_RUN_SECONDS", valve_source)

    def test_garden_example_uses_the_current_htv405_identity(self) -> None:
        dashboard = (
            ROOT
            / "examples"
            / "federico-garden"
            / "garden-local-dashboard.yaml"
        ).read_text()
        self.assertNotIn("garden_valve_", dashboard)
        for entity in (
            "binary_sensor.rainpoint_4_zone_valve_8013_zone_1_watering",
            "sensor.rainpoint_4_zone_valve_8013_device_report_time",
            "sensor.rainpoint_4_zone_valve_8013_last_water_usage",
            "sensor.rainpoint_4_zone_valve_8013_battery",
        ):
            self.assertIn(entity, dashboard)
        self.assertIn("Valve Battery (not decoded)", dashboard)

    def test_release_versions_are_recorded_in_the_current_changelog(self) -> None:
        addon_config = (ROOT / "rainpointd_addon" / "config.yaml").read_text()
        addon_match = re.search(r"^version: (\S+)$", addon_config, re.MULTILINE)
        self.assertIsNotNone(addon_match)
        assert addon_match is not None
        integration_version = json.loads(
            (
                ROOT
                / "custom_components"
                / "rainpoint_local"
                / "manifest.json"
            ).read_text()
        )["version"]
        current_changelog = (
            ROOT / "rainpointd_addon" / "CHANGELOG.md"
        ).read_text()[:2_000]
        addon_docs = (ROOT / "rainpointd_addon" / "DOCS.md").read_text()
        self.assertIn(f"## {addon_match.group(1)} /", current_changelog)
        self.assertIn(
            f"Integration {integration_version}", current_changelog
        )
        self.assertIn(f"Version {addon_match.group(1)} supports", addon_docs)

    def test_firmware_docs_describe_the_supervised_htv405_boundary(self) -> None:
        firmware_docs = (
            ROOT / "firmware" / "rainpoint_bridge" / "README.md"
        ).read_text()
        self.assertIn("1--60 whole-minute opens", firmware_docs)
        self.assertIn("disabled by default", firmware_docs)
        self.assertNotIn(
            "Keeps valve control absent from the Home Assistant", firmware_docs
        )

    def test_migration_design_uses_valve_owned_bounded_runs(self) -> None:
        migration = (ROOT / "CLOUD_TO_LOCAL_MIGRATION.md").read_text()
        self.assertNotIn("Close-first valve control", migration)
        self.assertIn("Valve-owned bounded open", migration)


if __name__ == "__main__":
    unittest.main()
