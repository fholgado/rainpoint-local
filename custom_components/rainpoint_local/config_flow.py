"""Config flow for RainPoint Local."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    RainPointLocalCannotConnect,
    RainPointLocalClient,
    RainPointLocalInvalidResponse,
)
from .const import CONF_HOST, CONF_PORT, DEFAULT_PORT, DOMAIN


class RainPointLocalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a local rainpointd gateway."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            client = RainPointLocalClient(
                user_input[CONF_HOST],
                user_input[CONF_PORT],
                async_get_clientsession(self.hass),
            )
            try:
                info = await client.info()
            except RainPointLocalCannotConnect:
                errors["base"] = "cannot_connect"
            except RainPointLocalInvalidResponse:
                errors["base"] = "invalid_response"
            else:
                await self.async_set_unique_id(info["gateway_id"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"RainPoint Local ({info['gateway_id']})",
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default="127.0.0.1"): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=65535)
                ),
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )
