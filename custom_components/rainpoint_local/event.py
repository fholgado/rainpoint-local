"""Device report events for RainPoint Local."""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import RainPointLocalCoordinator
from .entity import RainPointLocalEntity

EVENT_REPORT_RECEIVED = "report_received"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one report event entity for every registered RF device."""
    coordinator: RainPointLocalCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def async_add_missing_entities() -> None:
        entities = []
        for device_id in coordinator.data:
            if device_id in known:
                continue
            known.add(device_id)
            entities.append(RainPointReportEvent(coordinator, device_id))
        if entities:
            async_add_entities(entities)

    async_add_missing_entities()
    entry.async_on_unload(
        coordinator.async_add_listener(async_add_missing_entities)
    )


class RainPointReportEvent(RainPointLocalEntity, EventEntity):
    """Record each newly received RF report in Home Assistant activity."""

    _attr_translation_key = "report_received"
    _attr_event_types = [EVENT_REPORT_RECEIVED]

    def __init__(
        self, coordinator: RainPointLocalCoordinator, device_id: str
    ) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_report_received"
        self._last_event_id = self._event_id(self.device)

    @staticmethod
    def _event_id(device: dict[str, Any]) -> int:
        """Return a stable event cursor from a device snapshot."""
        value = device.get("last_event_id", 0)
        return value if isinstance(value, int) else 0

    @callback
    def _handle_coordinator_update(self) -> None:
        """Publish an HA event whenever rainpointd observes a new RF report."""
        event_id = self._event_id(self.device)
        if event_id > self._last_event_id:
            self._trigger_event(
                EVENT_REPORT_RECEIVED,
                {
                    "event_id": event_id,
                    "observed_at": self.device.get("observed_at"),
                },
            )
            self._last_event_id = event_id
        super()._handle_coordinator_update()
