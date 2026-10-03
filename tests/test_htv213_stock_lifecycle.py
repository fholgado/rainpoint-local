"""Stock lifecycle evidence; not a local pairing or counter-reset recipe."""
from dataclasses import replace
import json
from pathlib import Path
import unittest

from research.pairing_native_transcripts import (
    TraceEvent, analyze_events, decode, valve_settings_fields,
)


class Htv213StockLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = (Path(__file__).resolve().parents[1] / "research" / "fixtures"
                / "htv213_stock_lifecycle_20260928.json")
        cls.fixture = json.loads(path.read_text())
        cls.trials = {
            trial["name"]: tuple(
                TraceEvent(row["time_s"], row["direction"], decode(row["frame"]))
                for row in trial["events"])
            for trial in cls.fixture["trials"]
        }

    def packets(self, trial, command):
        return [event.packet for event in self.trials[trial]
                if event.packet.command == command]

    def test_addressed_responses_match_reverse_routes_and_full_phase(self):
        self.assertEqual(sum(map(len, self.trials.values())), 64)
        for name, events in self.trials.items():
            with self.subTest(trial=name):
                # Factory announcements/assignments do not have reversed routes.
                addressed = tuple(e for e in events
                                  if e.packet.command not in (1, 0x81))
                report = analyze_events(addressed)
                self.assertEqual(report.count("matching response candidate;"),
                                 len(addressed) // 2)
                self.assertIn("None within the selected candidate rules", report)

    def test_high_phase_bit_is_required_for_response_matching(self):
        pair = tuple(e for e in self.trials["quiet3h"]
                     if e.packet.phase == 63 and e.packet.command in (2, 0x82))
        self.assertEqual(len(pair), 2)
        incorrect = replace(pair[1], packet=replace(pair[1].packet, phase=31))
        self.assertIn("matching response candidate;", analyze_events(pair))
        report = analyze_events((pair[0], incorrect))
        self.assertNotIn("matching response candidate;", report)
        self.assertIn("unmatched response", report)

    def test_retained_assignment_echoes_observed_announcement_phases(self):
        requests = self.packets("battery_rejoin", 1)
        replies = self.packets("battery_rejoin", 0x81)
        self.assertEqual([p.phase for p in requests], [1, 2, 3, 4])
        self.assertEqual([p.phase for p in replies], [1, 4])
        for packet in requests:
            self.assertEqual(packet.data, bytes.fromhex("0bff200501043e03"))
            self.assertEqual(packet.route[0], bytes.fromhex("80000000"))
        for packet in replies:
            self.assertEqual(packet.data[:3], bytes.fromhex("00020b"))
            self.assertEqual(packet.data[-2:], bytes.fromhex("0102"))
            self.assertIn(packet.phase, [p.phase for p in requests])

    def test_rejoin_continues_state_settings_and_plans_for_each_port(self):
        name = "battery_rejoin"
        reports = [p for p in self.packets(name, 2) if p.phase in (5, 6)]
        self.assertEqual([(p.phase, p.data[:3]) for p in reports],
                         [(5, bytes.fromhex("0b0b01")),
                          (6, bytes.fromhex("0b0b02"))])
        self.assertEqual([p.data for p in self.packets(name, 5)],
                         [bytes.fromhex("0b01"), bytes.fromhex("0b02")])
        self.assertEqual([p.data for p in self.packets(name, 6)],
                         [bytes.fromhex("0b0100"), bytes.fromhex("0b0200")])
        self.assertEqual([p.phase for p in self.packets(name, 0x85)], [7, 8])
        for packet in self.packets(name, 0x85):
            self.assertEqual(packet.data[0], 0)
            settings = valve_settings_fields(packet.data[1:])
            self.assertEqual((settings["work_time_raw"], settings["mist_open_raw"],
                              settings["interval_raw"]), (600, 10, 30))
        self.assertEqual([(p.phase, p.data) for p in self.packets(name, 0x86)],
                         [(9, b"\0"), (10, b"\0")])
        for trial in self.trials:
            for packet in self.packets(trial, 0x82):
                self.assertEqual(packet.data[:2], b"\0\x02")

    def test_all_selected_runs_have_response_open_idle_and_duration_summary(self):
        for name, phase, port in (("quiet30", 7, 1), ("quiet3h", 8, 2),
                                  ("hub_restart", 3, 1), ("battery_rejoin", 4, 2)):
            with self.subTest(trial=name):
                request = self.packets(name, 0x21)[0]
                self.assertEqual((request.phase, request.data),
                                 (phase, bytes((port, 2, 1, 60, 0))))
                reply = self.packets(name, 0xa1)[0]
                self.assertEqual((reply.phase, reply.data[:2]), (phase, b"\0\x21"))
                self.assertEqual(int.from_bytes(reply.data[8:10], "little"), 61)
                self.assertEqual(int.from_bytes(reply.data[11:13], "little"), 60)
                opened = next(e for e in self.trials[name]
                              if e.packet.command == 2 and e.packet.data[2:4]
                              == bytes((port, 0x21)))
                self.assertEqual(int.from_bytes(opened.packet.data[10:12], "little"), 55)
                idle = next(e for e in self.trials[name]
                            if e.time_s > opened.time_s and e.packet.command == 2
                            and e.packet.data[2:4] == bytes((port, 0)))
                self.assertEqual(idle.packet.data[10:12], b"\0\0")
                summary = self.packets(name, 4)[0]
                self.assertEqual(summary.data[1], port)
                self.assertEqual(int.from_bytes(summary.data[-2:], "little"), 60)

    def test_restart_notification_precedes_lower_control_without_proving_cause(self):
        events = self.trials["hub_restart"]
        notify = next(e for e in events if e.packet.command == 0x20)
        control = next(e for e in events if e.packet.command == 0x21)
        self.assertEqual((notify.packet.phase, notify.packet.data), (2, b"\x02\x01"))
        self.assertEqual([(p.phase, p.data) for p in self.packets("hub_restart", 0xa0)],
                         [(2, b"\0")])
        self.assertLess(notify.time_s, control.time_s)
        self.assertEqual(control.packet.phase, 3)
        self.assertEqual(self.packets("quiet3h", 0x21)[0].phase, 8)
        # This proves observed ordering only, not that notification resets a valve.
        self.assertIn("causal reset is unproven", self.fixture["limits"])

    def test_battery_rejoin_and_wrap_do_not_define_the_master_sequence(self):
        self.assertEqual([self.packets(n, 0x21)[0].phase for n in self.trials],
                         [7, 8, 3, 4])
        self.assertEqual([p.phase for p in self.packets("quiet3h", 2)][-2:], [63, 1])
        self.assertEqual([p.phase for p in self.packets("battery_rejoin", 2)],
                         [36, 37, 5, 6, 11, 13])
        self.assertEqual(self.packets("battery_rejoin", 0x21)[0].phase, 4)
        self.assertEqual(self.packets("battery_rejoin", 0x20), [])
        self.assertEqual(self.packets("battery_rejoin", 0xa0), [])

    def test_all_routes_are_synthetic_and_clock_fields_are_zeroed(self):
        allowed = {bytes.fromhex("11556677"), bytes.fromhex("22446688"), bytes(4)}
        for events in self.trials.values():
            for event in events:
                packet = event.packet
                for route in packet.route:
                    self.assertIn(bytes((route[0] & 127,)) + route[1:], allowed)
                if packet.command == 4:
                    self.assertEqual(packet.data[3:7], bytes(4))
                elif packet.command == 0x82 and len(packet.data) > 2:
                    self.assertEqual(packet.data[2:6], bytes(4))
                    self.assertEqual(packet.data[6], 1)
                elif packet.command == 0x81:
                    self.assertEqual(packet.data[5:9], bytes(4))


if __name__ == "__main__":
    unittest.main()
