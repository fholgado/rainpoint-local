"""Duration controls for supervised RainPoint valve runs."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import RainPointLocalCoordinator
from .entity import RainPointLocalEntity


DEFAULT_RUN_MINUTES = 1
MAXIMUM_RUN_MINUTES = 60


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one bounded duration control for each HTV405 zone."""
    coordinator: RainPointLocalCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[tuple[str, int]] = set()

    @callback
    def async_add_missing_entities() -> None:
        entities: list[NumberEntity] = []
        for device_id, device in coordinator.data.items():
            if "bounded_valve_control" not in device.get("capabilities", []):
                continue
            for zone in range(1, 5):
                identity = (device_id, zone)
                if identity in known:
                    continue
                known.add(identity)
                entities.append(
                    RainPointHtv405ZoneDuration(
                        coordinator, device_id, zone
                    )
                )
        if entities:
            async_add_entities(entities)

    async_add_missing_entities()
    entry.async_on_unload(
        coordinator.async_add_listener(async_add_missing_entities)
    )


class RainPointHtv405ZoneDuration(RainPointLocalEntity, NumberEntity):
    """Configure the next bounded run for one valve zone."""

    _attr_translation_key = "htv405_zone_duration"
    _attr_native_min_value = 1
    _attr_native_max_value = MAXIMUM_RUN_MINUTES
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: RainPointLocalCoordinator,
        device_id: str,
        zone: int,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._zone = zone
        self._attr_unique_id = f"{device_id}_zone_{zone}_duration"
        self._attr_translation_placeholders = {"zone": str(zone)}
        coordinator.htv405_run_minutes.setdefault(
            (device_id, zone), DEFAULT_RUN_MINUTES
        )

    @property
    def native_value(self) -> float:
        """Return the duration used by the next open command."""
        return float(
            self.coordinator.htv405_run_minutes[
                (self.device_id, self._zone)
            ]
        )

    async def async_set_native_value(self, value: float) -> None:
        """Store one whole-minute duration in coordinator memory."""
        minutes = int(value)
        if value != minutes or not 1 <= minutes <= MAXIMUM_RUN_MINUTES:
            raise ValueError("duration must be 1-60 whole minutes")
        self.coordinator.htv405_run_minutes[
            (self.device_id, self._zone)
        ] = minutes
        self.async_write_ha_state()
