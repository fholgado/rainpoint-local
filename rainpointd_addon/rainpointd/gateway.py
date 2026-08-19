"""Transport-independent state and event model for the local gateway."""

from __future__ import annotations

import copy
import hmac
import os
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
from .firmware_catalog import FirmwareCatalog
from .pairing import HCS026EnrollmentManager, factory_endpoint, paired_endpoint
from .pairing_protocol import (
    AUTOMATIC_HCS026_PROFILE_ID,
    automatic_hcs026_profile_metadata,
    pairing_profile,
)
from .valve_pairing_protocol import (
    AUTOMATIC_HTV405_PROFILE_ID,
    CALIBRATED_FREQUENCY_OFFSET_HZ as HTV405_FREQUENCY_OFFSET_HZ,
    automatic_htv405_profile_metadata,
    build_htv405_profile,
)
from .valve_protocol import is_htv405_link_frame
from .product_identity import (
    GENERIC_HCS02X_MODEL,
    HCS026_MODEL,
    HCS02X_PROTOCOL,
    HTV145_MODEL,
    PRODUCT_MODELS,
    ProductIdentity,
    family_from_product_code,
    hcs02x_identity,
    is_hcs02x_sensor,
    product_for_model,
)
from .storage import (
    DEFAULT_EVENT_RETENTION_LIMIT,
    SQLiteEventStore,
    frame_accepted,
)


