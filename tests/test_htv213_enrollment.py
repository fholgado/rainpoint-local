"""Normal enrollment recipe; no node, serial port or live RF access."""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rainpointd_addon"))
from rainpointd.htv213_enrollment import EnrollmentProfile, completed_association
from rainpointd import htv213_pairing
from rainpointd.htv213_control import ControlJournal
from rainpointd.storage import SQLiteEventStore
from research.pairing_native_transcripts import decode
from tests.test_valve_configuration import alter
import tempfile


class Htv213EnrollmentTest(unittest.TestCase):
    def setUp(self):
        self.profile = EnrollmentProfile(address=2, initial_center_hz=434351500,
                                         routine_center_hz=434241500, power_dbm=0)
        self.identity = dict(controller="a2446688", companion="22446688")
        events = json.loads((ROOT / "research/fixtures/htv213_stock_pairing_controls_20260928.json").read_text())["trials"][0]["events"]
        self.ack = next(e["frame"] for e in events if e["direction"] == "device" and decode(e["frame"]).command == 0xa0)
        self.report = next(e["frame"] for e in events if e["direction"] == "device" and decode(e["frame"]).command == 2)

    def test_discovery_command_needs_no_factory_or_research_inputs(self):
        command = self.profile.command(**self.identity)
        self.assertEqual(command["type"], "htv213_enrollment_start")
        self.assertNotIn("factory_endpoint", command)
        self.assertNotIn("dry_valve_confirmed", command)
        self.assertEqual(command["device_address"], 2)
        self.assertEqual(command["assigned_selector"], 11)
        self.assertEqual(command["notification_phase"], 2)
        self.assertEqual(command["reply_delay_us"], 49000)
        self.assertEqual(command["duration_seconds"], 120)
        self.assertEqual(command["controller_endpoint"], self.identity["controller"])
        self.assertEqual(command["companion_endpoint"], self.identity["companion"])

    def test_recipe_matches_existing_explicit_enrollment(self):
        normal = self.profile.command(**self.identity, duration_seconds=300)
        explicit = htv213_pairing.build_command({**normal, "factory_endpoint": "11556677",
            "dry_valve_confirmed": True}, **self.identity)
        ignored = {"type", "command_id", "local_clock", "factory_endpoint"}
        self.assertEqual({k: v for k, v in normal.items() if k not in ignored},
                         {k: v for k, v in explicit.items() if k not in ignored})
        self.assertEqual(explicit["type"], "htv213_pairing_start")
        self.assertEqual(explicit["factory_endpoint"], "11556677")

    def test_address_and_radio_calibration_are_supplied_not_installation_defaults(self):
        with self.assertRaises(TypeError):
            EnrollmentProfile()
        other = EnrollmentProfile(address=7, initial_center_hz=434391500, routine_center_hz=434281500)
        command = other.command(controller="aabbccdd", companion="2abbccdd")
        self.assertEqual(command["device_address"], 7)
        self.assertEqual(command["initial_center_hz"], 434391500)
        self.assertEqual(command["routine_center_hz"], 434281500)
        self.assertEqual(command["controller_endpoint"], "aabbccdd")
        self.assertEqual(command["companion_endpoint"], "2abbccdd")

    def test_bad_profile_or_derived_carrier_cannot_build_an_enrollment(self):
        for changes in ({"address": True}, {"address": 0}, {"address": 256},
                        {"selector": 0}, {"selector": 16}, {"timing_raw": 0},
                        {"notification_phase": 0}, {"notification_phase": 63}, {"notification_phase": 64},
                        {"reply_delay_us": 0}, {"notification_delay_ms": 0},
                        {"power_dbm": 8}, {"initial_center_hz": 433000000},
                        {"routine_center_hz": 435000001}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(self.profile, **changes).command(**self.identity)
        for duration in (True, 0, 9, 301):
            with self.assertRaises(ValueError):
                self.profile.command(**self.identity, duration_seconds=duration)

    def test_wrong_controller_relation_does_not_build_an_enrollment(self):
        for controller, companion in (("a2446689", "22446688"), ("80000000", "00000000")):
            with self.assertRaises(ValueError):
                self.profile.command(controller=controller, companion=companion)

    def test_explicit_research_admission_still_requires_dry_confirmation_and_target(self):
        normal = self.profile.command(**self.identity)
        for extras in ({"factory_endpoint": "11556677"}, {"dry_valve_confirmed": True},
                       {"factory_endpoint": "91556677", "dry_valve_confirmed": True}):
            with self.assertRaises(ValueError):
                htv213_pairing.build_command({**normal, **extras}, **self.identity)

    def test_local_clock_is_preserved_and_each_enrollment_has_its_own_id(self):
        # The already-local wall clock is not converted to UTC by this module.
        now = datetime(2026, 10, 3, 14, 5, 6, tzinfo=timezone.utc)
        one = self.profile.command(**self.identity, now=now)
        two = self.profile.command(**self.identity, now=now)
        self.assertEqual(one["local_clock"], "20261003140506")
        self.assertNotEqual(one["command_id"], two["command_id"])

    def completed(self):
        command = self.profile.command(**self.identity)
        # A synthetic terminal-status wrapper over real normalized frames.
        # Their historical ordering is not evidence of a completed local pair.
        status = dict(command_id=command["command_id"], state="observed",
            factory_endpoint="11556677", reports=3, settings_sent=3, plans_sent=3,
            notification_accepted=True, notification_ack_frame=self.ack,
            completion_frame=self.report)
        return command, status

    def test_completion_prepares_two_port_retained_configuration_and_ack_phase_seed(self):
        command, status = self.completed()
        result = completed_association(node_id="rp-001122334455", command=command, status=status)
        self.assertEqual(result["association_key"], "a2446688:91556677")
        config = result["configuration"]
        self.assertEqual(config["model"], "HTV213FRF")
        self.assertEqual(config["revision"], 2)
        self.assertEqual(len(config["ports"]), 2)
        self.assertTrue(all(port["empty_plan"] for port in config["ports"]))
        self.assertEqual(config["address"], 2)
        seed = result["control_seed"]
        self.assertEqual(seed["acknowledged_phase"], 2)
        self.assertEqual(seed["evidence_id"], command["command_id"])
        # Persisting the proposed seed reserves phase 3, not report phase 6.
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteEventStore(Path(directory) / "events.sqlite")
            try:
                journal = ControlJournal(store)
                key = journal.seed(**seed)
                self.assertEqual(journal.snapshot(key)["next_phase"], 3)
                self.assertEqual(store.valve_registry(), [])
            finally:
                store.close()

    def test_completion_rejects_incomplete_mismatched_or_boolean_masks(self):
        command, status = self.completed()
        for changes in ({"command_id": "00" * 16}, {"state": "armed"}, {"state": "failed"},
                        {"notification_accepted": 1}, {"notification_accepted": False},
                        {"reports": True}, {"reports": 1}, {"settings_sent": 1}, {"plans_sent": 1},
                        {"factory_endpoint": "00000000"}, {"factory_endpoint": "91556677"},
                        {"factory_endpoint": "11556678"}, {"notification_ack_frame": None},
                        {"completion_frame": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                completed_association(node_id="rp-001122334455", command=command, status={**status, **changes})

    def test_completion_requires_positive_full_phase_ack_and_native_port_report(self):
        command, status = self.completed()
        for ack in (alter(self.ack, phase=3), alter(self.ack, data=b"\x01"),
                    alter(self.ack, command=0xa1), alter(self.ack, data=b"\x00\x00")):
            with self.assertRaises(ValueError):
                completed_association(node_id="rp-001122334455", command=command,
                                      status={**status, "notification_ack_frame": ack})
        data = decode(self.report).data
        for index, value in ((0, 12), (2, 3), (3, 0x20), (10, 1), (13, 1)):
            wrong = bytearray(data); wrong[index] = value
            with self.assertRaises(ValueError):
                completed_association(node_id="rp-001122334455", command=command,
                                      status={**status, "completion_frame": alter(self.report, data=wrong)})
        for field in ("notification_ack_frame", "completion_frame"):
            wrong = bytearray.fromhex(status[field]); wrong[8] ^= 1
            with self.assertRaises(ValueError):
                completed_association(node_id="rp-001122334455", command=command,
                                      status={**status, field: alter(wrong.hex())})

    def test_completion_rejects_missing_identity_or_research_command(self):
        command, status = self.completed()
        for changes in ({"controller_endpoint": None}, {"companion_endpoint": None},
                        {"type": "htv213_pairing_start"}, {"command_id": ""},
                        {"notification_phase": 63}):
            with self.assertRaises(ValueError):
                completed_association(node_id="rp-001122334455", command={**command, **changes}, status=status)
