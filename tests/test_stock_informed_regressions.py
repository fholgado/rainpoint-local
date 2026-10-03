"""Offline real-seam regressions prompted by the stock/local comparison."""
from datetime import datetime
import binascii
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'rainpointd_addon'))

from rainpointd.ingest import FrameIngestor
from rainpointd.storage import SQLiteEventStore
from tests.support import CapturedInstallationGateway as Gateway, observe_captured_sensor_route
from tests.test_integration_migration import _integration_function
from tests import test_rainpoint_safety as safety

MEASUREMENT = '79f4882f28b9840280c4e500241081820385c41c000000000000000000000000000000003169'
STOCK_ACK = ('79f4882f28c4e500243984028088c181000100000000'
             '000000000000000000000000000022e3')
OLD = '2026-09-20T10:00:00+00:00'
FRESH = '2026-09-20T12:00:00+00:00'
NODE = 'rp-001122334455'


def consume(ingestor, frame, observed_at):
    return ingestor.consume_event({'time': observed_at,
        'rows': [{'len': len(frame) * 4, 'data': frame}]})


def soil(gateway):
    return next(d for d in gateway.devices(now=datetime.fromisoformat(FRESH))
                if d['device_id'] == 'soil-left-bed')


def connected_sensor_owner(gateway):
    gateway.update_node(NODE, connected=True, authenticated=True,
        protocol_version=2, capabilities=['rx', 'sensor_pairing_tx',
            'configurable_rf_controller_identity', 'routine_sensor_ack_tx', 'retained_sensor_rejoin_channel'])


def setup_rejoin(gateway, selector):
    gateway._store.upsert_enrollment_record({
        'factory_endpoint': '1bce0024', 'paired_endpoint': '9bce0024',
        'enrolled_at': OLD, 'last_seen_at': OLD})
    gateway.register_radio_node(node_id=NODE, token='ab' * 32,
                               name='Offline fixture radio', area='Fixture')
    connected_sensor_owner(gateway)
    observe_captured_sensor_route(gateway)
    return gateway.assign_radio_node_ack(node_id=NODE,
        paired_endpoint='9bce0024', assigned_channel=selector)


class SoilFreshnessRegressionTest(unittest.TestCase):
    def test_valid_nonmeasurement_sensor_frame_does_not_refresh_moisture(self):
        with tempfile.TemporaryDirectory() as directory:
            gateway = Gateway(storage_path=str(Path(directory) / 'gateway.sqlite3'))
            self.addCleanup(gateway.close)
            ingestor = FrameIngestor(gateway)
            consume(ingestor, MEASUREMENT, OLD)
            # Synthetic valid nonmeasurement event derived from the captured
            # association, not a claim about an observed heartbeat serializer.
            frame = bytearray.fromhex(MEASUREMENT)
            frame[13] = 4
            frame[14:36] = bytes(22)
            frame[-2:] = (binascii.crc_hqx(frame[:-2], 0) ^ 0x4f03).to_bytes(2, 'big')
            consume(ingestor, frame.hex(), FRESH)
            event = gateway.events()[-1]
            self.assertTrue(event['state']['rf_frame_accepted'])
            self.assertEqual('paired', event['state']['hcs026_pairing_state'])
            self.assertNotIn('device_id', event)
            device = soil(gateway)
            self.assertEqual(OLD, device['observed_at'])
            self.assertEqual(56, device['state']['soil_moisture_percent'])
            self.assertFalse(device['reporting'])

    def test_stock_ack_preserves_stale_moisture_through_restart_and_ha(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'gateway.sqlite3')
            gateway = Gateway(storage_path=path)
            self.addCleanup(gateway.close)
            ingestor = FrameIngestor(gateway)
            self.assertEqual(1, consume(ingestor, MEASUREMENT, OLD))
            self.assertEqual(1, consume(ingestor, STOCK_ACK, FRESH))
            event = gateway.events()[-1]
            self.assertEqual('rf_frame', event['event_type'])
            self.assertTrue(event['state']['rf_trailer_valid'])
            self.assertNotIn('device_id', event)
            gateway.close()
            gateway = Gateway(storage_path=path)
            self.addCleanup(gateway.close)
            device = soil(gateway)
            self.assertEqual(56, device['state']['soil_moisture_percent'])
            self.assertEqual(OLD, device['observed_at'])
            self.assertEqual(7200, device['report_age_seconds'])
            self.assertFalse(device['reporting'])
            # Execute the actual HA property with only the coordinator-backed
            # device lookup replaced; no Home Assistant instance is needed.
            reporting = _integration_function('binary_sensor.py', 'is_on', {},
                classname='RainPointReportingBinarySensor')
            self.assertFalse(reporting.fget(SimpleNamespace(device=device)))
            attributes = _integration_function('binary_sensor.py',
                'extra_state_attributes', {}, classname='RainPointReportingBinarySensor')
            self.assertEqual(7200, attributes.fget(SimpleNamespace(device=device))['report_age_seconds'])
            self.assertEqual(1, consume(FrameIngestor(gateway), MEASUREMENT, FRESH))
            current = soil(gateway)
            self.assertEqual(FRESH, current['observed_at'])
            self.assertEqual(0, current['report_age_seconds'])
            self.assertTrue(reporting.fget(SimpleNamespace(device=current)))

    def test_invalid_measurement_does_not_refresh_old_measurement(self):
        with tempfile.TemporaryDirectory() as directory:
            gateway = Gateway(storage_path=str(Path(directory) / 'gateway.sqlite3'))
            self.addCleanup(gateway.close)
            ingestor = FrameIngestor(gateway)
            consume(ingestor, MEASUREMENT, OLD)
            damaged = bytearray.fromhex(MEASUREMENT)
            damaged[-1] ^= 1
            consume(ingestor, damaged.hex(), FRESH)
            device = soil(gateway)
            self.assertEqual(56, device['state']['soil_moisture_percent'])
            self.assertEqual(OLD, device['observed_at'])
            self.assertFalse(device['reporting'])


