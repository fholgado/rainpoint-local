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
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import RainPointLocalCoordinator
from .entity import RainPointLocalEntity
from .node_entity import RainPointRadioNodeEntity


def _report_summary(device: dict[str, Any]) -> str:
    """Build a concise summary for the device Activity row."""
    state = device.get("state", {})
    parts: list[str] = []

    moisture = state.get("soil_moisture_percent")
    if isinstance(moisture, (int, float)):
        parts.append(f"Moisture {moisture:g}%")

    valve_state = state.get("valve_state")
    if isinstance(valve_state, str):
        parts.append(valve_state.replace("_", " ").title())

    duration = state.get("duration_seconds")
    if isinstance(duration, (int, float)):
        if duration % 60 == 0:
            parts.append(f"{duration / 60:g} min")
        else:
            parts.append(f"{duration:g} sec")

    usage = state.get("last_usage_liters")
    if isinstance(usage, (int, float)):
        parts.append(f"{usage:g} L")

    battery = state.get("battery_percent")
    if isinstance(battery, (int, float)):
        parts.append(f"Battery {battery:g}%")

    return " · ".join(parts) if parts else "Data received"


def _report_attributes(device: dict[str, Any]) -> dict[str, Any]:
    """Return useful report data without persisting raw RF frames."""
    state = device.get("state", {})
    attributes = {
        "event_id": device.get("last_event_id"),
        "model": device.get("model"),
        "summary": _report_summary(device),
        "rf_frame_success_percent": device.get("rf_frame_success_percent"),
    }
    for key in (
        "soil_moisture_percent",
        "valve_state",
        "is_watering",
        "duration_seconds",
        "last_usage_liters",
        "battery_percent",
        "rf_rssi_db",
    ):
        if key in state:
            attributes[key] = state[key]
    return attributes


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
        state_key="rf_rssi_db",
        native_unit_of_measurement="dB",
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
    RainPointSensorDescription(
        key="report_count",
        translation_key="report_count",
        state_key="report_count",
        device_field=True,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RainPointSensorDescription(
        key="average_report_interval",
        translation_key="average_report_interval",
        state_key="average_report_interval_seconds",
        device_field=True,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RainPointSensorDescription(
        key="longest_report_gap",
        translation_key="longest_report_gap",
        state_key="longest_report_gap_seconds",
        device_field=True,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RainPointSensorDescription(
        key="reception_success",
        translation_key="reception_success",
        state_key="rf_frame_success_percent",
        device_field=True,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


@dataclass(frozen=True, kw_only=True)
class RainPointNodeSensorDescription(SensorEntityDescription):
    """Describe one radio-node diagnostic field."""

    path: tuple[str, ...]


NODE_DESCRIPTIONS = (
    RainPointNodeSensorDescription(
        key="node_last_seen",
        translation_key="node_last_seen",
        path=("last_seen",),
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RainPointNodeSensorDescription(
        key="ip_address",
        translation_key="ip_address",
        path=("ip_address",),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RainPointNodeSensorDescription(
        key="wifi_signal_strength",
        translation_key="wifi_signal_strength",
        path=("wifi_rssi_dbm",),
        native_unit_of_measurement="dBm",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RainPointNodeSensorDescription(
        key="device_temperature",
        translation_key="device_temperature",
        path=("device_temperature_c",),
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RainPointNodeSensorDescription(
        key="uptime",
        translation_key="uptime",
        path=("uptime_seconds",),
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RainPointNodeSensorDescription(
        key="free_heap",
        translation_key="free_heap",
        path=("free_heap_bytes",),
        native_unit_of_measurement="B",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RainPointNodeSensorDescription(
        key="minimum_free_heap",
        translation_key="minimum_free_heap",
        path=("minimum_free_heap_bytes",),
        native_unit_of_measurement="B",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RainPointNodeSensorDescription(
        key="largest_free_block",
        translation_key="largest_free_block",
        path=("largest_free_block_bytes",),
        native_unit_of_measurement="B",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RainPointNodeSensorDescription(
        key="maximum_loop_gap",
        translation_key="maximum_loop_gap",
        path=("maximum_loop_gap_ms",),
        native_unit_of_measurement="ms",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RainPointNodeSensorDescription(
        key="network_bytes_sent",
        translation_key="network_bytes_sent",
        path=("network_bytes_sent",),
        native_unit_of_measurement="B",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RainPointNodeSensorDescription(
        key="network_bytes_received",
        translation_key="network_bytes_received",
        path=("network_bytes_received",),
        native_unit_of_measurement="B",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RainPointNodeSensorDescription(
        key="received_frames",
        translation_key="received_frames",
        path=("received_frames",),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RainPointNodeSensorDescription(
        key="duplicate_frames",
        translation_key="duplicate_frames",
        path=("duplicate_frames",),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RainPointNodeSensorDescription(
        key="invalid_messages",
        translation_key="invalid_messages",
        path=("invalid_messages",),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RainPointNodeSensorDescription(
        key="radio_packets",
        translation_key="radio_packets",
        path=("radio_health", "primary", "packets"),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RainPointNodeSensorDescription(
        key="radio_overflows",
        translation_key="radio_overflows",
        path=("radio_health", "primary", "overflows"),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RainPointNodeSensorDescription(
        key="wifi_reconnects",
        translation_key="wifi_reconnects",
        path=("wifi_reconnects",),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    RainPointNodeSensorDescription(
        key="gateway_authentications",
        translation_key="gateway_authentications",
        path=("gateway_authentications",),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


def _path_value(value: dict[str, Any], path: tuple[str, ...]) -> Any:
    """Read one nested diagnostic path."""
    current: Any = value
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


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
        for node_id, node in coordinator.nodes.items():
            for description in NODE_DESCRIPTIONS:
                identity = (f"radio-node:{node_id}", description.key)
                if (
                    _path_value(node, description.path) is None
                    or identity in known
                ):
                    continue
                known.add(identity)
                entities.append(
                    RainPointRadioNodeSensor(
                        coordinator, node_id, description
                    )
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
    def name(self) -> Any:
        """Include decoded report data in the timestamp Activity row."""
        if self.entity_description.key != "report_time":
            return super().name
        if self.entity_id is None:
            return "Device report time"
        return f"Last report · {_report_summary(self.device)}"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Attach structured report data to the last-report timestamp."""
        if self.entity_description.key == "report_time":
            return _report_attributes(self.device)
        if self.entity_description.key == "reception_success":
            return {
                key: self.device.get(key)
                for key in (
                    "valid_rf_frame_count",
                    "invalid_rf_frame_count",
                    "rf_frame_count",
                    "last_frame_at",
                    "last_valid_frame_at",
                    "last_invalid_frame_at",
                )
            }
        return None

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


class RainPointRadioNodeSensor(RainPointRadioNodeEntity, SensorEntity):
    """Expose one custom local radio-node diagnostic."""

    entity_description: RainPointNodeSensorDescription

    def __init__(
        self,
        coordinator: RainPointLocalCoordinator,
        node_id: str,
        description: RainPointNodeSensorDescription,
    ) -> None:
        super().__init__(coordinator, node_id)
        self.entity_description = description
        self._attr_unique_id = f"radio-node:{node_id}_{description.key}"

    @property
    def native_value(self) -> Any:
        """Return the current node diagnostic."""
        value = _path_value(self.node, self.entity_description.path)
        if self.entity_description.device_class != SensorDeviceClass.TIMESTAMP:
            return value
        if not isinstance(value, str):
            return None
        parsed = dt_util.parse_datetime(value)
        if parsed is not None and parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return parsed
