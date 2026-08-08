"""Transport-independent state and event model for the local gateway."""

from __future__ import annotations

import copy
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

from rainpoint_protocol import decode

from .rf import HCS026_ENDPOINTS
from .storage import SQLiteEventStore


API_VERSION = "v1"
REPORTING_TIMEOUTS = {
    "HCS026FRF": 15 * 60,
    "HTV145FRF": 6 * 60 * 60,
}
DEFAULT_REPORTING_TIMEOUT = 60 * 60


class Gateway:
    """Store decoded device state independently of the active radio transport."""

    def __init__(
        self,
        *,
        gateway_id: str = "rainpoint-replay",
        transport: str = "replay",
        read_only: bool = True,
        event_limit: int = 1_000,
        storage_path: str | None = None,
    ) -> None:
        self.gateway_id = gateway_id
        self.transport = transport
        self.read_only = read_only
        self._devices: dict[str, dict[str, Any]] = {}
        self._memory_metrics: dict[str, dict[str, Any]] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=event_limit)
        self._store = SQLiteEventStore(storage_path) if storage_path else None
        if self._store:
            self._events.extend(self._store.recent_events(event_limit))
        self._restore_devices()
        self._next_event_id = self.latest_event_id() + 1
        self._lock = threading.Lock()
        self._transport_healthy = True
        self._transport_error: str | None = None

    def info(self) -> dict[str, Any]:
        """Return gateway capabilities."""
        with self._lock:
            return {
                "api_version": API_VERSION,
                "gateway_id": self.gateway_id,
                "transport": self.transport,
                "read_only": self.read_only,
                "device_count": len(self._devices),
                "transport_healthy": self._transport_healthy,
                "transport_error": self._transport_error,
                "persistent_storage": self._store is not None,
                "stored_event_count": (
                    self._store.event_count() if self._store else len(self._events)
                ),
            }

    def close(self) -> None:
        """Close persistent resources."""
        with self._lock:
            if self._store:
                self._store.close()
                self._store = None

    def set_transport_status(
        self, healthy: bool, error: str | None = None
    ) -> None:
        """Update transport health for API and Supervisor watchdog checks."""
        with self._lock:
            self._transport_healthy = healthy
            self._transport_error = error

    def health(self) -> dict[str, Any]:
        """Return health separately from capability metadata."""
        with self._lock:
            return {
                "status": "ok" if self._transport_healthy else "error",
                "transport": self.transport,
                "detail": self._transport_error,
            }

    def observe(
        self,
        *,
        device_id: str,
        name: str,
        model: str,
        frame: str,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        """Decode one observation, update state, and append an immutable event."""
        return self.observe_decoded(
            device_id=device_id,
            name=name,
            model=model,
            frame=frame,
            state=decode(frame, model),
            observed_at=observed_at,
        )

    def register(
        self,
        *,
        device_id: str,
        name: str,
        model: str,
        state: dict[str, Any] | None = None,
    ) -> None:
        """Register an unavailable device before its first observation."""
        with self._lock:
            self._devices.setdefault(
                device_id,
                {
                    "device_id": device_id,
                    "name": name,
                    "model": model,
                    "available": False,
                    "last_event_id": 0,
                    "observed_at": None,
                    "state": copy.deepcopy(state or {}),
                },
            )

    def observe_decoded(
        self,
        *,
        device_id: str,
        name: str,
        model: str,
        frame: str,
        state: dict[str, Any],
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        """Store a transport-decoded observation and append an event."""
        timestamp = observed_at or datetime.now(timezone.utc).isoformat()
        decoded = copy.deepcopy(state)

        with self._lock:
            event_id = self._next_event_id
            self._next_event_id += 1
            event = {
                "event_id": event_id,
                "event_type": "device_observation",
                "observed_at": timestamp,
                "device_id": device_id,
                "name": name,
                "model": model,
                "raw": frame,
                "state": decoded,
            }
            self._events.append(event)
            if self._store:
                self._store.append(event)
            else:
                self._update_memory_metrics(device_id, timestamp)
            self._devices[device_id] = {
                "device_id": device_id,
                "name": name,
                "model": model,
                "available": True,
                "last_event_id": event_id,
                "observed_at": timestamp,
                "state": decoded,
            }
            return copy.deepcopy(event)

    def observe_rf_frame(
        self,
        *,
        frame: str,
        state: dict[str, Any],
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        """Retain a normalized RF frame without creating a HA device."""
        timestamp = observed_at or datetime.now(timezone.utc).isoformat()
        with self._lock:
            event_id = self._next_event_id
            self._next_event_id += 1
            event = {
                "event_id": event_id,
                "event_type": "rf_frame",
                "observed_at": timestamp,
                "raw": frame,
                "state": copy.deepcopy(state),
            }
            self._events.append(event)
            if self._store:
                self._store.append(event)
            return copy.deepcopy(event)

    def devices(
        self, now: datetime | None = None
    ) -> list[dict[str, Any]]:
        """Return a stable snapshot of all known devices."""
        with self._lock:
            metrics = (
                self._store.device_metrics()
                if self._store
                else self._memory_metrics
            )
            devices = copy.deepcopy(self._devices)
            for device_id, device in devices.items():
                device.update(
                    {
                        key: value
                        for key, value in metrics.get(device_id, {}).items()
                        if not key.startswith("_")
                    }
                )
                self._add_reporting_status(device, now)
            return sorted(devices.values(), key=lambda item: item["device_id"])

    def _update_memory_metrics(self, device_id: str, observed_at: str) -> None:
        """Track cadence for ephemeral replay gateways without SQLite."""
        metric = self._memory_metrics.get(device_id)
        if metric is None:
            self._memory_metrics[device_id] = {
                "first_observed_at": observed_at,
                "last_observed_at": observed_at,
                "report_count": 1,
                "average_report_interval_seconds": None,
                "longest_report_gap_seconds": 0.0,
                "_interval_count": 0,
                "_total_interval_seconds": 0.0,
            }
            return
        try:
            current = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            previous = datetime.fromisoformat(
                metric["last_observed_at"].replace("Z", "+00:00")
            )
            gap = max(0.0, (current - previous).total_seconds())
        except (TypeError, ValueError):
            gap = 0.0
        metric["last_observed_at"] = observed_at
        metric["report_count"] += 1
        metric["_interval_count"] += 1
        metric["_total_interval_seconds"] += gap
        metric["average_report_interval_seconds"] = round(
            metric["_total_interval_seconds"] / metric["_interval_count"], 3
        )
        metric["longest_report_gap_seconds"] = max(
            metric["longest_report_gap_seconds"], gap
        )

    def events(self, since: int = 0) -> list[dict[str, Any]]:
        """Return retained events newer than an event ID."""
        with self._lock:
            if self._store:
                return self._store.events(since)
            return copy.deepcopy(
                [event for event in self._events if event["event_id"] > since]
            )

    def latest_event_id(self) -> int:
        """Return the newest event ID."""
        if self._store:
            return self._store.latest_event_id()
        return self._events[-1]["event_id"] if self._events else 0

    def endpoints(self) -> list[dict[str, Any]]:
        """Return persistent RF endpoint discovery summaries."""
        with self._lock:
            return self._store.endpoints() if self._store else []

    def _restore_devices(self) -> None:
        """Rebuild decoded device state from retained observations."""
        for event in self._events:
            if event.get("event_type") != "device_observation":
                continue
            if not self._is_restorable_device(event):
                continue
            self._devices[event["device_id"]] = {
                "device_id": event["device_id"],
                "name": event["name"],
                "model": event["model"],
                "available": True,
                "last_event_id": event["event_id"],
                "observed_at": event["observed_at"],
                "state": copy.deepcopy(event["state"]),
            }

    @staticmethod
    def _add_reporting_status(
        device: dict[str, Any], now: datetime | None
    ) -> None:
        """Attach current receive status without changing device availability."""
        threshold = REPORTING_TIMEOUTS.get(
            device.get("model"), DEFAULT_REPORTING_TIMEOUT
        )
        observed_at = device.get("observed_at")
        age: float | None = None
        if isinstance(observed_at, str):
            try:
                observed = datetime.fromisoformat(
                    observed_at.replace("Z", "+00:00")
                )
                reference = now
                if reference is None:
                    reference = (
                        datetime.now(timezone.utc)
                        if observed.tzinfo is not None
                        else datetime.now()
                    )
                elif observed.tzinfo is None and reference.tzinfo is not None:
                    reference = reference.replace(tzinfo=None)
                elif observed.tzinfo is not None and reference.tzinfo is None:
                    reference = reference.replace(tzinfo=timezone.utc)
                age = max(0.0, (reference - observed).total_seconds())
            except ValueError:
                pass
        device["report_age_seconds"] = round(age, 3) if age is not None else None
        device["reporting_timeout_seconds"] = threshold
        device["reporting"] = age is not None and age <= threshold

    @staticmethod
    def _is_restorable_device(event: dict[str, Any]) -> bool:
        """Reject obsolete auto-discoveries that predate endpoint validation."""
        if event.get("model") != "HCS026FRF":
            return True
        device_id = str(event.get("device_id", ""))
        if not device_id.startswith("hcs026-"):
            return True
        endpoint = str(event.get("state", {}).get("rf_endpoint", "")).lower()
        return endpoint in HCS026_ENDPOINTS
