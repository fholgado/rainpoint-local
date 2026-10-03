"""Authenticated dry admission and journal evidence; fake node transport."""
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tests import test_htv213_pairing_gateway as pairing_fixture
from tests.test_htv213_pairing_gateway import NODE, request
from tests.test_valve_configuration import alter
from rainpointd import htv213_control_experiment as experiment
from rainpointd.htv213_control_trial import ControlJournal
from rainpointd.http import create_server

ROOT = Path(__file__).resolve().parents[1]


class Htv213ControlExperimentTest(unittest.TestCase):
    def setUp(self):
        pairing_fixture.Htv213PairingGatewayTest.setUp(self)
        self.gateway.update_node(NODE, capabilities=["htv213_pairing_experiment", experiment.CAPABILITY])
        self.request = {**request(), "port": 1, "seconds": 60, "acknowledged_phase": 2,
                        "pairing_evidence_id": "ab" * 16}
        fixture = json.loads((ROOT / "research/fixtures/htv213_stock_pairing_controls_20260928.json").read_text())
        self.events = next(t["events"] for t in fixture["trials"] if t["name"] == "zone1_auto60")

    def observe(self, status, event, node_state="open_confirmed"):
        raw = bytearray.fromhex(event["frame"])
        raw[5:9] = bytes.fromhex(self.gateway.rf_identity.controller_endpoint)
        experiment.observe(self.gateway, NODE, {"command_id": status["command_id"],
            "state": node_state, "frame": alter(raw.hex())})

    def test_explicit_unassigned_canary_only_and_no_valve_registration(self):
        result = experiment.start(self.gateway, self.request)
        self.assertFalse(result["operational"])
        command = self.sent[-1][1]
        self.assertEqual(command["type"], "htv213_control_probe_open")
        self.assertEqual((command["phase"], command["port"], command["seconds"]), (3, 1, 60))
        self.assertEqual(command["controller_endpoint"], self.gateway.rf_identity.controller_endpoint)
        self.assertEqual(self.gateway._store.valve_registry(), [])
        with self.assertRaises(ValueError): experiment.start(self.gateway, self.request)
        with self.assertRaises(ValueError): self.gateway.start_pairing()

    def test_old_firmware_owned_node_and_registered_valve_are_rejected(self):
        self.gateway.update_node(NODE, capabilities=["htv213_pairing_experiment"])
        with self.assertRaises(ValueError): experiment.start(self.gateway, self.request)
        self.gateway.update_node(NODE, capabilities=[experiment.CAPABILITY])
        with patch.object(self.gateway._store, "ack_assignments", return_value=[{}]):
            with self.assertRaises(ValueError): experiment.start(self.gateway, self.request)
        with patch.object(self.gateway._store, "valve_registry", return_value=[{"valve_endpoint": "91556677"}]):
            with self.assertRaises(ValueError): experiment.start(self.gateway, self.request)
        self.assertEqual(self.sent, [])

    def test_status_label_cannot_establish_acceptance_or_completion_without_rf(self):
        result = experiment.start(self.gateway, self.request)
        experiment.observe(self.gateway, NODE, {"command_id": result["command_id"], "state": "complete"})
        status = self.gateway._nodes[NODE]["htv213_control"]
        self.assertEqual(status["state"], "indeterminate")
        self.assertFalse(status["acknowledged"])
        with self.assertRaises(ValueError): experiment.start(self.gateway, self.request)

    def test_stock_rf_result_idle_and_summary_complete_journal(self):
        result = experiment.start(self.gateway, self.request)
        for event in self.events:
            if event["direction"] == "device":
                self.observe(result, event)
        status = self.gateway._nodes[NODE]["htv213_control"]
        self.assertEqual(status["state"], "complete")
        self.assertTrue(status["acknowledged"] and status["idle"] and status["summary"])
        self.assertFalse(status["operational"])

    def test_early_close_requires_correlated_confirmed_open(self):
        result = experiment.start(self.gateway, self.request)
        close = {"node_id": NODE, "open_command_id": result["command_id"], "port": 1,
                 "dry_valve_confirmed": True}
        with self.assertRaises(ValueError): experiment.close(self.gateway, close)
        self.observe(result, self.events[1])
        with self.assertRaises(ValueError): experiment.close(self.gateway, {**close, "port": 2})
        stopped = experiment.close(self.gateway, close)
        self.assertEqual(stopped["phase"], 4)
        self.assertEqual(self.sent[-1][1]["type"], "htv213_control_probe_close")
        self.assertEqual(self.sent[-1][1]["open_command_id"], result["command_id"])
        with self.assertRaises(ValueError): experiment.close(self.gateway, close)

    def test_transport_exception_reserves_phase_without_duplicate_attempt(self):
        self.gateway.set_node_command_sender(lambda *_: (_ for _ in ()).throw(ConnectionError()))
        with self.assertRaises(ConnectionError): experiment.start(self.gateway, self.request)
        key = self.gateway._htv213_control_owner[2]
        record = ControlJournal(self.gateway._store).snapshot(key)
        self.assertEqual((record["state"], record["next_phase"]), ("indeterminate", 4))
        with self.assertRaises(ValueError): experiment.start(self.gateway, self.request)

    def test_http_requires_authentication_and_dry_confirmation(self):
        server = create_server(self.gateway, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/api/v1/experiments/htv213/open"
            for token, body, expected in ((None, self.request, 401),
                    ("test-token", {**self.request, "dry_valve_confirmed": False}, 400)):
                headers = {"Content-Type": "application/json"}
                if token: headers["Authorization"] = "Bearer " + token
                with self.assertRaises(HTTPError) as raised:
                    urlopen(Request(url, data=json.dumps(body).encode(), headers=headers), timeout=2)
                self.assertEqual(raised.exception.code, expected); raised.exception.close()
            self.assertEqual(self.sent, [])
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_manual_crc_retrial_requires_new_canary_and_preserves_original_command(self):
        first = experiment.start(self.gateway, self.request)
        original = self.sent[-1][1].copy()
        proof = dict(prior_command_id=first["command_id"], evidence_sha256="cd" * 32,
                     authorization_id="ef" * 16)
        retry = {**self.request, "crc_retrial": proof}
        with self.assertRaises(ValueError): experiment.start(self.gateway, retry)
        experiment.observe(self.gateway, NODE, {"command_id": first["command_id"], "state": "overdue"})
        with self.assertRaises(ValueError): experiment.start(self.gateway, retry)
        self.gateway.update_node(NODE, firmware_version="0.19.0-htv213-control.2")
        second = experiment.start(self.gateway, retry)
        self.assertNotEqual(first["command_id"], second["command_id"])
        original["command_id"] = second["command_id"]
        self.assertEqual(self.sent[-1][1], original)
        experiment.observe(self.gateway, NODE, {"command_id": second["command_id"], "state": "overdue"})
        with self.assertRaises(ValueError): experiment.start(self.gateway, retry)
        self.assertEqual(len(self.sent), 2)
