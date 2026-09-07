"""Supervised, duration-bounded RainPoint valve entities."""

from __future__ import annotations

from homeassistant.components.valve import ValveEntity, ValveEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import RainPointLocalError
from .api_models import multi_zone_numbers
from .const import CONF_TOKEN, DOMAIN
from .coordinator import RainPointLocalCoordinator
from .entity import RainPointLocalEntity


DEFAULT_BOUNDED_RUN_MINUTES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create controls for each enrolled valve without inventing outlets."""
    coordinator: RainPointLocalCoordinator = hass.data[DOMAIN][entry.entry_id]
    token = str(entry.data.get(CONF_TOKEN, entry.options.get(CONF_TOKEN, "")))
    known: set[tuple[str, int]] = set()

    @callback
    def async_add_missing_entities() -> None:
        entities: list[ValveEntity] = []
        for device_id, device in coordinator.data.items():
            if (device.get("model") == "HTV145FRF"
                    and "bounded_single_valve_control" in device.get("capabilities", [])):
                if (device_id, 1) not in known:
                    known.add((device_id, 1))
                    entities.append(RainPointSingleValve(coordinator, device_id, token))
                continue
            if "bounded_valve_control" not in device.get("capabilities", []):
                continue
            for zone in multi_zone_numbers(device):
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
    def supported_features(self) -> ValveEntityFeature:
        """Disable actuation controls while a transaction is in progress."""
        if (
            self.decoded_state.get("rf_control_transaction_active") is True
            or self.decoded_state.get("rf_control_command_pending") is True
        ):
            return ValveEntityFeature(0)
        if self.is_closed is False:
            return (
                ValveEntityFeature.CLOSE
                if self.decoded_state.get("rf_control_available") is True
                else ValveEntityFeature(0)
            )
        if self.is_closed is True:
            return (
                ValveEntityFeature.OPEN
                if self.decoded_state.get("rf_control_start_available") is True
                else ValveEntityFeature(0)
            )
        return ValveEntityFeature(0)

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
            "start_available": self.decoded_state.get(
                "rf_control_start_available"
            ),
            "start_unavailable_reason": self.decoded_state.get(
                "rf_control_start_unavailable_reason"
            ),
            "command_pending": self.decoded_state.get(
                "rf_control_command_pending"
            ),
            "transaction_state": self.decoded_state.get(
                "rf_control_transaction_state"
            ),
            "transaction_id": self.decoded_state.get(
                "rf_control_transaction_id"
            ),
            "transaction_status": self.decoded_state.get(
                "rf_control_transaction_status"
            ),
            "transaction_active": self.decoded_state.get(
                "rf_control_transaction_active"
            ),
            "transaction_zone": self.decoded_state.get(
                "rf_control_transaction_zone"
            ),
            "transaction_duration_seconds": self.decoded_state.get(
                "rf_control_transaction_duration_seconds"
            ),
            "transaction_not_before": self.decoded_state.get(
                "rf_control_transaction_not_before"
            ),
            "transaction_error": self.decoded_state.get(
                "rf_control_transaction_error"
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
        if self.decoded_state.get("rf_control_start_available") is not True:
            raise HomeAssistantError(
                self.decoded_state.get("rf_control_start_unavailable_reason")
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
        # Run Now waits for this command's transaction ID. A debounced request
        # can return with the previous snapshot during HA's refresh cooldown.
        # Fetch authoritative state before returning; never infer watering from
        # the successful POST itself.
        await self.coordinator.async_refresh()

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
        await self.coordinator.async_refresh()


class RainPointSingleValve(RainPointHtv405ZoneValve):
    """One duration-bounded outlet on an HTV145 timer."""

    _attr_translation_key = "single_valve"

    def __init__(self, coordinator, device_id: str, token: str) -> None:
        super().__init__(coordinator, device_id, 1, token)
        self._attr_unique_id = f"{device_id}_control"
        self._attr_translation_placeholders = {}

    @property
    def is_closed(self) -> bool | None:
        watering = self.decoded_state.get("is_watering")
        return not watering if isinstance(watering, bool) else None

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "bounded_run_seconds": self.coordinator.htv405_run_minutes.get(
                (self.device_id, 1), DEFAULT_BOUNDED_RUN_MINUTES) * 60,
            "control_available": self.decoded_state.get("rf_control_available"),
            "start_unavailable_reason": self.decoded_state.get("rf_control_start_unavailable_reason"),
            "command_pending": self.decoded_state.get("rf_control_command_pending"),
            "confirmed_at": self.decoded_state.get("rf_control_confirmed_at"),
            "expected_idle_at": self.decoded_state.get("rf_control_expected_idle_at"),
            "overdue": self.decoded_state.get("rf_control_overdue"),
        }

    async def async_open_valve(self, **kwargs) -> None:
        if self.decoded_state.get("rf_control_start_available") is not True:
            raise HomeAssistantError("Valve is not ready; inspect its counter and radio status")
        minutes = self.coordinator.htv405_run_minutes.get(
            (self.device_id, 1), DEFAULT_BOUNDED_RUN_MINUTES)
        try:
            await self.coordinator.client.open_single_valve(
                self._token, device_id=self.device_id, duration_seconds=minutes * 60)
        except RainPointLocalError as error:
            raise HomeAssistantError(str(error)) from error
        await self.coordinator.async_refresh()

    async def async_close_valve(self, **kwargs) -> None:
        try:
            await self.coordinator.client.close_single_valve(
                self._token, device_id=self.device_id)
        except RainPointLocalError as error:
            raise HomeAssistantError(str(error)) from error
        await self.coordinator.async_refresh()
