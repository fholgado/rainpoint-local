"""Native HA model selection backed by the gateway's real enrollment policy."""
import copy
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from tests import test_htv213_enrollment_journal as enrollment_tests
from tests.test_htv213_pairing_gateway import NODE
from tests.test_integration_migration import _integration_function
from tests.test_api_models import api_models
from rainpointd import htv213_enrollment as enrollment, htv213_enrollment_flow as flow


class MenuPolicyTest(unittest.TestCase):
    def setUp(self):
        self.fixture = enrollment_tests.EnrollmentFlowTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.gateway = self.fixture.gateway

    def profile(self):
        return next(p for p in self.gateway.pairing()["supported_profiles"]
                    if p["profile_id"] == enrollment.PROFILE_ID)

    def test_standard_firmware_eligibility_needs_no_research_capability(self):
        node = self.gateway._nodes[NODE]
        capabilities = [c for c in node['capabilities']
            if c not in {'htv213_pairing_experiment', 'htv213_control_experiment'}]
        self.gateway.update_node(NODE, capabilities=capabilities + ['htv213_control_v1'])
        self.assertIn(NODE, self.profile()['eligible_node_ids'])
        self.gateway.update_node(NODE, capabilities=capabilities)
        self.assertNotIn(NODE, self.profile()['eligible_node_ids'])

    def test_every_required_capability_is_enforced_by_catalog_and_start(self):
        before = self.gateway._store.metadata_value(enrollment.KEY)
        for capability in flow.REQUIRED_CAPABILITIES:
            with self.subTest(capability=capability):
                self.gateway.update_node(NODE, capabilities=[c for c in self.fixture.capabilities if c != capability])
                self.assertEqual(self.profile()["eligible_node_ids"], [])
                with self.assertRaisesRegex(ValueError, "firmware"):
                    self.fixture.start()
        self.assertEqual(self.fixture.sent, [])
        self.assertEqual(self.gateway._store.metadata_value(enrollment.KEY), before)

    def test_htv213_only_radio_is_listed_without_a_legacy_pairing_capability(self):
        self.gateway.update_node(NODE, capabilities=sorted(flow.REQUIRED_CAPABILITIES) + ['htv213_control_v1'])
        self.assertEqual(self.profile()["eligible_node_ids"], [NODE])

    def test_radio_without_manual_tuning_uses_defaults_and_disconnect_still_blocks(self):
        self.gateway._store.set_metadata_value(enrollment.KEY, '{"radios":{},"sessions":{},"current":null}')
        self.assertTrue(self.profile()["user_pairing_supported"])
        self.assertEqual(self.profile()["eligible_node_ids"], [NODE])
        self.fixture.start()
        command = self.fixture.sent[0][1]
        # Independently SDR-qualified default on the original and spare radio.
        self.assertEqual(command["initial_center_hz"], 434397000)
        self.assertEqual(command["routine_center_hz"], 434287000)
        self.gateway.update_node(NODE, connected=False)
        self.assertEqual(self.profile()["eligible_node_ids"], [])
        self.assertEqual(len(self.fixture.sent), 1)

    def test_other_family_assignment_excludes_node_without_changing_it(self):
        with patch.object(self.gateway._store, "ack_assignments", return_value=[{}]):
            self.assertEqual(self.profile()["eligible_node_ids"], [])
            with self.assertRaisesRegex(ValueError, "already owns"):
                self.fixture.start()
        self.assertEqual(self.fixture.sent, [])

    def test_shared_firmware_can_enroll_without_revoking_sensor_ack_owner(self):
        self.gateway.update_node(NODE, capabilities=self.fixture.capabilities + ['htv213_shared_radio_v1'])
        with patch.object(self.gateway._store, "ack_assignments", return_value=[{"node_id": NODE}]):
            self.assertEqual(self.profile()["eligible_node_ids"], [NODE])
            self.fixture.start()
        self.assertEqual([command['type'] for _, command in self.fixture.sent], ['htv213_enrollment_start'])

    def test_saved_valve_is_not_revoked_or_repaired_by_visiting_menu(self):
        self.fixture.accept()
        self.gateway.complete_pairing(endpoint="91556677", name="Keep me")
        before = copy.deepcopy(self.gateway.devices())
        self.fixture.sent.clear()
        self.assertEqual(self.profile()["eligible_node_ids"], [])
        with self.assertRaisesRegex(ValueError, "already owns"):
            self.fixture.start()
        self.assertEqual(self.gateway.devices(), before)
        self.assertEqual(self.fixture.sent, [])


class NativeMenuTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = enrollment_tests.EnrollmentFlowTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.progress = self.fixture.gateway.pairing()
        self.profile = next(p for p in api_models.pairing_profiles(self.progress)
                            if p.profile_id == enrollment.PROFILE_ID)
        self.client = types.SimpleNamespace(pairing=AsyncMock(return_value=self.progress), start_pairing=AsyncMock())
        self.ui = types.SimpleNamespace(_client=lambda: self.client,
            _pairing_profile=self.profile, _pairing_reviewed=False, _pairing_request={},
            async_show_form=Mock(side_effect=lambda **kw: kw), async_step_pairing_review=AsyncMock())
        # Form-schema construction only; execute the actual async HA callback.
        vol = types.SimpleNamespace(Schema=lambda x:x, Required=lambda x,**kw:x,
            In=lambda x:x, All=lambda *x:x, Coerce=lambda x:x, Range=lambda **kw:kw)
        self.callback = _integration_function("config_flow.py", "async_step_pair_device", dict(
            vol=vol, pairing_profiles=api_models.pairing_profiles, APIModelError=api_models.APIModelError,
            RainPointLocalCannotConnect=ConnectionError, RainPointLocalInvalidResponse=ValueError,
            RainPointLocalCommandRejected=RuntimeError, RainPointLocalUnauthorized=PermissionError))

    async def test_menu_loads_two_zone_and_radio_selection_requires_no_rf_fields(self):
        load = _integration_function("config_flow.py", "_async_load_pairing_profiles",
                                     {"pairing_profiles":api_models.pairing_profiles})
        await load(self.ui)
        self.assertIn(enrollment.PROFILE_ID, self.ui._pairing_profiles)
        form = await self.callback(self.ui)
        self.assertEqual(form["errors"], {})
        self.assertEqual(set(self.ui._pairing_nodes), {NODE})
        self.assertEqual(set(form["data_schema"]), {"node_id", "duration_seconds"})
        await self.callback(self.ui, {"node_id":NODE, "duration_seconds":120})
        self.ui.async_step_pairing_review.assert_awaited_once_with()
        self.client.start_pairing.assert_not_awaited()
        self.assertEqual(self.fixture.sent, [])

    async def test_eligibility_refresh_blocks_stale_review_without_arming(self):
        self.fixture.gateway.update_node(NODE, capabilities=[enrollment.CAPABILITY])
        self.client.pairing.return_value = self.fixture.gateway.pairing()
        self.ui._pairing_reviewed = True
        form = await self.callback(self.ui, {"node_id":NODE, "duration_seconds":120})
        self.assertEqual(form["errors"]["base"], "no_prepared_two_zone_radio")
        self.assertEqual(self.ui._pairing_nodes, {})
        self.client.start_pairing.assert_not_awaited()
        self.ui.async_step_pairing_review.assert_not_awaited()

    async def test_failed_refresh_cannot_arm_or_advance_review(self):
        self.client.pairing.side_effect = ConnectionError
        form = await self.callback(self.ui, {"node_id":NODE, "duration_seconds":120})
        self.assertEqual(form["errors"]["base"], "cannot_connect")
        self.client.start_pairing.assert_not_awaited()
        self.ui.async_step_pairing_review.assert_not_awaited()

    async def test_withdrawn_model_cannot_arm_from_a_stale_form(self):
        next(p for p in self.progress["supported_profiles"]
             if p["profile_id"] == enrollment.PROFILE_ID)["user_pairing_supported"] = False
        self.ui._pairing_reviewed = True
        form = await self.callback(self.ui, {"node_id":NODE, "duration_seconds":120})
        self.assertEqual(form["errors"]["base"], "invalid_response")
        self.client.start_pairing.assert_not_awaited()

    async def test_legacy_profile_without_eligibility_keeps_capability_selection(self):
        payload = next(p for p in self.progress["supported_profiles"] if p["model"] == "HTV405FRF")
        self.ui._pairing_profile = api_models.PairingProfileMetadata.from_payload(payload)
        self.progress["pairing_nodes"][0]["capabilities"].append(payload["required_node_capability"])
        form = await self.callback(self.ui)
        self.assertEqual(form["errors"], {})
        self.assertEqual(set(self.ui._pairing_nodes), {NODE})
