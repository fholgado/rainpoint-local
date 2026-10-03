"""Offline public journal/store tests; never access live databases or radios."""
import binascii
import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'rainpointd_addon'))
from rainpointd.storage import SQLiteEventStore
from rainpointd.valve_command_phase import build_command, decode_envelope
from rainpointd.valve_phase_commands import FullPhaseCommandJournal
from rainpointd.valve_protocol import ValveLink
from tests.test_valve_phase_trial import at, NODE
from tests.valve_native_helpers import alter, FailCommit


class FullPhaseCommandJournalTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'journal.sqlite'
        self.store = SQLiteEventStore(self.path)
        self.addCleanup(lambda: self.store.close())

    def setup_model(self, model, *, phase=None):
        self.model = model
        if model == 'HTV145FRF':
            fixture = json.loads((ROOT / 'research/fixtures/htv145_active_counter_recovery_20260906.json').read_text())
            transaction = fixture['command_transactions'][0]
            self.request, self.ack = transaction['command_frame'], transaction['response_frame']
            if phase is not None:
                self.request, self.ack = [alter(f, phase=phase) for f in (self.request, self.ack)]
            envelope = decode_envelope(self.request)
            a, b = [v.hex() for v in envelope.route]
            self.port, self.storage_key = 1, a + ':' + b
            self.store.configure_htv145_control(valve_endpoint=b, controller_endpoint=a,
                node_id=NODE, center_hz=433920000, power_dbm=10, invert=False,
                trailer_residual=binascii.crc_hqx(envelope.raw[:36],0) ^ int.from_bytes(envelope.raw[36:],'big'),
                close_trailer_residual=0x4f03,
                command_marker_inverted=True, report_ack_center_hz=433140000, updated_at=at(-30))
            self.store.synchronize_htv145_control_counter(valve_endpoint=self.storage_key,
                next_sequence=128 | (envelope.phase >> 1), source='matching_immediate_response', observed_at=at(-20))
            self.store.observe_htv145_control_state(valve_endpoint=self.storage_key,
                watering=False, observed_at=at(-15), frame=self.ack)
            self.store.reserve_htv145_command(valve_endpoint=self.storage_key, command_id='aa'*16,
                action='open', duration_seconds=60, started_at=at(-10), expected_idle_at=at(50))
            self.store.confirm_htv145_command(valve_endpoint=self.storage_key, command_id='aa'*16,
                sequence=128 | (envelope.phase >> 1), watering=True,
                confirmation='matching_immediate_response', observed_at=at(-9), frame=self.ack)
            self.store.observe_htv145_control_state(valve_endpoint=self.storage_key,
                watering=False, observed_at=at(0), frame=self.ack)
        else:
            fixture = json.loads((ROOT / 'research/fixtures/htv405_local_port2_baseline_20261001.json').read_text())
            self.ack = fixture['events'][0]['frame']
            raw = bytes.fromhex(self.ack)
            link = ValveLink(raw[9:13], bytes((raw[5] & 127,)) + raw[6:9])
            phase = 1 if phase is None else phase
            self.request = build_command(model=model, link=link, phase=phase, action='open',
                port=2, duration_seconds=60, residue=0x4f03, selector=5).hex()
            self.ack = alter(self.ack, phase=phase)
            self.port, self.storage_key = 2, link.controller_endpoint.hex()
            self.store.upsert_valve_link(controller_endpoint=raw[5:9].hex(),
                valve_endpoint=self.storage_key, model=model, device_id='fixture-four',
                name='Fixture four-zone', area=None, accepted_at=at(-40))
            self.store.update_valve_control_profile(valve_endpoint=self.storage_key, node_id=NODE,
                companion_endpoint=link.valve_endpoint.hex(), selector=5,
                frequency_offset_hz=97154, observed_at=at(-30))
            self.store.confirm_valve_control_response(valve_endpoint=self.storage_key, node_id=NODE,
                sequence=phase >> 1, next_sequence=phase >> 1, zone=2, watering=False,
                center_hz=433518527, observed_at=at(-15), frame=self.ack)
            self.store.reserve_htv405_command(valve_endpoint=self.storage_key, node_id=NODE,
                command_id='aa'*16, action='open', zone=2, duration_seconds=60, started_at=at(-10))
            self.store.confirm_valve_control_response(valve_endpoint=self.storage_key, node_id=NODE,
                sequence=phase >> 1, next_sequence=((phase >> 1) + 1) & 31, zone=2, watering=True,
                center_hz=433518527, observed_at=at(-9), frame=self.ack,
                run_started_at=at(-10), run_duration_seconds=60, expected_idle_at=at(50))
            self.store.observe_htv405_state_report(valve_endpoint=self.storage_key,
                watering=False, zone=2, observed_at=at(0))
        self.journal = FullPhaseCommandJournal(self.store, model=model, storage_key=self.storage_key)

    def prepare(self, **changes):
        return self.journal.prepare(**{**dict(node_id=NODE, request_frame=self.request,
            response_frame=self.ack, port=self.port, baseline_at=at(-9), now=at(0)), **changes})

    def reserve(self, *, action='open', seconds=60, now=at(10)):
        return self.journal.reserve(action=action, port=self.port,
            duration_seconds=seconds if action=='open' else None, now=now)

    def result(self, tx):
        data = bytearray(decode_envelope(self.ack).data)
        data[1] = (0x20 if self.model=='HTV145FRF' else self.port << 5) | int(tx['action']=='open')
        if tx['action']=='open':
            data[8:10] = data[11:13] = tx['duration_seconds'].to_bytes(2, 'little')
        return alter(self.ack, phase=tx['phase'], data=data)

    def test_prepare_and_reserve_preserve_pairing_counter_and_legacy_transactions(self):
        for model in ('HTV145FRF', 'HTV405FRF'):
            with self.subTest(model=model):
                self.setup_model(model)
                before = copy.deepcopy((self.store.valve_registry(), self.store.htv145_control_states(),
                    self.store.htv145_transaction(self.storage_key)))
                prepared = self.prepare()
                tx = self.reserve()
                self.assertEqual(prepared['next_phase'], 6 if model=='HTV145FRF' else 2)
                self.assertEqual(tx['phase'], prepared['next_phase'])
                self.assertEqual(before, (self.store.valve_registry(), self.store.htv145_control_states(),
                    self.store.htv145_transaction(self.storage_key)))
                self.assertEqual(decode_envelope(tx['frame']).phase, tx['phase'])

    def test_consecutive_actions_allocate_adjacent_phases_without_using_action_or_report_counter(self):
        for model in ('HTV145FRF', 'HTV405FRF'):
            self.setup_model(model); prepared = self.prepare()
            phases = []
            for index, action in enumerate(('open', 'open', 'close', 'close', 'open')):
                tx = self.reserve(action=action, now=at(10+index*20))
                phases.append(tx['phase'])
                def sender(node, command):
                    persisted = self.journal.snapshot()['commands'][-1]
                    self.assertEqual(node, NODE)
                    self.assertEqual(persisted, command)
                    self.assertEqual(self.journal.snapshot()['state'], 'awaiting_result')
                self.journal.dispatch(tx['command_id'], now=at(10+index*20), sender=sender)
                self.assertTrue(self.journal.observe_result(node_id=NODE,
                    frame=self.result(tx), observed_at=at(11+index*20)))
                self.assertFalse(self.journal.observe_result(node_id=NODE,
                    frame=self.result(tx), observed_at=at(12+index*20)))
            self.assertEqual(phases, [6,7,8,9,10] if model=='HTV145FRF' else [2,3,4,5,6])
            self.assertEqual(self.journal.snapshot()['next_phase'], prepared['next_phase']+5)

    def test_restart_cannot_dispatch_an_attempted_packet_or_allocate_another(self):
        self.setup_model('HTV145FRF'); self.prepare(); tx = self.reserve()
        sent = []
        self.journal.dispatch(tx['command_id'], now=at(10), sender=lambda *args: sent.append(args))
        self.store.close(); self.store = SQLiteEventStore(self.path)
        self.journal = FullPhaseCommandJournal(self.store, model=self.model, storage_key=self.storage_key)
        with self.assertRaises(RuntimeError):
            self.journal.dispatch(tx['command_id'], now=at(11), sender=lambda *args: sent.append(args))
        with self.assertRaises(RuntimeError): self.reserve(now=at(30))
        self.assertEqual(len(sent), 1)
        self.assertEqual(self.journal.snapshot()['commands'][-1]['frame'], tx['frame'])
        self.assertTrue(self.journal.expire(now=at(26)))
        self.assertEqual(self.journal.snapshot()['state'], 'uncertain')
        with self.assertRaises(RuntimeError): self.reserve(now=at(40))
        with self.assertRaises(RuntimeError): self.prepare()

    def test_wrong_full_phase_owner_action_and_negative_result_cannot_synchronize(self):
        self.setup_model('HTV405FRF'); self.prepare(); tx = self.reserve()
        self.journal.dispatch(tx['command_id'], now=at(10), sender=lambda *_: None)
        reply = self.result(tx)
        self.assertFalse(self.journal.observe_result(node_id='foreign', frame=reply, observed_at=at(11)))
        self.assertFalse(self.journal.observe_result(node_id=NODE,
            frame=alter(reply, phase=tx['phase']+1), observed_at=at(11)))
        data = bytearray(decode_envelope(reply).data); data[1] = 0x40
        self.assertFalse(self.journal.observe_result(node_id=NODE,
            frame=alter(reply, data=data), observed_at=at(11)))
        data = bytearray(decode_envelope(reply).data); data[0] = 6
        self.assertTrue(self.journal.observe_result(node_id=NODE,
            frame=alter(reply, data=data), observed_at=at(11)))
        self.assertEqual(self.journal.snapshot()['commands'][-1]['native_result'], 6)
        self.assertEqual(self.journal.snapshot()['state'], 'uncertain')
        with self.assertRaises(RuntimeError): self.reserve(now=at(30))

    def test_pending_legacy_command_and_stale_baseline_are_not_migrated(self):
        self.setup_model('HTV145FRF')
        with self.assertRaises(ValueError): self.prepare(baseline_at=at(-11))
        self.store.reserve_htv145_command(valve_endpoint=self.storage_key, command_id='bb'*16,
            action='open', duration_seconds=60, started_at=at(10), expected_idle_at=at(70))
        pending = self.store.htv145_control_states(self.storage_key)[0]
        with self.assertRaises(RuntimeError): self.prepare(now=at(11))
        self.assertIsNone(self.journal.snapshot())
        self.assertEqual(self.store.htv145_control_states(self.storage_key)[0], pending)

    def test_later_legacy_command_invalidates_preparation_before_any_send(self):
        self.setup_model('HTV145FRF'); self.prepare()
        self.store.reserve_htv145_command(valve_endpoint=self.storage_key, command_id='bb'*16,
            action='open', duration_seconds=60, started_at=at(10), expected_idle_at=at(70))
        before = self.journal.snapshot()
        with self.assertRaisesRegex(RuntimeError, 'legacy association'): self.reserve(now=at(30))
        self.assertEqual(self.journal.snapshot(), before)

    def test_owner_or_profile_changes_prevent_dispatch_of_already_reserved_packet(self):
        self.setup_model('HTV405FRF'); self.prepare(); tx=self.reserve()
        self.store.update_valve_control_profile(valve_endpoint=self.storage_key,
            node_id='rp-aabbccddeeff', companion_endpoint='91abcdef', selector=5,
            frequency_offset_hz=97154, observed_at=at(11))
        sent=[]
        with self.assertRaisesRegex(RuntimeError,'legacy association'):
            self.journal.dispatch(tx['command_id'],now=at(11),sender=lambda *args:sent.append(args))
        self.assertEqual(sent,[])
        self.assertEqual(self.journal.snapshot()['state'],'reserved')

    def test_stale_compare_and_save_cannot_overwrite_a_new_reservation(self):
        self.setup_model('HTV145FRF'); self.prepare()
        saved = self.store.metadata_value(self.journal.key)
        original = self.journal.snapshot()
        self.reserve()
        retained = self.journal.snapshot()
        with self.assertRaisesRegex(RuntimeError,'phase reservation changed'):
            self.store.compare_and_save_valve_command_phase(self.journal.key,expected=saved,
                payload=json.dumps(original),model=self.model,storage_key=self.storage_key,
                legacy_state=original['legacy_state'])
        self.assertEqual(self.journal.snapshot(),retained)

    def test_transport_exception_and_expired_reservation_never_create_a_new_phase(self):
        self.setup_model('HTV145FRF');self.prepare();tx=self.reserve()
        def failed_transport(*_): raise ConnectionError('delivery unknown')
        with self.assertRaises(ConnectionError):
            self.journal.dispatch(tx['command_id'],now=at(10),sender=failed_transport)
        self.assertEqual(self.journal.snapshot()['state'],'awaiting_result')
        with self.assertRaises(RuntimeError): self.reserve(now=at(40))
        self.assertFalse(self.journal.observe_result(node_id=NODE,frame=self.result(tx),observed_at=at(26)))
        self.assertTrue(self.journal.expire(now=at(26)))
        self.assertFalse(self.journal.observe_result(node_id=NODE,frame=self.result(tx),observed_at=at(27)))
        self.assertEqual(self.journal.snapshot()['pending'],tx['command_id'])

    def test_unsent_reservation_expires_without_dispatch_or_counter_reuse(self):
        self.setup_model('HTV405FRF');self.prepare();tx=self.reserve()
        sent=[]
        with self.assertRaisesRegex(RuntimeError,'expired'):
            self.journal.dispatch(tx['command_id'],now=at(16),sender=lambda *args:sent.append(args))
        self.assertTrue(self.journal.expire(now=at(16)))
        self.assertEqual(sent,[])
        self.assertEqual(self.journal.snapshot()['commands'][-1],tx)
        with self.assertRaises(RuntimeError):self.reserve(now=at(40))

    def test_command_interval_starts_at_dispatch_not_reservation(self):
        self.setup_model('HTV145FRF');self.prepare();tx=self.reserve()
        self.journal.dispatch(tx['command_id'],now=at(15),sender=lambda *_:None)
        self.assertTrue(self.journal.observe_result(node_id=NODE,frame=self.result(tx),observed_at=at(16)))
        with self.assertRaisesRegex(RuntimeError,'15-second'):self.reserve(now=at(25))
        self.assertEqual(self.reserve(now=at(30))['phase'],7)

    def test_commit_failure_rolls_back_reservation_and_blocks_transport(self):
        self.setup_model('HTV145FRF'); self.prepare()
        before = self.journal.snapshot()
        connection = self.store._connection
        self.store._connection = FailCommit(connection)
        try:
            with self.assertRaises(sqlite3.OperationalError): self.reserve()
        finally:
            self.store._connection = connection
        self.assertEqual(self.journal.snapshot(), before)
        tx = self.reserve(); sent=[]
        self.store._connection = FailCommit(connection)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self.journal.dispatch(tx['command_id'], now=at(10), sender=lambda *args: sent.append(args))
        finally:
            self.store._connection = connection
        self.assertEqual(sent, [])
        self.assertEqual(self.journal.snapshot()['state'], 'reserved')

    def test_rollover_is_not_silently_qualified_by_offline_math(self):
        self.setup_model('HTV145FRF', phase=61); self.prepare()
        phases=[]
        for now in (10,30):
            tx = self.reserve(now=at(now)); phases.append(tx['phase'])
            self.journal.dispatch(tx['command_id'], now=at(now), sender=lambda *_: None)
            self.assertTrue(self.journal.observe_result(node_id=NODE,
                frame=self.result(tx), observed_at=at(now+1)))
        self.assertEqual(phases, [62,63])
        self.assertEqual(self.journal.snapshot()['next_phase'], 0)
        with self.assertRaisesRegex(RuntimeError, 'rollover'): self.reserve(now=at(50))
