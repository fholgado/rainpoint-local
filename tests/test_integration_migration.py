#!/usr/bin/env python3

from __future__ import annotations

import ast
import json
import importlib.util
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, call
from pathlib import Path
from datetime import timedelta

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "custom_components" / "rainpoint_local"

# Load the pure migration module without importing Home Assistant.
package = types.ModuleType("rainpoint_local")
package.__path__ = [str(PACKAGE)]
sys.modules.setdefault("rainpoint_local", package)
for module_name in ("const", "migration", "api_models", "notifications", "registry"):
    spec = importlib.util.spec_from_file_location(
        f"rainpoint_local.{module_name}", PACKAGE / f"{module_name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

from rainpoint_local.migration import migrate_entry_payload
from rainpoint_local.api_models import multi_zone_numbers, unsupported_device_entity_ids
from rainpoint_local.registry import device_for_entry


def _integration_function(filename, name, namespace, classname=None):
    """Exercise the actual HA callback with registry/entity APIs stubbed."""
    from rainpoint_local.notifications import notify_command_failure
    namespace.setdefault("device_for_entry", device_for_entry)
    namespace.setdefault("notify_command_failure", notify_command_failure)
    tree = ast.parse((PACKAGE / filename).read_text())
    if classname is not None:
        tree = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == classname)
    function = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    module = ast.parse("from __future__ import annotations")
    module.body.append(function)
    exec(compile(module, str(PACKAGE / filename), "exec"), namespace)
    return namespace[name]


