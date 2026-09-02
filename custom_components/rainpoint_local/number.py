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
MINIMUM_RUN_MINUTES = 1
MAXIMUM_RUN_MINUTES = 60
RUN_MINUTE_STEP = 1


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
    _attr_native_min_value = MINIMUM_RUN_MINUTES
    _attr_native_max_value = MAXIMUM_RUN_MINUTES
    _attr_native_step = RUN_MINUTE_STEP
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
        """Store one duration inside the gateway-declared continuous range."""
        minutes = int(value)
        minimum, maximum, step = self._duration_range()
        if (
            value != minutes
            or minutes < minimum
            or minutes > maximum
            or (minutes - minimum) % step
        ):
            raise ValueError(
                "duration must be between "
                f"{minimum} and {maximum} minutes in {step}-minute steps"
            )
        self.coordinator.htv405_run_minutes[
            (self.device_id, self._zone)
        ] = minutes
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the continuous duration capability."""
        minimum, maximum, step = self._duration_range()
        return {
            "duration_min_minutes": minimum,
            "duration_max_minutes": maximum,
            "duration_step_minutes": step,
        }

    def _duration_range(self) -> tuple[int, int, int]:
        """Use a sane gateway range or the integration's bounded fallback."""
        values = tuple(
            self.decoded_state.get(key)
            for key in (
                "rf_control_duration_min_minutes",
                "rf_control_duration_max_minutes",
                "rf_control_duration_step_minutes",
            )
        )
        if (
            all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in values
            )
            and MINIMUM_RUN_MINUTES
            <= values[0]
            <= values[1]
            <= MAXIMUM_RUN_MINUTES
            and 1 <= values[2] <= values[1] - values[0] + 1
        ):
            return values
        return MINIMUM_RUN_MINUTES, MAXIMUM_RUN_MINUTES, RUN_MINUTE_STEP
