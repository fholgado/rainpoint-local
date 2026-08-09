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

    def test_reception_quality_persists_and_invalid_endpoint_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(path))
            gateway.register(
                device_id="soil-test",
                name="Test Soil",
                model="HCS026FRF",
                state={"soil_moisture_percent": None},
            )
            gateway.observe_decoded(
                device_id="soil-test",
                name="Test Soil",
                model="HCS026FRF",
                frame="valid",
                observed_at="2026-08-08T12:00:00",
                state={
                    "soil_moisture_percent": 44,
                    "rf_endpoint": "aabbcc01",
                    "rf_endpoint_a": "11223344",
                    "rf_endpoint_b": "aabbcc01",
                    "rf_trailer_valid": True,
                    "rf_frame_accepted": True,
                },
            )
            gateway.observe_rf_frame(
                device_id="soil-test",
                frame="invalid",
                observed_at="2026-08-08T12:01:00",
                state={
                    "soil_moisture_percent": 4,
                    "rf_endpoint": "aabbcc00",
                    "rf_endpoint_a": "11223340",
                    "rf_endpoint_b": "aabbcc00",
                    "rf_trailer_valid": False,
                    "rf_frame_accepted": False,
                },
            )

            device = gateway.devices(now=datetime(2026, 8, 8, 12, 2))[0]
            self.assertEqual(44, device["state"]["soil_moisture_percent"])
            self.assertEqual("2026-08-08T12:00:00", device["observed_at"])
            self.assertEqual(50.0, device["rf_frame_success_percent"])
            self.assertEqual(1, device["valid_rf_frame_count"])
            self.assertEqual(1, device["invalid_rf_frame_count"])
            endpoints = {item["endpoint"] for item in gateway.endpoints()}
            self.assertIn("aabbcc01", endpoints)
            self.assertNotIn("aabbcc00", endpoints)
            self.assertNotIn("11223340", endpoints)
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(path))
            restored_device = restored.devices(
                now=datetime(2026, 8, 8, 12, 2)
            )[0]
            self.assertEqual(44, restored_device["state"]["soil_moisture_percent"])
            self.assertEqual(50.0, restored_device["rf_frame_success_percent"])
            restored.close()

    def test_legacy_rejected_observation_is_not_restored_or_counted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(path))
            gateway.observe_decoded(
                device_id="soil-test",
                name="Test Soil",
                model="HCS026FRF",
                frame="valid",
                observed_at="2026-08-08T12:00:00",
                state={
                    "soil_moisture_percent": 78,
                    "rf_endpoint": "aabbcc01",
                    "rf_trailer_valid": True,
                },
            )
            gateway.observe_decoded(
                device_id="soil-test",
                name="Test Soil",
                model="HCS026FRF",
                frame="corrupted",
                observed_at="2026-08-08T12:01:00",
                state={
                    "soil_moisture_percent": 14,
                    "rf_endpoint": "aabbcc00",
                    "rf_trailer_valid": False,
                },
            )
            gateway._store._connection.execute(
                "UPDATE device_metrics SET report_count = 2 "
                "WHERE device_id = 'soil-test'"
            )
            gateway._store._connection.execute(
                """
                INSERT INTO endpoints(
                    endpoint, first_seen, last_seen, frame_count,
                    last_frame
                ) VALUES ('aabbcc00', '2026-08-08T12:01:00',
                          '2026-08-08T12:01:00', 1, 'corrupted')
                """
            )
            gateway._store._connection.execute(
                "DELETE FROM storage_metadata WHERE key IN "
                "('device_metrics_version', 'endpoint_inventory_version')"
            )
            gateway._store._connection.commit()
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(path))
            device = restored.devices(now=datetime(2026, 8, 8, 12, 2))[0]
            self.assertEqual(78, device["state"]["soil_moisture_percent"])
            self.assertEqual("2026-08-08T12:00:00", device["observed_at"])
            self.assertEqual(1, device["report_count"])
            self.assertEqual(50.0, device["rf_frame_success_percent"])
            self.assertNotIn(
                "aabbcc00", {item["endpoint"] for item in restored.endpoints()}
            )
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

    def test_receive_only_learning_and_registry_persist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(
                transport="rtl433",
                storage_path=str(path),
                registry_token="test-token",
            )
            gateway.observe_rf_frame(
                frame="first",
                observed_at="2026-08-08T12:00:00+00:00",
                state={"rf_endpoint": "aabbcc01"},
            )
            session = gateway.start_learning(
                120, now=datetime.fromisoformat("2026-08-08T12:01:00+00:00")
            )
            self.assertTrue(session["active"])
            self.assertFalse(session["rf_pairing"])
            self.assertEqual([], session["new_endpoints"])

            gateway.observe_rf_frame(
                frame="second",
                observed_at="2026-08-08T12:01:30+00:00",
                state={"rf_endpoint": "aabbcc02"},
            )
            learning = gateway.learning(
                now=datetime.fromisoformat("2026-08-08T12:02:00+00:00")
            )
            self.assertEqual(
                ["aabbcc02"],
                [item["endpoint"] for item in learning["new_endpoints"]],
            )
            gateway.observe_rf_frame(
                frame="too-late",
                observed_at="2026-08-08T12:04:00+00:00",
                state={"rf_endpoint": "aabbccff"},
            )
            expired = gateway.learning(
                now=datetime.fromisoformat("2026-08-08T12:05:00+00:00")
            )
            self.assertFalse(expired["active"])
            self.assertEqual(
                ["aabbcc02"],
                [item["endpoint"] for item in expired["new_endpoints"]],
            )
            accepted = gateway.accept_endpoint(
                endpoint="AABBCC02",
                name="Test Moisture",
                model="HCS026FRF",
                area="Bench",
                now=datetime.fromisoformat("2026-08-08T12:02:00+00:00"),
            )
            self.assertEqual("local-aabbcc02", accepted["device_id"])
            self.assertTrue(gateway.registry_authorized("test-token"))
            self.assertFalse(gateway.registry_authorized("wrong"))
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(path))
            self.assertEqual("Test Moisture", restored.registry()[0]["name"])
            renamed = restored.update_registry_device(
                "local-aabbcc02", name="Patio Sensor"
            )
            self.assertEqual("Patio Sensor", renamed["name"])
            self.assertEqual("Bench", renamed["area"])
            forgotten = restored.forget_registry_device("local-aabbcc02")
            self.assertEqual("aabbcc02", forgotten["endpoint"])
            self.assertEqual([], restored.registry())
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
        self.assertEqual(0, info["node_count"])
        self.assertEqual([], self.get_json("/api/v1/nodes")["nodes"])

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

    def test_registry_writes_are_disabled_without_token(self) -> None:
        request = Request(
            f"{self.base}/api/v1/learning",
            data=b'{"duration_seconds":60}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as raised:
            urlopen(request, timeout=2)
        self.assertEqual(403, raised.exception.code)


class RegistryHTTPAPITest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        path = Path(self.temporary_directory.name) / "rainpoint.sqlite3"
        gateway = Gateway(storage_path=str(path), registry_token="test-token")
        gateway.observe_rf_frame(
            frame="observed",
            state={"rf_endpoint": "aabbcc03"},
        )
        self.server = create_server(gateway, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.server.gateway.close()
        self.thread.join(timeout=2)
        self.temporary_directory.cleanup()

    def post_json(
        self, path: str, payload: dict, *, token: str | None = "test-token"
    ) -> dict:
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            f"{self.base}{path}",
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            return json.load(response)

    def test_authenticated_registry_lifecycle_never_claims_rf_pairing(self) -> None:
        with self.assertRaises(HTTPError) as raised:
            self.post_json(
                "/api/v1/registry/accept",
                {
                    "endpoint": "aabbcc03",
                    "name": "Bench Sensor",
                    "model": "HCS026FRF",
                },
                token=None,
            )
        self.assertEqual(401, raised.exception.code)

        accepted = self.post_json(
            "/api/v1/registry/accept",
            {
                "endpoint": "aabbcc03",
                "name": "Bench Sensor",
                "model": "HCS026FRF",
            },
        )
        self.assertFalse(accepted["rf_paired"])
        device_id = accepted["device"]["device_id"]
        renamed = self.post_json(
            f"/api/v1/registry/{device_id}/rename", {"area": "Garden"}
        )
        self.assertEqual("Garden", renamed["device"]["area"])
        forgotten = self.post_json(
            f"/api/v1/registry/{device_id}/forget", {}
        )
        self.assertFalse(forgotten["rf_unpaired"])

    def test_learning_api_is_receive_only(self) -> None:
        result = self.post_json(
            "/api/v1/learning", {"duration_seconds": 60}
        )
        self.assertTrue(result["active"])
        self.assertFalse(result["rf_pairing"])


if __name__ == "__main__":
    unittest.main()
