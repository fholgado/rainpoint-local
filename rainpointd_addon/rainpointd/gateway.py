"""Transport-independent state and event model for the local gateway."""

from __future__ import annotations

import copy
import hmac
import re
import secrets
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from rainpoint_protocol import decode

from .device_catalog import DeviceCatalog, LEGACY_HOME_CATALOG
from .pairing import HCS026EnrollmentManager, factory_endpoint, paired_endpoint
from .pairing_protocol import (
    AUTOMATIC_HCS026_PROFILE_ID,
    automatic_hcs026_profile_metadata,
    pairing_profile,
)
from .storage import (
    DEFAULT_EVENT_RETENTION_LIMIT,
    SQLiteEventStore,
    frame_accepted,
)


API_VERSION = "v1"
REPORTING_TIMEOUTS = {
    "HCS026FRF": 15 * 60,
    "HTV145FRF": 6 * 60 * 60,
}
DEFAULT_REPORTING_TIMEOUT = 60 * 60
RECEIVER_DEDUPLICATION_SECONDS = 0.25
REGISTRY_MODELS = {"HCS026FRF", "HTV145FRF"}
RADIO_NODE_ID = re.compile(r"rp-[0-9a-f]{12}\Z")
RADIO_NODE_TOKEN = re.compile(r"[0-9a-fA-F]{64}\Z")
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
        event_retention_limit: int = DEFAULT_EVENT_RETENTION_LIMIT,
        registry_token: str | None = None,
        catalog: DeviceCatalog = LEGACY_HOME_CATALOG,
    ) -> None:
        self.gateway_id = gateway_id
        self.transport = transport
        self.read_only = read_only
        self._registry_token = registry_token or None
        self._base_catalog = catalog
        self.catalog = catalog
        self._registry_metadata: dict[str, dict[str, Any]] = {}
        self._suppressed_endpoints: frozenset[str] = frozenset()
        self._devices: dict[str, dict[str, Any]] = {}
        self._nodes: dict[str, dict[str, Any]] = {}
        self._memory_metrics: dict[str, dict[str, Any]] = {}
        self._memory_reception_metrics: dict[str, dict[str, Any]] = {}
        self._recent_receiver_frames: dict[str, tuple[str, float]] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=event_limit)
        self._store = (
            SQLiteEventStore(
                storage_path,
                event_retention_limit=event_retention_limit,
            )
            if storage_path
            else None
        )
        self._pairing = (
            HCS026EnrollmentManager(
                repository=self._store,
                legacy_path=Path(storage_path).with_suffix(
                    ".hcs026-pairing.json"
                ),
            )
            if storage_path
            else None
        )
        self._migrate_legacy_registry_identities()
        self._refresh_registry_catalog()
        if self._store:
            self._events.extend(self._store.recent_events(event_limit))
        self._restore_devices()
        self._next_event_id = self.latest_event_id() + 1
        self._lock = threading.Lock()
        self._transport_healthy = True
        self._transport_error: str | None = None
        self._node_command_sender: (
            Callable[[str, dict[str, Any]], None] | None
        ) = None
        self._active_pairing_node_id: str | None = None
        self._active_pairing_command_id: str | None = None
        self._pending_node_adoptions: dict[str, dict[str, Any]] = {}

    def info(self) -> dict[str, Any]:
        """Return gateway capabilities."""
        with self._lock:
            managed_node_ids = {
                str(item["node_id"])
                for item in (self._store.radio_nodes() if self._store else [])
            }
            all_node_ids = managed_node_ids | set(self._nodes)
            return {
                "api_version": API_VERSION,
                "gateway_id": self.gateway_id,
                "transport": self.transport,
                "read_only": self.read_only,
                "device_count": len(self._devices),
                "node_count": len(all_node_ids),
                "connected_node_count": sum(
                    self._nodes.get(node_id, {}).get("connected") is True
                    for node_id in all_node_ids
                ),
                "managed_node_count": len(managed_node_ids),
                "transport_healthy": self._transport_healthy,
                "transport_error": self._transport_error,
                "persistent_storage": self._store is not None,
                "storage_schema_version": (
                    self._store.schema_version() if self._store else None
                ),
                "stored_event_count": (
                    self._store.event_count() if self._store else len(self._events)
                ),
                "oldest_retained_event_id": (
                    self._store.oldest_event_id()
                    if self._store
                    else (self._events[0]["event_id"] if self._events else 0)
                ),
                "event_retention_limit": (
                    self._store.event_retention_limit
                    if self._store
                    else self._events.maxlen
                ),
                "registry_available": self._store is not None,
                "registry_writes_enabled": self._registry_token is not None,
                "rf_pairing_available": bool(self._pairing_nodes()),
                "rf_pairing_monitor_available": self._pairing is not None,
                "rf_pairing_transmitter_required": True,
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

    def set_node_command_sender(
        self, sender: Callable[[str, dict[str, Any]], None] | None
    ) -> None:
        """Attach the authenticated node command boundary owned by the LAN server."""
        with self._lock:
            self._node_command_sender = sender

    def nodes(self) -> list[dict[str, Any]]:
        """Return radio-node connection and receiver diagnostics."""
        with self._lock:
            nodes = copy.deepcopy(self._nodes)
            for registration in (
                self._store.radio_nodes() if self._store else []
            ):
                node_id = str(registration["node_id"])
                node = nodes.setdefault(
                    node_id,
                    {
                        "node_id": node_id,
                        "connected": False,
                        "authenticated": False,
                        "tx_armed": False,
                    },
                )
                node.update(
                    {
                        "name": registration["name"],
                        "area": registration["area"],
                        "managed": True,
                        "registered_at": registration["registered_at"],
                        "updated_at": registration["updated_at"],
                    }
                )
            return sorted(
                list(nodes.values()),
                key=lambda item: item["node_id"],
            )

    def import_node_credentials(self, credentials: dict[str, str]) -> None:
        """Migrate legacy add-on option credentials into managed storage."""
        if not self._store:
            return
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            for node_id, token in credentials.items():
                self._validate_radio_node_identity(node_id, token)
                self._store.upsert_radio_node(
                    node_id=node_id,
                    token=token.lower(),
                    name=node_id,
                    area=None,
                    updated_at=now,
                    replace_existing=False,
                )

    def radio_node_credential(self, node_id: str) -> str | None:
        """Return one private node credential to the listener only."""
        if not self._store:
            return None
        with self._lock:
            return self._store.radio_node_credentials().get(node_id)

    def pending_radio_node_credential(self, node_id: str) -> str | None:
        """Return one unexpired adoption credential to the node listener."""
        with self._lock:
            adoption = self._pending_node_adoptions.get(node_id)
            if adoption is None:
                return None
            if time.monotonic() >= adoption["expires_monotonic"]:
                self._pending_node_adoptions.pop(node_id, None)
                return None
            return str(adoption["token"])

    def start_radio_node_adoption(
        self,
        *,
        node_id: str,
        name: str,
        area: str | None,
        duration_seconds: int = 300,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Issue a temporary credential for one physically confirmed node."""
        if not self._store:
            raise RuntimeError("persistent radio-node registry is unavailable")
        node_id = node_id.strip().lower()
        name = name.strip()
        if not RADIO_NODE_ID.fullmatch(node_id):
            raise ValueError("invalid radio-node ID")
        if not name or len(name) > 100:
            raise ValueError("radio-node name must be 1 to 100 characters")
        if area is not None:
            area = area.strip() or None
            if area is not None and len(area) > 100:
                raise ValueError("radio-node area must be at most 100 characters")
        if not 60 <= duration_seconds <= 600:
            raise ValueError("duration_seconds must be between 60 and 600")
        if self.radio_node_credential(node_id) is not None:
            raise ValueError("radio node is already adopted")
        issued_at = now or datetime.now(timezone.utc)
        token = secrets.token_hex(32)
        adoption = {
            "adoption_id": uuid.uuid4().hex,
            "node_id": node_id,
            "token": token,
            "name": name,
            "area": area,
            "issued_at": issued_at.isoformat(),
            "expires_at": (
                issued_at + timedelta(seconds=duration_seconds)
            ).isoformat(),
            "expires_monotonic": time.monotonic() + duration_seconds,
        }
        with self._lock:
            self._pending_node_adoptions[node_id] = adoption
        return {
            "adoption_id": adoption["adoption_id"],
            "node_id": node_id,
            "node_token": token,
            "expires_at": adoption["expires_at"],
        }

    def radio_node_adoption(self, node_id: str) -> dict[str, Any]:
        """Return public progress for one pending or completed adoption."""
        node_id = node_id.strip().lower()
        with self._lock:
            adoption = self._pending_node_adoptions.get(node_id)
            if adoption is not None:
                if time.monotonic() >= adoption["expires_monotonic"]:
                    self._pending_node_adoptions.pop(node_id, None)
                    return {"node_id": node_id, "state": "expired"}
                return {
                    "adoption_id": adoption["adoption_id"],
                    "node_id": node_id,
                    "state": "waiting_for_node",
                    "expires_at": adoption["expires_at"],
                }
            managed = self._store.radio_node_credentials() if self._store else {}
            return {
                "node_id": node_id,
                "state": "adopted" if node_id in managed else "not_found",
            }

    def complete_radio_node_adoption(self, node_id: str) -> dict[str, Any] | None:
        """Persist a pending credential after its first authenticated session."""
        if not self._store:
            return None
        with self._lock:
            adoption = self._pending_node_adoptions.get(node_id)
            if adoption is None:
                return None
            if time.monotonic() >= adoption["expires_monotonic"]:
                self._pending_node_adoptions.pop(node_id, None)
                return None
            registered = self._store.upsert_radio_node(
                node_id=node_id,
                token=adoption["token"],
                name=adoption["name"],
                area=adoption["area"],
                updated_at=datetime.now(timezone.utc).isoformat(),
                replace_existing=False,
            )
            self._pending_node_adoptions.pop(node_id, None)
            return registered

    def cancel_radio_node_adoption(self, node_id: str) -> dict[str, Any]:
        """Invalidate one uncommitted adoption credential."""
        node_id = node_id.strip().lower()
        with self._lock:
            cancelled = self._pending_node_adoptions.pop(node_id, None) is not None
        return {"node_id": node_id, "state": "cancelled", "cancelled": cancelled}

    def identify_radio_node(
        self, node_id: str, duration_seconds: int = 15
    ) -> dict[str, Any]:
        """Blink one authenticated node without enabling its RF transmitter."""
        if not 3 <= duration_seconds <= 60:
            raise ValueError("duration_seconds must be between 3 and 60")
        with self._lock:
            node = self._nodes.get(node_id)
            if (
                node is None
                or node.get("connected") is not True
                or node.get("authenticated") is not True
            ):
                raise ValueError("radio node is not connected")
            if "identify" not in node.get("capabilities", []):
                raise ValueError("radio node does not support identification")
            if self._node_command_sender is None:
                raise RuntimeError("radio-node command transport is unavailable")
            command_id = uuid.uuid4().hex
            self._node_command_sender(
                node_id,
                {
                    "type": "identify_start",
                    "command_id": command_id,
                    "duration_seconds": duration_seconds,
                },
            )
            node["identify_active"] = True
            node["identify_command_id"] = command_id
            return {
                "node_id": node_id,
                "identify_active": True,
                "duration_seconds": duration_seconds,
                "command_id": command_id,
            }

    def register_radio_node(
        self,
        *,
        node_id: str,
        token: str,
        name: str,
        area: str | None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Register an independently authenticated custom local radio node."""
        if not self._store:
            raise RuntimeError("persistent radio-node registry is unavailable")
        node_id = node_id.strip().lower()
        token = token.strip().lower()
        name = name.strip()
        if not name or len(name) > 100:
            raise ValueError("radio-node name must be 1 to 100 characters")
        if area is not None:
            area = area.strip() or None
            if area is not None and len(area) > 100:
                raise ValueError("radio-node area must be at most 100 characters")
        self._validate_radio_node_identity(node_id, token)
        timestamp = (now or datetime.now(timezone.utc)).isoformat()
        with self._lock:
            return self._store.upsert_radio_node(
                node_id=node_id,
                token=token,
                name=name,
                area=area,
                updated_at=timestamp,
                replace_existing=True,
            )

    @staticmethod
    def _validate_radio_node_identity(node_id: str, token: str) -> None:
        """Validate the stable ESP32 identity and 256-bit node credential."""
        if not RADIO_NODE_ID.fullmatch(node_id):
            raise ValueError("invalid radio-node ID")
        if not RADIO_NODE_TOKEN.fullmatch(token):
            raise ValueError(
                "radio-node token must contain 64 hexadecimal characters"
            )

    def receivers(self) -> list[dict[str, Any]]:
        """Return physical receiver coverage independently of device cadence."""
        with self._lock:
            return self._store.receiver_metrics() if self._store else []

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
            endpoint = str((state or {}).get("rf_endpoint", "")).lower()
            if endpoint in self._suppressed_endpoints:
                return
            registry_metadata = self._registry_metadata.get(device_id)
            if registry_metadata is not None:
                name = str(registry_metadata["name"])
            device = {
                "device_id": device_id,
                "name": name,
                "model": model,
                "available": False,
                "last_event_id": 0,
                "observed_at": None,
                "state": copy.deepcopy(state or {}),
            }
            if registry_metadata is not None:
                device["area"] = registry_metadata.get("area")
            self._devices.setdefault(
                device_id,
                device,
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
            duplicate = self._receiver_duplicate_locked(
                frame=frame,
                state=decoded,
                observed_at=timestamp,
                device_id=device_id,
            )
            if duplicate is not None:
                return duplicate
            registry_metadata = self._registry_metadata.get(device_id)
            if registry_metadata is not None:
                name = str(registry_metadata["name"])
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
            device = {
                "device_id": device_id,
                "name": name,
                "model": model,
                "available": True,
                "last_event_id": event_id,
                "observed_at": timestamp,
                "state": decoded,
            }
            if registry_metadata is not None:
                device["area"] = registry_metadata.get("area")
            self._devices[device_id] = device
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
        decoded = copy.deepcopy(state)
        with self._lock:
            duplicate = self._receiver_duplicate_locked(
                frame=frame,
                state=decoded,
                observed_at=timestamp,
                device_id=device_id,
            )
            if duplicate is not None:
                return duplicate
            event_id = self._next_event_id
            self._next_event_id += 1
            event = {
                "event_id": event_id,
                "event_type": "rf_frame",
                "observed_at": timestamp,
                "raw": frame,
                "state": decoded,
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

    def _receiver_duplicate_locked(
        self,
        *,
        frame: str,
        state: dict[str, Any],
        observed_at: str,
        device_id: str | None,
    ) -> dict[str, Any] | None:
        """Deduplicate one air transmission while retaining receiver evidence."""
        receiver_id = state.get("rf_receiver_id")
        if not isinstance(receiver_id, str):
            return None
        now = time.monotonic()
        previous = self._recent_receiver_frames.get(frame)
        duplicate = bool(
            previous
            and previous[0] != receiver_id
            and now - previous[1] <= RECEIVER_DEDUPLICATION_SECONDS
        )
        if not duplicate:
            self._recent_receiver_frames[frame] = (receiver_id, now)
        if len(self._recent_receiver_frames) > 512:
            cutoff = now - max(RECEIVER_DEDUPLICATION_SECONDS, 1)
            self._recent_receiver_frames = {
                key: value
                for key, value in self._recent_receiver_frames.items()
                if value[1] >= cutoff
            }
        if not duplicate:
            return None
        evidence = {
            "event_type": "receiver_duplicate",
            "observed_at": observed_at,
            "raw": frame,
            "state": copy.deepcopy(state),
            "deduplicated": True,
        }
        if device_id is not None:
            evidence["device_id"] = device_id
        if self._store:
            self._store.record_receiver_duplicate(evidence)
        node = self._nodes.get(receiver_id)
        if node is not None:
            node["duplicate_frames"] = int(node.get("duplicate_frames", 0)) + 1
        return copy.deepcopy(evidence)

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

    def endpoint_suppressed(self, endpoint: str) -> bool:
        """Return whether local policy hides an RF endpoint as a device."""
        return endpoint.lower() in self._suppressed_endpoints

    def pairing(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Return HCS026 enrollment progress and available radio nodes."""
        with self._lock:
            if self._pairing is None:
                return {
                    "active": False,
                    "available": False,
                    "transmitter_available": False,
                    "transmitter_required": True,
                    "candidates": [],
                    "new_records": [],
                    "records": [],
                }
            return self._pairing_snapshot(now=now)

    def start_pairing(
        self,
        duration_seconds: int = 120,
        *,
        node_id: str | None = None,
        profile_id: str = AUTOMATIC_HCS026_PROFILE_ID,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Open enrollment and optionally arm one authenticated radio node."""
        if not 10 <= duration_seconds <= 900:
            raise ValueError("duration_seconds must be between 10 and 900")
        with self._lock:
            if self._pairing is None:
                raise RuntimeError("persistent pairing state is unavailable")
            self._pairing.start(duration_seconds, now=now)
            self._active_pairing_node_id = None
            self._active_pairing_command_id = None
            if node_id is not None:
                nodes = {item["node_id"]: item for item in self._pairing_nodes()}
                if node_id not in nodes:
                    self._pairing.stop()
                    raise ValueError("selected radio node cannot transmit pairing")
                if self._node_command_sender is None:
                    self._pairing.stop()
                    raise RuntimeError("radio-node command transport is unavailable")
                automatic = profile_id == AUTOMATIC_HCS026_PROFILE_ID
                if automatic:
                    clock_lead_seconds = 240
                else:
                    try:
                        profile = pairing_profile(profile_id)
                    except KeyError:
                        self._pairing.stop()
                        raise ValueError("unsupported pairing profile") from None
                    clock_lead_seconds = profile.clock_lead_seconds
                local_clock = (
                    (now or datetime.now().astimezone())
                    + timedelta(seconds=clock_lead_seconds)
                ).strftime("%Y%m%d%H%M%S")
                command_id = uuid.uuid4().hex
                command = {
                    "type": "pairing_start",
                    "command_id": command_id,
                    "profile": profile_id,
                    "duration_seconds": duration_seconds,
                    "local_clock": local_clock,
                    "frequency_offset_hz": 45_000,
                    "power_dbm": 10,
                    "invert": False,
                }
                if not automatic:
                    command["factory_endpoint"] = profile.factory_endpoint
                try:
                    self._node_command_sender(node_id, command)
                except (ConnectionError, KeyError, RuntimeError, ValueError):
                    self._pairing.stop()
                    raise
                self._active_pairing_node_id = node_id
                self._active_pairing_command_id = command_id
            return self._pairing_snapshot(now=now)

    def stop_pairing(self) -> dict[str, Any]:
        """Close the current pairing window and disarm its selected node."""
        with self._lock:
            if self._pairing is None:
                raise RuntimeError("persistent pairing state is unavailable")
            self._cancel_active_pairing_node()
            self._pairing.stop()
            return self._pairing_snapshot()

    def _pairing_snapshot(
        self, *, now: datetime | None = None
    ) -> dict[str, Any]:
        """Add dry-run transmitter capability and UI stage information."""
        if self._pairing is None:
            raise RuntimeError("persistent pairing state is unavailable")
        snapshot = self._pairing.status(now=now)
        profile: dict[str, Any] | None = None
        candidates = snapshot.get("candidates", [])
        if snapshot.get("new_records"):
            stage = "paired_identity_observed"
        elif candidates:
            stage = "factory_detected_transmitter_required"
            profile = automatic_hcs026_profile_metadata()
            profile["factory_endpoint"] = str(candidates[0])
            profile["paired_endpoint"] = paired_endpoint(str(candidates[0]))
        elif snapshot.get("active"):
            stage = "waiting_for_factory_announcement"
        else:
            stage = "inactive"
        pairing_nodes = self._pairing_nodes()
        selected_node = next(
            (
                item
                for item in pairing_nodes
                if item["node_id"] == self._active_pairing_node_id
            ),
            None,
        )
        if selected_node is not None:
            node_state = (
                selected_node.get("pairing_state")
                if selected_node.get("pairing_command_id")
                == self._active_pairing_command_id
                else None
            )
            if node_state == "failed":
                stage = "transmitter_failed"
            elif node_state == "completed" and not snapshot.get("new_records"):
                stage = "terminal_confirmation_processing"
            elif node_state == "armed":
                stage = "transmitter_armed"
        return {
            "available": True,
            "supported_profiles": [automatic_hcs026_profile_metadata()],
            "transmitter_available": bool(pairing_nodes),
            "transmitter_required": True,
            "pairing_nodes": pairing_nodes,
            "selected_node_id": self._active_pairing_node_id,
            "command_id": self._active_pairing_command_id,
            "transmit_performed": self._active_pairing_node_id is not None,
            "stage": stage,
            "dry_run_profile": profile,
            **snapshot,
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
            if self._active_pairing_node_id is not None:
                node = next(
                    (
                        item
                        for item in self._pairing_nodes()
                        if item["node_id"] == self._active_pairing_node_id
                    ),
                    None,
                )
                if (
                    node is None
                    or node.get("pairing_command_id")
                    != self._active_pairing_command_id
                    or node.get("pairing_state") != "completed"
                ):
                    raise RuntimeError(
                        "selected radio node has not confirmed pairing completion"
                    )
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
            existing_sensor = self.catalog.sensor(endpoint)
            device_id = (
                existing_sensor.device_id
                if existing_sensor is not None
                else f"hcs026-{endpoint}"
            )
            registered = self._store.accept_endpoint(
                endpoint=endpoint,
                device_id=device_id,
                name=name,
                model="HCS026FRF",
                area=area,
                accepted_at=timestamp,
            )
            self._refresh_registry_catalog()
            resolved = self.catalog.sensor(endpoint)
            resolved_device_id = resolved.device_id if resolved else device_id
            if resolved_device_id in self._devices:
                self._devices[resolved_device_id]["name"] = name
                self._devices[resolved_device_id]["area"] = area
            self._cancel_active_pairing_node()
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
        message_type = state.get("rf_message_type", state.get("message_type"))
        if isinstance(message_type, int):
            fields["message_type"] = message_type & 0x7F
        try:
            observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            observed = datetime.now(timezone.utc)
        self._pairing.observe(fields, now=observed)

    def _pairing_nodes(self) -> list[dict[str, Any]]:
        """Return connected protocol-v2 nodes with the narrow pairing capability."""
        if self._node_command_sender is None:
            return []
        return [
            copy.deepcopy(node)
            for node in self._nodes.values()
            if node.get("connected") is True
            and node.get("authenticated") is True
            and node.get("protocol_version") == 2
            and "sensor_pairing_tx" in node.get("capabilities", [])
        ]

    def _cancel_active_pairing_node(self) -> None:
        """Best-effort disarm for the node selected by the current session."""
        node_id = self._active_pairing_node_id
        command_id = self._active_pairing_command_id
        sender = self._node_command_sender
        if node_id is not None and command_id is not None and sender is not None:
            try:
                sender(
                    node_id,
                    {"type": "pairing_cancel", "command_id": command_id},
                )
            except (ConnectionError, KeyError, RuntimeError, ValueError):
                pass
        self._active_pairing_node_id = None
        self._active_pairing_command_id = None

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
            existing_sensor = (
                self.catalog.sensor(endpoint)
                if model == "HCS026FRF"
                else None
            )
            registered = self._store.accept_endpoint(
                endpoint=endpoint,
                device_id=(
                    existing_sensor.device_id
                    if existing_sensor is not None
                    else f"local-{endpoint}"
                ),
                name=name,
                model=model,
                area=area,
                accepted_at=timestamp,
            )
            self._refresh_registry_catalog()
            return registered

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
            updated = self._store.update_registry_device(
                device_id,
                name=next_name,
                area=next_area,
                updated_at=timestamp,
            )
            self._refresh_registry_catalog()
            resolved = self.catalog.sensor(str(updated["endpoint"]))
            resolved_device_id = resolved.device_id if resolved else device_id
            if resolved_device_id in self._devices:
                self._devices[resolved_device_id]["name"] = updated["name"]
                self._devices[resolved_device_id]["area"] = updated["area"]
            return updated

    def forget_registry_device(self, device_id: str) -> dict[str, Any]:
        """Forget local metadata and enrollment without RF transmission."""
        with self._lock:
            if not self._store:
                raise RuntimeError("persistent registry is unavailable")
            existing = self._store.registry_device(device_id)
            endpoint = str(existing["endpoint"])
            sensor = self.catalog.sensor(endpoint)
            resolved_device_id = sensor.device_id if sensor else device_id
            enrollment_factory = None
            if existing.get("model") == "HCS026FRF" and endpoint.endswith("24"):
                try:
                    enrollment_factory = factory_endpoint(endpoint)
                except ValueError:
                    enrollment_factory = endpoint
            forgotten = self._store.forget_registry_device(
                device_id,
                suppressed_at=datetime.now(timezone.utc).isoformat(),
                enrollment_factory_endpoint=enrollment_factory,
            )
            if (
                self._pairing is not None
                and forgotten.get("model") == "HCS026FRF"
                and str(forgotten.get("endpoint", "")).endswith("24")
            ):
                self._pairing.forget(
                    str(forgotten["endpoint"]), persist=False
                )
            self._refresh_registry_catalog()
            self._devices.pop(resolved_device_id, None)
            return forgotten

    def forget_sensor(self, device_id: str) -> dict[str, Any]:
        """Hide and dissociate one known HCS026 sensor without RF TX."""
        with self._lock:
            if not self._store or self._pairing is None:
                raise RuntimeError("persistent sensor registry is unavailable")
            device = self._devices.get(device_id)
            if device is None:
                match = re.fullmatch(r"hcs026-([0-9a-f]{8})", device_id)
                if match and match.group(1) in self._suppressed_endpoints:
                    endpoint = match.group(1)
                    return {
                        "device_id": device_id,
                        "endpoint": endpoint,
                        "factory_endpoint": factory_endpoint(endpoint),
                        "model": "HCS026FRF",
                        "already_forgotten": True,
                        "registry_record_removed": False,
                    }
                raise KeyError(device_id)
            if device.get("model") != "HCS026FRF":
                raise ValueError("only HCS026 sensors can be forgotten")
            state = device.get("state", {})
            endpoint = str(
                state.get("rf_endpoint") or state.get("rf_paired_endpoint") or ""
            ).lower()
            if not re.fullmatch(r"[0-9a-f]{8}", endpoint):
                raise ValueError("sensor has no valid paired RF endpoint")
            factory = factory_endpoint(endpoint)
            registered = self._store.forget_sensor_endpoint(
                endpoint,
                suppressed_at=datetime.now(timezone.utc).isoformat(),
                enrollment_factory_endpoint=factory,
            )
            self._pairing.forget(endpoint, persist=False)
            self._refresh_registry_catalog()
            self._devices.pop(device_id, None)
            return {
                "device_id": device_id,
                "endpoint": endpoint,
                "factory_endpoint": factory,
                "name": device.get("name", device_id),
                "model": "HCS026FRF",
                "registry_record_removed": registered is not None,
            }

    def _refresh_registry_catalog(self) -> None:
        """Layer persistent sensor identity metadata over compatibility data."""
        registrations = self._store.registry() if self._store else []
        self._suppressed_endpoints = (
            self._store.suppressed_endpoints()
            if self._store
            else frozenset()
        )
        self.catalog = self._base_catalog.with_registry_sensors(registrations)
        metadata: dict[str, dict[str, Any]] = {}
        for registration in registrations:
            if registration.get("model") != "HCS026FRF":
                continue
            sensor = self.catalog.sensor(str(registration["endpoint"]))
            if sensor is not None:
                metadata[sensor.device_id] = copy.deepcopy(registration)
        self._registry_metadata = metadata

    def _migrate_legacy_registry_identities(self) -> None:
        """Align known endpoints with IDs already exposed by the prototype."""
        if self._store is None:
            return
        for registration in self._store.registry():
            if registration.get("model") != "HCS026FRF":
                continue
            sensor = self._base_catalog.sensor(str(registration["endpoint"]))
            if (
                sensor is not None
                and registration.get("device_id") != sensor.device_id
            ):
                self._store.migrate_registry_device_id(
                    sensor.endpoint, sensor.device_id
                )

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
            device_id = str(event["device_id"])
            registry_metadata = self._registry_metadata.get(device_id)
            device = {
                "device_id": event["device_id"],
                "name": (
                    registry_metadata["name"]
                    if registry_metadata is not None
                    else event["name"]
                ),
                "model": event["model"],
                "available": True,
                "last_event_id": event["event_id"],
                "observed_at": event["observed_at"],
                "state": copy.deepcopy(event["state"]),
            }
            if registry_metadata is not None:
                device["area"] = registry_metadata.get("area")
            self._devices[event["device_id"]] = device

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

    def _is_restorable_device(self, event: dict[str, Any]) -> bool:
        """Reject obsolete auto-discoveries that predate endpoint validation."""
        if frame_accepted(event) is False:
            return False
        if event.get("model") != "HCS026FRF":
            return True
        endpoint = str(event.get("state", {}).get("rf_endpoint", "")).lower()
        if endpoint in self._suppressed_endpoints:
            return False
        device_id = str(event.get("device_id", ""))
        if not device_id.startswith("hcs026-"):
            return True
        state = event.get("state", {})
        return (
            endpoint in self.catalog.sensor_endpoints
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
