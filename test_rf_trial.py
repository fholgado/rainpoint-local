"""Tests for repeatable RF trial evidence analysis."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parent / "tools" / "rf_trial.py"
SPEC = importlib.util.spec_from_file_location("rf_trial", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def frame(source: str, destination: str, message: int) -> str:
    value = bytearray(38)
    value[:5] = bytes.fromhex("79f4882f28")
    value[5:9] = bytes.fromhex(source)
    value[9:13] = bytes.fromhex(destination)
    value[13] = message
    return value.hex()


class RFTrialTests(unittest.TestCase):
    def manifest(self) -> dict:
        return {
            "expected_factory_endpoint": "1bce0024",
            "expected_paired_endpoint": "9bce0024",
            "stock_gateway_state": "off_verified",
        }

    def test_successful_isolated_sensor_trial(self) -> None:
        events = [
            {"raw": frame("80000000", "1bce0024", 1)},
            {"raw": frame("b9840280", "9bce0024", 3)},
            {"raw": frame("b9840280", "9bce0024", 5)},
        ]
        report = MODULE.analyze_trial(self.manifest(), events)
        self.assertTrue(report["passed"])
        self.assertEqual(1, report["terminal_message_03_count"])

    def test_stock_gateway_traffic_fails_isolation(self) -> None:
        events = [
            {"raw": frame("80000000", "1bce0024", 1)},
            {"raw": frame("9bce0024", "39840280", 0x81)},
        ]
        report = MODULE.analyze_trial(self.manifest(), events)
        self.assertFalse(report["passed"])
        self.assertFalse(
            report["checks"]["known_stock_gateway_endpoint_silent"]
        )

    def test_authorized_local_reply_is_not_stock_gateway_traffic(self) -> None:
        manifest = self.manifest()
        manifest["rf_transmit_authorized"] = True
        events = [
            {"raw": frame("80000000", "1bce0024", 1)},
            {"raw": frame("9bce0024", "39840280", 0x81)},
            {"raw": frame("b9840280", "9bce0024", 3)},
        ]
        report = MODULE.analyze_trial(manifest, events)
        self.assertTrue(report["passed"])
        self.assertEqual(1, report["companion_reply_frame_count"])
        self.assertEqual(0, report["stock_gateway_frame_count"])

    def test_assigned_channel_must_be_echoed(self) -> None:
        manifest = self.manifest()
        manifest["assigned_channel"] = 5
        paired_message = bytearray.fromhex(frame("b9840280", "9bce0024", 1))
        paired_message[16] = 2
        paired_message[17] = 0xE5
        events = [
            {"raw": frame("80000000", "1bce0024", 1)},
            {"raw": paired_message.hex()},
            {"raw": frame("b9840280", "9bce0024", 3)},
        ]
        report = MODULE.analyze_trial(manifest, events)
        self.assertTrue(report["checks"]["assigned_channel_echoed"])
        self.assertEqual({"5": 1}, report["echoed_channel_counts"])

        manifest["assigned_channel"] = 4
        report = MODULE.analyze_trial(manifest, events)
        self.assertFalse(report["checks"]["assigned_channel_echoed"])
        self.assertFalse(report["passed"])

    def test_installed_valve_endpoint_is_not_stock_gateway_evidence(self) -> None:
        events = [
            {"raw": frame("80000000", "1bce0024", 1)},
            {"raw": frame("b9840280", "9bce0024", 3)},
            {"raw": frame("b9840280", "b42d008f", 0x15)},
        ]
        report = MODULE.analyze_trial(self.manifest(), events)
        self.assertTrue(report["passed"])
        self.assertEqual(0, report["stock_gateway_frame_count"])

    def test_valve_pairing_requires_more_than_one_unclassified_frame(self) -> None:
        manifest = {
            "kind": "valve_pairing",
            "expected_factory_endpoint": None,
            "expected_paired_endpoint": None,
            "stock_gateway_state": "on",
        }
        report = MODULE.analyze_trial(
            manifest, [{"raw": frame("01020304", "05060708", 1)}]
        )
        self.assertFalse(report["passed"])
        self.assertFalse(report["checks"]["bidirectional_valve_exchange_observed"])

    def test_valve_pairing_inventories_bidirectional_exchange(self) -> None:
        manifest = {
            "kind": "valve_pairing",
            "expected_factory_endpoint": None,
            "expected_paired_endpoint": None,
            "stock_gateway_state": "on",
        }
        report = MODULE.analyze_trial(
            manifest,
            [
                {"raw": frame("01020304", "05060708", 1)},
                {"raw": frame("05060708", "01020304", 3)},
            ],
        )
        self.assertTrue(report["passed"])
        self.assertEqual(["01020304<->05060708"], report["bidirectional_links"])


if __name__ == "__main__":
    unittest.main()
