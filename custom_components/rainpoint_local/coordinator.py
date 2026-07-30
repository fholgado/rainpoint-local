"""Data coordinator for RainPoint Local."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import RainPointLocalClient, RainPointLocalError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class RainPointLocalCoordinator(DataUpdateCoordinator[dict[str, dict]]):
    """Poll local gateway snapshots."""

    def __init__(self, hass: HomeAssistant, client: RainPointLocalClient) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, dict]:
        try:
            devices = await self.client.devices()
        except RainPointLocalError as exc:
            raise UpdateFailed(f"Unable to update from rainpointd: {exc}") from exc
        return {device["device_id"]: device for device in devices}
