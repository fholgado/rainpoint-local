"""Dry-trial counters and evidence on temporary SQLite; never live dispatch."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rainpointd_addon"))
from rainpointd.storage import SQLiteEventStore
from rainpointd.htv213_control_trial import ControlJournal
from research.pairing_native_transcripts import decode
from tests.test_valve_configuration import alter

NODE = "rp-001122334455"


class FailCommit:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, *args):
        return self.connection.execute(*args)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.connection.rollback()
        raise sqlite3.OperationalError("simulated failed commit")


class Htv213ControlJournalTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "events.sqlite"
        self.store = SQLiteEventStore(self.path)
        self.addCleanup(lambda: self.store.close())
        self.journal = ControlJournal(self.store)
        self.identity = dict(node_id=NODE, controller="a2446688", valve="91556677", selector=11,
                             acknowledged_phase=2, evidence_id="ab" * 16)
        self.key = self.journal.seed(**self.identity)
        fixture = json.loads((ROOT / "research/fixtures/htv213_stock_pairing_controls_20260928.json").read_text())
        self.trials = {t["name"]: t["events"] for t in fixture["trials"]}

    def reserve(self, action="open", port=1, seconds=60):
        return self.journal.reserve(self.key, action=action, port=port, seconds=seconds, dry_confirmed=True)

    def observe(self, frame, **overrides):
        return self.journal.observe(self.key, node_id=overrides.get("node_id", NODE), frame=frame)

    def frames(self, name="zone1_auto60"):
        return [e["frame"] for e in self.trials[name] if e["direction"] == "device"]

    def test_reserve_commit_precedes_callback_and_transport_return_is_not_success(self):
        tx = self.reserve()
        self.assertEqual(tx["phase"], 3)
        def send(identity, transaction):
            snapshot = ControlJournal(self.store).snapshot(self.key)
            self.assertEqual(snapshot["state"], "indeterminate")
            self.assertEqual(snapshot["next_phase"], 4)
            self.assertEqual(identity["valve"], "91556677")
            self.assertEqual(transaction, tx)
        self.journal.dispatch(self.key, tx, send)
        self.assertEqual(self.journal.snapshot(self.key)["state"], "indeterminate")

    def test_restart_never_reseeds_or_replays_reserved_or_attempted_phase(self):
        tx = self.reserve()
        self.store.close()
        self.store = SQLiteEventStore(self.path)
        self.journal = ControlJournal(self.store)
        self.assertEqual(self.journal.seed(**self.identity), self.key)
        self.assertEqual(self.journal.snapshot(self.key)["next_phase"], 4)
        with self.assertRaises(ValueError): self.reserve()
        self.journal.dispatch(self.key, tx, lambda *_: None)
        with self.assertRaises(ValueError): self.journal.dispatch(self.key, tx, lambda *_: self.fail("duplicate"))
        with self.assertRaises(ValueError):
            self.journal.seed(**{**self.identity, "acknowledged_phase": 0, "evidence_id": "cd" * 16})

    def test_indeterminate_send_cannot_reuse_counter_or_issue_speculative_close(self):
        tx = self.reserve()
        with self.assertRaises(ConnectionError):
            self.journal.dispatch(self.key, tx, lambda *_: (_ for _ in ()).throw(ConnectionError()))
        with self.assertRaises(ValueError): self.reserve()
        with self.assertRaises(ValueError): self.reserve("close", seconds=0)
        self.assertEqual(self.journal.snapshot(self.key)["next_phase"], 4)

    def test_stock_complete_cycle_advances_only_the_master_command_counter(self):
        tx = self.reserve()
        self.journal.dispatch(self.key, tx, lambda *_: None)
        for frame in self.frames():
            self.observe(frame)
        snapshot = self.journal.snapshot(self.key)
        self.assertEqual(snapshot["state"], "complete")
        self.assertEqual(snapshot["transaction"]["elapsed_seconds"], 60)
        self.assertEqual(snapshot["next_phase"], 4)  # Not report phase 14 + 1.
        self.assertEqual(self.reserve(port=2, seconds=120)["phase"], 4)
        self.assertEqual(self.store.valve_registry(), [])

    def test_early_close_and_other_port_idle_are_correlated(self):
        # Seed another explicit trial at the captured early-stop master phase.
        other = {**self.identity, "valve": "91556678", "acknowledged_phase": 4}
        key = self.journal.seed(**other)
        for event in self.trials["zone1_early_close"]:
            packet = decode(event["frame"])
            if packet.command == 0x21:
                action = "open" if packet.data[2] else "close"
                tx = self.journal.reserve(key, action=action, port=1,
                                          seconds=120 if action == "open" else 0, dry_confirmed=True)
                self.assertEqual(tx["phase"], packet.phase)
                self.journal.dispatch(key, tx, lambda *_: None)
            elif event["direction"] == "device":
                raw = bytearray.fromhex(event["frame"]); raw[9:13] = bytes.fromhex(other["valve"])
                self.journal.observe(key, node_id=NODE, frame=alter(raw.hex()))
        snapshot = self.journal.snapshot(key)
        self.assertEqual(snapshot["state"], "complete")
        self.assertEqual(snapshot["next_phase"], 7)
        self.assertEqual(snapshot["transaction"]["elapsed_seconds"], 34)
        self.assertEqual(self.journal.snapshot(self.key)["next_phase"], 3)

    def test_wrong_owner_routes_phase_selector_port_and_negative_result_do_not_advance(self):
        tx = self.reserve(); self.journal.dispatch(self.key, tx, lambda *_: None)
        ack = self.frames()[0]
        self.assertFalse(self.observe(ack, node_id="rp-aabbccddeeff"))
        self.assertFalse(self.observe(alter(ack, phase=4)))
        data = bytearray(decode(ack).data); data[0] = 9
        self.assertFalse(self.observe(alter(ack, data=data)))
        wrong = bytearray.fromhex(ack); wrong[8] ^= 1
        self.assertFalse(self.observe(alter(wrong.hex())))
        self.assertEqual(self.journal.snapshot(self.key)["state"], "indeterminate")
        self.assertTrue(self.observe(ack))
        idle = next(f for f in self.frames() if decode(f).command == 2 and decode(f).data[3] == 0)
        for offset, value in ((0, 12), (2, 2)):
            data = bytearray(decode(idle).data); data[offset] = value
            self.assertFalse(self.observe(alter(idle, data=data)))
        self.assertFalse(self.journal.snapshot(self.key)["transaction"]["idle"])

    def test_failed_commit_rolls_back_and_never_calls_sender(self):
        connection = self.store._connection
        self.store._connection = FailCommit(connection)
        try:
            with self.assertRaises(sqlite3.OperationalError): self.reserve()
        finally:
            self.store._connection = connection
        self.assertEqual(self.journal.snapshot(self.key)["state"], "ready")
        self.assertEqual(self.journal.snapshot(self.key)["next_phase"], 3)
        tx = self.reserve()
        self.store._connection = FailCommit(connection)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self.journal.dispatch(self.key, tx, lambda *_: self.fail("dispatch before commit"))
        finally:
            self.store._connection = connection
        self.assertEqual(self.journal.snapshot(self.key)["state"], "reserved")

    def test_dry_bounds_and_no_implicit_wrap(self):
        for changes in ({"dry_confirmed": False}, {"seconds": 3601}, {"port": 3}, {"port": True}):
            with self.assertRaises(ValueError):
                self.journal.reserve(self.key, **{ "action": "open", "port": 1,
                    "seconds": 60, "dry_confirmed": True, **changes})
        with self.assertRaises(ValueError): self.journal.seed(**{**self.identity, "acknowledged_phase": 63})

    def test_once_only_boundary_preserves_jump_history_and_requires_every_completion(self):
        tx = self.reserve(); self.journal.dispatch(self.key, tx, lambda *_: None)
        for frame in self.frames(): self.observe(frame)
        for phase in (62, 63, 0, 1):
            before = self.journal.snapshot(self.key)
            args = dict(prior_command_id=before['transaction']['command_id'], authorization_id='ab'*16,
                        port=1, seconds=60, dry_confirmed=True)
            tx = self.journal.reserve_boundary_probe(self.key, **args)
            self.assertEqual(tx['phase'], phase)
            self.assertEqual(tx['counter_boundary']['prior_next_phase'], before['next_phase'])
            with self.assertRaises(ValueError): self.journal.reserve_boundary_probe(self.key, **args)
            with self.assertRaises(ValueError): self.reserve()
            self.journal.dispatch(self.key, tx, lambda *_: None)
            with self.assertRaises(ValueError): self.journal.dispatch(self.key, tx, lambda *_: self.fail('duplicate'))
            for frame in self.frames():
                self.observe(alter(frame, phase=phase) if decode(frame).command == 0xa1 else frame)
            self.assertEqual(self.journal.snapshot(self.key)['state'], 'complete')
            if phase != 1:
                with self.assertRaises(ValueError): self.reserve()
        result = self.journal.snapshot(self.key)
        self.assertEqual(result['counter_boundary']['origin_next_phase'], 4)
        self.assertTrue(result['counter_boundary']['complete'])
        self.assertEqual([t['phase'] for t in result['history']], [3, 62, 63, 0])
        for auth in ('ab'*16, 'cd'*16):
            with self.assertRaises(ValueError):
                self.journal.reserve_boundary_probe(self.key, **{**args, 'authorization_id':auth,
                    'prior_command_id':result['transaction']['command_id']})
        # Qualification is association-local. A complete ordinary cycle must
        # now use all 64 wire values without depending on report phases.
        for phase in tuple(range(2,64)) + (0,1):
            tx = self.reserve()
            self.assertEqual(tx['phase'], phase)
            self.journal.dispatch(self.key, tx, lambda *_: None)
            for frame in self.frames():
                self.observe(alter(frame, phase=phase) if decode(frame).command == 0xa1 else frame)
        self.assertEqual(self.journal.snapshot(self.key)['next_phase'], 2)

    def test_boundary_commit_failure_and_bad_scope_never_consume_or_send(self):
        tx = self.reserve(); self.journal.dispatch(self.key, tx, lambda *_: None)
        for frame in self.frames(): self.observe(frame)
        args = dict(prior_command_id=tx['command_id'], authorization_id='ab'*16,
                    port=1, seconds=60, dry_confirmed=True)
        before = self.journal.snapshot(self.key)
        for change in ({'dry_confirmed':False}, {'port':3}, {'seconds':120},
                       {'authorization_id':''}, {'prior_command_id':'cd'*16}):
            with self.assertRaises(ValueError): self.journal.reserve_boundary_probe(self.key, **{**args, **change})
        connection = self.store._connection
        self.store._connection = FailCommit(connection)
        try:
            with self.assertRaises(sqlite3.OperationalError): self.journal.reserve_boundary_probe(self.key, **args)
        finally: self.store._connection = connection
        self.assertEqual(self.journal.snapshot(self.key), before)

    def test_unqualified_association_still_stops_at_the_wrap_boundary(self):
        identity = {**self.identity, 'valve':'91556678', 'acknowledged_phase':62}
        key = self.journal.seed(**identity)
        tx = self.journal.reserve(key, action='open', port=1, seconds=60, dry_confirmed=True)
        self.assertEqual(tx['phase'], 63)
        self.journal.dispatch(key, tx, lambda *_: None)
        for frame in self.frames():
            raw = bytearray.fromhex(frame); raw[9:13] = bytes.fromhex(identity['valve'])
            corrected = alter(raw.hex(), phase=63) if decode(frame).command==0xa1 else alter(raw.hex())
            self.journal.observe(key, node_id=NODE, frame=corrected)
        self.assertEqual(self.journal.snapshot(key)['state'], 'complete')
        with self.assertRaises(ValueError):
            self.journal.reserve(key, action='open', port=1, seconds=60, dry_confirmed=True)

    def test_real_boundary_frames_qualify_only_after_all_four_completed_steps(self):
        tx = self.reserve(); self.journal.dispatch(self.key, tx, lambda *_: None)
        for frame in self.frames(): self.observe(frame)
        fixture = json.loads((ROOT/'research/fixtures/htv213_local_counter_boundary_20260930.json').read_text())
        for trial in fixture['trials']:
            tx = self.journal.reserve_boundary_probe(self.key,
                prior_command_id=self.journal.snapshot(self.key)['transaction']['command_id'],
                authorization_id='ef'*16, port=1, seconds=60, dry_confirmed=True)
            self.assertEqual(tx['phase'], trial['phase'])
            self.journal.dispatch(self.key, tx, lambda *_: None)
            for event in trial['events']:
                if event['direction']=='device': self.observe(event['frame'])
            result = self.journal.snapshot(self.key)
            self.assertEqual(result['state'], 'complete')
            self.assertEqual(result['counter_boundary']['complete'], trial['phase']==1)
        self.store.close()
        self.store = SQLiteEventStore(self.path)
        self.journal = ControlJournal(self.store)
        self.assertEqual(self.journal.snapshot(self.key)['next_phase'], 2)
        self.assertTrue(self.journal.snapshot(self.key)['counter_boundary']['complete'])

    def test_ha_five_minute_capture_completes_without_report_counter_reseed(self):
        with closing(SQLiteEventStore(Path(self.directory.name) / 'ha-five-minute.sqlite')) as store:
            journal = ControlJournal(store)
            key = journal.seed(**{**self.identity, 'acknowledged_phase': 6})
            tx = journal.reserve(key, action='open', port=2, seconds=300, dry_confirmed=True)
            journal.dispatch(key, tx, lambda *_: None)
            events = json.loads((ROOT / 'research/fixtures/htv213_local_ha_auto300_20260930.json').read_text())['events']
            for event in events:
                if event['direction'] == 'device':
                    journal.observe(key, node_id=NODE, frame=event['frame'])
            result = journal.snapshot(key)
            self.assertEqual(result['state'], 'complete')
            self.assertEqual(result['transaction']['elapsed_seconds'], 300)
            self.assertEqual(result['transaction']['phase'], 7)
            self.assertEqual(result['next_phase'], 8)

    def test_explicit_crc_retrial_preserves_attempt_and_phase_and_cannot_repeat(self):
        prior = self.reserve()
        self.journal.dispatch(self.key, prior, lambda *_: None)
        args = dict(prior_command_id=prior["command_id"], evidence_sha256="cd" * 32,
                    authorization_id="ef" * 16, port=1, seconds=60, dry_confirmed=True)
        for change in ({"dry_confirmed": False}, {"port": 2}, {"seconds": 61},
                       {"prior_command_id": "00" * 16}, {"evidence_sha256": ""},
                       {"authorization_id": ""}):
            with self.assertRaises(ValueError):
                self.journal.reserve_crc_retrial(self.key, **{**args, **change})
        tx = self.journal.reserve_crc_retrial(self.key, **args)
        self.assertEqual(tx["phase"], prior["phase"])
        self.assertNotEqual(tx["command_id"], prior["command_id"])
        record = self.journal.snapshot(self.key)
        self.assertEqual(record["history"], [prior])
        self.assertEqual(record["next_phase"], 4)
        self.journal.dispatch(self.key, tx, lambda *_: None)
        with self.assertRaises(ValueError):
            self.journal.reserve_crc_retrial(self.key, **{**args, "prior_command_id": tx["command_id"]})
        with self.assertRaises(ValueError): self.reserve()

    def test_crc_retrial_cannot_repeat_acknowledged_open(self):
        prior = self.reserve()
        self.journal.dispatch(self.key, prior, lambda *_: None)
        self.observe(self.frames()[0])
        with self.assertRaises(ValueError):
            self.journal.reserve_crc_retrial(self.key, prior_command_id=prior["command_id"],
                evidence_sha256="cd" * 32, authorization_id="ef" * 16,
                port=1, seconds=60, dry_confirmed=True)

    def test_local_corrected_crc_capture_completes_the_audited_retrial(self):
        prior = self.reserve()
        self.journal.dispatch(self.key, prior, lambda *_: None)
        tx = self.journal.reserve_crc_retrial(self.key, prior_command_id=prior["command_id"],
            evidence_sha256="cd" * 32, authorization_id="ef" * 16,
            port=1, seconds=60, dry_confirmed=True)
        self.journal.dispatch(self.key, tx, lambda *_: None)
        events = json.loads((ROOT / "research/fixtures/htv213_local_control_crc_corrected_20260930.json").read_text())["events"]
        for event in events:
            if event["direction"] == "device": self.observe(event["frame"])
        result = self.journal.snapshot(self.key)
        self.assertEqual(result["state"], "complete")
        self.assertEqual(result["next_phase"], 4)
        self.assertEqual(result["history"], [prior])
        self.assertEqual(result["transaction"]["elapsed_seconds"], 60)
