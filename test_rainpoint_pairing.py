#!/usr/bin/env python3

from __future__ import annotations

import sys
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "rainpointd_addon"))

from rainpointd.pairing import (  # noqa: E402
    HCS026EnrollmentManager,
    factory_endpoint,
    paired_endpoint,
)
from rainpointd.rf import normalize_row  # noqa: E402


UTC = timezone.utc
FACTORY = {
    "hcs026_pairing_state": "factory",
    "hcs026_factory_endpoint": "1bce0024",
    "message_type": 1,
}
PAIRED = {
    "hcs026_pairing_state": "paired",
    "hcs026_factory_endpoint": "1bce0024",
    "hcs026_paired_endpoint": "9bce0024",
    "message_type": 3,
}


class HCS026EnrollmentTest(unittest.TestCase):
    def test_identity_derivation_matches_both_controlled_sensors(self) -> None:
        self.assertEqual("9bce0024", paired_endpoint("1bce0024"))
        self.assertEqual("95a98024", paired_endpoint("15a98024"))
        self.assertEqual("1bce0024", factory_endpoint("9bce0024"))
        with self.assertRaises(ValueError):
            paired_endpoint("9bce0024")

    def test_enrolls_only_complete_sequence_inside_window_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pairing.json"
            now = datetime(2026, 8, 10, 14, 13, 27, tzinfo=UTC)
            manager = HCS026EnrollmentManager(path)
            manager.start(120, now=now)
            self.assertEqual(
                "candidate_observed", manager.observe(FACTORY, now=now)["action"]
            )
            result = manager.observe(PAIRED, now=now + timedelta(seconds=3))
            self.assertEqual("enrolled", result["action"])
            self.assertEqual(
                "9bce0024", manager.status(now=now)["new_records"][0]["paired_endpoint"]
            )

            restored = HCS026EnrollmentManager(path)
            self.assertEqual("9bce0024", restored.records()[0].paired_endpoint)
            self.assertEqual(
                "known_paired",
                restored.observe(PAIRED, now=now + timedelta(seconds=9))["action"],
            )

    def test_controlled_capture_fixture_enrolls_both_sensors(self) -> None:
        fixture = json.loads(
            (ROOT / "research/fixtures/hcs026_pairing_battery.json").read_text()
        )
        with tempfile.TemporaryDirectory() as directory:
            manager = HCS026EnrollmentManager(Path(directory) / "pairing.json")
            now = datetime(2026, 8, 10, tzinfo=UTC)
            manager.start(now=now)
            actions = []
            for index, observation in enumerate(fixture["observations"]):
                frame = observation["frame"]
                decoded = normalize_row({"len": len(frame) * 4, "data": frame})
                actions.append(
                    manager.observe(decoded, now=now + timedelta(seconds=index))["action"]
                )
            self.assertEqual(2, actions.count("enrolled"))
            self.assertEqual(
                ["95a98024", "9bce0024"],
                sorted(record.paired_endpoint for record in manager.records()),
            )

    def test_duplicate_frames_are_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = HCS026EnrollmentManager(Path(directory) / "pairing.json")
            now = datetime(2026, 8, 10, tzinfo=UTC)
            manager.start(now=now)
            manager.observe(FACTORY, now=now)
            manager.observe(FACTORY, now=now + timedelta(milliseconds=100))
            manager.observe(PAIRED, now=now + timedelta(seconds=3))
            result = manager.observe(PAIRED, now=now + timedelta(seconds=6))
            self.assertEqual("known_paired", result["action"])
            self.assertEqual(1, len(manager.records()))

    def test_paired_identity_without_terminal_message_is_only_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = HCS026EnrollmentManager(Path(directory) / "pairing.json")
            now = datetime(2026, 8, 10, tzinfo=UTC)
            manager.start(now=now)
            manager.observe(FACTORY, now=now)
            progress = manager.observe(
                {**PAIRED, "message_type": 1},
                now=now + timedelta(seconds=3),
            )
            self.assertEqual("paired_progress", progress["action"])
            self.assertEqual([], manager.records())
            enrolled = manager.observe(PAIRED, now=now + timedelta(seconds=12))
            self.assertEqual("enrolled", enrolled["action"])

    def test_timeout_and_interrupted_window_do_not_enroll(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pairing.json"
            now = datetime(2026, 8, 10, tzinfo=UTC)
            manager = HCS026EnrollmentManager(path)
            manager.start(2, now=now)
            manager.observe(FACTORY, now=now)
            self.assertEqual(
                "pairing_window_closed",
                manager.observe(PAIRED, now=now + timedelta(seconds=3))["reason"],
            )
            self.assertFalse(path.exists())

            restarted = HCS026EnrollmentManager(path)
            self.assertEqual(
                "pairing_window_closed", restarted.observe(PAIRED, now=now)["reason"]
            )

    def test_naive_rtl_timestamp_does_not_interrupt_aware_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = HCS026EnrollmentManager(Path(directory) / "pairing.json")
            aware = datetime.now(timezone.utc)
            manager.start(120, now=aware)
            local_naive = datetime.now().replace(tzinfo=None)
            result = manager.observe(FACTORY, now=local_naive)
            self.assertEqual("candidate_observed", result["action"])

    def test_requires_factory_announcement_and_supports_local_forget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = HCS026EnrollmentManager(Path(directory) / "pairing.json")
            now = datetime(2026, 8, 10, tzinfo=UTC)
            manager.start(now=now)
            self.assertEqual(
                "factory_announcement_missing", manager.observe(PAIRED, now=now)["reason"]
            )
            manager.observe(FACTORY, now=now)
            manager.observe(PAIRED, now=now + timedelta(seconds=3))
            self.assertTrue(manager.forget("9bce0024"))
            self.assertFalse(manager.forget("1bce0024"))
            self.assertEqual([], manager.records())


if __name__ == "__main__":
    unittest.main()
