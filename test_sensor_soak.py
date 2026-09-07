#!/usr/bin/env python3

from __future__ import annotations

import unittest

from tools.sensor_soak import evaluate


def snapshot(timestamp: str, count: int, *, reporting: bool = True) -> dict:
    return {
        "captured_at": timestamp,
        "devices": {
            "devices": [
                {
                    "device_id": "soil-a",
                    "name": "Sensor A",
                    "report_count": count,
                    "reporting": reporting,
                    "report_age_seconds": 120,
                    "state": {"device_kind": "soil_sensor"},
                }
            ]
        },
        "nodes": {
            "nodes": [
                {
                    "managed": True,
                    "connected": True,
                    "authenticated": True,
                    "routine_ack_assigned_sensors": 1,
                }
            ]
        },
        "receivers": {"receivers": []},
    }


class SensorSoakTests(unittest.TestCase):
    def test_passes_complete_72_hour_fleet_soak(self) -> None:
        before = snapshot("2026-08-10T12:00:00Z", 10)
        after = snapshot("2026-08-13T12:00:00Z", 154)
        report = evaluate(before, after)
        self.assertTrue(report["passed"])
        self.assertEqual(144, report["sensors"][0]["minimum_report_delta"])

    def test_rejects_stale_sensor_even_when_count_advanced(self) -> None:
        before = snapshot("2026-08-10T12:00:00Z", 10)
        after = snapshot("2026-08-13T12:00:00Z", 154, reporting=False)
        report = evaluate(before, after)
        self.assertFalse(report["passed"])
        self.assertFalse(report["sensors"][0]["checks"]["reporting_now"])

    def test_rejects_short_observation(self) -> None:
        before = snapshot("2026-08-10T12:00:00Z", 10)
        after = snapshot("2026-08-10T13:00:00Z", 12)
        report = evaluate(before, after)
        self.assertFalse(report["duration_passed"])
        self.assertFalse(report["passed"])


class ReliabilityCollectionTests(unittest.TestCase):
    def test_cursor_and_fixed_window_survive_reopen_and_completion(self):
        import tempfile
        from pathlib import Path
        from datetime import datetime, timedelta, timezone
        from tools.reliability_soak import connect, collect
        now = datetime(2026, 9, 6, tzinfo=timezone.utc)
        def getter(resource):
            if resource == "devices":
                return {"devices": [{"last_event_id": 10}]}
            if resource == "events?since=10":
                return {"events": [{"event_id": 11}]}
            return {"events": []}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "soak.sqlite3"
            db = connect(path)
            first = collect(db, getter, now=now, hours=1)
            db.close()
            db = connect(path)
            second = collect(db, getter, now=now + timedelta(hours=1), hours=72)
            self.assertEqual(first["ends_at"], second["ends_at"])
            self.assertEqual("completed", second["state"])
            self.assertEqual(1, second["events"])
            def forbidden(_):
                raise AssertionError("completed window must not poll")
            self.assertEqual(second, collect(db, forbidden, now=now + timedelta(hours=2)))
            db.close()

    def test_failed_page_preserves_cursor_and_records_error_without_details(self):
        import tempfile
        from pathlib import Path
        from datetime import datetime, timezone
        from tools.reliability_soak import connect, collect, summary
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "soak.sqlite3")
            def getter(resource):
                if resource.startswith("events?"):
                    raise RuntimeError("sensitive response")
                return {"devices": [{"last_event_id": 10}]}
            with self.assertRaises(RuntimeError):
                collect(db, getter, now=datetime.now(timezone.utc))
            result = summary(db)
            self.assertEqual("0", result["cursor"])
            self.assertEqual(0, result["snapshots"])
            self.assertEqual({"collection_error": 1}, result["observations"])
            self.assertEqual("RuntimeError", db.execute("SELECT detail FROM observations").fetchone()[0])
            db.close()

    def test_retention_gap_is_recorded_and_cannot_silently_pass(self):
        import tempfile
        from pathlib import Path
        from datetime import datetime, timezone
        from tools.reliability_soak import connect, collect
        with tempfile.TemporaryDirectory() as directory:
            db = connect(Path(directory) / "soak.sqlite3")
            def getter(resource):
                if resource == "devices": return {"devices": [{"last_event_id": 10}]}
                if resource.startswith("events?"): return {"events": [{"event_id": 13}]}
                return {}
            result = collect(db, getter, now=datetime.now(timezone.utc))
            self.assertEqual({"event_gap": 1}, result["observations"])
            self.assertEqual("evidence_only_not_automatic_pass", result["qualification"])
            db.close()


if __name__ == "__main__":
    unittest.main()
