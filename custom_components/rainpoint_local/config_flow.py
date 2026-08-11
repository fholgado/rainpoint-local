"""Config flow for RainPoint Local."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    RainPointLocalCannotConnect,
    RainPointLocalClient,
    RainPointLocalInvalidResponse,
    RainPointLocalUnauthorized,
)
from .const import CONF_HOST, CONF_PORT, CONF_TOKEN, DEFAULT_PORT, DOMAIN


class RainPointLocalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a local rainpointd gateway."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> RainPointLocalOptionsFlow:
        """Return the local-gateway management flow."""
        return RainPointLocalOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await self._async_validate(user_input)
            except RainPointLocalCannotConnect:
                errors["base"] = "cannot_connect"
            except RainPointLocalInvalidResponse:
                errors["base"] = "invalid_response"
            else:
                return await self._async_create_gateway_entry(user_input, info)

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

    async def async_step_import(self, user_input: dict[str, Any]) -> FlowResult:
        """Import a temporary YAML bootstrap as a normal config entry."""
        try:
            info = await self._async_validate(user_input)
        except RainPointLocalCannotConnect:
            return self.async_abort(reason="cannot_connect")
        except RainPointLocalInvalidResponse:
            return self.async_abort(reason="invalid_response")
        return await self._async_create_gateway_entry(user_input, info)

    async def _async_validate(
        self, user_input: dict[str, Any]
    ) -> dict[str, Any]:
        """Connect to rainpointd and return compatible gateway metadata."""
        client = RainPointLocalClient(
            user_input[CONF_HOST],
            user_input[CONF_PORT],
            async_get_clientsession(self.hass),
        )
        return await client.info()

    async def _async_create_gateway_entry(
        self, user_input: dict[str, Any], info: dict[str, Any]
    ) -> FlowResult:
        """Create one unique entry for a validated gateway."""
        await self.async_set_unique_id(info["gateway_id"])
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"RainPoint Local ({info['gateway_id']})",
            data=user_input,
        )


class RainPointLocalOptionsFlow(config_entries.OptionsFlow):
    """Manage receive-only sensor pairing for an existing gateway."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry
        self._token = str(entry.options.get(CONF_TOKEN, ""))
        self._paired_endpoint: str | None = None
        self._pairing_nodes: dict[str, str] = {}

    def _client(self) -> RainPointLocalClient:
        return RainPointLocalClient(
            self._entry.data[CONF_HOST],
            self._entry.data[CONF_PORT],
            async_get_clientsession(self.hass),
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_show_menu(step_id="init", menu_options=["pair_sensor"])

    async def async_step_pair_sensor(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        try:
            progress = await self._client().pairing()
        except RainPointLocalCannotConnect:
            errors["base"] = "cannot_connect"
        except RainPointLocalInvalidResponse:
            errors["base"] = "invalid_response"
        else:
            self._pairing_nodes = {
                str(node["node_id"]): (
                    f"{node['node_id']} ({node.get('firmware_version') or 'unknown firmware'})"
                )
                for node in progress.get("pairing_nodes", [])
                if isinstance(node, dict) and isinstance(node.get("node_id"), str)
            }
            if not self._pairing_nodes:
                errors["base"] = "no_pairing_node"
        if user_input is not None:
            self._token = str(user_input[CONF_TOKEN])
            node_id = str(user_input.get("node_id", ""))
            if node_id not in self._pairing_nodes:
                errors["base"] = "no_pairing_node"
            else:
                try:
                    await self._client().start_pairing(
                        self._token,
                        int(user_input["duration_seconds"]),
                        node_id=node_id,
                    )
                except RainPointLocalUnauthorized:
                    errors["base"] = "invalid_auth"
                except RainPointLocalCannotConnect:
                    errors["base"] = "cannot_connect"
                except RainPointLocalInvalidResponse:
                    errors["base"] = "invalid_response"
                else:
                    self.hass.config_entries.async_update_entry(
                        self._entry,
                        options={**self._entry.options, CONF_TOKEN: self._token},
                    )
                    return await self.async_step_pairing_progress()

        node_choices = self._pairing_nodes or {
            "": "No pairing-capable radio node connected"
        }
        default_node = next(iter(node_choices))

        return self.async_show_form(
            step_id="pair_sensor",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOKEN, default=self._token): str,
                    vol.Required("node_id", default=default_node): vol.In(
                        node_choices
                    ),
                    vol.Required("duration_seconds", default=120): vol.All(
                        vol.Coerce(int), vol.Range(min=10, max=900)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_pairing_progress(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        try:
            progress = await self._client().pairing()
        except RainPointLocalCannotConnect:
            progress = {"active": True, "candidates": []}
            errors["base"] = "cannot_connect"
        except RainPointLocalInvalidResponse:
            progress = {"active": True, "candidates": []}
            errors["base"] = "invalid_response"
        else:
            new_records = progress.get("new_records", [])
            if new_records:
                self._paired_endpoint = str(new_records[0]["paired_endpoint"])
                return await self.async_step_sensor_details()
            if not progress.get("active"):
                return self.async_abort(reason="pairing_timeout")

        candidates = ", ".join(progress.get("candidates", [])) or "None yet"
        return self.async_show_form(
            step_id="pairing_progress",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"candidates": candidates},
        )

    async def async_step_sensor_details(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if self._paired_endpoint is None:
            return self.async_abort(reason="pairing_timeout")
        errors: dict[str, str] = {}
        if user_input is not None:
            name = str(user_input["name"])
            area = str(user_input.get("area", "")).strip() or None
            try:
                result = await self._client().complete_pairing(
                    self._token,
                    endpoint=self._paired_endpoint,
                    name=name,
                    area=area,
                )
            except RainPointLocalUnauthorized:
                errors["base"] = "invalid_auth"
            except RainPointLocalCannotConnect:
                errors["base"] = "cannot_connect"
            except RainPointLocalInvalidResponse:
                errors["base"] = "invalid_response"
            else:
                coordinator = self.hass.data.get(DOMAIN, {}).get(
                    self._entry.entry_id
                )
                if coordinator is not None:
                    await coordinator.async_request_refresh()
                device = result.get("device", {})
                device_id = device.get("device_id")
                if isinstance(device_id, str):
                    device_registry = dr.async_get(self.hass)
                    device_entry = device_registry.async_get_device(
                        identifiers={(DOMAIN, device_id)}
                    )
                    if device_entry is not None:
                        device_registry.async_update_device(
                            device_entry.id,
                            name=name,
                            suggested_area=area,
                        )
                return self.async_create_entry(title="Sensor paired", data={})

        return self.async_show_form(
            step_id="sensor_details",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "name", default=f"RainPoint Sensor {self._paired_endpoint[-4:]}"
                    ): str,
                    vol.Optional("area", default=""): str,
                }
            ),
            errors=errors,
            description_placeholders={"endpoint": self._paired_endpoint},
        )
