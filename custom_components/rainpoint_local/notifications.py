"""Default, observation-only HA watering notifications; no mobile service calls."""
from __future__ import annotations


class WateringNotifications:
    """Deduplicate snapshots and retain the latest run/problem per physical valve.

    Unknown state is not a stop. Intent is not watering. A failed close does not
    prove a valve closed. Initial idle/history establishes a baseline only.
    """

    def __init__(self, entry_id, publish):
        self.entry_id = entry_id
        self.publish = publish
        self.previous = {}
        self.failures = {}
        self.durations = {}

    def _emit(self, device_id, kind, title, message):
        self.publish(message, title=title,
                     notification_id=f"rainpoint_local_{self.entry_id}_{device_id}_{kind}")

    def command_failed(self, device_id, name, action):
        self._emit(device_id, "problem", f"{name}: watering command failed",
                   f"The {action} request could not be completed. Check the valve and its "
                   "HA control status before retrying; this does not confirm whether water flowed.")

    def observe(self, devices):
        for device_id, device in devices.items():
            if device.get("model") not in {"HTV145FRF", "HTV405FRF"}:
                continue
            state = device.get("state", {})
            name = device.get("name") or device.get("model") or "RainPoint valve"
            old = self.previous.get(device_id)
            watering = state.get("is_watering")
            zone = state.get("active_zone")
            transaction = state.get("rf_control_transaction_id")
            phase = state.get("rf_control_transaction_state")
            duration = state.get("rf_control_transaction_duration_seconds")
            # The duration belongs to a confirmed open, never a failed request
            # or a changed number helper. HTV405's run transaction has no action.
            confirmed = phase in {"confirmed", "watering_confirmed"}
            previous_duration = self.durations.get(device_id)
            if (confirmed and transaction and (old is None or old["confirmed_transaction"] != transaction)
                    and watering is True and state.get("rf_control_transaction_action") != "close"
                    and isinstance(duration, (int, float)) and not isinstance(duration, bool)
                    and 0 < duration <= 3600):
                self.durations[device_id] = duration
            if phase in {"failed", "interrupted"} and transaction and self.failures.get(device_id) != transaction:
                self.failures[device_id] = transaction
                self._emit(device_id, "problem", f"{name}: watering command failed",
                           "The valve did not confirm the requested operation. Check its control "
                           "status and inspect the valve before retrying; water may have flowed.")
            overdue = state.get("rf_control_overdue") is True
            if overdue and (old is None or not old["overdue"]):
                self._emit(device_id, "problem", f"{name}: watering needs attention",
                           "The expected stop has not been confirmed. Inspect the valve; missing "
                           "telemetry does not establish whether it is open or closed.")
            prior_watering = old["watering"] if old else None
            if watering is True and (prior_watering is not True or zone != old["zone"]
                                     or previous_duration != self.durations.get(device_id)):
                outlet = f" (zone {zone})" if isinstance(zone, int) and zone > 0 else ""
                minutes = self.durations.get(device_id)
                requested = f" Requested duration: {minutes / 60:g} minutes." if minutes else ""
                verb = "reports watering" if old is None else "confirmed watering"
                self._emit(device_id, "run", f"{name}: watering",
                           f"The valve {verb}{outlet}.{requested}")
            elif watering is False and prior_watering is True:
                self._emit(device_id, "run", f"{name}: watering stopped",
                           "The valve reported that watering stopped. This confirms idle state, "
                           "not the volume delivered or that the full requested duration elapsed.")
                self.durations.pop(device_id, None)
            # Preserve a known run through an unavailable/unknown snapshot so
            # later confirmed idle can close it without inventing a transition.
            self.previous[device_id] = {"watering": watering if isinstance(watering, bool) else prior_watering,
                                        "zone": zone, "overdue": overdue,
                                        "confirmed_transaction": transaction if confirmed else (
                                            old.get("confirmed_transaction") if old else None)}
        for records in (self.previous, self.failures, self.durations):
            for device_id in set(records) - set(devices):
                records.pop(device_id, None)


def notify_command_failure(entity, action):
    """Record HA-local refusals/connection errors without copying exception secrets."""
    reporter = getattr(entity.coordinator, "notifications", None)
    if reporter is not None:
        device = (entity.coordinator.data or {}).get(entity.device_id, {})
        reporter.command_failed(entity.device_id, device.get("name") or "RainPoint valve", action)


def setup_notifications(hass, entry, coordinator):
    """Enable HA notifications on every install; listen only to successful snapshots."""
    from homeassistant.components import persistent_notification
    from homeassistant.core import callback

    @callback
    def publish(message, **kwargs):
        persistent_notification.async_create(hass, message, **kwargs)
        # An optional user automation can forward this event to their phone.
        hass.bus.async_fire("rainpoint_local_watering_notification", {
            "entry_id": entry.entry_id, "message": message, **kwargs})

    reporter = WateringNotifications(entry.entry_id, publish)
    coordinator.notifications = reporter

    @callback
    def updated():
        if coordinator.last_update_success:
            reporter.observe(coordinator.data or {})

    entry.async_on_unload(coordinator.async_add_listener(updated))
    updated()
