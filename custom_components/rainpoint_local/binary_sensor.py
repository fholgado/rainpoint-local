"""Binary sensors for RainPoint Local."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import RainPointLocalCoordinator
from .entity import RainPointLocalEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create read-only watering state entities."""
    coordinator: RainPointLocalCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        RainPointWateringBinarySensor(coordinator, device_id)
        for device_id, device in coordinator.data.items()
        if "is_watering" in device.get("state", {})
    )


class RainPointWateringBinarySensor(RainPointLocalEntity, BinarySensorEntity):
    """Report whether a valve says it is watering."""

    _attr_translation_key = "watering"

    def __init__(
        self, coordinator: RainPointLocalCoordinator, device_id: str
    ) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_watering"

    @property
    def is_on(self) -> bool | None:
        """Return reported watering state."""
        value = self.decoded_state.get("is_watering")
        return bool(value) if value is not None else None
