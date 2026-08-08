"""Sensor entities for RainPoint Local."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    PERCENTAGE,
    UnitOfTime,
    UnitOfVolume,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import RainPointLocalCoordinator
from .entity import RainPointLocalEntity


@dataclass(frozen=True, kw_only=True)
class RainPointSensorDescription(SensorEntityDescription):
    """Describe a decoded gateway state field."""

    state_key: str
    device_field: bool = False


DESCRIPTIONS = (
    RainPointSensorDescription(
        key="soil_moisture",
        translation_key="soil_moisture",
        state_key="soil_moisture_percent",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.MOISTURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    RainPointSensorDescription(
        key="battery",
        translation_key="battery",
        state_key="battery_percent",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RainPointSensorDescription(
        key="signal_strength",
        translation_key="signal_strength",
        state_key="rssi_dbm",
        native_unit_of_measurement="dBm",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RainPointSensorDescription(
        key="valve_state",
        translation_key="valve_state",
        state_key="valve_state",
    ),
    RainPointSensorDescription(
        key="duration",
        translation_key="duration",
        state_key="duration_seconds",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
    ),
    RainPointSensorDescription(
        key="last_usage",
        translation_key="last_usage",
        state_key="last_usage_liters",
        native_unit_of_measurement=UnitOfVolume.LITERS,
        device_class=SensorDeviceClass.WATER,
    ),
    RainPointSensorDescription(
        key="report_time",
        translation_key="report_time",
        state_key="observed_at",
        device_field=True,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create sensors for fields present in the initial snapshot."""
    coordinator: RainPointLocalCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[tuple[str, str]] = set()

    @callback
    def async_add_missing_entities() -> None:
        entities = []
        for device_id, device in coordinator.data.items():
            state = device.get("state", {})
            for description in DESCRIPTIONS:
                identity = (device_id, description.key)
                source = device if description.device_field else state
                if description.state_key not in source or identity in known:
                    continue
                known.add(identity)
                entities.append(
                    RainPointLocalSensor(coordinator, device_id, description)
                )
        if entities:
            async_add_entities(entities)

    async_add_missing_entities()
    entry.async_on_unload(
        coordinator.async_add_listener(async_add_missing_entities)
    )


class RainPointLocalSensor(RainPointLocalEntity, SensorEntity):
    """Expose one decoded field."""

    entity_description: RainPointSensorDescription

    def __init__(
        self,
        coordinator: RainPointLocalCoordinator,
        device_id: str,
        description: RainPointSensorDescription,
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def native_value(self) -> Any:
        """Return the current decoded value."""
        description = self.entity_description
        source = self.device if description.device_field else self.decoded_state
        value = source.get(description.state_key)
        if description.device_class != SensorDeviceClass.TIMESTAMP:
            return value
        if not isinstance(value, str):
            return None
        parsed: datetime | None = dt_util.parse_datetime(value)
        if parsed is None:
            return None
        # rtl_433 timestamps use the add-on's local clock but omit its offset.
        # Timestamp sensors require a timezone-aware value.
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return parsed
