#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "rainpointd_addon"))

from rainpointd.firmware_catalog import FirmwareCatalog
from rainpointd.gateway import Gateway
from rainpointd.http import create_server


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


if __name__ == "__main__":
    unittest.main()
