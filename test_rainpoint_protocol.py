#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "rainpointd_addon"))

from rainpoint_protocol import decode, parse_tlv  # noqa: E402


class RainPointProtocolTest(unittest.TestCase):
    def test_captured_fixtures(self) -> None:
        fixtures = json.loads(
            (ROOT / "rainpointd_addon" / "fixtures.json").read_text()
        )
        for fixture in fixtures:
            with self.subTest(fixture=fixture["name"]):
                actual = decode(fixture["frame"], fixture["model"])
                for key, expected in fixture["expected"].items():
                    self.assertEqual(expected, actual.get(key), key)

    def test_running_valve_tlv_types(self) -> None:
        entries = parse_tlv(
            "10#E1B900DC01D82120B724A0FC19AD58029F2E000000FF0FAA9CFC19"
        )
        self.assertEqual(
            [32, 31, 30, 2, 21, 19, 15, 54],
            [entry["type_code"] for entry in entries],
        )

    def test_rejects_bad_hex(self) -> None:
        with self.assertRaises(ValueError):
            decode("10#not-hex", "HCS026FRF")

    def test_rejects_unknown_model(self) -> None:
        with self.assertRaises(ValueError):
            decode("10#E1BA00DC01883AFF0F6C9CFC19", "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
