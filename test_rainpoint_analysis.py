#!/usr/bin/env python3

from __future__ import annotations

import io
import json
import unittest

from tools.analyze_rainpoint_events import analyze, load_events


class RainPointEventAnalysisTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
