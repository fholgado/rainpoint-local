"""Replay phase-independent builders; never qualify RF acceptance by synthesis."""
import binascii
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import sys

from tests.valve_native_helpers import decode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'rainpointd_addon'))
from rainpointd.valve_command_phase import build_command, decode_envelope, matches_positive_result
from rainpointd.valve_protocol import ValveLink
FIXTURES = ROOT / "research/fixtures"


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


class FullCommandPhaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("c++")
        if not compiler:
            raise unittest.SkipTest("native C++ compiler unavailable")
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.probe = str(Path(cls.directory.name) / "phase-probe")
        subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-I" + str(ROOT / "firmware/rainpoint_bridge/include"),
            str(ROOT / "firmware/rainpoint_bridge/tests/valve_command_phase_probe.cpp"),
            "-o", cls.probe], check=True, capture_output=True, text=True)

    def build(self, rows):
        result = subprocess.run([self.probe], input="\n".join(rows) + "\n",
                                check=True, capture_output=True, text=True)
        output = result.stdout.splitlines()
        self.assertEqual(len(rows), len(output))
        return [line.split()[1] if line.startswith("1 ") else None for line in output]

    @staticmethod
    def row(model, phase, opened, seconds=None, port=1, selector=5, residue=0x4f03,
            a="b1c2d38f", b="a1b2c380"):
        seconds = (60 if opened else 0) if seconds is None else seconds
        return f"{model} {phase} {int(opened)} {seconds} {port} {selector} {residue} {a} {b}"

    def test_all_phases_are_independent_of_action_and_keep_existing_bodies(self):
        cases = [(model, phase, opened, port) for model in ("145", "405")
                 for phase in range(64) for opened in (False, True)
                 for port in (range(1, 5) if model == "405" else (1,))]
        rows = []
        for model, phase, opened, port in cases:
            rows += [self.row(model, phase, opened, port=port),
                     self.row("legacy" + model, phase >> 1, opened, port=port)]
        frames = self.build(rows)
        for index, (model, phase, opened, port) in enumerate(cases):
            actual, legacy = frames[index*2:index*2+2]
            with self.subTest(model=model, phase=phase, opened=opened, port=port):
                self.assertIsNotNone(actual)
                observed, old = decode(actual), decode(legacy)
                self.assertEqual(observed.phase, phase)
                self.assertEqual(observed.command, 0x21)
                self.assertEqual(observed.data, old.data)
                self.assertEqual(observed.route, old.route)
                self.assertEqual(len(observed.data), 5 if opened else 3)
                raw, original = bytes.fromhex(actual), bytes.fromhex(legacy)
                self.assertEqual(raw[:14], original[:14])
                self.assertEqual(raw[15:36], original[15:36])
                # Every previously emitted phase is byte-for-byte unchanged.
                if bool(phase & 1) == opened:
                    self.assertEqual(actual, legacy)

    def test_gateway_builder_matches_radio_for_all_phases_actions_ports_and_durations(self):
        link = ValveLink(bytes.fromhex('b1c2d38f'), bytes.fromhex('a1b2c380'))
        cases = [(model, phase, action, port, seconds)
                 for model in ('145', '405') for phase in range(64)
                 for action in ('open', 'close')
                 for port in (range(1, 5) if model == '405' else (1,))
                 for seconds in ((60, 1260, 3600) if action == 'open' else (None,))]
        expected = self.build([self.row(model, phase, action == 'open',
            seconds=seconds or 0, port=port) for model, phase, action, port, seconds in cases])
        for case, wire in zip(cases, expected):
            model, phase, action, port, seconds = case
            with self.subTest(case=case):
                actual = build_command(model='HTV' + model + 'FRF', link=link,
                    phase=phase, action=action, port=port, duration_seconds=seconds,
                    residue=0x4f03, selector=5)
                self.assertEqual(actual.hex(), wire)
                self.assertEqual(decode_envelope(actual).phase, phase)

    def test_native_result_codec_replays_captured_success_and_negative_results(self):
        data = fixture('htv145_active_counter_recovery_20260906.json')
        matched = 0
        for transaction in data['command_transactions']:
            response = transaction.get('response_frame')
            if response:
                request, reply = [decode_envelope(f) for f in (transaction['command_frame'], response)]
                if reply.command == 0xa1:
                    self.assertEqual(matches_positive_result(request, reply,
                        model='HTV145FRF', port=1), reply.data[0] == 0)
                    matched += 1
        self.assertGreaterEqual(matched, 3)

    def test_both_existing_single_zone_marker_policies_are_unchanged(self):
        rows = []
        for counter in range(32):
            for opened in (False, True):
                phase = 2 * counter + int(not opened)
                rows += [self.row("145", phase, opened),
                         self.row("legacy145normal", counter, opened)]
        frames = self.build(rows)
        for i in range(0, len(frames), 2):
            self.assertEqual(frames[i], frames[i+1])

    def test_existing_duration_and_association_guards_are_not_relaxed(self):
        for model in ("145", "405"):
            rows = [self.row(model, 64, True), self.row(model, 255, True),
                    self.row(model, 0, True, seconds=0),
                    self.row(model, 0, True, seconds=61),
                    self.row(model, 0, False, seconds=60),
                    self.row(model, 0, True, residue=0),
                    self.row(model, 0, True, a="00000000"),
                    self.row(model, 0, True, a="a1b2c380")]
            self.assertEqual(self.build(rows), [None] * len(rows))
        self.assertEqual(self.build([self.row("405", 0, True, port=0),
                                     self.row("405", 0, True, port=5),
                                     self.row("405", 0, True, selector=11),
                                     self.row("405", 0, True, seconds=3660)]), [None]*4)

    def assert_single_replays(self, captured):
        rows = []
        for frame in captured:
            raw = bytes.fromhex(frame)
            packet = decode(frame)
            self.assertEqual(packet.command, 0x21)
            self.assertEqual(packet.data[:2], b"\x01\x02")
            opened = packet.data[2] == 1
            residue = binascii.crc_hqx(raw[:36], 0) ^ int.from_bytes(raw[36:], "big")
            rows.append(self.row("145", packet.phase, opened,
                                 seconds=int.from_bytes(packet.data[3:], "little"),
                                 residue=residue, a=raw[5:9].hex(), b=raw[9:13].hex()))
        self.assertEqual(self.build(rows), captured)

    def test_stock_single_zone_consecutive_opens_replay_exactly(self):
        data = fixture("htv145_selector2_stock_pairing_control_20260905.json")
        frames = [row["command_frame"] for row in data["command_transactions"]]
        self.assertEqual([decode(f).phase for f in frames], [3, 4, 5, 6, 7])
        self.assert_single_replays(frames)

    def test_single_zone_selector6_stock_durations_and_retries_replay_exactly(self):
        data = fixture("htv145_selector6_stock_duration_commands_20260828.json")
        frames = []
        for row in data["transactions"]:
            frames.extend(attempt["raw"] for attempt in row.get("request_frames", []))
            if "request_frame" in row:
                frames.append(row["request_frame"])
        self.assertGreaterEqual(len(frames), 4)
        self.assert_single_replays(frames)

    def test_single_zone_historical_active_close_jump_and_wrap_replay_exactly(self):
        data = fixture("htv145_active_counter_recovery_20260906.json")
        frames = [row["command_frame"] for row in data["command_transactions"]]
        self.assertEqual([decode(f).phase for f in frames], [5, 0, 1, 2, 3, 62, 63, 0])
        self.assert_single_replays(frames)
        # These are active-close anchors, not four consecutive automatic runs.
        self.assertEqual([decode(f).data[2] for f in frames], [1, 0, 1, 0, 1, 0, 1, 0])

    def test_four_zone_stock_opens_have_both_parities(self):
        ordinary = fixture("htv405_stock_cloud_control_matrix_20260824.json")
        stopped = fixture("htv405_stock_early_stop_20260824.json")
        odd_opens = [decode(t["open_command_frame"]) for t in ordinary["trials"]]
        even_runs = [t for t in stopped["runs"] if t["open_command"]]
        even_opens = [decode(t["open_command"]["frame"]) for t in even_runs]
        self.assertEqual([p.phase for p in odd_opens], [3, 5, 7, 9])
        self.assertEqual([p.phase for p in even_opens], [20, 22])
        for packet in odd_opens + even_opens:
            self.assertEqual(packet.data[1:], b"\x02\x01\x3c\x00")
        for run in even_runs:
            opened, closed = [decode(run[name]["frame"]) for name in ("open_command", "close_command")]
            self.assertEqual(closed.phase, opened.phase + 1)
            self.assertEqual(closed.data, bytes((run["zone"], 2, 0)))
            # Independent state coverage exists, but there is no immediate
            # a1 stored for these two runs; do not invent matched ACK evidence.
            self.assertEqual(decode(run["active_report"]["frame"]).command, 2)
            self.assertEqual(decode(run["idle_report"]["frame"]).command, 2)

    def result_views(self, frames):
        result = subprocess.run([self.probe], input="\n".join("result " + f for f in frames) + "\n",
                                check=True, capture_output=True, text=True)
        return [tuple(map(int, line.split())) for line in result.stdout.splitlines()]

    def test_four_zone_reply_control_mode_is_not_request_port(self):
        data = fixture("htv405_stock_early_stop_20260824.json")["authenticated_counter_examples"][0]
        request, response = decode(data["open_command"]["frame"]), decode(data["open_response"]["frame"])
        self.assertEqual(request.data, b"\x04\x02\x01\x3c\x00")
        self.assertEqual(response.phase, request.phase)
        self.assertEqual(self.result_views([data["open_response"]["frame"]]), [(1, 9, 0, 2, 1)])
        # The retained native state is mode 2/work 1, not a reply port of 1.
        # Port 4 comes from the request; physical evidence remains separate.
        self.assertEqual(response.data[1], 0x21)

    def test_result_phase_and_state_are_independent_for_all_64_values(self):
        data = fixture("htv145_active_counter_recovery_20260906.json")
        frames, expected = [], []
        for row in data["command_transactions"][:2]:
            raw = bytes.fromhex(row["response_frame"])
            packet = decode(row["response_frame"])
            residue = binascii.crc_hqx(raw[:36], 0) ^ int.from_bytes(raw[36:], "big")
            for phase in range(64):
                changed = bytearray(raw)
                changed[13] = (changed[13] & 224) | (phase >> 1)
                changed[14] = (changed[14] & 127) | ((phase & 1) << 7)
                changed[36:] = (binascii.crc_hqx(changed[:36], 0) ^ residue).to_bytes(2, "big")
                frames.append(changed.hex())
                expected.append((1, phase, packet.data[0], packet.data[1] >> 4, packet.data[1] & 15))
        self.assertEqual(self.result_views(frames), expected)

    def test_result_envelope_does_not_turn_negative_into_success_or_parse_reports(self):
        data = fixture("htv145_active_counter_recovery_20260906.json")
        negative = data["idle_close_transactions"][0]["response_frame"]
        native = decode(negative)
        parsed = self.result_views([negative])[0]
        self.assertEqual(parsed[2], native.data[0])
        self.assertNotEqual(parsed[2], 0)
        self.assertEqual(parsed[2], 6)  # Historical normalized result "3" is native 6.
        invalid = [data["command_transactions"][0]["command_frame"],
                   data["command_transactions"][0]["independent_state_frame"]]
        damaged = bytearray.fromhex(data["command_transactions"][0]["response_frame"])
        damaged[20] ^= 1
        invalid.append(damaged.hex())
        self.assertEqual(self.result_views(invalid), [(0, 0, 0, 0, 0)] * 3)

    def test_gateway_and_radio_reject_reserved_phase_bit_even_with_valid_trailer(self):
        data = fixture('htv145_active_counter_recovery_20260906.json')
        raw = bytearray.fromhex(data['command_transactions'][0]['response_frame'])
        raw[13] |= 0x20  # Native phase bit 6, not one of the six counter bits.
        raw[-2:] = (binascii.crc_hqx(raw[:-2],0) ^ 0xc713).to_bytes(2,'big')
        self.assertIsNone(decode_envelope(bytes(raw)))
        self.assertEqual(self.result_views([raw.hex()]), [(0,0,0,0,0)])

    def test_stock_four_zone_port_four_ack_matches_retained_request_not_mode_nibble(self):
        row = fixture('htv405_stock_early_stop_20260824.json')['authenticated_counter_examples'][0]
        request = decode_envelope(row['open_command']['frame'])
        response = decode_envelope(row['open_response']['frame'])
        self.assertTrue(matches_positive_result(request,response,model='HTV405FRF',port=4))
        self.assertFalse(matches_positive_result(request,response,model='HTV405FRF',port=1))

    def test_runtime_import_requires_the_explicit_experiment_flag(self):
        source = (ROOT / "firmware/rainpoint_bridge/src/main.cpp").read_text()
        self.assertIn('#ifdef RAINPOINT_VALVE_PHASE_EXPERIMENT\n#include <Preferences.h>\n#include "rainpoint_phase_canary.h"', source)
        self.assertIn('#ifdef RAINPOINT_VALVE_PHASE_EXPERIMENT\n#include "valve_phase_runtime.inc"', source)


if __name__ == "__main__":
    unittest.main()
