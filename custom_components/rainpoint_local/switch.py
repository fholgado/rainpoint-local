"""Bounded RF-transmission controls for RainPoint radio nodes."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_TOKEN, DOMAIN
from .coordinator import RainPointLocalCoordinator
from .node_entity import RainPointRadioNodeEntity
from .entity import RainPointLocalEntity
from .api import RainPointLocalError


DEFAULT_RECEIVE_ONLY_SECONDS = 30 * 60


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add one RF-transmission switch per capable node."""
    coordinator: RainPointLocalCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def async_add_missing_entities() -> None:
        entities = []
        for node_id, node in coordinator.nodes.items():
            if (
                node_id in known
                or "rf_maintenance" not in node.get("capabilities", [])
            ):
                continue
            known.add(node_id)
            entities.append(
                RainPointRadioNodeRfTransmissionsSwitch(
                    coordinator,
                    node_id,
                    str(entry.data.get(CONF_TOKEN, "")),
                )
            )
        for device_id, device in coordinator.data.items():
            if device_id in known or "morning_synchronization" not in device.get("capabilities", []):
                continue
            known.add(device_id)
            entities.append(RainPointMorningSyncSwitch(coordinator, device_id,
                str(entry.data.get(CONF_TOKEN, entry.options.get(CONF_TOKEN, "")))))
        if entities:
            async_add_entities(entities)

    async_add_missing_entities()
    entry.async_on_unload(
        coordinator.async_add_listener(async_add_missing_entities)
    )


class RainPointRadioNodeRfTransmissionsSwitch(
    RainPointRadioNodeEntity, SwitchEntity
):
    """Temporarily silence or explicitly restore a node's RF transmitter."""

    _attr_translation_key = "radio_node_rf_transmissions"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: RainPointLocalCoordinator,
        node_id: str,
        token: str,
    ) -> None:
        super().__init__(coordinator, node_id)
        self._token = token
        self._attr_unique_id = f"radio-node:{node_id}_rf_transmissions"

    @property
    def is_on(self) -> bool | None:
        """Return true for normal RF operation and false for receive-only."""
        mode = self.node.get("rf_mode")
        if mode == "normal":
            return True
        if mode == "receive_only":
            return False
        return None

    async def async_turn_off(self, **kwargs: object) -> None:
        """Silence RF transmission for 30 minutes, then auto-recover."""
        await self.coordinator.client.set_radio_node_rf_mode(
            self._token,
            self.node_id,
            "receive_only",
            DEFAULT_RECEIVE_ONLY_SECONDS,
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: object) -> None:
        """Restore normal RF transmission immediately."""
        await self.coordinator.client.set_radio_node_rf_mode(
            self._token, self.node_id, "normal"
        )
        await self.coordinator.async_request_refresh()


class RainPointMorningSyncSwitch(RainPointLocalEntity, SwitchEntity):
    """Enable daily synchronization and direct daytime watering together."""

    _attr_translation_key = "morning_sync"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, device_id: str, token: str) -> None:
        super().__init__(coordinator, device_id)
        self._token = token
        self._attr_unique_id = f"{device_id}_morning_sync"

    @property
    def is_on(self) -> bool:
        return self.decoded_state.get("rf_morning_sync_enabled") is True

    async def _set_enabled(self, enabled: bool) -> None:
        try:
            await self.coordinator.client.configure_morning_sync(self._token,
                device_id=self.device_id, enabled=enabled, timezone=self.hass.config.time_zone)
        except RainPointLocalError as error:
            raise HomeAssistantError(str(error)) from error
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        await self._set_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set_enabled(False)
