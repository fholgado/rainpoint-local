#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import http.client
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rainpointd_addon"))
sys.path.insert(0, str(ROOT / "tools"))

from rainpointd.firmware_catalog import FirmwareCatalog
from rainpointd.gateway import Gateway
from rainpointd.http import create_server
from rainpointd import http as gateway_http
from stage_firmware_release import stage_release


class FirmwareCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.artifact = self.root / "radio-node-0.9.0-test.3.bin"
        self.content = b"firmware" * 8192
        self.artifact.write_bytes(self.content)
        self.catalog_path = self.root / "catalog.json"
        self.catalog_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "releases": [
                        {
                            "release_id": "esp32dev-ota-0.9.0-test.3",
                            "version": "0.9.0-test.3",
                            "channel": "experimental",
                            "hardware_profile": "esp32dev-cc1101-v1",
                            "firmware_variant": "unified",
                            "compatible_variants": ["pairing-ota", "unified"],
                            "required_capability": "firmware_update_trial",
                            "artifact": self.artifact.name,
                            "size_bytes": len(self.content),
                            "sha256": hashlib.sha256(self.content).hexdigest(),
                            "release_summary": "Experimental OTA UI trial",
                            "release_notes": "Validates managed local updates.",
                            "release_url": "https://example.com/release",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_catalog_matches_trial_node_and_rejects_tampering(self) -> None:
        catalog = FirmwareCatalog.load(self.catalog_path)
        node = {
            "firmware_version": "0.9.0-test.2",
            "capabilities": ["rx", "firmware_update_trial"],
        }
        release = catalog.latest_for_node(node)
        self.assertIsNotNone(release)
        assert release is not None
        self.assertTrue(release["update_available"])
        self.assertTrue(release["artifact_ready"])
        self.artifact.write_bytes(self.content + b"tampered")
        self.assertFalse(catalog.artifact_ready(release["release_id"]))

    def test_newer_research_variant_is_not_offered_to_unified_node(self) -> None:
        research_artifact = self.root / "radio-node-1.0.0-probe.bin"
        research_artifact.write_bytes(self.content)
        payload = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        payload["releases"].append(
            {
                "release_id": "esp32dev-ota-1.0.0-probe",
                "version": "1.0.0-probe.1",
                "channel": "experimental",
                "hardware_profile": "esp32dev-cc1101-v1",
                "firmware_variant": "htv145-pairing-probe",
                "compatible_variants": ["htv145-pairing-probe"],
                "required_capability": "firmware_update_trial",
                "artifact": research_artifact.name,
                "size_bytes": len(self.content),
                "sha256": hashlib.sha256(self.content).hexdigest(),
                "release_summary": "Research-only pairing probe",
                "release_notes": "Must not reach unified nodes.",
            }
        )
        self.catalog_path.write_text(json.dumps(payload), encoding="utf-8")

        catalog = FirmwareCatalog.load(self.catalog_path)
        release = catalog.latest_for_node(
            {
                "firmware_version": "0.9.0-test.2",
                "firmware_variant": "unified",
                "firmware_channel": "experimental",
                "hardware_profile": "esp32dev-cc1101-v1",
                "capabilities": ["rx", "firmware_update_trial"],
            }
        )
        self.assertIsNotNone(release)
        assert release is not None
        self.assertEqual("esp32dev-ota-0.9.0-test.3", release["release_id"])

    def test_staging_refuses_catalog_overflow_before_writing_artifact(
        self,
    ) -> None:
        destination = self.root / "bounded"
        destination.mkdir()
        releases = [
            {
                "release_id": f"old-probe-{index:02d}",
                "channel": "experimental",
                "hardware_profile": "esp32dev-cc1101-v1",
                "firmware_variant": "htv145-pairing-probe",
            }
            for index in range(32)
        ]
        original_catalog = {
            "schema_version": 1,
            "releases": releases,
        }
        catalog_path = destination / "catalog.json"
        catalog_path.write_text(json.dumps(original_catalog), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "exceed 32 releases"):
            stage_release(
                self.artifact,
                destination,
                release_id="new-probe",
                version="1.0.0-probe.23",
                summary="Corrected PHY",
                notes="Bounded test release",
                firmware_variant="htv145-pairing-probe",
            )

        self.assertFalse((destination / "new-probe.bin").exists())
        self.assertEqual(
            original_catalog,
            json.loads(catalog_path.read_text(encoding="utf-8")),
        )

    def test_staging_can_explicitly_supersede_same_variant_release(self) -> None:
        destination = self.root / "supersede"
        destination.mkdir()
        releases = [
            {
                "release_id": f"old-probe-{index:02d}",
                "channel": "experimental",
                "hardware_profile": "esp32dev-cc1101-v1",
                "firmware_variant": "htv145-pairing-probe",
            }
            for index in range(32)
        ]
        catalog_path = destination / "catalog.json"
        catalog_path.write_text(
            json.dumps({"schema_version": 1, "releases": releases}),
            encoding="utf-8",
        )

        release = stage_release(
            self.artifact,
            destination,
            release_id="new-probe",
            version="1.0.0-probe.23",
            summary="Corrected PHY",
            notes="Bounded test release",
            firmware_variant="htv145-pairing-probe",
            supersede_release_ids=["old-probe-31"],
        )

        staged = json.loads(catalog_path.read_text(encoding="utf-8"))
        self.assertEqual(32, len(staged["releases"]))
        self.assertNotIn(
            "old-probe-31",
            {item["release_id"] for item in staged["releases"]},
        )
        self.assertEqual(["old-probe-31"], release["supersedes"])
        self.assertTrue((destination / "new-probe.bin").exists())

    def test_gateway_installs_by_release_id_and_serves_verified_artifact(
        self,
    ) -> None:
        commands: list[tuple[str, dict]] = []
        gateway = Gateway(
            firmware_catalog=FirmwareCatalog.load(self.catalog_path)
        )
        node_id = "rp-001122334455"
        gateway.update_node(
            node_id,
            connected=True,
            authenticated=True,
            firmware_version="0.9.0-test.2",
            capabilities=["rx", "sensor_pairing_tx", "firmware_update_trial"],
            tx_armed=False,
            hardware_profile="esp32dev-cc1101-v1",
            firmware_variant="pairing-ota",
            firmware_channel="experimental",
            gateway_host="192.0.2.10",
        )
        gateway.set_node_command_sender(
            lambda target, command: commands.append((target, command))
        )
        result = gateway.install_radio_node_firmware_release(
            node_id, release_id="esp32dev-ota-0.9.0-test.3"
        )
        self.assertEqual("requested", result["state"])
        self.assertEqual(
            "http://192.0.2.10:8787/firmware/esp32dev-ota-0.9.0-test.3.bin",
            commands[0][1]["url"],
        )

        server = create_server(gateway, port=0)
        import threading

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(
                f"http://127.0.0.1:{server.server_port}/firmware/"
                "esp32dev-ota-0.9.0-test.3.bin",
                timeout=2,
            ) as response:
                self.assertEqual(self.content, response.read())
                self.assertEqual(
                    f'"sha256:{hashlib.sha256(self.content).hexdigest()}"',
                    response.headers["ETag"],
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            gateway.close()

    def test_firmware_stream_allows_slow_progress_beyond_api_timeout(self):
        """An OTA reader writing flash must not share JSON's total-write budget."""
        self.content = b"firmware" * 131072
        self.artifact.write_bytes(self.content)
        payload = json.loads(self.catalog_path.read_text())
        payload["releases"][0].update(
            size_bytes=len(self.content),
            sha256=hashlib.sha256(self.content).hexdigest(),
        )
        self.catalog_path.write_text(json.dumps(payload))
        gateway = Gateway(firmware_catalog=FirmwareCatalog.load(self.catalog_path))
        server = create_server(gateway, port=0)
        accept = server.get_request

        def constrained_connection():
            client, address = accept()
            client.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 32768)
            client.settimeout(0.25)
            return client, address

        server.get_request = constrained_connection
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        try:
            with patch.object(gateway_http, "FIRMWARE_PROGRESS_TIMEOUT_SECONDS", 1), \
                 patch.object(gateway_http, "FIRMWARE_TRANSFER_TIMEOUT_SECONDS", 10):
                thread.start()
                connection.connect()
                connection.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 32768)
                connection.request("GET", "/firmware/esp32dev-ota-0.9.0-test.3.bin")
                response = connection.getresponse()
                received = bytearray()
                started = time.monotonic()
                while chunk := response.read(8192):
                    received.extend(chunk)
                    time.sleep(0.015)
                self.assertGreater(time.monotonic() - started, 0.25)
                self.assertEqual(len(self.content), len(received))
                self.assertEqual(
                    hashlib.sha256(self.content).digest(),
                    hashlib.sha256(received).digest(),
                )
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            gateway.close()

    def test_firmware_stream_bounds_and_restores_socket_timeout(self):
        for mode in ("success", "stall", "deadline", "disconnect", "short_write"):
            with self.subTest(mode=mode):
                handler = object.__new__(gateway_http.RequestHandler)
                handler.connection = Mock()
                handler.connection.gettimeout.return_value = 10
                handler.wfile = Mock()
                handler.close_connection = False
                handler.wfile.write.side_effect = lambda chunk: len(chunk)
                times = [0, 0, 1, 2]
                if mode == "stall":
                    handler.wfile.write.side_effect = TimeoutError()
                elif mode == "disconnect":
                    handler.wfile.write.side_effect = BrokenPipeError()
                elif mode == "short_write":
                    handler.wfile.write.side_effect = lambda chunk: len(chunk) - 1
                elif mode == "deadline":
                    times = [0, 0, 121, 121]
                with patch.object(gateway_http.time, "monotonic", side_effect=times), \
                     patch.object(gateway_http._LOGGER, "warning") as warning:
                    handler._write_firmware(b"x" * 32768, "test-release")
                handler.connection.settimeout.assert_called_with(10)
                self.assertEqual(mode != "success", handler.close_connection)
                if mode == "success":
                    warning.assert_not_called()
                    self.assertEqual(2, handler.wfile.write.call_count)
                else:
                    warning.assert_called_once()
                    self.assertEqual(1, handler.wfile.write.call_count)
                if mode == "deadline":
                    self.assertEqual("transfer_deadline", warning.call_args.args[-1])
                elif mode == "stall":
                    self.assertEqual("progress_timeout", warning.call_args.args[-1])

    def test_firmware_capacity_preserves_api_access_and_releases_slots(self):
        gateway = Gateway(firmware_catalog=FirmwareCatalog.load(self.catalog_path))
        server = create_server(gateway, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        try:
            thread.start()
            # Simulate two active downloads without extending the test duration.
            self.assertTrue(server._firmware_slots.acquire(blocking=False))
            self.assertTrue(server._firmware_slots.acquire(blocking=False))
            connection.request("GET", "/firmware/esp32dev-ota-0.9.0-test.3.bin")
            response = connection.getresponse()
            self.assertEqual(503, response.status)
            response.read()
            connection.request("GET", "/api/v1/firmware/releases")
            response = connection.getresponse()
            self.assertEqual(200, response.status)
            response.read()
            server._firmware_slots.release()
            server._firmware_slots.release()
            # Errors and successful transfers both return the capacity permit.
            for path, status in (("missing", 404), ("esp32dev-ota-0.9.0-test.3", 200)):
                connection.request("GET", f"/firmware/{path}.bin")
                response = connection.getresponse()
                self.assertEqual(status, response.status)
                response.read()
            for _ in range(2):
                self.assertTrue(server._firmware_slots.acquire(timeout=1))
            self.assertFalse(server._firmware_slots.acquire(blocking=False))
            for _ in range(2):
                server._firmware_slots.release()
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            gateway.close()


if __name__ == "__main__":
    unittest.main()
