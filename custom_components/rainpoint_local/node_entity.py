"""Shared entities for custom local ESP32/CC1101 radio nodes."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import RainPointLocalCoordinator


class RainPointRadioNodeEntity(
    CoordinatorEntity[RainPointLocalCoordinator]
):
    """Base entity attached to one custom local radio node."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: RainPointLocalCoordinator, node_id: str
    ) -> None:
        super().__init__(coordinator)
        self.node_id = node_id

    @property
    def node(self) -> dict[str, Any]:
        """Return the latest radio-node snapshot."""
        return self.coordinator.nodes.get(
            self.node_id,
            {"node_id": self.node_id, "connected": False},
        )

    @property
    def available(self) -> bool:
        """Return whether the node has an authenticated gateway session."""
        return bool(
            self.node.get("connected") and self.node.get("authenticated")
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Group diagnostics beneath one custom local radio-node device."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"radio-node:{self.node_id}")},
            name=self.node.get("name", self.node_id),
            manufacturer="RainPoint Local",
            model="ESP32/CC1101 radio node",
            sw_version=self.node.get("firmware_version"),
            suggested_area=self.node.get("area"),
        )
