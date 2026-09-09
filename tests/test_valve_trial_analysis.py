"""Tests for passive enrollment and multi-zone differential analysis."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rainpointd_addon"))

from tools.valve_trial_analysis import (
    analyze_valve_transactions,
    analyze_zone_matrix,
    classify_htv405_retained_attempts,
    classify_pairing_exchange,
)


def frame(source: str, destination: str, message: int, *, zone: int = 0,
          action: int = 0, duration_seconds: int = 0) -> str:
    value = bytearray(38)
    value[:5] = bytes.fromhex("79f4882f28")
    value[5:9] = bytes.fromhex(source)
    value[9:13] = bytes.fromhex(destination)
    value[13] = message
    value[14] = action
    value[15] = zone
    value[19:21] = (duration_seconds // 2).to_bytes(2, "little")
    return value.hex()


class CounterRecoveryEvidenceTests(unittest.TestCase):
    def test_active_counter_anchors_support_followup_and_wraparound(self):
        import json
        from pathlib import Path
        from tools.analyze_htv145_command_phase import command_phase
        from rainpointd.valve_protocol import ValveLink, decode_htv145_gateway_command, decode_htv145_command_response, decode_htv145_command_error, decode_htv145_state_report
        fixture = json.loads((Path(__file__).resolve().parents[1] / 'research/fixtures/htv145_active_counter_recovery_20260906.json').read_text())
        link = ValveLink(bytes.fromhex(fixture['controller_endpoint']), bytes.fromhex(fixture['valve_endpoint']))
        rows = fixture['command_transactions']
        self.assertEqual([5, 0, 1, 2, 3, 62, 63, 0], [command_phase(bytes.fromhex(r['command_frame']), link) for r in rows])
        for row in rows:
            command = decode_htv145_gateway_command(bytes.fromhex(row['command_frame']), link)
            response = bytes.fromhex(row['response_frame'])
            reply = decode_htv145_command_response(response, link)
            self.assertIsNone(decode_htv145_command_error(response, link))
            for key in ('sequence', 'watering', 'command_marker_inverted'):
                self.assertEqual(command[key], reply[key])
            self.assertEqual(row['watering'], decode_htv145_state_report(bytes.fromhex(row['independent_state_frame']), link)['watering'])
            self.assertGreater(row['independent_state_at'], row['observed_at'])
        self.assertNotEqual(rows[1]['phase'], (rows[0]['phase'] + 1) % 64)
        self.assertNotEqual(rows[5]['phase'], (rows[4]['phase'] + 1) % 64)
        self.assertEqual(0x80, decode_htv145_command_response(bytes.fromhex(rows[6]['response_frame']), link)['next_sequence'])

    def test_next_phase_negative_marker_is_not_a_timeout_or_acceptance(self):
        import json
        from pathlib import Path
        from tools.analyze_htv145_control_iq import summarize_matches
        from rainpointd.valve_protocol import ValveLink, decode_htv145_command_error, decode_htv145_command_response
        fixture = json.loads((Path(__file__).resolve().parents[1] / 'research/fixtures/htv145_next_phase_idle_close_rejection_20260906.json').read_text())
        link = ValveLink(bytes.fromhex(fixture['controller_endpoint']), bytes.fromhex(fixture['valve_endpoint']))
        response = bytes.fromhex(fixture['response_frame'])
        self.assertEqual({'sequence': 0x82, 'result_code': 3}, decode_htv145_command_error(response, link))
        self.assertIsNone(decode_htv145_command_response(response, link))
        summary = summarize_matches([dict(frame_hex=response.hex(), phase_count=136,
            alternating_wake_symbol_histogram={'321': 136}, alternating_wake_symbols=[321])], link)
        self.assertEqual(1, len(summary['errors']))
        self.assertEqual([], summary['responses'])

    def test_supported_anchor_decoder_requires_matching_zero_idle_response(self):
        import binascii
        from rainpointd.htv145_control import Htv145ControlProfile
        from rainpointd.valve_protocol import decode_htv145_idle_anchor_response
        profile = Htv145ControlProfile(node_id="rp-001122334455", controller_endpoint="b1c2d38f",
            valve_endpoint="a1b2c380", center_hz=434398811, power_dbm=10, invert=False,
            trailer_residual=0x4f03, close_trailer_residual=0x4f03,
            command_marker_inverted=True, report_ack_center_hz=434398811)
        raw = bytearray.fromhex("79f4882f28a1b2c380b1c2d38f81d0868010cf80000000409e00569e000000000000000060e2")
        residue = binascii.crc_hqx(raw[:-2], 0) ^ int.from_bytes(raw[-2:], "big")
        raw[13] = 0x80; raw[14] = 0x50; raw[18] = 0x4f
        raw[-2:] = (binascii.crc_hqx(raw[:-2], 0) ^ residue).to_bytes(2, "big")
        self.assertEqual({"sequence": 0x80, "result_code": 0}, decode_htv145_idle_anchor_response(bytes(raw), profile.link))
        raw[5] ^= 1
        self.assertIsNone(decode_htv145_idle_anchor_response(bytes(raw), profile.link))

    def test_captured_baseline_negative_cannot_authenticate_anchor(self):
        import json
        from pathlib import Path
        from rainpointd.htv145_control import Htv145ControlProfile
        from rainpointd.valve_protocol import decode_htv145_idle_anchor_response
        from rainpointd.valve_protocol import decode_htv145_command_error, decode_htv145_gateway_command
        fixture = json.loads((Path(__file__).resolve().parents[1] / "research/fixtures/htv145_counter_anchor_baseline_negative_20260906.json").read_text())
        profile = Htv145ControlProfile(node_id="rp-001122334455",
            controller_endpoint=fixture["controller_endpoint"], valve_endpoint=fixture["valve_endpoint"],
            center_hz=434398811, power_dbm=10, invert=False,
            trailer_residual=0x4f03, close_trailer_residual=0x4f03,
            command_marker_inverted=True, report_ack_center_hz=434398811)
        command, reply = [bytes.fromhex(row["frame_hex"]) for row in fixture["frames"]]
        self.assertFalse(decode_htv145_gateway_command(command, profile.link)["watering"])
        self.assertEqual({"sequence": 0x83, "result_code": 3}, decode_htv145_command_error(reply, profile.link))
        self.assertIsNone(decode_htv145_idle_anchor_response(reply, profile.link))

    def test_fresh_pairing_control_baseline_has_matching_open_close_and_idle(self):
        import json
        from pathlib import Path
        from rainpointd.valve_protocol import ValveLink, decode_htv145_gateway_command, decode_htv145_command_response, decode_htv145_state_report
        data = json.loads((Path(__file__).resolve().parents[1] / "research/fixtures/htv145_fresh_pairing_control_baseline_20260906.json").read_text())
        link = ValveLink(bytes.fromhex(data["controller_endpoint"]), bytes.fromhex(data["valve_endpoint"]))
        commands = [decode_htv145_gateway_command(bytes.fromhex(row["frame"]), link) for row in data["commands"]]
        replies = [decode_htv145_command_response(bytes.fromhex(row["frame"]), link) for row in data["responses"]]
        self.assertEqual([(129, True), (130, False)], [(c["sequence"], c["watering"]) for c in commands])
        self.assertEqual(60, commands[0]["duration_seconds"])
        for command in commands:
            self.assertTrue(any(reply and all(reply[k] == command[k] for k in ("sequence", "watering", "command_marker_inverted")) for reply in replies))
        self.assertFalse(decode_htv145_state_report(bytes.fromhex(data["independent_idle_frame"]), link)["watering"])
        self.assertEqual(130, commands[-1]["next_sequence"])

    def test_recorded_stock_commands_advance_counter_and_marker_together(self):
        import json
        from pathlib import Path
        from tools.analyze_htv145_command_phase import analyze_transactions, command_phase
        from rainpointd.valve_protocol import ValveLink
        root = Path(__file__).resolve().parents[1] / "research/fixtures"
        stock = json.loads((root / "htv145_selector2_stock_pairing_control_20260905.json").read_text())
        rows = stock["command_transactions"]
        first = bytes.fromhex(rows[0]["command_frame"])
        link = ValveLink(first[5:9], first[9:13])
        result = analyze_transactions(rows, link)
        self.assertEqual([3, 4, 5, 6, 7], [c["phase"] for c in result["commands"]])
        self.assertTrue(result["all_adjacent_increment"])
        fresh = json.loads((root / "htv145_fresh_pairing_control_baseline_20260906.json").read_text())
        accepted_close = bytes.fromhex(fresh["commands"][1]["frame"])
        self.assertEqual(4, command_phase(accepted_close, link))
        rejected = json.loads((root / "htv145_repeated_idle_close_rejection_20260906.json").read_text())
        from rainpointd.valve_protocol import decode_htv145_command_error, decode_htv145_command_response
        self.assertEqual(accepted_close.hex(), rejected["command_frame"])
        reply = bytes.fromhex(rejected["response_frame"])
        self.assertIsNone(decode_htv145_command_response(reply, link))
        self.assertEqual(3, decode_htv145_command_error(reply, link)["result_code"])
        next_phase = json.loads((root / "htv145_next_phase_idle_close_rejection_20260906.json").read_text())
        candidate = bytes.fromhex(next_phase["command_frame"])
        self.assertEqual(5, command_phase(candidate, link))
        self.assertEqual(0x82, candidate[13])
        self.assertEqual(0x90, candidate[14])
        self.assertEqual(accepted_close[15:36], candidate[15:36])

class ValveTrialAnalysisTests(unittest.TestCase):
    def test_distinguishes_retained_rejoin_from_new_assignment(self) -> None:
        report = classify_htv405_retained_attempts(
            [
                {
                    "capture": "boot",
                    "factory_flag": "7f",
                    "assignment_observed": False,
                    "paired_traffic_observed": False,
                },
                {
                    "capture": "stored",
                    "factory_flag": "ff",
                    "assignment_observed": False,
                    "paired_traffic_observed": True,
                },
                {
                    "capture": "accepted",
                    "factory_flag": "ff",
                    "assignment_observed": True,
                    "paired_traffic_observed": True,
                    "node_completed_steps": 1,
                    "interpretation": "assignment accepted under controlled test",
                },
            ]
        )

        self.assertEqual("cold_boot_sweep_only", report["attempts"][0]["classification"])
        self.assertEqual(
            "retained_association_rejoin", report["attempts"][1]["classification"]
        )
        self.assertTrue(report["attempts"][2]["new_assignment_proven"])
        self.assertFalse(report["findings"]["white_led_is_assignment_proof"])

    def test_correlates_htv145_retries_response_and_independent_state(self) -> None:
        raws = [
            "79f4882f28b42d008fb9840280811082808100d8020000000000000000000000000000001c68",
            "79f4882f28b42d008fb9840280811082808100d8020000000000000000000000000000001c68",
            "79f4882f28b42d008fb9840280811082808100d8020000000000000000000000000000001c68",
            "79f4882f28b9840280b42d008f8150868010cf8702000040d80256d802000000000000004bfa",
            "79f4882f28b9840280b42d008f89810785898090cf8702000040d58256d80200000000003fc6",
        ]
        offsets = (0, 0.729210, 1.668479, 1.719304, 7.348155)
        base = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
        events = [
            {
                "event_id": index + 1,
                "observed_at": (base + timedelta(seconds=offset)).isoformat(),
                "raw": raw,
            }
            for index, (offset, raw) in enumerate(zip(offsets, raws))
        ]

        report = analyze_valve_transactions(
            events,
            model="HTV145FRF",
            controller_endpoint="b42d008f",
            valve_endpoint="b9840280",
        )

        self.assertEqual(1, report["logical_command_count"])
        self.assertEqual(3, report["rf_attempt_count"])
        transaction = report["transactions"][0]
        self.assertEqual([0.0, 729.21, 1668.479], transaction["attempt_offsets_ms"])
        self.assertEqual(4, transaction["response_event_id"])
        self.assertEqual(50.825, transaction["response_latency_ms"])
        self.assertEqual(5, transaction["state_event_id"])
        self.assertEqual(0x89, transaction["state_sequence"])

    def test_correlates_htv405_profile_specific_zone_transaction(self) -> None:
        raws = [
            "79f4882f2894a98013398402808e90828082009e0000000000000000000000000000000030da",
            "79f4882f28b984028094a980130ed0868020cf80000000409e00569e000000000000000010a4",
            "79f4882f28b984028094a980131a8107820580a0cf80000000409e00569e0000000000000d22",
        ]
        base = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
        events = [
            {
                "event_id": index + 1,
                "observed_at": (base + timedelta(seconds=index)).isoformat(),
                "raw": raw,
            }
            for index, raw in enumerate(raws)
        ]

        report = analyze_valve_transactions(
            events,
            model="HTV405FRF",
            controller_endpoint="b9840280",
            valve_endpoint="94a98013",
            companion_endpoint="39840280",
        )

        transaction = report["transactions"][0]
        self.assertEqual(2, transaction["zone"])
        self.assertEqual("selector2_local", transaction["zone_packing"])
        self.assertEqual(60, transaction["duration_seconds"])
        self.assertEqual(2, transaction["response_event_id"])
        self.assertEqual(3, transaction["state_event_id"])
        self.assertTrue(transaction["state_watering"])

    def test_correlates_htv405_close_response_and_zone_less_idle(self) -> None:
        raws = [
            "79f4882f2894a980133984028084108180810000000000000000000000000000000000004f0c",
            "79f4882f28b984028094a9801304508683104f80000000408000568000000000000000001e6e",
            "79f4882f28b984028094a980131d0107820580804f8000000040800056800000000000000045",
        ]
        base = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
        events = [
            {
                "event_id": index + 1,
                "observed_at": (base + timedelta(seconds=index)).isoformat(),
                "raw": raw,
            }
            for index, raw in enumerate(raws)
        ]

        report = analyze_valve_transactions(
            events,
            model="HTV405FRF",
            controller_endpoint="b9840280",
            valve_endpoint="94a98013",
            companion_endpoint="39840280",
        )

        transaction = report["transactions"][0]
        self.assertEqual("close", transaction["action"])
        self.assertEqual(1, transaction["zone"])
        self.assertEqual(2, transaction["response_event_id"])
        self.assertEqual(3, transaction["state_event_id"])
        self.assertFalse(transaction["state_watering"])

    def test_classifies_structural_three_phase_exchange(self) -> None:
        events = [
            {"event_id": 1, "observed_at": "2026-08-17T12:00:00Z",
             "raw": frame("01020304", "05060708", 1)},
            {"event_id": 2, "observed_at": "2026-08-17T12:00:01Z",
             "raw": frame("05060708", "01020304", 2)},
            {"event_id": 3, "observed_at": "2026-08-17T12:00:02Z",
             "raw": frame("01020304", "05060708", 3)},
        ]

        report = classify_pairing_exchange(events)

        self.assertEqual(1, report["bidirectional_exchange_count"])
        phases = [
            item["phase"] for item in report["exchanges"][0]["phase_candidates"]
        ]
        self.assertEqual(
            [
                "initial_announcement_candidate",
                "first_reverse_reply_candidate",
                "first_post_reply_confirmation_candidate",
            ],
            phases,
        )

    def test_mixed_naive_and_aware_timestamps_follow_event_cursor(self) -> None:
        events = [
            {"event_id": 1, "observed_at": "2026-08-17T12:00:00",
             "raw": frame("01020304", "05060708", 1)},
            {"event_id": 2, "observed_at": "2026-08-17T16:00:01+00:00",
             "raw": frame("05060708", "01020304", 2)},
        ]

        report = classify_pairing_exchange(events)

        self.assertEqual(1, report["bidirectional_exchange_count"])

    def test_finds_zone_action_and_duration_candidates(self) -> None:
        base = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
        actions = []
        events = []
        rows = [
            (zone, "zone_open", duration, 0x10)
            for zone in range(1, 5)
            for duration in (60, 120)
        ] + [
            (zone, "zone_close", None, 0x90) for zone in range(1, 5)
        ]
        for index, (zone, action, duration, action_byte) in enumerate(rows):
            marked_at = base + timedelta(seconds=index * 20)
            marker = {
                "timestamp": marked_at.isoformat(),
                "action": action,
                "zone": zone,
            }
            if duration is not None:
                marker["duration_seconds"] = duration
            actions.append(marker)
            events.append(
                {
                    "event_id": index + 1,
                    "observed_at": (marked_at + timedelta(seconds=1)).isoformat(),
                    "raw": frame(
                        "01020304",
                        "05060708",
                        index + 1,
                        zone=zone,
                        action=action_byte,
                        duration_seconds=duration or 0,
                    ),
                }
            )

        report = analyze_zone_matrix(events, actions)

        self.assertTrue(report["evidence_complete"])
        self.assertTrue(report["coverage"]["matrix_complete"])
        route = report["routes"][0]
        self.assertEqual(15, route["zone_candidates"][0]["byte"])
        self.assertIn(14, {item["byte"] for item in route["action_candidates"]})
        self.assertIn(
            (19, "little", 2),
            {
                (
                    item["offset"],
                    item["byte_order"],
                    item["scale_to_seconds"],
                )
                for item in route["duration_candidates"]
            },
        )

    def test_rejects_confounded_partial_matrix(self) -> None:
        base = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
        actions = [
            {
                "timestamp": base.isoformat(),
                "action": "zone_open",
                "zone": 1,
                "duration_seconds": 60,
            }
        ]
        events = [
            {
                "event_id": 1,
                "observed_at": (base + timedelta(seconds=1)).isoformat(),
                "raw": frame(
                    "01020304", "05060708", 1, zone=1, action=0x10,
                    duration_seconds=60,
                ),
            }
        ]

        report = analyze_zone_matrix(events, actions)

        self.assertFalse(report["evidence_complete"])
        self.assertFalse(report["coverage"]["matrix_complete"])
        self.assertEqual(7, len(report["coverage"]["missing_open_pairs"]))

    def test_applies_append_only_zone_correction_and_ignores_notes(self) -> None:
        base = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
        actions = [
            {
                "timestamp": base.isoformat(),
                "action": "zone_open",
                "zone": 1,
                "duration_seconds": 120,
            },
            {
                "timestamp": (base + timedelta(seconds=35)).isoformat(),
                "action": "zone_close",
                "zone": 1,
            },
            {
                "timestamp": (base + timedelta(seconds=40)).isoformat(),
                "action": "marker_correction",
                "zone": 2,
                "duration_seconds": 120,
            },
            {
                "timestamp": (base + timedelta(seconds=45)).isoformat(),
                "action": "zone_running_observation",
                "zone": 2,
                "duration_seconds": 120,
            },
        ]
        events = [
            {
                "event_id": 1,
                "observed_at": (base + timedelta(seconds=15)).isoformat(),
                "raw": frame(
                    "01020304", "05060708", 1, zone=2, action=0x10,
                    duration_seconds=120,
                ),
            },
            {
                "event_id": 2,
                "observed_at": (base + timedelta(seconds=36)).isoformat(),
                "raw": frame(
                    "01020304", "05060708", 2, zone=2, action=0x90,
                ),
            },
        ]

        report = analyze_zone_matrix(events, actions)

        self.assertEqual([[2, 120]], report["coverage"]["observed_open_pairs"])
        self.assertEqual([2], report["coverage"]["observed_close_zones"])
        self.assertEqual(2, report["structured_action_count"])
        self.assertTrue(all(item["frame_count"] == 1 for item in report["actions"]))

    def test_uses_bounded_preceding_frame_for_retrospective_marker(self) -> None:
        base = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
        actions = [
            {
                "timestamp": base.isoformat(),
                "action": "zone_open",
                "zone": 1,
                "duration_seconds": 60,
            },
            {
                "timestamp": (base + timedelta(seconds=50)).isoformat(),
                "action": "zone_close",
                "zone": 1,
            },
        ]
        events = [
            {
                "event_id": 1,
                "observed_at": (base + timedelta(seconds=5)).isoformat(),
                "raw": frame(
                    "01020304", "05060708", 1, zone=1, action=0x10,
                    duration_seconds=60,
                ),
            },
            {
                "event_id": 2,
                "observed_at": (base + timedelta(seconds=45)).isoformat(),
                "raw": frame(
                    "01020304", "05060708", 2, zone=1, action=0x90,
                ),
            },
        ]

        report = analyze_zone_matrix(events, actions)

        self.assertEqual(1, report["actions"][0]["frame_count"])
        self.assertEqual(1, report["actions"][1]["frame_count"])


if __name__ == "__main__":
    unittest.main()
