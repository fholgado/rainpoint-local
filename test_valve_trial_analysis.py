"""Tests for passive enrollment and multi-zone differential analysis."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from tools.valve_trial_analysis import analyze_zone_matrix, classify_pairing_exchange


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


if __name__ == "__main__":
    unittest.main()
