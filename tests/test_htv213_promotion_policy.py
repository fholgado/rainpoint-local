"""Normal model slot/phase policy; no hardware or live database access."""
import copy
import json
from pathlib import Path
import re
import unittest
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tests import test_htv213_enrollment_journal as enrollment_tests
from tests import test_htv213_control_core as control_tests
from rainpointd import htv213_enrollment as enrollment
from rainpointd.htv213_control import KEY, MODEL_PHASE_POLICY, wraps
from rainpointd.valve_recovery import KEY as RECOVERY_KEY
from rainpointd.valve_pairing_protocol import HTV145_STEPS, HTV405_STEPS
from rainpointd.http import create_server

ROOT = Path(__file__).resolve().parents[1]


class EnrollmentSlotTest(unittest.TestCase):
    def setUp(self):
        self.fixture = enrollment_tests.EnrollmentJournalTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.journal, self.store = self.fixture.journal, self.fixture.store
        self.controller = self.fixture.command["controller_endpoint"]

    def owner(self, *, address=2):
        self.fixture.command["device_address"] = address
        self.fixture.accepted()
        return self.fixture.complete()

    def test_legacy_slots_match_the_frozen_assignment_bytes(self):
        addresses = set()
        for steps in (HTV145_STEPS, HTV405_STEPS):
            body = steps[0].reply_body
            addresses.add(((body[4] << 1) | (body[5] >> 7)) & 255)
        # Check the actual firmware HCS026 template, not a new guessed sensor
        # address derived from its RF selector or app device count.
        source = (ROOT / "firmware/rainpoint_bridge/include/rainpoint_pairing.h").read_text()
        template = source.split("constexpr PairingProfile kHcs026PairingTemplate =", 1)[1]
        frame = re.search(r"\{\{(0x79, 0xf4[^}]+)\}\}", template).group(1)
        raw = bytes(int(value.strip(), 16) for value in frame.split(","))
        addresses.add(((raw[17] << 1) | (raw[18] >> 7)) & 255)
        self.assertEqual(addresses, set(enrollment.LEGACY_ADDRESSES))
        self.assertEqual(self.journal.address(self.controller), 2)

    def test_attempted_slot_survives_failure_and_gateway_restart(self):
        self.fixture.command["device_address"] = 2
        self.journal.begin(enrollment_tests.NODE, self.fixture.command)
        self.journal.observe(enrollment_tests.NODE, dict(
            command_id=self.fixture.command["command_id"], state="failed"))
        restarted = enrollment.EnrollmentJournal(self.store)
        self.assertEqual(restarted.address(self.controller), 3)

    def test_retained_slots_tombstones_and_controller_isolation(self):
        old = self.owner(address=2)
        old.update(revoking=True, revoked=True)
        self.store.save_htv213_owner(json.dumps({self.fixture.key: old}))
        config = copy.deepcopy(old["configuration"])
        config.update(model="HTV145FRF", factory_endpoint="1155668f",
                      valve_endpoint="9155668f", address=3, ports=config["ports"][:1])
        self.store.save_valve_recovery(json.dumps({config["factory_endpoint"]: {"configuration": config}}))
        self.assertEqual(self.journal.address(self.controller), 4)
        self.assertEqual(self.journal.address(self.controller, replacement_key=self.fixture.key), 2)
        config["controller_endpoint"] = "a2446689"
        self.store.save_valve_recovery(json.dumps({config["factory_endpoint"]: {"configuration": config}}))
        self.assertEqual(self.journal.address(self.controller), 3)
        self.assertEqual(self.journal.address("a2446689"), 2)

    def test_explicit_repair_cannot_reuse_a_frozen_legacy_slot(self):
        self.owner(address=1)
        with self.assertRaisesRegex(ValueError, "slot conflicts"):
            self.journal.address(self.controller, replacement_key=self.fixture.key)

    def test_exhausted_slot_space_does_not_mutate_state(self):
        self.owner()
        state = json.loads(self.store.metadata_value(enrollment.KEY))
        template = state["sessions"][state["current"]]
        state["sessions"] = {str(address): {**copy.deepcopy(template),
            "command": {**template["command"], "device_address": address}}
            for address in range(1, 256)}
        self.store.set_metadata_value(enrollment.KEY, json.dumps(state))
        before = self.store.metadata_value(enrollment.KEY)
        with self.assertRaisesRegex(ValueError, "no available"):
            self.journal.address(self.controller)
        self.assertEqual(self.store.metadata_value(enrollment.KEY), before)

    def test_normal_enrollment_records_model_policy_without_fabricated_trial(self):
        self.owner()
        record = json.loads(self.store.metadata_value(KEY))[self.fixture.key]
        self.assertEqual(record["phase_policy"], MODEL_PHASE_POLICY)
        self.assertNotIn("counter_boundary", record)
        self.assertEqual(record["next_phase"], 3)


