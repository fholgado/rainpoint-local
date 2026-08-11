"""Config flow for RainPoint Local."""

from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from .api import (
    RainPointLocalCannotConnect,
    RainPointLocalClient,
    RainPointLocalInvalidResponse,
    RainPointLocalUnauthorized,
)
from .const import CONF_HOST, CONF_PORT, CONF_TOKEN, DEFAULT_PORT, DOMAIN


LEGACY_TRANSPORT_GATEWAY_IDS = {
    "rainpoint-replay",
    "rainpoint-rtl433",
    "rainpoint-esp32_serial",
}


class RainPointLocalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a local rainpointd gateway."""

    VERSION = 1

    def __init__(self) -> None:
        self._hassio_discovery: dict[str, Any] | None = None

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

    async def async_step_hassio(
        self, discovery_info: HassioServiceInfo
    ) -> FlowResult:
        """Receive credentials through supported Supervisor discovery."""
        config = discovery_info.config
        try:
            discovered = {
                CONF_HOST: str(config[CONF_HOST]),
                CONF_PORT: int(config[CONF_PORT]),
                CONF_TOKEN: str(config[CONF_TOKEN]),
            }
            gateway_id = str(config["gateway_id"])
        except (KeyError, TypeError, ValueError):
            return self.async_abort(reason="invalid_response")
        if not discovered[CONF_TOKEN] or not gateway_id:
            return self.async_abort(reason="invalid_response")

        legacy_entry = next(
            (
                entry
                for entry in self._async_current_entries()
                if entry.unique_id in LEGACY_TRANSPORT_GATEWAY_IDS
            ),
            None,
        )
        if legacy_entry is not None:
            self.hass.config_entries.async_update_entry(
                legacy_entry,
                data=discovered,
                unique_id=gateway_id,
                title=f"RainPoint Local ({gateway_id})",
            )
            return self.async_abort(reason="already_configured")

        current_entry = next(
            (
                entry
                for entry in self._async_current_entries()
                if entry.unique_id == gateway_id
            ),
            None,
        )
        if current_entry is not None:
            self.hass.config_entries.async_update_entry(
                current_entry,
                data=discovered,
                title=f"RainPoint Local ({gateway_id})",
            )
            return self.async_abort(reason="already_configured")

        await self.async_set_unique_id(gateway_id)
        self._abort_if_unique_id_configured(updates=discovered)
        self._hassio_discovery = discovered
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm setup of a Supervisor-discovered local gateway."""
        if self._hassio_discovery is None:
            return self.async_abort(reason="invalid_response")
        if user_input is None:
            return self.async_show_form(step_id="hassio_confirm")
        try:
            info = await self._async_validate(self._hassio_discovery)
        except RainPointLocalCannotConnect:
            return self.async_abort(reason="cannot_connect")
        except RainPointLocalInvalidResponse:
            return self.async_abort(reason="invalid_response")
        return await self._async_create_gateway_entry(
            self._hassio_discovery, info
        )

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
        self._token = str(
            entry.data.get(CONF_TOKEN, entry.options.get(CONF_TOKEN, ""))
        )
        self._paired_endpoint: str | None = None
        self._pairing_nodes: dict[str, str] = {}
        self._pairing_task: asyncio.Task[None] | None = None
        self._pairing_error: str | None = None

    def _client(self) -> RainPointLocalClient:
        return RainPointLocalClient(
            self._entry.data[CONF_HOST],
            self._entry.data[CONF_PORT],
            async_get_clientsession(self.hass),
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if self._token and (
            self._entry.data.get(CONF_TOKEN) != self._token
            or CONF_TOKEN in self._entry.options
        ):
            self.hass.config_entries.async_update_entry(
                self._entry,
                data={**self._entry.data, CONF_TOKEN: self._token},
                options={
                    key: value
                    for key, value in self._entry.options.items()
                    if key != CONF_TOKEN
                },
            )
        menu_options = ["pair_sensor"] if self._token else ["authenticate_gateway"]
        return self.async_show_menu(step_id="init", menu_options=menu_options)

    async def async_step_authenticate_gateway(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Authenticate a manually configured standalone gateway once."""
        errors: dict[str, str] = {}
        if user_input is not None:
            token = str(user_input[CONF_TOKEN]).strip()
            try:
                await self._client().authenticate(token)
            except RainPointLocalUnauthorized:
                errors["base"] = "invalid_auth"
            except RainPointLocalCannotConnect:
                errors["base"] = "cannot_connect"
            except RainPointLocalInvalidResponse:
                errors["base"] = "invalid_response"
            else:
                self._token = token
                self.hass.config_entries.async_update_entry(
                    self._entry,
                    data={**self._entry.data, CONF_TOKEN: token},
                )
                return await self.async_step_pair_sensor()
        return self.async_show_form(
            step_id="authenticate_gateway",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): str}),
            errors=errors,
        )

    async def async_step_pair_sensor(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if not self._token:
            return await self.async_step_authenticate_gateway()
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
                    self._pairing_task = self.hass.async_create_task(
                        self._async_wait_for_sensor()
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
        if self._pairing_task is None:
            return self.async_abort(reason="pairing_timeout")
        if self._pairing_task.done():
            return self.async_show_progress_done(next_step_id="pairing_result")
        return self.async_show_progress(
            step_id="pairing_progress",
            progress_action="wait_for_sensor",
            progress_task=self._pairing_task,
        )

    async def _async_wait_for_sensor(self) -> None:
        """Poll pairing state until the selected sensor finishes enrollment."""
        try:
            while True:
                try:
                    progress = await self._client().pairing()
                except RainPointLocalCannotConnect:
                    self._pairing_error = "cannot_connect"
                    return
                except RainPointLocalInvalidResponse:
                    self._pairing_error = "invalid_response"
                    return

                new_records = progress.get("new_records", [])
                if new_records:
                    self._paired_endpoint = str(
                        new_records[0]["paired_endpoint"]
                    )
                    return
                if progress.get("stage") == "transmitter_failed":
                    self._pairing_error = "pairing_failed"
                    return
                if not progress.get("active"):
                    self._pairing_error = "pairing_timeout"
                    return
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            try:
                await self._client().stop_pairing(self._token)
            except (
                RainPointLocalCannotConnect,
                RainPointLocalInvalidResponse,
                RainPointLocalUnauthorized,
            ):
                pass
            raise

    async def async_step_pairing_result(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Advance automatically after the pairing progress task completes."""
        if self._pairing_error is not None:
            return self.async_abort(reason=self._pairing_error)
        return await self.async_step_sensor_details()

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
