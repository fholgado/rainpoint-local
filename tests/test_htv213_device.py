"""HA-facing dry canary qualification, controls, pending UI and deletion."""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tests import test_htv213_owner as fixture
from tests.test_htv213_control_experiment import NODE
from tests.test_valve_configuration import alter
from research.pairing_native_transcripts import decode
from rainpointd import htv213_device as device, htv213_owner as owner, htv213_control_experiment as control
from rainpointd.htv213_control_trial import ControlJournal
from tests.test_watering_notifications import module as notification_module

ROOT=Path(__file__).resolve().parents[1]


class Htv213DeviceTest(unittest.TestCase):
    def setUp(self):
        fixture.Htv213OwnerTest.setUp(self)
        self.owner=owner.configure(self.gateway,self.request)
        self.journal=ControlJournal(self.gateway._store)
        trials=json.loads((ROOT/'research/fixtures/htv213_local_outlet_stop_20260930.json').read_text())['trials']
        for trial in trials:
            for event in trial['events']:
                packet=decode(event['frame'])
                if event['direction']=='gateway' and packet.command==0x21:
                    action='open' if packet.data[2] else 'close'
                    seconds=int.from_bytes(packet.data[3:5],'little') if action=='open' else 0
                    self.tx=self.journal.reserve(self.key,action=action,port=packet.data[0],seconds=seconds,dry_confirmed=True)
                    self.journal.dispatch(self.key,self.tx,lambda *_:None)
                elif event['direction']=='device':
                    raw=bytearray.fromhex(event['frame']);raw[5:9]=bytes.fromhex(self.gateway.rf_identity.controller_endpoint)
                    frame=alter(raw.hex())
                    self.journal.observe(self.key,node_id=NODE,frame=frame)
                    owner.observe(self.gateway,NODE,dict(command_id=self.owner['command_id'],enabled=True,frame=frame))
        self.assertEqual(self.journal.snapshot(self.key)['state'],'complete')
        self.assertEqual(self.journal.snapshot(self.key)['next_phase'],7)
        self.sent.clear()

    def publish(self):
        return device.publish(self.gateway,dict(association_key=self.key,name='Two outlets'))

    def test_qualified_device_has_two_real_outlets_and_no_speculative_telemetry(self):
        result=self.publish()
        state=result['state']
        self.assertEqual(result['model'],'HTV213FRF')
        self.assertTrue(state['rf_control_start_available'])
        self.assertFalse(state['zone_1_is_watering'])
        self.assertFalse(state['zone_2_is_watering'])
        self.assertNotIn('zone_3_is_watering',state)
        self.assertNotIn('last_usage_liters',state)
        self.assertNotIn('battery_percent',state)
        self.assertEqual(self.sent,[])
        self.assertIn(result['device_id'], {d['device_id'] for d in self.gateway.devices()})

    def test_publish_requires_real_completion_and_fresh_both_port_idle(self):
        records=owner.records(self.gateway)
        records[self.key]['ports']['2']['watering']=True
        self.gateway._store.save_htv213_owner(json.dumps(records))
        with self.assertRaises(ValueError): self.publish()
        self.assertEqual(self.sent,[])

    def test_reconnected_node_without_trial_status_projects_retained_idle(self):
        # A real reconnect has no in-memory control trial, unlike the setup
        # fixture that just completed an experiment on the same connection.
        self.gateway.update_node(NODE, htv213_control=None)
        result = self.publish()
        self.assertTrue(result['state']['rf_control_start_available'])
        self.assertEqual(result['state']['rf_control_transaction_state'], 'confirmed')
        self.assertEqual(self.sent, [])

    def test_public_control_uses_persisted_profile_no_repeat_and_no_optimistic_open(self):
        target=self.publish()['device_id']
        result=self.gateway.request_valve_control(device_id=target,action='open',zone=2,duration_seconds=60)
        command=self.sent[-1][1]
        self.assertEqual((command['phase'],command['port'],command['seconds']),(7,2,60))
        self.assertEqual(command['factory_endpoint'],self.request['factory_endpoint'])
        state=device.project(self.gateway)[target]['state']
        self.assertTrue(state['rf_control_command_pending'])
        self.assertFalse(state['rf_control_start_available'])
        self.assertIsNone(state['is_watering'])
        self.assertIsNone(state['zone_2_is_watering'])
        self.assertFalse(state['zone_1_is_watering'])
        with self.assertRaises(ValueError):
            self.gateway.request_valve_control(device_id=target,action='open',zone=2,duration_seconds=60)
        self.assertEqual(len(self.sent),1)
        later=device.project(self.gateway,datetime.now(timezone.utc)+timedelta(seconds=12))[target]['state']
        self.assertFalse(later['rf_control_command_pending'])
        self.assertEqual(later['rf_control_transaction_state'],'failed')
        self.assertIsNotNone(later['rf_control_transaction_error'])
        self.assertEqual(self.journal.snapshot(self.key)['next_phase'],8)

    def test_public_controls_do_not_use_experimental_admission_or_journal(self):
        with patch.object(control, 'eligible', side_effect=AssertionError('experimental admission')), \
             patch.object(control, 'dispatch', side_effect=AssertionError('experimental dispatch')), \
             patch.object(ControlJournal, 'reserve', side_effect=AssertionError('experimental reservation')):
            target = self.publish()['device_id']
            self.gateway.request_valve_control(device_id=target, action='open', zone=1, duration_seconds=60)
        self.assertEqual(len(self.sent), 1)
        command = self.sent[0][1]
        self.assertEqual((command['phase'], command['port'], command['seconds']), (7, 1, 60))
        self.assertTrue(device.project(self.gateway)[target]['state']['rf_control_command_pending'])
        self.assertEqual(self.journal.snapshot(self.key)['next_phase'], 8)

    def test_normal_firmware_uses_non_probe_open_and_close_without_changing_phases(self):
        capabilities = self.gateway._nodes[NODE]['capabilities']
        self.gateway.update_node(NODE, capabilities=[c for c in capabilities
            if c not in {'htv213_pairing_experiment', 'htv213_control_experiment'}] + ['htv213_control_v1'])
        target = self.publish()['device_id']
        device.request(self.gateway, target, 'open', 1, 60)
        self.assertEqual(self.sent[-1][1]['type'], 'htv213_control_open')
        self.assertEqual(self.sent[-1][1]['phase'], 7)
        self.replay_report(0xa1)
        self.replay_report(2)
        device.request(self.gateway, target, 'close', 1)
        self.assertEqual(self.sent[-1][1]['type'], 'htv213_control_close')
        self.assertEqual(self.sent[-1][1]['phase'], 8)
        self.assertEqual(self.journal.snapshot(self.key)['next_phase'], 9)

    def test_older_test_firmware_keeps_its_deployed_command_names(self):
        target = self.publish()['device_id']
        device.request(self.gateway, target, 'open', 1, 60)
        self.assertEqual(self.sent[-1][1]['type'], 'htv213_control_probe_open')
        self.replay_report(0xa1)
        self.replay_report(2)
        device.request(self.gateway, target, 'close', 1)
        self.assertEqual(self.sent[-1][1]['type'], 'htv213_control_probe_close')

    def replay_report(self, command, *, idle=False):
        event = next(e for e in self.events if e['direction'] == 'device' and
                     decode(e['frame']).command == command and
                     (command != 2 or (decode(e['frame']).data[3] == 0) == idle))
        raw = bytearray.fromhex(event['frame'])
        raw[5:9] = bytes.fromhex(self.gateway.rf_identity.controller_endpoint)
        frame = alter(raw.hex(), phase=7) if command == 0xa1 else alter(raw.hex())
        self.journal.observe(self.key, node_id=NODE, frame=frame)
        owner.observe(self.gateway, NODE, dict(command_id=self.owner['command_id'], enabled=True, frame=frame))

    def test_missing_ack_never_reuses_precommand_idle_and_late_evidence_recovers(self):
        target = self.publish()['device_id']
        device.request(self.gateway, target, 'open', 1, 60)
        later = datetime.now(timezone.utc) + timedelta(seconds=12)
        state = device.project(self.gateway, later)[target]['state']
        self.assertIsNone(state['zone_1_is_watering'])
        self.assertEqual(state['valve_state'], 'unknown')
        self.assertEqual(state['rf_control_transaction_state'], 'failed')
        self.assertFalse(state['rf_control_available'])
        for action in ('open', 'close'):
            with self.assertRaises(ValueError): device.request(self.gateway, target, action, 1, 60)
        self.replay_report(0xa1)
        self.assertIsNone(device.project(self.gateway)[target]['state']['is_watering'])
        self.replay_report(2)
        self.assertTrue(device.project(self.gateway)[target]['state']['is_watering'])
        self.replay_report(2, idle=True)
        self.replay_report(4)
        state = device.project(self.gateway)[target]['state']
        self.assertFalse(state['is_watering'])
        self.assertTrue(state['rf_control_start_available'])
        self.assertEqual(self.journal.snapshot(self.key)['next_phase'], 8)
        self.assertEqual(len(self.sent), 1)

    def test_confirmed_idle_missing_summary_is_not_an_overdue_open(self):
        target = self.publish()['device_id']
        device.request(self.gateway, target, 'open', 1, 60)
        self.replay_report(0xa1)
        self.replay_report(2)
        self.replay_report(2, idle=True)
        state = device.project(self.gateway, datetime.now(timezone.utc) + timedelta(seconds=130))[target]['state']
        self.assertFalse(state['is_watering'])
        self.assertFalse(state['rf_control_overdue'])
        self.assertEqual(state['rf_control_transaction_state'], 'failed')
        self.assertIn('summary', state['rf_control_transaction_error'].lower())
        self.assertFalse(state['rf_control_start_available'])
        self.assertEqual(len(self.sent), 1)

    def test_missing_ack_recovers_after_new_both_outlet_idle_without_resending(self):
        self.check_missing_ack_recovery(reconnect=False)

    def test_missing_ack_recovery_survives_lost_gateway_runtime_and_radio_reboot(self):
        self.check_missing_ack_recovery(reconnect=True)

    def check_missing_ack_recovery(self, *, reconnect):
        from rainpointd import htv213_control_transport as transport
        self.gateway._nodes[NODE]['capabilities'].append('htv213_idle_recovery_v1')
        target = self.publish()['device_id']
        device.request(self.gateway, target, 'open', 1, 60)
        tx = self.journal.snapshot(self.key)['transaction']
        transport.observe(self.gateway, NODE, dict(command_id=tx['command_id'], state='uncertain'))
        self.assertEqual(device.project(self.gateway)[target]['state']['rf_control_transaction_state'], 'failed')
        if reconnect:
            self.gateway._nodes[NODE]['capabilities'].append(owner.IDLE_RESUME_CAPABILITY)
            self.gateway._htv213_control_owner = None
            self.gateway.update_node(NODE, htv213_control=None)
            owner.restore(self.gateway, NODE)
            restored = self.sent[-1][1]
            self.assertEqual(restored['type'], 'htv213_owner_set')
            self.assertEqual(restored['recovery_command_id'], tx['command_id'])
            self.assertFalse(device.project(self.gateway)[target]['state']['rf_control_start_available'])
        trials = json.loads((ROOT/'research/fixtures/htv213_local_outlet_stop_20260930.json').read_text())['trials']
        for port in (1, 2):
            event = next(e for trial in trials for e in trial['events']
                         if e['direction'] == 'device' and decode(e['frame']).command == 2
                         and decode(e['frame']).data[2:4] == bytes((port, 0)))
            raw = bytearray.fromhex(event['frame'])
            raw[5:9] = bytes.fromhex(self.gateway.rf_identity.controller_endpoint)
            owner.observe(self.gateway, NODE, dict(command_id=self.owner['command_id'],
                enabled=True, frame=alter(raw.hex())))
            if port == 1:
                self.assertFalse(device.project(self.gateway)[target]['state']['rf_control_start_available'])
        # Fresh reports alone do not bypass a radio still holding the command.
        self.assertFalse(device.project(self.gateway)[target]['state']['rf_control_start_available'])
        transport.observe(self.gateway, NODE, dict(command_id=tx['command_id'], state='recovered_idle'))
        state = device.project(self.gateway)[target]['state']
        self.assertTrue(state['rf_control_start_available'])
        self.assertEqual(state['rf_control_transaction_state'], 'recovered_idle')
        self.assertFalse(state['is_watering'])
        self.assertEqual(self.journal.snapshot(self.key)['next_phase'], 8)
        self.assertFalse(self.journal.snapshot(self.key)['transaction']['acknowledged'])
        self.assertEqual(len(self.sent), 2 if reconnect else 1)
        self.assertIn('unknown', state['rf_control_transaction_status'])
        self.assertFalse(self.gateway._nodes[NODE]['tx_armed'])
        self.assertEqual(self.gateway._htv213_experiment_deadline, 0)
        # The recovered disposition survives journal reload; a late ACK does
        # not rewrite the old unknown outcome into a successful run.
        self.replay_report(0xa1)
        self.assertEqual(ControlJournal(self.gateway._store).snapshot(self.key)['state'], 'recovered_idle')
        # Only a new user action emits another open, with the next phase.
        device.request(self.gateway, target, 'open', 2, 60)
        self.assertEqual(len(self.sent), 3 if reconnect else 2)
        self.assertEqual(self.sent[-1][1]['phase'], 8)
        prior = self.journal.snapshot(self.key)['history'][-1]
        self.assertFalse(prior['acknowledged'])
        self.assertFalse(prior['summary'])
        self.assertEqual(prior['outcome'], 'unknown')

    def test_idle_recovery_rejects_stale_partial_active_and_uncorrelated_evidence(self):
        from rainpointd import htv213_control_transport as transport
        target = self.publish()['device_id']
        self.gateway._nodes[NODE]['capabilities'].append(transport.IDLE_RECOVERY_CAPABILITY)
        device.request(self.gateway, target, 'open', 1, 60)
        tx = self.journal.snapshot(self.key)['transaction']
        baseline = owner.records(self.gateway)
        for report in baseline[self.key]['ports'].values():
            report.update(watering=False, remaining_seconds=0, requested_seconds=0,
                          observed_at=datetime.now(timezone.utc).isoformat())
        node = copy.deepcopy(self.gateway._nodes[NODE])
        journal_baseline = self.journal._records()
        for case in ('old_firmware', 'wrong_command', 'wrong_node', 'pending_owner', 'revoked',
                     'one_port', 'active', 'stale', 'pre_command', 'invalid_timestamp', 'nonzero',
                     'future', 'disconnected', 'unauthenticated', 'boundary', 'acknowledged', 'close'):
            with self.subTest(case=case):
                records = copy.deepcopy(baseline)
                self.gateway._nodes[NODE] = copy.deepcopy(node)
                journal_records = copy.deepcopy(journal_baseline)
                report = records[self.key]['ports']['1']
                message = dict(command_id=tx['command_id'], state='recovered_idle')
                sender = NODE
                if case == 'old_firmware': self.gateway._nodes[NODE]['capabilities'].remove(transport.IDLE_RECOVERY_CAPABILITY)
                elif case == 'wrong_command': message['command_id'] = 'old-command'
                elif case == 'wrong_node': sender = 'rp-000000000099'
                elif case == 'pending_owner': self.gateway._nodes[NODE]['htv213_owner']['state'] = 'pending'
                elif case == 'revoked': records[self.key]['revoking'] = True
                elif case == 'one_port': records[self.key]['ports'].pop('2')
                elif case == 'active': report['watering'] = True
                elif case == 'stale': report['observed_at'] = (datetime.now(timezone.utc)-timedelta(seconds=1201)).isoformat()
                elif case == 'pre_command': report['observed_at'] = tx['reserved_at']
                elif case == 'invalid_timestamp': report['observed_at'] = 'not-a-time'
                elif case == 'nonzero': report['remaining_seconds'] = 1
                elif case == 'future': report['observed_at'] = (datetime.now(timezone.utc)+timedelta(seconds=60)).isoformat()
                elif case == 'disconnected': self.gateway._nodes[NODE]['connected'] = False
                elif case == 'unauthenticated': self.gateway._nodes[NODE]['authenticated'] = False
                elif case == 'boundary': journal_records[self.key]['counter_boundary'] = {'complete': False}
                elif case == 'acknowledged': journal_records[self.key]['transaction']['acknowledged'] = True
                elif case == 'close': journal_records[self.key]['transaction']['action'] = 'close'
                self.journal._save(journal_records)
                self.gateway._store.save_htv213_owner(json.dumps(records))
                transport.observe(self.gateway, sender, message)
                self.assertEqual(self.journal.snapshot(self.key)['state'], 'indeterminate')
                self.assertEqual(self.journal.snapshot(self.key)['next_phase'], 8)
                self.assertEqual(len(self.sent), 1)
                if case != 'revoked':
                    self.assertFalse(device.project(self.gateway)[target]['state']['rf_control_start_available'])

    def test_overdue_report_does_not_invent_stop_and_completion_needs_rf(self):
        target = self.publish()['device_id']
        device.request(self.gateway, target, 'open', 1, 60)
        self.replay_report(0xa1)
        self.replay_report(2)
        now = datetime.now(timezone.utc) + timedelta(seconds=130)
        state = device.project(self.gateway, now)[target]['state']
        self.assertTrue(state['is_watering'])
        self.assertTrue(state['rf_control_overdue'])
        self.assertFalse(state['rf_control_available'])
        self.assertEqual(state['rf_control_transaction_state'], 'failed')
        self.replay_report(2, idle=True)
        self.replay_report(4)
        state = device.project(self.gateway, now)[target]['state']
        self.assertFalse(state['rf_control_overdue'])
        self.assertFalse(state['is_watering'])
        self.assertTrue(state['rf_control_start_available'])
        self.assertEqual(len(self.sent), 1)

    def test_gateway_failure_replay_drives_one_persistent_alert_and_real_stop(self):
        target = self.publish()['device_id']
        notices = []
        reporter = notification_module.WateringNotifications('test', lambda message, **kw: notices.append((message, kw)))
        reporter.observe(device.project(self.gateway))
        device.request(self.gateway, target, 'open', 1, 60)
        reporter.observe(device.project(self.gateway))
        self.assertEqual(notices, [])
        self.replay_report(0xa1); self.replay_report(2)
        reporter.observe(device.project(self.gateway))
        self.assertEqual(len(notices), 1)
        later = datetime.now(timezone.utc) + timedelta(seconds=130)
        reporter.observe(device.project(self.gateway, later))
        reporter.observe(device.project(self.gateway, later))
        self.assertEqual(len(notices), 2)
        self.assertIn('expected stop has not been confirmed', notices[-1][0])
        self.assertTrue(notices[-1][1]['notification_id'].endswith('_problem'))
        self.replay_report(2, idle=True); self.replay_report(4)
        reporter.observe(device.project(self.gateway, later))
        self.assertEqual(len(notices), 3)
        self.assertIn('reported that watering stopped', notices[-1][0])
        self.assertEqual(len(self.sent), 1)

    def test_disconnect_and_stale_reports_do_not_invent_idle_or_enable_commands(self):
        target=self.publish()['device_id']
        self.gateway.update_node(NODE,connected=False)
        self.assertFalse(device.project(self.gateway)[target]['available'])
        with self.assertRaises(ValueError): device.request(self.gateway,target,'open',1,60)
        self.gateway.update_node(NODE,connected=True)
        state=device.project(self.gateway,datetime.now(timezone.utc)+timedelta(hours=1))[target]['state']
        self.assertIsNone(state['is_watering'])
        self.assertFalse(state['rf_control_start_available'])
        self.assertEqual(self.sent,[])

    def test_forget_persists_revoke_tombstone_before_clear_and_restart_never_restores(self):
        target=self.publish()['device_id']
        result=self.gateway.forget_registry_device(target)
        self.assertTrue(result['ownership_cleanup_pending'])
        self.assertNotIn(target,device.project(self.gateway))
        self.assertEqual(self.sent[-1][1]['type'],'htv213_owner_clear')
        self.sent.clear()
        owner.restore(self.gateway,NODE)
        self.assertEqual(self.sent[-1][1]['type'],'htv213_owner_clear')
        owner.observe(self.gateway,NODE,dict(command_id=self.owner['command_id'],enabled=False))
        self.assertTrue(owner.records(self.gateway)[self.key]['revoked'])
        self.assertEqual(self.journal.snapshot(self.key)['next_phase'],7)
        with self.assertRaises(ValueError): owner.configure(self.gateway,self.request)

    def test_forget_command_passes_actual_firmware_command_id_validation(self):
        from tests.test_htv213_runtime import function
        target=self.publish()['device_id']
        self.gateway.forget_registry_device(target)
        command=self.sent[-1][1]
        validator=function((ROOT/'firmware/rainpoint_bridge/src/main.cpp').read_text(),
                           'bool validCommandId(')
        source='#include <string>\n#include <cctype>\nusing String=std::string;\n'+validator
        source+='\nint main() { return validCommandId('+json.dumps(command['command_id'])+') ? 0 : 1; }'
        with tempfile.TemporaryDirectory() as folder:
            executable=str(Path(folder)/'command-id')
            subprocess.run([shutil.which('c++'),'-std=c++17','-x','c++','-','-o',executable],
                           input=source,text=True,capture_output=True,check=True)
            result=subprocess.run([executable],capture_output=True)
        self.assertEqual(result.returncode,0,'owner-clear command must reach firmware dispatch')
        self.assertEqual(command['owner_id'],self.owner['command_id'])

    def test_persistence_failure_does_not_publish_or_dispatch(self):
        with patch.object(self.gateway._store,'save_htv213_owner',side_effect=OSError):
            with self.assertRaises(OSError): self.publish()
        self.assertEqual(device.project(self.gateway),{})
        self.assertEqual(self.sent,[])

    def test_boundary_api_requires_published_idle_owner_and_explicit_authorization(self):
        proof = dict(prior_command_id=self.journal.snapshot(self.key)['transaction']['command_id'],
                     authorization_id='ef'*16)
        request = {**self.request, 'counter_boundary':proof}
        with self.assertRaises(ValueError): control.start(self.gateway, request)
        self.publish()
        result = control.start(self.gateway, request)
        self.assertEqual(result['phase'], 62)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][1]['phase'], 62)
        with self.assertRaises(ValueError): control.start(self.gateway, request)
        self.assertEqual(len(self.sent), 1)
