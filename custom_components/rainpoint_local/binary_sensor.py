"""Binary sensors for RainPoint Local."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
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
        entity
        for device_id, device in coordinator.data.items()
        for entity in _entities_for_device(coordinator, device_id, device)
    )


def _entities_for_device(
    coordinator: RainPointLocalCoordinator,
    device_id: str,
    device: dict,
) -> list[BinarySensorEntity]:
    """Create binary diagnostics supported by a device snapshot."""
    entities: list[BinarySensorEntity] = []
    if "is_watering" in device.get("state", {}):
        entities.append(RainPointWateringBinarySensor(coordinator, device_id))
    if "reporting" in device:
        entities.append(RainPointReportingBinarySensor(coordinator, device_id))
    return entities


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


class RainPointReportingBinarySensor(RainPointLocalEntity, BinarySensorEntity):
    """Report whether a device has checked in within its model threshold."""

    _attr_translation_key = "reporting"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: RainPointLocalCoordinator, device_id: str
    ) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_reporting"

    @property
    def is_on(self) -> bool | None:
        """Return current report freshness."""
        value = self.device.get("reporting")
        return bool(value) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict:
        """Expose age and threshold for troubleshooting."""
        return {
            "report_age_seconds": self.device.get("report_age_seconds"),
            "reporting_timeout_seconds": self.device.get(
                "reporting_timeout_seconds"
            ),
        }
