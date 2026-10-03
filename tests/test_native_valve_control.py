"""Normal gateway control with temporary databases and captured RF fixtures.

No synthetic replay in this module qualifies a live OPEN/CLOSE or rollover.
"""
import copy
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rainpointd_addon"))
from rainpointd.gateway import Gateway
from rainpointd.native_valve_control import CAPABILITY, HANDOFF_CAPABILITY, SCOPE_CAPABILITY
from rainpointd.storage import SQLiteEventStore
from rainpointd.valve_command_phase import build_command, decode_envelope
from rainpointd.valve_protocol import ValveLink
from rainpointd.valve_phase_commands import FullPhaseCommandJournal
from rainpointd.valve_phase_trial import assert_node_available
from tests import test_valve_phase_commands as fixtures
from tests.test_valve_phase_trial import at, NODE
from tests.valve_native_helpers import alter, FailCommit


class NativeGatewayControlTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "gateway.sqlite"
        self.store = SQLiteEventStore(self.path)
        self.addCleanup(self.store.close)
        self.sent = []
        # Deterministic deadlines: captured fixture timestamps are historical.
        timer_patch = patch("rainpointd.gateway.threading.Timer", side_effect=lambda *args: MagicMock())
        self.timer_factory = timer_patch.start()
        self.addCleanup(timer_patch.stop)

    def setup_model(self, model, *, enabled=True, activate=True, qualification=False):
        fixtures.FullPhaseCommandJournalTests.setup_model(self, model)
        if model == "HTV145FRF":
            data = json.loads((ROOT / "research/fixtures/htv145_active_counter_recovery_20260906.json").read_text())
            self.active = data["command_transactions"][0]["independent_state_frame"]
            decoded = bytearray(decode_envelope(self.active).data)
            decoded[3] = 0
            decoded[10:12] = decoded[13:15] = bytes(2)
            self.idle = alter(self.active, data=decoded)
            self.device_id = "fixture-single"
            a, b = [x.hex() for x in decode_envelope(self.request).route]
            self.store.upsert_valve_link(controller_endpoint=a, valve_endpoint=b, model=model,
                device_id=self.device_id, name="Fixture single", area=None, accepted_at=at(-40))
        else:
            data = json.loads((ROOT / "research/fixtures/htv405_local_port2_baseline_20261001.json").read_text())
            self.active, self.idle = [e["frame"] for e in data["events"][1:]]
            self.device_id = "fixture-four"
        self.gateway = Gateway(storage_path=str(self.path), transport="esp32", read_only=False,
            valve_control_enabled=True, native_phase_enabled=enabled)
        self.addCleanup(self.gateway.close)
        self.gateway.set_node_command_sender(lambda node, command: self.sent.append((node, command)))
        self.gateway.update_node(NODE, connected=True, authenticated=True, radio_ready=True,
            capabilities=[CAPABILITY, HANDOFF_CAPABILITY, SCOPE_CAPABILITY, "htv145_control_tx_candidate", "htv145_report_ack_tx",
                          "valve_control_tx_candidate"])
        if model == "HTV145FRF":
            a, b = [x.hex() for x in decode_envelope(self.request).route]
            self.gateway.register(device_id=self.device_id, model=model, name="Fixture",
                state=dict(rf_endpoint_a=a, rf_endpoint_b=b))
        for frame, timestamp in ((self.ack, at(-9)), (self.idle, at(0))):
            self.gateway.observe_rf_frame(frame=frame, state=dict(rf_node_id=NODE, model=model), observed_at=timestamp)
        if activate:
            self.owner = self.gateway.activate_native_valve_candidate(device_id=self.device_id,
                request_frame=self.request, response_frame=self.ack, baseline_at=at(-9),
                idle_frame=self.idle, idle_at=at(0), port=self.port, now=at(0),
                qualification_seconds=300 if qualification else None, maximum_commands=2 if qualification else None)
            self.receipt(stage="ready", phase=self.owner["next_phase"], command_id=self.owner["epoch"])

    def receipt(self, *, stage, phase, command_id, frame=None, now=at(1), node=NODE):
        return self.gateway.observe_native_valve_receipt(node, dict(epoch=self.owner["epoch"],
            command_id=command_id, stage=stage, phase=phase, frame=frame,
            qualification_remaining_ms=200000), now=now)

    def command(self, *, action="open", seconds=60, now=at(10), qualified=False):
        with patch("rainpointd.gateway.datetime") as clock:
            clock.now.return_value = datetime.fromisoformat(now)
            return self.gateway.request_valve_control(device_id=self.device_id,
                action=action, zone=self.port, duration_seconds=seconds if action == "open" else None,
                _native_qualification_epoch=self.owner["epoch"] if qualified else None)

    def snapshot(self):
        return self.gateway._native_control.owner(device_id=self.device_id)

    def state(self, now=at(11)):
        return next(d["state"] for d in self.gateway.devices(now=datetime.fromisoformat(now))
                    if d["device_id"] == self.device_id)

    def observe(self, frame, *, now=at(11), node=NODE):
        self.gateway.observe_rf_frame(frame=frame, state=dict(rf_node_id=node, model=self.model), observed_at=now)

    def ack_for(self, tx):
        return fixtures.FullPhaseCommandJournalTests.result(self, tx)

    def maintenance(self, operation, now=at(71)):
        return self.gateway.request_native_valve_maintenance(
            device_id=self.device_id, operation=operation, now=now)

    def maintenance_receipt(self, handoff, *, now=at(72), **changes):
        tx = self.snapshot()["commands"][-1]
        message = dict(epoch=self.owner["epoch"], command_id=tx["command_id"], frame=tx["frame"],
            phase=tx["phase"], stage="released" if handoff["kind"] == "handback" else "accepted",
            maintenance_id=handoff["id"], maintenance_kind=handoff["kind"],
            legacy_counter=handoff["legacy_counter"], qualification_remaining_ms=200000)
        return self.gateway.observe_native_valve_receipt(NODE, {**message, **changes}, now=now)

    def completed_run(self, *, physical=True):
        self.command()
        tx = self.snapshot()["commands"][-1]
        self.observe(self.ack_for(tx))
        self.receipt(stage="accepted", phase=tx["phase"], command_id=tx["command_id"], frame=tx["frame"])
        if physical:
            self.observe(self.active, now=at(12))
        else:
            self.state(at(26))
        self.observe(self.idle, now=at(70))
        return self.snapshot()["commands"][-1]

    def check_open_close_open(self, model):
        """Rehearse the next dry trial through public controls, not allocator-only."""
        self.setup_model(model)
        phases = []
        baseline = self.owner['next_phase']
        for index, action in enumerate(('open', 'close', 'open')):
            started = 10 + index * 20
            self.command(action=action, now=at(started))
            tx = self.snapshot()['commands'][-1]
            phases.append(tx['phase'])
            self.observe(self.ack_for(tx), now=at(started+1))
            self.receipt(stage='accepted', phase=tx['phase'], command_id=tx['command_id'],
                         frame=tx['frame'], now=at(started+1))
            self.observe(self.active if action == 'open' else self.idle, now=at(started+2))
            state = self.state(at(started+3))
            self.assertEqual(state['rf_control_transaction_state'], 'confirmed')
            self.assertEqual(state['is_watering'], action == 'open')
            self.assertEqual(decode_envelope(tx['frame']).phase, tx['phase'])
        self.assertEqual(phases, [baseline, baseline+1, baseline+2])
        self.assertEqual([command['type'] for _, command in self.sent],
                         ['valve_native_adopt'] + ['valve_native_command'] * 3)

    def test_single_public_open_close_open_uses_three_adjacent_phases(self):
        self.check_open_close_open('HTV145FRF')

    def test_four_public_open_close_open_uses_three_adjacent_phases(self):
        self.check_open_close_open('HTV405FRF')

    def test_recovery_requires_exact_positive_and_idle_preserves_failed_watering(self):
        self.setup_model("HTV145FRF")
        self.completed_run(physical=False)
        before = copy.deepcopy(self.snapshot())
        self.sent.clear()
        handoff = self.maintenance("recover")
        self.assertTrue(self.state(at(71))["rf_control_transaction_active"])
        self.assertFalse(self.maintenance_receipt(handoff, maintenance_id="00"*16))
        self.assertEqual(self.snapshot()["state"], "recovering")
        self.assertTrue(self.maintenance_receipt(handoff))
        after = self.snapshot()
        self.assertEqual(after["transaction"], before["transaction"])
        self.assertEqual(after["commands"], before["commands"])
        self.assertEqual(after["next_phase"], before["next_phase"])
        self.assertEqual(after["state"], "ready")
        self.assertEqual(after["handoff"]["previous_failure"], "missing_independent_confirmation")
        self.assertTrue(self.state(at(72))["rf_control_start_available"])
        self.assertEqual([c["type"] for _, c in self.sent], ["valve_native_recover"])

    def test_missing_and_late_ack_never_recover(self):
        self.setup_model("HTV405FRF")
        self.command()
        self.state(at(26)); self.observe(self.idle, now=at(70))
        with self.assertRaises(RuntimeError): self.maintenance("recover")
        tx = self.snapshot()["commands"][-1]
        self.observe(self.ack_for(tx), now=at(71))
        with self.assertRaises(RuntimeError): self.maintenance("recover", at(72))
        self.assertEqual(self.snapshot()["state"], "uncertain")

    def test_recovery_rejects_early_idle_and_requires_handoff_capability(self):
        self.setup_model("HTV405FRF")
        self.command(); tx = self.snapshot()["commands"][-1]
        self.observe(self.ack_for(tx))
        self.receipt(stage="accepted", phase=tx["phase"], command_id=tx["command_id"], frame=tx["frame"])
        self.state(at(26)); self.observe(self.idle, now=at(27))
        with self.assertRaises(RuntimeError): self.maintenance("recover", at(30))
        self.observe(self.idle, now=at(200))
        with self.assertRaises(RuntimeError): self.maintenance("recover", at(321))
        self.gateway.update_node(NODE, capabilities=[CAPABILITY])
        with self.assertRaises(RuntimeError): self.maintenance("recover", at(201))

    def check_handback(self, model):
        self.setup_model(model)
        tx = self.completed_run()
        self.sent.clear()
        before = self.store.valve_phase_migration_state(model, self.storage_key)
        handoff = self.maintenance("handback")
        self.assertTrue(self.store.native_valve_node_owned(NODE))
        self.assertEqual(self.store.valve_phase_migration_state(model, self.storage_key), before)
        with self.assertRaises(RuntimeError): self.command(now=at(72))
        self.assertFalse(self.maintenance_receipt(handoff, legacy_counter=2))
        self.assertTrue(self.maintenance_receipt(handoff))
        self.assertIsNone(self.snapshot())
        retired = self.store.native_valve_commands()[0]
        self.assertEqual(retired["state"], "handed_back")
        self.assertEqual(retired["commands"][-1], tx)
        current = self.store.valve_phase_migration_state(model, self.storage_key)
        counter = (tx["phase"]+1)//2
        self.assertEqual(current["next_counter"], (128|counter) if model=="HTV145FRF" else counter)
        self.assertEqual(current["latest_send"], at(10))
        self.assertEqual([c["type"] for _, c in self.sent], ["valve_native_handback"])
        assert_node_available(self.store, NODE)

    def test_single_handback_is_atomic_and_preserves_history(self):
        self.check_handback("HTV145FRF")

    def test_four_handback_is_atomic_and_preserves_history(self):
        self.check_handback("HTV405FRF")

    def test_handback_commit_failure_keeps_counter_and_exclusive_owner(self):
        self.setup_model("HTV145FRF")
        self.completed_run(); handoff = self.maintenance("handback")
        before = self.store.valve_phase_migration_state(self.model, self.storage_key)
        original = self.gateway._store._connection
        with patch.object(self.gateway._store, "_connection", FailCommit(original)):
            with self.assertRaises(Exception): self.maintenance_receipt(handoff)
        self.assertEqual(before, self.store.valve_phase_migration_state(self.model, self.storage_key))
        self.assertTrue(self.store.native_valve_node_owned(NODE))
        self.assertTrue(self.maintenance_receipt(handoff))

    def test_handoff_timeout_is_visible_and_only_explicit_no_rf_repeat(self):
        self.setup_model("HTV405FRF")
        self.completed_run(); handoff = self.maintenance("handback")
        sent = copy.deepcopy(self.sent)
        state = self.state(at(87))
        self.assertEqual(state["rf_control_transaction_state"], "unresolved")
        self.assertEqual(state["rf_control_unavailable_reason"], "native_handoff_confirmation_missing")
        self.assertEqual(self.sent, sent)
        self.maintenance("handback", at(88))
        self.assertEqual(self.sent[-1][1], handoff["message"])
        self.assertTrue(self.maintenance_receipt(handoff, now=at(89)))

    def test_odd_close_cannot_return_to_unqualified_legacy_recipe(self):
        self.setup_model("HTV405FRF")
        self.completed_run()
        self.command(action="close", now=at(80))
        tx = self.snapshot()["commands"][-1]
        self.observe(self.ack_for(tx), now=at(81))
        self.receipt(stage="accepted", phase=tx["phase"], command_id=tx["command_id"], frame=tx["frame"], now=at(81))
        self.observe(self.idle, now=at(82))
        self.assertEqual(tx["phase"], 3)
        with self.assertRaises(RuntimeError): self.maintenance("handback", at(83))

    def test_unknown_command_result_invalidates_maintenance_proof(self):
        self.setup_model("HTV405FRF")
        tx = self.completed_run()
        self.observe(alter(self.ack_for(tx), phase=tx["phase"]+1), now=at(71))
        self.assertEqual(self.snapshot()["failure"], "unrecognized_native_result")
        for operation in ("recover", "handback"):
            with self.assertRaises(RuntimeError): self.maintenance(operation, at(72))

    def test_negative_result_cannot_be_recovered_from_a_later_idle(self):
        self.setup_model("HTV145FRF"); self.command()
        tx = self.snapshot()["commands"][-1]
        data = bytearray(decode_envelope(self.ack_for(tx)).data); data[0] = 6
        self.observe(alter(self.ack_for(tx), data=data))
        self.receipt(stage="uncertain", phase=tx["phase"], command_id=tx["command_id"], frame=tx["frame"])
        self.observe(self.idle, now=at(70))
        with self.assertRaises(RuntimeError): self.maintenance("recover")

    def test_gateway_restart_waits_for_correlated_release_without_replaying(self):
        self.setup_model("HTV405FRF")
        self.completed_run(); handoff = self.maintenance("handback")
        self.gateway.close(); self.sent.clear()
        self.gateway = Gateway(storage_path=str(self.path), transport="esp32", read_only=False,
            valve_control_enabled=True, native_phase_enabled=True)
        self.addCleanup(self.gateway.close)
        self.gateway.set_node_command_sender(lambda node, command: self.sent.append((node, command)))
        self.gateway.update_node(NODE, connected=True, authenticated=True,
            capabilities=[CAPABILITY, HANDOFF_CAPABILITY])
        with self.assertRaises(RuntimeError): self.command(now=at(74))
        self.assertFalse(self.sent)
        self.assertTrue(self.store.native_valve_node_owned(NODE))
        self.assertTrue(self.maintenance_receipt(handoff, now=at(75)))
        self.assertFalse(self.store.native_valve_node_owned(NODE))
        self.assertFalse(self.sent)

    def test_transport_checks_exact_maintenance_proof(self):
        self.setup_model("HTV145FRF")
        self.completed_run(); handoff = self.maintenance("handback")
        self.gateway._native_control.authorize(NODE, handoff["message"])
        with self.assertRaises(ValueError):
            self.gateway._native_control.authorize(NODE, {**handoff["message"], "phase": 1})
        with self.assertRaises(ValueError):
            self.gateway._native_control.authorize(NODE, {**handoff["message"], "idle_frame": self.active})

    def test_bounded_qualification_blocks_ha_wrong_outlet_and_wrong_duration(self):
        self.setup_model("HTV405FRF", qualification=True)
        admission = next(c for _,c in self.sent if c["type"]=="valve_native_adopt")
        self.gateway._native_control.authorize(NODE, admission)
        for changes in ({"port":1}, {"maximum_commands":0}, {"qualification_seconds":900}):
            with self.assertRaises(ValueError):
                self.gateway._native_control.authorize(NODE, {**admission, **changes})
        self.sent.clear()
        self.assertFalse(self.state()["rf_control_available"])
        self.assertEqual(self.state()["rf_control_unavailable_reason"], "native_qualification_locked")
        with self.assertRaises(PermissionError): self.command()
        with self.assertRaises(PermissionError): self.command(seconds=120, qualified=True)
        with self.assertRaises(PermissionError): self.command(action="close", qualified=True)
        with self.assertRaises(PermissionError):
            self.gateway.request_valve_control(device_id=self.device_id, action="open", zone=1,
                duration_seconds=60, _native_qualification_epoch=self.owner["epoch"])
        self.assertFalse(self.sent)
        self.assertEqual(self.snapshot()["commands"], [])
        self.command(qualified=True)
        self.assertEqual(len(self.snapshot()["commands"]), 1)

    def test_qualification_expiry_and_restart_cannot_restore_rf_permission(self):
        self.setup_model("HTV145FRF", qualification=True)
        with self.assertRaises(PermissionError): self.command(qualified=True, now=at(301))
        self.command(qualified=True)
        tx = self.snapshot()["commands"][-1]
        self.observe(self.ack_for(tx)); self.observe(self.active, now=at(12))
        self.receipt(stage="accepted", phase=tx["phase"], command_id=tx["command_id"], frame=tx["frame"])
        self.observe(self.idle, now=at(70))
        message = dict(epoch=self.owner["epoch"], command_id=tx["command_id"], phase=tx["phase"],
            frame=tx["frame"], stage="accepted", qualification_remaining_ms=0)
        self.gateway.observe_native_valve_receipt(NODE, message, now=at(71))
        with self.assertRaises(PermissionError): self.command(qualified=True, now=at(72))
        # Expired RF permission never blocks explicit non-transmitting handback.
        self.observe(self.idle, now=at(301))
        handoff = self.maintenance("handback", at(302))
        self.assertTrue(self.maintenance_receipt(handoff, now=at(303), qualification_remaining_ms=0))

    def test_qualification_budget_consumes_attempts_not_successes(self):
        self.setup_model("HTV405FRF", qualification=True)
        for start in (10, 90):
            self.command(qualified=True, now=at(start))
            tx = self.snapshot()["commands"][-1]
            self.observe(self.ack_for(tx), now=at(start+1))
            self.receipt(stage="accepted", phase=tx["phase"], command_id=tx["command_id"], frame=tx["frame"], now=at(start+1))
            self.state(at(start+16))  # Preserve an original missing-state failure.
            self.observe(self.idle, now=at(start+60))
            handoff = self.maintenance("recover", at(start+61))
            self.maintenance_receipt(handoff, now=at(start+62))
        with self.assertRaises(PermissionError): self.command(qualified=True, now=at(180))
        self.assertEqual(len(self.snapshot()["commands"]), 2)
        self.assertEqual(sum(c["type"]=="valve_native_command" for _,c in self.sent), 2)

    def test_qualification_requires_distinct_radio_capability(self):
        self.setup_model("HTV405FRF", activate=False)
        self.gateway.update_node(NODE, capabilities=[CAPABILITY, HANDOFF_CAPABILITY])
        with self.assertRaises(RuntimeError):
            self.gateway.activate_native_valve_candidate(device_id=self.device_id, request_frame=self.request,
                response_frame=self.ack, baseline_at=at(-9), idle_frame=self.idle, idle_at=at(0),
                port=2, now=at(0), qualification_seconds=300, maximum_commands=2)
        self.assertFalse(self.store.native_valve_commands())

    def test_stale_storage_receipt_cannot_commit_handback(self):
        self.setup_model("HTV405FRF")
        self.completed_run(); self.maintenance("handback")
        stale = self.store.metadata_value(self.journal.key)
        self.state(at(87))
        with self.assertRaises(RuntimeError):
            self.store.complete_native_valve_handback(self.journal.key, expected=stale, observed_at=at(88))
        self.assertTrue(self.store.native_valve_node_owned(NODE))

    def test_new_epoch_archives_only_verified_handback(self):
        self.setup_model("HTV405FRF")
        self.completed_run(); handoff = self.maintenance("handback")
        self.maintenance_receipt(handoff)
        old = self.store.metadata_value(self.journal.key)
        # A subsequent accepted legacy command is required, not the old baseline.
        request = build_command(model=self.model, link=ValveLink(*decode_envelope(self.request).route),
            phase=3, action="open", port=2, duration_seconds=60, residue=0x4f03, selector=5).hex()
        ack = alter(self.ack, phase=3)
        self.store.reserve_htv405_command(valve_endpoint=self.storage_key, node_id=NODE,
            command_id="aa"*16, action="open", zone=2, duration_seconds=60, started_at=at(80))
        self.observe(ack, now=at(81))
        self.store.confirm_valve_control_response(valve_endpoint=self.storage_key, node_id=NODE,
            sequence=1, next_sequence=2, zone=2, watering=True, center_hz=433518527,
            observed_at=at(81), frame=ack, run_started_at=at(80), run_duration_seconds=60, expected_idle_at=at(140))
        self.observe(self.idle, now=at(140))
        fresh = self.gateway.activate_native_valve_candidate(device_id=self.device_id,
            request_frame=request, response_frame=ack, baseline_at=at(81), idle_frame=self.idle,
            idle_at=at(140), port=self.port, now=at(140))
        self.assertNotEqual(fresh["epoch"], self.owner["epoch"])
        self.assertEqual(self.store.metadata_value("valve_native_phase_archive_v1:"+self.owner["epoch"]), old)
        self.assertEqual(len(self.store.native_valve_commands()), 1)

    def test_standard_controls_require_radio_receipt_ack_and_independent_state(self):
        self.check_standard_controls("HTV145FRF")

    def test_four_zone_standard_controls_require_all_evidence(self):
        self.check_standard_controls("HTV405FRF")

    def check_standard_controls(self, model):
        self.setup_model(model)
        self.sent.clear()
        self.command()
        tx = self.snapshot()["commands"][-1]
        self.assertEqual([c["type"] for _, c in self.sent], ["valve_native_command"])
        self.assertTrue(self.state()["rf_control_transaction_active"])
        self.observe(self.ack_for(tx))
        self.assertTrue(self.state()["rf_control_transaction_active"])
        self.receipt(stage="accepted", phase=tx["phase"], command_id=tx["command_id"], frame=tx["frame"])
        self.assertTrue(self.state()["rf_control_transaction_active"])
        cursor = self.gateway.latest_event_id()
        self.observe(self.active, now=at(12))
        self.assertTrue(any(e["event_type"] == "native_valve_control_updated"
                            for e in self.gateway.events(since=cursor)))
        self.assertEqual(self.state(at(12))["rf_control_transaction_state"], "confirmed")
        self.assertFalse(self.state(at(12))["rf_control_start_available"])
        self.assertTrue(self.state(at(12))["is_watering"])
        self.observe(self.idle, now=at(70))
        self.assertTrue(self.state(at(70))["rf_control_start_available"])

    def test_duplicate_click_no_new_reservation_and_close_uses_adjacent_phase(self):
        self.setup_model("HTV145FRF"); self.command()
        tx = self.snapshot()["commands"][-1]
        with self.assertRaises(RuntimeError): self.command(now=at(11))
        self.assertEqual(len(self.snapshot()["commands"]), 1)
        self.observe(self.active, now=at(11))
        self.observe(self.ack_for(tx), now=at(12))
        self.receipt(stage="accepted", phase=tx["phase"], command_id=tx["command_id"], frame=tx["frame"], now=at(13))
        self.command(action="close", now=at(30))
        close = self.snapshot()["commands"][-1]
        self.assertEqual(close["phase"], tx["phase"] + 1)
        self.observe(self.ack_for(close), now=at(31))
        self.receipt(stage="accepted", phase=close["phase"], command_id=close["command_id"], frame=close["frame"], now=at(31))
        self.observe(self.idle, now=at(32))
        self.assertEqual(self.state(at(32))["rf_control_transaction_state"], "confirmed")

    def test_missing_result_or_independent_state_is_failure_without_retry(self):
        self.setup_model("HTV405FRF"); self.command()
        tx = self.snapshot()["commands"][-1]
        self.observe(self.ack_for(tx))
        self.receipt(stage="accepted", phase=tx["phase"], command_id=tx["command_id"], frame=tx["frame"])
        state = self.state(at(26))
        self.assertEqual(state["rf_control_transaction_state"], "failed")
        self.assertEqual(state["rf_control_transaction_error"], "missing_independent_confirmation")
        with self.assertRaises(RuntimeError): self.command(now=at(30))
        self.assertEqual(len(self.snapshot()["commands"]), 1)
        self.observe(self.active, now=at(31))
        self.assertEqual(self.state(at(31))["rf_control_transaction_state"], "failed")

    def test_confirmation_deadline_publishes_failure_without_snapshot_polling(self):
        self.setup_model("HTV405FRF"); self.command()
        tx = self.snapshot()["commands"][-1]
        self.observe(self.ack_for(tx))
        self.receipt(stage="accepted", phase=tx["phase"], command_id=tx["command_id"], frame=tx["frame"])
        cursor = self.gateway.latest_event_id()
        callback = self.timer_factory.call_args.args[1]
        sent = list(self.sent)
        with patch("rainpointd.gateway.datetime") as clock:
            clock.now.return_value = datetime.fromisoformat(at(26))
            callback()
        self.assertEqual(self.snapshot()["transaction"]["state"], "failed")
        self.assertEqual(self.snapshot()["failure"], "missing_independent_confirmation")
        self.assertEqual(self.sent, sent)
        self.assertTrue(any(e["event_type"] == "native_valve_control_updated"
                            for e in self.gateway.events(since=cursor)))

    def test_wrong_receipt_and_neighbor_rx_cannot_unlock_counter(self):
        self.setup_model("HTV145FRF"); self.command()
        tx = self.snapshot()["commands"][-1]
        self.assertFalse(self.receipt(stage="accepted", phase=tx["phase"], command_id=tx["command_id"], frame=self.request))
        self.observe(self.ack_for(tx), node="rp-112233445566")
        self.assertEqual(self.snapshot()["state"], "awaiting_result")
        self.assertEqual(self.state(at(26))["rf_control_transaction_state"], "failed")

    def test_negative_result_and_late_positive_leave_exact_attempt_uncertain(self):
        self.setup_model("HTV405FRF"); self.command()
        tx = self.snapshot()["commands"][-1]
        ack = self.ack_for(tx)
        data = bytearray(decode_envelope(ack).data); data[0] = 6
        self.observe(alter(ack, data=data))
        self.assertEqual(self.state()["rf_control_transaction_error"], "negative_native_result")
        self.observe(ack, now=at(12)); self.observe(self.active, now=at(13))
        self.assertEqual(self.snapshot()["state"], "uncertain")
        self.assertEqual(self.snapshot()["commands"][-1]["frame"], tx["frame"])

    def test_restart_never_replays_attempt_or_falls_back_when_flag_disabled(self):
        self.setup_model("HTV145FRF"); self.command()
        before = copy.deepcopy(self.snapshot())
        self.gateway.close()
        self.sent.clear()
        self.gateway = Gateway(storage_path=str(self.path), read_only=False, valve_control_enabled=True)
        self.addCleanup(self.gateway.close)
        self.gateway.set_node_command_sender(lambda *args: self.sent.append(args))
        self.gateway.update_node(NODE, connected=True, authenticated=True, capabilities=[CAPABILITY])
        with self.assertRaises(RuntimeError): self.command(now=at(12))
        self.assertFalse(self.sent)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.state(at(26))["rf_control_transaction_state"], "failed")

    def test_native_owner_blocks_old_reservations_and_sync_without_changing_legacy_bytes(self):
        self.setup_model("HTV145FRF")
        before = self.store.valve_phase_migration_state(self.model, self.storage_key)
        with self.assertRaises(RuntimeError): assert_node_available(self.store, NODE)
        with self.assertRaises(RuntimeError):
            self.store.reserve_htv145_command(valve_endpoint=self.storage_key,
                command_id="cd"*16, action="open", duration_seconds=60, started_at=at(30), expected_idle_at=at(90))
        with self.assertRaises(RuntimeError):
            self.store.synchronize_htv145_control_counter(valve_endpoint=self.storage_key,
                next_sequence=129, source="matching_immediate_response", observed_at=at(30))
        with self.assertRaises(RuntimeError):
            self.store.delete_htv145_control(self.storage_key)
        with self.assertRaises(RuntimeError):
            self.store.reserve_htv145_revocation(self.storage_key, "cd"*16)
        self.assertEqual(before, self.store.valve_phase_migration_state(self.model, self.storage_key))

    def test_native_four_zone_owner_blocks_profile_reassignment_reseed_and_deletion(self):
        self.setup_model("HTV405FRF")
        before = self.store.valve_phase_migration_state(self.model, self.storage_key)
        profile = before["profile"]
        with self.assertRaises(RuntimeError):
            self.store.update_valve_control_profile(valve_endpoint=self.storage_key,
                node_id=NODE, companion_endpoint=profile["control_companion_endpoint"],
                selector=profile["control_selector"], frequency_offset_hz=0, observed_at=at(30))
        with self.assertRaises(RuntimeError):
            self.store.assign_htv405_control_node(valve_endpoint=self.storage_key,
                node_id=NODE, observed_at=at(30))
        with self.assertRaises(RuntimeError):
            self.store.synchronize_htv405_control_counter(valve_endpoint=self.storage_key,
                node_id=NODE, next_sequence=1, source="authenticated_command_response", observed_at=at(30))
        with self.assertRaises(RuntimeError):
            self.store.forget_valve_registry_device(self.device_id, suppressed_at=at(30))
        self.assertEqual(before, self.store.valve_phase_migration_state(self.model, self.storage_key))

    def test_transport_authorization_requires_attempted_exact_bytes(self):
        self.setup_model("HTV405FRF"); self.command()
        node, message = self.sent[-1]
        self.gateway._native_control.authorize(node, message)
        for fields in (dict(frame=self.request), dict(epoch="ff"*16), dict(phase=63), dict(port=4)):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.gateway._native_control.authorize(node, {**message, **fields})

    def test_dispatch_exception_and_matching_radio_error_fail_immediately(self):
        self.setup_model("HTV405FRF")
        def broken(*args):
            raise ConnectionError("ambiguous transport write")
        self.gateway.set_node_command_sender(broken)
        with self.assertRaises(ConnectionError): self.command()
        self.assertEqual(self.state()["rf_control_transaction_error"], "transport_dispatch_uncertain")
        self.assertEqual(len(self.snapshot()["commands"]), 1)
        tx = self.snapshot()["commands"][-1]
        self.assertFalse(self.gateway.observe_native_valve_error(NODE, dict(command_id="ef"*16), now=at(11)))
        self.assertTrue(self.gateway.observe_native_valve_error(NODE, dict(command_id=tx["command_id"]), now=at(11)))
        self.assertEqual(self.state()["rf_control_transaction_error"], "radio_rejected_native_command")

    def test_reconnect_requires_new_exact_radio_receipt_without_replaying(self):
        self.setup_model("HTV145FRF"); self.command()
        tx = self.snapshot()["commands"][-1]
        self.observe(self.ack_for(tx))
        self.receipt(stage="accepted", phase=tx["phase"], command_id=tx["command_id"], frame=tx["frame"])
        self.observe(self.active, now=at(12)); self.observe(self.idle, now=at(70))
        self.gateway.update_node(NODE, connected=False)
        self.gateway.update_node(NODE, connected=True)
        with self.assertRaises(RuntimeError): self.command(now=at(80))
        self.assertFalse(self.state(at(80))["rf_control_start_available"])
        self.assertTrue(self.receipt(stage="accepted", phase=tx["phase"], command_id=tx["command_id"], frame=tx["frame"], now=at(81)))
        self.assertTrue(self.state(at(81))["rf_control_start_available"])
        self.assertEqual(len(self.snapshot()["commands"]), 1)

    def test_failed_close_keeps_run_stop_deadline_and_never_claims_idle(self):
        self.setup_model("HTV405FRF"); self.command()
        tx = self.snapshot()["commands"][-1]
        self.observe(self.ack_for(tx))
        self.receipt(stage="accepted", phase=tx["phase"], command_id=tx["command_id"], frame=tx["frame"])
        self.observe(self.active, now=at(12))
        self.command(action="close", now=at(30))
        self.assertEqual(self.state(at(46))["rf_control_transaction_state"], "failed")
        self.assertTrue(self.state(at(101))["rf_control_overdue"])
        self.assertTrue(self.state(at(101))["is_watering"])
        self.observe(self.idle, now=at(102))
        self.assertFalse(self.state(at(102))["is_watering"])
        self.assertFalse(self.state(at(102))["rf_control_overdue"])
        self.assertFalse(self.state(at(102))["rf_control_start_available"])

    def test_admission_requires_explicit_opt_in_and_retained_real_idle(self):
        self.setup_model("HTV145FRF", enabled=False, activate=False)
        with self.assertRaises(RuntimeError):
            self.gateway.activate_native_valve_candidate(device_id=self.device_id, request_frame=self.request,
                response_frame=self.ack, baseline_at=at(-9), idle_frame=self.idle, idle_at=at(0), port=1, now=at(0))
        self.gateway._native_control.enabled = True
        with self.assertRaises(ValueError):
            self.gateway.activate_native_valve_candidate(device_id=self.device_id, request_frame=self.request,
                response_frame=self.ack, baseline_at=at(-9), idle_frame=self.idle, idle_at=at(1), port=1, now=at(1))
        self.assertFalse(self.store.native_valve_commands())

    def test_owner_duplicate_idle_remains_admissible_without_duplicate_logical_event(self):
        self.setup_model("HTV405FRF", activate=False)
        before = self.gateway.info()["latest_event_id"]
        self.gateway.observe_rf_frame(frame=self.idle, observed_at=at(1),
            state=dict(rf_node_id="secondary", rf_receiver_id="secondary", model=self.model))
        duplicate = self.gateway.observe_rf_frame(frame=self.idle, observed_at=at(2),
            state=dict(rf_node_id=NODE, rf_receiver_id=NODE, model=self.model))
        self.assertTrue(duplicate["deduplicated"])
        self.assertEqual(self.gateway.info()["latest_event_id"], before + 1)
        reopened = SQLiteEventStore(self.path)
        try:
            self.assertTrue(reopened.has_receiver_observation(NODE, self.idle, at(2)))
            self.assertFalse(reopened.has_receiver_observation(NODE, self.idle, at(3)))
            self.assertFalse(reopened.has_receiver_observation("other-owner", self.idle, at(2)))
        finally:
            reopened.close()
        self.gateway._events.clear()  # Admission must not depend on memory cadence.
        owner = self.gateway.activate_native_valve_candidate(device_id=self.device_id,
            request_frame=self.request, response_frame=self.ack, baseline_at=at(-9),
            idle_frame=self.idle, idle_at=at(2), port=self.port, now=at(2))
        self.assertTrue(owner["active"])

    def test_network_receive_mode_does_not_override_explicit_valve_control(self):
        self.setup_model("HTV405FRF", activate=False)
        self.gateway.read_only = True
        self.owner = self.gateway.activate_native_valve_candidate(device_id=self.device_id,
            request_frame=self.request, response_frame=self.ack, baseline_at=at(-9),
            idle_frame=self.idle, idle_at=at(0), port=self.port, now=at(0))
        self.receipt(stage="ready", phase=self.owner["next_phase"], command_id=self.owner["epoch"])
        self.command()
        self.assertEqual(len(self.snapshot()["commands"]), 1)
        self.gateway._valve_control_enabled = False
        with self.assertRaises(PermissionError):
            self.maintenance("recover")

    def test_four_zone_routine_idle_uses_no_cycling_field_as_port(self):
        self.setup_model("HTV405FRF", activate=False)
        for cycle in (1, 4):
            idle = alter(self.idle, data=bytes.fromhex("040e01009f00000000810000ad0000")[:2]
                + bytes((cycle,)) + bytes.fromhex("009f00000000810000ad0000"))
            report = self.gateway._native_control._physical(dict(model=self.model,
                baseline_response=self.ack, selector=4), idle)
            self.assertEqual(report, dict(watering=False, port=0, remaining=0, requested=0))
            data=bytearray(decode_envelope(idle).data);data[3]=0x41
            self.assertIsNone(self.gateway._native_control._physical(dict(model=self.model,
                baseline_response=self.ack, selector=4), alter(idle,data=data)))
            data[3]=0;data[13]=60
            self.assertIsNone(self.gateway._native_control._physical(dict(model=self.model,
                baseline_response=self.ack, selector=4), alter(idle,data=data)))
