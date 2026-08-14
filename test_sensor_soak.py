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


if __name__ == "__main__":
    unittest.main()