class HardeningFlowTest(unittest.IsolatedAsyncioTestCase):
    async def test_pairing_review_has_no_radio_side_effect_and_back_preserves_choice(self):
        profile = types.SimpleNamespace(display_name="Valve")
        flow = types.SimpleNamespace(_pairing_profile=profile, _pairing_nodes={"n":"Radio"},
            _pairing_request={"node_id":"n", "duration_seconds":120}, async_show_menu=Mock(),
            async_step_pair_device=AsyncMock(), async_step_add_device=AsyncMock())
        review = _integration_function("config_flow.py", "async_step_pairing_review", {})
        await review(flow)
        self.assertEqual(["start_pairing", "change_pairing_model", "change_pairing_radio"],
                         flow.async_show_menu.call_args.kwargs["menu_options"])
        flow.async_step_pair_device.assert_not_awaited()
        back = _integration_function("config_flow.py", "async_step_change_pairing_radio", {})
        await back(flow)
        flow.async_step_pair_device.assert_awaited_once_with()
        self.assertEqual("n", flow._pairing_request["node_id"])

    def test_pairing_intermediate_forms_render_next(self):
        tree = ast.parse((PACKAGE / "config_flow.py").read_text())
        for name in ("_async_select_pairing_profile", "async_step_pair_device"):
            method = next(node for node in ast.walk(tree)
                          if isinstance(node, ast.AsyncFunctionDef) and node.name == name)
            form = next(node for node in ast.walk(method)
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "async_show_form")
            keywords = {arg.arg: arg.value for arg in form.keywords}
            self.assertIn("last_step", keywords, name)
            self.assertIs(ast.literal_eval(keywords["last_step"]), False, name)

    async def test_management_menu_omits_manual_radio_credentials(self):
        flow = types.SimpleNamespace(
            _token="test-token", _entry=types.SimpleNamespace(
                data={"registry_write_token": "test-token"}, options={}),
            async_show_menu=Mock())
        callback = _integration_function("config_flow.py", "async_step_init",
                                         {"CONF_TOKEN": "registry_write_token"})
        await callback(flow)
        self.assertEqual(["add_device", "verify_valve", "remove_radio_node"],
                         flow.async_show_menu.call_args.kwargs["menu_options"])

    def test_pairing_labels_omit_manual_credentials_and_use_review_back(self):
        strings = json.loads((PACKAGE / "strings.json").read_text())
        translated = json.loads((PACKAGE / "translations/en.json").read_text())
        self.assertEqual(strings, translated)
        steps = strings["options"]["step"]
        self.assertNotIn("add_radio_node", steps["init"]["menu_options"])
        self.assertEqual("Back", steps["pairing_review"]["menu_options"]["change_pairing_radio"])
        self.assertNotIn("cancel_add_device", steps["pairing_review"]["menu_options"])

    async def test_commissioning_review_and_skip_never_start_watering(self):
        client = types.SimpleNamespace(commission_valve=AsyncMock(return_value={
            "state": "awaiting_consent", "pairing_command_id": "pair-1"}))
        flow = types.SimpleNamespace(_client=lambda: client, _token="token",
            _commission_device_id="valve", async_show_menu=Mock(), async_create_entry=Mock())
        fn = _integration_function("config_flow.py", "async_step_commission_review", {})
        await fn(flow)
        client.commission_valve.assert_awaited_once_with("token", "valve", "status")
        self.assertEqual("pair-1", flow._commission_pairing_command_id)
        self.assertIn("commission_later", flow.async_show_menu.call_args.kwargs["menu_options"])
        await _integration_function("config_flow.py", "async_step_commission_later", {})(flow)
        self.assertEqual(1, client.commission_valve.await_count)

    async def test_commissioning_progress_cancels_only_its_pairing_session(self):
        import asyncio
        client = types.SimpleNamespace(commission_valve=AsyncMock(side_effect=[asyncio.CancelledError(), {}]))
        flow = types.SimpleNamespace(_client=lambda: client, _token="token",
            _commission_device_id="valve", _commission_pairing_command_id="pair-1")
        ns = {"asyncio": asyncio, **{name: ValueError for name in (
            "RainPointLocalCannotConnect", "RainPointLocalInvalidResponse",
            "RainPointLocalUnauthorized", "RainPointLocalCommandRejected")}}
        fn = _integration_function("config_flow.py", "_async_commission_wait", ns)
        with self.assertRaises(asyncio.CancelledError): await fn(flow)
        self.assertEqual([call("token", "valve", "advance", pairing_command_id="pair-1"),
                         call("token", "valve", "cancel", pairing_command_id="pair-1")],
                         client.commission_valve.await_args_list)

    async def test_setup_enables_owner_without_watering_consent_or_experiments(self):
        client = types.SimpleNamespace(commission_valve=AsyncMock(return_value={"state": "ready"}))
        async def wait(): pass
        # Close the scheduled coroutine in this callback-only harness.
        def create_task(coro):
            coro.close()
            return "task"
        flow = types.SimpleNamespace(_client=lambda: client, _token="token", context={},
            _commission_device_id="valve", _commission_pairing_command_id="pair-1",
            hass=types.SimpleNamespace(async_create_task=create_task),
            _async_commission_wait=wait, async_step_commission_progress=AsyncMock())
        namespace = {name: ValueError for name in (
            "RainPointLocalCannotConnect", "RainPointLocalInvalidResponse",
            "RainPointLocalUnauthorized", "RainPointLocalCommandRejected")}
        await _integration_function("config_flow.py", "async_step_commission_start", namespace)(flow, {})
        client.commission_valve.assert_awaited_once_with("token", "valve", "enable",
            pairing_command_id="pair-1")
        flow.async_step_commission_progress.assert_awaited_once()

    async def test_event_listener_refreshes_state_and_recovers_reset_cursor(self):
        import asyncio
        from rainpoint_local.api_models import events_require_refresh, apply_sensor_event_page
        for events, cursor, refresh in [([{"event_type":"rf_frame"}], 11, False),
                                        ([{"event_type":"device_observation"}], 11, True), ([], 0, True)]:
            coordinator = types.SimpleNamespace(_event_cursor=10, data={},
                client=types.SimpleNamespace(events=AsyncMock(side_effect=[(events,cursor),asyncio.CancelledError()])),
                async_refresh=AsyncMock(), last_update_success=True)
            fn = _integration_function("coordinator.py", "_async_event_listener", {
                "asyncio":asyncio, "RainPointLocalError":ValueError, "events_require_refresh":events_require_refresh, "apply_sensor_event_page":apply_sensor_event_page, "DEFAULT_SCAN_INTERVAL":timedelta(minutes=1)})
            with self.assertRaises(asyncio.CancelledError): await fn(coordinator)
            self.assertEqual(cursor, coordinator._event_cursor)
            self.assertEqual(int(refresh),coordinator.async_refresh.await_count)

    async def test_frequent_sensor_pushes_cannot_starve_reconciliation(self):
        import asyncio
        from rainpoint_local.api_models import events_require_refresh, apply_sensor_event_page
        event={"event_type":"device_observation", "device_id":"soil", "model":"HCS026FRF",
               "event_id":11,"observed_at":"2026-09-07T00:00:00+00:00","state":{"soil_moisture_percent":30}}
        coordinator=types.SimpleNamespace(_event_cursor=10,last_update_success=True,
            data={"soil":{"model":"HCS026FRF","state":{},"last_event_id":10}},
            client=types.SimpleNamespace(events=AsyncMock(side_effect=[([event],11),asyncio.CancelledError()])),
            async_refresh=AsyncMock(),async_set_updated_data=Mock())
        fn=_integration_function("coordinator.py","_async_event_listener",{
            "asyncio":asyncio,"RainPointLocalError":ValueError,"events_require_refresh":events_require_refresh,
            "apply_sensor_event_page":apply_sensor_event_page,"DEFAULT_SCAN_INTERVAL":timedelta(0)})
        with self.assertRaises(asyncio.CancelledError):await fn(coordinator)
        coordinator.async_refresh.assert_awaited_once()
        coordinator.async_set_updated_data.assert_not_called()

    def test_migration_rejects_future_versions_and_preserves_identity_and_user_options(self):
        for version in (0,4,True):
            with self.assertRaises(ValueError): migrate_entry_payload(version,{}, {})
        data={"host":" gateway ","port":8787,"registry_write_token":"current","gateway_id":"stable"}
        options={"registry_write_token":"obsolete", "user_option":42}
        version,new_data,new_options=migrate_entry_payload(2,data,options)
        self.assertEqual(3,version);self.assertEqual("current",new_data["registry_write_token"])
        self.assertEqual("stable",new_data["gateway_id"]);self.assertEqual({"user_option":42},new_options)
        self.assertEqual((version,new_data,new_options),migrate_entry_payload(version,new_data,new_options))
        self.assertIn("registry_write_token",options)


