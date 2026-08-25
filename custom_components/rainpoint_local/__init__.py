"""RainPoint Local integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import (
    area_registry as ar,
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RainPointLocalClient, RainPointLocalError
from .const import CONF_HOST, CONF_PORT, CONF_TOKEN, DEFAULT_PORT, DOMAIN, PLATFORMS
from .coordinator import RainPointLocalCoordinator
from .migration import migrate_entry_payload

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
        info = await client.info()
    except RainPointLocalError as exc:
        raise ConfigEntryNotReady(f"Unable to connect to rainpointd: {exc}") from exc

    coordinator = RainPointLocalCoordinator(
        hass,
        client,
        entry.entry_id,
        event_cursor=info.latest_event_id,
        event_long_poll="event_long_poll" in info.capabilities,
    )
    await coordinator.async_config_entry_first_refresh()
    await _async_migrate_radio_node_metadata(hass, entry, coordinator)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    coordinator.async_start_event_listener()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_migrate_radio_node_metadata(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: RainPointLocalCoordinator,
) -> None:
    """Move legacy HA-only node labels into the gateway registry once."""
    token = str(entry.data.get(CONF_TOKEN, entry.options.get(CONF_TOKEN, "")))
    if not token:
        return
    device_registry = dr.async_get(hass)
    area_registry = ar.async_get(hass)
    changed = False
    for node_id, node in coordinator.nodes.items():
        if node.get("name") != node_id and node.get("area") is not None:
            continue
        device = device_registry.async_get_device(
            identifiers={(DOMAIN, f"radio-node:{node_id}")}
        )
        if device is None:
            continue
        name = str(device.name_by_user or node.get("name") or node_id).strip()
        area = node.get("area")
        if area is None and device.area_id:
            area_entry = area_registry.async_get_area(device.area_id)
            area = area_entry.name if area_entry is not None else None
        if name == node.get("name") and area == node.get("area"):
            continue
        try:
            await coordinator.client.update_radio_node_metadata(
                token,
                node_id,
                name=name,
                area=area,
            )
        except RainPointLocalError as exc:
            _LOGGER.warning(
                "Unable to migrate radio-node metadata for %s: %s", node_id, exc
            )
            continue
        changed = True
    if changed:
        await coordinator.async_request_refresh()


async def async_migrate_entry(
    hass: HomeAssistant, entry: ConfigEntry
) -> bool:
    """Migrate persistent configuration and obsolete integration entities."""
    version, data, options = migrate_entry_payload(
        entry.version, dict(entry.data), dict(entry.options)
    )
    if version != entry.version or data != entry.data or options != entry.options:
        hass.config_entries.async_update_entry(
            entry,
            data=data,
            options=options,
            version=version,
        )

    # Version 0.1.2 briefly exposed a duplicate event entity per report.
    entity_registry = er.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    ):
        if entity_entry.unique_id.endswith("_report_received"):
            entity_registry.async_remove(entity_entry.entity_id)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload RainPoint Local."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if isinstance(coordinator, RainPointLocalCoordinator):
        await coordinator.async_stop_event_listener()
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    device_entry: DeviceEntry,
) -> bool:
    """Forget one supported local device selected from its HA device menu."""
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
    device = coordinator.data.get(local_id)
    if device is None:
        # A successful gateway inventory that no longer contains the device is
        # terminal local evidence that it was already forgotten or removed by
        # a storage migration. Allow HA to clear its stale registry record
        # without attempting another backend mutation.
        return coordinator.last_update_success
    if "forget" not in device.get("capabilities", []):
        return False
    try:
        await coordinator.client.forget_sensor(token, local_id)
        await coordinator.async_request_refresh()
    except RainPointLocalError as exc:
        _LOGGER.warning("Unable to forget RainPoint sensor %s: %s", local_id, exc)
        return False
    return True
