"""Execute the real manual flow callback without requiring a full HA install."""
import json
import types
import unittest
from unittest.mock import AsyncMock, Mock

from tests.test_integration_migration import _integration_function, PACKAGE


class CannotConnect(Exception):
    pass


class InvalidResponse(Exception):
    pass


class Unauthorized(Exception):
    pass


class ManualGatewaySetupTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Only HA's form rendering/selector objects are substituted. The actual
        # callback constructs the schema and handles submissions; real HA CI
        # additionally validates the schema and connects to an isolated TLS server.
        vol = types.SimpleNamespace(Schema=dict, Required=lambda name, **kwargs: name,
            All=lambda *args: args, Coerce=lambda value: value, Range=lambda **kw: kw)
        selector = types.SimpleNamespace(TextSelector=lambda config: config,
            TextSelectorConfig=lambda **kw: kw, TextSelectorType=types.SimpleNamespace(PASSWORD="password"))
        self.step = _integration_function("config_flow.py", "async_step_user", {
            "vol": vol, "selector": selector, "CONF_HOST": "host", "CONF_PORT": "port",
            "DEFAULT_PORT": 8787, "CONF_TOKEN": "registry_write_token",
            "RainPointLocalCannotConnect": CannotConnect,
            "RainPointLocalInvalidResponse": InvalidResponse,
            "RainPointLocalUnauthorized": Unauthorized,
        }, classname="RainPointLocalConfigFlow")
        self.flow = types.SimpleNamespace(_async_validate=AsyncMock(return_value="metadata"),
            _async_create_gateway_entry=AsyncMock(return_value={"type": "create_entry"}),
            async_show_form=Mock(side_effect=lambda **kw: {"type": "form", **kw}))

    async def test_manual_form_collects_a_masked_management_credential(self):
        result = await self.step(self.flow)
        self.assertIn("registry_write_token", result["data_schema"])
        self.assertEqual({"type": "password"}, result["data_schema"]["registry_write_token"])
        self.flow._async_validate.assert_not_awaited()

    async def test_valid_submission_passes_credential_to_validation_and_storage(self):
        data = {"host": "gateway.example", "port": 8787, "registry_write_token": "a" * 32}
        self.assertEqual({"type": "create_entry"}, await self.step(self.flow, data))
        self.flow._async_validate.assert_awaited_once_with(data)
        self.flow._async_create_gateway_entry.assert_awaited_once_with(data, "metadata")

    async def test_empty_credential_never_attempts_plaintext_validation(self):
        result = await self.step(self.flow, {"host": "gateway.example", "port": 8787,
            "registry_write_token": ""})
        self.assertEqual({"base": "invalid_auth"}, result["errors"])
        self.flow._async_validate.assert_not_awaited()
        self.flow._async_create_gateway_entry.assert_not_awaited()

    async def test_rejected_credential_returns_a_redacted_form_error(self):
        self.flow._async_validate.side_effect = Unauthorized("do-not-echo-this-secret")
        result = await self.step(self.flow, {"host": "gateway.example", "port": 8787,
            "registry_write_token": "short-secret"})
        self.assertEqual({"base": "invalid_auth"}, result["errors"])
        self.assertNotIn("short-secret", repr(result))
        self.assertNotIn("do-not-echo", repr(result))
        self.flow._async_create_gateway_entry.assert_not_awaited()

    async def test_network_and_protocol_failures_do_not_create_an_entry(self):
        for error, code in ((CannotConnect, "cannot_connect"), (InvalidResponse, "invalid_response")):
            with self.subTest(code=code):
                self.flow._async_validate.side_effect = error("private detail")
                result = await self.step(self.flow, {"host": "gateway.example", "port": 8787,
                    "registry_write_token": "a" * 32})
                self.assertEqual({"base": code}, result["errors"])
                self.assertNotIn("private detail", repr(result))
        self.flow._async_create_gateway_entry.assert_not_awaited()

    def test_credential_label_is_manual_only_and_translations_match(self):
        text = json.loads((PACKAGE / "strings.json").read_text())
        self.assertEqual(text, json.loads((PACKAGE / "translations/en.json").read_text()))
        self.assertIn("registry_write_token", text["config"]["step"]["user"]["data"])
        self.assertIn("invalid_auth", text["config"]["error"])
        self.assertNotIn("registry_write_token", text["config"]["step"]["hassio_confirm"].get("data", {}))
