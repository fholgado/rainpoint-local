"""Atomic enrollment epochs and standard pairing contract, with no live RF."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import threading
import asyncio
import time
import types
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import unittest
from unittest.mock import patch, AsyncMock

from tests import test_htv213_enrollment as recipe_fixture
from tests.test_htv213_pairing_gateway import NODE
from tests.test_valve_configuration import alter
from rainpointd import htv213_enrollment as enrollment, htv213_enrollment_flow as flow, htv213_owner as owner
from rainpointd.htv213_control import ControlJournal, KEY as CONTROL_KEY
from rainpointd.storage import SQLiteEventStore
from rainpointd.gateway import Gateway
from rainpointd.http import create_server
from tests import test_api_models as ha_contract
from tests import test_integration_migration as ha_source


class EnrollmentJournalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "events.sqlite"
        self.store = SQLiteEventStore(self.path); self.addCleanup(self.store.close)
        self.journal = enrollment.EnrollmentJournal(self.store)
        helper = recipe_fixture.Htv213EnrollmentTest(); helper.setUp()
        self.command, self.proof = helper.completed()
        self.key = "a2446688:91556677"

    def accepted(self, *, replacement_key=None):
        self.journal.begin(NODE, self.command, replacement_key=replacement_key)
        self.assertTrue(self.journal.observe(NODE, self.proof))

    def complete(self):
        return self.journal.complete(NODE, self.command["command_id"], name="Two outlets", area="Bench")

    def test_commit_saves_owner_configuration_phase_and_enrollment_together(self):
        self.accepted(); result = self.complete()
        self.assertEqual(self.journal.current()["state"], "complete")
        self.assertEqual(ControlJournal(self.store).snapshot(self.key)["next_phase"], 3)
        self.assertEqual(result["device_id"], "local-htv213-91556677")
        self.assertEqual(result["area"], "Bench")
        self.assertTrue(result["command"]["retained_rejoin_enabled"])
        self.assertEqual(result["ports"], {}, "no invented per-port freshness")
        self.assertEqual(self.store.valve_registry(), [])

    def test_configured_wait_survives_discovery_expiry_and_restart_without_commit(self):
        now = datetime.now(timezone.utc)
        self.journal.begin(NODE, self.command, now=now)
        waiting = {**self.proof, "state": "armed", "awaiting_confirmation": True, "completion_frame": ""}
        self.assertTrue(self.journal.observe(NODE, waiting, now=now + timedelta(seconds=30)))
        expires = self.journal.current(now)["expires_at"]
        self.journal.observe(NODE, waiting, now=now + timedelta(seconds=60))
        self.assertEqual(self.journal.current(now)["expires_at"], expires, "repeats cannot extend wait")
        reopened = SQLiteEventStore(self.path)
        try:
            journal = enrollment.EnrollmentJournal(reopened)
            later = now + timedelta(seconds=480)
            self.assertEqual(journal.current(later)["state"], "armed")
            self.assertTrue(journal.current(later)["awaiting_confirmation"])
            self.assertIsNone(reopened.metadata_value(owner.KEY))
            self.assertIsNone(reopened.metadata_value(CONTROL_KEY))
            self.assertTrue(journal.observe(NODE, self.proof, now=later))
            self.assertEqual(journal.current(later)["state"], "accepted")
        finally:
            reopened.close()

    def test_incomplete_wait_does_not_extend_discovery(self):
        now = datetime.now(timezone.utc)
        self.journal.begin(NODE, self.command, now=now)
        expires = self.journal.current(now)["expires_at"]
        for changes in ({"plans_sent": 1}, {"notification_accepted": False},
                        {"notification_ack_frame": ""}, {"awaiting_confirmation": False}):
            status = {**self.proof, "state": "armed", "awaiting_confirmation": True, **changes}
            self.journal.observe(NODE, status, now=now + timedelta(seconds=30))
            self.assertEqual(self.journal.current(now)["expires_at"], expires)
        self.assertEqual(self.journal.current(now + timedelta(seconds=480))["state"], "expired")

    def test_naming_replay_and_restart_cannot_reset_a_reserved_phase(self):
        self.accepted(); self.complete()
        journal = ControlJournal(self.store)
        journal.reserve(self.key, action="open", port=1, seconds=60)
        before = journal.snapshot(self.key)
        reopened = SQLiteEventStore(self.path)
        try:
            result = enrollment.EnrollmentJournal(reopened).complete(NODE, self.command["command_id"], name="Late request")
            self.assertEqual(result["name"], "Two outlets")
            self.assertEqual(ControlJournal(reopened).snapshot(self.key), before)
        finally:
            reopened.close()

    def test_incomplete_wrong_node_and_missing_rf_cannot_commit(self):
        self.journal.begin(NODE, self.command)
        self.assertFalse(self.journal.observe("rp-aabbccddeeff", self.proof))
        self.assertFalse(self.journal.observe(NODE, {**self.proof, "command_id": "bb" * 16}))
        with self.assertRaises(ValueError): self.complete()
        self.journal.observe(NODE, {**self.proof, "completion_frame": ""})
        self.assertEqual(self.journal.current()["state"], "failed")
        with self.assertRaises(ValueError): self.complete()
        self.assertIsNone(self.store.metadata_value(owner.KEY))
        self.assertIsNone(self.store.metadata_value(CONTROL_KEY))

    def test_statement_failure_rolls_back_all_three_records(self):
        self.accepted()
        before = self.store.metadata_value(enrollment.KEY)
        self.store._connection.execute("CREATE TEMP TRIGGER reject_owner BEFORE INSERT ON storage_metadata WHEN NEW.key='htv213_reply_owner_v1' BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
        self.store._connection.commit()
        with self.assertRaises(Exception): self.complete()
        self.assertEqual(self.store.metadata_value(enrollment.KEY), before)
        self.assertIsNone(self.store.metadata_value(owner.KEY))
        self.assertIsNone(self.store.metadata_value(CONTROL_KEY))
        self.store._connection.execute("DROP TRIGGER reject_owner")
        self.store._connection.commit()
        self.complete()

    def test_stale_snapshot_cannot_overwrite_owner_or_counter(self):
        data, _, _, expected = self.journal._load()
        self.store.save_htv213_owner('{"other":{"node_id":"rp-aabbccddeeff"}}')
        with self.assertRaises(RuntimeError):
            self.store.save_htv213_enrollment(expected, {enrollment.KEY: json.dumps(data)})
        self.assertIsNone(self.store.metadata_value(enrollment.KEY))

    def test_repair_requires_revocation_and_archives_old_commands(self):
        self.accepted(); old = self.complete()
        ControlJournal(self.store).reserve(self.key, action="open", port=1, seconds=60)
        prior = ControlJournal(self.store).snapshot(self.key)
        self.command = {**self.command, "command_id": "cd" * 16}
        self.proof = {**self.proof, "command_id": self.command["command_id"]}
        with self.assertRaises(ValueError):
            self.journal.begin(NODE, self.command, replacement_key=self.key)
        old.update(revoking=True, revoked=True)
        self.store.save_htv213_owner(json.dumps({self.key: old}))
        self.accepted(replacement_key=self.key); result = self.complete()
        self.assertEqual(result["device_id"], old["device_id"])
        self.assertEqual(ControlJournal(self.store).snapshot(self.key)["next_phase"], 3)
        self.assertEqual(self.journal.current()["replaced"]["control"], prior)
        before = ControlJournal(self.store).snapshot(self.key)
        self.assertFalse(self.journal.observe(NODE, {**self.proof, "command_id": old["enrollment_id"]}))
        self.assertEqual(ControlJournal(self.store).snapshot(self.key), before)

    def test_repair_target_mismatch_does_not_change_old_counter(self):
        self.accepted(); old = self.complete(); old.update(revoking=True, revoked=True)
        self.store.save_htv213_owner(json.dumps({self.key: old}))
        before = self.store.metadata_value(CONTROL_KEY)
        self.command = {**self.command, "command_id": "cd" * 16}
        self.journal.begin(NODE, self.command, replacement_key=self.key)
        proof = {**self.proof, "command_id": self.command["command_id"], "factory_endpoint": "11556678"}
        for key in ("notification_ack_frame", "completion_frame"):
            raw = bytearray.fromhex(proof[key]); raw[9:13] = bytes.fromhex("91556678")
            proof[key] = alter(raw.hex())
        self.journal.observe(NODE, proof)
        self.assertEqual(self.journal.current()["state"], "failed")
        self.assertEqual(self.store.metadata_value(CONTROL_KEY), before)

    def test_fresh_ui_discovery_can_repair_only_a_previously_revoked_owner(self):
        self.accepted(); old = self.complete(); old.update(revoking=True, revoked=True)
        self.store.save_htv213_owner(json.dumps({self.key: old}))
        self.command = {**self.command, "command_id": "cd" * 16}
        self.proof = {**self.proof, "command_id": self.command["command_id"]}
        self.accepted(); self.complete()
        self.assertEqual(self.journal.current()["replaced"]["owner"], old)

    def test_owner_revoked_after_begin_cannot_be_used_as_a_repair_shortcut(self):
        self.journal.begin(NODE, self.command)
        old = dict(node_id=NODE, revoking=True, revoked=True)
        self.store.save_htv213_owner(json.dumps({self.key: old}))
        self.journal.observe(NODE, self.proof)
        with self.assertRaises(ValueError): self.complete()
        self.assertIsNone(self.store.metadata_value(CONTROL_KEY))

    def test_no_duplicate_attempt_after_dispatch_failure_until_deadline(self):
        now = datetime.now(timezone.utc)
        self.journal.begin(NODE, self.command, now=now)
        self.journal.transition(NODE, self.command["command_id"], "dispatch_failed")
        other = {**self.command, "command_id": "cd" * 16}
        with self.assertRaises(ValueError): self.journal.begin(NODE, other, now=now)
        later = now + timedelta(seconds=self.command["duration_seconds"] + 6)
        self.journal.begin(NODE, other, now=later)
        self.assertFalse(self.journal.observe(NODE, self.proof, now=later))


class EnrollmentFlowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.gateway = Gateway(transport="network", storage_path=str(Path(self.temp.name) / "gateway.sqlite"), registry_token="test-token")
        self.addCleanup(self.gateway.close)
        self.gateway.register_radio_node(node_id=NODE, token="ab" * 32, name="Dry test", area=None)
        self.capabilities = ["rx", "sensor_pairing_tx", "configurable_rf_controller_identity", enrollment.CAPABILITY,
            owner.CAPABILITY, owner.REJOIN_CAPABILITY, "htv213_control_experiment", "htv213_pairing_experiment"]
        self.gateway.update_node(NODE, connected=True, authenticated=True, protocol_version=2, tx_armed=False, capabilities=self.capabilities)
        self.gateway.configure_htv213_radio(NODE, initial_center_hz=434351500, routine_center_hz=434241500)
        self.sent = []
        self.gateway.set_node_command_sender(lambda node, command: self.sent.append((node, copy.deepcopy(command))))
        helper = recipe_fixture.Htv213EnrollmentTest(); helper.setUp(); _, self.proof = helper.completed()

    def start(self):
        return self.gateway.start_pairing(node_id=NODE, profile_id=enrollment.PROFILE_ID)

    def accept(self):
        started = self.start()
        proof = {**self.proof, "command_id": started["command_id"]}
        for key in ("notification_ack_frame", "completion_frame"):
            raw = bytearray.fromhex(proof[key]); raw[5:9] = bytes.fromhex(self.gateway.rf_identity.controller_endpoint)
            proof[key] = alter(raw.hex())
        self.assertTrue(flow.observe(self.gateway, NODE, proof))
        return started

    def test_standard_start_progress_complete_uses_saved_profile_and_no_open(self):
        started = self.accept()
        self.assertEqual(self.gateway.pairing()["stage"], "valve_pairing_completed")
        self.assertEqual(self.gateway.pairing()["completed_endpoint"], "91556677")
        result = self.gateway.complete_pairing(endpoint="91556677", name="Two outlets", area="Bench")
        self.assertEqual(result["model"], "HTV213FRF")
        self.assertEqual(result["area"], "Bench")
        self.assertFalse(result["state"]["rf_control_enabled"])
        self.assertEqual([c["type"] for _, c in self.sent], ["htv213_enrollment_start", "htv213_owner_set"])
        key = self.gateway.rf_identity.controller_endpoint + ":91556677"
        self.assertEqual(ControlJournal(self.gateway._store).snapshot(key)["next_phase"], 3)
        self.assertFalse(self.gateway.pairing()["active"])
        self.assertEqual(self.sent[0][1]["device_address"], 2)
        self.assertNotIn("factory_endpoint", self.sent[0][1])
        self.assertEqual(started["active_profile_id"], enrollment.PROFILE_ID)

    def test_configured_wait_uses_native_ha_confirmation_stage(self):
        started = self.start()
        proof = {**self.proof, "command_id": started["command_id"],
                 "state": "armed", "awaiting_confirmation": True, "completion_frame": ""}
        raw = bytearray.fromhex(proof["notification_ack_frame"])
        raw[5:9] = bytes.fromhex(self.gateway.rf_identity.controller_endpoint)
        proof["notification_ack_frame"] = alter(raw.hex())
        self.assertTrue(flow.observe(self.gateway, NODE, proof))
        snapshot = self.gateway.pairing()
        self.assertTrue(snapshot["active"])
        self.assertEqual(snapshot["stage"], "waiting_for_terminal_confirmation")
        self.assertEqual(ha_contract.api_models.pairing_progress_action(snapshot), "confirm_device")
        self.assertIsNone(snapshot["completed_endpoint"])

    def test_menu_stays_hidden_until_model_qualification_not_per_user_experiments(self):
        profile = next(p for p in ha_contract.api_models.pairing_profiles(self.gateway.pairing()) if p.profile_id == enrollment.PROFILE_ID)
        self.assertFalse(profile.user_pairing_supported)
        self.assertEqual(profile.maximum_duration_seconds, 300)
        self.assertNotIn("dry_valve_confirmed", self.start())

    def test_no_calibration_old_firmware_and_unmanaged_or_owned_node_do_not_send(self):
        self.gateway._store.set_metadata_value(enrollment.KEY, '{"radios":{},"sessions":{},"current":null}')
        with self.assertRaisesRegex(ValueError, "calibration"): self.start()
        self.gateway.configure_htv213_radio(NODE, initial_center_hz=434351500, routine_center_hz=434241500)
        self.gateway.update_node(NODE, capabilities=["rx", "sensor_pairing_tx"])
        with self.assertRaises(ValueError): self.start()
        self.gateway.update_node(NODE, capabilities=self.capabilities)
        with patch.object(self.gateway._store, "ack_assignments", return_value=[{}]):
            with self.assertRaises(ValueError): self.start()
        self.assertEqual(self.sent, [])

    def test_cancel_is_scoped_and_waits_for_radio_terminal_not_transport_return(self):
        started = self.start()
        with self.assertRaises(ValueError): self.gateway.stop_pairing(command_id="old")
        self.gateway.stop_pairing(command_id=started["command_id"])
        self.gateway.stop_pairing(command_id=started["command_id"])
        self.assertEqual(len(self.sent), 2)
        with self.assertRaises(ValueError): self.start()
        flow.observe(self.gateway, NODE, dict(command_id=started["command_id"], state="disarmed"))
        self.assertFalse(self.gateway.pairing()["active"])
        self.start()

    def test_rejected_missing_proof_and_wrong_node_visible_to_progress(self):
        started = self.start()
        self.assertFalse(flow.observe(self.gateway, "rp-aabbccddeeff", self.proof))
        flow.observe(self.gateway, NODE, dict(command_id=started["command_id"], state="observed"))
        self.assertEqual(self.gateway.pairing()["stage"], "transmitter_failed")
        with self.assertRaises(ValueError):
            self.gateway.complete_pairing(endpoint="91556677", name="No proof")
        self.assertEqual(self.gateway._store.valve_registry(), [])

    def test_commit_failure_cannot_restore_owner_or_publish_device(self):
        self.accept(); before = copy.deepcopy(self.sent)
        with patch.object(self.gateway._store, "save_htv213_enrollment", side_effect=OSError):
            with self.assertRaises(OSError): self.gateway.complete_pairing(endpoint="91556677", name="Fail")
        self.assertEqual(self.sent, before)
        self.assertEqual(owner.records(self.gateway), {})
        self.assertEqual(self.gateway.devices(), [])

    def test_restart_restores_only_committed_owner_and_preserves_counter(self):
        self.accept(); self.gateway.complete_pairing(endpoint="91556677", name="Two outlets")
        key = self.gateway.rf_identity.controller_endpoint + ":91556677"
        before = ControlJournal(self.gateway._store).snapshot(key)
        self.sent.clear(); owner.restore(self.gateway, NODE)
        self.assertEqual([c["type"] for _, c in self.sent], ["htv213_owner_set"])
        self.assertEqual(ControlJournal(self.gateway._store).snapshot(key), before)

    def test_completed_http_naming_replay_does_not_send_configuration_or_reset_counter(self):
        self.accept(); result = self.gateway.complete_pairing(endpoint="91556677", name="Two outlets")
        key = self.gateway.rf_identity.controller_endpoint + ":91556677"
        ControlJournal(self.gateway._store).reserve(key, action="open", port=1, seconds=60)
        before = ControlJournal(self.gateway._store).snapshot(key)
        self.sent.clear()
        again = self.gateway.complete_pairing(endpoint="91556677", name="Late request")
        self.assertEqual(again["device_id"], result["device_id"])
        self.assertEqual(self.sent, [])
        self.assertEqual(ControlJournal(self.gateway._store).snapshot(key), before)

    def test_restart_retains_uncommitted_proof_and_never_replays_enrollment(self):
        started = self.accept()
        restarted = Gateway(transport="network", storage_path=str(Path(self.temp.name) / "gateway.sqlite"))
        try:
            sent = []; restarted.set_node_command_sender(lambda node, command: sent.append(command))
            restarted.update_node(NODE, connected=True, authenticated=True, protocol_version=2, tx_armed=False, capabilities=self.capabilities)
            progress = restarted.pairing()
            self.assertEqual(progress["command_id"], started["command_id"])
            self.assertEqual(progress["completed_endpoint"], "91556677")
            self.assertEqual(sent, [])
            self.assertFalse(ha_contract.api_models.pairing_is_finalizing(progress))
            restarted.complete_pairing(endpoint="91556677", name="Recovered review")
            self.assertEqual([c["type"] for c in sent], ["htv213_owner_set"])
        finally:
            restarted.close()

    def test_cancel_after_verified_completion_abandons_naming_without_rf(self):
        started = self.accept(); self.sent.clear()
        result = self.gateway.stop_pairing(command_id=started["command_id"])
        self.assertFalse(result["active"])
        self.assertEqual(self.sent, [])
        self.assertEqual(owner.records(self.gateway), {})
        self.start()

    def test_standard_http_pairing_requires_auth_and_contract_is_ha_parseable(self):
        server = create_server(self.gateway, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        url = f"http://127.0.0.1:{server.server_port}/api/v1/pairing/start"
        payload = json.dumps(dict(node_id=NODE, profile_id=enrollment.PROFILE_ID, duration_seconds=120)).encode()
        try:
            with self.assertRaises(HTTPError) as raised:
                urlopen(Request(url, data=payload, headers={"Content-Type": "application/json"}), timeout=2)
            self.assertEqual(raised.exception.code, 401); raised.exception.close()
            self.assertEqual(self.sent, [])
            with urlopen(Request(url, data=payload, headers={"Content-Type": "application/json", "Authorization": "Bearer test-token"}), timeout=2) as response:
                self.assertEqual(response.status, 201)
                started = json.load(response)
            self.assertIsNone(ha_contract.api_models.pairing_completed_endpoint(started))
            self.assertEqual(ha_contract.api_models.pairing_progress_action(started), "wait_for_device")
            self.assertEqual(started["active_profile_id"], enrollment.PROFILE_ID)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_ordinary_pairing_cannot_overlap_a_normal_htv213_attempt(self):
        self.start()
        with self.assertRaises(ValueError): self.gateway.start_pairing()

    def test_stale_control_receipt_after_repair_cannot_touch_new_epoch(self):
        from rainpointd import htv213_control_transport
        self.accept(); self.gateway.complete_pairing(endpoint="91556677", name="Two outlets")
        key = self.gateway.rf_identity.controller_endpoint + ":91556677"
        before = ControlJournal(self.gateway._store).snapshot(key)
        self.gateway._htv213_control_owner = (NODE, "old-command", key)
        htv213_control_transport.observe(self.gateway, NODE, dict(command_id="old-command", state="complete"))
        self.assertEqual(ControlJournal(self.gateway._store).snapshot(key), before)


class NativeEnrollmentProgressTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = EnrollmentFlowTest("test_menu_stays_hidden_until_model_qualification_not_per_user_experiments")
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)

    async def poll(self, progress):
        contract = ha_contract.api_models
        callback = ha_source._integration_function("config_flow.py", "_async_wait_for_device", dict(
            asyncio=asyncio, time=time, APIModelError=contract.APIModelError,
            pairing_completed_endpoint=contract.pairing_completed_endpoint,
            pairing_is_finalizing=contract.pairing_is_finalizing,
            pairing_progress_action=contract.pairing_progress_action,
            RainPointLocalCannotConnect=ConnectionError, RainPointLocalInvalidResponse=ValueError,
            RainPointLocalUnauthorized=PermissionError, RainPointLocalCommandRejected=RuntimeError))
        client = types.SimpleNamespace(pairing=AsyncMock(return_value=progress))
        ui = types.SimpleNamespace(_client=lambda: client, _pairing_command_id=progress["command_id"],
            _pairing_error=None, _paired_endpoint=None, _pairing_progress_action="wait_for_device",
            _pairing_deadline=time.monotonic() + 5)
        await callback(ui)
        return ui

    async def test_native_flow_advances_to_naming_only_with_terminal_rf_proof(self):
        self.fixture.accept()
        result = await self.poll(self.fixture.gateway.pairing())
        self.assertEqual(result._paired_endpoint, "91556677")
        self.assertIsNone(result._pairing_error)
        self.assertEqual([c["type"] for _, c in self.fixture.sent], ["htv213_enrollment_start"])

    async def test_native_flow_exposes_failed_completion_without_watering(self):
        started = self.fixture.start()
        flow.observe(self.fixture.gateway, NODE, dict(command_id=started["command_id"], state="observed"))
        result = await self.poll(self.fixture.gateway.pairing())
        self.assertEqual(result._pairing_error, "pairing_failed")
        self.assertIsNone(result._paired_endpoint)
        self.assertEqual([c["type"] for _, c in self.fixture.sent], ["htv213_enrollment_start"])
