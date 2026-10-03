"""Reply ownership admission, restart and exact-association report projection."""
import json
import unittest
from unittest.mock import patch

from tests import test_htv213_control_experiment as fixture
from tests.test_htv213_control_experiment import NODE
from research.pairing_native_transcripts import decode
from tests.test_valve_configuration import alter
from rainpointd import htv213_control_experiment as control, htv213_owner as owner
from rainpointd.htv213_control_trial import ControlJournal


class Htv213OwnerTest(unittest.TestCase):
    def setUp(self):
        fixture.Htv213ControlExperimentTest.setUp(self)
        self.gateway.update_node(NODE, capabilities=[control.CAPABILITY,owner.CAPABILITY])
        first=control.start(self.gateway,self.request)
        self.key=self.gateway._htv213_control_owner[2]
        for event in self.events:
            if event['direction']=='device':
                fixture.Htv213ControlExperimentTest.observe(self,first,event,'complete' if event==self.events[-2] else 'open_confirmed')
        self.gateway._htv213_experiment_deadline=0
        self.gateway.update_node(NODE,tx_armed=False)
        self.assertEqual(ControlJournal(self.gateway._store).snapshot(self.key)['state'],'complete')
        self.request['trial_command_id']=first['command_id']
        self.sent.clear()

    def test_configuration_persists_before_sending_and_never_opens(self):
        def send(node,command):
            self.assertIn(self.key,owner.records(self.gateway))
            self.assertEqual(command['type'],'htv213_owner_set')
            self.sent.append(command)
        self.gateway.set_node_command_sender(send)
        result=owner.configure(self.gateway,self.request)
        self.assertFalse(result['operational'])
        self.assertEqual(len(self.sent),1)
        self.assertEqual(ControlJournal(self.gateway._store).snapshot(self.key)['next_phase'],4)
        with self.assertRaises(ValueError): owner.configure(self.gateway,self.request)

    def test_old_firmware_wrong_evidence_and_store_failure_do_not_send(self):
        with self.assertRaises(ValueError): owner.configure(self.gateway,{**self.request,'trial_command_id':'bad'})
        with patch.object(self.gateway._store,'save_htv213_owner',side_effect=OSError):
            with self.assertRaises(OSError): owner.configure(self.gateway,self.request)
        self.assertEqual(self.sent,[])
        self.assertEqual(owner.records(self.gateway),{})

    def test_restore_is_configuration_only_and_does_not_replay_control(self):
        result=owner.configure(self.gateway,self.request)
        before=ControlJournal(self.gateway._store).snapshot(self.key)
        self.sent.clear()
        owner.restore(self.gateway,NODE)
        self.assertEqual(len(self.sent),1)
        self.assertEqual(self.sent[0][1]['type'],'htv213_owner_set')
        self.assertEqual(self.sent[0][1]['command_id'],result['command_id'])
        self.assertEqual(ControlJournal(self.gateway._store).snapshot(self.key),before)
        with patch.object(self.gateway._store,'ack_assignments',return_value=[{}]):
            owner.restore(self.gateway,NODE)
        self.assertEqual(len(self.sent),1)

    def test_correlated_report_changes_only_its_port_and_never_command_counter(self):
        result=owner.configure(self.gateway,self.request)
        report=next(e['frame'] for e in self.events if e['direction']=='device' and
                    decode(e['frame']).command==2)
        raw=bytearray.fromhex(report);raw[5:9]=bytes.fromhex(self.gateway.rf_identity.controller_endpoint)
        message=dict(command_id=result['command_id'],enabled=True,frame=alter(raw.hex()))
        owner.observe(self.gateway,NODE,{**message,'command_id':'wrong'})
        self.assertEqual(owner.records(self.gateway)[self.key]['ports'],{})
        owner.observe(self.gateway,NODE,message)
        self.assertEqual(set(owner.records(self.gateway)[self.key]['ports']),{'1'})
        self.assertEqual(self.gateway._nodes[NODE]['htv213_owner']['state'],'ready')
        self.assertEqual(ControlJournal(self.gateway._store).snapshot(self.key)['next_phase'],4)
