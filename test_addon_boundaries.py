#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).parent


class AddonBoundaryTest(unittest.TestCase):
    def test_ha_valve_controls_expose_and_guard_synchronized_transactions(
        self,
    ) -> None:
        valve_source = (
            ROOT / "custom_components" / "rainpoint_local" / "valve.py"
        ).read_text()
        sensor_source = (
            ROOT / "custom_components" / "rainpoint_local" / "sensor.py"
        ).read_text()
        button_source = (
            ROOT / "custom_components" / "rainpoint_local" / "button.py"
        ).read_text()
        binary_sensor_source = (
            ROOT
            / "custom_components"
            / "rainpoint_local"
            / "binary_sensor.py"
        ).read_text()
        http_source = (
            ROOT / "rainpointd_addon" / "rainpointd" / "http.py"
        ).read_text()

        self.assertIn("request_htv405_synchronized_open", http_source)
        self.assertIn("rf_control_transaction_active", valve_source)
        self.assertIn("return ValveEntityFeature(0)", valve_source)
        self.assertIn("rf_control_start_available", valve_source)
        self.assertIn('"transaction_id"', valve_source)
        self.assertIn("control_transaction_status", sensor_source)
        self.assertIn('"transaction_id"', sensor_source)
        self.assertIn(
            "RainPointHtv405CancelWateringRequestButton", button_source
        )
        self.assertIn("cancel_htv405_watering_transaction", button_source)
        self.assertIn(
            "RainPointControlStartAvailableBinarySensor",
            binary_sensor_source,
        )
        self.assertIn("rf_control_start_available", binary_sensor_source)

    def test_mac_continuous_iq_capture_is_bounded_and_receive_only(self) -> None:
        script = ROOT / "tools" / "capture_rainpoint_continuous_iq.sh"
        result = subprocess.run(
            [
                "bash",
                str(script),
                "--duration-seconds",
                "5",
                "--dry-run",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("rtl_sdr", result.stdout)
        self.assertIn("-n 10000000", result.stdout)
        self.assertIn("-f 433700000", result.stdout)
        self.assertIn("-s 2000000", result.stdout)
        self.assertNotIn("ssh ", script.read_text())
        self.assertNotIn("ha addons", script.read_text())

    def test_installable_addon_excludes_research_controls(self) -> None:
        config = (ROOT / "rainpointd_addon" / "config.yaml").read_text()
        run_script = (ROOT / "rainpointd_addon" / "run.sh").read_text()
        translations = (
            ROOT / "rainpointd_addon" / "translations" / "en.yaml"
        ).read_text()
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
        for option in (
            "supervised_htv405_control",
            "htv145_dry_acceptance",
        ):
            self.assertIn(f"\n  {option}:\n", translations)
            self.assertNotIn(f"\n      {option}:\n", translations)

    def test_unified_firmware_accepts_gateway_owned_ack_commands(self) -> None:
        source = (
            ROOT / "firmware" / "rainpoint_bridge" / "src" / "wifi_transport.cpp"
        ).read_text()
        command_boundary = source.split("if (authenticated_ &&", 1)[1].split(
            "void WifiTransport::authenticate", 1
        )[0]
        self.assertIn('type == "routine_ack_configure"', command_boundary)
        self.assertIn('type == "routine_ack_revoke"', command_boundary)
        self.assertIn(
            'type == "htv405_routine_ack_configure"', command_boundary
        )
        self.assertIn('type == "htv405_routine_ack_revoke"', command_boundary)
        self.assertIn("htv405_routine_ack_tx", source)

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
        wifi_source = (
            ROOT
            / "firmware"
            / "rainpoint_bridge"
            / "src"
            / "wifi_transport.cpp"
        ).read_text()
        self.assertIn(
            'os.environ.get("RAINPOINT_RESEARCH_BENCH", "0")',
            build_profile,
        )
        self.assertIn(
            '"RAINPOINT_SUPERVISED_HTV405_CONTROL", "1"',
            build_profile,
        )
        self.assertIn(
            'os.environ.get("RAINPOINT_HTV145_TX_CANDIDATE", "0")',
            build_profile,
        )
        self.assertIn('standard_version = "0.15.7"', build_profile)
        self.assertIn(
            'supervised_version = "0.15.7"',
            build_profile,
        )
        self.assertIn(
            'htv145_candidate_version = '
            '"0.15.0-htv145-control-candidate.3"',
            build_profile,
        )
        self.assertIn(
            '"0.15.3-htv145-pairing-probe.25"',
            build_profile,
        )
        self.assertIn(
            '"0.15.3-htv145-pairing-tail-candidate.1"',
            build_profile,
        )
        self.assertIn(
            '"0.15.4-htv145-pairing-counter2-candidate.4"',
            build_profile,
        )
        self.assertIn('firmware_variant = "unified"', build_profile)
        self.assertIn(
            'firmware_variant = "htv145-pairing-probe"',
            build_profile,
        )
        self.assertIn("RAINPOINT_FIRMWARE_VARIANT", build_profile)
        self.assertIn("RAINPOINT_FIRMWARE_VARIANT", wifi_source)

    def test_htv145_post_frame_tail_is_research_only_and_bounded(self) -> None:
        root = ROOT / "firmware" / "rainpoint_bridge"
        build_profile = (root / "tools" / "build_profile.py").read_text()
        main_source = (root / "src" / "main.cpp").read_text()
        radio_source = (root / "src" / "cc1101.cpp").read_text()
        pairing_source = (
            root / "include" / "rainpoint_htv145_pairing.h"
        ).read_text()
        wifi_source = (root / "src" / "wifi_transport.cpp").read_text()

        self.assertIn(
            '"RAINPOINT_HTV145_POST_FRAME_TAIL_CANDIDATE", "0"',
            build_profile,
        )
        self.assertIn(
            "RAINPOINT_HTV145_POST_FRAME_TAIL_CANDIDATE requires both",
            build_profile,
        )
        self.assertIn('"RAINPOINT_RESEARCH_BENCH=1 and "', build_profile)
        self.assertIn(
            "RAINPOINT_HTV145_POST_FRAME_TAIL_CANDIDATE == 1",
            main_source,
        )
        self.assertIn("replyStep == 0", main_source)
        self.assertIn("postFrameLowHoldMicros > 500", radio_source)
        self.assertIn(
            "kStage0PostFrameLowHoldAdjustmentUs = 115",
            pairing_source,
        )
        self.assertIn("htv145_post_frame_tail_candidate", wifi_source)

    def test_htv145_counter2_branch_is_research_only(self) -> None:
        root = ROOT / "firmware" / "rainpoint_bridge"
        build_profile = (root / "tools" / "build_profile.py").read_text()
        pairing_source = (
            root / "include" / "rainpoint_htv145_pairing.h"
        ).read_text()
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

        self.assertIn(
            '"RAINPOINT_HTV145_FACTORY_COUNTER_CANDIDATE", "0"',
            build_profile,
        )
        self.assertIn(
            "RAINPOINT_HTV145_FACTORY_COUNTER_CANDIDATE requires both",
            build_profile,
        )
        self.assertIn("kCounter2PairingTemplate", pairing_source)
        self.assertIn("kTargetFactoryCounter", pairing_source)
        self.assertIn(
            "RAINPOINT_HTV145_FACTORY_COUNTER_CANDIDATE=2", workflow
        )

    def test_htv405_control_uses_bounded_identical_frame_retries(self) -> None:
        source = (
            ROOT / "firmware" / "rainpoint_bridge" / "src" / "main.cpp"
        ).read_text()
        self.assertIn("kValveProbeRetryDelayMs{{650, 1'450}}", source)
        self.assertIn("valveControlProbe.commandFrame", source)
        self.assertIn('"gateway_command_retry_sent"', source)
        self.assertIn('"gateway_command_rejected"', source)

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
        self.assertIn("htv405_auto_identity_pairing", transport)
        self.assertIn(
            "#if RAINPOINT_SUPERVISED_HTV405_CONTROL == 1",
            transport,
        )
        self.assertIn("valve_control_tx_candidate", transport)
        self.assertIn(
            "#if RAINPOINT_SUPERVISED_HTV405_CONTROL == 1",
            source,
        )
        self.assertIn('type == "valve_control_open"', source)
        self.assertNotIn("-DRAINPOINT_RESEARCH_BENCH=1", platformio)
        self.assertIn("supervised_htv405_control: false", addon_config)
        boundary_check = (
            ROOT / "tools" / "check_firmware_boundaries.py"
        ).read_text()
        self.assertIn("SUPERVISED_VALVE_CONTROL_COMMANDS", boundary_check)
        self.assertIn('option == "--supervised"', boundary_check)
        for forbidden in (
            'type == "valve_open"',
            'type == "valve_close"',
            'type == "watering_start"',
        ):
            self.assertNotIn(forbidden, source)

    def test_ci_builds_and_checks_the_isolated_htv145_pairing_candidate(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        boundary_check = (
            ROOT / "tools" / "check_firmware_boundaries.py"
        ).read_text()
        self.assertIn("RAINPOINT_HTV145_PAIRING_CANDIDATE=1", workflow)
        self.assertIn("--htv145-pairing", workflow)
        self.assertIn("HTV145_PAIRING_CAPABILITIES", boundary_check)
        self.assertIn('option == "--htv145-pairing"', boundary_check)

    def test_htv145_acceptance_is_compile_and_research_gated(self) -> None:
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
        config = (ROOT / "rainpointd_addon" / "config.yaml").read_text()
        integration_source = "\n".join(
            path.read_text()
            for path in (ROOT / "custom_components" / "rainpoint_local").glob(
                "*.py"
            )
        )
        self.assertIn("RAINPOINT_HTV145_TX_CANDIDATE == 1", source)
        self.assertIn("htv145_control_candidate", source)
        self.assertIn(
            "RAINPOINT_HTV145_TX_CANDIDATE requires "
            "RAINPOINT_RESEARCH_BENCH=1",
            build_profile,
        )
        self.assertIn("htv145_dry_acceptance: false", config)
        self.assertIn("/research/htv145-acceptance/", http_source)
        self.assertIn("--enable-htv145-dry-acceptance", main_source)
        self.assertNotIn("htv145-acceptance", integration_source)

    def test_home_assistant_forms_use_labels_and_native_area_selectors(self) -> None:
        source = (
            ROOT / "custom_components" / "rainpoint_local" / "config_flow.py"
        ).read_text()
        self.assertIn("node.get('name') or node['node_id']", source)
        self.assertEqual(3, source.count("selector.AreaSelector()"))
        self.assertNotIn('vol.Optional("area", default=""): str', source)

    def test_home_assistant_pairing_ui_uses_gateway_device_catalog(self) -> None:
        source = (
            ROOT / "custom_components" / "rainpoint_local" / "config_flow.py"
        ).read_text()
        models = (
            ROOT / "custom_components" / "rainpoint_local" / "api_models.py"
        ).read_text()
        strings = json.loads(
            (
                ROOT / "custom_components" / "rainpoint_local" / "strings.json"
            ).read_text()
        )["options"]
        self.assertIn("pairing_profiles(progress)", source)
        self.assertIn('("add_sensor", "add_valve")', source)
        self.assertIn('vol.Required("profile_id")', source)
        self.assertIn("profile.required_node_capability", source)
        self.assertNotIn('vol.Required("factory_endpoint")', source)
        self.assertIn('frozenset({"sensor", "valve"})', models)
        self.assertEqual(
            {"add_sensor", "add_valve"},
            set(strings["step"]["add_device"]["menu_options"]),
        )
        self.assertIn("add_sensor", strings["step"])
        self.assertIn("add_valve", strings["step"])
        self.assertIn("pair_device", strings["step"])
        self.assertIn("device_details", strings["step"])

    def test_home_assistant_device_removal_uses_family_neutral_registry(self) -> None:
        integration = (
            ROOT / "custom_components" / "rainpoint_local" / "__init__.py"
        ).read_text()
        client = (
            ROOT / "custom_components" / "rainpoint_local" / "api.py"
        ).read_text()
        self.assertIn("coordinator.client.forget_device(token, local_id)", integration)
        self.assertNotIn(
            "coordinator.client.forget_sensor(token, local_id)", integration
        )
        self.assertIn('f"registry/{device_id}/forget"', client)

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
        self.assertIn("MINIMUM_RUN_MINUTES = 1", number_source)
        self.assertIn("MAXIMUM_RUN_MINUTES = 60", number_source)
        self.assertIn("RUN_MINUTE_STEP = 1", number_source)
        self.assertIn('"rf_control_duration_min_minutes"', number_source)
        self.assertIn('"rf_control_duration_max_minutes"', number_source)
        self.assertIn('"rf_control_duration_step_minutes"', number_source)
        self.assertNotIn("DEFAULT_VALIDATED_RUN_MINUTES", number_source)
        self.assertNotIn(
            '"rf_control_validated_duration_minutes"', number_source
        )
        self.assertIn(
            "_attr_native_min_value = MINIMUM_RUN_MINUTES", number_source
        )
        self.assertIn(
            "_attr_native_max_value = MAXIMUM_RUN_MINUTES", number_source
        )
        self.assertIn("_attr_native_step = RUN_MINUTE_STEP", number_source)
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
            "sensor.rainpoint_4_zone_valve_8013_battery",
            "binary_sensor.garden_htv405_4_zone_water_timer_8013",
            "sensor.garden_htv405_4_zone_water_timer_8013_control_request_status",
        ):
            self.assertIn(entity, dashboard)
        self.assertNotIn(
            "sensor.rainpoint_4_zone_valve_8013_last_water_usage",
            dashboard,
        )
        self.assertNotIn("input_number.garden_water_used_today", dashboard)
        self.assertIn("Valve Battery (not decoded)", dashboard)

    def test_garden_manual_run_uses_one_observable_transaction(self) -> None:
        scripts = (
            ROOT
            / "examples"
            / "federico-garden"
            / "garden-local-scripts.yaml"
        ).read_text()
        force_run = scripts.split(
            "garden_run_manual_watering_program:", maxsplit=1
        )[0]

        self.assertEqual(1, force_run.count("action: valve.open_valve"))
        self.assertIn("transaction_state", force_run)
        self.assertIn("transaction_status", force_run)
        self.assertIn("transaction_id_before", force_run)
        self.assertIn("watering_confirmed", force_run)
        self.assertIn("completed", force_run)
        self.assertIn("failed", force_run)
        self.assertIn("cancelled", force_run)
        self.assertIn("duration_min_minutes", force_run)
        self.assertIn("duration_max_minutes", force_run)
        self.assertIn("duration_step_minutes", force_run)
        self.assertNotIn("validated_duration_minutes", force_run)
        self.assertNotIn('timeout: "00:00:10"', force_run)
        self.assertNotIn("accepted_command_results", force_run)

    def test_htv405_omits_unsupported_water_usage_entity(self) -> None:
        sensor_source = (
            ROOT / "custom_components" / "rainpoint_local" / "sensor.py"
        ).read_text()
        coordinator_source = (
            ROOT / "custom_components" / "rainpoint_local" / "coordinator.py"
        ).read_text()
        self.assertIn(
            'device.get("model") == "HTV405FRF"', sensor_source
        )
        self.assertIn(
            'description.state_key == "last_usage_liters"', sensor_source
        )
        self.assertIn(
            'f"{device_id}_last_usage"', coordinator_source
        )
        self.assertIn("entity_registry.async_remove", coordinator_source)

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
        ).read_text()
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
