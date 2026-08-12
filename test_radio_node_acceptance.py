"""Tests for the read-only radio-node acceptance checker."""

from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path


MODULE_PATH = Path(__file__).parent / "tools" / "check_radio_node.py"
SPEC = importlib.util.spec_from_file_location("check_radio_node", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RadioNodeAcceptanceTests(unittest.TestCase):
    def snapshot(self) -> dict:
        return {
            "info": {"transport_healthy": True, "transport": "rtl433"},
            "nodes": {
                "nodes": [
                    {
                        "node_id": "rp-001122aabbcc",
                        "connected": True,
                        "authenticated": True,
                        "managed": True,
                        "protocol_version": 2,
                        "capabilities": ["rx", "sensor_pairing_tx"],
                        "tx_armed": False,
                        "last_seen": "2026-08-12T12:00:00+00:00",
                        "free_heap_bytes": 200_000,
                        "ip_address": "192.0.2.10",
                        "wifi_rssi_dbm": -60,
                        "radio_health": {
                            "primary": {"configuration_valid": True}
                        },
                    }
                ]
            },
            "receivers": {
                "receivers": [
                    {
                        "receiver_id": "rp-001122aabbcc",
                        "device_id": "sensor-1",
                        "accepted_frame_count": 4,
                    },
                    {
                        "receiver_id": "local-sdr",
                        "device_id": "sensor-1",
                        "accepted_frame_count": 3,
                    },
                ]
            },
        }

    def test_healthy_node_passes(self) -> None:
        report = MODULE.evaluate_node(
            self.snapshot(),
            "rp-001122aabbcc",
            now=datetime(2026, 8, 12, 12, 1, tzinfo=timezone.utc),
        )
        self.assertTrue(report["passed"])

    def test_armed_or_stale_node_fails(self) -> None:
        snapshot = self.snapshot()
        snapshot["nodes"]["nodes"][0]["tx_armed"] = True
        report = MODULE.evaluate_node(
            snapshot,
            "rp-001122aabbcc",
            now=datetime(2026, 8, 12, 12, 3, tzinfo=timezone.utc),
        )
        self.assertFalse(report["passed"])
        failures = {item["name"] for item in report["checks"] if not item["passed"]}
        self.assertEqual(failures, {"transmitter_disarmed", "fresh_heartbeat"})

    def test_unknown_node_fails_cleanly(self) -> None:
        report = MODULE.evaluate_node(self.snapshot(), "rp-ffffffffffff")
        self.assertFalse(report["passed"])
        self.assertIsNone(report["node"])


if __name__ == "__main__":
    unittest.main()
