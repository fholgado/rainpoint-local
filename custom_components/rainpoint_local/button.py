"""Buttons for RainPoint Local radio-node management."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_TOKEN, DOMAIN
from .coordinator import RainPointLocalCoordinator
from .node_entity import RainPointRadioNodeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add management buttons for capable radio nodes."""
    coordinator: RainPointLocalCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[tuple[str, str]] = set()

    @callback
    def async_add_missing_entities() -> None:
        entities = []
        for node_id, node in coordinator.nodes.items():
            token = str(entry.data.get(CONF_TOKEN, ""))
            if (
                (node_id, "identify") not in known
                and "identify" in node.get("capabilities", [])
            ):
                known.add((node_id, "identify"))
                entities.append(
                    RainPointRadioNodeIdentifyButton(
                        coordinator, node_id, token
                    )
                )
            if (
                (node_id, "reboot") not in known
                and "node_reboot" in node.get("capabilities", [])
            ):
                known.add((node_id, "reboot"))
                entities.append(
                    RainPointRadioNodeRebootButton(
                        coordinator, node_id, token
                    )
                )
        if entities:
            async_add_entities(entities)

    async_add_missing_entities()
    entry.async_on_unload(
        coordinator.async_add_listener(async_add_missing_entities)
    )


class RainPointRadioNodeIdentifyButton(RainPointRadioNodeEntity, ButtonEntity):
    """Blink a node's onboard status LED for physical identification."""

    _attr_translation_key = "identify_radio_node"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: RainPointLocalCoordinator,
        node_id: str,
        token: str,
    ) -> None:
        super().__init__(coordinator, node_id)
        self._token = token
        self._attr_unique_id = f"radio-node:{node_id}_identify"

    async def async_press(self) -> None:
        """Request a 15-second bounded identification blink."""
        await self.coordinator.client.identify_radio_node(
            self._token, self.node_id, 15
        )
        await self.coordinator.async_request_refresh()


class RainPointRadioNodeRebootButton(RainPointRadioNodeEntity, ButtonEntity):
    """Restart a node without erasing its adoption or configuration."""

    _attr_translation_key = "reboot_radio_node"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: RainPointLocalCoordinator,
        node_id: str,
        token: str,
    ) -> None:
        super().__init__(coordinator, node_id)
        self._token = token
        self._attr_unique_id = f"radio-node:{node_id}_reboot"

    async def async_press(self) -> None:
        """Restart the node; firmware boots back into normal RF mode."""
        await self.coordinator.client.reboot_radio_node(
            self._token, self.node_id
        )
        await self.coordinator.async_request_refresh()