API_VERSION = "v1"
REPORTING_TIMEOUTS = {
    HCS026_MODEL: 15 * 60,
    HTV145_MODEL: 6 * 60 * 60,
}
PROTOCOL_REPORTING_TIMEOUTS = {HCS02X_PROTOCOL: 15 * 60}
DEFAULT_REPORTING_TIMEOUT = 60 * 60
RECEIVER_DEDUPLICATION_SECONDS = 0.25
REGISTRY_MODELS = {
    GENERIC_HCS02X_MODEL,
    *(product.model for product in PRODUCT_MODELS),
}
RADIO_NODE_ID = re.compile(r"rp-[0-9a-f]{12}\Z")
RADIO_NODE_TOKEN = re.compile(r"[0-9a-fA-F]{64}\Z")
FIRMWARE_VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+-]{0,47}\Z")
FIRMWARE_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")
FIRMWARE_PUBLIC_HOST = re.compile(
    r"(?=.{1,253}\Z)[0-9A-Za-z](?:[0-9A-Za-z.-]*[0-9A-Za-z])?\Z"
)
MAXIMUM_ROUTINE_ACK_ASSIGNMENTS = 8
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
        registry_token_path: str | None = None,
        claim_code: str | None = None,
        catalog: DeviceCatalog = LEGACY_HOME_CATALOG,
        firmware_catalog: FirmwareCatalog | None = None,
        firmware_public_port: int = 8787,
    ) -> None:
        self.gateway_id = gateway_id
        self.transport = transport
        self.read_only = read_only
        self._registry_token = registry_token or None
        self._registry_token_path = (
            Path(registry_token_path) if registry_token_path else None
        )
        self._claim_code = claim_code or None
        self._base_catalog = catalog
        self.catalog = catalog
        self._firmware_catalog = firmware_catalog or FirmwareCatalog()
        self._firmware_public_port = firmware_public_port
        self._registry_metadata: dict[str, dict[str, Any]] = {}
        self._suppressed_endpoints: frozenset[str] = frozenset()
        self._devices: dict[str, dict[str, Any]] = {}
        self._nodes: dict[str, dict[str, Any]] = {}
        self._memory_metrics: dict[str, dict[str, Any]] = {}
        self._memory_reception_metrics: dict[str, dict[str, Any]] = {}
        self._recent_receiver_frames: dict[str, tuple[str, float]] = {}
        self._sensor_link_diagnostics: dict[str, dict[str, Any]] = {}
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
            self._restore_observed_htv405_links()
        self._restore_devices()
        self._ensure_registered_sensor_devices()
        self._ensure_registered_valve_devices()
        self._next_event_id = self.latest_event_id() + 1
        self._lock = threading.Lock()
        self._event_condition = threading.Condition(self._lock)
        self._transport_healthy = True
        self._transport_error: str | None = None
        self._node_command_sender: (
            Callable[[str, dict[str, Any]], None] | None
        ) = None
        self._active_pairing_node_id: str | None = None
        self._active_pairing_command_id: str | None = None
        self._active_pairing_profile_id: str | None = None
        self._active_pairing_ack_parameters: dict[str, Any] | None = None
        self._pending_node_adoptions: dict[str, dict[str, Any]] = {}
        self._automatic_rejoin_started: dict[str, float] = {}

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
                "api_versions": [API_VERSION],
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
                "claim_available": self._claim_code is not None,
                "rf_pairing_available": bool(self._pairing_nodes()),
                "rf_pairing_monitor_available": self._pairing is not None,
                "rf_pairing_transmitter_required": True,
                "latest_event_id": self.latest_event_id(),
                "capabilities": [
                    "device_snapshots",
                    "event_long_poll",
                    "radio_node_adoption",
                    "sensor_pairing",
                    "routine_ack_ownership",
                    *(
                        ["firmware_updates"]
                        if self._firmware_catalog.enabled
                        else []
                    ),
                ],
                "event_delivery": {
                    "mode": "long_poll",
                    "max_wait_seconds": 30,
                },
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

    def observe_sensor_link_status(
        self, node_id: str, endpoint: str, **fields: Any
    ) -> None:
        """Record an owner node's ACK or paired-sensor recovery outcome."""
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._event_condition:
            diagnostics = self._sensor_link_diagnostics.setdefault(
                endpoint, {"rf_ack_owner_node_id": node_id}
            )
            if (
                fields.get("rf_ack_confirmation") == "pending_observation"
                and diagnostics.get("rf_ack_confirmation")
                == "pending_observation"
            ):
                diagnostics["rf_ack_unconfirmed_attempts"] = int(
                    diagnostics.get("rf_ack_unconfirmed_attempts", 0)
                ) + 1
            diagnostics.update(copy.deepcopy({
                key: value for key, value in fields.items()
                if value is not None
            }))
            diagnostics["rf_ack_owner_node_id"] = node_id
            diagnostics["rf_link_status_at"] = timestamp
            device_id = next(
                (
                    item_id
                    for item_id, device in self._devices.items()
                    if str(device.get("state", {}).get("rf_endpoint", "")).lower()
                    == endpoint
                ),
                None,
            )
            event = {
                "event_id": self._next_event_id,
                "event_type": "sensor_link_status",
                "observed_at": timestamp,
                "node_id": node_id,
                "state": copy.deepcopy(diagnostics),
            }
            if device_id is not None:
                event["device_id"] = device_id
            self._next_event_id += 1
            self._events.append(event)
            if self._store:
                self._store.append(event)
            self._event_condition.notify_all()

    def notify_node_update(self, node_id: str, event_type: str) -> None:
        """Wake long-poll clients for an infrequent node lifecycle change."""
        with self._event_condition:
            event = {
                "event_id": self._next_event_id,
                "event_type": event_type,
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "node_id": node_id,
            }
            self._next_event_id += 1
            self._events.append(event)
            if self._store:
                self._store.append(event)
            self._event_condition.notify_all()

    def set_node_command_sender(
        self, sender: Callable[[str, dict[str, Any]], None] | None
    ) -> None:
        """Attach the authenticated node command boundary owned by the LAN server."""
        with self._lock:
            self._node_command_sender = sender

    def restore_radio_node_ack_assignments(self, node_id: str) -> int:
        """Restore gateway-owned ACK routes after a node reconnect or OTA boot."""
        with self._lock:
            if self._store is None or self._node_command_sender is None:
                return 0
            node = self._nodes.get(node_id, {})
            if "routine_sensor_ack_tx" not in node.get("capabilities", []):
                return 0
            assignments = self._store.ack_assignments(node_id)
            sender = self._node_command_sender
        restored = 0
        for assignment in assignments:
            command = self._ack_configuration_command(assignment)
            try:
                sender(node_id, command)
            except (ConnectionError, KeyError, RuntimeError, ValueError):
                break
            self.update_node(
                node_id, routine_ack_command_id=command["command_id"]
            )
            restored += 1
        self.update_node(
            node_id,
            routine_ack_assigned_sensors=len(assignments),
            routine_ack_restore_requested=restored,
        )
        return restored

    def assign_radio_node_ack(
        self,
        *,
        node_id: str,
        paired_endpoint: str,
        assigned_channel: int,
        frequency_offset_hz: int = 45_000,
        power_dbm: int = 10,
        invert: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Persist one explicit single-owner ACK route and configure if online."""
        node_id = node_id.strip().lower()
        paired_endpoint = paired_endpoint.strip().lower()
        if not RADIO_NODE_ID.fullmatch(node_id):
            raise ValueError("invalid radio node ID")
        try:
            factory_endpoint(paired_endpoint)
        except ValueError as error:
            raise ValueError("invalid paired sensor endpoint") from error
        if assigned_channel not in {4, 5}:
            raise ValueError("ACK channel must be 4 or 5")
        if not -200_000 <= frequency_offset_hz <= 200_000:
            raise ValueError("ACK frequency offset is out of range")
        if power_dbm not in {-30, -20, -15, -10, -6, 0, 5, 7, 10}:
            raise ValueError("ACK transmit power is unsupported")
        if not isinstance(invert, bool):
            raise ValueError("ACK polarity must be boolean")
        with self._lock:
            if self._store is None:
                raise RuntimeError("persistent ACK assignment storage unavailable")
            if paired_endpoint not in {
                str(item["paired_endpoint"])
                for item in self._store.enrollment_records()
            }:
                raise KeyError(paired_endpoint)
            if node_id not in {
                str(item["node_id"]) for item in self._store.radio_nodes()
            }:
                raise KeyError(node_id)
            owned = self._store.ack_assignments(node_id)
            if (
                len(owned) >= MAXIMUM_ROUTINE_ACK_ASSIGNMENTS
                and paired_endpoint
                not in {item["paired_endpoint"] for item in owned}
            ):
                raise ValueError("radio node acknowledgement capacity is full")
            assignment = {
                "paired_endpoint": paired_endpoint,
                "node_id": node_id,
                "assigned_channel": assigned_channel,
                "frequency_offset_hz": frequency_offset_hz,
                "power_dbm": power_dbm,
                "invert": invert,
                "updated_at": (now or datetime.now(timezone.utc)).isoformat(),
            }
            previous = next(
                (
                    item
                    for item in self._store.ack_assignments()
                    if item["paired_endpoint"] == paired_endpoint
                ),
                None,
            )
            if (
                previous is not None
                and previous["node_id"] != node_id
                and self._node_command_sender is not None
            ):
                try:
                    self._node_command_sender(
                        str(previous["node_id"]),
                        {
                            "type": "routine_ack_revoke",
                            "command_id": uuid.uuid4().hex,
                            "paired_endpoint": paired_endpoint,
                        },
                    )
                except (ConnectionError, KeyError, RuntimeError, ValueError):
                    pass
            self._store.upsert_ack_assignment(assignment)
            node = self._nodes.get(node_id, {})
            if (
                self._node_command_sender is not None
                and node.get("connected") is True
                and "routine_sensor_ack_tx" in node.get("capabilities", [])
            ):
                command = self._ack_configuration_command(assignment)
                self._node_command_sender(node_id, command)
                self._nodes.setdefault(node_id, {"node_id": node_id})[
                    "routine_ack_command_id"
                ] = command["command_id"]
            return copy.deepcopy(assignment)

    def ack_assignments(self) -> list[dict[str, Any]]:
        """Return the persistent ownership map without node credentials."""
        with self._lock:
            return self._store.ack_assignments() if self._store else []

    @staticmethod
    def _ack_configuration_command(assignment: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "routine_ack_configure",
            "command_id": uuid.uuid4().hex,
            "paired_endpoint": assignment["paired_endpoint"],
            "assigned_channel": int(assignment["assigned_channel"]),
            "frequency_offset_hz": int(assignment["frequency_offset_hz"]),
            "power_dbm": int(assignment["power_dbm"]),
            "invert": bool(assignment["invert"]),
        }

    def _delete_ack_assignment_locked(self, endpoint: str) -> None:
        if self._store is None:
            return
        assignment = self._store.delete_ack_assignment(endpoint)
        if assignment is None or self._node_command_sender is None:
            return
        try:
            command = (
                {
                    "type": "routine_ack_revoke",
                    "command_id": uuid.uuid4().hex,
                    "paired_endpoint": endpoint,
                }
            )
            self._node_command_sender(
                str(assignment["node_id"]),
                command,
            )
            node = self._nodes.setdefault(
                str(assignment["node_id"]),
                {"node_id": str(assignment["node_id"])},
            )
            node["routine_ack_command_id"] = command["command_id"]
        except (ConnectionError, KeyError, RuntimeError, ValueError):
            pass

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
            result = list(nodes.values())
            for node in result:
                if self._store is not None:
                    node["routine_ack_assigned_sensors"] = len(
                        self._store.ack_assignments(str(node["node_id"]))
                    )
                release = self._firmware_catalog.latest_for_node(node)
                if release is not None:
                    node["firmware_update"] = release
            return sorted(result, key=lambda item: item["node_id"])

    def firmware_releases(self) -> list[dict[str, Any]]:
        """Return public metadata for locally staged firmware releases."""
        return self._firmware_catalog.releases()

    def firmware_artifact(self, release_id: str) -> tuple[bytes, str]:
        """Resolve and verify one artifact immediately before HTTP delivery."""
        release = self._firmware_catalog.get(release_id)
        content = self._firmware_catalog.verified_artifact_content(release_id)
        return content, release.sha256

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

    def revoke_radio_node(self, node_id: str) -> dict[str, Any]:
        """Revoke one adopted node credential without deleting RF devices."""
        node_id = node_id.strip().lower()
        if not self._store:
            raise RuntimeError("persistent radio-node registry is unavailable")
        with self._lock:
            revoked = self._store.delete_radio_node(node_id)
            self._pending_node_adoptions.pop(node_id, None)
            node = self._nodes.get(node_id)
            if node is not None:
                node["managed"] = False
                node["authenticated"] = False
        return {"node_id": node_id, "revoked": revoked}

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

    def start_radio_node_firmware_update(
        self,
        node_id: str,
        *,
        url: str,
        version: str,
        size_bytes: int,
        sha256: str,
    ) -> dict[str, Any]:
        """Start an integrity-checked update on an explicit OTA trial node."""
        node_id = node_id.strip().lower()
        if (
            not url.startswith("http://")
            or len(url) > 320
            or any(character.isspace() for character in url)
            or not FIRMWARE_VERSION.fullmatch(version)
            or not 64 * 1024 <= size_bytes <= 2 * 1024 * 1024
            or not FIRMWARE_SHA256.fullmatch(sha256)
        ):
            raise ValueError("invalid firmware update metadata")
        with self._lock:
            node = self._nodes.get(node_id)
            if (
                node is None
                or node.get("connected") is not True
                or node.get("authenticated") is not True
            ):
                raise ValueError("radio node is not connected")
            if "firmware_update_trial" not in node.get("capabilities", []):
                raise ValueError("radio node does not support OTA trials")
            if node.get("tx_armed") is True:
                raise ValueError("radio node is armed for RF transmission")
            if self._node_command_sender is None:
                raise RuntimeError("radio-node command transport is unavailable")
            command_id = uuid.uuid4().hex
            command = {
                "type": "firmware_update_start",
                "command_id": command_id,
                "url": url,
                "version": version,
                "size_bytes": size_bytes,
                "sha256": sha256.lower(),
            }
            self._node_command_sender(node_id, command)
            node.update(
                {
                    "firmware_update_state": "requested",
                    "firmware_update_command_id": command_id,
                    "firmware_candidate_version": version,
                    "firmware_update_received_bytes": 0,
                    "firmware_update_total_bytes": size_bytes,
                }
            )
            return {
                "node_id": node_id,
                "state": "requested",
                "command_id": command_id,
                "candidate_version": version,
                "size_bytes": size_bytes,
            }

    def install_radio_node_firmware_release(
        self,
        node_id: str,
        *,
        release_id: str,
        public_host: str | None = None,
    ) -> dict[str, Any]:
        """Install one catalogued release without accepting artifact metadata."""
        node_id = node_id.strip().lower()
        with self._lock:
            node = copy.deepcopy(self._nodes.get(node_id))
        if node is None:
            raise ValueError("radio node is not connected")
        if not self._firmware_catalog.compatible(release_id, node):
            raise ValueError("firmware release is not compatible with radio node")
        release = self._firmware_catalog.get(release_id)
        self._firmware_catalog.verified_artifact(release_id)
        host = str(node.get("gateway_host") or public_host or "").strip()
        if not FIRMWARE_PUBLIC_HOST.fullmatch(host):
            raise ValueError("firmware public host is unavailable")
        url = (
            f"http://{host}:{self._firmware_public_port}/firmware/"
            f"{release.release_id}.bin"
        )
        result = self.start_radio_node_firmware_update(
            node_id,
            url=url,
            version=release.version,
            size_bytes=release.size_bytes,
            sha256=release.sha256,
        )
        result["release_id"] = release.release_id
        return result

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

    def update_radio_node_metadata(
        self,
        *,
        node_id: str,
        name: str,
        area: str | None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Update a managed node's friendly metadata without its credential."""
        if not self._store:
            raise RuntimeError("persistent radio-node registry is unavailable")
        node_id = node_id.strip().lower()
        name = name.strip()
        if not name or len(name) > 100:
            raise ValueError("radio-node name must be 1 to 100 characters")
        if area is not None:
            area = area.strip() or None
            if area is not None and len(area) > 100:
                raise ValueError("radio-node area must be at most 100 characters")
        timestamp = (now or datetime.now(timezone.utc)).isoformat()
        with self._lock:
            updated = self._store.update_radio_node(
                node_id,
                name=name,
                area=area,
                updated_at=timestamp,
            )
            node = self._nodes.setdefault(node_id, {"node_id": node_id})
            node.update({"name": name, "area": area})
            return updated

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
            self._event_condition.notify_all()
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
            self._confirm_sensor_ack_locked(decoded, timestamp)
            duplicate = self._receiver_duplicate_locked(
                frame=frame,
                state=decoded,
                observed_at=timestamp,
                device_id=device_id,
            )
            if duplicate is not None:
                return duplicate
            rejoin = self._maybe_start_known_sensor_rejoin(decoded)
            if rejoin is not None:
                decoded["automatic_rejoin"] = rejoin
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
            self._event_condition.notify_all()
            if self._store:
                self._store.append(event)
            else:
                self._update_memory_reception_metrics(event)
            self._observe_pairing(decoded, timestamp)
            return copy.deepcopy(event)

    def _confirm_sensor_ack_locked(
        self, state: dict[str, Any], observed_at: str
    ) -> None:
        """Correlate a valid over-air ACK seen by a second receiver."""
        endpoint = state.get("routine_ack_endpoint")
        if not isinstance(endpoint, str):
            return
        diagnostics = self._sensor_link_diagnostics.get(endpoint.lower())
        if diagnostics is None or (
            diagnostics.get("rf_ack_confirmation") != "pending_observation"
        ):
            return
        attempted_at = diagnostics.get("rf_link_status_at")
        if not isinstance(attempted_at, str):
            return
        try:
            attempted = datetime.fromisoformat(
                attempted_at.replace("Z", "+00:00")
            )
            observed = datetime.fromisoformat(
                observed_at.replace("Z", "+00:00")
            )
            if attempted.tzinfo is None:
                attempted = attempted.replace(tzinfo=timezone.utc)
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            elapsed = (observed - attempted).total_seconds()
        except ValueError:
            return
        if not 0 <= elapsed <= 2:
            return
        diagnostics["rf_ack_confirmation"] = "observed_over_air"
        diagnostics["rf_ack_observed_at"] = observed_at
        receiver = state.get("rf_receiver_id")
        if isinstance(receiver, str):
            diagnostics["rf_ack_observer"] = receiver
        state["local_ack_confirmation"] = "observed_over_air"

    def _maybe_start_known_sensor_rejoin(
        self, state: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Answer a known sensor's factory announcement without an open UI flow."""
        if self._store is None or self._node_command_sender is None:
            return None
        if self._pairing is not None and self._pairing.status().get("active"):
            return None
        pairing_state = state.get(
            "hcs026_pairing_state", state.get("rf_pairing_state")
        )
        factory = state.get(
            "hcs026_factory_endpoint", state.get("rf_factory_endpoint")
        )
        if pairing_state != "factory" or not isinstance(factory, str):
            return None
        try:
            endpoint = paired_endpoint(factory.strip().lower())
        except ValueError:
            return None
        known = any(
            str(item["paired_endpoint"]) == endpoint
            for item in self._store.enrollment_records()
        )
        assignment = next(
            (
                item
                for item in self._store.ack_assignments()
                if str(item["paired_endpoint"]) == endpoint
            ),
            None,
        )
        if not known:
            return None
        result: dict[str, Any] = {
            "known_sensor": True,
            "factory_endpoint": factory.strip().lower(),
            "paired_endpoint": endpoint,
            "requested": False,
        }
        if endpoint in self._suppressed_endpoints:
            result["reason"] = "sensor_suppressed"
            return result
        if assignment is None:
            result["reason"] = "ack_owner_unassigned"
            return result
        result["ack_owner_node_id"] = str(assignment["node_id"])
        now_monotonic = time.monotonic()
        previous_request = self._automatic_rejoin_started.get(endpoint)
        if (
            previous_request is not None
            and now_monotonic - previous_request < 90
        ):
            result["reason"] = "cooldown_active"
            return result
        node_id = str(assignment["node_id"])
        node = self._nodes.get(node_id, {})
        if not (
            node.get("connected") is True
            and node.get("authenticated") is True
            and "sensor_pairing_tx" in node.get("capabilities", [])
        ):
            result["reason"] = "ack_owner_offline"
            return result
        local_clock = (
            datetime.now().astimezone() + timedelta(seconds=240)
        ).strftime("%Y%m%d%H%M%S")
        command_id = uuid.uuid4().hex
        command = {
            "type": "pairing_start",
            "command_id": command_id,
            "profile": AUTOMATIC_HCS026_PROFILE_ID,
            "factory_endpoint": factory.strip().lower(),
            "known_rejoin": True,
            "duration_seconds": 60,
            "local_clock": local_clock,
            "frequency_offset_hz": int(assignment["frequency_offset_hz"]),
            "power_dbm": int(assignment["power_dbm"]),
            "invert": bool(assignment["invert"]),
        }
        try:
            self._node_command_sender(node_id, command)
        except (ConnectionError, KeyError, RuntimeError, ValueError):
            result["reason"] = "command_delivery_failed"
            return result
        self._automatic_rejoin_started[endpoint] = now_monotonic
        node.update(
            {
                "automatic_rejoin_endpoint": endpoint,
                "automatic_rejoin_command_id": command_id,
                "automatic_rejoin_state": "requested",
            }
        )
        result.update(
            {
                "requested": True,
                "reason": "known_factory_announcement",
                "command_id": command_id,
            }
        )
        return result

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
                    device["model"] = registered["model"]
                    state = device.setdefault("state", {})
                    if registered.get("protocol"):
                        state["rf_protocol_family"] = registered["protocol"]
                    if registered.get("model_source"):
                        state["product_model_source"] = registered[
                            "model_source"
                        ]
                    if registered.get("product_code") is not None:
                        state["rf_product_code"] = registered["product_code"]
                        family = family_from_product_code(
                            "soil_sensor", registered["product_code"]
                        )
                        if family is not None:
                            state["product_family_capabilities"] = list(
                                family.catalog_capabilities
                            )
                    if registered.get("model_code") is not None:
                        state["rf_model_code"] = registered["model_code"]
                if is_hcs02x_sensor(
                    model=device.get("model"),
                    protocol=device.get("state", {}).get("rf_protocol_family"),
                ):
                    state = device.setdefault("state", {})
                    state["device_kind"] = "soil_sensor"
                    state["product_model_exact"] = (
                        product_for_model(device.get("model")) is not None
                    )
                    device["capabilities"] = ["forget", "soil_moisture"]
                    endpoint = str(state.get("rf_endpoint", "")).lower()
                    if endpoint in self._sensor_link_diagnostics:
                        state.update(copy.deepcopy(
                            self._sensor_link_diagnostics[endpoint]
                        ))
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
                "last_report_interval_seconds": None,
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
        metric["last_report_interval_seconds"] = round(gap, 3)
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

    def events(
        self, since: int = 0, wait_seconds: float = 0
    ) -> list[dict[str, Any]]:
        """Return retained events, optionally waiting for the next event."""
        wait_seconds = max(0.0, min(float(wait_seconds), 30.0))
        deadline = time.monotonic() + wait_seconds
        with self._event_condition:
            while True:
                if self._store:
                    events = self._store.events(since)
                else:
                    events = copy.deepcopy(
                        [
                            event
                            for event in self._events
                            if event["event_id"] > since
                        ]
                    )
                if events or wait_seconds == 0:
                    return events
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._event_condition.wait(timeout=remaining)

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

    def claim_registry(self, claim_code: str) -> str:
        """Exchange a one-time standalone setup code for a management token."""
        with self._lock:
            if self._claim_code is None or not hmac.compare_digest(
                claim_code, self._claim_code
            ):
                raise PermissionError("invalid or expired setup code")
            token = secrets.token_urlsafe(32)
            self._persist_registry_token_locked(token)
            self._registry_token = token
            self._claim_code = None
            return token

    def rotate_registry_token(self) -> str:
        """Replace the gateway credential and immediately revoke the old one."""
        with self._lock:
            token = secrets.token_urlsafe(32)
            self._persist_registry_token_locked(token)
            self._registry_token = token
            return token

    def _persist_registry_token_locked(self, token: str) -> None:
        """Atomically persist a rotated token when a credential path is set."""
        if self._registry_token_path is None:
            return
        path = self._registry_token_path
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(token, encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(path)

    def registry(self) -> list[dict[str, Any]]:
        """Return accepted local metadata; this is not RF pairing state."""
        with self._lock:
            return self._store.registry() if self._store else []

    def register_observed_htv405_link(
        self,
        *,
        controller_endpoint: str,
        valve_endpoint: str,
        frame: str,
        observed_at: str | None = None,
    ) -> dict[str, Any] | None:
        """Persist an HTV405 link only after a strict receive-side decode."""
        try:
            raw = bytes.fromhex(frame)
        except ValueError:
            return None
        if not is_htv405_link_frame(raw) or self._store is None:
            return None
        controller_endpoint = controller_endpoint.strip().lower()
        valve_endpoint = valve_endpoint.strip().lower()
        if (
            not re.fullmatch(r"[0-9a-f]{8}", controller_endpoint)
            or not re.fullmatch(r"[89a-f][0-9a-f]{5}13", valve_endpoint)
            or controller_endpoint == valve_endpoint
        ):
            return None
        with self._lock:
            existing = self.catalog.valve_link(
                controller_endpoint, valve_endpoint
            )
            if existing is not None:
                return {
                    "controller_endpoint": existing.controller_endpoint,
                    "valve_endpoint": existing.valve_endpoint,
                    "device_id": existing.device_id,
                    "name": existing.name,
                    "model": existing.model,
                }
            timestamp = observed_at or datetime.now(timezone.utc).isoformat()
            registration = self._store.upsert_valve_link(
                controller_endpoint=controller_endpoint,
                valve_endpoint=valve_endpoint,
                device_id=f"htv405-{valve_endpoint}",
                name=f"RainPoint 4-zone valve {valve_endpoint[-4:]}",
                model="HTV405FRF",
                area=None,
                accepted_at=timestamp,
            )
            self._refresh_registry_catalog()
            self._ensure_registered_valve_devices()
            return registration

    def _restore_observed_htv405_links(self) -> None:
        """Backfill valve links from retained strict structural reports."""
        if self._store is None:
            return
        changed = False
        for event in reversed(self._events):
            state = event.get("state", {})
            raw_hex = event.get("raw")
            controller_endpoint = state.get("rf_endpoint_a")
            valve_endpoint = state.get("rf_endpoint_b")
            if not all(
                isinstance(value, str)
                for value in (raw_hex, controller_endpoint, valve_endpoint)
            ):
                continue
            try:
                raw = bytes.fromhex(raw_hex)
            except ValueError:
                continue
            if (
                not is_htv405_link_frame(raw)
                or not re.fullmatch(
                    r"[89a-f][0-9a-f]{5}13", valve_endpoint.lower()
                )
                or self.catalog.valve_link(
                    controller_endpoint, valve_endpoint
                )
                is not None
            ):
                continue
            self._store.upsert_valve_link(
                controller_endpoint=controller_endpoint.lower(),
                valve_endpoint=valve_endpoint.lower(),
                device_id=f"htv405-{valve_endpoint.lower()}",
                name=f"RainPoint 4-zone valve {valve_endpoint[-4:]}",
                model="HTV405FRF",
                area=None,
                accepted_at=str(event["observed_at"]),
            )
            changed = True
        if changed:
            self._refresh_registry_catalog()

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
        factory_endpoint: str | None = None,
        valve_route: str | None = None,
        companion_endpoint: str | None = None,
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
            self._active_pairing_profile_id = None
            self._active_pairing_ack_parameters = None
            if node_id is not None:
                nodes = {item["node_id"]: item for item in self._pairing_nodes()}
                if node_id not in nodes:
                    self._pairing.stop()
                    raise ValueError("selected radio node cannot transmit pairing")
                if self._node_command_sender is None:
                    self._pairing.stop()
                    raise RuntimeError("radio-node command transport is unavailable")
                automatic = profile_id == AUTOMATIC_HCS026_PROFILE_ID
                valve_candidate = profile_id == AUTOMATIC_HTV405_PROFILE_ID
                valve_profile = None
                if valve_candidate:
                    try:
                        valve_profile = build_htv405_profile(
                            factory_endpoint=str(factory_endpoint or ""),
                            valve_route=str(valve_route or ""),
                            companion_endpoint=str(companion_endpoint or ""),
                        )
                    except ValueError:
                        self._pairing.stop()
                        raise ValueError(
                            "invalid HTV405 association identifiers"
                        ) from None
                    # Continuous stock-gateway captures encode the current
                    # wall clock. The four-minute lead is HCS026-specific.
                    clock_lead_seconds = 0
                elif automatic:
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
                    "frequency_offset_hz": (
                        HTV405_FREQUENCY_OFFSET_HZ
                        if valve_candidate
                        else 45_000
                    ),
                    "power_dbm": 10,
                    "invert": False,
                }
                if not automatic:
                    command["factory_endpoint"] = (
                        valve_profile.factory_endpoint
                        if valve_profile is not None
                        else profile.factory_endpoint
                    )
                if valve_profile is not None:
                    command["valve_route"] = valve_profile.valve_route
                    command["companion_endpoint"] = (
                        valve_profile.companion_endpoint
                    )
                try:
                    self._node_command_sender(node_id, command)
                except (ConnectionError, KeyError, RuntimeError, ValueError):
                    self._pairing.stop()
                    raise
                self._active_pairing_node_id = node_id
                self._active_pairing_command_id = command_id
                self._active_pairing_profile_id = profile_id
                self._active_pairing_ack_parameters = {
                    "frequency_offset_hz": command["frequency_offset_hz"],
                    "power_dbm": command["power_dbm"],
                    "invert": command["invert"],
                }
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
        completed_endpoint: str | None = None
        completed_existing_record = False
        new_records = snapshot.get("new_records", [])
        if new_records:
            completed_endpoint = str(new_records[0]["paired_endpoint"])
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
            reported_endpoint = selected_node.get("pairing_paired_endpoint")
            observed_valve_completed = False
            if (
                self._active_pairing_profile_id
                == AUTOMATIC_HTV405_PROFILE_ID
                and isinstance(reported_endpoint, str)
                and self._store is not None
            ):
                observed_valve_completed = any(
                    item["valve_endpoint"] == reported_endpoint.lower()
                    for item in self._store.valve_registry()
                )
            if observed_valve_completed:
                completed_endpoint = reported_endpoint.lower()
                stage = "valve_pairing_completed"
            elif node_state == "failed":
                stage = "transmitter_failed"
            elif node_state == "completed":
                if (
                    self._active_pairing_profile_id
                    == AUTOMATIC_HTV405_PROFILE_ID
                    and isinstance(reported_endpoint, str)
                    and re.fullmatch(r"[89a-f][0-9a-f]{5}13", reported_endpoint)
                ):
                    completed_endpoint = reported_endpoint
                    stage = "valve_pairing_completed"
                elif isinstance(reported_endpoint, str):
                    reported_endpoint = reported_endpoint.strip().lower()
                    try:
                        reported_factory = factory_endpoint(reported_endpoint)
                    except ValueError:
                        reported_endpoint = ""
                    if reported_endpoint and any(
                        item.factory_endpoint == reported_factory
                        and item.paired_endpoint == reported_endpoint
                        for item in self._pairing.records()
                    ):
                        completed_endpoint = reported_endpoint
                        completed_existing_record = not any(
                            item.get("paired_endpoint") == reported_endpoint
                            for item in new_records
                        )
                if stage != "valve_pairing_completed":
                    stage = (
                        "paired_identity_observed"
                        if completed_endpoint is not None
                        else "terminal_confirmation_processing"
                    )
            elif selected_node.get(
                "pairing_awaiting_terminal_confirmation"
            ) is True:
                stage = "waiting_for_terminal_confirmation"
            elif node_state == "armed":
                stage = (
                    "pairing_exchange_in_progress"
                    if int(selected_node.get("pairing_completed_steps") or 0) > 0
                    else "transmitter_armed"
                )
        return {
            "available": True,
            "supported_profiles": [
                automatic_hcs026_profile_metadata(),
                automatic_htv405_profile_metadata(),
            ],
            "transmitter_available": bool(pairing_nodes),
            "transmitter_required": True,
            "pairing_nodes": pairing_nodes,
            "selected_node_id": self._active_pairing_node_id,
            "active_profile_id": self._active_pairing_profile_id,
            "command_id": self._active_pairing_command_id,
            "transmit_performed": self._active_pairing_node_id is not None,
            "stage": stage,
            "completed_endpoint": completed_endpoint,
            "completed_existing_record": completed_existing_record,
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
            node: dict[str, Any] | None = None
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
            identity = hcs02x_identity(
                {},
                trusted_model=(
                    existing_sensor.model if existing_sensor is not None else None
                ),
            )
            try:
                existing_registration = self._store.registry_endpoint(endpoint)
            except KeyError:
                existing_registration = None
            if (
                existing_registration is not None
                and str(existing_registration.get("model_source", "")).startswith(
                    "rf_"
                )
            ):
                registration_model = str(existing_registration["model"])
                registration_protocol = str(
                    existing_registration.get("protocol") or identity.protocol
                )
                registration_source = str(
                    existing_registration["model_source"]
                )
                registration_product_code = existing_registration.get(
                    "product_code"
                )
                registration_model_code = existing_registration.get("model_code")
            else:
                registration_model = identity.model
                registration_protocol = identity.protocol
                registration_source = identity.source
                registration_product_code = identity.product_code
                registration_model_code = identity.model_code
            registered = self._store.accept_endpoint(
                endpoint=endpoint,
                device_id=device_id,
                name=name,
                model=registration_model,
                area=area,
                accepted_at=timestamp,
                protocol=registration_protocol,
                model_source=registration_source,
                product_code=registration_product_code,
                model_code=registration_model_code,
            )
            if (
                self._active_pairing_node_id is not None
                and node is not None
                and "routine_sensor_ack_tx" in node.get("capabilities", [])
                and self._active_pairing_ack_parameters is not None
                and node.get("pairing_assigned_channel") in {4, 5}
            ):
                assignment = {
                    "paired_endpoint": endpoint,
                    "node_id": self._active_pairing_node_id,
                    "assigned_channel": int(node["pairing_assigned_channel"]),
                    **self._active_pairing_ack_parameters,
                    "updated_at": timestamp,
                }
                self._store.upsert_ack_assignment(assignment)
                if self._node_command_sender is not None:
                    try:
                        command = self._ack_configuration_command(assignment)
                        self._node_command_sender(
                            self._active_pairing_node_id, command
                        )
                        node["routine_ack_command_id"] = command["command_id"]
                    except (
                        ConnectionError,
                        KeyError,
                        RuntimeError,
                        ValueError,
                    ):
                        pass
            self._refresh_registry_catalog()
            self._ensure_registered_sensor_devices()
            resolved = self.catalog.sensor(endpoint)
            resolved_device_id = resolved.device_id if resolved else device_id
            if resolved_device_id in self._devices:
                self._devices[resolved_device_id]["name"] = name
                self._devices[resolved_device_id]["area"] = area
            self._cancel_active_pairing_node()
            self._pairing.stop()
            return registered

    def confirm_product_identity(
        self,
        *,
        endpoint: str,
        identity: ProductIdentity,
        observed_at: str | None = None,
    ) -> None:
        """Persist stronger family or model identity inferred from RF evidence."""
        if not identity.source.startswith("rf_"):
            return
        with self._lock:
            if self._store is None:
                return
            try:
                existing = self._store.registry_endpoint(endpoint)
            except KeyError:
                return
            if (
                product_for_model(existing.get("model")) is not None
                and not identity.exact_model
            ):
                return
            if (
                existing.get("model") == identity.model
                and existing.get("model_source") == identity.source
                and existing.get("product_code") == identity.product_code
                and existing.get("model_code") == identity.model_code
            ):
                return
            timestamp = observed_at or datetime.now(timezone.utc).isoformat()
            self._store.update_registry_product_identity(
                endpoint,
                model=identity.model,
                protocol=identity.protocol,
                model_source=identity.source,
                product_code=identity.product_code,
                model_code=identity.model_code,
                updated_at=timestamp,
            )
            self._refresh_registry_catalog()
            device_id = str(existing["device_id"])
            if device_id in self._devices:
                self._devices[device_id]["model"] = identity.model

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
        registrations = {
            str(item["node_id"]): item
            for item in (self._store.radio_nodes() if self._store else [])
        }
        result = []
        for node in self._nodes.values():
            if not (
                node.get("connected") is True
                and node.get("authenticated") is True
                and node.get("protocol_version") == 2
                and "sensor_pairing_tx" in node.get("capabilities", [])
            ):
                continue
            item = copy.deepcopy(node)
            registration = registrations.get(str(node["node_id"]))
            if registration is not None:
                item.update(
                    {
                        "name": registration["name"],
                        "area": registration["area"],
                        "managed": True,
                    }
                )
            assigned = (
                len(self._store.ack_assignments(str(node["node_id"])))
                if self._store is not None
                else 0
            )
            item["routine_ack_assigned_sensors"] = assigned
            item["routine_ack_capacity"] = MAXIMUM_ROUTINE_ACK_ASSIGNMENTS
            if (
                "routine_sensor_ack_tx" in node.get("capabilities", [])
                and assigned >= MAXIMUM_ROUTINE_ACK_ASSIGNMENTS
            ):
                continue
            result.append(item)
        return result

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
        self._active_pairing_profile_id = None
        self._active_pairing_ack_parameters = None

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
                if is_hcs02x_sensor(model=model)
                else None
            )
            product = product_for_model(model)
            protocol = (
                HCS02X_PROTOCOL
                if is_hcs02x_sensor(model=model)
                else product.protocol if product is not None else None
            )
            try:
                existing_registration = self._store.registry_endpoint(endpoint)
            except KeyError:
                existing_registration = None
            if (
                existing_registration is not None
                and str(existing_registration.get("model_source", "")).startswith(
                    "rf_"
                )
            ):
                if model not in {
                    GENERIC_HCS02X_MODEL,
                    existing_registration["model"],
                }:
                    raise ValueError(
                        "requested model conflicts with packet-derived identity"
                    )
                model = str(existing_registration["model"])
                protocol = existing_registration.get("protocol")
                model_source = str(existing_registration["model_source"])
                product_code = existing_registration.get("product_code")
                model_code = existing_registration.get("model_code")
            else:
                model_source = "user_or_catalog"
                product_code = None
                model_code = None
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
                protocol=protocol,
                model_source=model_source,
                product_code=product_code,
                model_code=model_code,
            )
            self._refresh_registry_catalog()
            self._ensure_registered_sensor_devices()
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
            if is_hcs02x_sensor(
                model=existing.get("model"),
                protocol=existing.get("protocol"),
            ) and endpoint.endswith("24"):
                try:
                    enrollment_factory = factory_endpoint(endpoint)
                except ValueError:
                    enrollment_factory = endpoint
                self._delete_ack_assignment_locked(endpoint)
            forgotten = self._store.forget_registry_device(
                device_id,
                suppressed_at=datetime.now(timezone.utc).isoformat(),
                enrollment_factory_endpoint=enrollment_factory,
            )
            if (
                self._pairing is not None
                and is_hcs02x_sensor(
                    model=forgotten.get("model"),
                    protocol=forgotten.get("protocol"),
                )
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
                        "model": GENERIC_HCS02X_MODEL,
                        "already_forgotten": True,
                        "registry_record_removed": False,
                    }
                raise KeyError(device_id)
            if not is_hcs02x_sensor(
                model=device.get("model"),
                protocol=device.get("state", {}).get("rf_protocol_family"),
            ):
                raise ValueError("device does not use the HCS02x sensor protocol")
            state = device.get("state", {})
            endpoint = str(
                state.get("rf_endpoint") or state.get("rf_paired_endpoint") or ""
            ).lower()
            if not re.fullmatch(r"[0-9a-f]{8}", endpoint):
                raise ValueError("sensor has no valid paired RF endpoint")
            factory = factory_endpoint(endpoint)
            self._delete_ack_assignment_locked(endpoint)
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
                "model": device.get("model", GENERIC_HCS02X_MODEL),
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
        valve_registrations = (
            self._store.valve_registry() if self._store else []
        )
        self.catalog = self._base_catalog.with_registries(
            registrations, valve_registrations
        )
        metadata: dict[str, dict[str, Any]] = {}
        for registration in registrations:
            if not is_hcs02x_sensor(
                model=registration.get("model"),
                protocol=registration.get("protocol"),
            ):
                continue
            sensor = self.catalog.sensor(str(registration["endpoint"]))
            if sensor is not None:
                metadata[sensor.device_id] = copy.deepcopy(registration)
        for registration in valve_registrations:
            valve = self.catalog.valve_link(
                str(registration["controller_endpoint"]),
                str(registration["valve_endpoint"]),
            )
            if valve is not None:
                metadata[valve.device_id] = copy.deepcopy(registration)
        self._registry_metadata = metadata

    def _migrate_legacy_registry_identities(self) -> None:
        """Align known endpoints with IDs already exposed by the prototype."""
        if self._store is None:
            return
        for registration in self._store.registry():
            if not is_hcs02x_sensor(
                model=registration.get("model"),
                protocol=registration.get("protocol"),
            ):
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

    def _ensure_registered_sensor_devices(self) -> None:
        """Expose named sensors even when suppression hid their last report."""
        if self._store is None:
            return
        for registration in self._store.registry():
            if not is_hcs02x_sensor(
                model=registration.get("model"),
                protocol=registration.get("protocol"),
            ):
                continue
            endpoint = str(registration["endpoint"]).lower()
            if endpoint in self._suppressed_endpoints:
                continue
            device_id = str(registration["device_id"])
            state: dict[str, Any] = {
                "model": registration["model"],
                "rf_endpoint": endpoint,
                "rf_protocol_family": (
                    registration.get("protocol") or HCS02X_PROTOCOL
                ),
                "product_model_source": registration.get("model_source"),
                "product_model_exact": (
                    product_for_model(registration.get("model")) is not None
                ),
                "device_kind": "soil_sensor",
            }
            if registration.get("product_code") is not None:
                state["rf_product_code"] = registration["product_code"]
            if registration.get("model_code") is not None:
                state["rf_model_code"] = registration["model_code"]
            try:
                factory = factory_endpoint(endpoint)
            except ValueError:
                pass
            else:
                state.update(
                    {
                        "rf_factory_endpoint": factory,
                        "rf_paired_endpoint": endpoint,
                        "rf_pairing_state": "paired",
                    }
                )
            self._devices.setdefault(
                device_id,
                {
                    "device_id": device_id,
                    "name": registration["name"],
                    "model": registration["model"],
                    "available": False,
                    "last_event_id": 0,
                    "observed_at": None,
                    "state": state,
                    "area": registration.get("area"),
                },
            )

    def _ensure_registered_valve_devices(self) -> None:
        """Expose persisted valve links before their next control report."""
        if self._store is None:
            return
        for registration in self._store.valve_registry():
            device_id = str(registration["device_id"])
            self._devices.setdefault(
                device_id,
                {
                    "device_id": device_id,
                    "name": registration["name"],
                    "model": registration["model"],
                    "available": False,
                    "last_event_id": 0,
                    "observed_at": None,
                    "state": {
                        "model": registration["model"],
                        "rf_endpoint_a": registration["controller_endpoint"],
                        "rf_endpoint_b": registration["valve_endpoint"],
                        "device_kind": "irrigation_valve",
                        "rf_protocol_family": "rainpoint_htv",
                    },
                    "area": registration.get("area"),
                },
            )

    @staticmethod
    def _add_reporting_status(
        device: dict[str, Any], now: datetime | None
    ) -> None:
        """Attach current receive status without changing device availability."""
        threshold = REPORTING_TIMEOUTS.get(
            device.get("model"),
            PROTOCOL_REPORTING_TIMEOUTS.get(
                device.get("state", {}).get("rf_protocol_family"),
                DEFAULT_REPORTING_TIMEOUT,
            ),
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
        if not is_hcs02x_sensor(
            model=event.get("model"),
            protocol=event.get("state", {}).get("rf_protocol_family"),
        ):
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
