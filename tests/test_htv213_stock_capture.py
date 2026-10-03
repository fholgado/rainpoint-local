"""Captured two-port stock behavior, not a local HTV213 transmit profile."""
import json
from pathlib import Path
import unittest

from research.pairing_native_transcripts import (
    TraceEvent, analyze_events, decode, valve_settings_fields,
)


class Htv213StockCaptureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "research" / "fixtures" / "htv213_stock_pairing_controls_20260928.json"
        cls.fixture = json.loads(path.read_text())
        cls.trials = {
            trial["name"]: tuple(TraceEvent(row["time_s"], row["direction"], decode(row["frame"]))
                                 for row in trial["events"])
            for trial in cls.fixture["trials"]
        }

    def packets(self, trial, command):
        return [event.packet for event in self.trials[trial]
                if event.packet.command == command]

    def test_every_selected_pair_matches_full_phase_and_reverse_direction(self):
        self.assertEqual(sum(map(len, self.trials.values())), 44)
        for name, events in self.trials.items():
            with self.subTest(trial=name):
                report = analyze_events(events)
                self.assertEqual(report.count("matching response candidate;"), len(events) // 2)
                self.assertIn("None within the selected candidate rules", report)
        self.assertEqual([packet.phase for packet in self.packets("zone2_auto120", 2)], [30, 32, 34])
        self.assertEqual([packet.phase for packet in self.packets("zone1_early_close", 2)], [52, 53, 54])

    def test_enrollment_repeats_state_settings_and_plan_for_exactly_two_ports(self):
        name = "enrollment"
        self.assertEqual([p.data[2] for p in self.packets(name, 2)], [1, 2])
        self.assertEqual([p.data for p in self.packets(name, 5)], [b"\x0b\x01", b"\x0b\x02"])
        self.assertEqual([p.data for p in self.packets(name, 6)], [b"\x0b\x01\0", b"\x0b\x02\0"])
        for packet in self.packets(name, 0x85):
            self.assertEqual(packet.data[0], 0)
            fields = valve_settings_fields(packet.data[1:])
            self.assertEqual((fields["work_time_raw"], fields["mist_open_raw"], fields["interval_raw"]), (600, 10, 30))
        notification = self.packets(name, 0x20)[0]
        self.assertEqual((notification.phase, notification.data), (2, b"\x02\0"))
        self.assertEqual(self.packets(name, 0xa0)[0].phase, 2)

    def test_both_ports_use_little_endian_seconds_and_valve_confirmed_automatic_stop(self):
        for name, port, seconds in (("zone1_auto60", 1, 60), ("zone2_auto120", 2, 120)):
            with self.subTest(trial=name):
                request = self.packets(name, 0x21)[0]
                self.assertEqual(request.data[:3], bytes((port, 2, 1)))
                self.assertEqual(int.from_bytes(request.data[3:5], "little"), seconds)
                reply = self.packets(name, 0xa1)[0]
                self.assertEqual(reply.data[:2], b"\0\x21")
                self.assertEqual(int.from_bytes(reply.data[8:10], "little"), seconds + 1)
                self.assertEqual(int.from_bytes(reply.data[11:13], "little"), seconds)
                statuses = [p for p in self.packets(name, 2) if p.data[2] == port]
                self.assertEqual(statuses[0].data[3], 0x21)
                self.assertEqual(int.from_bytes(statuses[0].data[10:12], "little"), seconds - 5)
                self.assertEqual(statuses[-1].data[3], 0)
                self.assertEqual(statuses[-1].data[10:12], b"\0\0")
                self.assertEqual(int.from_bytes(self.packets(name, 4)[0].data[-2:], "little"), seconds)

    def test_early_close_reply_is_not_identical_to_later_idle_report(self):
        name = "zone1_early_close"
        self.assertEqual([p.data for p in self.packets(name, 0x21)], [bytes.fromhex("0102017800"), bytes.fromhex("010200")])
        self.assertEqual([p.phase for p in self.packets(name, 0x21)], [5, 6])
        close_reply = self.packets(name, 0xa1)[-1]
        self.assertEqual(close_reply.phase, 6)
        self.assertEqual(close_reply.data[:2], bytes.fromhex("0020"))
        self.assertEqual(close_reply.data[8:10], b"\0\0")
        self.assertEqual(int.from_bytes(close_reply.data[11:13], "little"), 120)
        self.assertEqual(self.packets(name, 2)[-1].data[3], 0)
        self.assertEqual(int.from_bytes(self.packets(name, 4)[0].data[-2:], "little"), 34)

    def test_hub_commands_do_not_consume_device_report_sequence(self):
        control_phases = [p.phase for name in ("zone1_auto60", "zone2_auto120", "zone1_early_close")
                          for p in self.packets(name, 0x21)]
        self.assertEqual(control_phases, [3, 4, 5, 6])
        self.assertEqual(self.packets("zone1_early_close", 0x82)[-1].phase, 54)

    def test_fixture_uses_only_synthetic_routes_and_zeros_device_clock_fields(self):
        allowed = {bytes.fromhex("11556677"), bytes.fromhex("22446688")}
        for events in self.trials.values():
            for event in events:
                packet = event.packet
                for route in packet.route:
                    self.assertIn(bytes((route[0] & 127,)) + route[1:], allowed)
                if packet.command == 4:
                    self.assertEqual(packet.data[3:7], bytes(4))
                    self.assertEqual(packet.data[7], 0x21)
                if packet.command == 0x82 and len(packet.data) > 2:
                    self.assertEqual(packet.data[2:6], bytes(4))
                    self.assertEqual(packet.data[6], 1)


if __name__ == "__main__":
    unittest.main()
