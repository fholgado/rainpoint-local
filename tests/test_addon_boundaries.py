#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import runpy
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class AddonBoundaryTest(unittest.TestCase):
    def test_supervisor_watchdog_uses_tls_compatible_tcp_probe(self):
        config = (ROOT / "rainpointd_addon" / "config.yaml").read_text()
        self.assertIn("watchdog: tcp://[HOST]:[PORT:8787]", config)
        self.assertNotIn("watchdog: http://", config)



    def test_runtime_has_no_household_identity_or_research_imports(self):
        roots=[ROOT/"rainpointd_addon",ROOT/"custom_components/rainpoint_local",
               ROOT/"firmware/rainpoint_bridge/src",ROOT/"firmware/rainpoint_bridge/include"]
        forbidden=("b9840280","b42d008f","94a98013","9ce58024","soil-right-bed","192.168.",
                   "from research", "import research", "LEGACY_HOME_CATALOG")
        for root in roots:
            for path in root.rglob("*"):
                if path.suffix not in {".py",".cpp",".h"}: continue
                source=path.read_text()
                for text in forbidden:
                    self.assertNotIn(text,source,msg=str(path.relative_to(ROOT)))
        self.assertFalse((ROOT/"rainpointd_addon/rainpointd/valve_control_bench.py").exists())

    def test_firmware_has_one_environment_with_both_valves(self):
        root = ROOT / "firmware/rainpoint_bridge"
        self.assertEqual(1, (root / "platformio.ini").read_text().count("[env:"))
        class Environment(dict):
            def subst(self, value):
                if value == "$PROJECT_DIR":
                    return str(root)
                raise AssertionError(value)
            def Append(self, **kwargs):
                self.defines = dict(kwargs["CPPDEFINES"])
        def build(values):
            env = Environment()
            with patch.dict(os.environ, values, clear=True):
                runpy.run_path(str(root / "tools/build_profile.py"), init_globals={"env": env, "Import": lambda _: None})
            return env.defines
        self.assertNotIn("RAINPOINT_HTV145_ENABLED", build({}))
        self.assertIn("unified", build({})["RAINPOINT_FIRMWARE_VARIANT"])
        for values in [{"RAINPOINT_HTV145_ENABLED": "0"},
                       {"RAINPOINT_HTV145_ENABLED": "1"},
                       {"RAINPOINT_HTV145_ASSIGNMENT_SELECTOR_CANDIDATE": "2"},
                       {"RAINPOINT_RESEARCH_BENCH": "1"}]:
            with self.assertRaises(ValueError):
                build(values)
        source = (root / "src/main.cpp").read_text()
        for command in ("htv145_dry_open_probe", "htv145_dry_close_probe", "pairing_probe_b",
                        "htv145_fifo_step4_calibration", "htv145_prelude_calibration"):
            self.assertNotIn(command, source)
        for capability in ("routine_ack_configure", "htv405_routine_ack_configure", "firmware_update_start",
                           "htv145_control_open", "htv145_control_revoke"):
            self.assertIn(capability, source)
        # Implemented research commands must be reachable through the authenticated transport.
        import re
        transport = (root / "src/wifi_transport.cpp").read_text()
        handled = set(re.findall(r'type == "(htv145_control_[a-z_]+)"', source))
        admitted = set(re.findall(r'type == "(htv145_control_[a-z_]+)"', transport))
        self.assertLessEqual(handled, admitted)
        self.assertIn("!htv145Owner().counterAuthenticated", source)
        self.assertIn("!rfMaintenance.transmitAllowed()", source)
        self.assertIn("!wifiTransport.authenticated()", source)

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

        self.assertIn("request_valve_control", http_source)
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
        self.assertNotIn(" -S ", result.stdout)
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
            self.assertNotIn(option, translations)
            self.assertNotIn(option, config)
            self.assertNotIn(option, run_script)
        main = (ROOT / "rainpointd_addon/rainpointd/__main__.py").read_text()
        self.assertIn("valve_control_enabled=True", main)
        self.assertNotIn("--enable-supervised-htv405-control", main)

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
            "valve_control_tx_candidate",
            transport,
        )
        self.assertIn("valve_control_tx_candidate", transport)
        self.assertIn(
            "valve_control_open",
            source,
        )
        self.assertIn('type == "valve_control_open"', source)
        self.assertNotIn("-DRAINPOINT_RESEARCH_BENCH=1", platformio)
        self.assertNotIn("supervised_htv405_control", addon_config)
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

    def test_ci_checks_both_valve_families_in_the_production_image(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        boundary_check = (
            ROOT / "tools" / "check_firmware_boundaries.py"
        ).read_text()
        self.assertNotIn("RAINPOINT_HTV145_ENABLED", workflow)
        self.assertIn("--htv145-pairing", workflow)
        self.assertIn("HTV145_PAIRING_CAPABILITIES", boundary_check)
        self.assertIn('option == "--htv145-pairing"', boundary_check)

    def test_htv145_acceptance_remains_separate_from_promoted_controls(self) -> None:
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
        self.assertNotIn("RAINPOINT_HTV145_ENABLED", source)
        self.assertNotIn("RAINPOINT_HTV145_ENABLED", (ROOT / "firmware/rainpoint_bridge/src/cc1101.cpp").read_text())
        self.assertIn("htv145_control_candidate", source)
        self.assertIn(
            '"RAINPOINT_HTV145_ENABLED"',
            build_profile,
        )
        self.assertNotIn("htv145_dry_acceptance", config)
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
        # Retained single-zone entity names belong only to the Front Yard view.
        garden, front = dashboard.split("  - title: Front Yard", maxsplit=1)
        self.assertNotIn("garden_valve_", garden)
        self.assertIn("valve.rainpoint_valve_008f_valve", front)
        self.assertIn("sensor.garden_valve_last_water_usage", front)
        self.assertNotIn("front_garden_bed_water_valve", dashboard)
        self.assertIn("binary_sensor.front_yard_local_run_available", front)
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

    def test_single_valve_example_requires_fresh_confirmation_and_preserves_alerts(self) -> None:
        example = ROOT / "examples" / "federico-garden"
        script = (example / "single-valve-scripts.yaml").read_text()
        self.assertEqual(1, script.count("action: valve.open_valve"))
        self.assertNotIn("action: valve.close_valve", script)
        self.assertIn('timeout: "00:00:40"', script)
        self.assertIn("state_attr(valve_entity, 'confirmed_at')", script)
        self.assertIn("requested_at | float", script)
        self.assertIn("persistent_notification.create", script)
        self.assertIn("urgent_notify_service", script)
        self.assertIn("mode: single", script)
        self.assertIn("start_available", script)
        self.assertIn("No duplicate open was sent", script)
        self.assertIn("confirmation_mode: single_valve",
            (example / "garden-local-scripts.yaml").read_text())

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
            'unsupported_device_entity_ids(device_id, device)', coordinator_source
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
