"""Offline stock-firmware/capture boundary checks; no actuator authority.

The stock CMT payload starts after the first bit of normalized byte 4. These tests
cross-check its fields against independently labeled, retained RF captures.
They do not change runtime framing, counters, or acceptance policy.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest


FIXTURES = Path(__file__).resolve().parents[1] / "research" / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def stock_payload(frame_hex: str) -> bytes:
    frame = bytes.fromhex(frame_hex)
    if len(frame) != 38 or frame[:5] != bytes.fromhex("79f4882f28"):
        raise ValueError("expected a normalized RainPoint frame")
    return bytes(((frame[i + 4] << 1) | (frame[i + 5] >> 7)) & 255 for i in range(32))


class StockValveFrameReferenceTests(unittest.TestCase):
    def assert_control(self, frame_hex: str, *, port: int, seconds: int) -> bytes:
        payload = stock_payload(frame_hex)
        self.assertEqual(payload[0], 0x51)
        self.assertEqual(payload[10] & 0x7F, 0x21)
        self.assertFalse(payload[10] & 0x80)
        self.assertEqual(payload[11] & 0x1F, 5 if seconds else 3)
        self.assertEqual(payload[12:15], bytes((port, 2, bool(seconds))))
        self.assertEqual(int.from_bytes(payload[15:17], "little"), seconds)
        # The final payload bit overlaps the first bit of the historical
        # normalized trailer; do not assume that boundary bit is padding zero.
        self.assertEqual(payload[17:31], bytes(14))
        return payload

    def test_four_zone_stock_controls_have_native_ports_and_seconds(self):
        fixture = load_fixture("htv405_stock_cloud_control_matrix_20260824.json")
        phases = []
        for trial in fixture["trials"]:
            with self.subTest(zone=trial["zone"]):
                opened = self.assert_control(trial["open_command_frame"], port=trial["zone"], seconds=60)
                closed = self.assert_control(trial["close_command_frame"], port=trial["zone"], seconds=0)
                phases.extend((opened[9] & 63, closed[9] & 63))
        self.assertEqual(phases, list(range(3, 11)))

    def test_single_zone_stock_seconds_cross_normalized_marker_boundary(self):
        fixture = load_fixture("htv145_selector6_stock_duration_commands_20260828.json")
        phases = []
        for transaction in fixture["transactions"]:
            frames = [row["raw"] for row in transaction.get("request_frames", [])]
            if "request_frame" in transaction:
                frames.append(transaction["request_frame"])
            for frame in frames:
                with self.subTest(action=transaction["action"], seconds=transaction.get("duration_seconds", 0)):
                    payload = self.assert_control(frame, port=1, seconds=transaction.get("duration_seconds", 0))
                    reply = stock_payload(transaction["response_frame"])
                    self.assertEqual(reply[9] & 63, payload[9] & 63)
                    self.assertEqual(reply[10], payload[10] | 0x80)
            phases.append(payload[9] & 63)
        self.assertEqual(phases, [3, 4, 5, 6])

    def test_two_consecutive_positive_opens_advance_phase_not_action_bit(self):
        fixture = load_fixture("htv145_selector2_stock_pairing_control_20260905.json")
        phases = []
        actions = []
        for run in fixture["controls"]:
            for command in run["commands"]:
                seconds = run["requested_seconds"] if command["action"] == "open" else 0
                payload = self.assert_control(command["frame"], port=1, seconds=seconds)
                phases.append(payload[9] & 63)
                actions.append(command["action"])
        self.assertEqual(actions, ["open", "open", "close", "open", "close"])
        self.assertEqual(phases, [3, 4, 5, 6, 7])

    def test_four_zone_report_durations_are_also_native_little_endian_seconds(self):
        fixture = load_fixture("htv405_packed_duration_boundary_20260902.json")
        for trial, native_remaining in zip(fixture["trials"], (294, 895), strict=True):
            with self.subTest(seconds=trial["requested_seconds"]):
                payload = stock_payload(trial["active_report"])
                self.assertEqual(int.from_bytes(payload[25:27], "little"), trial["reported_duration_seconds"])
                remaining = int.from_bytes(payload[22:24], "little")
                self.assertEqual(remaining, native_remaining)
                # Preserve the old fixture's reported result as evidence of
                # its discarded one-second bit, rather than rewriting it.
                self.assertEqual(remaining & ~1, trial["reported_remaining_seconds"])

    def test_stock_pairing_reply_echoes_full_six_bit_sequence(self):
        fixture = load_fixture("htv145_selector2_stock_pairing_control_20260905.json")
        frames = [stock_payload(row["frame"]) for row in fixture["pairing"]["frames"]]
        for request_index, response_index in ((0, 1), (2, 3), (4, 5), (6, 7), (8, 9), (10, 11)):
            with self.subTest(request=request_index):
                request, response = frames[request_index], frames[response_index]
                self.assertEqual(response[9] & 63, request[9] & 63)
                self.assertEqual(response[10], request[10] | 0x80)


if __name__ == "__main__":
    unittest.main()