class SingleValvePromotionTest(unittest.IsolatedAsyncioTestCase):
    async def test_single_valve_failure_refreshes_persistent_diagnostics_without_optimism(self):
        attrs = _integration_function("valve.py", "extra_state_attributes",
            {"DEFAULT_BOUNDED_RUN_MINUTES": 1}, classname="RainPointSingleValve")
        for method, action in (("async_open_valve", "open_single_valve"),
                               ("async_close_valve", "close_single_valve")):
            coordinator = types.SimpleNamespace(htv405_run_minutes={}, async_refresh=AsyncMock(),
                client=types.SimpleNamespace(**{action: AsyncMock(side_effect=ValueError("dispatch failed"))}))
            entity = types.SimpleNamespace(coordinator=coordinator, device_id="one", _token="token",
                decoded_state={"rf_control_start_available": True, "is_watering": False,
                    "rf_control_transaction_id": "request", "rf_control_transaction_state": "failed",
                    "rf_control_transaction_error": "node_dispatch_failed_counter_unsynchronized"})
            callback = _integration_function("valve.py", method,
                {"RainPointLocalError": ValueError, "HomeAssistantError": RuntimeError,
                 "DEFAULT_BOUNDED_RUN_MINUTES": 1}, classname="RainPointSingleValve")
            with self.assertRaisesRegex(RuntimeError, "dispatch failed"):
                await callback(entity)
            coordinator.async_refresh.assert_awaited_once()
            self.assertEqual("request", attrs.fget(entity)["transaction_id"])
            self.assertEqual("failed", attrs.fget(entity)["transaction_state"])
            self.assertFalse(entity.decoded_state["is_watering"])

    def test_single_valve_start_availability_is_authoritative(self):
        callback = _integration_function("valve.py", "extra_state_attributes",
            {"DEFAULT_BOUNDED_RUN_MINUTES": 1}, classname="RainPointSingleValve")
        entity = types.SimpleNamespace(device_id="one",
            coordinator=types.SimpleNamespace(htv405_run_minutes={}), decoded_state={})
        for ready in (None, False, True):
            entity.decoded_state = {"rf_control_available": True,
                "rf_control_start_available": ready, "rf_control_command_pending": False}
            self.assertIs(callback.fget(entity)["start_available"], ready)

    async def test_public_commands_refresh_confirmed_state_and_bound_duration(self):
        for method, action in (("async_open_valve", "open_single_valve"),
                               ("async_close_valve", "close_single_valve")):
            client = types.SimpleNamespace(open_single_valve=AsyncMock(), close_single_valve=AsyncMock())
            coordinator = types.SimpleNamespace(client=client, async_refresh=AsyncMock(),
                htv405_run_minutes={("one", 1): 5})
            entity = types.SimpleNamespace(coordinator=coordinator, device_id="one", _token="token",
                decoded_state={"rf_control_start_available": True, "is_watering": False})
            callback = _integration_function("valve.py", method,
                {"RainPointLocalError": ValueError, "HomeAssistantError": RuntimeError,
                 "DEFAULT_BOUNDED_RUN_MINUTES": 1}, classname="RainPointSingleValve")
            await callback(entity)
            kwargs = {"device_id": "one"}
            if action == "open_single_valve": kwargs["duration_seconds"] = 300
            getattr(client, action).assert_awaited_once_with("token", **kwargs)
            coordinator.async_refresh.assert_awaited_once()
            self.assertFalse(entity.decoded_state["is_watering"])
            if action == "open_single_valve":
                entity.decoded_state["rf_control_start_available"] = False
                with self.assertRaises(RuntimeError): await callback(entity)
                self.assertEqual(1, client.open_single_valve.await_count)

    async def test_exact_single_model_creates_one_control_and_no_zone_entities(self):
        single, multi, add = Mock(), Mock(), Mock()
        coordinator = types.SimpleNamespace(data={
            "one": {"model": "HTV145FRF", "capabilities": ["bounded_single_valve_control"]},
            "unverified": {"model": "HTV145FRF", "capabilities": []},
        })
        callback = _integration_function("valve.py", "async_add_missing_entities", {
            "callback": lambda fn: fn, "coordinator": coordinator, "known": set(), "token": "token",
            "RainPointSingleValve": single, "RainPointHtv405ZoneValve": multi,
            "multi_zone_numbers": multi_zone_numbers, "async_add_entities": add,
        })
        callback(); callback()
        single.assert_called_once_with(coordinator, "one", "token")
        multi.assert_not_called()
        add.assert_called_once_with([single.return_value])


