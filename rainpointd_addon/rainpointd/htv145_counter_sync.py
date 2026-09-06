"""Explicit, close-only counter recovery after a fresh report from the ACK owner.

The fixed zero anchor is separately qualified from ordinary command success.
Neither telemetry counters nor result 3 outside this reservation authenticate it.
"""
from datetime import datetime, timedelta

from . import morning_sync
from .valve_protocol import decode_htv145_state_report


MAX_SYNC_ATTEMPTS = 3
RETRYABLE_FAILURES = frozenset({
    "idle_anchor_response_timeout",
    "confirmation_timeout_counter_unsynchronized",
    "gateway_connection_lost_counter_unsynchronized",
    "idle_anchor_transport_failed",
    "transmit_failed",
    "response_receiver_tune_failed",
    "node_rejected_invalid_htv145_idle_anchor_counter_unsynchronized",
})


def failed_attempt(data: dict, *, reason: str, observed_at: str) -> dict:
    """Persist a bounded retry decision with the failed reservation's release.

    Legacy requests without a retry budget remain one-shot. A retry requires a
    report received after this failure, keeps the original deadline, and uses a
    new command ID. Protocol conflicts and unexpected watering remain terminal.
    """
    result = {**data, "command_id": None, "last_attempt_result": reason,
              "last_attempt_finished_at": observed_at}
    attempts = data.get("attempt_count", 1)
    maximum = min(data.get("max_attempts", 1), MAX_SYNC_ATTEMPTS)
    retryable = reason.split(":", 1)[0] in RETRYABLE_FAILURES
    inside_window = bool(data.get("deadline") and
        datetime.fromisoformat(observed_at) < datetime.fromisoformat(data["deadline"]))
    if retryable and attempts < maximum and inside_window:
        result.update(state="waiting_for_report", report_after=observed_at,
                      reason="retry_waiting_for_new_owner_idle_report")
    else:
        terminal_reason = ("attempt_limit_reached:" + reason if retryable and attempts >= maximum
                           else "sync_window_expired:" + reason if retryable and not inside_window
                           else reason)
        result.update(state="failed", deadline=None, reason=terminal_reason)
    return result


