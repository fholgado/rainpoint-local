"""Supervised, duration-bounded RainPoint valve entities."""

from __future__ import annotations

from homeassistant.components.valve import ValveEntity, ValveEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import RainPointLocalError
from .const import CONF_TOKEN, DOMAIN
from .coordinator import RainPointLocalCoordinator
from .entity import RainPointLocalEntity


DEFAULT_BOUNDED_RUN_MINUTES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create four supervised valve entities for eligible HTV405 devices."""
    coordinator: RainPointLocalCoordinator = hass.data[DOMAIN][entry.entry_id]
    token = str(entry.data.get(CONF_TOKEN, entry.options.get(CONF_TOKEN, "")))
    known: set[tuple[str, int]] = set()

    @callback
    def async_add_missing_entities() -> None:
        entities: list[ValveEntity] = []
        for device_id, device in coordinator.data.items():
            if "bounded_valve_control" not in device.get("capabilities", []):
                continue
            for zone in range(1, 5):
                identity = (device_id, zone)
                if identity in known:
                    continue
                known.add(identity)
                entities.append(
                    RainPointHtv405ZoneValve(
                        coordinator, device_id, zone, token
                    )
                )
        if entities:
            async_add_entities(entities)

    async_add_missing_entities()
    entry.async_on_unload(
        coordinator.async_add_listener(async_add_missing_entities)
    )


class RainPointHtv405ZoneValve(RainPointLocalEntity, ValveEntity):
    """One mutually exclusive zone of an HTV405 four-zone timer."""

    _attr_translation_key = "htv405_zone"
    _attr_reports_position = False
    _attr_supported_features = (
        ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE
    )

    def __init__(
        self,
        coordinator: RainPointLocalCoordinator,
        device_id: str,
        zone: int,
        token: str,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._zone = zone
        self._token = token
        self._attr_unique_id = f"{device_id}_zone_{zone}_control"
        self._attr_translation_placeholders = {"zone": str(zone)}

    @property
    def available(self) -> bool:
        """Keep confirmed state visible while a command is pending."""
        return bool(
            super().available
            and self.decoded_state.get("rf_control_enabled") is True
        )

    @property
    def is_closed(self) -> bool | None:
        """Return only valve-originated state, never the requested command."""
        value = self.decoded_state.get(
            f"zone_{self._zone}_is_watering"
        )
        if isinstance(value, bool):
            return not value
        active_zone = self.decoded_state.get("active_zone")
        if isinstance(active_zone, int):
            return active_zone != self._zone
        watering = self.decoded_state.get("is_watering")
        if watering is False:
            return True
        return None

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the supervised duration and confirmation boundary."""
        run_minutes = self.coordinator.htv405_run_minutes.get(
            (self.device_id, self._zone), DEFAULT_BOUNDED_RUN_MINUTES
        )
        return {
            "zone": self._zone,
            "bounded_run_seconds": run_minutes * 60,
            "control_available": self.decoded_state.get(
                "rf_control_available"
            ),
            "control_unavailable_reason": self.decoded_state.get(
                "rf_control_unavailable_reason"
            ),
            "command_pending": self.decoded_state.get(
                "rf_control_command_pending"
            ),
            "last_result": self.decoded_state.get("rf_control_last_result"),
            "recovery_sequence": self.decoded_state.get(
                "rf_control_recovery_sequence"
            ),
            "recovery_attempt": self.decoded_state.get(
                "rf_control_recovery_attempt"
            ),
            "recovery_not_before": self.decoded_state.get(
                "rf_control_recovery_not_before"
            ),
            "confirmed_at": self.decoded_state.get(
                "rf_control_confirmed_at"
            ),
        }

    async def async_open_valve(self, **kwargs) -> None:
        """Start one duration-bounded supervised run."""
        if self.decoded_state.get("rf_control_available") is not True:
            raise HomeAssistantError(
                self.decoded_state.get("rf_control_unavailable_reason")
                or "RainPoint valve control is unavailable"
            )
        try:
            run_minutes = self.coordinator.htv405_run_minutes.get(
                (self.device_id, self._zone), DEFAULT_BOUNDED_RUN_MINUTES
            )
            await self.coordinator.client.open_htv405_zone(
                self._token,
                device_id=self.device_id,
                zone=self._zone,
                duration_seconds=run_minutes * 60,
            )
        except RainPointLocalError as error:
            raise HomeAssistantError(str(error)) from error
        await self.coordinator.async_request_refresh()

    async def async_close_valve(self, **kwargs) -> None:
        """Stop this zone early when it is confirmed active."""
        try:
            await self.coordinator.client.close_htv405_zone(
                self._token,
                device_id=self.device_id,
                zone=self._zone,
            )
        except RainPointLocalError as error:
            raise HomeAssistantError(str(error)) from error
        await self.coordinator.async_request_refresh()
