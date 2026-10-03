"""Real SQLite handoff and telemetry coexistence; no RF or live database."""
from datetime import datetime
import json
import sqlite3
import threading
from types import SimpleNamespace
import unittest

from tests import test_valve_phase_trial as fixture_helpers
from tests.test_valve_phase_trial import ROOT, NODE, at
from tests.valve_native_helpers import FailCommit, alter
from rainpointd.htv145_control import Htv145ControlCoordinator, Htv145ControlProfile
from rainpointd.htv145_counter_sync import Htv145CounterSync
from rainpointd.valve_phase_trial import PhaseTrialJournal, assert_node_available, packet
from rainpointd.valve_phase_experiment import act, authorize_send, eligible
from rainpointd.gateway import Gateway


class ValvePhaseHandoffTest(unittest.TestCase):
    def setup_model(self, model, *, baseline_phase=None, port=1, ports_capability=True):
        fixture = fixture_helpers.ValvePhaseTrialTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.store = fixture.store
        if model == "HTV405FRF":
            trial = json.loads((ROOT / "research/fixtures/htv405_stock_cloud_control_matrix_20260824.json").read_text())["trials"][0]
            fixture.baseline["command_frame"] = trial["open_command_frame"]
            fixture.active = trial["active_report_frame"]
            raw = bytearray.fromhex(fixture.ack)
            raw[5:13] = bytes.fromhex(fixture.active)[5:13]
            fixture.ack = alter(raw.hex(), phase=packet(fixture.baseline["command_frame"])[2])
        if baseline_phase is not None:
            fixture.baseline["command_frame"] = alter(fixture.baseline["command_frame"], phase=baseline_phase)
            fixture.ack = alter(fixture.ack, phase=baseline_phase)
        if port!=1:
            data=bytearray(packet(fixture.baseline["command_frame"])[3]);data[0]=port
            fixture.baseline["command_frame"]=alter(fixture.baseline["command_frame"],data=data)
            data=bytearray(packet(fixture.active)[3]);data[2]=port
            fixture.active=alter(fixture.active,data=data)
        raw = bytes.fromhex(fixture.baseline["command_frame"])
        a, b = raw[5:9].hex(), raw[9:13].hex()
        counter = (packet(fixture.baseline["command_frame"])[2] + 1) // 2
        valve, controller = (b, a) if model == "HTV145FRF" else (a, (int(b,16) | 0x80000000).to_bytes(4,"big").hex())
        self.store.upsert_valve_link(controller_endpoint=controller, valve_endpoint=valve,
            device_id="fixture-valve", name="Fixture valve", model=model, area=None, accepted_at=at(-20))
        profile = None
        if model == "HTV145FRF":
            profile = Htv145ControlProfile(node_id=NODE, controller_endpoint=a,
                valve_endpoint=b, center_hz=433920000, power_dbm=10, invert=False,
                trailer_residual=0x4f03, command_marker_inverted=True,
                report_ack_center_hz=433140000)
            Htv145ControlCoordinator(store=self.store, sender=lambda *_: None).configure(profile, observed_at=at(-10))
            self.store.synchronize_htv145_control_counter(valve_endpoint=profile.storage_key,
                next_sequence=128 | counter, source="matching_immediate_response", observed_at=at(-5))
            self.store.observe_htv145_control_state(valve_endpoint=profile.storage_key,
                watering=False, observed_at=at(0), frame=fixture.active)
        else:
            self.store.update_valve_control_profile(valve_endpoint=valve, node_id=NODE,
                companion_endpoint=b, selector=5,
                frequency_offset_hz=97154, observed_at=at(-10))
            self.store.confirm_valve_control_response(valve_endpoint=valve, node_id=NODE,
                sequence=counter, next_sequence=counter, zone=1, watering=False,
                center_hz=433518527, observed_at=at(-5), frame=fixture.ack)
        self.sent = []
        self.gateway = SimpleNamespace(_store=self.store, _lock=threading.RLock(),
            _node_command_sender=lambda node, command: self.sent.append((node, command)),
            _devices={"fixture-valve": dict(model=model, available=True, observed_at=at(0),
                state={"is_watering": False, **{f"zone_{p}_is_watering":False for p in range(1,5)}})},
            _htv145_profile_for_device=lambda _: profile,
            nodes=lambda: [dict(node_id=NODE, managed=True, connected=True, authenticated=True,
                tx_armed=False, capabilities=["valve_phase_trial"]+(["valve_phase_trial_ports"] if ports_capability else []))],
            pairing=lambda: {"active": False}, _ack_ownership=SimpleNamespace(snapshot=lambda: []))
        self.key = "ab" * 16
        self.request = dict(device_id="fixture-valve", authorization_id=self.key,
            evidence_id="cd" * 16, baseline_observed_at=at(0),
            request_frame=fixture.baseline["command_frame"], response_frame=fixture.ack,
            selector=packet(fixture.active)[3][0],port=port)
        self.valve, self.profile = valve, profile
        self.action("prepare", 0, self.request)

    def action(self, action, second, request=None):
        return act(self.gateway, action, request or {"authorization_id":self.key},
                   now=datetime.fromisoformat(at(second)))

    def run_once(self, second):
        self.action("open", second)
        tx = self.fixture.journal.snapshot(self.key)["transactions"][-1]
        self.fixture.complete(self.key, tx, second)
        if self.profile is None:
            # Normal telemetry remains independent of the experimental journal.
            for watering, offset in ((True,2),(False,61)):
                self.store.observe_htv405_state_report(valve_endpoint=self.valve,
                    watering=watering, zone=self.request["port"], observed_at=at(second+offset))

    def test_dry_port_is_durable_and_sent_unchanged_for_both_runs(self):
        for port in (2,3,4):
            with self.subTest(port=port):
                self.setup_model("HTV405FRF",port=port)
                self.run_once(1);self.run_once(70)
                record=self.fixture.journal.snapshot(self.key)
                self.assertEqual(record["identity"]["port"],port)
                self.assertEqual([tx["port"] for tx in record["transactions"]],[port,port])
                self.assertEqual([c["port"] for _,c in self.sent],[port,port])
                self.action("release",140)
                self.assertEqual(self.fixture.journal.snapshot(self.key)["state"],"releasing")

    def test_old_radio_and_invalid_model_port_cannot_admit_dry_port(self):
        with self.assertRaisesRegex(ValueError,"multi-port"):
            self.setup_model("HTV405FRF",port=2,ports_capability=False)
        with self.assertRaisesRegex(ValueError,"port"):
            self.setup_model("HTV145FRF",port=2)

    def test_lost_port_capability_prevents_reservation_or_send(self):
        self.setup_model("HTV405FRF",port=2)
        original=self.gateway.nodes
        self.gateway.nodes=lambda:[{**original()[0],"capabilities":["valve_phase_trial"]}]
        with self.assertRaisesRegex(ValueError,"multi-port"):self.action("open",1)
        self.assertEqual(self.sent,[])
        self.assertEqual(self.fixture.journal.snapshot(self.key)["transactions"],[])

    def test_four_zone_telemetry_invalidation_does_not_block_second_verified_run(self):
        self.setup_model("HTV405FRF")
        self.run_once(1)
        self.assertIsNone(self.store.valve_registry()[0]["control_next_sequence"])
        self.run_once(70)
        self.assertEqual("complete", self.fixture.journal.snapshot(self.key)["state"])
        self.action("release", 140)
        self.assertEqual(3, self.store.valve_registry()[0]["control_next_sequence"])
        self.assertEqual(2, sum(c["type"] == "valve_phase_trial_open" for _, c in self.sent))

    def test_single_zone_release_is_locked_until_correlated_ack_and_cannot_reseed(self):
        self.setup_model("HTV145FRF")
        self.run_once(1); self.run_once(70)
        self.action("release", 140)
        self.assertEqual(132, self.store.htv145_control_states(self.profile.storage_key)[0]["next_sequence"])
        with self.assertRaises(RuntimeError): assert_node_available(self.store, NODE)
        journal = self.fixture.journal
        self.assertFalse(journal.acknowledge_release(self.key, node_id="rp-aabbccddeeff", phase=7))
        self.assertFalse(journal.acknowledge_release(self.key, node_id=NODE, phase=6))
        self.assertTrue(journal.acknowledge_release(self.key, node_id=NODE, phase=7))
        assert_node_available(self.store, NODE)
        with self.assertRaises(ValueError): self.action("open", 150)
        with self.assertRaises(ValueError): self.action("release", 150)

    def test_atomic_release_rolls_back_counter_and_journal_on_commit_failure(self):
        self.setup_model("HTV145FRF")
        self.run_once(1); self.run_once(70)
        connection = self.store._connection
        self.store._connection = FailCommit(connection)
        try:
            with self.assertRaises(sqlite3.OperationalError): self.action("release",140)
        finally:
            self.store._connection = connection
        self.assertEqual("complete", self.fixture.journal.snapshot(self.key)["state"])
        self.assertEqual(131,self.store.htv145_control_states(self.profile.storage_key)[0]["next_sequence"])
        self.assertFalse(any(c["type"] == "valve_phase_trial_release" for _,c in self.sent))

    def test_production_transmission_change_blocks_second_run(self):
        self.setup_model("HTV405FRF")
        self.run_once(1)
        with self.store._connection:
            self.store._connection.execute("UPDATE valve_registry SET control_last_command_started_at=?",(at(65),))
        with self.assertRaisesRegex(ValueError,"production counter changed"):
            self.action("open",70)
        self.assertEqual(1,len(self.sent))

    def test_lock_blocks_actuation_but_not_routine_ownership_configuration(self):
        self.setup_model("HTV145FRF")
        for kind in ("pairing_start","htv145_control_open","htv145_control_sync","valve_control_open"):
            with self.subTest(kind=kind), self.assertRaises(RuntimeError):
                authorize_send(self.gateway,NODE,{"type":kind})
        for kind in ("htv145_control_configure","htv145_control_status","htv405_routine_ack_configure"):
            authorize_send(self.gateway,NODE,{"type":kind})
        assert_node_available(None,NODE)

    def test_single_zone_maintenance_cannot_queue_while_trial_locked(self):
        self.setup_model("HTV145FRF")
        coordinator = Htv145ControlCoordinator(store=self.store, enabled=True,
            sender=lambda *_: self.fail("maintenance transmitted during trial"))
        sync = Htv145CounterSync(coordinator, lambda _: {"capabilities":["htv145_idle_anchor"]})
        before = self.store.htv145_counter_sync(self.profile.storage_key)
        with self.assertRaises(RuntimeError): sync.request(self.profile, now=at(1))
        self.assertEqual(before, self.store.htv145_counter_sync(self.profile.storage_key))

    def test_queued_four_zone_transaction_prevents_admission(self):
        self.setup_model("HTV405FRF")
        with self.store._connection:
            self.store._connection.execute("UPDATE valve_registry SET control_transaction_state='waiting_for_valve_report'")
        with self.assertRaisesRegex(ValueError,"unresolved"):
            eligible(self.gateway,"fixture-valve",at(1))

    def test_missing_trial_capability_prevents_admission(self):
        self.setup_model("HTV145FRF")
        self.gateway.nodes = lambda: [dict(node_id=NODE, managed=True, connected=True,
            authenticated=True,tx_armed=False,capabilities=[])]
        with self.assertRaisesRegex(ValueError,"phase-trial firmware"):
            eligible(self.gateway,"fixture-valve",at(1))

    def test_real_gateway_profiles_and_production_requests_respect_trial_lock(self):
        for model in ("HTV145FRF", "HTV405FRF"):
            with self.subTest(model=model):
                self.setup_model(model)
                gateway = Gateway(storage_path=str(self.fixture.path), valve_control_enabled=True)
                try:
                    gateway._devices = self.gateway._devices
                    endpoints = packet(self.fixture.baseline["command_frame"])[0][5:13]
                    gateway._devices["fixture-valve"]["state"].update(
                        rf_endpoint_a=endpoints[:4].hex(), rf_endpoint_b=endpoints[4:].hex())
                    gateway.register_radio_node(node_id=NODE, token="ef" * 32, name="Fixture", area=None)
                    gateway.update_node(NODE, connected=True, authenticated=True, tx_armed=False,
                        capabilities=["valve_phase_trial", "htv145_report_ack_tx", "htv145_control_tx_candidate", "valve_control_tx_candidate"])
                    gateway.set_node_command_sender(lambda node, command: self.sent.append((node,command)))
                    self.gateway = gateway
                    eligible(gateway,"fixture-valve",at(1))
                    self.run_once(1)
                    before = len(self.sent)
                    with self.assertRaises(RuntimeError):
                        gateway.request_valve_control(device_id="fixture-valve", action="open",duration_seconds=60)
                    self.assertEqual(before,len(self.sent))
                    self.run_once(70)
                    self.action("release",140)
                    self.assertEqual("releasing",PhaseTrialJournal(gateway._store).snapshot(self.key)["state"])
                finally:
                    gateway.close()