class Htv145CounterSync:
    def __init__(self, coordinator, ready_node):
        self.coordinator = coordinator
        self.store = coordinator.store
        self.ready_node = ready_node

    def _require_owner(self, profile):
        self.coordinator._require_enabled()
        if "htv145_idle_anchor" not in self.ready_node(profile).get("capabilities", []):
            raise RuntimeError("counter sync requires idle-anchor radio firmware")

    def status(self, profile, *, now):
        state = self.coordinator.readiness(profile, observed_at=now)["state"]
        data = self.store.htv145_counter_sync(profile.valve_endpoint)
        try:
            self._require_owner(profile)
            available = True
        except (RuntimeError, PermissionError):
            available = False
        phase = data.get("state", "idle")
        if phase == "waiting_for_report" and datetime.fromisoformat(now) >= datetime.fromisoformat(data["deadline"]):
            phase = "failed"
        ready = bool(state["counter_synchronized"] and not state["pending_command_id"])
        attempts, maximum = data.get("attempt_count", 0), data.get("max_attempts", 1)
        waiting = (f"Waiting for idle report (attempt {attempts + 1}/{maximum})"
                   if attempts else "Waiting for idle report")
        label = ("Radio unavailable" if not available else
                 waiting if phase == "waiting_for_report" else
                 f"Syncing (attempt {attempts}/{maximum})" if phase == "syncing" else
                 "Sync failed" if phase == "failed" else "Ready" if ready else "Needs sync")
        return {**data, "config": data.get("config", dict(morning_sync.DEFAULT_CONFIG)),
                "state": phase, "status": label, "ready": ready and available and phase not in {"waiting_for_report", "syncing", "failed"},
                "available": available and not state["pending_command_id"] and not state["revocation_command_id"]}

    def configure(self, profile, settings, *, now):
        data = self.store.htv145_counter_sync(profile.valve_endpoint)
        config = morning_sync.configuration(data.get("config", {}), settings)
        if data.get("state") == "syncing":
            raise RuntimeError("wait for the pending counter anchor before changing settings")
        if config["enabled"]:
            self._require_owner(profile)
        if not config["enabled"] and data.get("state") == "waiting_for_report":
            data.update(state="cancelled", deadline=None, reason="disabled")
        data["config"] = config
        self.store.save_htv145_counter_sync(profile.valve_endpoint, data)
        return self.status(profile, now=now)

    def request(self, profile, *, now, wait_seconds=None):
        self._require_owner(profile)
        data = self.store.htv145_counter_sync(profile.valve_endpoint)
        current = datetime.fromisoformat(now)
        state = self.coordinator.readiness(profile, observed_at=now)["state"]
        if data.get("state") == "syncing" or (data.get("state") == "waiting_for_report"
                and current < datetime.fromisoformat(data["deadline"])):
            return self.status(profile, now=now)
        if state["pending_command_id"] or state["revocation_command_id"]:
            raise RuntimeError("finish the pending valve operation before queuing counter sync")
        seconds = wait_seconds if wait_seconds is not None else data.get("config", morning_sync.DEFAULT_CONFIG)["window_minutes"] * 60
        if not 1 <= seconds <= 7200:
            raise ValueError("counter sync wait must be bounded to two hours")
        data.update(state="waiting_for_report", requested_at=now, report_after=now,
                    attempt_count=0, max_attempts=MAX_SYNC_ATTEMPTS,
                    last_attempt_result=None, last_attempt_finished_at=None,
                    deadline=(current + timedelta(seconds=seconds)).isoformat(), command_id=None,
                    reason="waiting_for_new_owner_idle_report")
        self.store.save_htv145_counter_sync(profile.valve_endpoint, data)
        return self.status(profile, now=now)

    def observe(self, profile, frame, node_id, *, now):
        data = self.store.htv145_counter_sync(profile.valve_endpoint)
        if data.get("state") != "waiting_for_report" or node_id != profile.node_id:
            return
        current = datetime.fromisoformat(now)
        if not datetime.fromisoformat(data.get("report_after", data["requested_at"])) < current < datetime.fromisoformat(data["deadline"]):
            return
        report = decode_htv145_state_report(frame, profile.link)
        if report is None or report["watering"]:
            return
        self._require_owner(profile)
        state = self.coordinator.readiness(profile, observed_at=now)["state"]
        if state["pending_command_id"] or state["revocation_command_id"]:
            return
        if state["last_command_started_at"] and (current - datetime.fromisoformat(state["last_command_started_at"])).total_seconds() < 15:
            return
        self.coordinator.observe_frame(profile, frame, observed_at=now)
        self.coordinator.request_idle_anchor(profile, started_at=now)

    def tick(self, profile, *, now):
        data = self.store.htv145_counter_sync(profile.valve_endpoint)
        current = datetime.fromisoformat(now)
        if data.get("state") == "waiting_for_report" and current >= datetime.fromisoformat(data["deadline"]):
            data.update(state="failed", deadline=None, reason="idle_report_wait_expired")
            self.store.save_htv145_counter_sync(profile.valve_endpoint, data)
        config = data.get("config", morning_sync.DEFAULT_CONFIG)
        if not config["enabled"]:
            return
        day, phase, remaining = morning_sync.service_window(config, current)
        if phase != "inside" or not remaining or data.get("last_service_date") == day:
            return
        self._require_owner(profile)
        state = self.coordinator.readiness(profile, observed_at=now)["state"]
        if state["pending_command_id"] or state["revocation_command_id"]:
            return
        # Persist the calendar claim before authorizing a queue. A crash here
        # skips maintenance rather than replaying an anchor on startup.
        data["last_service_date"] = day
        self.store.save_htv145_counter_sync(profile.valve_endpoint, data)
        self.request(profile, now=now, wait_seconds=remaining)
