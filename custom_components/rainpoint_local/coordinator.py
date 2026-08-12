"""Data coordinator for RainPoint Local."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import RainPointLocalClient, RainPointLocalError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class RainPointLocalCoordinator(DataUpdateCoordinator[dict[str, dict]]):
    """Poll local gateway snapshots."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: RainPointLocalClient,
        config_entry_id: str,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.client = client
        self.config_entry_id = config_entry_id
        self.nodes: dict[str, dict] = {}
        self.receivers: list[dict] = []
        self._logged_inventory = False

    async def _async_update_data(self) -> dict[str, dict]:
        try:
            devices = await self.client.devices()
            nodes = await self.client.nodes()
            receivers = await self.client.receivers()
        except RainPointLocalError as exc:
            raise UpdateFailed(f"Unable to update from rainpointd: {exc}") from exc
        result = {device["device_id"]: device for device in devices}
        self.nodes = {
            node["node_id"]: node
            for node in nodes
            if isinstance(node.get("node_id"), str)
        }
        self.receivers = receivers
        self._async_reconcile_device_metadata(result)
        active_ids = set(result) | {
            f"radio-node:{node_id}" for node_id in self.nodes
        }
        self._async_reconcile_entity_registry(active_ids)
        if not self._logged_inventory:
            _LOGGER.debug(
                "Loaded %d RainPoint devices, %d custom local radio nodes, and "
                "%d receiver coverage records",
                len(result),
                len(self.nodes),
                len(self.receivers),
            )
            self._logged_inventory = True
        return result

    def _async_reconcile_device_metadata(
        self, devices: dict[str, dict]
    ) -> None:
        """Keep HA model metadata aligned with gateway identification evidence."""
        device_registry = dr.async_get(self.hass)
        for local_id, device in devices.items():
            entry = device_registry.async_get_device(
                identifiers={(DOMAIN, local_id)}
            )
            model = device.get("model")
            if (
                entry is not None
                and isinstance(model, str)
                and entry.model != model
            ):
                device_registry.async_update_device(entry.id, model=model)

    def _async_reconcile_entity_registry(
        self, active_device_ids: set[str]
    ) -> None:
        """Disable removed-device entities without overriding user choices."""
        device_registry = dr.async_get(self.hass)
        entity_registry = er.async_get(self.hass)
        local_ids_by_registry_id: dict[str, str] = {}
        for device_entry in dr.async_entries_for_config_entry(
            device_registry, self.config_entry_id
        ):
            local_id = next(
                (
                    identifier[1]
                    for identifier in device_entry.identifiers
                    if identifier[0] == DOMAIN
                ),
                None,
            )
            if local_id is not None:
                local_ids_by_registry_id[device_entry.id] = local_id

        for entity_entry in er.async_entries_for_config_entry(
            entity_registry, self.config_entry_id
        ):
            if entity_entry.unique_id.startswith("radio-node:"):
                local_id = entity_entry.unique_id.partition("_")[0]
            else:
                local_id = local_ids_by_registry_id.get(
                    entity_entry.device_id or ""
                )
            if local_id is None:
                continue
            if local_id not in active_device_ids and entity_entry.disabled_by is None:
                entity_registry.async_update_entity(
                    entity_entry.entity_id,
                    disabled_by=er.RegistryEntryDisabler.INTEGRATION,
                )
            elif (
                local_id in active_device_ids
                and entity_entry.disabled_by
                == er.RegistryEntryDisabler.INTEGRATION
            ):
                entity_registry.async_update_entity(
                    entity_entry.entity_id,
                    disabled_by=None,
                )
