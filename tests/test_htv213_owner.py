"""Reply ownership admission, restart and exact-association report projection."""
import json
import copy
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import unittest
from unittest.mock import patch

from tests import test_htv213_control_experiment as fixture
from tests.test_htv213_control_experiment import NODE
from research.pairing_native_transcripts import decode
from tests.test_valve_configuration import alter
from rainpointd import htv213_control_experiment as control, htv213_owner as owner
from rainpointd.htv213_control_trial import ControlJournal
from rainpointd.http import create_server


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

    def test_reconnect_restores_unknown_open_observation_not_transmission(self):
        owner.configure(self.gateway, self.request)
        self.gateway._nodes[NODE]['capabilities'] += ['htv213_idle_recovery_resume_v1']
        result = control.start(self.gateway, self.request)
        journal = ControlJournal(self.gateway._store)
        before = journal.snapshot(self.key)
        self.gateway._htv213_control_owner = None  # Includes a gateway restart.
        self.sent.clear()
        owner.restore(self.gateway, NODE)
        self.assertEqual(len(self.sent), 1)
        command = self.sent[0][1]
        self.assertEqual(command['type'], 'htv213_owner_set')
        self.assertEqual(command['recovery_command_id'], result['command_id'])
        self.assertEqual(command['recovery_phase'], before['transaction']['phase'])
        self.assertEqual(command['recovery_port'], before['transaction']['port'])
        self.assertEqual(command['recovery_seconds'], before['transaction']['requested_seconds'])
        self.assertEqual(journal.snapshot(self.key), before)
        self.assertEqual(self.gateway._htv213_control_owner, (NODE, result['command_id'], self.key))

    def test_reconnect_does_not_resume_ineligible_transaction_or_identity(self):
        owner.configure(self.gateway, self.request)
        control.start(self.gateway, self.request)
        journal = ControlJournal(self.gateway._store)
        baseline = journal._records()
        for case in ('old_firmware', 'acked', 'close', 'complete', 'boundary', 'node', 'selector', 'route', 'epoch'):
            with self.subTest(case=case):
                records = copy.deepcopy(baseline)
                record = records[self.key]
                self.gateway._nodes[NODE]['capabilities'] = [control.CAPABILITY, owner.CAPABILITY,
                    'htv213_idle_recovery_resume_v1']
                if case == 'old_firmware': self.gateway._nodes[NODE]['capabilities'].pop()
                elif case == 'acked': record['transaction']['acknowledged'] = True
                elif case == 'close': record['transaction']['action'] = 'close'
                elif case == 'complete': record['state'] = 'complete'
                elif case == 'boundary': record['counter_boundary'] = {'complete': False}
                elif case == 'node': record['identity']['node_id'] = 'rp-000000000099'
                elif case == 'selector': record['identity']['selector'] = 12
                elif case == 'route': record['identity']['controller'] = 'aabbccdd'
                elif case == 'epoch':
                    owners = owner.records(self.gateway)
                    owners[self.key]['enrollment_id'] = '0' * 32
                    self.gateway._store.save_htv213_owner(json.dumps(owners))
                journal._save(records)
                self.sent.clear()
                owner.restore(self.gateway, NODE)
                self.assertNotIn('recovery_command_id', self.sent[-1][1])
                self.assertEqual(journal._records(), records)

    def recovery_request(self):
        self.gateway.update_node(NODE, capabilities=[control.CAPABILITY, owner.CAPABILITY, owner.REJOIN_CAPABILITY])
        config = copy.deepcopy(owner.records(self.gateway)[self.key]['configuration'])
        config['revision'] = 7
        config['ports'][1]['settings'] = '0102030405060708090a0b0c0d0e'
        return dict(association_key=self.key, enabled=True, configuration=config)

    def test_explicit_recovery_configuration_survives_restart_without_counter_changes(self):
        result = owner.configure(self.gateway, self.request)
        before = ControlJournal(self.gateway._store).snapshot(self.key)
        request = self.recovery_request()
        self.sent.clear()
        owner.configure_recovery(self.gateway, request)
        command = self.sent[-1][1]
        self.assertEqual(command['type'], 'htv213_owner_set')
        self.assertEqual(command['configuration_revision'], 7)
        self.assertEqual(command['port_2_settings'], request['configuration']['ports'][1]['settings'])
        self.assertTrue(command['retained_rejoin_enabled'])
        owner.restore(self.gateway, NODE)
        self.assertEqual(self.sent[-1][1], command)
        self.assertEqual(ControlJournal(self.gateway._store).snapshot(self.key), before)
        # An old in-flight status cannot confirm the new configuration.
        self.gateway.update_node(NODE, htv213_owner=None)
        owner.observe(self.gateway, NODE, dict(command_id=result['command_id'], enabled=True))
        self.assertIsNone(self.gateway._nodes[NODE].get('htv213_owner'))
        owner.observe(self.gateway, NODE, dict(command_id=result['command_id'], enabled=True,
                      retained_rejoin_enabled=True, configuration_revision=7))
        self.assertTrue(self.gateway._nodes[NODE]['htv213_owner']['retained_rejoin_enabled'])

    def test_recovery_missing_configuration_changed_identity_and_commit_failure_send_nothing(self):
        owner.configure(self.gateway, self.request)
        request = self.recovery_request()
        self.sent.clear()
        for field, value in (('selector', 12), ('address', 99), ('model', 'HTV405FRF')):
            changed = copy.deepcopy(request)
            changed['configuration'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                owner.configure_recovery(self.gateway, changed)
        with self.assertRaises(ValueError):
            owner.configure_recovery(self.gateway, {**request, 'configuration': None})
        before = owner.records(self.gateway)
        with patch.object(self.gateway._store, 'save_htv213_owner', side_effect=OSError):
            with self.assertRaises(OSError): owner.configure_recovery(self.gateway, request)
        self.assertEqual(owner.records(self.gateway), before)
        self.assertEqual(self.sent, [])

    def test_recovery_opt_in_is_not_restored_to_old_firmware_or_another_owner(self):
        owner.configure(self.gateway, self.request)
        request = self.recovery_request()
        owner.configure_recovery(self.gateway, request)
        self.sent.clear()
        self.gateway.update_node(NODE, capabilities=[owner.CAPABILITY])
        owner.restore(self.gateway, NODE)
        with self.assertRaises(ValueError): owner.configure_recovery(self.gateway, request)
        self.assertEqual(self.sent, [])
        self.gateway.update_node(NODE, capabilities=[owner.CAPABILITY, owner.REJOIN_CAPABILITY])
        with patch.object(self.gateway._store, 'ack_assignments', return_value=[{}]):
            owner.restore(self.gateway, NODE)
            with self.assertRaises(ValueError): owner.configure_recovery(self.gateway, request)
        self.assertEqual(self.sent, [])

    def test_original_canary_owner_migrates_known_empty_configuration_without_enabling_rejoin(self):
        owner.configure(self.gateway, self.request)
        saved = owner.records(self.gateway)
        del saved[self.key]['configuration']
        for key in list(saved[self.key]['command']):
            if key.startswith('port_') or key in ('configuration_revision', 'retained_rejoin_enabled'):
                del saved[self.key]['command'][key]
        self.gateway._store.save_htv213_owner(json.dumps(saved))
        self.sent.clear()
        owner.restore(self.gateway, NODE)
        command = self.sent[-1][1]
        self.assertEqual(command['configuration_revision'], 2)
        self.assertFalse(command['retained_rejoin_enabled'])
        self.assertEqual(command['port_1_settings'], '58020a001e000000000000000000')
        self.assertIn('configuration', owner.records(self.gateway)[self.key])

    def test_recovery_http_is_authenticated_and_sends_configuration_only(self):
        owner.configure(self.gateway, self.request)
        body = self.recovery_request()
        self.sent.clear()
        server = create_server(self.gateway, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}/api/v1/experiments/htv213/recovery'
            headers = {'Content-Type': 'application/json'}
            with self.assertRaises(HTTPError) as raised:
                urlopen(Request(url, data=json.dumps(body).encode(), headers=headers), timeout=2)
            self.assertEqual(raised.exception.code, 401)
            raised.exception.close()
            self.assertEqual(self.sent, [])
            headers['Authorization'] = 'Bearer test-token'
            with self.assertRaises(HTTPError) as malformed:
                urlopen(Request(url, data=json.dumps({**body, 'association_key': []}).encode(),
                                headers=headers), timeout=2)
            self.assertEqual(malformed.exception.code, 400)
            malformed.exception.close()
            self.assertEqual(self.sent, [])
            with urlopen(Request(url, data=json.dumps(body).encode(), headers=headers), timeout=2) as response:
                self.assertEqual(response.status, 202)
                self.assertTrue(json.load(response)['retained_rejoin_enabled'])
            self.assertEqual([message['type'] for _, message in self.sent], ['htv213_owner_set'])
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)
