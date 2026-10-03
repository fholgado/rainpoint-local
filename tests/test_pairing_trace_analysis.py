"""Offline analyzer semantics/correlation; never device acceptance tests."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from research.pairing_native_transcripts import (
    PacketShape, TraceEvent, analyze_events, decode, exchanges, read_events, semantics,
    valve_settings_fields,
)
from tests.test_stock_valve_frame_reference import load_fixture


def events_from_failure(name):
    fixture = load_fixture(name)
    events = [TraceEvent(row["end_seconds"], "device", decode(row["frame"]))
              for row in fixture["requests"]]
    events += [TraceEvent(row["start_seconds"], "gateway", decode(row["frame"]))
               for row in fixture["replies"]]
    row = fixture["configuration_response"]
    events.append(TraceEvent(row.get("end_seconds", row["start_seconds"]), "device", decode(row["frame"])))
    return tuple(events)


class PairingTraceAnalysisTest(unittest.TestCase):
    def setUp(self):
        self.rows = [row for row in exchanges() if row.profile == "HTV145 counter-2"]

    def test_semantics_distinguish_ports_pages_parameters_and_version(self):
        self.assertIn("port=1", semantics(self.rows[4].device))
        self.assertIn("page=0", semantics(self.rows[5].device))
        self.assertIn("IDs=32", semantics(self.rows[6].device))
        self.assertIn("version=2; kind=0", semantics(self.rows[2].gateway))
        self.assertNotIn("selector", semantics(self.rows[2].gateway))
        self.assertIn("configuration version=1", semantics(self.rows[1].gateway, self.rows[1].device))
        self.assertIn("all parameters", semantics(PacketShape(0x59, 1, b"\0")))

    def test_same_bytes_have_different_meanings_by_request_family(self):
        reply = PacketShape(0x85, 5, bytes.fromhex("0001"))
        self.assertEqual("result=0; stored settings bytes=1", semantics(reply))
        self.assertNotIn("version", semantics(replace(reply, command=0x82)))
        no_version = replace(self.rows[1].device, data=bytes.fromhex("0c0901"))
        self.assertNotIn("version", semantics(self.rows[1].gateway, no_version))
        self.assertIn("more plan data (not generic failure)", semantics(PacketShape(0x86, 1, b"\1")))
        self.assertIn("not pairing completion", semantics(self.rows[5].gateway))

    def test_captured_valve_settings_are_raw_fields_not_duration_or_battery(self):
        settings = [row.gateway for row in exchanges()
                    if row.profile.startswith("HTV") and row.gateway and row.gateway.command == 0x85]
        self.assertEqual(len(settings), 6)
        for reply in settings:
            with self.subTest(profile=reply.data.hex()):
                fields = valve_settings_fields(reply.data[1:])
                self.assertEqual(list(fields.values()), [600, 10, 30, 0, 0, 0, 0, 0, 0])
                label = semantics(reply)
                self.assertIn("candidate class-1F layout (units unqualified)", label)
                self.assertNotIn("seconds", label)
                self.assertNotIn("battery", label)
                self.assertNotIn("soil_address", label)

    def test_settings_widths_endianness_and_flag_are_independent(self):
        fields = valve_settings_fields(bytes.fromhex("34127856bc9a25d5efcdab891122"))
        self.assertEqual(list(fields.values()),
                         [0x1234, 0x5678, 0x9abc, 0x25, 0x55, 1, 0x89abcdef, 0x11, 0x22])
        self.assertEqual(valve_settings_fields(bytes([255] * 14))["delay_raw"], 0xffffffff)
        for size in (0, 13, 15):
            with self.assertRaises(ValueError):
                valve_settings_fields(bytes(size))

    def test_all_three_historical_failures_identify_four_unanswered_plan_retries(self):
        for name in (
            "htv145_receive_edge_terminal_retry_20260905.json",
            "htv145_low_gain_terminal_retry_20260905.json",
            "htv145_calibrated_tail_terminal_retry_20260905.json",
        ):
            with self.subTest(fixture=name):
                report = analyze_events(events_from_failure(name))
                self.assertEqual(report.count("matching response candidate;"), 4)
                self.assertEqual(report.count("repeated request (changed phase)"), 4)
                missing = report.split("## Requests with no matching response observed")[1]
                for phase in (8, 9, 10, 11):
                    self.assertIn(f"06 phase {phase}; plan read;", missing)
                self.assertEqual(missing.count("- "), 4)
                self.assertIn("Terminal 59 request observed: False", report)
                self.assertIn("not proof of RF loss", report)

    def test_delayed_notification_ack_is_device_response_not_request(self):
        request, reply = self.rows[2].gateway, self.rows[3].device
        report = analyze_events((TraceEvent(3, "gateway", request), TraceEvent(3.3, "device", reply)))
        self.assertIn("matching response candidate; delta=0.300000s", report)
        self.assertIn("None within the selected candidate rules", report)
        self.assertIn("does not establish completed pairing", report)

    def test_wrong_full_phase_command_direction_or_route_does_not_match(self):
        request, reply = self.rows[1].device, self.rows[1].gateway
        foreign = (bytes((reply.route[0][0], reply.route[0][1] ^ 1)) + reply.route[0][2:], reply.route[1])
        cases = (
            (replace(reply, phase=reply.phase ^ 1), "gateway"),
            (replace(reply, command=0x85), "gateway"),
            (replace(reply, route=foreign), "gateway"),
            (reply, "device"),
        )
        for candidate, direction in cases:
            with self.subTest(direction=direction, phase=candidate.phase, command=candidate.command):
                report = analyze_events((TraceEvent(1, "device", request), TraceEvent(1.1, direction, candidate)))
                self.assertNotIn("matching response candidate;", report)
                self.assertIn("unmatched response in capture/window", report)
                self.assertIn("02 phase 5;", report)

    def test_explicit_window_and_duplicate_ack_never_complete_twice(self):
        request, reply = self.rows[1].device, self.rows[1].gateway
        events = (TraceEvent(1, "device", request), TraceEvent(11.1, "gateway", reply))
        self.assertNotIn("matching response candidate;", analyze_events(events))
        self.assertIn("matching response candidate;", analyze_events(events, window_s=11))
        events = (TraceEvent(1, "device", request), TraceEvent(1.1, "gateway", reply),
                  TraceEvent(1.2, "gateway", reply))
        report = analyze_events(events)
        self.assertEqual(report.count("matching response candidate;"), 1)
        self.assertEqual(report.count("unmatched response in capture/window"), 1)

    def test_reused_phase_is_explicitly_ambiguous_and_uses_latest_timestamp(self):
        request, reply = self.rows[1].device, self.rows[1].gateway
        report = analyze_events((TraceEvent(1, "device", request), TraceEvent(1.5, "device", request),
                                 TraceEvent(1.6, "gateway", reply)))
        self.assertIn("repeated request (same phase)", report)
        self.assertIn("repeated phase is ambiguous", report)
        self.assertIn("delta=0.100000s", report)

    def test_events_are_sorted_and_report_does_not_publish_routes_or_raw_packets(self):
        events = events_from_failure("htv145_receive_edge_terminal_retry_20260905.json")
        report = analyze_events(events)
        self.assertEqual(report, analyze_events(tuple(reversed(events))))
        self.assertNotIn("79f4882f28", report)
        for event in events:
            for identity in event.packet.route:
                self.assertNotIn(identity.hex(), report)
                self.assertNotIn(identity.hex(), repr(event.packet))

    def test_labelled_file_schema_rejects_invalid_times_and_unexpected_fields(self):
        frame = load_fixture("htv145_counter2_stock_enrollment_20260901.json")["exchanges"][1]["request_frame"]
        record = {"time_s": 1, "direction": "device", "frame": frame}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.json"
            # Test fixtures, not application output files.
            path.write_text(json.dumps([record]))
            self.assertEqual(read_events(path)[0].packet.phase, 5)
            invalid = [
                [dict(record, time_s=True)], [dict(record, time_s=-1)],
                [dict(record, time_s=float("nan"))], [dict(record, direction="guess")],
                [dict(record, private_extra="not accepted")], [dict(record, frame="not hex")], {},
            ]
            for records in invalid:
                path.write_text(json.dumps(records))
                with self.assertRaises(ValueError):
                    read_events(path)

    def test_invalid_analysis_limits_and_missing_route_are_rejected(self):
        for window in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                analyze_events((), window_s=window)
        with self.assertRaises(ValueError):
            analyze_events((TraceEvent(1, "device", PacketShape(6, 7, b"\x0c\1\0")),))


if __name__ == "__main__":
    unittest.main()
