"""Local morning maintenance time, stored by the gateway."""

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from .api import RainPointLocalError
from .const import CONF_TOKEN, DOMAIN
from .entity import RainPointLocalEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    known = set()

    @callback
    def add_missing() -> None:
        entities = []
        for device_id, device in coordinator.data.items():
            if device_id in known or "morning_synchronization" not in device.get("capabilities", []):
                continue
            known.add(device_id)
            entities.append(RainPointMorningSyncTime(coordinator, device_id,
                str(entry.data.get(CONF_TOKEN, entry.options.get(CONF_TOKEN, "")))),)
        if entities:
            async_add_entities(entities)

    add_missing()
    entry.async_on_unload(coordinator.async_add_listener(add_missing))


class RainPointMorningSyncTime(RainPointLocalEntity, TimeEntity):
    _attr_translation_key = "morning_sync_start"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, device_id: str, token: str) -> None:
        super().__init__(coordinator, device_id)
        self._token = token
        self._attr_unique_id = f"{device_id}_morning_sync_start"

    @property
    def native_value(self) -> time | None:
        value = self.decoded_state.get("rf_morning_sync_start_time")
        return time.fromisoformat(value) if isinstance(value, str) else None

    @property
    def extra_state_attributes(self) -> dict:
        return {"timezone": self.decoded_state.get("rf_morning_sync_timezone"),
                "window_minutes": self.decoded_state.get("rf_morning_sync_window_minutes")}

    async def async_set_value(self, value: time) -> None:
        try:
            await self.coordinator.client.configure_morning_sync(self._token,
                device_id=self.device_id, start_time=value.strftime("%H:%M"),
                timezone=self.hass.config.time_zone)
        except RainPointLocalError as error:
            raise HomeAssistantError(str(error)) from error
        await self.coordinator.async_request_refresh()