class ValveCommandRefreshTest(unittest.IsolatedAsyncioTestCase):
    async def test_one_zone_sync_button_preserves_entity_and_old_gateway_fallback(self):
        tree = ast.parse((PACKAGE / "button.py").read_text())
        cls = next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=="RainPointRestoreRetainedCounterButton")
        method = next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=="async_press")
        module = ast.parse("from __future__ import annotations"); module.body.append(method)
        ns = {"RainPointLocalError":ValueError,"HomeAssistantError":RuntimeError}
        exec(compile(module,"button.py","exec"),ns)
        for supported in (False,True):
            client = types.SimpleNamespace(restore_retained_counter=AsyncMock(),sync_htv405_now=AsyncMock())
            entity = types.SimpleNamespace(device_id="one",_token="test",decoded_state={"rf_htv145_counter_sync_supported":supported},
                coordinator=types.SimpleNamespace(client=client,async_request_refresh=AsyncMock()))
            await ns["async_press"](entity)
            expected = client.sync_htv405_now if supported else client.restore_retained_counter
            other = client.restore_retained_counter if supported else client.sync_htv405_now
            expected.assert_awaited_once_with("test",device_id="one")
            other.assert_not_awaited()
        self.assertIn("_restore_retained_counter",ast.unparse(cls))

    async def test_command_publishes_new_transaction_despite_refresh_cooldown(self):
        """Replay the old sync snapshot that caused a confirmed run to alert.

        HA's debounced request can return without fetching during its cooldown.
        The valve service must publish the authoritative post-command snapshot
        before returning, including when that snapshot is not yet confirmed.
        """
        for method, action in (("async_open_valve", "open_htv405_zone"),
                               ("async_close_valve", "close_htv405_zone")):
            for outcome in ("waiting_for_confirmation", "watering_confirmed", "failed"):
                with self.subTest(method=method, outcome=outcome):
                    old_id = "previous-synchronization"
                    snapshot = {"rf_control_start_available": True,
                                "rf_control_transaction_id": old_id,
                                "rf_control_transaction_state": "completed"}
                    gateway_snapshot = {**snapshot,
                                        "rf_control_transaction_id": "new-command",
                                        "rf_control_transaction_state": outcome}
                    async def refresh():
                        snapshot.clear()
                        snapshot.update(gateway_snapshot)
                    coordinator = types.SimpleNamespace(
                        htv405_run_minutes={("four", 1): 15},
                        client=types.SimpleNamespace(**{action: AsyncMock()}),
                        # A throttled request returns before the next refresh.
                        async_request_refresh=AsyncMock(),
                        async_refresh=AsyncMock(side_effect=refresh),
                    )
                    entity = types.SimpleNamespace(coordinator=coordinator,
                        decoded_state=snapshot, device_id="four", _zone=1, _token="test-token")
                    callback = _integration_function("valve.py", method, {
                        "HomeAssistantError": RuntimeError,
                        "RainPointLocalError": ValueError,
                        "DEFAULT_BOUNDED_RUN_MINUTES": 1,
                    })
                    await callback(entity)
                    # Run Now's five-second new-ID guard must not mistake the
                    # previous completed sync for this command's result.
                    self.assertNotEqual(old_id, snapshot["rf_control_transaction_id"])
                    self.assertEqual(outcome, snapshot["rf_control_transaction_state"])
                    coordinator.async_refresh.assert_awaited_once()
                    getattr(coordinator.client, action).assert_awaited_once()


