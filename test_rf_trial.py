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
            {"raw": frame("b42d008f", "9bce0024", 3)},
        ]
        report = MODULE.analyze_trial(self.manifest(), events)
        self.assertFalse(report["passed"])
        self.assertFalse(
            report["checks"]["known_stock_gateway_endpoint_silent"]
        )

    def test_valve_baseline_does_not_require_unknown_identities(self) -> None:
        manifest = {
            "expected_factory_endpoint": None,
            "expected_paired_endpoint": None,
            "stock_gateway_state": "on",
        }
        report = MODULE.analyze_trial(
            manifest, [{"raw": frame("01020304", "05060708", 1)}]
        )
        self.assertTrue(report["passed"])


if __name__ == "__main__":
    unittest.main()
