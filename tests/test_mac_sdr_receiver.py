from __future__ import annotations

import json
from pathlib import Path
import ssl
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from tools.mac_sdr_receiver import LiveForwarder, launch_agent, normalize_live_line, receiver_command, run
from rainpointd.esp32_network import ESP32NetworkServer
from rainpointd.gateway import Gateway
from rainpointd.secure_transport import server_context

FRAME = "79f4882f28b42d008f9ce580240784830701800544200000000000000000000000000000308a"
EVENT = {"time": "2026-09-12 17:00:00", "rows": [{"len": 304, "data": FRAME}]}


class MacSDRReceiverTest(unittest.TestCase):
    def test_command_is_receive_only_and_plist_contains_no_credentials(self):
        command = receiver_command({"rtl433_path": "/opt/homebrew/bin/rtl_433"})
        self.assertIn("json", command)
        self.assertNotIn("-S", command)
        self.assertNotIn("-r", command)
        agent = launch_agent(Path("/private/receiver.json"), Path(sys.executable))
        self.assertFalse(agent["KeepAlive"])
        self.assertNotIn("token", repr(agent))
        with self.assertRaises(ValueError):
            receiver_command({"rtl433_path": "relative"})

    def test_source_time_is_preserved_not_reinterpreted(self):
        record = normalize_live_line(json.dumps(EVENT).encode())
        self.assertEqual(EVENT["time"], record["source_time"])
        self.assertTrue(record["received_at"].endswith("+00:00"))
        self.assertEqual([FRAME], record["frames"])
        self.assertIsNone(normalize_live_line(b"not json"))
        self.assertIsNone(normalize_live_line(b"x" * 65537))

    def test_real_child_stops_at_budget_and_does_not_erase_evidence_on_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            config = {"output_directory": directory, "max_journal_bytes": 1024}
            command = [sys.executable, "-c", f"import json; [print(json.dumps({EVENT!r}), flush=True) for _ in range(20)]"]
            self.assertEqual("storage_full", run(config, command=command))
            journal = Path(directory) / "events.jsonl"
            body = journal.read_bytes()
            self.assertGreater(len(body), 0)
            self.assertLessEqual(len(body), 1024)
            self.assertEqual("storage_full", run(config, command=command))
            self.assertEqual(body, journal.read_bytes())
            self.assertEqual("storage_full", json.loads((Path(directory) / "status.json").read_text())["state"])

    def test_stop_terminates_silent_child(self):
        with tempfile.TemporaryDirectory() as directory:
            deadline = time.monotonic() + 0.5
            self.assertEqual("stopped", run({"output_directory": directory},
                stop=lambda: time.monotonic() >= deadline,
                command=[sys.executable, "-c", "import time; time.sleep(30)"]))

    def test_symlink_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "events.jsonl").symlink_to(Path(directory) / "other")
            with self.assertRaises(ValueError):
                run({"output_directory": directory}, stop=lambda: True)

    @unittest.skipUnless(hasattr(ssl.SSLContext, "set_psk_server_callback"), "TLS-PSK needs Python 3.13")
    def test_forwarder_authenticates_to_real_gateway_as_rx_only(self):
        node_id, token = "rp-112233445566", "a1" * 32
        with tempfile.TemporaryDirectory() as directory:
            token_file = Path(directory) / "receiver.key"
            token_file.write_text(token)
            token_file.chmod(0o600)
            gateway = Gateway(storage_path=str(Path(directory) / "gateway.sqlite3"))
            server = ESP32NetworkServer(gateway, host="127.0.0.1", port=0,
                node_tokens={node_id: token}, tls_context=server_context(lambda identity: token if identity == node_id else None))
            server.start()
            forwarder = LiveForwarder({"host": "127.0.0.1", "port": server.server_port,
                "node_id": node_id, "token_file": str(token_file)})
            try:
                forwarder.send_live(normalize_live_line(json.dumps(EVENT).encode()))
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    if gateway.nodes() and gateway.nodes()[0].get("received_frames") == 1:
                        break
                    time.sleep(.01)
                node = gateway.nodes()[0]
                self.assertEqual(1, forwarder.sent)
                self.assertEqual(1, node["received_frames"])
                self.assertTrue(node["transport_encrypted"])
                self.assertEqual(1, node["protocol_version"])
                self.assertEqual(["rx"], node["capabilities"])
                self.assertFalse(node["tx_armed"])
                self.assertFalse(gateway.pairing()["transmitter_available"])
            finally:
                forwarder.close()
                server.stop()
                gateway.close()

    def test_failed_forward_drops_without_replaying_or_leaking_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            token_file = Path(directory) / "receiver.key"
            token_file.write_text("a1" * 32)
            token_file.chmod(0o600)
            forwarder = LiveForwarder({"host": "127.0.0.1", "node_id": "rp-112233445566", "token_file": str(token_file)})
            record = normalize_live_line(json.dumps(EVENT).encode())
            with patch.object(forwarder, "_connect", side_effect=OSError("private detail")) as connect:
                forwarder.send_live(record)
                forwarder.send_live(record)
                self.assertEqual(1, connect.call_count)
            self.assertEqual(2, forwarder.dropped)
            self.assertEqual(0, forwarder.sent)


if __name__ == "__main__":
    unittest.main()
