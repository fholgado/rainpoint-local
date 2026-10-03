"""Remaining seconds retain the bit crossing normalized-byte boundaries."""
import unittest

from tests.test_stock_informed_regressions import ROOT
from rainpointd.valve_protocol import _decode_htv405_remaining_duration
from tests.test_stock_valve_frame_reference import load_fixture, stock_payload


class RemainingTimeRegressionTest(unittest.TestCase):
    def test_captured_odd_and_even_remaining_time(self):
        fixture = load_fixture('htv405_packed_duration_boundary_20260902.json')
        for trial in fixture['trials']:
            frame = bytes.fromhex(trial['active_report'])
            expected = int.from_bytes(stock_payload(frame.hex())[22:24], 'little')
            self.assertEqual(expected, _decode_htv405_remaining_duration(frame[26:28], frame[28] & 0x80))

    def test_every_remaining_second_in_supported_range(self):
        for seconds in range(3601):
            low, high = seconds.to_bytes(2, 'little')
            encoded = bytes((0x80 | (low >> 1), ((low & 1) << 7) | (high >> 1)))
            self.assertEqual(seconds, _decode_htv405_remaining_duration(encoded, (high & 1) << 7))

    def test_invalid_marker_length_and_range(self):
        for encoded, extension in ((b'', 0), (b'\x00\x00', 0), (b'\x80\x00', 1), (b'\xff\xff', 128)):
            with self.subTest(encoded=encoded, extension=extension), self.assertRaises(ValueError):
                _decode_htv405_remaining_duration(encoded, extension)
