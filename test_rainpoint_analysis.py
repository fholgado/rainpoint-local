#!/usr/bin/env python3

from __future__ import annotations

import binascii
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
    @staticmethod
    def _valid_frame(payload: bytearray, residue: int = 0xC713) -> str:
        trailer = binascii.crc_hqx(payload[:36], 0) ^ residue
        payload[36:38] = trailer.to_bytes(2, "big")
        return payload.hex()

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
        self.assertFalse(association["trailer_valid"])
        candidate = association["candidates"][0]
        self.assertEqual("9ce58024", candidate["endpoint"])
        self.assertTrue(candidate["value_matches"])
        self.assertAlmostEqual(1.039986, candidate["delta_seconds"])

    def test_correlates_valve_command_response_latency(self) -> None:
        response_frame = bytearray.fromhex(
            "79f4882f28b9840280b42d008f8150868010cf92800000409e00569e"
            "000000000000000044ce"
        )
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
            "raw": self._valid_frame(response_frame),
            "state": {},
        }

        transactions = analyze([request, response])["valve_transactions"]

        self.assertEqual(1, transactions["command_count"])
        self.assertEqual({"open": 1}, transactions["mode_counts"])
        self.assertEqual({"open": 1}, transactions["acknowledged_counts"])
        self.assertEqual({"1020": 1}, transactions["open_duration_counts"])
        self.assertEqual(
            {"b42d008f->b9840280": 1}, transactions["link_counts"]
        )
        command = transactions["commands"][0]
        self.assertEqual("b42d008f", command["controller_endpoint"])
        self.assertEqual("b9840280", command["valve_endpoint"])
        self.assertEqual(11, command["response_event_id"])
        self.assertAlmostEqual(0.18, command["response_latency_seconds"])

    def test_correlates_an_unknown_valve_link_without_house_ids(self) -> None:
        request_frame = bytearray(38)
        request_frame[:5] = bytes.fromhex("79f4882f28")
        request_frame[5:9] = bytes.fromhex("11223344")
        request_frame[9:13] = bytes.fromhex("aabbccdd")
        request_frame[13:15] = bytes((0x81, 0x90))
        response_frame = bytearray(38)
        response_frame[:5] = bytes.fromhex("79f4882f28")
        response_frame[5:9] = bytes.fromhex("aabbccdd")
        response_frame[9:13] = bytes.fromhex("11223344")
        response_frame[13:15] = bytes((0x81, 0xD0))
        request = {
            "event_id": 20,
            "observed_at": "2026-08-07T12:00:00.000000",
            "raw": self._valid_frame(request_frame),
            "state": {},
        }
        response = {
            "event_id": 21,
            "observed_at": "2026-08-07T12:00:00.400000",
            "raw": self._valid_frame(response_frame),
            "state": {},
        }

        transactions = analyze([request, response])["valve_transactions"]

        self.assertEqual(1, transactions["command_count"])
        self.assertEqual({"11223344->aabbccdd": 1}, transactions["link_counts"])
        self.assertEqual(21, transactions["commands"][0]["response_event_id"])

    def test_htv405_operation_uses_selector_not_repeat_bit(self) -> None:
        opened = {
            "event_id": 30,
            "observed_at": "2026-08-24T15:55:52.332153+00:00",
            "raw": (
                "79f4882f2894a98013398402808a10828181009e000000000"
                "0000000000000000000000049f1"
            ),
            "state": {},
        }
        closed = {
            "event_id": 31,
            "observed_at": "2026-08-24T15:56:14.041945+00:00",
            "raw": (
                "79f4882f2894a98013398402808a908181810000000000000"
                "000000000000000000000001e1a"
            ),
            "state": {},
        }

        transactions = analyze([opened, closed])["valve_transactions"]

        self.assertEqual(
            ["open", "close"],
            [command["mode"] for command in transactions["commands"]],
        )
        self.assertEqual(
            ["8a", "8a"],
            [command["sequence"] for command in transactions["commands"]],
        )

    def test_mixed_receiver_timestamp_styles_do_not_break_analysis(self) -> None:
        request_frame = bytearray(38)
        request_frame[:5] = bytes.fromhex("79f4882f28")
        request_frame[5:9] = bytes.fromhex("11223344")
        request_frame[9:13] = bytes.fromhex("aabbccdd")
        request_frame[13:15] = bytes((0x81, 0x90))
        response_frame = bytearray(38)
        response_frame[:5] = bytes.fromhex("79f4882f28")
        response_frame[5:9] = bytes.fromhex("aabbccdd")
        response_frame[9:13] = bytes.fromhex("11223344")
        response_frame[13:15] = bytes((0x81, 0xD0))

        transactions = analyze(
            [
                {
                    "event_id": 30,
                    "observed_at": "2026-08-07T08:00:00.000000",
                    "raw": self._valid_frame(request_frame),
                    "state": {},
                },
                {
                    "event_id": 31,
                    "observed_at": "2026-08-07T12:00:00.180000+00:00",
                    "raw": self._valid_frame(response_frame),
                    "state": {},
                },
            ]
        )["valve_transactions"]

        self.assertEqual(1, transactions["command_count"])


if __name__ == "__main__":
    unittest.main()
