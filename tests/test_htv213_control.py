"""Offline HTV213 control candidate; no device/network or watering calls."""
import json
import binascii
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from research.pairing_native_transcripts import decode
from tests.test_valve_configuration import alter
from tests.test_htv213_pairing import REPEAT_FACTORY

ROOT = Path(__file__).resolve().parents[1]


class Htv213ControlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("c++")
        if not compiler:
            raise unittest.SkipTest("native compiler unavailable")
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.exe = str(Path(cls.temp.name) / "control")
        subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                        "-I" + str(ROOT / "firmware/rainpoint_bridge/include"),
                        str(ROOT / "firmware/rainpoint_bridge/tests/htv213_control_probe.cpp"),
                        "-o", cls.exe], check=True, capture_output=True, text=True)
        fixture = json.loads((ROOT / "research/fixtures/htv213_stock_pairing_controls_20260928.json").read_text())
        cls.trials = {t["name"]: t["events"] for t in fixture["trials"]}

    def run_ops(self, ops):
        result = subprocess.run([self.exe], input="\n".join(ops) + "\n", text=True,
                                capture_output=True, check=True)
        return [list(map(int, row.split()[:15])) + [row.split()[15]]
                for row in result.stdout.splitlines()]

    def packet(self, command, trial="zone1_auto60", last=False):
        frames = [e["frame"] for e in self.trials[trial] if decode(e["frame"]).command == command]
        return frames[-1 if last else 0]

    def test_control_and_report_ack_bodies_match_all_stock_trials(self):
        for name, events in self.trials.items():
            if name == "enrollment":
                continue
            previous = None
            for event in events:
                packet = decode(event["frame"])
                if event["direction"] == "gateway":
                    if packet.command == 0x21:
                        seconds = int.from_bytes(packet.data[3:5], "little") if packet.data[2] else 0
                        operation = f"build 0 {packet.data[0]} {seconds} {packet.phase}"
                    else:
                        operation = f"ack 0 {previous}"
                    row = self.run_ops([operation])[0]
                    self.assertEqual(row[0], 1, (name, operation))
                    actual = decode(row[-1])
                    self.assertEqual((actual.command, actual.phase, actual.data),
                                     (packet.command, packet.phase, packet.data))
                    if packet.command == 0x21:
                        # Controls contain no wall clock. Match the whole
                        # redacted envelope/flags/trailer, not just its body.
                        self.assertEqual(row[-1], event["frame"])
                    self.assertEqual(row[13:15], [434241500, 2400 if packet.command == 0x21 else 320])
                previous = event["frame"]

    def test_captured_runs_require_result_idle_and_summary(self):
        for name, events in self.trials.items():
            if name == "enrollment":
                continue
            ops = []
            for event in events:
                packet = decode(event["frame"])
                now = round(event["time_s"] * 1000)
                if packet.command == 0x21:
                    if packet.data[2]:
                        ops.append(f"start {now} {packet.data[0]} {int.from_bytes(packet.data[3:], 'little')} {packet.phase}")
                    else:
                        ops.append(f"close {now} {packet.phase}")
                    ops.append(f"finish {now+1} 1")
                elif event["direction"] == "device":
                    ops.append(f"observe {now} {event['frame']}")
            rows = self.run_ops(ops)
            self.assertEqual(rows[-1][1], 6, name)  # Complete, not merely TX success.
            self.assertEqual(rows[-1][3], 1)
            self.assertEqual(rows[-1][4], name == "zone1_early_close")
            self.assertEqual(rows[-1][6:8], [1, 1])
            self.assertEqual(rows[-1][8], {"zone1_auto60": 60, "zone2_auto120": 120,
                                         "zone1_early_close": 34}[name])
            self.assertNotEqual(rows[-2][1], 6)

    def test_all_dry_trial_seconds_ports_and_full_phases(self):
        ops = [f"build 0 {port} {seconds} {phase}" for port in (1, 2)
               for seconds in (1, 60, 119, 120, 255, 256, 257, 3600) for phase in range(64)]
        ops += [f"build 0 {port} {seconds} 7" for port in (1, 2) for seconds in range(1,3601)]
        for operation, row in zip(ops, self.run_ops(ops), strict=True):
            _, _, port, seconds, phase = operation.split()
            packet = decode(row[-1])
            self.assertEqual((packet.phase, packet.data),
                             (int(phase), bytes((int(port), 2, 1)) + int(seconds).to_bytes(2,'little')))
        for op in ("start 0 0 60 3", "start 0 3 60 3", "start 0 1 0 3",
                   "start 0 1 3601 3", "start 0 1 60 64"):
            self.assertEqual(self.run_ops([op])[0][0], 0)

    def test_local_corrected_crc_cycle_confirms_and_completes_without_close(self):
        events = json.loads((ROOT / "research/fixtures/htv213_local_control_crc_corrected_20260930.json").read_text())["events"]
        ops = ["start 0 1 60 3", "finish 1 1"]
        self.assertEqual(self.run_ops(ops)[0][-1], events[0]["frame"])
        for event in events[1:]:
            decode(event["frame"])  # Also validate redacted gateway ACK integrity.
            if event["direction"] == "device":
                ops.append(f"observe {round(event['time_s']*1000)} {event['frame']}")
        rows = self.run_ops(ops)
        self.assertEqual(rows[2][1], 3)  # Matching a1 confirms open.
        self.assertEqual(rows[-1][1], 6)
        self.assertEqual(rows[-1][3:9], [1, 0, 1, 1, 1, 60])

    def test_retained_owner_acknowledges_reports_settings_plans_not_commands(self):
        events = json.loads((ROOT / "research/fixtures/htv213_local_control_crc_corrected_20260930.json").read_text())["events"]
        for event in events:
            row=self.run_ops([f"owner_ack 0 {event['frame']}"])[0]
            command=decode(event['frame']).command
            self.assertEqual(row[0],int(event['direction']=='device' and command in (2,4)))
            if row[0]:
                reply=decode(row[-1])
                self.assertEqual((reply.command,reply.phase),(command|128,decode(event['frame']).phase))
        report = next(e['frame'] for e in events if e['direction']=='device' and decode(e['frame']).command==2)
        for command in (5, 6):
            for port in (1, 2):
                frame=alter(report, command=command, data=bytes((11,port)) + (b'\0' if command==6 else b''))
                row=self.run_ops([f"owner_ack 0 {frame}"])[0]
                self.assertEqual(row[0],1)
                self.assertEqual(decode(row[-1]).command,command|128)

    def test_ha_300_second_capture_and_wrapped_report_phases(self):
        events = json.loads((ROOT / 'research/fixtures/htv213_local_ha_auto300_20260930.json').read_text())['events']
        ops = ['start 0 2 300 7', 'finish 1 1']
        self.assertEqual(self.run_ops(ops)[0][-1], events[0]['frame'])
        report_phases = set()
        for event in events[1:]:
            packet = decode(event['frame'])
            if event['direction'] == 'device':
                ops.append(f"observe {round(event['time_s']*1000)} {event['frame']}")
                if packet.command in (2, 4):
                    report_phases.add(packet.phase)
                    reply = decode(self.run_ops([f"owner_ack 0 {event['frame']}"])[0][-1])
                    self.assertEqual((reply.command, reply.phase), (packet.command | 128, packet.phase))
        rows = self.run_ops(ops)
        self.assertEqual(rows[-1][1], 6)
        self.assertEqual(rows[-1][8], 300)
        self.assertTrue({63, 1}.issubset(report_phases))

    def test_retained_assignment_is_opt_in_and_uses_request_carrier(self):
        fixture = json.loads((ROOT / 'research/fixtures/htv213_stock_lifecycle_20260928.json').read_text())
        events = next(t['events'] for t in fixture['trials'] if t['name'] == 'battery_rejoin')
        requests = [e['frame'] for e in events if decode(e['frame']).command == 1]
        for frame in requests:
            self.assertEqual(self.run_ops([f'owner_ack 0 {frame}'])[0][0], 0)
            for selector, hz in ((11, 434241500), (12, 434351500)):
                data = bytearray(decode(frame).data); data[0] = selector
                request = alter(frame, data=data)
                row = self.run_ops([f'owner_rejoin 0 {request}'])[0]
                self.assertEqual(row[0], 1)
                self.assertEqual(row[13], hz)
                reply = decode(row[-1])
                self.assertEqual((reply.command, reply.phase), (0x81, decode(frame).phase))
                self.assertEqual(reply.data[:5], bytes.fromhex('00020be001'))
                self.assertEqual(reply.data[-1], 2)
        frame = requests[0]
        for selector in (0, 1, 10, 13, 15, 16):
            data = bytearray(decode(frame).data); data[0] = selector
            self.assertEqual(self.run_ops([f'owner_rejoin 0 {alter(frame, data=data)}'])[0][0], 0)
        for suffix in (0, 1, 2, 4, 5, 6, 8, 255):
            data = bytearray(decode(frame).data); data[-1] = suffix
            self.assertEqual(self.run_ops([f'owner_rejoin 0 {alter(frame, data=data)}'])[0][0], 0)
        wrong = bytearray.fromhex(frame); wrong[12] ^= 1
        self.assertEqual(self.run_ops([f'owner_rejoin 0 {alter(wrong.hex())}'])[0][0], 0)

    def test_battery_only_07_announcement_reuses_owner_without_master_phase_change(self):
        # Oct 3 battery-only startup has the same body as this redacted local
        # repeat-pairing fixture. The bytes do not identify a button press.
        self.assertEqual(decode(REPEAT_FACTORY).data, bytes.fromhex('0bff200501043e07'))
        for phase in range(64):
            with self.subTest(phase=phase):
                request = alter(REPEAT_FACTORY, phase=phase)
                self.assertEqual(self.run_ops([f'owner_ack 0 {request}'])[0][0], 0)
                row = self.run_ops([f'owner_rejoin 0 {request}'])[0]
                self.assertEqual(row[0], 1)
                reply = decode(row[-1])
                self.assertEqual((reply.command, reply.phase), (0x81, phase))
                self.assertEqual(reply.data, bytes.fromhex('00020be001000000000102'))
                self.assertEqual(row[13], 434241500)
                self.assertEqual(row[1:3], [0, 0])  # No master command allocation.
        wrong = bytearray.fromhex(REPEAT_FACTORY); wrong[12] ^= 1
        self.assertEqual(self.run_ops([f'owner_rejoin 0 {alter(wrong.hex())}'])[0][0], 0)
        for index in range(1, 7):
            data = bytearray(decode(REPEAT_FACTORY).data); data[index] ^= 1
            self.assertEqual(self.run_ops([f'owner_rejoin 0 {alter(REPEAT_FACTORY, data=data)}'])[0][0], 0)

    def test_retained_rejoin_configuration_replays_both_ports_without_master_commands(self):
        fixture = json.loads((ROOT / 'research/fixtures/htv213_stock_lifecycle_20260928.json').read_text())
        events = next(t['events'] for t in fixture['trials'] if t['name'] == 'battery_rejoin')
        commands = []
        for event in events:
            request = decode(event['frame'])
            if event['direction'] != 'device' or request.command not in (1, 2, 5, 6):
                continue
            row = self.run_ops([f"owner_rejoin 0 {event['frame']}"])[0]
            self.assertEqual(row[0], 1)
            reply = decode(row[-1]); commands.append(reply.command)
            self.assertEqual((reply.command, reply.phase), (request.command | 128, request.phase))
            self.assertEqual(reply.data[0], 0)
            self.assertEqual(row[1:3], [0, 0])  # No master trial or phase allocation.
            if request.command == 5:
                self.assertEqual(reply.data[1:], bytes.fromhex('58020a001e000000000000000000'))
            elif request.command == 6:
                self.assertEqual(reply.data, b'\0')
        self.assertTrue({0x81, 0x82, 0x85, 0x86}.issubset(commands))
        announcement = next(e['frame'] for e in events if decode(e['frame']).command == 1)
        self.assertEqual(self.run_ops([f'owner_ack 0 {announcement}'])[0][0], 0)

    def test_owner_configuration_is_per_port_and_never_guesses_unknown_values(self):
        report = self.packet(2)
        data = bytearray(decode(report).data)
        data[1] = 2  # Explicit configuration-version request.
        report = alter(report, data=data)
        settings = '0102030405060708090a0b0c0d0e'
        setup = f'config 0 7 2 {settings} 1 1'
        self.assertEqual(decode(self.run_ops([setup, f'owner_ack 0 {report}'])[-1][-1]).data, b'\0\7')
        for port in (1, 2):
            request = alter(report, command=5, data=bytes((11, port)))
            response = decode(self.run_ops([setup, f'owner_ack 0 {request}'])[-1][-1])
            expected = settings if port == 2 else '58020a001e000000000000000000'
            self.assertEqual(response.data, b'\0' + bytes.fromhex(expected))
        for command, known, empty in ((5, 0, 1), (6, 1, 0)):
            request = alter(report, command=command, data=bytes((11, 2)) + (b'\0' if command == 6 else b''))
            rows = self.run_ops([f'config 0 7 2 {settings} {known} {empty}', f'owner_ack 0 {request}'])
            self.assertEqual(rows[-1][0], 0)

    def test_local_second_outlet_and_explicit_stop_captures(self):
        fixture=json.loads((ROOT / 'research/fixtures/htv213_local_outlet_stop_20260930.json').read_text())
        for trial in fixture['trials']:
            ops=[]
            for event in trial['events']:
                packet=decode(event['frame'])
                ms=round(event['time_s']*1000)
                if event['direction']=='gateway' and packet.command==0x21:
                    if packet.data[2]:
                        seconds=int.from_bytes(packet.data[3:5],'little')
                        ops.append(f'start {ms} {packet.data[0]} {seconds} {packet.phase}')
                    else: ops.append(f'close {ms} {packet.phase}')
                    ops.append(f'finish {ms+1} 1')
                elif event['direction']=='device': ops.append(f"observe {ms} {event['frame']}")
            self.assertEqual(self.run_ops(ops)[-1][1],6,trial['name'])

    def test_rf_verified_master_boundary_includes_zero_not_report_reseed(self):
        fixture = json.loads((ROOT / 'research/fixtures/htv213_local_counter_boundary_20260930.json').read_text())
        self.assertEqual([t['phase'] for t in fixture['trials']], [62,63,0,1])
        for trial in fixture['trials']:
            phase = trial['phase']
            ops = [f'start 0 1 60 {phase}', 'finish 1 1']
            self.assertEqual(self.run_ops(ops)[0][-1], trial['events'][0]['frame'])
            for event in trial['events'][1:]:
                packet = decode(event['frame'])
                if event['direction'] == 'device':
                    ops.append(f"observe {round(event['time_s']*1000)} {event['frame']}")
                if packet.command == 0xa1:
                    self.assertEqual(packet.phase, phase)
            result = self.run_ops(ops)[-1]
            self.assertEqual(result[1], 6)
            self.assertEqual(result[3:9], [1,0,1,1,1,60])

    def test_native_crc_final_bit_matches_independent_crc_for_both_values(self):
        frames = [row[-1] for row in self.run_ops([f"build 0 1 60 {phase}" for phase in range(64)])]
        actual = [row[0] for row in self.run_ops([f"tail 0 {frame}" for frame in frames])]
        expected = []
        for frame in frames:
            raw = bytes.fromhex(frame)
            native = bytes(((raw[i+4]<<1)|(raw[i+5]>>7))&255 for i in range(32))
            expected.append(binascii.crc_hqx(native, 0xa8a8)&1)
        self.assertEqual(set(expected), {0,1})
        self.assertEqual(actual, expected)

    def test_no_optimistic_open_no_retries_and_no_timeout_close(self):
        rows = self.run_ops(["start 0 1 60 3", "finish 10 1", "listen 1509",
                             "tick 1510", "close 1600 4", "start 1600 1 60 4",
                             "tick 120000"])
        self.assertEqual(rows[1][1:4], [2, 3, 0])  # Awaiting, not confirmed.
        self.assertEqual(rows[2][0], 1)
        self.assertEqual(rows[3][1], 7)  # Uncertain, not "watering did not happen".
        self.assertEqual(rows[4][0], 0)
        self.assertEqual(rows[5][0], 0)
        self.assertEqual(rows[-1][1], 8)  # Overdue evidence deadline.
        self.assertTrue(all(row[-1] == "-" for row in rows[1:]))
        local = json.loads((ROOT / "research/fixtures/htv213_local_control_20260930.json").read_text())["events"]
        rows = self.run_ops(["start 0 1 60 3", "finish 1 1", "tick 1501",
                             f"observe 137803 {local[1]['frame']}"])
        self.assertEqual(rows[0][-1], local[0]["frame"])
        self.assertEqual(rows[-1][1], 8)  # Late other-port idle cannot turn failure into success.
        self.assertEqual(rows[-1][3:8], [0, 0, 0, 0, 0])

    def test_wrong_phase_routes_result_shape_and_other_port_do_not_confirm(self):
        ack = self.packet(0xa1)
        data = bytearray(decode(ack).data)
        rejected = [alter(ack, phase=4), alter(ack, data=data[:-1])]
        data[0] = 1
        rejected.append(alter(ack, data=data))
        other = bytearray.fromhex(ack); other[8] ^= 1
        rejected.append(alter(other.hex()))
        for frame in rejected:
            rows = self.run_ops(["start 0 1 60 3", "finish 1 1", f"observe 10 {frame}"])
            self.assertEqual(rows[-1][0], 0)
            self.assertEqual(rows[-1][3], 0)
        idle1 = self.packet(2, "zone2_auto120")
        for event in self.trials["zone2_auto120"]:
            packet = decode(event["frame"])
            if packet.command == 2 and packet.data[2] == 1:
                idle1 = event["frame"]
        rows = self.run_ops(["start 0 2 120 4", "finish 1 1",
                             f"observe 10 {self.packet(0xa1, 'zone2_auto120')}",
                             f"observe 20 {idle1}"])
        self.assertEqual(rows[-1][0], 0)
        self.assertEqual(rows[-1][6], 0)

    def test_summary_alone_and_stale_idle_cannot_complete(self):
        rows = self.run_ops(["start 0 1 60 3", "finish 1 1",
                             f"observe 2 {self.packet(2, last=True)}",
                             f"observe 3 {self.packet(4)}",
                             f"observe 4 {self.packet(0xa1)}",
                             f"observe 5 {self.packet(4)}"])
        self.assertEqual(rows[-1][6:8], [0, 0])
        self.assertNotEqual(rows[-1][1], 6)

    def test_close_is_explicit_and_keeps_original_requested_duration(self):
        rows = self.run_ops(["start 0 1 120 5", "finish 1 1",
                             f"observe 10 {self.packet(0xa1, 'zone1_early_close')}",
                             "close 35000 6", "finish 35001 1",
                             f"observe 35300 {self.packet(0xa1, 'zone1_early_close', last=True)}",
                             "close 36000 7"])
        self.assertEqual(decode(rows[3][-1]).data, bytes.fromhex("010200"))
        self.assertEqual(rows[5][4], 1)
        self.assertEqual(rows[-1][0], 0)

    def test_failed_transmit_and_cancel_cannot_resend(self):
        for operation in ("finish 1 0", "cancel 1"):
            rows = self.run_ops(["start 0 1 60 3", operation,
                                 "start 2 1 60 3", "close 2 4"])
            self.assertEqual(rows[-1][0], 0)
            self.assertEqual(rows[-2][0], 0)
