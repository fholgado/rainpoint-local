"""Offline response-correlation invariants; synthetic mutations are not RF evidence."""
import binascii
from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from tests import test_rainpoint_safety as safety
from tests import test_rainpointd as gateway_tests
from tests.test_stock_valve_frame_reference import stock_payload


def mutate_frame(raw, changes):
    """Preserve a public fixture's known trailer residue while changing fields."""
    frame = bytearray.fromhex(raw) if isinstance(raw, str) else bytearray(raw)
    residue = binascii.crc_hqx(frame[:-2], 0) ^ int.from_bytes(frame[-2:], 'big')
    for offset, value in changes.items():
        frame[offset] = value
    frame[-2:] = (binascii.crc_hqx(frame[:-2], 0) ^ residue).to_bytes(2, 'big')
    return bytes(frame)


class Htv145SequenceRegressionTest(unittest.TestCase):
    setUp = safety.Htv145RuntimeTest.setUp
    enroll = safety.Htv145RuntimeTest.enroll

    def reserve_open(self):
        self.enroll()
        return self.coordinator.request_open(self.profile, duration_seconds=60,
            started_at='2026-09-05T12:02:00+00:00')

    def test_opposite_sixth_bit_positive_cannot_resolve_reservation(self):
        self.reserve_open()
        before = self.store.htv145_control_states()[0]
        wrong_phase = mutate_frame(self.response, {13: 0x82, 14: 0x50})
        self.assertEqual(4, stock_payload(wrong_phase.hex())[9] & 63)
        with self.assertRaisesRegex(ValueError, 'marker'):
            self.coordinator.observe_frame(self.profile, wrong_phase,
                observed_at='2026-09-05T12:02:01+00:00')
        self.assertEqual(before, self.store.htv145_control_states()[0])

    def test_correct_response_cannot_predate_reservation_or_confirm_twice(self):
        self.reserve_open()
        reply = mutate_frame(self.response, {13: 0x82})
        self.assertEqual(5, stock_payload(reply.hex())[9] & 63)
        before = self.store.htv145_control_states()[0]
        with self.assertRaisesRegex(ValueError, 'predates'):
            self.coordinator.observe_frame(self.profile, reply,
                observed_at='2026-09-05T12:01:59+00:00')
        self.assertEqual(before, self.store.htv145_control_states()[0])
        confirmed = self.coordinator.observe_frame(self.profile, reply,
            observed_at='2026-09-05T12:02:01+00:00')
        self.assertEqual(0x83, confirmed['next_sequence'])
        sent = len(self.sent)
        with self.assertRaisesRegex(ValueError, 'reservation'):
            self.coordinator.observe_frame(self.profile, reply,
                observed_at='2026-09-05T12:02:02+00:00')
        self.assertEqual(confirmed, self.store.htv145_control_states()[0])
        self.assertEqual(sent, len(self.sent))

    def test_duplicate_open_is_not_dispatched_as_new_transaction(self):
        self.reserve_open()
        before, sent = self.store.htv145_control_states()[0], len(self.sent)
        with self.assertRaises(RuntimeError):
            self.coordinator.request_open(self.profile, duration_seconds=60,
                started_at='2026-09-05T12:02:20+00:00')
        self.assertEqual(before, self.store.htv145_control_states()[0])
        self.assertEqual(sent, len(self.sent))


class Htv405SequenceRegressionTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.gateway = gateway_tests.GatewayTest._gateway_with_pending_htv405_open(
            Path(temporary.name) / 'events.sqlite3')
        self.addCleanup(self.gateway.close)
        self.response = gateway_tests.GatewayTest.HTV405_OPEN_RESPONSE_SEQUENCE_6
        self.node = 'rp-001122334455'

    def test_opposite_action_same_upper_five_bits_cannot_confirm_gateway(self):
        before = self.gateway._store.valve_registry()[0]
        opposite = mutate_frame(self.response, {14: 0x50, 18: 0x4f})
        self.assertEqual(12, stock_payload(opposite.hex())[9] & 63)
        self.assertEqual(13, stock_payload(self.response)[9] & 63)
        self.assertIsNone(self.gateway.observe_valve_control_air_response(
            self.node, opposite.hex(), observed_at='2026-08-24T20:00:21+00:00'))
        self.assertEqual(before, self.gateway._store.valve_registry()[0])

    def test_stale_or_out_of_window_response_does_not_consume_pending(self):
        before = self.gateway._store.valve_registry()[0]
        for timestamp in ('2026-08-24T20:00:19+00:00', '2026-08-24T20:01:20+00:00'):
            with self.subTest(timestamp=timestamp):
                self.assertIsNone(self.gateway.observe_valve_control_air_response(
                    self.node, self.response, observed_at=timestamp))
                self.assertEqual(before, self.gateway._store.valve_registry()[0])

    def test_duplicate_open_and_duplicate_response_never_dispatch_another_open(self):
        sent = []
        self.gateway.set_node_command_sender(lambda node, command: sent.append(command))
        with self.assertRaises(RuntimeError):
            self.gateway.request_htv405_control(device_id='htv405-94a98013',
                action='open', zone=1, duration_seconds=60,
                now=datetime.fromisoformat('2026-08-24T20:00:40+00:00'))
        self.assertEqual([], sent)
        confirmed = self.gateway.observe_valve_control_air_response(
            self.node, self.response, observed_at='2026-08-24T20:00:21+00:00')
        self.assertIsNotNone(confirmed)
        self.assertIsNone(self.gateway.observe_valve_control_air_response(
            self.node, self.response, observed_at='2026-08-24T20:00:22+00:00'))
        self.assertEqual(confirmed, self.gateway._store.valve_registry()[0])
        self.assertEqual([], sent)


if __name__ == '__main__':
    unittest.main()