class IntegrationMigrationTest(unittest.TestCase):
    def test_one_zone_counter_capability_creates_only_retained_restore_button(self):
        constructor = Mock()
        add = Mock()
        coordinator = types.SimpleNamespace(nodes={}, data={
            "one": {"capabilities": ["retained_counter_restore"]},
            "unqualified": {"capabilities": ["forget"]},
        })
        factory = _integration_function("button.py", "async_add_missing_entities", {
            "callback": lambda fn: fn, "known": set(), "coordinator": coordinator,
            "entry": types.SimpleNamespace(data={}, options={}), "CONF_TOKEN": "token",
            "RainPointRestoreRetainedCounterButton": constructor, "async_add_entities": add,
        })
        factory()
        constructor.assert_called_once_with(coordinator, "one", "")
        add.assert_called_once_with([constructor.return_value])
        factory()
        self.assertEqual(1, constructor.call_count)

    def test_one_zone_gets_sync_window_without_four_zone_duration_controls(self):
        sync, duration, add = Mock(), Mock(), Mock()
        coordinator = types.SimpleNamespace(data={"one":{"model":"HTV145FRF","capabilities":["morning_synchronization"]}})
        factory = _integration_function("number.py","async_add_missing_entities", {
            "callback":lambda f:f,"known":set(),"coordinator":coordinator,
            "entry":types.SimpleNamespace(data={},options={}),"CONF_TOKEN":"token",
            "RainPointMorningSyncWindow":sync,"RainPointHtv405ZoneDuration":duration,
            "multi_zone_numbers":multi_zone_numbers,"async_add_entities":add})
        factory(); factory()
        sync.assert_called_once_with(coordinator,"one","")
        duration.assert_not_called()
        add.assert_called_once_with([sync.return_value])
        import json
        for path in ("strings.json","translations/en.json"):
            self.assertEqual("Sync counter",json.loads((PACKAGE/path).read_text())["entity"]["button"]["resynchronize_counter"]["name"])

    def test_known_sensor_details_use_ha_customizations_and_exact_identity(self):
        entry = types.SimpleNamespace(name_by_user="Right Bed", name="Old name", area_id="garden", config_entries={"gateway"})
        registry = Mock(spec=["async_get_device"])
        registry.async_get_device.return_value = entry
        areas = Mock()
        areas.async_get_area_by_name.return_value = types.SimpleNamespace(id="yard")
        resolve = _integration_function("config_flow.py", "_known_device_details", {
            "DOMAIN": "rainpoint_local",
            "dr": types.SimpleNamespace(async_get=lambda _: registry),
            "ar": types.SimpleNamespace(async_get=lambda _: areas),
        })
        devices = [{"device_id": "saved-sensor", "name": "Gateway name", "area": "Yard",
                    "state": {"rf_paired_endpoint": "12345624"}}]
        self.assertEqual({"name": "Right Bed", "area": "garden"}, resolve(None, devices, "12345624", "gateway"))
        registry.async_get_device.assert_called_with(identifiers={("rainpoint_local", "saved-sensor")})
        self.assertEqual({}, resolve(None, devices, "99995624", "gateway"))
        entry.area_id = None
        self.assertEqual({"name": "Right Bed"}, resolve(None, devices, "12345624", "gateway"))
        registry.async_get_device.return_value = None
        self.assertEqual({"name": "Gateway name", "area": "yard"}, resolve(None, devices, "12345624", "gateway"))

    def test_single_zone_factory_ignores_legacy_four_zone_keys(self):
        constructor = Mock()
        namespace = {name: constructor for name in (
            "RainPointWateringBinarySensor", "RainPointZoneWateringBinarySensor",
            "RainPointReportingBinarySensor", "RainPointControlStartAvailableBinarySensor",
        )}
        namespace["multi_zone_numbers"] = multi_zone_numbers
        factory = _integration_function("binary_sensor.py", "_entities_for_device", namespace)
        state = {"is_watering": False, **{f"zone_{z}_is_watering": None for z in range(1, 5)}}
        entities = factory(None, "single", {"model": "HTV145FRF", "state": state})
        self.assertEqual(["watering"], [key for key, _entity in entities])
        entities = factory(None, "four", {"model": "HTV405FRF", "state": state})
        self.assertEqual(5, len(entities))

    def test_registry_removes_only_unsupported_single_zone_entities(self):
        entity_registry = Mock()
        unique_ids = ["single_watering", "single_last_usage", "single_zone_1_watering",
                      "single_zone_4_watering", "four_zone_4_watering", "four_last_usage"]
        entries = [types.SimpleNamespace(unique_id=uid, entity_id=f"binary_sensor.{uid}",
                                         device_id=uid.split("_")[0], disabled_by=None)
                   for uid in unique_ids]
        registry_devices = [types.SimpleNamespace(id=uid, identifiers={("rainpoint_local", uid)})
                            for uid in ("single", "four")]
        namespace = {
            "DOMAIN": "rainpoint_local", "unsupported_device_entity_ids": unsupported_device_entity_ids,
            "dr": types.SimpleNamespace(async_get=lambda _h: object(), async_entries_for_config_entry=lambda *_: registry_devices),
            "er": types.SimpleNamespace(async_get=lambda _h: entity_registry, async_entries_for_config_entry=lambda *_: entries,
                                         RegistryEntryDisabler=types.SimpleNamespace(INTEGRATION="integration")),
        }
        reconcile = _integration_function("coordinator.py", "_async_reconcile_entity_registry", namespace)
        reconcile(types.SimpleNamespace(hass=None, config_entry_id="entry"), {"single", "four"},
                  {"single": {"model": "HTV145FRF"}, "four": {"model": "HTV405FRF"}})
        self.assertEqual([
            call("binary_sensor.single_zone_1_watering"),
            call("binary_sensor.single_zone_4_watering"),
            call("binary_sensor.four_last_usage"),
        ], entity_registry.async_remove.call_args_list)
        entity_registry.async_update_entity.assert_not_called()

    def test_v1_moves_management_token_from_options(self) -> None:
        version, data, options = migrate_entry_payload(
            1,
            {"host": " gateway.local ", "port": "8787"},
            {"registry_write_token": "secret", "unrelated": True},
        )
        self.assertEqual(3, version)
        self.assertEqual("gateway.local", data["host"])
        self.assertEqual(8787, data["port"])
        self.assertEqual("secret", data["registry_write_token"])
        self.assertEqual({"unrelated": True}, options)

    def test_current_payload_is_idempotent(self) -> None:
        original_data = {"host": "gateway.local", "port": 8787}
        original_options = {"unrelated": True}
        version, data, options = migrate_entry_payload(
            3, original_data, original_options
        )
        self.assertEqual((3, original_data, original_options), (version, data, options))


if __name__ == "__main__":
    unittest.main()
