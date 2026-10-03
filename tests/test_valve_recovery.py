"""Real SQLite/gateway recovery seams; fake transport never emits RF."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rainpointd_addon"))
from rainpointd.storage import SQLiteEventStore
from rainpointd.valve_recovery import ValveRecovery, KEY, CAPABILITY, configuration
from tests.support import CapturedInstallationGateway as Gateway
from research.pairing_native_transcripts import decode

NODE = "rp-001122334455"
OTHER = "rp-112233445566"


def config(model="HTV213FRF"):
    return dict(model=model, factory_endpoint="11556677", valve_endpoint="91556677",
                controller_endpoint="a2446688", node_id=NODE, selector=11, revision=2,
                address=7, timing_raw=480,
                ports=[dict(settings="58020a001e00" + "00" * 8, empty_plan=True)
                       for _ in range({"HTV213FRF": 2, "HTV405FRF": 4}[model])])


class FailCommit:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, *args):
        return self.connection.execute(*args)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.connection.rollback()
        raise sqlite3.OperationalError("simulated failed commit")


class ValveRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "events.sqlite3"
        self.store = SQLiteEventStore(self.path)
        self.addCleanup(lambda: self.store.close())
        self.nodes = {NODE: dict(connected=True, authenticated=True,
                                 connected_at="session-one", capabilities=[CAPABILITY])}
        self.sent = []
        self.block = None
        self.recovery = self.make()
        fixture = json.loads((ROOT / "research/fixtures/htv213_stock_lifecycle_20260928.json").read_text())
        self.events = fixture["trials"][-1]["events"]
        self.announcement = next(e["frame"] for e in self.events if decode(e["frame"]).command == 1)
        self.now = datetime.now(timezone.utc).isoformat()

    def make(self, profiles=None, sender=None):
        return ValveRecovery(self.store, self.nodes, lambda _: self.block,
                             sender or (lambda node, command: self.sent.append((node, command))),
                             profiles=profiles)

    def observe(self, frame=None, **kwargs):
        return self.recovery.observe(frame or self.announcement, kwargs.get("node", NODE),
                                     kwargs.get("at", self.now))

    def test_explicit_configuration_required_and_production_dispatch_is_gated(self):
        self.assertIsNone(self.observe())
        self.recovery.configure(config())
        result = self.observe()
        self.assertEqual(result["reason"], "assignment_profile_unqualified")
        self.assertEqual(self.sent, [])
        self.assertEqual(self.store.valve_registry(), [])  # Observations cannot enroll.

    def test_configuration_validation_cannot_invent_settings_or_plans(self):
        for field, value in (("revision", 0), ("selector", True), ("address", 0),
                             ("factory_endpoint", "91556677"), ("ports", [])):
            candidate = config()
            candidate[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.recovery.configure(candidate)
        for value in ({"settings": "00" * 14, "empty_plan": False},
                      {"settings": None, "empty_plan": True}):
            candidate = config()
            candidate["ports"][0] = value
            with self.assertRaises(ValueError):
                configuration(candidate)
        self.assertIsNone(self.store.metadata_value(KEY))

    def test_commit_failure_never_changes_ram_or_durable_configuration(self):
        self.recovery.configure(config())
        before = self.store.metadata_value(KEY)
        before_ram = copy.deepcopy(self.recovery.records)
        candidate = config()
        candidate["revision"] = 9
        with patch.object(self.store, "_connection", FailCommit(self.store._connection)):
            with self.assertRaises(sqlite3.OperationalError):
                self.recovery.configure(candidate)
        self.assertEqual(self.store.metadata_value(KEY), before)
        self.assertEqual(self.recovery.records, before_ram)
        self.assertEqual(self.make().records, before_ram)

    def test_journal_commit_failure_sends_nothing_and_cannot_claim_progress(self):
        self.recovery = self.make(profiles={"HTV213FRF": "test-only"})
        self.recovery.configure(config())
        before = copy.deepcopy(self.recovery.records)
        with patch.object(self.store, "_connection", FailCommit(self.store._connection)):
            with self.assertRaises(sqlite3.OperationalError):
                self.observe()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.recovery.records, before)

    def test_once_only_dispatch_survives_restart_and_transport_uncertainty(self):
        self.recovery = self.make(profiles={"HTV213FRF": "test-only"})
        self.recovery.configure(config())
        first = self.observe()
        self.assertEqual(first["state"], "requested")
        self.assertEqual(len(self.sent), 1)
        self.recovery = self.make(profiles={"HTV213FRF": "test-only"})
        self.assertEqual(self.observe(), first)
        self.assertEqual(len(self.sent), 1)
        # Journaled request is never replayed merely because a gateway restarts.
        self.assertEqual(self.sent[0][1]["configuration"]["address"], 7)
        self.assertEqual(self.sent[0][1]["configuration"]["revision"], 2)
        self.assertNotIn("sequence", self.sent[0][1])
        self.assertNotIn("pairing_start", self.sent[0][1].values())

    def test_lost_delivery_is_not_retried_inside_same_window(self):
        def lost(node, command):
            self.sent.append((node, command))
            raise ConnectionError("uncertain delivery")
        self.recovery = self.make(profiles={"HTV213FRF": "test-only"}, sender=lost)
        self.recovery.configure(config())
        self.assertEqual(self.observe()["state"], "delivery_unknown")
        self.observe()
        self.assertEqual(len(self.sent), 1)

    def test_wrong_owner_disconnected_owner_cleanup_and_new_session_block(self):
        self.recovery.configure(config())
        self.assertIsNone(self.observe(node=OTHER))
        self.nodes[NODE]["authenticated"] = False
        self.assertIsNone(self.observe())
        self.nodes[NODE]["authenticated"] = True
        self.block = "ownership_cleanup_pending"
        self.assertEqual(self.observe()["reason"], self.block)
        self.block = None
        self.observe()
        self.nodes[NODE]["connected_at"] = "session-two"
        self.assertEqual(self.observe()["state"], "interrupted")
        self.assertEqual(self.sent, [])

    def test_addressed_progress_never_claims_reply_acceptance_or_completion(self):
        self.recovery.configure(config())
        self.observe()
        for event in self.events:
            p = decode(event["frame"])
            if event["direction"] == "device" and p.command in (2, 5, 6):
                self.observe(event["frame"])
        progress = self.recovery.snapshot()[0]
        self.assertEqual(progress["progress"], dict(reports=[1, 2], settings=[1, 2], plans=[1, 2]))
        self.assertEqual(progress["state"], "addressed_progress")
        self.assertEqual(progress["reason"], "assignment_profile_unqualified")
        self.assertEqual(self.sent, [])
        before = self.store.metadata_value(KEY)
        self.observe(self.events[-2]["frame"])
        self.assertEqual(before, self.store.metadata_value(KEY))

    def test_corrupt_frame_stale_timestamp_and_expiry_do_not_dispatch(self):
        self.recovery = self.make(profiles={"HTV213FRF": "test-only"})
        self.recovery.configure(config())
        self.assertIsNone(self.observe(self.announcement[:-2] + "00"))
        self.assertIsNone(self.observe(at="not-a-time"))
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.assertEqual(self.observe(at=old)["reason"], "stale_observation")
        before = self.store.metadata_value(KEY)
        report = next(e["frame"] for e in self.events if decode(e["frame"]).command == 2)
        self.assertIsNone(self.observe(report))  # Old window expired.
        self.assertEqual(before, self.store.metadata_value(KEY))
        self.assertEqual(self.sent, [])


class ValveRecoveryGatewayTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name) / "gateway.sqlite3")
        self.gateway = Gateway(storage_path=self.path)
        self.addCleanup(lambda: self.gateway.close())
        self.now = datetime.now(timezone.utc).isoformat()
        store = self.gateway._store
        store.upsert_valve_link(controller_endpoint="a2446688", valve_endpoint="91556677",
            device_id="recovery-test", name="Test valve", model="HTV405FRF", area=None, accepted_at=self.now)
        store.update_valve_control_profile(valve_endpoint="91556677", node_id=NODE,
            companion_endpoint="22446688", selector=11, frequency_offset_hz=0, observed_at=self.now)
        self.gateway.update_node(NODE, connected=True, authenticated=True, connected_at="first", capabilities=[])
        self.before = copy.deepcopy(store.valve_registry())
        fixture = json.loads((ROOT / "research/fixtures/htv213_stock_lifecycle_20260928.json").read_text())
        # Synthetic reuse of a factory identity for gateway admission tests;
        # this is not claimed to be a physical HTV405 retained announcement.
        self.frame = next(e["frame"] for e in fixture["trials"][-1]["events"]
                          if decode(e["frame"]).command == 1)

    def test_real_ingestion_diagnostics_and_restart_preserve_registry_and_counters(self):
        self.gateway.configure_valve_recovery(config("HTV405FRF"))
        result = self.gateway.observe_rf_frame(frame=self.frame, state={"rf_node_id": NODE}, observed_at=self.now)
        self.assertEqual(result["state"]["valve_recovery"]["reason"], "assignment_profile_unqualified")
        self.assertEqual(self.gateway._store.valve_registry(), self.before)
        self.gateway.close()
        self.gateway = Gateway(storage_path=self.path)
        self.assertEqual(self.gateway._store.valve_registry(), self.before)
        self.assertEqual(self.gateway.valve_recovery_status()[0]["reason"], "assignment_profile_unqualified")

    def test_removal_suppression_and_owner_change_invalidate_saved_configuration(self):
        self.gateway.configure_valve_recovery(config("HTV405FRF"))
        self.gateway._store.assign_htv405_control_node(valve_endpoint="91556677", node_id=OTHER, observed_at=self.now)
        result = self.gateway.observe_rf_frame(frame=self.frame, state={"rf_node_id": NODE}, observed_at=self.now)
        self.assertEqual(result["state"]["valve_recovery"]["reason"], "owner_changed")
        self.gateway._store.forget_valve_registry_device("recovery-test", suppressed_at=self.now)
        self.assertEqual(self.gateway._valve_recovery_eligibility(config("HTV405FRF")), "device_suppressed")
        self.assertEqual(self.gateway._store.valve_registry(), [])
        self.assertEqual(self.gateway.valve_recovery_status(), [])
        self.gateway.close()
        self.gateway = Gateway(storage_path=self.path)
        self.assertEqual(self.gateway.valve_recovery_status(), [])

    def test_failed_removal_rolls_back_recovery_registry_and_suppression_together(self):
        self.gateway.configure_valve_recovery(config("HTV405FRF"))
        store = self.gateway._store
        retained = store.metadata_value(KEY)
        with patch.object(store, "_connection", FailCommit(store._connection)):
            with self.assertRaises(sqlite3.OperationalError):
                store.forget_valve_registry_device("recovery-test", suppressed_at=self.now)
        self.assertEqual(store.valve_registry(), self.before)
        self.assertEqual(store.metadata_value(KEY), retained)
        self.assertNotIn("91556677", store.suppressed_endpoints())
        self.assertEqual(len(self.gateway.valve_recovery_status()), 1)

    def test_removing_one_association_preserves_other_recovery_records(self):
        self.gateway.configure_valve_recovery(config("HTV405FRF"))
        store = self.gateway._store
        second = config("HTV405FRF")
        second.update(factory_endpoint="11556678", valve_endpoint="91556678")
        store.upsert_valve_link(controller_endpoint="a2446688", valve_endpoint="91556678",
            device_id="other-recovery-test", name="Other valve", model="HTV405FRF",
            area=None, accepted_at=self.now)
        store.update_valve_control_profile(valve_endpoint="91556678", node_id=NODE,
            companion_endpoint="22446688", selector=11, frequency_offset_hz=0,
            observed_at=self.now)
        self.gateway.configure_valve_recovery(second)
        other = self.gateway.valve_recovery_status()[1]
        store.forget_valve_registry_device("recovery-test", suppressed_at=self.now)
        self.assertEqual(self.gateway.valve_recovery_status(), [other])
