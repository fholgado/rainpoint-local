"""Shared RainPoint Local entity behavior."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import RainPointLocalCoordinator


class RainPointLocalEntity(CoordinatorEntity[RainPointLocalCoordinator]):
    """Base entity attached to one locally registered device."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: RainPointLocalCoordinator, device_id: str
    ) -> None:
        super().__init__(coordinator)
        self.device_id = device_id

    @property
    def device(self) -> dict[str, Any]:
        """Return the latest device snapshot."""
        return self.coordinator.data.get(
            self.device_id,
            {
                "device_id": self.device_id,
                "name": self.device_id,
                "available": False,
                "state": {},
            },
        )

    @property
    def decoded_state(self) -> dict[str, Any]:
        """Return decoded device state."""
        return self.device.get("state", {})

    @property
    def available(self) -> bool:
        """Return gateway-reported availability."""
        return bool(self.device.get("available", False))

    @property
    def device_info(self) -> DeviceInfo:
        """Group measurements beneath one HA device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=self.device.get("name", self.device_id),
            manufacturer="RainPoint",
            model=self.device.get("model"),
        )
