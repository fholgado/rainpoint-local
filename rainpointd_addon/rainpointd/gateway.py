"""Transport-independent state and event model for the local gateway."""

from __future__ import annotations

import copy
import hmac
import re
import threading
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from rainpoint_protocol import decode

from .rf import HCS026_ENDPOINTS
from .pairing import HCS026EnrollmentManager
from .storage import SQLiteEventStore, frame_accepted


API_VERSION = "v1"
REPORTING_TIMEOUTS = {
    "HCS026FRF": 15 * 60,
    "HTV145FRF": 6 * 60 * 60,
}
DEFAULT_REPORTING_TIMEOUT = 60 * 60
REGISTRY_MODELS = {"HCS026FRF", "HTV145FRF"}
_UNSET = object()


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
        registry_token: str | None = None,
    ) -> None:
        self.gateway_id = gateway_id
        self.transport = transport
        self.read_only = read_only
        self._registry_token = registry_token or None
        self._devices: dict[str, dict[str, Any]] = {}
        self._nodes: dict[str, dict[str, Any]] = {}
        self._memory_metrics: dict[str, dict[str, Any]] = {}
        self._memory_reception_metrics: dict[str, dict[str, Any]] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=event_limit)
        self._store = SQLiteEventStore(storage_path) if storage_path else None
        self._pairing = (
            HCS026EnrollmentManager(
                Path(storage_path).with_suffix(".hcs026-pairing.json")
            )
            if storage_path
            else None
        )
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
                "node_count": len(self._nodes),
                "transport_healthy": self._transport_healthy,
                "transport_error": self._transport_error,
                "persistent_storage": self._store is not None,
                "stored_event_count": (
                    self._store.event_count() if self._store else len(self._events)
                ),
                "registry_available": self._store is not None,
                "registry_writes_enabled": self._registry_token is not None,
                "rf_pairing_available": self._pairing is not None,
                "rf_pairing_receive_only": True,
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

    def update_node(self, node_id: str, **fields: Any) -> None:
        """Update ephemeral diagnostics for one authenticated radio node."""
        with self._lock:
            node = self._nodes.setdefault(node_id, {"node_id": node_id})
            node.update(copy.deepcopy(fields))

    def nodes(self) -> list[dict[str, Any]]:
        """Return radio-node connection and receiver diagnostics."""
        with self._lock:
            return sorted(
                copy.deepcopy(list(self._nodes.values())),
                key=lambda item: item["node_id"],
            )

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
                self._update_memory_reception_metrics(event)
            self._devices[device_id] = {
                "device_id": device_id,
                "name": name,
                "model": model,
                "available": True,
                "last_event_id": event_id,
                "observed_at": timestamp,
                "state": decoded,
            }
            self._observe_pairing(decoded, timestamp)
            return copy.deepcopy(event)

    def observe_rf_frame(
        self,
        *,
        frame: str,
        state: dict[str, Any],
        observed_at: str | None = None,
        device_id: str | None = None,
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
            if device_id is not None:
                event["device_id"] = device_id
            self._events.append(event)
            if self._store:
                self._store.append(event)
            else:
                self._update_memory_reception_metrics(event)
            self._observe_pairing(state, timestamp)
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
            reception_metrics = (
                self._store.reception_metrics()
                if self._store
                else self._memory_reception_metrics
            )
            devices = copy.deepcopy(self._devices)
            registry = {
                item["device_id"]: item
                for item in (self._store.registry() if self._store else [])
            }
            for device_id, device in devices.items():
                if registered := registry.get(device_id):
                    device["name"] = registered["name"]
                    device["area"] = registered["area"]
                device.update(
                    {
                        key: value
                        for key, value in metrics.get(device_id, {}).items()
                        if not key.startswith("_")
                    }
                )
                reception = reception_metrics.get(device_id, {})
                device.update(copy.deepcopy(reception))
                last_valid = reception.get("last_valid_frame_at")
                if isinstance(last_valid, str):
                    state_observed_at = device.get("observed_at")
                    if state_observed_at != last_valid:
                        device["state_observed_at"] = state_observed_at
                    device["observed_at"] = last_valid
                    event_id = reception.get("last_valid_frame_event_id")
                    if isinstance(event_id, int):
                        device["last_event_id"] = event_id
                    device["available"] = True
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

    def _update_memory_reception_metrics(self, event: dict[str, Any]) -> None:
        """Track integrity for gateways running without persistent storage."""
        device_id = event.get("device_id")
        valid = frame_accepted(event)
        observed_at = event.get("observed_at")
        event_id = event.get("event_id")
        if (
            not isinstance(device_id, str)
            or not isinstance(valid, bool)
            or not isinstance(observed_at, str)
            or not isinstance(event_id, int)
        ):
            return
        metric = self._memory_reception_metrics.setdefault(
            device_id,
            {
                "valid_rf_frame_count": 0,
                "invalid_rf_frame_count": 0,
            },
        )
        count_key = (
            "valid_rf_frame_count" if valid else "invalid_rf_frame_count"
        )
        metric[count_key] += 1
        valid_count = metric["valid_rf_frame_count"]
        invalid_count = metric["invalid_rf_frame_count"]
        total = valid_count + invalid_count
        metric.update(
            {
                "rf_frame_count": total,
                "rf_frame_success_percent": round(valid_count * 100 / total, 1),
                "last_frame_at": observed_at,
                "last_frame_event_id": event_id,
            }
        )
        if valid:
            metric["last_valid_frame_at"] = observed_at
            metric["last_valid_frame_event_id"] = event_id
        else:
            metric["last_invalid_frame_at"] = observed_at

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

    def registry_authorized(self, token: str | None) -> bool:
        """Validate the optional registry-write token in constant time."""
        expected = self._registry_token
        return (
            expected is not None
            and token is not None
            and hmac.compare_digest(token, expected)
        )

    def registry(self) -> list[dict[str, Any]]:
        """Return accepted local metadata; this is not RF pairing state."""
        with self._lock:
            return self._store.registry() if self._store else []

    def pairing(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Return receive-only HCS026 enrollment progress."""
        with self._lock:
            if self._pairing is None:
                return {
                    "active": False,
                    "available": False,
                    "receive_only": True,
                    "candidates": [],
                    "new_records": [],
                    "records": [],
                }
            return {
                "available": True,
                "receive_only": True,
                **self._pairing.status(now=now),
            }

    def start_pairing(
        self, duration_seconds: int = 120, *, now: datetime | None = None
    ) -> dict[str, Any]:
        """Open a receive-only HCS026 enrollment window."""
        if not 10 <= duration_seconds <= 900:
            raise ValueError("duration_seconds must be between 10 and 900")
        with self._lock:
            if self._pairing is None:
                raise RuntimeError("persistent pairing state is unavailable")
            return {
                "available": True,
                "receive_only": True,
                **self._pairing.start(duration_seconds, now=now),
            }

    def stop_pairing(self) -> dict[str, Any]:
        """Close the current pairing window without transmitting anything."""
        with self._lock:
            if self._pairing is None:
                raise RuntimeError("persistent pairing state is unavailable")
            return {
                "available": True,
                "receive_only": True,
                **self._pairing.stop(),
            }

    def complete_hcs026_pairing(
        self,
        *,
        endpoint: str,
        name: str,
        area: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Name a sensor proven by the current receive-only pairing session."""
        endpoint = endpoint.strip().lower()
        name = _clean_label(name, "name")
        area = _clean_optional_label(area, "area")
        timestamp = (now or datetime.now(timezone.utc)).isoformat()
        with self._lock:
            if self._pairing is None or self._store is None:
                raise RuntimeError("persistent pairing state is unavailable")
            record = next(
                (
                    item
                    for item in self._pairing.records()
                    if item.paired_endpoint == endpoint
                ),
                None,
            )
            if record is None:
                raise KeyError(endpoint)
            if endpoint not in {item["endpoint"] for item in self._store.endpoints()}:
                raise KeyError(endpoint)
            device_id = f"hcs026-{endpoint}"
            registered = self._store.accept_endpoint(
                endpoint=endpoint,
                device_id=device_id,
                name=name,
                model="HCS026FRF",
                area=area,
                accepted_at=timestamp,
            )
            if device_id in self._devices:
                self._devices[device_id]["name"] = name
                self._devices[device_id]["area"] = area
            self._pairing.stop()
            return registered

    def _observe_pairing(self, state: dict[str, Any], timestamp: str) -> None:
        """Feed accepted normalized enrollment fields to the state machine."""
        if self._pairing is None or state.get("rf_frame_accepted") is False:
            return
        pairing_state = state.get(
            "hcs026_pairing_state", state.get("rf_pairing_state")
        )
        factory = state.get(
            "hcs026_factory_endpoint", state.get("rf_factory_endpoint")
        )
        paired = state.get(
            "hcs026_paired_endpoint", state.get("rf_paired_endpoint")
        )
        if pairing_state not in {"factory", "paired"}:
            return
        fields = {
            "hcs026_pairing_state": pairing_state,
            "hcs026_factory_endpoint": factory,
        }
        if paired is not None:
            fields["hcs026_paired_endpoint"] = paired
        try:
            observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            observed = datetime.now(timezone.utc)
        self._pairing.observe(fields, now=observed)

    def accept_endpoint(
        self,
        *,
        endpoint: str,
        name: str,
        model: str,
        area: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Accept an observed endpoint into the persistent local registry."""
        endpoint = endpoint.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{8}", endpoint):
            raise ValueError("endpoint must be exactly 8 hexadecimal characters")
        if model not in REGISTRY_MODELS:
            raise ValueError(f"unsupported model: {model}")
        name = _clean_label(name, "name")
        area = _clean_optional_label(area, "area")
        timestamp = (now or datetime.now(timezone.utc)).isoformat()
        with self._lock:
            if not self._store:
                raise RuntimeError("persistent registry is unavailable")
            known = {item["endpoint"] for item in self._store.endpoints()}
            if endpoint not in known:
                raise KeyError(endpoint)
            return self._store.accept_endpoint(
                endpoint=endpoint,
                device_id=f"local-{endpoint}",
                name=name,
                model=model,
                area=area,
                accepted_at=timestamp,
            )

    def update_registry_device(
        self,
        device_id: str,
        *,
        name: str | None = None,
        area: str | None | object = _UNSET,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Update human-facing metadata for a local registration."""
        with self._lock:
            if not self._store:
                raise RuntimeError("persistent registry is unavailable")
            existing = self._store.registry_device(device_id)
            next_name = existing["name"] if name is None else _clean_label(name, "name")
            next_area = (
                existing["area"]
                if area is _UNSET
                else _clean_optional_label(area, "area")
            )
            timestamp = (now or datetime.now(timezone.utc)).isoformat()
            return self._store.update_registry_device(
                device_id,
                name=next_name,
                area=next_area,
                updated_at=timestamp,
            )

    def forget_registry_device(self, device_id: str) -> dict[str, Any]:
        """Forget local metadata without transmitting an RF unpair command."""
        with self._lock:
            if not self._store:
                raise RuntimeError("persistent registry is unavailable")
            return self._store.forget_registry_device(device_id)

    def start_learning(
        self,
        duration_seconds: int = 300,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Start a receive-only window that highlights newly seen endpoints."""
        if not 10 <= duration_seconds <= 3_600:
            raise ValueError("duration_seconds must be between 10 and 3600")
        started = now or datetime.now(timezone.utc)
        with self._lock:
            if not self._store:
                raise RuntimeError("persistent registry is unavailable")
            session = {
                "session_id": uuid.uuid4().hex,
                "started_at": started.isoformat(),
                "expires_at": (started + timedelta(seconds=duration_seconds)).isoformat(),
                "baseline_endpoints": [
                    item["endpoint"] for item in self._store.endpoints()
                ],
            }
            self._store.save_learning_session(session)
            return self._learning_snapshot(session, started)

    def learning(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Return current receive-only learning progress and discoveries."""
        current = now or datetime.now(timezone.utc)
        with self._lock:
            if not self._store:
                return {
                    "active": False,
                    "rf_pairing": False,
                    "new_endpoints": [],
                    "detail": "persistent registry is unavailable",
                }
            session = self._store.learning_session()
            if session is None:
                return {
                    "active": False,
                    "rf_pairing": False,
                    "new_endpoints": [],
                }
            return self._learning_snapshot(session, current)

    def _learning_snapshot(
        self, session: dict[str, Any], current: datetime
    ) -> dict[str, Any]:
        """Merge a stored learning window with the current endpoint inventory."""
        started = datetime.fromisoformat(session["started_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(session["expires_at"].replace("Z", "+00:00"))
        if expires.tzinfo is None and current.tzinfo is not None:
            current = current.replace(tzinfo=None)
        elif expires.tzinfo is not None and current.tzinfo is None:
            current = current.astimezone()
        baseline = set(session["baseline_endpoints"])
        endpoints = self._store.endpoints() if self._store else []
        return {
            "session_id": session["session_id"],
            "started_at": session["started_at"],
            "expires_at": session["expires_at"],
            "active": current <= expires,
            "rf_pairing": False,
            "new_endpoints": [
                item
                for item in endpoints
                if item["endpoint"] not in baseline
                and _timestamp_in_window(item["first_seen"], started, expires)
            ],
            "detail": (
                "receive-only discovery; accepting an endpoint changes local "
                "metadata and does not pair the physical device"
            ),
        }

    def _restore_devices(self) -> None:
        """Rebuild decoded device state from retained observations."""
        events = (
            self._store.latest_device_events() if self._store else self._events
        )
        for event in events:
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
        if frame_accepted(event) is False:
            return False
        if event.get("model") != "HCS026FRF":
            return True
        device_id = str(event.get("device_id", ""))
        if not device_id.startswith("hcs026-"):
            return True
        endpoint = str(event.get("state", {}).get("rf_endpoint", "")).lower()
        state = event.get("state", {})
        return (
            endpoint in HCS026_ENDPOINTS
            or state.get("rf_pairing_state") == "paired"
        )


def _clean_label(value: str, field: str) -> str:
    """Validate short human-facing registry labels."""
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 80:
        raise ValueError(f"{field} must contain 1 to 80 characters")
    return cleaned


def _clean_optional_label(value: Any, field: str) -> str | None:
    """Validate an optional short registry label."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string or null")
    return _clean_label(value, field)


def _timestamp_in_window(
    value: str, started: datetime, expires: datetime
) -> bool:
    """Compare rtl_433 local timestamps with an aware learning window."""
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    if observed.tzinfo is None and started.tzinfo is not None:
        started = started.astimezone().replace(tzinfo=None)
        expires = expires.astimezone().replace(tzinfo=None)
    elif observed.tzinfo is not None and started.tzinfo is None:
        observed = observed.astimezone().replace(tzinfo=None)
    return started <= observed <= expires
