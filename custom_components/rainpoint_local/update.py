"""Firmware updates for custom local RainPoint radio nodes."""

from __future__ import annotations

from typing import Any

from homeassistant.components import network
from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import RainPointLocalError
from .const import CONF_TOKEN, DOMAIN
from .coordinator import RainPointLocalCoordinator
from .node_entity import RainPointRadioNodeEntity


IN_PROGRESS_STATES = {
    "requested",
    "downloading",
    "ready_to_reboot",
    "awaiting_health_confirmation",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add one update entity for each catalogue-compatible radio node."""
    coordinator: RainPointLocalCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def async_add_missing_entities() -> None:
        entities = []
        for node_id, node in coordinator.nodes.items():
            if node_id in known or not isinstance(
                node.get("firmware_update"), dict
            ):
                continue
            known.add(node_id)
            entities.append(
                RainPointRadioNodeFirmwareUpdate(
                    coordinator,
                    node_id,
                    str(entry.data.get(CONF_TOKEN, "")),
                )
            )
        if entities:
            async_add_entities(entities)

    async_add_missing_entities()
    entry.async_on_unload(
        coordinator.async_add_listener(async_add_missing_entities)
    )


class RainPointRadioNodeFirmwareUpdate(
    RainPointRadioNodeEntity, UpdateEntity
):
    """Install one compatible gateway-catalogued firmware release."""

    _attr_translation_key = "radio_node_firmware"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_entity_category = EntityCategory.CONFIG
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.PROGRESS
        | UpdateEntityFeature.RELEASE_NOTES
    )
    _attr_title = "RainPoint radio node firmware"

    def __init__(
        self,
        coordinator: RainPointLocalCoordinator,
        node_id: str,
        token: str,
    ) -> None:
        super().__init__(coordinator, node_id)
        self._token = token
        self._attr_unique_id = f"radio-node:{node_id}_firmware"

    @property
    def release(self) -> dict[str, Any]:
        value = self.node.get("firmware_update")
        return value if isinstance(value, dict) else {}

    @property
    def installed_version(self) -> str | None:
        value = self.node.get("firmware_version")
        return value if isinstance(value, str) else None

    @property
    def latest_version(self) -> str | None:
        value = self.release.get("version")
        return value if isinstance(value, str) else None

    @property
    def release_summary(self) -> str | None:
        value = self.release.get("release_summary")
        return value if isinstance(value, str) and value else None

    @property
    def release_url(self) -> str | None:
        value = self.release.get("release_url")
        return value if isinstance(value, str) and value else None

    @property
    def in_progress(self) -> bool:
        return self.node.get("firmware_update_state") in IN_PROGRESS_STATES

    @property
    def update_percentage(self) -> float | None:
        state = self.node.get("firmware_update_state")
        if state in {"ready_to_reboot", "awaiting_health_confirmation"}:
            return 100.0
        if state not in IN_PROGRESS_STATES:
            return None
        received = self.node.get("firmware_update_received_bytes")
        total = self.node.get("firmware_update_total_bytes")
        if not isinstance(received, int) or not isinstance(total, int) or total <= 0:
            return 0.0
        return round(min(100.0, max(0.0, received * 100 / total)), 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "channel": self.release.get("channel"),
            "update_state": self.node.get("firmware_update_state"),
            "update_detail": self.node.get("firmware_update_detail"),
            "candidate_pending": self.node.get("firmware_candidate_pending"),
            "boot_attempts": self.node.get("firmware_update_boot_attempts"),
        }

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Ask the gateway to install its latest compatible local release."""
        release_id = self.release.get("release_id")
        if not isinstance(release_id, str) or not release_id:
            raise HomeAssistantError("No compatible radio-node release is staged")
        if version is not None and version != self.latest_version:
            raise HomeAssistantError("Specific firmware versions are not supported")
        try:
            public_host = await network.async_get_source_ip(self.hass)
            await self.coordinator.client.install_radio_node_firmware(
                self._token,
                node_id=self.node_id,
                release_id=release_id,
                public_host=str(public_host),
            )
        except RainPointLocalError as exc:
            raise HomeAssistantError(
                f"Unable to start radio-node firmware update: {exc}"
            ) from exc
        await self.coordinator.async_request_refresh()

    async def async_release_notes(self) -> str | None:
        value = self.release.get("release_notes")
        return value if isinstance(value, str) and value else self.release_summary
