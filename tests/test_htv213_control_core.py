"""Ordinary model controls and compatibility with existing canary records."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rainpointd_addon"))
from rainpointd.htv213_control import ControlJournal
from rainpointd.htv213_control_trial import ControlJournal as TrialJournal
from rainpointd.storage import SQLiteEventStore
from research.pairing_native_transcripts import decode
from tests.test_valve_configuration import alter

NODE = "rp-001122334455"


class Htv213ControlCoreTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "events.sqlite"
        self.store = SQLiteEventStore(self.path)
        self.addCleanup(lambda: self.store.close())
        self.journal = ControlJournal(self.store)
        self.identity = dict(node_id=NODE, controller="a2446688", valve="91556677",
                             selector=11, acknowledged_phase=1, evidence_id="ab" * 16)
        self.key = self.journal.seed(**self.identity)
        self.events = json.loads((ROOT / "research/fixtures/htv213_local_post_battery_control_20261003.json").read_text())["events"]

    def reserve(self, journal=None, key=None, **changes):
        return (journal or self.journal).reserve(key or self.key, **{
            "action": "open", "port": 1, "seconds": 60, **changes})

    def finish(self, journal=None, key=None, phase=2):
        journal = journal or self.journal
        for event in self.events:
            if event["direction"] != "device":
                continue
            frame = event["frame"]
            if decode(frame).command == 0xa1 and phase != 2:
                frame = alter(frame, phase=phase)
            journal.observe(key or self.key, node_id=NODE, frame=frame)

    def test_ordinary_interface_does_not_expose_experimental_probes(self):
        self.assertFalse(hasattr(self.journal, "reserve_boundary_probe"))
        self.assertFalse(hasattr(self.journal, "reserve_crc_retrial"))
        for extra in ({"phase": 62}, {"dry_confirmed": True}, {"authorization_id": "cd" * 16}):
            with self.assertRaises(TypeError):
                self.reserve(**extra)
        self.assertEqual(self.journal.snapshot(self.key)["next_phase"], 2)

    def test_post_battery_capture_completes_without_counter_reset(self):
        tx = self.reserve()
        self.assertEqual(tx["phase"], 2)
        self.journal.dispatch(self.key, tx, lambda *_: None)
        self.finish()
        record = self.journal.snapshot(self.key)
        self.assertEqual(record["state"], "complete")
        self.assertEqual(record["transaction"]["elapsed_seconds"], 60)
        self.assertEqual(record["next_phase"], 3)
        self.assertEqual(self.store.valve_registry(), [])

    def test_existing_trial_reservation_survives_switch_to_model_and_restart(self):
        trial = TrialJournal(self.store)
        tx = trial.reserve(self.key, action="open", port=1, seconds=60, dry_confirmed=True)
        before = trial.snapshot(self.key)
        self.store.close()
        self.store = SQLiteEventStore(self.path)
        self.journal = ControlJournal(self.store)
        self.assertEqual(self.journal.seed(**self.identity), self.key)
        self.assertEqual(self.journal.snapshot(self.key), before)
        self.journal.dispatch(self.key, tx, lambda *_: None)
        with self.assertRaises(ValueError):
            trial = TrialJournal(self.store)
            trial.dispatch(self.key, tx, lambda *_: self.fail("duplicate"))
        self.finish()
        next_tx = trial.reserve(self.key, action="open", port=2, seconds=60, dry_confirmed=True)
        self.assertEqual(next_tx["phase"], 3)

    def test_attempted_command_is_never_replayed_or_reseeded_on_restart(self):
        tx = self.reserve()
        with self.assertRaises(ConnectionError):
            self.journal.dispatch(self.key, tx, lambda *_: (_ for _ in ()).throw(ConnectionError()))
        before = self.journal.snapshot(self.key)
        self.store.close()
        self.store = SQLiteEventStore(self.path)
        self.journal = ControlJournal(self.store)
        self.journal.seed(**self.identity)
        self.assertEqual(self.journal.snapshot(self.key), before)
        with self.assertRaises(ValueError):
            self.journal.dispatch(self.key, tx, lambda *_: self.fail("replay"))
        with self.assertRaises(ValueError):
            self.reserve()
        with self.assertRaises(ValueError):
            self.reserve(action="close", seconds=0)

    def test_multiple_associations_keep_transactions_and_counters_separate(self):
        second_valve = "91556678"
        second = self.journal.seed(**{**self.identity, "valve": second_valve, "acknowledged_phase": 8})
        tx = self.reserve()
        other = self.reserve(key=second, port=2)
        self.journal.dispatch(self.key, tx, lambda *_: None)
        self.journal.dispatch(second, other, lambda *_: None)
        before = self.journal.snapshot(second)
        self.finish()
        self.assertEqual(self.journal.snapshot(second), before)
        self.assertEqual(self.journal.snapshot(self.key)["state"], "complete")
        self.assertEqual(self.journal.snapshot(second)["next_phase"], 10)
        # Even a matching phase/body from the first valve cannot confirm the second.
        ack = next(e["frame"] for e in self.events
                   if e["direction"] == "device" and decode(e["frame"]).command == 0xa1)
        self.assertFalse(self.journal.observe(second, node_id=NODE, frame=alter(ack, phase=9)))

    def test_experimental_adapter_still_requires_explicit_dry_confirmation(self):
        trial = TrialJournal(self.store)
        for confirmation in (False, None, 1, "yes"):
            with self.assertRaises(ValueError):
                trial.reserve(self.key, action="open", port=1, seconds=60,
                              dry_confirmed=confirmation)
        self.assertEqual(trial.snapshot(self.key), self.journal.snapshot(self.key))

    def test_existing_incomplete_boundary_still_blocks_normal_commands(self):
        trial = TrialJournal(self.store)
        tx = self.reserve()
        self.journal.dispatch(self.key, tx, lambda *_: None)
        self.finish()
        trial.reserve_boundary_probe(self.key, prior_command_id=tx["command_id"],
            authorization_id="cd" * 16, port=1, seconds=60, dry_confirmed=True)
        before = trial.snapshot(self.key)
        with self.assertRaises(ValueError):
            self.reserve()
        self.assertEqual(self.journal.snapshot(self.key), before)

    def test_existing_completed_boundary_retains_wrap_without_requalification(self):
        trial = TrialJournal(self.store)
        tx = self.reserve()
        self.journal.dispatch(self.key, tx, lambda *_: None)
        self.finish()
        fixture = json.loads((ROOT / "research/fixtures/htv213_local_counter_boundary_20260930.json").read_text())
        for captured in fixture["trials"]:
            tx = trial.reserve_boundary_probe(self.key,
                prior_command_id=trial.snapshot(self.key)["transaction"]["command_id"],
                authorization_id="cd" * 16, port=1, seconds=60, dry_confirmed=True)
            self.journal.dispatch(self.key, tx, lambda *_: None)
            for event in captured["events"]:
                if event["direction"] == "device":
                    self.journal.observe(self.key, node_id=NODE, frame=event["frame"])
        before = trial.snapshot(self.key)
        self.store.close()
        self.store = SQLiteEventStore(self.path)
        self.journal = ControlJournal(self.store)
        self.assertEqual(self.journal.snapshot(self.key), before)
        self.assertTrue(before["counter_boundary"]["complete"])
        for phase in tuple(range(2, 64)) + (0, 1):
            tx = self.reserve()
            self.assertEqual(tx["phase"], phase)
            self.journal.dispatch(self.key, tx, lambda *_: None)
            self.finish(phase=phase)
        self.assertEqual(self.journal.snapshot(self.key)["next_phase"], 2)

    def test_normal_bounds_do_not_consume_a_phase_on_invalid_request(self):
        before = self.journal.snapshot(self.key)
        for changes in ({"port": True}, {"port": 3}, {"seconds": True}, {"seconds": 0},
                        {"seconds": 3601}, {"action": "unknown"}, {"action": "close", "seconds": 1}):
            with self.assertRaises(ValueError):
                self.reserve(**changes)
        self.assertEqual(self.journal.snapshot(self.key), before)