class ModelPhasePolicyTest(unittest.TestCase):
    def setUp(self):
        self.fixture = control_tests.Htv213ControlCoreTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def policy(self):
        records = json.loads(self.fixture.store.metadata_value(KEY))
        records[self.fixture.key]["phase_policy"] = MODEL_PHASE_POLICY
        self.fixture.store.save_htv213_control_trial(json.dumps(records))

    def test_ordinary_policy_wraps_from_real_seed_without_probe_or_jump(self):
        self.policy()
        for phase in tuple(range(2, 64)) + (0, 1, 2):
            tx = self.fixture.reserve()
            self.assertEqual(tx["phase"], phase)
            self.fixture.journal.dispatch(self.fixture.key, tx, lambda *_: None)
            self.fixture.finish(phase=phase)
        record = self.fixture.journal.snapshot(self.fixture.key)
        self.assertEqual(record["next_phase"], 3)
        self.assertNotIn("counter_boundary", record)
        self.assertEqual(len(record["history"]), 64)
        self.assertTrue(wraps(record))

    def test_policy_does_not_promote_old_records_or_accept_unknown_policy(self):
        before = self.fixture.journal.snapshot(self.fixture.key)
        self.assertFalse(wraps(before))
        self.assertFalse(wraps({"phase_policy": "htv405_modulo64_v1"}))
        self.assertEqual(self.fixture.journal.snapshot(self.fixture.key), before)

    def test_policy_does_not_release_an_uncertain_command_or_reseed_on_restart(self):
        self.policy()
        tx = self.fixture.reserve()
        self.fixture.journal.dispatch(self.fixture.key, tx, lambda *_: None)
        before = self.fixture.journal.snapshot(self.fixture.key)
        with self.assertRaises(ValueError):
            self.fixture.reserve()
        self.fixture.journal.seed(**self.fixture.identity)
        self.assertEqual(self.fixture.journal.snapshot(self.fixture.key), before)
        self.assertEqual(before["next_phase"], 3)


class CarrierProvisioningTest(unittest.TestCase):
    def setUp(self):
        self.fixture = enrollment_tests.EnrollmentFlowTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.server = create_server(self.fixture.gateway, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.url = f"http://127.0.0.1:{self.server.server_port}/api/v1/nodes/{enrollment_tests.NODE}/htv213-calibration"

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, body, *, token="test-token", url=None):
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        return urlopen(Request(url or self.url, data=json.dumps(body).encode(), headers=headers), timeout=2)

    def test_authenticated_provisioning_persists_without_rf_or_counter_change(self):
        body = dict(initial_center_hz=434391500, routine_center_hz=434281500)
        before = self.fixture.gateway._store.metadata_value(KEY)
        with self.request(body) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.load(response), dict(node_id=enrollment_tests.NODE, model="HTV213FRF", **body))
        profile = enrollment.EnrollmentJournal(self.fixture.gateway._store).profile(enrollment_tests.NODE, 2)
        self.assertEqual(profile.initial_center_hz, body["initial_center_hz"])
        self.assertEqual(profile.routine_center_hz, body["routine_center_hz"])
        self.assertEqual(self.fixture.gateway._store.metadata_value(KEY), before)
        self.assertEqual(self.fixture.sent, [])

    def test_bad_auth_unknown_radio_and_invalid_values_cannot_provision(self):
        body = dict(initial_center_hz=434391500, routine_center_hz=434281500)
        before = self.fixture.gateway._store.metadata_value(enrollment.KEY)
        cases = [(body, dict(token=None), 401), (body, dict(token="wrong"), 401),
                 ({**body, "initial_center_hz": True}, {}, 400),
                 ({**body, "routine_center_hz": "434281500"}, {}, 400),
                 ({**body, "factory_endpoint": "11556677"}, {}, 400),
                 (body, dict(url=self.url.replace(enrollment_tests.NODE, "rp-aabbccddeeff")), 400)]
        for request_body, options, status in cases:
            with self.assertRaises(HTTPError) as raised:
                self.request(request_body, **options)
            self.assertEqual(raised.exception.code, status)
            raised.exception.close()
        self.assertEqual(self.fixture.gateway._store.metadata_value(enrollment.KEY), before)
        self.assertEqual(self.fixture.sent, [])

    def test_active_enrollment_keeps_its_saved_carrier_configuration(self):
        self.fixture.start()
        before = self.fixture.gateway._store.metadata_value(enrollment.KEY)
        with self.assertRaises(HTTPError) as raised:
            self.request(dict(initial_center_hz=434391500, routine_center_hz=434281500))
        self.assertEqual(raised.exception.code, 400)
        raised.exception.close()
        self.assertEqual(self.fixture.gateway._store.metadata_value(enrollment.KEY), before)
        self.assertEqual([command["type"] for _, command in self.fixture.sent], ["htv213_enrollment_start"])
