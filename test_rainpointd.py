#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "rainpointd_addon"))

from rainpointd.gateway import Gateway
from rainpointd.http import create_server
from rainpointd.replay import ReplayTransport, load_fixtures


class GatewayTest(unittest.TestCase):
    def test_replay_seeds_five_devices(self) -> None:
        gateway = Gateway()
        ReplayTransport(gateway, fixtures=load_fixtures()).seed()

        devices = gateway.devices()
        self.assertEqual(5, len(devices))
        valve = next(item for item in devices if item["device_id"] == "valve-1")
        self.assertEqual("idle", valve["state"]["valve_state"])
        right = next(
            item for item in devices if item["device_id"] == "soil-right-bed"
        )
        self.assertEqual(58, right["state"]["soil_moisture_percent"])
        self.assertEqual(6, len(gateway.events()))

    def test_events_support_cursor(self) -> None:
        gateway = Gateway()
        ReplayTransport(gateway).seed()
        self.assertEqual([5, 6], [e["event_id"] for e in gateway.events(since=4)])

    def test_transport_health(self) -> None:
        gateway = Gateway(transport="rtl433")
        self.assertEqual("ok", gateway.health()["status"])
        gateway.set_transport_status(False, "receiver disconnected")
        self.assertEqual(
            {
                "status": "error",
                "transport": "rtl433",
                "detail": "receiver disconnected",
            },
            gateway.health(),
        )

    def test_persistent_events_devices_and_endpoint_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(path))
            gateway.observe_rf_frame(
                frame="aa",
                observed_at="2026-08-06T12:35:44",
                state={
                    "rf_endpoint_a": "hub00001",
                    "rf_endpoint_b": "valve001",
                    "rf_message_type": 0x98,
                    "rf_rssi_db": -1.5,
                },
            )
            gateway.observe_decoded(
                device_id="soil-test",
                name="Test Soil",
                model="HCS026FRF",
                frame="bb",
                observed_at="2026-08-06T12:36:00",
                state={
                    "rf_endpoint": "sensor01",
                    "rf_endpoint_a": "hub00001",
                    "rf_endpoint_b": "sensor01",
                    "soil_moisture_percent": 44,
                },
            )
            self.assertEqual(2, gateway.info()["stored_event_count"])
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(path))
            self.assertEqual([1, 2], [e["event_id"] for e in restored.events()])
            self.assertEqual(44, restored.devices()[0]["state"]["soil_moisture_percent"])
            inventory = {item["endpoint"]: item for item in restored.endpoints()}
            self.assertEqual(2, inventory["hub00001"]["frame_count"])
            self.assertEqual(1, inventory["valve001"]["as_b_count"])
            self.assertEqual(1, inventory["sensor01"]["as_sensor_count"])
            event = restored.observe_rf_frame(frame="cc", state={})
            self.assertEqual(3, event["event_id"])
            restored.close()

    def test_restore_ignores_obsolete_auto_discovered_hcs026_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(path))
            gateway.observe_decoded(
                device_id="hcs026-b42d008f",
                name="RainPoint HCS026 b42d008f",
                model="HCS026FRF",
                frame="valve-response",
                state={
                    "rf_endpoint": "b42d008f",
                    "soil_moisture_percent": 60,
                },
            )
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(path))
            self.assertEqual([], restored.devices())
            self.assertEqual(1, len(restored.events()))
            restored.close()

    def test_persistent_report_metrics_and_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(path))
            for minute in (0, 2, 7):
                gateway.observe_decoded(
                    device_id="soil-test",
                    name="Test Soil",
                    model="HCS026FRF",
                    frame=f"frame-{minute}",
                    observed_at=f"2026-08-08T12:{minute:02d}:00",
                    state={"soil_moisture_percent": 44},
                )

            device = gateway.devices(now=datetime(2026, 8, 8, 12, 20))[0]
            self.assertEqual(3, device["report_count"])
            self.assertEqual(210, device["average_report_interval_seconds"])
            self.assertEqual(300, device["longest_report_gap_seconds"])
            self.assertEqual(780, device["report_age_seconds"])
            self.assertEqual(900, device["reporting_timeout_seconds"])
            self.assertTrue(device["reporting"])
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(path))
            stale = restored.devices(now=datetime(2026, 8, 8, 12, 23))[0]
            self.assertEqual(3, stale["report_count"])
            self.assertFalse(stale["reporting"])
            restored.close()

    def test_existing_database_metrics_are_backfilled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(path))
            gateway.observe_decoded(
                device_id="valve-1",
                name="Valve",
                model="HTV145FRF",
                frame="first",
                observed_at="2026-08-08T01:00:00",
                state={"is_watering": False},
            )
            gateway.observe_decoded(
                device_id="valve-1",
                name="Valve",
                model="HTV145FRF",
                frame="second",
                observed_at="2026-08-08T02:00:00",
                state={"is_watering": False},
            )
            gateway._store._connection.execute("DELETE FROM device_metrics")
            gateway._store._connection.commit()
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(path))
            device = restored.devices(now=datetime(2026, 8, 8, 7, 0))[0]
            self.assertEqual(2, device["report_count"])
            self.assertEqual(3600, device["average_report_interval_seconds"])
            self.assertEqual(21600, device["reporting_timeout_seconds"])
            self.assertTrue(device["reporting"])
            restored.close()


class HTTPAPITest(unittest.TestCase):
    def setUp(self) -> None:
        gateway = Gateway()
        ReplayTransport(gateway).seed()
        self.server = create_server(gateway, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def get_json(self, path: str) -> dict:
        with urlopen(f"{self.base}{path}", timeout=2) as response:
            return json.load(response)

    def test_info_and_devices(self) -> None:
        info = self.get_json("/api/v1/info")
        self.assertEqual("v1", info["api_version"])
        self.assertTrue(info["read_only"])
        self.assertEqual(5, info["device_count"])
        self.assertEqual(5, len(self.get_json("/api/v1/devices")["devices"]))
        self.assertEqual([], self.get_json("/api/v1/endpoints")["endpoints"])

    def test_event_cursor(self) -> None:
        result = self.get_json("/api/v1/events?since=5")
        self.assertEqual([6], [event["event_id"] for event in result["events"]])
        self.assertEqual(6, result["next_since"])

    def test_post_is_rejected(self) -> None:
        request = Request(
            f"{self.base}/api/v1/devices/valve-1/open",
            data=b"{}",
            method="POST",
        )
        with self.assertRaises(HTTPError) as raised:
            urlopen(request, timeout=2)
        self.assertEqual(405, raised.exception.code)

    def test_unhealthy_transport_returns_503(self) -> None:
        self.server.gateway.set_transport_status(False, "receiver disconnected")
        with self.assertRaises(HTTPError) as raised:
            urlopen(f"{self.base}/health", timeout=2)
        self.assertEqual(503, raised.exception.code)


if __name__ == "__main__":
    unittest.main()
