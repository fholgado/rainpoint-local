"""Explicit, evidence-backed repair uses only stored RF and sends no actuation."""
import sqlite3
import unittest

from tests import test_valve_phase_handoff as fixtures
from tests.test_valve_phase_trial import NODE, at
from tests.valve_native_helpers import FailCommit, alter
from rainpointd.valve_phase_trial import assert_node_available
from rainpointd.valve_phase_experiment import observe


class PhaseRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.h = fixtures.ValvePhaseHandoffTest()
        self.addCleanup(self.h.doCleanups)
        self.h.setup_model("HTV145FRF", baseline_phase=1)
        self.h.gateway.nodes = lambda: [dict(node_id=NODE, managed=True, connected=True,
            authenticated=True, tx_armed=False,
            capabilities=["valve_phase_trial", "valve_phase_trial_recovery"])]
        self.h.gateway.update_node = lambda *_args, **_kwargs: None
        self.h.action("open",1)
        self.journal = self.h.fixture.journal
        self.journal.expire(self.h.key,now=at(17))
        self.before = self.journal.snapshot(self.h.key)
        frames = self.h.fixture.frames(2)
        self.events=[]
        for eid, second, frame in zip((10,11,12),(2,7,63),frames):
            event=dict(event_id=eid, observed_at=at(second), event_type="device_observation",
                device_id="fixture-valve", model="HTV145FRF", raw=frame,
                state=dict(rf_frame_accepted=True,rf_node_id=NODE))
            self.h.store.append(event); self.events.append(event)
        self.request=dict(authorization_id=self.h.key,event_ids=[10,11,12])

    def recover(self):
        return self.h.action("recover",70,self.request)

    def test_failed_history_preserved_until_correlated_radio_recovery_ack(self):
        self.assertEqual(self.recover()["state"],"recovering")
        after=self.journal.snapshot(self.h.key)
        self.assertEqual(after["transactions"],self.before["transactions"])
        self.assertEqual(after["failure"],self.before["failure"])
        self.assertEqual(after["recovery"]["previous_state"],"failed")
        with self.assertRaises(RuntimeError): assert_node_available(self.h.store,NODE)
        command=self.h.sent[-1][1]
        self.assertEqual(command["type"],"valve_phase_trial_recover")
        self.assertEqual(command["ack_frame"],self.events[0]["raw"])
        self.assertEqual(command["idle_age_ms"],62000)
        self.recover()
        self.assertEqual(command,self.h.sent[-1][1]) # Lost response: same non-RF handoff only.
        for node, phase, cid in (("rp-aabbccddeeff",2,command["command_id"]),
                (NODE,3,command["command_id"]),(NODE,2,"ab"*16)):
            observe(self.h.gateway,node,dict(authorization_id=self.h.key,stage=7,phase=phase,command_id=cid))
            with self.assertRaises(RuntimeError): assert_node_available(self.h.store,NODE)
        observe(self.h.gateway,NODE,dict(authorization_id=self.h.key,stage=7,phase=2,command_id=command["command_id"]))
        assert_node_available(self.h.store,NODE)
        self.assertEqual(self.journal.snapshot(self.h.key)["state"],"recovered")
        with self.assertRaises(ValueError): self.h.action("open",80)
        with self.assertRaises(ValueError): self.recover()
        self.assertEqual(sum(c["type"]=="valve_phase_trial_open" for _,c in self.h.sent),1)

    def test_storage_failure_keeps_lock_and_never_sends_recovery(self):
        connection=self.h.store._connection
        self.h.store._connection=FailCommit(connection)
        try:
            with self.assertRaises(sqlite3.OperationalError): self.recover()
        finally: self.h.store._connection=connection
        self.assertEqual(self.journal.snapshot(self.h.key),self.before)
        self.assertEqual(len(self.h.sent),1)

    def test_missing_tampered_foreign_and_negative_evidence_rejected(self):
        cases=[dict(state=dict(rf_frame_accepted=False,rf_node_id=NODE)),
               dict(state=dict(rf_frame_accepted=True,rf_node_id="rp-aabbccddeeff")),
               dict(device_id="another-valve"),dict(raw=alter(self.events[0]["raw"],phase=3)),
               dict(raw=alter(self.events[0]["raw"],data=bytes.fromhex("06219f00000000813c00ad3c00"))),
               dict(observed_at=at(20))]
        import json
        for changes in cases:
            with self.subTest(changes=changes):
                event={**self.events[0],**changes}
                with self.h.store._connection:
                    self.h.store._connection.execute("UPDATE events SET payload=? WHERE event_id=10",(json.dumps(event),))
                with self.assertRaises(ValueError): self.recover()
                self.assertEqual(self.journal.snapshot(self.h.key),self.before)
        with self.h.store._connection:
            self.h.store._connection.execute("UPDATE events SET payload=? WHERE event_id=10",(json.dumps(self.events[0]),))
        self.request["event_ids"]=[10,11,999]
        with self.assertRaises(ValueError): self.recover()
        self.assertEqual(len(self.h.sent),1)

    def test_later_result_or_watering_invalidates_old_anchor(self):
        for frame in (alter(self.events[0]["raw"],phase=3),self.events[1]["raw"]):
            event={**self.events[0],"event_id":20,"observed_at":at(65),"raw":frame}
            self.h.store.append(event)
            with self.assertRaises(ValueError): self.recover()
            with self.h.store._connection: self.h.store._connection.execute("DELETE FROM events WHERE event_id=20")

    def test_old_firmware_or_changed_production_state_cannot_recover(self):
        nodes=self.h.gateway.nodes
        self.h.gateway.nodes=lambda:[{**nodes()[0],"capabilities":["valve_phase_trial"]}]
        with self.assertRaisesRegex(ValueError,"signed recovery"): self.recover()
        self.h.gateway.nodes=nodes
        with self.h.store._connection:
            self.h.store._connection.execute("UPDATE htv145_control_state SET last_command_started_at=?",(at(66),))
        with self.assertRaisesRegex(ValueError,"transmission changed"): self.recover()
        self.assertEqual(len(self.h.sent),1)
