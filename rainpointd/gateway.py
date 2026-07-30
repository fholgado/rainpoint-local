"""Transport-independent state and event model for the local gateway."""

from __future__ import annotations

import copy
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

from rainpoint_protocol import decode


API_VERSION = "v1"


class Gateway:
    """Store decoded device state independently of the active radio transport."""

    def __init__(
        self,
        *,
        gateway_id: str = "rainpoint-replay",
        transport: str = "replay",
        read_only: bool = True,
        event_limit: int = 1_000,
    ) -> None:
        self.gateway_id = gateway_id
        self.transport = transport
        self.read_only = read_only
        self._devices: dict[str, dict[str, Any]] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=event_limit)
        self._next_event_id = 1
        self._lock = threading.Lock()

    def info(self) -> dict[str, Any]:
        """Return gateway capabilities."""
        with self._lock:
            return {
                "api_version": API_VERSION,
                "gateway_id": self.gateway_id,
                "transport": self.transport,
                "read_only": self.read_only,
                "device_count": len(self._devices),
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
        decoded = decode(frame, model)
        timestamp = observed_at or datetime.now(timezone.utc).isoformat()

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

    def devices(self) -> list[dict[str, Any]]:
        """Return a stable snapshot of all known devices."""
        with self._lock:
            return copy.deepcopy(
                sorted(self._devices.values(), key=lambda item: item["device_id"])
            )

    def events(self, since: int = 0) -> list[dict[str, Any]]:
        """Return retained events newer than an event ID."""
        with self._lock:
            return copy.deepcopy(
                [event for event in self._events if event["event_id"] > since]
            )