class RetainedSelectorRegressionTest(unittest.TestCase):
    def test_legacy_firmware_cannot_silently_rejoin_selector_five_on_four(self):
        with tempfile.TemporaryDirectory() as directory:
            gateway = Gateway(storage_path=str(Path(directory) / 'events.sqlite3'))
            self.addCleanup(gateway.close)
            setup_rejoin(gateway, 5)
            gateway.update_node(NODE, capabilities=['sensor_pairing_tx',
                'configurable_rf_controller_identity', 'routine_sensor_ack_tx'])
            commands = []
            gateway.set_node_command_sender(lambda node, command: commands.append(command))
            event = gateway.observe_rf_frame(frame='79f4882f28' + '00' * 33,
                state={'hcs026_pairing_state': 'factory', 'hcs026_factory_endpoint': '1bce0024',
                       'rf_receiver_id': NODE}, observed_at=FRESH)
            self.assertEqual('ack_owner_firmware_incompatible', event['state']['automatic_rejoin']['reason'])
            self.assertEqual([], commands)

    def test_known_rejoin_carries_retained_selector(self):
        for selector in (4, 5):
            with self.subTest(selector=selector), tempfile.TemporaryDirectory() as directory:
                gateway = Gateway(storage_path=str(Path(directory) / 'events.sqlite3'))
                self.addCleanup(gateway.close)
                setup_rejoin(gateway, selector)
                commands = []
                gateway.set_node_command_sender(lambda node, command: commands.append(command))
                event = gateway.observe_rf_frame(frame='79f4882f28' + '00' * 33,
                    state={'hcs026_pairing_state': 'factory',
                           'hcs026_factory_endpoint': '1bce0024', 'rf_receiver_id': NODE},
                    observed_at=FRESH)
                self.assertTrue(event['state']['automatic_rejoin']['requested'])
                self.assertEqual(selector, commands[-1].get('assigned_channel'))

    def test_supported_selectors_persist_and_reconnect_restores_exact_route(self):
        for selector in (4, 5):
            with self.subTest(selector=selector), tempfile.TemporaryDirectory() as directory:
                path = str(Path(directory) / 'gateway.sqlite3')
                gateway = Gateway(storage_path=path)
                assignment = setup_rejoin(gateway, selector)
                gateway.close()
                restored = Gateway(storage_path=path)
                self.addCleanup(restored.close)
                commands = []
                restored.set_node_command_sender(lambda node, command: commands.append((node, command)))
                connected_sensor_owner(restored)
                self.assertEqual(1, restored.restore_radio_node_ack_assignments(NODE))
                self.assertEqual(selector, commands[-1][1]['assigned_channel'])
                for field in ('controller_endpoint', 'companion_endpoint', 'paired_endpoint'):
                    self.assertEqual(assignment[field], commands[-1][1][field])
                self.assertEqual(selector, restored.ack_assignments()[0]['assigned_channel'])


class Htv145RevocationRegressionTest(unittest.TestCase):
    setUp = safety.Htv145RuntimeTest.setUp
    enroll = safety.Htv145RuntimeTest.enroll

    def test_failed_revoke_is_durable_and_reconnect_cannot_grant_again(self):
        self.enroll()
        self.sent.clear()
        def fail(node, command):
            self.sent.append((node, command))
            raise ConnectionError('fixture disconnected before delivery')
        self.coordinator.sender = fail
        with self.assertRaises(ConnectionError):
            self.runtime.revoke(self.profile)
        command = self.sent[-1][1]
        self.store.close()
        self.store = SQLiteEventStore(Path(self.temp.name) / 'events.sqlite3')
        self.coordinator.store = self.store
        self.assertEqual(command['command_id'],
            self.store.htv145_control_states()[0]['revocation_command_id'])
        self.node['connected_at'] = 'connection-2'
        self.coordinator.sender = lambda node, message: self.sent.append((node, message))
        with self.assertRaisesRegex(RuntimeError, 'revocation is pending'):
            self.runtime.restore(self.profile, now=FRESH)
        self.assertEqual(1, len(self.sent))
        confirmation = {**command, 'state': 'revoked'}
        self.runtime.observe_node('rp-aabbccddeeff', confirmation, now=FRESH)
        self.assertEqual(1, len(self.store.htv145_control_states()))
        self.runtime.observe_node(NODE, {**confirmation, 'command_id': 'stale'}, now=FRESH)
        self.assertEqual(1, len(self.store.htv145_control_states()))
        self.runtime.observe_node(NODE, confirmation, now=FRESH)
        self.assertEqual([], self.store.htv145_control_states())
        self.runtime.observe_node(NODE, confirmation, now=FRESH)
        self.assertEqual([], self.store.htv145_control_states())
