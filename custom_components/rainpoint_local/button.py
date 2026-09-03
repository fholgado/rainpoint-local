"""Buttons for RainPoint Local radio-node management."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import RainPointLocalError
from .const import CONF_TOKEN, DOMAIN
from .coordinator import RainPointLocalCoordinator
from .entity import RainPointLocalEntity
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
        token = str(
            entry.data.get(CONF_TOKEN, entry.options.get(CONF_TOKEN, ""))
        )
        for node_id, node in coordinator.nodes.items():
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
        for device_id, device in coordinator.data.items():
            if (
                (device_id, "resynchronize_counter") not in known
                and "counter_resynchronization"
                in device.get("capabilities", [])
            ):
                known.add((device_id, "resynchronize_counter"))
                entities.append(
                    RainPointHtv405ResynchronizeCounterButton(
                        coordinator, device_id, token
                    )
                )
            if (
                (device_id, "cancel_watering_request") not in known
                and "bounded_valve_control"
                in device.get("capabilities", [])
            ):
                known.add((device_id, "cancel_watering_request"))
                entities.append(
                    RainPointHtv405CancelWateringRequestButton(
                        coordinator, device_id, token
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


class RainPointHtv405ResynchronizeCounterButton(
    RainPointLocalEntity, ButtonEntity
):
    """Start fixed-anchor close-only synchronization for an idle HTV405."""

    _attr_translation_key = "resynchronize_valve_counter"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: RainPointLocalCoordinator,
        device_id: str,
        token: str,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._token = token
        self._attr_unique_id = f"{device_id}_resynchronize_counter"

    @property
    def available(self) -> bool:
        """Offer resynchronization only for a confirmed-idle lost counter."""
        return bool(
            super().available
            and self.decoded_state.get("rf_control_enabled") is True
            and self.decoded_state.get("is_watering") is False
            and self.decoded_state.get("rf_next_control_sequence") is None
            and self.decoded_state.get("rf_control_command_pending") is False
            and self.decoded_state.get("rf_control_transaction_active")
            is not True
            and self.decoded_state.get("rf_control_resync_state")
            == "ready"
        )

    @property
    def extra_state_attributes(self) -> dict:
        """Expose fixed-anchor progress without claiming a silent success."""
        return {
            "resync_state": self.decoded_state.get(
                "rf_control_resync_state"
            ),
            "candidate": self.decoded_state.get(
                "rf_control_resync_candidate"
            ),
            "candidate_position": self.decoded_state.get(
                "rf_control_resync_candidate_position"
            ),
            "candidate_count": self.decoded_state.get(
                "rf_control_resync_candidate_count"
            ),
            "candidate_attempt": self.decoded_state.get(
                "rf_control_resync_candidate_attempt"
            ),
            "last_result": self.decoded_state.get("rf_control_last_result"),
        }

    async def async_press(self) -> None:
        """Send the anchor; the gateway handles one bounded retry if needed."""
        try:
            await self.coordinator.client.resynchronize_htv405_counter(
                self._token,
                device_id=self.device_id,
            )
        except RainPointLocalError as error:
            raise HomeAssistantError(str(error)) from error
        await self.coordinator.async_request_refresh()


class RainPointHtv405CancelWateringRequestButton(
    RainPointLocalEntity, ButtonEntity
):
    """Cancel the non-actuating or queued-open portion of a transaction."""

    _attr_translation_key = "cancel_watering_request"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: RainPointLocalCoordinator,
        device_id: str,
        token: str,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._token = token
        self._attr_unique_id = f"{device_id}_cancel_watering_request"

    @property
    def available(self) -> bool:
        """Enable cancellation only before watering has been confirmed."""
        return bool(
            super().available
            and self.decoded_state.get("rf_control_transaction_state")
            in {
                "waiting_for_valve_report",
                "synchronizing",
                "waiting_for_command_interval",
            }
        )

    @property
    def extra_state_attributes(self) -> dict:
        """Show exactly which queued operation would be cancelled."""
        return {
            "transaction_state": self.decoded_state.get(
                "rf_control_transaction_state"
            ),
            "transaction_status": self.decoded_state.get(
                "rf_control_transaction_status"
            ),
            "zone": self.decoded_state.get("rf_control_transaction_zone"),
            "duration_seconds": self.decoded_state.get(
                "rf_control_transaction_duration_seconds"
            ),
        }

    async def async_press(self) -> None:
        """Cancel the queued request; this operation never transmits RF."""
        try:
            await self.coordinator.client.cancel_htv405_watering_transaction(
                self._token,
                device_id=self.device_id,
            )
        except RainPointLocalError as error:
            raise HomeAssistantError(str(error)) from error
        await self.coordinator.async_request_refresh()
