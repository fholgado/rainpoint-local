#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "rainpointd_addon"))

from rainpoint_protocol import decode, parse_tlv  # noqa: E402
from rainpointd.rf import normalize_row  # noqa: E402
from rainpointd.valve_protocol import (  # noqa: E402
    ValveLink,
    decode_htv145_command_response,
    decode_htv145_gateway_command,
    decode_htv145_state_report,
)


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

    def test_hcs026_cloud_and_rf_correlation_fixture(self) -> None:
        fixture = json.loads(
            (
                ROOT
                / "research"
                / "fixtures"
                / "hcs026_cloud_rf_correlation_20260824.json"
            ).read_text()
        )

        for observation in fixture["observations"]:
            with self.subTest(sensor=observation["sensor"]):
                cloud = decode(observation["cloud"]["payload"], "HCS026FRF")
                rf_frame = observation["rf"]["frame"]
                rf = normalize_row(
                    {"len": len(rf_frame) * 4, "data": rf_frame}
                )

                expected = observation["expected"]
                self.assertEqual(
                    expected["soil_moisture_percent"],
                    cloud["soil_moisture_percent"],
                )
                self.assertEqual(
                    expected["soil_moisture_percent"],
                    rf["soil_moisture_percent"],
                )
                self.assertEqual(
                    expected["battery_percent"], cloud["battery_percent"]
                )
                self.assertEqual(
                    expected["battery_percent"], rf["battery_percent"]
                )
                self.assertEqual(
                    expected["cloud_rssi_dbm"], cloud["rssi_dbm"]
                )
                self.assertTrue(rf["trailer_valid"])

    def test_htv145_cloud_battery_and_usage_correlation_fixture(self) -> None:
        fixture = json.loads(
            (
                ROOT
                / "research"
                / "fixtures"
                / "htv145_cloud_rf_battery_usage_correlation_20260824.json"
            ).read_text()
        )

        for observation in fixture["observations"]:
            with self.subTest(event=observation["rf_event_id"]):
                cloud = decode(observation["cloud_payload"], "HTV145FRF")
                expected = observation["expected"]
                self.assertEqual(
                    expected["battery_status"], cloud["battery_status"]
                )
                self.assertEqual(
                    expected["battery_percent"], cloud["battery_percent"]
                )
                self.assertEqual(
                    expected["last_usage_liters"], cloud["last_usage_liters"]
                )
                self.assertFalse(cloud["is_watering"])
                rf_frame = observation["rf_frame"]
                rf = normalize_row(
                    {"len": len(rf_frame) * 4, "data": rf_frame}
                )
                self.assertFalse(rf["is_watering"])
                self.assertEqual("idle", rf["valve_state"])

    def test_htv145_terminal_summary_correlation_fixture(self) -> None:
        fixture = json.loads(
            (
                ROOT
                / "research"
                / "fixtures"
                / "htv145_cloud_rf_terminal_summary_correlation_20260824.json"
            ).read_text()
        )

        for observation in fixture["observations"]:
            with self.subTest(event=observation["rf_event_id"]):
                expected = observation["expected"]
                cloud = decode(observation["cloud_payload"], "HTV145FRF")
                rf_frame = observation["rf_frame"]
                rf = normalize_row(
                    {"len": len(rf_frame) * 4, "data": rf_frame}
                )
                self.assertEqual(
                    expected["last_usage_liters"],
                    cloud["last_usage_liters"],
                )
                self.assertEqual(
                    expected["last_usage_liters"],
                    rf["last_usage_liters"],
                )
                self.assertEqual(
                    expected["duration_seconds"],
                    rf["duration_seconds"],
                )
                self.assertEqual(
                    expected["is_watering"], cloud["is_watering"]
                )
                self.assertEqual(
                    expected["is_watering"], rf["is_watering"]
                )
                self.assertEqual("idle", rf["valve_state"])
                self.assertTrue(rf["trailer_valid"])
                self.assertNotIn("battery_status", rf)
                self.assertNotIn("battery_percent", rf)

    def test_htv145_stock_command_counter_fixture(self) -> None:
        fixture = json.loads(
            (
                ROOT
                / "research"
                / "fixtures"
                / "htv145_stock_command_counter_20260824.json"
            ).read_text()
        )
        link = ValveLink(
            bytes.fromhex("b42d008f"), bytes.fromhex("b9840280")
        )
        for transaction in fixture["transactions"]:
            frames = {
                item["role"]: bytes.fromhex(item["raw"])
                for item in transaction["frames"]
            }
            requests = [
                frame
                for role, frame in frames.items()
                if role.startswith("open_request")
            ]
            for request in requests:
                decoded = decode_htv145_gateway_command(request, link)
                self.assertIsNotNone(decoded)
                self.assertEqual(
                    transaction["requested_duration_seconds"],
                    decoded["duration_seconds"],
                )
            if len(requests) > 1:
                self.assertEqual(1, len(set(requests)))
            response = frames.get("immediate_open_response")
            if response is not None:
                decoded_response = decode_htv145_command_response(
                    response, link
                )
                self.assertIsNotNone(decoded_response)
                self.assertEqual(
                    int(transaction["command_sequence"], 16),
                    decoded_response["sequence"],
                )
            corrupted = frames.get("corrupted_response_candidate")
            if corrupted is not None:
                self.assertIsNone(
                    decode_htv145_command_response(corrupted, link)
                )
            report = decode_htv145_state_report(
                frames["watering_state_confirmation"], link
            )
            self.assertIsNotNone(report)
            self.assertTrue(report["watering"])
            self.assertNotEqual(
                int(transaction["command_sequence"], 16),
                report["telemetry_sequence"],
            )

    def test_rejects_bad_hex(self) -> None:
        with self.assertRaises(ValueError):
            decode("10#not-hex", "HCS026FRF")

    def test_rejects_unknown_model(self) -> None:
        with self.assertRaises(ValueError):
            decode("10#E1BA00DC01883AFF0F6C9CFC19", "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
