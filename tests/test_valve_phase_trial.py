"""Offline installed-canary guards. Synthetic frames are not RF qualification."""
from datetime import datetime, timedelta, timezone
import json
import binascii
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rainpointd_addon"))
from rainpointd.storage import SQLiteEventStore
from rainpointd.valve_phase_trial import PhaseTrialJournal, packet
from rainpointd.valve_protocol import ValveLink, build_open_frame
from tests.valve_native_helpers import FailCommit, alter

NODE = "rp-001122334455"


def at(seconds):
    return (datetime(2026, 9, 30, tzinfo=timezone.utc) + timedelta(seconds=seconds)).isoformat()


class ValvePhaseTrialTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "journal.sqlite"
        self.store = SQLiteEventStore(self.path)
        self.addCleanup(lambda: self.store.close())
        self.journal = PhaseTrialJournal(self.store)
        fixture = json.loads((ROOT / "research/fixtures/htv145_active_counter_recovery_20260906.json").read_text())
        self.baseline = fixture["command_transactions"][0]
        self.ack = self.baseline["response_frame"]
        self.active = self.baseline["independent_state_frame"]

    def prepare(self, **changes):
        raw = bytes.fromhex(self.ack)
        return self.journal.prepare(**{**dict(authorization_id="ab" * 16,
            model="HTV145FRF", node_id=NODE,
            request_frame=self.baseline["command_frame"], response_frame=self.ack,
            report_route=[raw[5:9].hex(), raw[9:13].hex()], selector=packet(self.active)[3][0],
            evidence_id="cd" * 16, now=at(0), expires_at=at(600)), **changes})

    def start(self, key, seconds=1):
        tx = self.journal.reserve(key, now=at(seconds))
        def sender(identity, transaction):
            saved = PhaseTrialJournal(self.store).snapshot(key)
            self.assertEqual(saved["state"], "attempted")
            self.assertEqual(saved["transactions"][-1], transaction)
            self.assertEqual(identity["node_id"], NODE)
        self.journal.dispatch(key, tx, now=at(seconds), sender=sender)
        return tx

    def frames(self, phase):
        # Retain captured state shape, but make phase/time fields explicit.
        data = bytearray(packet(self.ack)[3])
        data[8:10] = (60).to_bytes(2, "little")
        ack = alter(self.ack, phase=phase, data=data)
        data = bytearray(packet(self.active)[3])
        data[10:12] = (59).to_bytes(2, "little")
        active = alter(self.active, phase=47, data=data)
        data[3] = 0
        data[10:12] = data[13:15] = bytes(2)
        return ack, active, alter(self.active, phase=48, data=data)

    def observe(self, key, frame, seconds, node=NODE):
        return self.journal.observe(key, node_id=node, frame=frame, observed_at=at(seconds))

    def complete(self, key, tx, seconds):
        for frame, offset in zip(self.frames(tx["phase"]), (1, 2, 61)):
            self.assertTrue(self.observe(key, frame, seconds + offset))

    def test_two_adjacent_opens_require_ack_and_independent_idle_then_exhaust_budget(self):
        key = self.prepare()
        for seconds, phase in ((1, 6), (70, 7)):
            tx = self.start(key, seconds)
            self.assertEqual((tx["phase"], tx["port"], tx["seconds"]), (phase, 1, 60))
            with self.assertRaises(ValueError): self.journal.reserve(key, now=at(seconds+1))
            self.complete(key, tx, seconds)
            self.assertEqual(self.journal.snapshot(key)["next_phase"], phase+1)
        self.assertEqual(self.journal.snapshot(key)["state"], "complete")
        with self.assertRaises(ValueError): self.journal.reserve(key, now=at(140))
        with self.assertRaises(ValueError): self.prepare()
        self.assertEqual(self.store.valve_registry(), [])

    def test_actual_generated_four_zone_port2_exchange(self):
        capture=json.loads((ROOT/'research/fixtures/htv405_local_port2_baseline_20261001.json').read_text())
        ack,active,idle=[e['frame'] for e in capture['events']]
        raw=bytes.fromhex(ack)
        request=bytearray(build_open_frame(ValveLink(raw[9:13], bytes((raw[5]&127,))+raw[6:9]),128,60,0x4f03,command_marker_inverted=True))
        request[17]=0x82
        request[-2:]=(binascii.crc_hqx(request[:-2],0)^0x4f03).to_bytes(2,'big')
        key=self.prepare(model='HTV405FRF',port=2,request_frame=request.hex(),response_frame=ack,
            report_route=[raw[5:9].hex(),raw[9:13].hex()],selector=4)
        tx=self.start(key)
        self.assertEqual(tx['phase'],2)
        wrong_ack=bytearray(packet(ack)[3]);wrong_ack[1]=0x61
        wrong_active=bytearray(packet(active)[3]);wrong_active[3]=0x61
        self.assertFalse(self.observe(key,alter(ack,phase=2,data=wrong_ack),2))
        self.assertFalse(self.observe(key,alter(active,data=wrong_active),3))
        self.assertTrue(self.observe(key,alter(ack,phase=2),4))
        self.assertFalse(self.observe(key,idle,5))
        self.assertTrue(self.observe(key,active,6))
        self.assertTrue(self.observe(key,idle,64))
        self.assertEqual(self.journal.snapshot(key)['state'],'between_runs')

    def test_transport_failure_and_restart_cannot_resend_or_reseed(self):
        key = self.prepare(); tx = self.journal.reserve(key, now=at(1))
        with self.assertRaises(ConnectionError):
            self.journal.dispatch(key, tx, now=at(1),
                sender=lambda *_: (_ for _ in ()).throw(ConnectionError()))
        self.store.close(); self.store = SQLiteEventStore(self.path)
        self.journal = PhaseTrialJournal(self.store)
        with self.assertRaises(ValueError):
            self.journal.dispatch(key, tx, now=at(2), sender=lambda *_: self.fail("duplicate open"))
        with self.assertRaises(ValueError): self.prepare(authorization_id="ef"*16)
        self.assertEqual(self.journal.snapshot(key)["next_phase"], 7)

    def test_commit_failure_blocks_reservation_and_dispatch(self):
        key = self.prepare(); connection = self.store._connection
        self.store._connection = FailCommit(connection)
        try:
            with self.assertRaises(sqlite3.OperationalError): self.journal.reserve(key, now=at(1))
        finally: self.store._connection = connection
        self.assertEqual(self.journal.snapshot(key)["state"], "ready")
        tx = self.journal.reserve(key, now=at(1))
        self.store._connection = FailCommit(connection)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self.journal.dispatch(key, tx, now=at(1), sender=lambda *_: self.fail("before commit"))
        finally: self.store._connection = connection
        self.assertEqual(self.journal.snapshot(key)["state"], "reserved")

    def test_expired_reservation_and_permission_do_not_send(self):
        key = self.prepare(expires_at=at(130))
        with self.assertRaises(ValueError): self.journal.reserve(key, now=at(6))
        tx = self.journal.reserve(key, now=at(1))
        with self.assertRaises(ValueError):
            self.journal.dispatch(key, tx, now=at(7), sender=lambda *_: self.fail("late open"))

    def test_foreign_and_wrong_phase_packets_cannot_accept_or_fail_trial(self):
        key = self.prepare(); tx = self.start(key)
        ack, active, idle = self.frames(tx["phase"])
        for frame, node in ((ack, "rp-aabbccddeeff"), (alter(ack, phase=7), NODE)):
            self.assertFalse(self.observe(key, frame, 30, node))
        self.assertEqual(self.journal.snapshot(key)["state"], "attempted")
        self.assertTrue(self.observe(key, ack, 2))
        self.assertFalse(self.observe(key, idle, 62))  # No active report yet.
        for index, value in ((0, 13), (2, 2)):
            data = bytearray(packet(active)[3]); data[index] = value
            self.assertFalse(self.observe(key, alter(active, data=data), 3))
        self.assertTrue(self.observe(key, active, 4))
        self.assertFalse(self.observe(key, idle, 10))  # Too early to complete 60s.
        self.assertTrue(self.observe(key, idle, 62))
        self.assertEqual(self.journal.snapshot(key)["state"], "between_runs")

    def test_negative_and_missing_confirmation_stop_without_retry(self):
        key = self.prepare(); tx = self.start(key)
        ack = self.frames(tx["phase"])[0]
        data = bytearray(packet(ack)[3]); data[0] = 6
        self.assertTrue(self.observe(key, alter(ack, data=data), 2))
        result = self.journal.snapshot(key)
        self.assertEqual((result["state"], result["native_result"]), ("failed", 6))
        with self.assertRaises(ValueError): self.journal.reserve(key, now=at(70))

    def test_timeout_without_ack_or_completion_never_reopens(self):
        key = self.prepare(); self.start(key)
        self.assertTrue(self.journal.expire(key, now=at(17)))
        with self.assertRaises(ValueError): self.journal.reserve(key, now=at(70))

    def test_invalid_baseline_and_unrelated_report_routes_rejected(self):
        for change in ({"response_frame":alter(self.ack, phase=4)},
                       {"report_route":["11223344", "55667788"]},
                       {"model":"HTV213FRF"}, {"expires_at":at(3601)},
                       {"selector":True}, {"evidence_id":""}):
            with self.subTest(change=change), self.assertRaises(ValueError): self.prepare(**change)
        for phase in (61, 62, 63):
            with self.subTest(phase=phase), self.assertRaises(ValueError):
                self.prepare(request_frame=alter(self.baseline["command_frame"], phase=phase),
                             response_frame=alter(self.ack, phase=phase))

    def test_four_zone_response_route_and_mode_not_port(self):
        # Synthetic four-zone route variant; does not claim physical acceptance.
        matrix = json.loads((ROOT / "research/fixtures/htv405_stock_cloud_control_matrix_20260824.json").read_text())
        trial = matrix["trials"][0]
        self.baseline["command_frame"] = trial["open_command_frame"]
        self.active = trial["active_report_frame"]
        raw = bytearray.fromhex(self.ack)
        raw[5:13] = bytes.fromhex(self.active)[5:13]
        self.ack = alter(raw.hex(), phase=packet(self.baseline["command_frame"])[2])
        key = self.prepare(model="HTV405FRF")
        tx = self.start(key)
        self.complete(key, tx, 1)
        self.assertIsNotNone(self.journal.snapshot(key)["transactions"][-1]["ack_at"])

    def test_positive_ack_without_idle_times_out_and_does_not_use_report_phase(self):
        key = self.prepare(); tx = self.start(key)
        ack, active, _ = self.frames(tx["phase"])
        self.assertTrue(self.observe(key, ack, 2))
        self.assertTrue(self.observe(key, active, 3))
        self.assertTrue(self.journal.expire(key, now=at(127)))
        self.assertEqual(self.journal.snapshot(key)["next_phase"], 7)
        self.assertEqual(self.journal.snapshot(key)["state"], "failed")
