"""Offline ownership transitions use real Gateway/SQLite and simulated radio replies."""
from pathlib import Path
import tempfile
import unittest

from tests.test_stock_informed_regressions import Gateway, NODE, OLD, setup_rejoin
from rainpointd.ack_ownership import CAPABILITY
from rainpointd.esp32 import ESP32SerialTransport
from unittest.mock import patch
from types import SimpleNamespace
from tests.test_integration_migration import _integration_function
import json

OTHER = 'rp-aabbccddeeff'
VALVE = 'htv405-94a98013'


def connect(gateway, node, session='connection-1'):
    gateway.update_node(node, connected=True, authenticated=True, connected_at=session,
        tx_armed=False, capabilities=['rx', 'valve_control_tx_candidate', 'htv405_routine_ack_tx',
            'routine_sensor_ack_tx', 'configurable_rf_controller_identity', 'retained_sensor_rejoin_channel', CAPABILITY])


def setup_valve(gateway):
    gateway._store.accept_paired_valve_link(controller_endpoint='ee86de80',
        valve_endpoint='94a98013', device_id=VALVE, name='Offline fixture valve',
        model='HTV405FRF', area='Fixture', accepted_at=OLD)
    gateway._store.update_valve_control_profile(valve_endpoint='94a98013', node_id=NODE,
        companion_endpoint='6e86de80', selector=5, frequency_offset_hz=97154, observed_at=OLD)
    connect(gateway, NODE)
    connect(gateway, OTHER)


def response(command):
    valve = command['type'].startswith('htv405_')
    return {'type': 'ack_ownership_status', 'kind': 'htv405' if valve else 'sensor',
        'endpoint': command['valve_endpoint' if valve else 'paired_endpoint'],
        'state': 'revoked' if command['type'].endswith('_revoke') else 'configured',
        **{key: command[key] for key in ('command_id', 'ownership_generation', 'ownership_session')}}


class AckOwnershipTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'events.sqlite3')
        self.gateway = Gateway(storage_path=self.path, valve_control_enabled=True)
        self.addCleanup(lambda: self.gateway.close())
        setup_valve(self.gateway)
        self.sent = []
        self.gateway.set_node_command_sender(lambda node, command: self.sent.append((node, command)))

    def reply(self, node, command, **changes):
        message = {**response(command), **changes}
        ESP32SerialTransport(self.gateway, device='offline').consume_line(
            json.dumps(message), authenticated_node_id=node)

    def restart(self):
        self.gateway.close()
        self.gateway = Gateway(storage_path=self.path, valve_control_enabled=True)
        self.gateway.set_node_command_sender(lambda node, command: self.sent.append((node, command)))
        connect(self.gateway, NODE, 'connection-2')
        connect(self.gateway, OTHER, 'connection-2')

    def test_failed_delivery_cannot_grant_replacement(self):
        def fail(node, command):
            self.sent.append((node, command))
            raise ConnectionError('offline test')
        self.gateway.set_node_command_sender(fail)
        self.gateway.assign_htv405_control_node(device_id=VALVE, node_id=OTHER)
        self.assertEqual([(NODE, 'htv405_routine_ack_revoke')], [(n, c['type']) for n, c in self.sent])
        self.assertEqual('delivery_failed', self.gateway.info()['ack_ownership_operations'][0]['state'])

    def test_handoff_requires_correlated_revoke_and_configure(self):
        self.gateway.assign_htv405_control_node(device_id=VALVE, node_id=OTHER)
        self.assertEqual(1, len(self.sent))
        command = self.sent[-1][1]
        for wrong in ({'command_id': 'stale'}, {'ownership_generation': 'stale'},
                      {'ownership_session': 'old'}, {'endpoint': 'deadbeef'}, {'state': 'configured'}):
            self.reply(NODE, command, **wrong)
            self.assertEqual(1, len(self.sent))
        self.reply(OTHER, command)
        self.assertEqual(1, len(self.sent))
        self.reply(NODE, command)
        self.assertEqual(OTHER, self.sent[-1][0])
        self.assertEqual('htv405_routine_ack_configure', self.sent[-1][1]['type'])
        self.assertEqual(NODE, self.gateway._store.valve_registry()[0]['control_node_id'])
        self.reply(OTHER, self.sent[-1][1])
        self.assertEqual(OTHER, self.gateway._store.valve_registry()[0]['control_node_id'])
        self.assertEqual([], self.gateway.info()['ack_ownership_operations'])
        count = len(self.sent)
        self.reply(NODE, command)
        self.assertEqual(count, len(self.sent))

    def test_delete_tombstone_survives_restart_without_registry_row(self):
        self.gateway.forget_registry_device(VALVE)
        old = self.sent[-1][1]
        self.restart()
        self.gateway.restore_radio_node_htv405_ack_assignments(NODE)
        self.assertEqual('htv405_routine_ack_revoke', self.sent[-1][1]['type'])
        self.assertNotEqual(old['command_id'], self.sent[-1][1]['command_id'])
        self.reply(NODE, old)
        self.assertEqual(1, len(self.gateway.info()['ack_ownership_operations']))
        self.reply(NODE, self.sent[-1][1])
        self.assertEqual([], self.gateway.info()['ack_ownership_operations'])
        self.assertEqual([], self.gateway._store.valve_registry())

    def test_sensor_handoff_blocks_restore_and_known_rejoin_until_confirmed(self):
        setup_rejoin(self.gateway, 5)
        connect(self.gateway, NODE)
        self.gateway.register_radio_node(node_id=OTHER, token='cd' * 32, name='Other', area=None)
        connect(self.gateway, OTHER)
        self.sent.clear()
        self.gateway.assign_radio_node_ack(node_id=OTHER, paired_endpoint='9bce0024', assigned_channel=5)
        command = self.sent[-1][1]
        self.assertEqual(NODE, self.gateway.ack_assignments()[0]['node_id'])
        self.assertEqual(0, self.gateway.restore_radio_node_ack_assignments(NODE))
        self.assertEqual(1, len(self.sent))
        event = self.gateway.observe_rf_frame(frame='79f4882f28' + '00' * 33,
            state={'hcs026_pairing_state': 'factory', 'hcs026_factory_endpoint': '1bce0024',
                   'rf_receiver_id': NODE})
        self.assertEqual('ack_ownership_cleanup_pending', event['state']['automatic_rejoin']['reason'])
        self.reply(NODE, command)
        self.reply(OTHER, self.sent[-1][1])
        self.assertEqual(OTHER, self.gateway.ack_assignments()[0]['node_id'])
        self.assertEqual(5, self.gateway.ack_assignments()[0]['assigned_channel'])

    def test_legacy_firmware_cannot_claim_revocation_confirmation(self):
        self.gateway.update_node(NODE, capabilities=['htv405_routine_ack_tx'])
        self.gateway.assign_htv405_control_node(device_id=VALVE, node_id=OTHER)
        self.assertEqual([], self.sent)
        self.assertEqual('owner_firmware_upgrade_required', self.gateway.info()['ack_ownership_operations'][0]['state'])

    def test_configure_failure_remains_blocked_and_reconnect_retries_only_configure(self):
        self.gateway.assign_htv405_control_node(device_id=VALVE, node_id=OTHER)
        self.reply(NODE, self.sent[-1][1])
        failed = self.sent[-1][1]
        self.reply(OTHER, failed, state='rejected')
        self.assertEqual('command_failed', self.gateway.info()['ack_ownership_operations'][0]['state'])
        self.assertEqual(NODE, self.gateway._store.valve_registry()[0]['control_node_id'])
        self.restart()
        before = len(self.sent)
        self.gateway.restore_radio_node_htv405_ack_assignments(NODE)
        self.assertEqual(before, len(self.sent))
        self.gateway.restore_radio_node_htv405_ack_assignments(OTHER)
        self.assertEqual('htv405_routine_ack_configure', self.sent[-1][1]['type'])
        self.reply(OTHER, failed)
        self.assertEqual(NODE, self.gateway._store.valve_registry()[0]['control_node_id'])
        self.reply(OTHER, self.sent[-1][1])
        self.assertEqual(OTHER, self.gateway._store.valve_registry()[0]['control_node_id'])

    def test_current_connection_and_authenticated_parser_are_required(self):
        self.gateway.assign_htv405_control_node(device_id=VALVE, node_id=OTHER)
        command = self.sent[-1][1]
        ESP32SerialTransport(self.gateway, device='offline').consume_line(json.dumps(response(command)))
        self.assertEqual(1, len(self.sent))
        connect(self.gateway, NODE, 'new-connection')
        self.reply(NODE, command)
        self.assertEqual(1, len(self.sent))
        self.gateway.restore_radio_node_htv405_ack_assignments(NODE)
        self.assertNotEqual(command['command_id'], self.sent[-1][1]['command_id'])
        self.gateway.update_node(NODE, authenticated=False)
        self.reply(NODE, self.sent[-1][1])
        self.assertEqual(2, len(self.sent))

    def test_journal_write_failure_prevents_dispatch(self):
        with patch.object(self.gateway._store, 'set_metadata_value', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.gateway.assign_htv405_control_node(device_id=VALVE, node_id=OTHER)
        self.assertEqual([], self.sent)
        self.assertEqual(NODE, self.gateway._store.valve_registry()[0]['control_node_id'])

    def test_synchronous_confirmation_is_not_lost(self):
        def immediate(node, command):
            self.sent.append((node, command))
            self.reply(node, command)
        self.gateway.set_node_command_sender(immediate)
        self.gateway.assign_htv405_control_node(device_id=VALVE, node_id=OTHER)
        self.assertEqual(OTHER, self.gateway._store.valve_registry()[0]['control_node_id'])
        self.assertEqual([], self.gateway.info()['ack_ownership_operations'])

    def test_sensor_deletion_and_readdition_cannot_drop_cleanup(self):
        setup_rejoin(self.gateway, 5)
        connect(self.gateway, NODE)
        with self.gateway._lock:
            self.gateway._delete_ack_assignment_locked('9bce0024')
        self.assertEqual([], self.gateway.ack_assignments())
        self.restart()
        with self.assertRaisesRegex(RuntimeError, 'cleanup'):
            self.gateway.assign_radio_node_ack(node_id=NODE, paired_endpoint='9bce0024', assigned_channel=5)
        with self.assertRaisesRegex(RuntimeError, 'cleanup'):
            self.gateway.start_pairing()
        self.gateway.restore_radio_node_ack_assignments(NODE)
        self.reply(NODE, self.sent[-1][1])
        self.assertEqual([], self.gateway.info()['ack_ownership_operations'])

    def test_cleanup_blocks_control_and_exposes_node_diagnostics(self):
        self.gateway.assign_htv405_control_node(device_id=VALVE, node_id=OTHER)
        with self.assertRaisesRegex(RuntimeError, 'cleanup'):
            self.gateway._htv405_control_profile(self.gateway._store.valve_registry()[0])
        with self.assertRaisesRegex(RuntimeError, 'cleanup'):
            self.gateway.revoke_radio_node(NODE)
        node = next(item for item in self.gateway.nodes() if item['node_id'] == NODE)
        self.assertEqual('pending', node['ack_ownership_state'])
        self.assertIsNone(node['ack_ownership_operations'][0]['confirmed_active_owner'])
        self.assertNotIn('target', node['ack_ownership_operations'][0])

    def test_ha_cleanup_diagnostic_is_visible_even_when_radio_is_offline(self):
        attributes = _integration_function('sensor.py', 'extra_state_attributes', {},
            classname='RainPointRadioNodeSensor')
        available = _integration_function('sensor.py', 'available', {},
            classname='RainPointRadioNodeSensor')
        entity = SimpleNamespace(entity_description=SimpleNamespace(key='ack_ownership_state'),
            coordinator=SimpleNamespace(last_update_success=True),
            node={'connected': False, 'ack_ownership_operations': [{'state': 'owner_offline'}]})
        self.assertTrue(available.fget(entity))
        self.assertEqual({'operations': [{'state': 'owner_offline'}]}, attributes.fget(entity))
        entity.coordinator.last_update_success = False
        self.assertFalse(available.fget(entity))
