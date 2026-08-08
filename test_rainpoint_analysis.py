#!/usr/bin/env python3

from __future__ import annotations

import io
import json
import unittest

from tools.analyze_rainpoint_events import analyze, fetch_events, load_events


class FakeResponse(io.StringIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


class RainPointEventAnalysisTest(unittest.TestCase):
    def test_fetches_all_cursor_pages(self) -> None:
        requested = []

        def open_page(url, *, timeout):
            requested.append((url, timeout))
            if "since=0" in url:
                payload = {
                    "events": [{"event_id": 1}, {"event_id": 2}],
                    "next_since": 2,
                }
            elif "since=2" in url:
                payload = {"events": [{"event_id": 3}], "next_since": 3}
            else:
                payload = {"events": [], "next_since": 3}
            return FakeResponse(json.dumps(payload))

        events = fetch_events(
            "http://gateway:8787/api/v1/events",
            timeout=4.5,
            opener=open_page,
        )

        self.assertEqual([1, 2, 3], [event["event_id"] for event in events])
        self.assertEqual(3, len(requested))
        self.assertTrue(all(timeout == 4.5 for _, timeout in requested))

    def test_rejects_stalled_cursor(self) -> None:
        def open_page(url, *, timeout):
            return FakeResponse(
                json.dumps({"events": [{"event_id": 1}], "next_since": 0})
            )

        with self.assertRaisesRegex(ValueError, "did not advance"):
            fetch_events(
                "http://gateway:8787/api/v1/events", opener=open_page
            )

    def test_loads_concatenated_api_pages_and_correlates_compact_status(self) -> None:
        right_bed = {
            "event_id": 1,
            "observed_at": "2026-08-07T01:28:59.614437",
            "raw": (
                "79f4882f28b42d008f9ce5802415848307018005c41c8000"
                "000000000000000000000000729c"
            ),
            "state": {
                "rf_endpoint": "9ce58024",
                "soil_moisture_percent": 57,
            },
        }
        compact = {
            "event_id": 2,
            "observed_at": "2026-08-07T01:29:00.654423",
            "raw": (
                "79f4882f28b9840280b42d008f8805040703000b8839e0b1"
                "00000000000000000000000001c8"
            ),
            "state": {},
        }
        source = io.StringIO(
            json.dumps({"events": [right_bed], "next_since": 1})
            + json.dumps({"events": [compact], "next_since": 2})
        )

        result = analyze(load_events(source))

        self.assertEqual(2, result["event_count"])
        association = result["compact_associations"][0]
        self.assertEqual(57, association["moisture"])
        candidate = association["candidates"][0]
        self.assertEqual("9ce58024", candidate["endpoint"])
        self.assertTrue(candidate["value_matches"])
        self.assertAlmostEqual(1.039986, candidate["delta_seconds"])

    def test_correlates_valve_command_response_latency(self) -> None:
        request = {
            "event_id": 10,
            "observed_at": "2026-08-07T12:00:00.000000",
            "raw": (
                "79f4882f28b42d008fb9840280811082808100fe0180"
                "00000000000000000000000000007669"
            ),
            "state": {},
        }
        response = {
            "event_id": 11,
            "observed_at": "2026-08-07T12:00:00.180000",
            "raw": (
                "79f4882f28b9840280b42d008f9750868010cf92800000409e00569e"
                "000000000000000044ce"
            ),
            "state": {},
        }

        transactions = analyze([request, response])["valve_transactions"]

        self.assertEqual(1, transactions["command_count"])
        self.assertEqual({"open": 1}, transactions["mode_counts"])
        self.assertEqual({"open": 1}, transactions["acknowledged_counts"])
        self.assertEqual({"1020": 1}, transactions["open_duration_counts"])
        command = transactions["commands"][0]
        self.assertEqual(11, command["response_event_id"])
        self.assertAlmostEqual(0.18, command["response_latency_seconds"])


if __name__ == "__main__":
    unittest.main()
