"""RainPoint Local integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RainPointLocalClient, RainPointLocalError
from .const import CONF_HOST, CONF_PORT, CONF_TOKEN, DEFAULT_PORT, DOMAIN, PLATFORMS
from .coordinator import RainPointLocalCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_HOST): cv.string,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

LEGACY_DEFAULT_TITLES = {
    "RainPoint Local (rainpoint-replay)",
    "RainPoint Local (rainpoint-rtl433)",
    "RainPoint Local (rainpoint-esp32_serial)",
}


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Import a temporary YAML bootstrap through the supported Config Flow."""
    if yaml_config := config.get(DOMAIN):
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data=dict(yaml_config),
            )
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up RainPoint Local from a config entry."""
    if entry.unique_id and entry.title in LEGACY_DEFAULT_TITLES:
        hass.config_entries.async_update_entry(
            entry, title=f"RainPoint Local ({entry.unique_id})"
        )
    client = RainPointLocalClient(
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        async_get_clientsession(hass),
    )
    try:
        await client.info()
    except RainPointLocalError as exc:
        raise ConfigEntryNotReady(f"Unable to connect to rainpointd: {exc}") from exc

    coordinator = RainPointLocalCoordinator(hass, client, entry.entry_id)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Version 0.1.2 briefly exposed a second event entity for each report.
    # The enriched report-time sensor now provides the same activity without
    # duplicating every packet in the device logbook.
    entity_registry = er.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    ):
        if entity_entry.unique_id.endswith("_report_received"):
            entity_registry.async_remove(entity_entry.entity_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload RainPoint Local."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    device_entry: DeviceEntry,
) -> bool:
    """Forget one HCS026 sensor selected from its HA device menu."""
    local_id = next(
        (
            identifier[1]
            for identifier in device_entry.identifiers
            if identifier[0] == DOMAIN
        ),
        None,
    )
    if local_id is None:
        return False
    token = str(
        config_entry.data.get(
            CONF_TOKEN, config_entry.options.get(CONF_TOKEN, "")
        )
    )
    if not token:
        return False
    coordinator = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
    if not isinstance(coordinator, RainPointLocalCoordinator):
        return False
    device = coordinator.data.get(local_id, {})
    if "forget" not in device.get("capabilities", []):
        return False
    try:
        await coordinator.client.forget_sensor(token, local_id)
        await coordinator.async_request_refresh()
    except RainPointLocalError as exc:
        _LOGGER.warning("Unable to forget RainPoint sensor %s: %s", local_id, exc)
        return False
    return True
