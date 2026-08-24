"""Tests for passive enrollment and multi-zone differential analysis."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

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
