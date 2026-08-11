"""Binary sensors for RainPoint Local."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import RainPointLocalCoordinator
from .entity import RainPointLocalEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create binary entities and add newly paired devices dynamically."""
    coordinator: RainPointLocalCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[tuple[str, str]] = set()

    @callback
    def async_add_missing_entities() -> None:
        entities: list[BinarySensorEntity] = []
        for device_id, device in coordinator.data.items():
            for key, entity in _entities_for_device(
                coordinator, device_id, device
            ):
                identity = (device_id, key)
                if identity in known:
                    continue
                known.add(identity)
                entities.append(entity)
        if entities:
            async_add_entities(entities)

    async_add_missing_entities()
    entry.async_on_unload(
        coordinator.async_add_listener(async_add_missing_entities)
    )


def _entities_for_device(
    coordinator: RainPointLocalCoordinator,
    device_id: str,
    device: dict,
) -> list[tuple[str, BinarySensorEntity]]:
    """Create binary diagnostics supported by a device snapshot."""
    entities: list[tuple[str, BinarySensorEntity]] = []
    if "is_watering" in device.get("state", {}):
        entities.append(
            ("watering", RainPointWateringBinarySensor(coordinator, device_id))
        )
    if "reporting" in device:
        entities.append(
            ("reporting", RainPointReportingBinarySensor(coordinator, device_id))
        )
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
