"""Standalone collector uses the production TLS peer and no write endpoints."""
import json
from pathlib import Path
import tempfile
import threading
import unittest

from rainpointd.gateway import Gateway
from rainpointd.http import create_server
from rainpointd.secure_transport import server_context
from tools.reliability_soak import gateway_getter, ha_credentials


class CollectorTransportTests(unittest.TestCase):
    def test_real_tls_peer_and_read_only_allowlist(self):
        key = "42" * 32
        gateway = Gateway(registry_token=key)
        server = create_server(gateway, port=0, tls_context=server_context(
            lambda identity: key if identity == "management" else None))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            origin = f"https://127.0.0.1:{server.server_port}"
            getter = gateway_getter(origin, key)
            self.assertEqual([], getter("devices")["devices"])
            self.assertIn("events", getter("events?since=0"))
            for path in ("pairing/start", "devices/x/valve/open", "../auth", "events?since=0&other=1"):
                with self.assertRaises(ValueError):
                    getter(path)
            with self.assertRaises(OSError):
                gateway_getter(origin, "43" * 32)("devices")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            gateway.close()

    def test_requires_tls_origin_and_valid_credential(self):
        for base in ("http://localhost:8787", "https://x/api", "https://user:secret@x", "https://x?token=secret"):
            with self.assertRaises(ValueError):
                gateway_getter(base, "a" * 64)
        with self.assertRaises(ValueError):
            gateway_getter("https://localhost:8787", "short")

    def test_select_existing_ha_entry_without_modifying_file(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)
            path = config / ".storage/core.config_entries"
            path.parent.mkdir()
            source = json.dumps({"data": {"entries": [
                {"entry_id": entry, "domain": "rainpoint_local", "data": {
                    "host": "::1", "port": 8787, "registry_write_token": entry * 64}}
                for entry in ("a", "b")]}})
            path.write_text(source)
            with self.assertRaises(ValueError):
                ha_credentials(config, None)
            with self.assertRaises(ValueError):
                ha_credentials(config, "missing")
            self.assertEqual(("https://[::1]:8787", "a" * 64), ha_credentials(config, "a"))
            self.assertEqual(source, path.read_text())
