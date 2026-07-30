"""RainPoint Local integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RainPointLocalClient, RainPointLocalError
from .const import CONF_HOST, CONF_PORT, DOMAIN, PLATFORMS
from .coordinator import RainPointLocalCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up RainPoint Local from a config entry."""
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
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload RainPoint Local."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
