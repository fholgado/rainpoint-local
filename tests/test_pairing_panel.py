"""Test actual panel callbacks without requiring HA in the local unit environment."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import unittest

from tests.test_integration_migration import _integration_function


class UnknownFlow(Exception):
    pass


class PairingPanelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = SimpleNamespace(stop_pairing=AsyncMock(), commission_valve=AsyncMock())
        self.manager = SimpleNamespace(async_get=Mock(return_value={
            "handler": "gateway-a", "context": {"rainpoint_pairing_command_id": "owned-command"}}),
            async_abort=Mock())
        self.entry = SimpleNamespace(domain="rainpoint_local", data={"registry_write_token": "private"})
        self.hass = SimpleNamespace(config_entries=SimpleNamespace(options=self.manager,
            async_get_entry=Mock(return_value=self.entry)),
            data={"rainpoint_local": {"gateway-a": SimpleNamespace(client=self.client)}})
        self.cancel = _integration_function("panel.py", "cancel_flow", {
            "DOMAIN": "rainpoint_local", "CONF_TOKEN": "registry_write_token", "UnknownFlow": UnknownFlow})

    async def test_scoped_stop_precedes_flow_removal(self):
        def assert_stopped(_):
            self.client.stop_pairing.assert_awaited_once_with("private", command_id="owned-command")
        self.manager.async_abort.side_effect = assert_stopped
        self.assertEqual({"closed": True, "stop_requested": True}, await self.cancel(self.hass, "gateway-a", "flow"))

    async def test_network_failure_retains_flow_for_retry(self):
        self.client.stop_pairing.side_effect = OSError("offline")
        with self.assertRaises(OSError):
            await self.cancel(self.hass, "gateway-a", "flow")
        self.manager.async_abort.assert_not_called()

    async def test_other_gateway_flow_cannot_be_cancelled(self):
        with self.assertRaises(ValueError):
            await self.cancel(self.hass, "gateway-b", "flow")
        self.client.stop_pairing.assert_not_awaited()
        self.manager.async_abort.assert_not_called()

    async def test_no_broad_stop_when_flow_never_armed(self):
        self.manager.async_get.return_value["context"] = {}
        result = await self.cancel(self.hass, "gateway-a", "flow")
        self.assertFalse(result["stop_requested"])
        self.client.stop_pairing.assert_not_awaited()

    async def test_already_finished_flow_is_closed_without_radio_write(self):
        self.manager.async_get.side_effect = UnknownFlow
        self.assertTrue((await self.cancel(self.hass, "gateway-a", "flow"))["closed"])
        self.client.stop_pairing.assert_not_awaited()

    async def test_setup_cancel_uses_its_own_device_and_pairing(self):
        self.manager.async_get.return_value["context"] = {
            "rainpoint_commission_device_id": "valve-a", "rainpoint_commission_command_id": "association-a"}
        await self.cancel(self.hass, "gateway-a", "flow")
        self.client.commission_valve.assert_awaited_once_with("private", "valve-a", "cancel", pairing_command_id="association-a")
        self.client.stop_pairing.assert_not_awaited()
