"""RainPoint Local integration."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RainPointLocalClient, RainPointLocalError
from .const import CONF_HOST, CONF_PORT, DEFAULT_PORT, DOMAIN, PLATFORMS
from .coordinator import RainPointLocalCoordinator

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

    coordinator = RainPointLocalCoordinator(hass, client)
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
