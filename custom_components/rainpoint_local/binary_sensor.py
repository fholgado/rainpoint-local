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
from .node_entity import RainPointRadioNodeEntity


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
        for node_id in coordinator.nodes:
            identity = (f"radio-node:{node_id}", "connected")
            if identity not in known:
                known.add(identity)
                entities.append(
                    RainPointRadioNodeConnectivity(coordinator, node_id)
                )
            armed_identity = (f"radio-node:{node_id}", "tx_armed")
            if armed_identity not in known:
                known.add(armed_identity)
                entities.append(
                    RainPointRadioNodeTxArmed(coordinator, node_id)
                )
            reboot_identity = (f"radio-node:{node_id}", "reboot_pending")
            if reboot_identity not in known:
                known.add(reboot_identity)
                entities.append(
                    RainPointRadioNodeRebootPending(coordinator, node_id)
                )
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
    for zone in range(1, 5):
        key = f"zone_{zone}_is_watering"
        if key in device.get("state", {}):
            entities.append(
                (
                    key,
                    RainPointZoneWateringBinarySensor(
                        coordinator, device_id, zone
                    ),
                )
            )
    if "reporting" in device:
        entities.append(
            ("reporting", RainPointReportingBinarySensor(coordinator, device_id))
        )
    if "rf_control_start_available" in device.get("state", {}):
        entities.append(
            (
                "control_start_available",
                RainPointControlStartAvailableBinarySensor(
                    coordinator, device_id
                ),
            )
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


class RainPointZoneWateringBinarySensor(
    RainPointLocalEntity, BinarySensorEntity
):
    """Report whether one zone of a multi-zone valve is watering."""

    _attr_translation_key = "zone_watering"

    def __init__(
        self,
        coordinator: RainPointLocalCoordinator,
        device_id: str,
        zone: int,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._zone = zone
        self._attr_unique_id = f"{device_id}_zone_{zone}_watering"
        self._attr_translation_placeholders = {"zone": str(zone)}

    @property
    def is_on(self) -> bool | None:
        """Return the zone's reported watering state."""
        value = self.decoded_state.get(f"zone_{self._zone}_is_watering")
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


class RainPointControlStartAvailableBinarySensor(
    RainPointLocalEntity, BinarySensorEntity
):
    """Expose whether Home Assistant may start a new valve transaction."""

    _attr_translation_key = "control_start_available"

    def __init__(
        self, coordinator: RainPointLocalCoordinator, device_id: str
    ) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_control_start_available"

    @property
    def is_on(self) -> bool | None:
        """Return the gateway-owned start gate."""
        value = self.decoded_state.get("rf_control_start_available")
        return bool(value) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict:
        """Explain why a new request is currently unavailable."""
        return {
            "unavailable_reason": self.decoded_state.get(
                "rf_control_start_unavailable_reason"
            ),
            "transaction_state": self.decoded_state.get(
                "rf_control_transaction_state"
            ),
            "transaction_status": self.decoded_state.get(
                "rf_control_transaction_status"
            ),
        }


class RainPointRadioNodeConnectivity(
    RainPointRadioNodeEntity, BinarySensorEntity
):
    """Report whether a custom local radio node is authenticated."""

    _attr_translation_key = "radio_node_connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: RainPointLocalCoordinator, node_id: str
    ) -> None:
        super().__init__(coordinator, node_id)
        self._attr_unique_id = f"radio-node:{node_id}_connected"

    @property
    def is_on(self) -> bool:
        """Return authenticated connection state."""
        return bool(
            self.node.get("connected") and self.node.get("authenticated")
        )

    @property
    def available(self) -> bool:
        """Keep connectivity state visible while the node is offline."""
        return True


class RainPointRadioNodeTxArmed(RainPointRadioNodeEntity, BinarySensorEntity):
    """Expose the fail-closed RF transmitter state."""

    _attr_translation_key = "radio_node_tx_armed"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: RainPointLocalCoordinator, node_id: str
    ) -> None:
        super().__init__(coordinator, node_id)
        self._attr_unique_id = f"radio-node:{node_id}_tx_armed"

    @property
    def is_on(self) -> bool:
        """Return whether bounded pairing transmission is armed."""
        return self.node.get("tx_armed") is True


class RainPointRadioNodeRebootPending(
    RainPointRadioNodeEntity, BinarySensorEntity
):
    """Expose whether the node accepted a deferred reboot request."""

    _attr_translation_key = "radio_node_reboot_pending"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: RainPointLocalCoordinator, node_id: str
    ) -> None:
        super().__init__(coordinator, node_id)
        self._attr_unique_id = f"radio-node:{node_id}_reboot_pending"

    @property
    def is_on(self) -> bool:
        """Return whether a reboot has been scheduled but not observed."""
        return self.node.get("node_reboot_pending") is True
