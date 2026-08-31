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
from .htv145_acceptance import Htv145DryValveAcceptance
from .htv145_control import Htv145ControlCoordinator, Htv145ControlProfile
from .htv405_control import (
    HTV405_CONTROL_BASE_CENTER_HZ,
    HTV405_RESPONSE_WINDOW_SECONDS,
    Htv405ControlCoordinator,
    Htv405ControlProfile,
)
from .pairing import HCS026EnrollmentManager, factory_endpoint, paired_endpoint
from .pairing_protocol import (
    AUTOMATIC_HCS026_PROFILE_ID,
    automatic_hcs026_profile_metadata,
    pairing_profile,
)
from .valve_pairing_protocol import (
    AUTOMATIC_HTV145_PROFILE_ID,
    AUTOMATIC_HTV405_PROFILE_ID,
    CALIBRATED_FREQUENCY_OFFSET_HZ as HTV405_FREQUENCY_OFFSET_HZ,
    automatic_htv145_profile_metadata,
    automatic_htv405_profile_metadata,
    build_htv145_profile,
    build_htv405_profile,
)
from .valve_protocol import (
    decode_htv405_gateway_command_rejection,
    decode_htv405_gateway_command_response,
    htv405_command_response_endpoint,
    htv405_phase_state,
    is_htv405_link_frame,
)
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
from .rf import normalize_row
from .rf_identity import (
    LEGACY_STOCK_COMPANION_ENDPOINT,
    LEGACY_STOCK_CONTROLLER_ENDPOINT,
    LocalRFControllerIdentity,
    generate_local_rf_identity,
    load_or_create_local_rf_identity,
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
HTV405_PENDING_GATEWAY_TIMEOUT_SECONDS = (
    HTV405_RESPONSE_WINDOW_SECONDS + 5.0
)
HTV405_FRESH_PAIRING_COUNTER_WINDOW_SECONDS = 15 * 60
HTV405_GUARDED_COUNTER_PROBE_SECONDS = 15
_UNSET = object()


def _observed_utc(value: str | datetime) -> datetime:
    """Interpret legacy naive rtl_433 values as gateway-local time."""
    observed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(value.replace("Z", "+00:00"))
    )
    if observed.tzinfo is None:
        observed = observed.astimezone()
    return observed.astimezone(timezone.utc)


def _merge_htv405_zone_state(
    current: dict[str, Any],
    previous: dict[str, Any],
) -> dict[str, Any]:
    """Merge a receiver-partial HTV405 projection into canonical state."""
    merged = copy.deepcopy(current)
    for zone in range(1, 5):
        watering_key = f"zone_{zone}_is_watering"
        if not isinstance(merged.get(watering_key), bool) and isinstance(
            previous.get(watering_key), bool
        ):
            merged[watering_key] = previous[watering_key]
            for suffix in ("remaining_seconds", "duration_seconds"):
                detail_key = f"zone_{zone}_{suffix}"
                if merged.get(detail_key) is None and detail_key in previous:
                    merged[detail_key] = copy.deepcopy(previous[detail_key])

    zone_states = {
        zone: merged.get(f"zone_{zone}_is_watering")
        for zone in range(1, 5)
    }
    active_zone = next(
        (
            zone
            for zone, watering in zone_states.items()
            if watering is True
        ),
        None,
    )
    if active_zone is not None:
        merged.update(
            {
                "active_zone": active_zone,
                "is_watering": True,
                "valve_state": "watering",
            }
        )
    elif all(
        isinstance(watering, bool) for watering in zone_states.values()
    ):
        merged.update(
            {
                "active_zone": None,
                "is_watering": False,
                "valve_state": "idle",
            }
        )
    return merged


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
        valve_control_enabled: bool = False,
        htv145_acceptance_enabled: bool = False,
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
        self._valve_control_enabled = valve_control_enabled
        self._htv145_acceptance_enabled = htv145_acceptance_enabled
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
        self.rf_identity: LocalRFControllerIdentity = (
            load_or_create_local_rf_identity(self._store)
            if self._store is not None
            else generate_local_rf_identity()
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
        self._htv145_acceptance: Htv145DryValveAcceptance | None = None
        self._active_pairing_node_id: str | None = None
        self._active_pairing_command_id: str | None = None
        self._active_pairing_profile_id: str | None = None
        self._active_pairing_ack_parameters: dict[str, Any] | None = None
        self._active_pairing_rf_identity: dict[str, str] | None = None
        self._active_pairing_control_profile: dict[str, Any] | None = None
        self._active_pairing_expected_valve_endpoint: str | None = None
        self._active_pairing_confirmed_valve_endpoint: str | None = None
        self._active_pairing_confirmation_observed_at: str | None = None
        self._active_pairing_confirmation_receiver: str | None = None
        self._active_pairing_confirmed_sensor_endpoint: str | None = None
        self._active_pairing_sensor_confirmation_observed_at: str | None = None
        self._active_pairing_sensor_confirmation_receiver: str | None = None
        self._active_pairing_sensor_identity_mismatch_at: str | None = None
        self._pending_node_adoptions: dict[str, dict[str, Any]] = {}
        self._automatic_rejoin_started: dict[str, float] = {}
        self._recover_pending_htv405_air_responses()
        self._reconcile_htv405_control_state_from_events()

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
                "rf_controller_identity": {
                    **self.rf_identity.as_dict(),
                    "persistent": self._store is not None,
                },
                "transport": self.transport,
                "read_only": self.read_only,
                "valve_control_enabled": self._valve_control_enabled,
                "htv145_acceptance_enabled": self._htv145_acceptance_enabled,
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
                    "unique_rf_controller_identity",
                    *(
                        ["htv405_supervised_control"]
                        if self._valve_control_enabled
                        else []
                    ),
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
            normalized = copy.deepcopy(fields)
            if "pairing_state" in normalized:
                self._normalize_node_pairing_status_locked(node, normalized)
            node.update(normalized)
            self._adopt_active_valve_identity_from_node_locked(node_id, node)

    @staticmethod
    def _normalize_node_pairing_status_locked(
        node: dict[str, Any], fields: dict[str, Any]
    ) -> None:
        """Separate the raw node transcript from the gateway pairing outcome.

        An HTV405 can enter ordinary paired operation before emitting the two
        optional final rows retained from the stock transcript. Only the
        gateway can validate that ordinary traffic addresses the active custom
        controller. Preserve the node's literal tail result for diagnostics,
        but do not let a later tail timeout overturn that stronger evidence.
        """
        raw_state = fields.get("pairing_state")
        raw_reason = fields.get("pairing_failure_reason")
        raw_detail = fields.get("pairing_detail")
        command_id = fields.get("pairing_command_id")
        fields["pairing_node_state"] = raw_state
        fields["pairing_node_failure_reason"] = raw_reason
        fields["pairing_node_detail"] = raw_detail

        accepted_command = node.get("pairing_terminal_accepted_command_id")
        if (
            isinstance(command_id, str)
            and command_id
            and isinstance(accepted_command, str)
            and command_id == accepted_command
        ):
            fields["pairing_outcome"] = "completed"
            fields["pairing_completion_source"] = "gateway_terminal_evidence"
            if raw_state == "armed":
                fields["pairing_tail_state"] = "active"
            elif raw_state == "completed":
                fields["pairing_tail_state"] = "completed"
            elif raw_state == "failed" and raw_reason == "session_timeout":
                fields["pairing_tail_state"] = "optional_tail_timeout"
                fields["pairing_state"] = "completed"
                fields["pairing_failure_reason"] = "none"
                fields["pairing_detail"] = (
                    "gateway_terminal_evidence_accepted_optional_tail_expired"
                )
            else:
                fields["pairing_tail_state"] = "failed_after_terminal_evidence"
            return

        # A new command starts a distinct outcome. Do not let terminal evidence
        # from a previous enrollment normalize a later physical attempt.
        if isinstance(command_id, str) and command_id and raw_state == "armed":
            for key in (
                "pairing_terminal_accepted_command_id",
                "pairing_terminal_accepted_at",
                "pairing_terminal_accepted_endpoint",
            ):
                node.pop(key, None)
            fields["pairing_outcome"] = "pending"
            fields["pairing_completion_source"] = None
            fields["pairing_tail_state"] = "active"
        elif raw_state == "completed":
            fields["pairing_outcome"] = "completed"
            fields["pairing_completion_source"] = "node_transcript"
            fields["pairing_tail_state"] = "completed"
        elif raw_state == "failed":
            fields["pairing_outcome"] = "failed"
            fields["pairing_completion_source"] = None
            fields["pairing_tail_state"] = "failed"

    def _adopt_active_valve_identity_from_node_locked(
        self, node_id: str, node: dict[str, Any]
    ) -> None:
        """Accept an automatically discovered HTV405 factory identity."""
        if (
            self._active_pairing_profile_id != AUTOMATIC_HTV405_PROFILE_ID
            or self._active_pairing_node_id != node_id
            or self._active_pairing_command_id is None
            or self._active_pairing_expected_valve_endpoint is not None
            or node.get("pairing_command_id")
            != self._active_pairing_command_id
        ):
            return
        factory = node.get("pairing_factory_endpoint")
        paired = node.get("pairing_paired_endpoint")
        identity = self._active_pairing_rf_identity or {}
        if not isinstance(factory, str) or not isinstance(paired, str):
            return
        try:
            profile = build_htv405_profile(
                factory_endpoint=factory.strip().lower(),
                valve_route=str(identity.get("controller_endpoint", "")),
                companion_endpoint=str(identity.get("companion_endpoint", "")),
            )
        except ValueError:
            return
        if profile.paired_endpoint != paired.strip().lower():
            return
        self._active_pairing_expected_valve_endpoint = profile.paired_endpoint
        self._active_pairing_control_profile = {
            "companion_endpoint": profile.companion_endpoint,
            "selector": 0x05,
            "frequency_offset_hz": HTV405_FREQUENCY_OFFSET_HZ,
        }

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

    def prepare_htv145_acceptance(
        self,
        *,
        node_id: str,
        controller_endpoint: str,
        valve_endpoint: str,
        center_hz: int,
        power_dbm: int,
        invert: bool,
        trailer_residual: int,
        idle_frame: str,
        passive_command_frame: str,
        idle_observed_at: str,
        passive_command_observed_at: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Prepare one isolated HTV145 dry-valve trial without actuating."""
        timestamp = (now or datetime.now(timezone.utc)).isoformat()
        profile = Htv145ControlProfile(
            node_id=node_id.strip().lower(),
            controller_endpoint=controller_endpoint.strip().lower(),
            valve_endpoint=valve_endpoint.strip().lower(),
            center_hz=center_hz,
            power_dbm=power_dbm,
            invert=invert,
            trailer_residual=trailer_residual,
        )
        try:
            idle = bytes.fromhex(idle_frame)
            passive = bytes.fromhex(passive_command_frame)
            idle_evidence_time = _observed_utc(idle_observed_at)
            passive_evidence_time = _observed_utc(
                passive_command_observed_at
            )
        except ValueError as error:
            raise ValueError("invalid HTV145 evidence frame or timestamp") from error
        with self._lock:
            if not self._htv145_acceptance_enabled:
                raise PermissionError("HTV145 dry-valve acceptance is disabled")
            if self._store is None or self._node_command_sender is None:
                raise RuntimeError("HTV145 acceptance transport is unavailable")
            node = self._nodes.get(profile.node_id, {})
            if not self._htv145_control_node_ready(node):
                raise RuntimeError("selected HTV145 radio node is unavailable")
            prior_states = self._store.htv145_control_states(
                profile.valve_endpoint
            )
            if prior_states:
                last_started = prior_states[0].get("last_command_started_at")
                if isinstance(last_started, str) and (
                    passive_evidence_time <= _observed_utc(last_started)
                ):
                    raise RuntimeError(
                        "passive HTV145 command evidence does not postdate "
                        "the previous local attempt"
                    )
            coordinator = Htv145ControlCoordinator(
                store=self._store,
                sender=self._node_command_sender,
                enabled=True,
            )
            harness = Htv145DryValveAcceptance(
                coordinator=coordinator,
                profile=profile,
                enabled=True,
            )
            commands = harness.prepare(
                idle_frame=idle,
                passive_command_frame=passive,
                observed_at=timestamp,
                idle_observed_at=idle_evidence_time.isoformat(),
                passive_command_observed_at=(
                    passive_evidence_time.isoformat()
                ),
            )
            self._htv145_acceptance = harness
            return {
                "state": "prepared_no_actuation",
                "selected_node_id": profile.node_id,
                "node_command_types": [item["type"] for item in commands],
                "acceptance": harness.report(finished_at=timestamp),
            }

    def start_htv145_acceptance_open(
        self,
        *,
        duration_seconds: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Dispatch the harness's one permitted duration-bounded open."""
        timestamp = (now or datetime.now(timezone.utc)).isoformat()
        with self._lock:
            harness = self._htv145_acceptance
            if not self._htv145_acceptance_enabled or harness is None:
                raise PermissionError("HTV145 dry-valve acceptance is not prepared")
            node = self._nodes.get(harness.profile.node_id, {})
            if not self._htv145_control_node_ready(node):
                raise RuntimeError("selected HTV145 radio node is unavailable")
            command = harness.open_once(
                duration_seconds=duration_seconds,
                started_at=timestamp,
            )
            return {
                "state": "pending_valve_evidence",
                "command": command,
                "acceptance": harness.report(finished_at=timestamp),
            }

    def htv145_acceptance_status(
        self, *, now: datetime | None = None
    ) -> dict[str, Any]:
        """Return the current private acceptance transcript and verdict."""
        timestamp = (now or datetime.now(timezone.utc)).isoformat()
        with self._lock:
            harness = self._htv145_acceptance
            if harness is None:
                return {
                    "enabled": self._htv145_acceptance_enabled,
                    "prepared": False,
                    "passed": False,
                }
            report = harness.report(finished_at=timestamp)
            report["enabled"] = self._htv145_acceptance_enabled
            report["prepared"] = True
            if self._store is not None:
                states = self._store.htv145_control_states(
                    harness.profile.valve_endpoint
                )
                report["coordinator"] = states[0] if states else None
            return report

    def observe_htv145_acceptance_candidate(
        self, node_id: str, message: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Feed selected-node response diagnostics into the active trial."""
        timestamp = datetime.now(timezone.utc).isoformat()
        with self._lock:
            harness = self._htv145_acceptance
            if harness is None or harness.profile.node_id != node_id:
                return None
            return harness.observe_candidate_status(
                message, observed_at=timestamp
            )

    @staticmethod
    def _htv145_control_node_ready(node: dict[str, Any]) -> bool:
        return bool(
            node.get("connected") is True
            and node.get("authenticated") is True
            and node.get("tx_armed") is not True
            and "htv145_control_tx_candidate" in node.get("capabilities", [])
        )

    def _observe_htv145_acceptance_frame_locked(
        self, *, frame: str, model: str, observed_at: str
    ) -> None:
        harness = self._htv145_acceptance
        if harness is None or model != HTV145_MODEL:
            return
        try:
            raw = bytes.fromhex(frame)
            harness.observe_frame(raw, observed_at=observed_at)
        except (KeyError, RuntimeError, ValueError):
            return

    def request_htv405_control(
        self,
        *,
        device_id: str,
        action: str,
        zone: int,
        duration_seconds: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Dispatch one supervised, duration-bounded HTV405 command."""
        timestamp = (now or datetime.now(timezone.utc)).isoformat()
        with self._lock:
            if not self._valve_control_enabled:
                raise PermissionError("HTV405 supervised control is disabled")
            if self._store is None or self._node_command_sender is None:
                raise RuntimeError("HTV405 control transport is unavailable")
            registration = next(
                (
                    item
                    for item in self._store.valve_registry()
                    if item["device_id"] == device_id
                ),
                None,
            )
            if registration is None or registration.get("model") != "HTV405FRF":
                raise KeyError(device_id)
            profile = self._htv405_control_profile(registration)
            node = self._nodes.get(profile.node_id, {})
            if not self._htv405_control_node_ready(node):
                raise RuntimeError("selected HTV405 radio node is unavailable")
            if (
                action == "open"
                and registration.get("control_next_sequence") is None
            ):
                recovered = self._store.recover_htv405_timeout_counter(
                    valve_endpoint=profile.valve_endpoint,
                    node_id=profile.node_id,
                    observed_at=timestamp,
                )
                if recovered is not None:
                    registration = recovered
            coordinator = Htv405ControlCoordinator(
                store=self._store,
                sender=self._node_command_sender,
                enabled=True,
            )
            if action == "open":
                if duration_seconds is None:
                    raise ValueError("HTV405 open requires a bounded duration")
                result = coordinator.request_open(
                    profile,
                    zone=zone,
                    duration_seconds=duration_seconds,
                    started_at=timestamp,
                )
            elif action == "close":
                result = coordinator.request_close(
                    profile,
                    zone=zone,
                    started_at=timestamp,
                )
            else:
                raise ValueError("HTV405 action must be open or close")
            self._refresh_registry_catalog()
            return result

    def request_htv405_idle_close_probe(
        self,
        *,
        device_id: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Dispatch one supervised close-only counter probe on Zone 1."""
        timestamp = (now or datetime.now(timezone.utc)).isoformat()
        with self._lock:
            if not self._valve_control_enabled:
                raise PermissionError("HTV405 supervised control is disabled")
            if self._store is None or self._node_command_sender is None:
                raise RuntimeError("HTV405 control transport is unavailable")
            registration = next(
                (
                    item
                    for item in self._store.valve_registry()
                    if item["device_id"] == device_id
                ),
                None,
            )
            if registration is None or registration.get("model") != "HTV405FRF":
                raise KeyError(device_id)
            profile = self._htv405_control_profile(registration)
            node = self._nodes.get(profile.node_id, {})
            if not self._htv405_control_node_ready(node):
                raise RuntimeError("selected HTV405 radio node is unavailable")
            if registration.get("control_confirmed_watering") not in {0, False}:
                raise RuntimeError("HTV405 valve is not confirmed idle")
            coordinator = Htv405ControlCoordinator(
                store=self._store,
                sender=self._node_command_sender,
                enabled=True,
            )
            result = coordinator.request_idle_close_probe(
                profile,
                zone=1,
                started_at=timestamp,
            )
            self._refresh_registry_catalog()
            return result

    def request_htv405_guarded_open_probe(
        self,
        *,
        device_id: str,
        candidate_sequence: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Dispatch one provisional 60-second Zone 1 synchronization open."""
        timestamp = (now or datetime.now(timezone.utc)).isoformat()
        with self._lock:
            if not self._valve_control_enabled:
                raise PermissionError("HTV405 supervised control is disabled")
            if self._store is None or self._node_command_sender is None:
                raise RuntimeError("HTV405 control transport is unavailable")
            registration = next(
                (
                    item
                    for item in self._store.valve_registry()
                    if item["device_id"] == device_id
                ),
                None,
            )
            if registration is None or registration.get("model") != "HTV405FRF":
                raise KeyError(device_id)
            profile = self._htv405_control_profile(registration)
            node = self._nodes.get(profile.node_id, {})
            if not self._htv405_control_node_ready(node):
                raise RuntimeError("selected HTV405 radio node is unavailable")
            device = self._devices.get(device_id, {})
            state = device.get("state", {})
            if (
                device.get("available") is not True
                or state.get("is_watering") is not False
                or registration.get("control_confirmed_watering") not in {0, False}
            ):
                raise RuntimeError("HTV405 valve is not confirmed idle")
            coordinator = Htv405ControlCoordinator(
                store=self._store,
                sender=self._node_command_sender,
                enabled=True,
            )
            result = coordinator.request_guarded_open_probe(
                profile,
                started_at=timestamp,
                candidate_sequence=candidate_sequence,
            )
            self._refresh_registry_catalog()
            return result

    def synchronize_htv405_control_counter(
        self,
        *,
        device_id: str,
        next_sequence: int,
        evidence_source: str,
        guard_duration_seconds: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Restore a supervised counter from explicit association evidence."""
        current = now or datetime.now(timezone.utc)
        timestamp = current.isoformat()
        with self._lock:
            if not self._valve_control_enabled:
                raise PermissionError("HTV405 supervised control is disabled")
            if self._store is None:
                raise RuntimeError("HTV405 control storage is unavailable")
            registration = next(
                (
                    item
                    for item in self._store.valve_registry()
                    if item["device_id"] == device_id
                ),
                None,
            )
            if registration is None:
                raise KeyError(device_id)
            profile = self._htv405_control_profile(registration)
            device = self._devices.get(device_id, {})
            device_state = device.get("state", {})
            if evidence_source == "fresh_generated_identity_pairing":
                if next_sequence != 1:
                    raise ValueError(
                        "fresh HTV405 pairing initializes command sequence 1"
                    )
                try:
                    paired_at = _observed_utc(str(registration["updated_at"]))
                    current = _observed_utc(current)
                    pairing_age = (current - paired_at).total_seconds()
                except (KeyError, TypeError, ValueError):
                    pairing_age = float("inf")
                if (
                    registration.get("controller_endpoint")
                    != self.rf_identity.controller_endpoint
                    or registration.get("control_last_result")
                    not in {
                        "association_updated_counter_required",
                        "idle_confirmed_counter_unsynchronized",
                    }
                    or not 0
                    <= pairing_age
                    <= HTV405_FRESH_PAIRING_COUNTER_WINDOW_SECONDS
                    or device.get("available") is not True
                    or device_state.get("is_watering") is not False
                ):
                    raise RuntimeError(
                        "HTV405 generated-identity pairing is not fresh and idle"
                    )
            elif evidence_source == "operator_guarded_counter_probe":
                if (
                    guard_duration_seconds is None
                    or isinstance(guard_duration_seconds, bool)
                    or guard_duration_seconds not in range(60, 3_601)
                    or guard_duration_seconds % 60
                ):
                    raise ValueError(
                        "guarded HTV405 counter probe requires the previous "
                        "60-3600 second whole-minute duration"
                    )
                last_failure = next(
                    (
                        event
                        for event in reversed(self._events)
                        if event.get("event_type") == "valve_control_failed"
                        and event.get("device_id") == device_id
                        and event.get("state", {}).get("result")
                        == (
                            "gateway_command_response_timeout_"
                            "counter_unsynchronized"
                        )
                    ),
                    None,
                )
                try:
                    failed_at = _observed_utc(
                        str(last_failure["observed_at"])
                    )
                    current = _observed_utc(current)
                except (KeyError, TypeError, ValueError):
                    failed_at = current
                safe_at = failed_at + timedelta(
                    seconds=(
                        guard_duration_seconds
                        + HTV405_GUARDED_COUNTER_PROBE_SECONDS
                    )
                )
                if (
                    registration.get("control_last_result")
                    not in {
                        "gateway_command_response_timeout_"
                        "counter_unsynchronized",
                        "idle_confirmed_counter_unsynchronized",
                    }
                    or registration.get("control_pending_command_id")
                    is not None
                    or registration.get("control_next_sequence") is not None
                    or registration.get("control_confirmed_watering")
                    not in {0, False}
                    or device.get("available") is not True
                    or device_state.get("is_watering") is not False
                    or current < safe_at
                ):
                    raise RuntimeError(
                        "HTV405 counter probe is not past its complete "
                        "possible-run guard"
                    )
            else:
                if guard_duration_seconds is not None:
                    raise ValueError(
                        "guard duration is only valid for a guarded counter probe"
                    )
                reported_at = registration.get("control_confirmed_at")
                try:
                    reported = _observed_utc(str(reported_at))
                    current = _observed_utc(current)
                    report_age = (current - reported).total_seconds()
                except (TypeError, ValueError):
                    report_age = float("inf")
                if (
                    device.get("available") is not True
                    or registration.get("control_confirmed_watering") not in {
                        0,
                        False,
                    }
                    or not 0 <= report_age <= 60
                ):
                    raise RuntimeError(
                        "HTV405 valve is not freshly confirmed idle"
                    )
            result = self._store.synchronize_htv405_control_counter(
                valve_endpoint=profile.valve_endpoint,
                node_id=profile.node_id,
                next_sequence=next_sequence,
                source=evidence_source,
                observed_at=timestamp,
            )
            self._refresh_registry_catalog()
            return result

    def cancel_htv405_control_recovery(
        self,
        *,
        device_id: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Cancel one provisional recovery candidate without transmitting."""
        timestamp = (now or datetime.now(timezone.utc)).isoformat()
        with self._lock:
            if self._store is None:
                raise RuntimeError("HTV405 control storage is unavailable")
            registration = next(
                (
                    item
                    for item in self._store.valve_registry()
                    if item["device_id"] == device_id
                ),
                None,
            )
            if registration is None or registration.get("model") != "HTV405FRF":
                raise KeyError(device_id)
            result = self._store.cancel_htv405_control_recovery(
                valve_endpoint=str(registration["valve_endpoint"]),
                node_id=str(registration["control_node_id"]),
                observed_at=timestamp,
            )
            self._refresh_registry_catalog()
            return result

    def assign_htv405_control_node(
        self,
        *,
        device_id: str,
        node_id: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Select one capable RF egress node without changing association IDs."""
        timestamp = (now or datetime.now(timezone.utc)).isoformat()
        with self._lock:
            if not self._valve_control_enabled:
                raise PermissionError("HTV405 supervised control is disabled")
            if self._store is None:
                raise RuntimeError("HTV405 control storage is unavailable")
            registration = next(
                (
                    item
                    for item in self._store.valve_registry()
                    if item["device_id"] == device_id
                ),
                None,
            )
            if registration is None or registration.get("model") != "HTV405FRF":
                raise KeyError(device_id)
            node = self._nodes.get(node_id, {})
            if not self._htv405_control_node_ready(node):
                raise RuntimeError("selected HTV405 radio node is unavailable")
            if registration.get("control_confirmed_watering") in {1, True}:
                raise RuntimeError("HTV405 valve is not confirmed idle")
            if registration.get("control_node_id") != node_id:
                self._revoke_htv405_ack_locked(registration)
            result = self._store.assign_htv405_control_node(
                valve_endpoint=str(registration["valve_endpoint"]),
                node_id=node_id,
                observed_at=timestamp,
            )
            try:
                self._configure_htv405_ack_locked(result)
            except (ConnectionError, KeyError, RuntimeError, ValueError):
                pass
            self._refresh_registry_catalog()
            return result

    @staticmethod
    def _htv405_control_profile(
        registration: dict[str, Any],
    ) -> Htv405ControlProfile:
        """Build a strict control profile from one durable association."""
        values = (
            registration.get("control_node_id"),
            registration.get("controller_endpoint"),
            registration.get("valve_endpoint"),
            registration.get("control_companion_endpoint"),
            registration.get("control_selector"),
            registration.get("control_frequency_offset_hz"),
        )
        if any(value is None for value in values):
            raise RuntimeError("HTV405 control association is incomplete")
        return Htv405ControlProfile(
            node_id=str(values[0]),
            controller_endpoint=str(values[1]),
            valve_endpoint=str(values[2]),
            companion_endpoint=str(values[3]),
            selector=int(values[4]),
            frequency_offset_hz=int(values[5]),
        )

    @staticmethod
    def _htv405_control_node_ready(node: dict[str, Any]) -> bool:
        """Require an idle authenticated candidate node before any RF TX."""
        return bool(
            node.get("connected") is True
            and node.get("authenticated") is True
            and node.get("tx_armed") is not True
            and "valve_control_tx_candidate" in node.get("capabilities", [])
        )

    @staticmethod
    def _node_supports_rf_controller_identity(
        node: dict[str, Any],
        controller_endpoint: str,
        companion_endpoint: str,
    ) -> bool:
        """Allow legacy associations on old firmware, but never new identities."""
        if (
            controller_endpoint == LEGACY_STOCK_CONTROLLER_ENDPOINT
            and companion_endpoint == LEGACY_STOCK_COMPANION_ENDPOINT
        ):
            return True
        return "configurable_rf_controller_identity" in node.get(
            "capabilities", []
        )

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
        unsupported = 0
        for assignment in assignments:
            if not self._node_supports_rf_controller_identity(
                node,
                str(assignment["controller_endpoint"]),
                str(assignment["companion_endpoint"]),
            ):
                unsupported += 1
                continue
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
            routine_ack_restore_unsupported_identity=unsupported,
        )
        return restored

    def restore_radio_node_htv405_ack_assignments(self, node_id: str) -> int:
        """Restore one-owner HTV405 liveness replies after reconnect/OTA."""
        with self._lock:
            if self._store is None or self._node_command_sender is None:
                return 0
            node = self._nodes.get(node_id, {})
            if (
                node.get("tx_armed") is True
                or "htv405_routine_ack_tx"
                not in node.get("capabilities", [])
            ):
                return 0
            registrations = [
                item
                for item in self._store.valve_registry()
                if item.get("model") == "HTV405FRF"
                and item.get("control_node_id") == node_id
                and item.get("control_companion_endpoint") is not None
                and item.get("control_frequency_offset_hz") is not None
            ]
            sender = self._node_command_sender
        restored = 0
        for registration in registrations:
            command = self._htv405_ack_configuration_command(registration)
            # Publish the correlation identifier before the command can elicit
            # a synchronous error from the node. Otherwise the listener may
            # misclassify that error as a pairing failure.
            self.update_node(
                node_id, htv405_routine_ack_command_id=command["command_id"]
            )
            try:
                sender(node_id, command)
            except (ConnectionError, KeyError, RuntimeError, ValueError):
                break
            restored += 1
        self.update_node(
            node_id,
            htv405_routine_ack_assigned_valves=len(registrations),
            htv405_routine_ack_restore_requested=restored,
        )
        return restored

    @staticmethod
    def _htv405_ack_configuration_command(
        registration: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a non-actuating ACK authorization from a durable link."""
        return {
            "type": "htv405_routine_ack_configure",
            "command_id": uuid.uuid4().hex,
            "controller_endpoint": str(registration["controller_endpoint"]),
            "valve_endpoint": str(registration["valve_endpoint"]),
            "companion_endpoint": str(
                registration["control_companion_endpoint"]
            ),
            "frequency_offset_hz": int(
                registration["control_frequency_offset_hz"]
            ),
            "power_dbm": 10,
            "invert": False,
        }

    def _configure_htv405_ack_locked(
        self, registration: dict[str, Any]
    ) -> None:
        node_id = registration.get("control_node_id")
        if not isinstance(node_id, str) or self._node_command_sender is None:
            return
        node = self._nodes.get(node_id, {})
        if (
            node.get("connected") is not True
            or node.get("tx_armed") is True
            or "htv405_routine_ack_tx" not in node.get("capabilities", [])
        ):
            return
        command = self._htv405_ack_configuration_command(registration)
        # Set the identifier before dispatch so a fast command error is still
        # attributed to the ACK configuration rather than the active pairing
        # transaction.
        node["htv405_routine_ack_command_id"] = command["command_id"]
        self._node_command_sender(node_id, command)

    def _revoke_htv405_ack_locked(
        self, registration: dict[str, Any]
    ) -> None:
        node_id = registration.get("control_node_id")
        endpoint = registration.get("valve_endpoint")
        if (
            not isinstance(node_id, str)
            or not isinstance(endpoint, str)
            or self._node_command_sender is None
        ):
            return
        try:
            command = {
                "type": "htv405_routine_ack_revoke",
                "command_id": uuid.uuid4().hex,
                "valve_endpoint": endpoint,
            }
            self._node_command_sender(node_id, command)
            self._nodes.setdefault(node_id, {"node_id": node_id})[
                "htv405_routine_ack_command_id"
            ] = command["command_id"]
        except (ConnectionError, KeyError, RuntimeError, ValueError):
            pass

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
            previous = next(
                (
                    item
                    for item in self._store.ack_assignments()
                    if item["paired_endpoint"] == paired_endpoint
                ),
                None,
            )
            assignment = {
                "paired_endpoint": paired_endpoint,
                "node_id": node_id,
                "assigned_channel": assigned_channel,
                "frequency_offset_hz": frequency_offset_hz,
                "power_dbm": power_dbm,
                "invert": invert,
                # Reassigning an ACK owner must never change the sensor's RF
                # association. Rows created before identity persistence are
                # explicitly backfilled to the retained stock identity.
                "controller_endpoint": (
                    previous.get("controller_endpoint")
                    if previous is not None
                    else LEGACY_STOCK_CONTROLLER_ENDPOINT
                ),
                "companion_endpoint": (
                    previous.get("companion_endpoint")
                    if previous is not None
                    else LEGACY_STOCK_COMPANION_ENDPOINT
                ),
                "updated_at": (now or datetime.now(timezone.utc)).isoformat(),
            }
            node = self._nodes.get(node_id, {})
            if (
                node.get("connected") is True
                and not self._node_supports_rf_controller_identity(
                    node,
                    str(assignment["controller_endpoint"]),
                    str(assignment["companion_endpoint"]),
                )
            ):
                raise ValueError(
                    "selected radio-node firmware cannot own this RF identity"
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
            "controller_endpoint": assignment["controller_endpoint"],
            "companion_endpoint": assignment["companion_endpoint"],
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
            self._confirm_valve_pairing_locked(frame, decoded, timestamp)
            device_state = copy.deepcopy(decoded)
            device_observed_at = timestamp
            if model == "HTV405FRF":
                previous = self._devices.get(device_id, {})
                previous_state = previous.get("state", {})
                if not isinstance(decoded.get("is_watering"), bool) and (
                    isinstance(previous_state.get("is_watering"), bool)
                ):
                    for key, value in previous_state.items():
                        if key in {
                            "is_watering",
                            "active_zone",
                            "valve_state",
                            "duration_seconds",
                            "last_usage_liters",
                        } or re.fullmatch(
                            r"zone_[1-4]_(?:is_watering|remaining_seconds|duration_seconds)",
                            key,
                        ):
                            device_state[key] = copy.deepcopy(value)
                    previous_observed_at = previous.get("observed_at")
                    if isinstance(previous_observed_at, str):
                        device_observed_at = previous_observed_at
                else:
                    # Every receiver owns a transport-local reducer and may
                    # hear only one zone from a multi-frame HTV405 status
                    # burst. An omitted zone is therefore "no update", not a
                    # reason to erase a boolean already established by another
                    # receiver.
                    device_state = _merge_htv405_zone_state(
                        device_state,
                        previous_state,
                    )
            device = {
                "device_id": device_id,
                "name": name,
                "model": model,
                "available": True,
                "last_event_id": event_id,
                "observed_at": device_observed_at,
                "state": device_state,
            }
            if registry_metadata is not None:
                device["area"] = registry_metadata.get("area")
            self._devices[device_id] = device
            if self._store is not None and model == "HTV405FRF":
                self._store.update_device_snapshot_state(
                    event,
                    device_state,
                )
            if (
                self._store is not None
                and model == "HTV405FRF"
                and isinstance(decoded.get("is_watering"), bool)
                and isinstance(decoded.get("rf_endpoint_b"), str)
            ):
                zone = decoded.get("active_zone", decoded.get("zone"))
                if not isinstance(zone, int) or isinstance(zone, bool):
                    zone = None
                self._store.observe_htv405_state_report(
                    valve_endpoint=str(decoded["rf_endpoint_b"]).lower(),
                    watering=bool(decoded["is_watering"]),
                    zone=zone,
                    observed_at=timestamp,
                )
                self._refresh_registry_catalog()
            self._observe_htv145_acceptance_frame_locked(
                frame=frame,
                model=model,
                observed_at=timestamp,
            )
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
            self._confirm_valve_pairing_locked(frame, decoded, timestamp)
            self._observe_htv145_acceptance_frame_locked(
                frame=frame,
                model=str(decoded.get("model", "")),
                observed_at=timestamp,
            )
            self._observe_pairing(decoded, timestamp)
            return copy.deepcopy(event)

    def _confirm_valve_pairing_locked(
        self,
        frame: str,
        state: dict[str, Any],
        observed_at: str,
    ) -> None:
        """Accept strict paired-valve traffic only from this live session."""
        expected = self._active_pairing_expected_valve_endpoint
        node_id = self._active_pairing_node_id
        command_id = self._active_pairing_command_id
        valve_profile_id = self._active_pairing_profile_id
        if (
            valve_profile_id not in {
                AUTOMATIC_HTV145_PROFILE_ID,
                AUTOMATIC_HTV405_PROFILE_ID,
            }
            or expected is None
            or node_id is None
            or command_id is None
        ):
            return
        # A pairing window may observe many routine link reports after the
        # valve has accepted the new controller. Complete the association only
        # once so later reports cannot reset an authenticated command counter.
        if self._active_pairing_confirmed_valve_endpoint == expected:
            return
        node = self._nodes.get(node_id, {})
        if (
            node.get("pairing_command_id") != command_id
            or int(node.get("pairing_completed_steps") or 0) < 1
        ):
            return
        endpoint = state.get("rf_endpoint_b")
        if not isinstance(endpoint, str) or endpoint.lower() != expected:
            return
        controller_endpoint = state.get("rf_endpoint_a")
        expected_route = (self._active_pairing_rf_identity or {}).get(
            "controller_endpoint"
        )
        if (
            not isinstance(controller_endpoint, str)
            or controller_endpoint.strip().lower() != expected_route
        ):
            return
        if valve_profile_id == AUTOMATIC_HTV405_PROFILE_ID:
            try:
                raw = bytes.fromhex(frame)
            except ValueError:
                return
            if not is_htv405_link_frame(raw):
                return
        else:
            if (
                state.get("model") != HTV145_MODEL
                or state.get("rf_trailer_valid") is not True
                or state.get("rf_frame_accepted") is not True
            ):
                return
        profile = self._active_pairing_control_profile
        if self._store is not None and profile is not None:
            controller_endpoint = controller_endpoint.strip().lower()
            model = (
                "HTV405FRF"
                if valve_profile_id == AUTOMATIC_HTV405_PROFILE_ID
                else HTV145_MODEL
            )
            device_id = (
                f"htv405-{expected}"
                if model == "HTV405FRF"
                else f"htv145-{expected}"
            )
            default_name = (
                f"RainPoint 4-zone valve {expected[-4:]}"
                if model == "HTV405FRF"
                else f"RainPoint valve {expected[-4:]}"
            )
            existing = next(
                (
                    item
                    for item in self._store.valve_registry()
                    if item["valve_endpoint"] == expected
                ),
                None,
            )
            same_authenticated_control_route = bool(
                valve_profile_id == AUTOMATIC_HTV405_PROFILE_ID
                and existing is not None
                and existing.get("controller_endpoint")
                == controller_endpoint
                and existing.get("control_node_id") == node_id
                and existing.get("control_companion_endpoint")
                == str(profile["companion_endpoint"])
                and existing.get("control_selector")
                == int(profile["selector"])
                and existing.get("control_frequency_offset_hz")
                == int(profile["frequency_offset_hz"])
                and isinstance(existing.get("control_next_sequence"), int)
                and not isinstance(
                    existing.get("control_next_sequence"), bool
                )
                and existing.get("control_next_sequence") in range(0x20)
                and existing.get("control_pending_command_id") is None
                and existing.get("control_confirmed_watering") in {0, False}
            )
            self._store.accept_paired_valve_link(
                controller_endpoint=controller_endpoint,
                valve_endpoint=expected,
                device_id=(
                    str(existing["device_id"])
                    if existing is not None
                    else device_id
                ),
                name=(
                    str(existing["name"])
                    if existing is not None
                    else default_name
                ),
                model=model,
                area=existing.get("area") if existing is not None else None,
                accepted_at=observed_at,
            )
        if (
            valve_profile_id == AUTOMATIC_HTV405_PROFILE_ID
            and self._store is not None
            and profile is not None
        ):
            if same_authenticated_control_route:
                registration = next(
                    item
                    for item in self._store.valve_registry()
                    if item["valve_endpoint"] == expected
                )
            else:
                try:
                    registration = self._store.update_valve_control_profile(
                        valve_endpoint=expected,
                        node_id=node_id,
                        companion_endpoint=str(profile["companion_endpoint"]),
                        selector=int(profile["selector"]),
                        frequency_offset_hz=int(profile["frequency_offset_hz"]),
                        observed_at=observed_at,
                    )
                except KeyError:
                    # The structural link should have been registered by the
                    # ingestor before this callback. Refuse to create control
                    # state if that receive-side proof is unexpectedly absent.
                    return
                if controller_endpoint == self.rf_identity.controller_endpoint:
                    # A physically validated fresh generated-identity
                    # association initializes the independent watering-command
                    # counter at 1. An exact same-route repair above preserves
                    # the already authenticated counter instead.
                    registration = (
                        self._store.synchronize_htv405_control_counter(
                            valve_endpoint=expected,
                            node_id=node_id,
                            next_sequence=1,
                            source="fresh_generated_identity_pairing",
                            observed_at=observed_at,
                        )
                    )
            try:
                self._configure_htv405_ack_locked(registration)
            except (ConnectionError, KeyError, RuntimeError, ValueError):
                # Persistence is authoritative; reconnect restoration retries
                # this best-effort live configuration.
                pass
            self._refresh_registry_catalog()
            self._ensure_registered_valve_devices()
        elif self._store is not None and profile is not None:
            self._refresh_registry_catalog()
            self._ensure_registered_valve_devices()
        self._active_pairing_confirmed_valve_endpoint = expected
        self._active_pairing_confirmation_observed_at = observed_at
        receiver = state.get("rf_receiver_id")
        self._active_pairing_confirmation_receiver = (
            receiver if isinstance(receiver, str) else None
        )
        # The selected node knows only whether it saw every retained transcript
        # row. The gateway has stronger command-scoped evidence: an ordinary
        # valve frame addressed to this active controller. Record that outcome
        # before HA finalizes the flow so a later optional-tail timeout remains
        # diagnostic detail rather than a false pairing failure.
        node["pairing_terminal_accepted_command_id"] = command_id
        node["pairing_terminal_accepted_at"] = observed_at
        node["pairing_terminal_accepted_endpoint"] = expected
        node["pairing_outcome"] = "completed"
        node["pairing_completion_source"] = "gateway_terminal_evidence"
        node["pairing_tail_state"] = (
            "active" if node.get("tx_armed") is True else "completed"
        )

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
        if (
            node.get("connected") is True
            and node.get("authenticated") is True
            and "sensor_pairing_tx" in node.get("capabilities", [])
            and not self._node_supports_rf_controller_identity(
                node,
                str(assignment["controller_endpoint"]),
                str(assignment["companion_endpoint"]),
            )
        ):
            result["reason"] = "ack_owner_firmware_incompatible"
            return result
        if not (
            node.get("connected") is True
            and node.get("authenticated") is True
            and "sensor_pairing_tx" in node.get("capabilities", [])
            and self._node_supports_rf_controller_identity(
                node,
                str(assignment["controller_endpoint"]),
                str(assignment["companion_endpoint"]),
            )
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
            "controller_endpoint": str(assignment["controller_endpoint"]),
            "companion_endpoint": str(assignment["companion_endpoint"]),
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
            observed = now or datetime.now(timezone.utc)
            self._expire_stale_htv405_commands_locked(observed)
            self._recover_matured_htv405_timeout_counters_locked(observed)
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
            valve_registry = {
                item["device_id"]: item
                for item in (
                    self._store.valve_registry() if self._store else []
                )
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
                if valve_registration := valve_registry.get(device_id):
                    state = device.setdefault("state", {})
                    confirmed_watering = valve_registration.get(
                        "control_confirmed_watering"
                    )
                    confirmed_at = valve_registration.get(
                        "control_confirmed_at"
                    )
                    if (
                        not isinstance(state.get("is_watering"), bool)
                        and confirmed_watering is not None
                    ):
                        watering = bool(confirmed_watering)
                        state.update(
                            {
                                "is_watering": watering,
                                "active_zone": (
                                    valve_registration.get(
                                        "control_active_zone"
                                    )
                                    if watering
                                    else None
                                ),
                                "valve_state": (
                                    "watering" if watering else "idle"
                                ),
                            }
                        )
                        if isinstance(confirmed_at, str):
                            device["observed_at"] = confirmed_at
                    pending_command = valve_registration.get(
                        "control_pending_command_id"
                    )
                    control_node_id = valve_registration.get("control_node_id")
                    control_node = self._nodes.get(str(control_node_id), {})
                    association_complete = all(
                        valve_registration.get(key) is not None
                        for key in (
                            "control_node_id",
                            "control_companion_endpoint",
                            "control_selector",
                            "control_frequency_offset_hz",
                        )
                    )
                    node_ready = self._htv405_control_node_ready(control_node)
                    counter_ready = (
                        valve_registration.get("control_next_sequence")
                        is not None
                    )
                    control_available = bool(
                        self._valve_control_enabled
                        and association_complete
                        and node_ready
                        and counter_ready
                        and pending_command is None
                    )
                    if not self._valve_control_enabled:
                        unavailable_reason = "disabled_by_gateway"
                    elif not association_complete:
                        unavailable_reason = "association_incomplete"
                    elif not node_ready:
                        unavailable_reason = "radio_node_unavailable"
                    elif not counter_ready:
                        recovery_sequence = valve_registration.get(
                            "control_recovery_sequence"
                        )
                        recovery_attempt = int(
                            valve_registration.get(
                                "control_recovery_attempt"
                            )
                            or 0
                        )
                        recovery_result = valve_registration.get(
                            "control_last_result"
                        )
                        if recovery_sequence is None:
                            unavailable_reason = (
                                "control_counter_unsynchronized"
                            )
                        elif (
                            recovery_result
                            == "gateway_command_response_timeout_"
                            "counter_unsynchronized"
                            and recovery_attempt > 1
                            and valve_registration.get(
                                "control_recovery_idle_at"
                            )
                            is None
                        ):
                            unavailable_reason = (
                                "awaiting_fresh_idle_confirmation"
                            )
                        else:
                            unavailable_reason = "counter_retry_interval"
                    elif pending_command is not None:
                        unavailable_reason = "command_pending_response"
                    else:
                        unavailable_reason = None
                    state.update(
                        {
                            "rf_control_enabled": self._valve_control_enabled,
                            "rf_control_available": control_available,
                            "rf_control_unavailable_reason": unavailable_reason,
                            "rf_control_command_pending": (
                                pending_command is not None
                            ),
                            "rf_control_node_id": control_node_id,
                            "rf_control_controller_endpoint": (
                                valve_registration.get("controller_endpoint")
                            ),
                            "rf_control_companion_endpoint": (
                                valve_registration.get(
                                    "control_companion_endpoint"
                                )
                            ),
                            "rf_control_pending_action": valve_registration.get(
                                "control_pending_action"
                            ),
                            "rf_control_pending_sequence": (
                                valve_registration.get(
                                    "control_pending_sequence"
                                )
                            ),
                            "rf_control_pending_zone": valve_registration.get(
                                "control_pending_zone"
                            ),
                            "rf_control_pending_duration_seconds": (
                                valve_registration.get(
                                    "control_pending_duration_seconds"
                                )
                            ),
                            "rf_control_pending_started_at": (
                                valve_registration.get(
                                    "control_pending_started_at"
                                )
                            ),
                            "rf_control_last_result": valve_registration.get(
                                "control_last_result"
                            ),
                            "rf_control_recovery_sequence": (
                                valve_registration.get(
                                    "control_recovery_sequence"
                                )
                            ),
                            "rf_control_recovery_attempt": int(
                                valve_registration.get(
                                    "control_recovery_attempt"
                                )
                                or 0
                            ),
                            "rf_control_recovery_not_before": (
                                valve_registration.get(
                                    "control_recovery_not_before"
                                )
                            ),
                        }
                    )
                    if self._valve_control_enabled:
                        device["capabilities"] = sorted(
                            {
                                *device.get("capabilities", []),
                                "bounded_valve_control",
                                "four_zone_valve",
                            }
                        )
                    if valve_registration.get("last_sequence") is not None:
                        state.update(
                            {
                                "rf_telemetry_sequence": int(
                                    valve_registration["last_sequence"]
                                ),
                                "rf_telemetry_repeat": bool(
                                    valve_registration["last_repeat"]
                                ),
                                "rf_next_telemetry_sequence": int(
                                    valve_registration["next_sequence"]
                                ),
                                "rf_next_telemetry_repeat": bool(
                                    valve_registration["next_repeat"]
                                ),
                                "rf_telemetry_phase_at": (
                                    valve_registration["last_phase_at"]
                                ),
                            }
                        )
                    if (
                        valve_registration.get("control_next_sequence")
                        is not None
                    ):
                        state.update(
                            {
                                "rf_next_control_sequence": int(
                                    valve_registration[
                                        "control_next_sequence"
                                    ]
                                ),
                                "rf_control_confirmed_watering": bool(
                                    valve_registration[
                                        "control_confirmed_watering"
                                    ]
                                ),
                                "rf_control_confirmed_at": (
                                    valve_registration[
                                        "control_confirmed_at"
                                    ]
                                ),
                                "rf_control_counter_authenticated": True,
                            }
                        )
                        if (
                            valve_registration.get("control_last_sequence")
                            is not None
                        ):
                            state["rf_control_confirmed_sequence"] = int(
                                valve_registration["control_last_sequence"]
                            )
                    if (
                        valve_registration.get("control_active_zone")
                        is not None
                        and valve_registration.get("control_run_started_at")
                        is not None
                        and valve_registration.get(
                            "control_run_duration_seconds"
                        )
                        is not None
                        and valve_registration.get(
                            "control_expected_idle_at"
                        )
                        is not None
                    ):
                        expected_idle_at = valve_registration[
                            "control_expected_idle_at"
                        ]
                        state.update(
                            {
                                "rf_control_run_started_at": (
                                    valve_registration[
                                        "control_run_started_at"
                                    ]
                                ),
                                "rf_control_run_duration_seconds": int(
                                    valve_registration[
                                        "control_run_duration_seconds"
                                    ]
                                ),
                                "rf_control_expected_idle_at": (
                                    expected_idle_at
                                ),
                            }
                        )
                        try:
                            completion_expected = datetime.fromisoformat(
                                expected_idle_at
                            )
                            if completion_expected.tzinfo is None:
                                completion_expected = (
                                    completion_expected.replace(
                                        tzinfo=timezone.utc
                                    )
                                )
                            run_is_current = completion_expected > datetime.now(
                                timezone.utc
                            )
                        except (TypeError, ValueError):
                            run_is_current = False
                        if run_is_current:
                            state["rf_control_active_zone"] = int(
                                valve_registration["control_active_zone"]
                            )
                        else:
                            state[
                                "rf_control_run_completion_unconfirmed"
                            ] = True
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
                elif device.get("model") in {HTV145_MODEL, "HTV405FRF"}:
                    device["capabilities"] = sorted(
                        {*device.get("capabilities", []), "forget"}
                    )
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

    def _expire_stale_htv405_commands_locked(
        self, now: str | datetime
    ) -> int:
        """Fail reservations whose node never supplied a usable RF result.

        Radio-node status is the preferred terminal signal.  This daemon-side
        deadline is the durable fallback for a disconnected, outdated, or
        interrupted node so one missing report cannot wedge valve control.
        The exact reservation is failed and the normal bounded counter
        recovery policy remains responsible for any later retry.
        """
        if self._store is None or not self._valve_control_enabled:
            return 0
        observed = _observed_utc(now)
        expired = 0
        for registration in self._store.valve_registry():
            command_id = registration.get("control_pending_command_id")
            node_id = registration.get("control_node_id")
            started_at = registration.get("control_pending_started_at")
            if not all(
                isinstance(value, str)
                for value in (command_id, node_id, started_at)
            ):
                continue
            try:
                started = _observed_utc(str(started_at))
            except (TypeError, ValueError):
                continue
            age_seconds = (observed - started).total_seconds()
            if age_seconds <= HTV405_PENDING_GATEWAY_TIMEOUT_SECONDS:
                continue
            action = registration.get("control_pending_action")
            try:
                failed = self._store.fail_htv405_command(
                    valve_endpoint=str(registration["valve_endpoint"]),
                    node_id=str(node_id),
                    command_id=str(command_id),
                    reason=(
                        "gateway_command_response_timeout_"
                        "counter_unsynchronized"
                    ),
                    observed_at=observed.isoformat(),
                )
            except KeyError:
                continue
            self._append_valve_control_event_locked(
                registration=failed,
                event_type="valve_control_failed",
                observed_at=observed.isoformat(),
                action=str(action) if isinstance(action, str) else None,
            )
            expired += 1
        if expired:
            self._refresh_registry_catalog()
        return expired

    def _recover_matured_htv405_timeout_counters_locked(
        self, now: str | datetime
    ) -> int:
        """Make a bounded timeout candidate usable once its guard matures.

        The recovery candidate was already chosen when the command timed out;
        this step never guesses a new counter.  Promoting it during the normal
        device refresh is important because Home Assistant otherwise keeps
        showing the valve as recovery-blocked indefinitely and no later caller
        can discover that the guard has elapsed without attempting a command.
        """
        if self._store is None or not self._valve_control_enabled:
            return 0
        observed = _observed_utc(now).isoformat()
        recovered = 0
        for registration in self._store.valve_registry():
            node_id = registration.get("control_node_id")
            if not isinstance(node_id, str):
                continue
            result = self._store.recover_htv405_timeout_counter(
                valve_endpoint=str(registration["valve_endpoint"]),
                node_id=node_id,
                observed_at=observed,
            )
            if result is None:
                continue
            self._append_valve_control_event_locked(
                registration=result,
                event_type="valve_control_recovered",
                observed_at=observed,
                action="open",
            )
            recovered += 1
        if recovered:
            self._refresh_registry_catalog()
        return recovered

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
            or valve_endpoint in self._suppressed_endpoints
        ):
            return None
        with self._lock:
            existing = self.catalog.valve_link(
                controller_endpoint, valve_endpoint
            )
            timestamp = observed_at or datetime.now(timezone.utc).isoformat()
            if existing is None:
                self._store.upsert_valve_link(
                    controller_endpoint=controller_endpoint,
                    valve_endpoint=valve_endpoint,
                    device_id=f"htv405-{valve_endpoint}",
                    name=f"RainPoint 4-zone valve {valve_endpoint[-4:]}",
                    model="HTV405FRF",
                    area=None,
                    accepted_at=timestamp,
                )
            phase = htv405_phase_state(raw)
            registration = self._store.update_valve_phase(
                valve_endpoint=valve_endpoint,
                sequence=int(phase["rf_telemetry_sequence"]),
                repeat=bool(phase["rf_telemetry_repeat"]),
                next_sequence=int(phase["rf_next_telemetry_sequence"]),
                next_repeat=bool(phase["rf_next_telemetry_repeat"]),
                observed_at=timestamp,
                frame=frame,
            )
            self._refresh_registry_catalog()
            self._ensure_registered_valve_devices()
            return registration

    def observe_valve_control_air_response(
        self,
        node_id: str,
        frame: str,
        *,
        observed_at: str | None = None,
    ) -> dict[str, Any] | None:
        """Confirm a pending command from an authenticated node's RF frame.

        The network listener supplies ``node_id`` only after authenticating
        the radio node. The gateway independently validates the frame,
        durable association, reserved counter, zone, action, and short
        response window before advancing control state.  The response may be
        received by any authenticated radio node: only the association owner
        transmits, but receiver diversity must not discard valve-owned proof.
        """
        if (
            self._store is None
            or not self._valve_control_enabled
            or not RADIO_NODE_ID.fullmatch(node_id)
        ):
            return None
        try:
            raw = bytes.fromhex(frame)
        except ValueError:
            return None
        response = decode_htv405_gateway_command_response(raw)
        if response is None:
            return None
        timestamp = observed_at or datetime.now(timezone.utc).isoformat()
        valve_endpoint = raw[9:13].hex()
        response_endpoint = raw[5:9].hex()
        with self._lock:
            registration = next(
                (
                    item
                    for item in self._store.valve_registry()
                    if item["valve_endpoint"] == valve_endpoint
                ),
                None,
            )
            if registration is None:
                return None
            sequence = response["rf_control_response_sequence"]
            next_sequence = response["rf_next_control_sequence"]
            zone = response["rf_control_response_zone"]
            watering = response["rf_control_response_watering"]
            action = "open" if watering else "close"
            pending_started_at = registration.get(
                "control_pending_started_at"
            )
            companion_endpoint = registration.get(
                "control_companion_endpoint"
            )
            try:
                expected_response_endpoint = (
                    htv405_command_response_endpoint(
                        str(companion_endpoint)
                    )
                )
            except ValueError:
                return None
            if (
                response_endpoint != expected_response_endpoint
                or not isinstance(
                    registration.get("control_pending_command_id"), str
                )
                or registration.get("control_pending_sequence") != sequence
                or registration.get("control_pending_zone") != zone
                or registration.get("control_pending_action") != action
                or not isinstance(pending_started_at, str)
            ):
                return None
            try:
                started = _observed_utc(pending_started_at)
                observed = _observed_utc(timestamp)
            except (TypeError, ValueError):
                return None
            response_age = (observed - started).total_seconds()
            if not 0 <= response_age <= HTV405_RESPONSE_WINDOW_SECONDS:
                return None
            run_started_at: str | None = None
            run_duration_seconds: int | None = None
            expected_idle_at: str | None = None
            if watering:
                duration = registration.get(
                    "control_pending_duration_seconds"
                )
                if (
                    not isinstance(duration, int)
                    or isinstance(duration, bool)
                    or duration not in range(60, 3_601)
                    or duration % 60
                ):
                    return None
                run_started_at = started.isoformat()
                run_duration_seconds = duration
                expected_idle_at = (
                    started + timedelta(seconds=duration)
                ).isoformat()
            frequency_offset = registration.get(
                "control_frequency_offset_hz"
            )
            if not isinstance(frequency_offset, int) or isinstance(
                frequency_offset, bool
            ):
                return None
            center_hz = HTV405_CONTROL_BASE_CENTER_HZ + frequency_offset
            try:
                accepted = self._store.confirm_valve_control_response(
                    valve_endpoint=valve_endpoint,
                    node_id=str(registration["control_node_id"]),
                    sequence=sequence,
                    next_sequence=next_sequence,
                    zone=zone,
                    watering=watering,
                    center_hz=center_hz,
                    observed_at=observed.isoformat(),
                    frame=frame.lower(),
                    run_started_at=run_started_at,
                    run_duration_seconds=run_duration_seconds,
                    expected_idle_at=expected_idle_at,
                )
            except (KeyError, ValueError):
                return None
            self._refresh_registry_catalog()
            self._append_valve_control_event_locked(
                registration=accepted,
                event_type="valve_control_confirmed",
                observed_at=observed.isoformat(),
                action=action,
            )
            return accepted

    def observe_valve_control_air_rejection(
        self,
        node_id: str,
        frame: str,
        *,
        observed_at: str | None = None,
    ) -> dict[str, Any] | None:
        """Fail a matching command from an authenticated negative reply.

        The strict negative envelope proves the valve received but rejected
        this counter.  It does not reveal whether the counter or payload was
        unacceptable, so the durable recovery policy retries the same
        candidate after the normal command-spacing guard.
        """
        if (
            self._store is None
            or not self._valve_control_enabled
            or not RADIO_NODE_ID.fullmatch(node_id)
        ):
            return None
        try:
            raw = bytes.fromhex(frame)
        except ValueError:
            return None
        rejection = decode_htv405_gateway_command_rejection(raw)
        if rejection is None:
            return None
        timestamp = observed_at or datetime.now(timezone.utc).isoformat()
        valve_endpoint = raw[9:13].hex()
        response_endpoint = raw[5:9].hex()
        with self._lock:
            registration = next(
                (
                    item
                    for item in self._store.valve_registry()
                    if item["valve_endpoint"] == valve_endpoint
                ),
                None,
            )
            if registration is None:
                return None
            pending_started_at = registration.get(
                "control_pending_started_at"
            )
            companion_endpoint = registration.get(
                "control_companion_endpoint"
            )
            try:
                expected_response_endpoint = (
                    htv405_command_response_endpoint(
                        str(companion_endpoint)
                    )
                )
                started = _observed_utc(str(pending_started_at))
                observed = _observed_utc(timestamp)
            except (TypeError, ValueError):
                return None
            sequence = rejection["rf_control_rejected_sequence"]
            command_id = registration.get("control_pending_command_id")
            response_age = (observed - started).total_seconds()
            if (
                response_endpoint != expected_response_endpoint
                or not isinstance(command_id, str)
                or registration.get("control_pending_sequence") != sequence
                or not 0 <= response_age <= HTV405_RESPONSE_WINDOW_SECONDS
            ):
                return None
            try:
                failed = self._store.fail_htv405_command(
                    valve_endpoint=valve_endpoint,
                    node_id=str(registration["control_node_id"]),
                    command_id=command_id,
                    reason="gateway_command_rejected_counter_unsynchronized",
                    observed_at=observed.isoformat(),
                )
            except (KeyError, ValueError):
                return None
            self._refresh_registry_catalog()
            self._append_valve_control_event_locked(
                registration=failed,
                event_type="valve_control_failed",
                observed_at=observed.isoformat(),
                action=registration.get("control_pending_action"),
            )
            return failed

    def _recover_pending_htv405_air_responses(self) -> None:
        """Finish a journaled response interrupted before durable commit."""
        if self._store is None or not self._valve_control_enabled:
            return
        retained_events = list(self._events)
        pending = [
            item
            for item in self._store.valve_registry()
            if isinstance(item.get("control_pending_command_id"), str)
        ]
        for registration in pending:
            node_id = registration.get("control_node_id")
            if not isinstance(node_id, str):
                continue
            for event in retained_events:
                state = event.get("state", {})
                if (
                    event.get("event_type") != "rf_frame"
                    or state.get("rf_receiver_id") != node_id
                    or not isinstance(event.get("raw"), str)
                    or not isinstance(event.get("observed_at"), str)
                ):
                    continue
                accepted = self.observe_valve_control_air_response(
                    node_id,
                    str(event["raw"]),
                    observed_at=str(event["observed_at"]),
                )
                if accepted is None:
                    accepted = self.observe_valve_control_air_rejection(
                        node_id,
                        str(event["raw"]),
                        observed_at=str(event["observed_at"]),
                    )
                if accepted is not None:
                    break

    def _reconcile_htv405_control_state_from_events(self) -> None:
        """Apply the latest definitive valve state after a confirmation.

        Some valid HTV405 heartbeats report no definitive watering boolean.
        They may be the newest device snapshot, so startup deliberately scans
        the retained decoded journal for the newest boolean state instead.
        """
        if self._store is None or not self._valve_control_enabled:
            return
        retained_events = list(self._events)
        for registration in self._store.valve_registry():
            confirmed_at = registration.get("control_confirmed_at")
            if not isinstance(confirmed_at, str):
                continue
            device_id = str(registration["device_id"])
            definitive_state_event = next(
                (
                    event
                    for event in reversed(retained_events)
                    if event.get("event_type") == "device_observation"
                    and event.get("device_id") == device_id
                    and isinstance(
                        event.get("state", {}).get("is_watering"), bool
                    )
                    and isinstance(event.get("observed_at"), str)
                ),
                None,
            )
            if definitive_state_event is None:
                continue
            watering = bool(
                definitive_state_event["state"]["is_watering"]
            )
            state_observed_at = str(definitive_state_event["observed_at"])
            try:
                state_time = _observed_utc(state_observed_at)
                response_time = _observed_utc(confirmed_at)
            except (TypeError, ValueError):
                continue
            if state_time < response_time:
                continue
            zone = definitive_state_event["state"].get("active_zone")
            if not isinstance(zone, int) or isinstance(zone, bool):
                zone = None
            with self._lock:
                self._store.observe_htv405_state_report(
                    valve_endpoint=str(registration["valve_endpoint"]),
                    watering=watering,
                    zone=zone,
                    observed_at=state_time.isoformat(),
                )
                device = self._devices.get(device_id)
                if device is not None:
                    device_state = device.setdefault("state", {})
                    device_state.update(
                        {
                            "is_watering": watering,
                            "active_zone": zone,
                            "valve_state": (
                                "watering" if watering else "idle"
                            ),
                        }
                    )
                    device["observed_at"] = state_time.isoformat()
                self._refresh_registry_catalog()

    def observe_valve_control_probe(
        self,
        node_id: str,
        report: dict[str, Any],
        *,
        observed_at: str | None = None,
    ) -> dict[str, Any] | None:
        """Persist only a node-verified HTV405 command response.

        The research firmware emits this status only after matching an
        over-air response to its pending transmitted counter.  The daemon
        independently re-decodes the response and checks the persisted local
        association before accepting the next controller counter.
        """
        status = report.get("state")
        failure_states = {
            "gateway_command_rejected",
            "gateway_command_response_timeout",
            "gateway_command_response_sequence_mismatch",
            "gateway_command_response_zone_mismatch",
        }
        if self._store is None:
            return None
        if status in failure_states:
            valve_endpoint = report.get("valve_endpoint")
            transmitted_sequence = report.get("transmitted_sequence")
            transmitted_zone = report.get("transmitted_zone")
            if (
                not isinstance(valve_endpoint, str)
                or not isinstance(transmitted_sequence, int)
                or isinstance(transmitted_sequence, bool)
                or not isinstance(transmitted_zone, int)
                or isinstance(transmitted_zone, bool)
            ):
                return None
            timestamp = observed_at or datetime.now(timezone.utc).isoformat()
            with self._lock:
                registration = next(
                    (
                        item
                        for item in self._store.valve_registry()
                        if item["valve_endpoint"] == valve_endpoint.lower()
                    ),
                    None,
                )
                if (
                    registration is None
                    or registration.get("control_node_id") != node_id
                    or registration.get("control_pending_sequence")
                    != transmitted_sequence
                    or registration.get("control_pending_zone")
                    != transmitted_zone
                    or not isinstance(
                        registration.get("control_pending_command_id"), str
                    )
                    or (
                        report.get("command_id") is not None
                        and report.get("command_id")
                        != registration.get("control_pending_command_id")
                    )
                ):
                    return None
                failed = self._store.fail_htv405_command(
                    valve_endpoint=valve_endpoint.lower(),
                    node_id=node_id,
                    command_id=str(
                        registration["control_pending_command_id"]
                    ),
                    reason=f"{status}_counter_unsynchronized",
                    observed_at=timestamp,
                )
                self._append_valve_control_event_locked(
                    registration=failed,
                    event_type="valve_control_failed",
                    observed_at=timestamp,
                    action=registration.get("control_pending_action"),
                )
                return failed
        if status not in {
            "zone_1_open_confirmed",
            "zone_1_closed_confirmed",
            "zone_candidate_open_response_confirmed",
            "zone_candidate_closed_response_confirmed",
        }:
            return None
        frame_hex = report.get("frame")
        valve_endpoint = report.get("valve_endpoint")
        controller_endpoint = report.get("controller_endpoint")
        companion_endpoint = report.get("companion_endpoint")
        if not all(
            isinstance(value, str)
            for value in (
                frame_hex,
                valve_endpoint,
                controller_endpoint,
                companion_endpoint,
            )
        ):
            return None
        try:
            raw = bytes.fromhex(frame_hex)
        except ValueError:
            return None
        response = decode_htv405_gateway_command_response(raw)
        if response is None:
            return None
        valve_endpoint = valve_endpoint.lower()
        controller_endpoint = controller_endpoint.lower()
        companion_endpoint = companion_endpoint.lower()
        try:
            expected_response_endpoint = htv405_command_response_endpoint(
                companion_endpoint
            )
        except ValueError:
            return None
        if (
            raw[5:9].hex() != expected_response_endpoint
            or raw[9:13].hex() != valve_endpoint
        ):
            return None
        confirmed_sequence = report.get("last_confirmed_sequence")
        next_sequence = report.get("next_sequence")
        watering = report.get("confirmed_watering")
        transmitted_zone = report.get("transmitted_zone")
        center_hz = report.get("center_hz")
        selector = report.get("selector")
        if (
            not isinstance(confirmed_sequence, int)
            or isinstance(confirmed_sequence, bool)
            or confirmed_sequence
            != response["rf_control_response_sequence"]
            or not isinstance(next_sequence, int)
            or isinstance(next_sequence, bool)
            or next_sequence != response["rf_next_control_sequence"]
            or not isinstance(watering, bool)
            or watering != response["rf_control_response_watering"]
            or not isinstance(transmitted_zone, int)
            or isinstance(transmitted_zone, bool)
            or transmitted_zone != response["rf_control_response_zone"]
            or not isinstance(center_hz, int)
            or isinstance(center_hz, bool)
            or not 430_000_000 <= center_hz <= 440_000_000
            or not isinstance(selector, int)
            or isinstance(selector, bool)
        ):
            return None
        timestamp = observed_at or datetime.now(timezone.utc).isoformat()
        run_started_at: str | None = None
        run_duration_seconds: int | None = None
        expected_idle_at: str | None = None
        if watering:
            duration = report.get("open_duration_seconds")
            age_ms = report.get("open_age_ms")
            if (
                not isinstance(duration, int)
                or isinstance(duration, bool)
                or duration <= 0
                or duration % 60
                or duration > 3_600
                or not isinstance(age_ms, int)
                or isinstance(age_ms, bool)
                or age_ms < 0
            ):
                return None
            try:
                observed = datetime.fromisoformat(timestamp)
            except ValueError:
                return None
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            started = observed - timedelta(milliseconds=age_ms)
            expected = started + timedelta(seconds=duration)
            run_started_at = started.isoformat()
            run_duration_seconds = duration
            expected_idle_at = expected.isoformat()
        with self._lock:
            registration = next(
                (
                    item
                    for item in self._store.valve_registry()
                    if item["valve_endpoint"] == valve_endpoint
                ),
                None,
            )
            if registration is None or any(
                (
                    registration.get("controller_endpoint")
                    != controller_endpoint,
                    registration.get("control_node_id") != node_id,
                    registration.get("control_companion_endpoint")
                    != companion_endpoint,
                    registration.get("control_selector") != selector,
                )
            ):
                return None
            pending_id = registration.get("control_pending_command_id")
            reported_command_id = report.get("command_id")
            if (
                reported_command_id is not None
                and reported_command_id != pending_id
            ):
                return None
            pending_action = registration.get("control_pending_action")
            try:
                accepted = self._store.confirm_valve_control_response(
                    valve_endpoint=valve_endpoint,
                    node_id=node_id,
                    sequence=confirmed_sequence,
                    next_sequence=next_sequence,
                    zone=transmitted_zone,
                    watering=watering,
                    center_hz=center_hz,
                    observed_at=timestamp,
                    frame=frame_hex.lower(),
                    run_started_at=run_started_at,
                    run_duration_seconds=run_duration_seconds,
                    expected_idle_at=expected_idle_at,
                )
            except ValueError:
                if not isinstance(pending_id, str):
                    return None
                failed = self._store.fail_htv405_command(
                    valve_endpoint=valve_endpoint,
                    node_id=node_id,
                    command_id=pending_id,
                    reason="response_state_mismatch_counter_unsynchronized",
                    observed_at=timestamp,
                )
                self._append_valve_control_event_locked(
                    registration=failed,
                    event_type="valve_control_failed",
                    observed_at=timestamp,
                    action=pending_action,
                )
                return failed
            self._refresh_registry_catalog()
            self._append_valve_control_event_locked(
                registration=accepted,
                event_type="valve_control_confirmed",
                observed_at=timestamp,
                action=pending_action,
            )
            return accepted

    def observe_valve_control_error(
        self,
        node_id: str,
        report: dict[str, Any],
        *,
        observed_at: str | None = None,
    ) -> bool:
        """Invalidate a matching durable reservation after node rejection."""
        if self._store is None or report.get("type") != "command_error":
            return False
        command_id = report.get("command_id")
        if not isinstance(command_id, str):
            return False
        timestamp = observed_at or datetime.now(timezone.utc).isoformat()
        with self._lock:
            registration = next(
                (
                    item
                    for item in self._store.valve_registry()
                    if item.get("control_node_id") == node_id
                    and item.get("control_pending_command_id") == command_id
                ),
                None,
            )
            if registration is None:
                return False
            action = registration.get("control_pending_action")
            error = str(report.get("error") or "node_rejected")
            safe_error = re.sub(r"[^a-z0-9_]+", "_", error.lower()).strip("_")
            failed = self._store.fail_htv405_command(
                valve_endpoint=str(registration["valve_endpoint"]),
                node_id=node_id,
                command_id=command_id,
                reason=(
                    f"node_rejected_{safe_error or 'command'}_"
                    "counter_unsynchronized"
                ),
                observed_at=timestamp,
            )
            self._append_valve_control_event_locked(
                registration=failed,
                event_type="valve_control_failed",
                observed_at=timestamp,
                action=action,
            )
            return True

    def _append_valve_control_event_locked(
        self,
        *,
        registration: dict[str, Any],
        event_type: str,
        observed_at: str,
        action: str | None = None,
    ) -> None:
        """Publish a redacted control result to long-poll consumers."""
        event = {
            "event_id": self._next_event_id,
            "event_type": event_type,
            "observed_at": observed_at,
            "device_id": registration["device_id"],
            "state": {
                "action": action,
                "active_zone": registration.get("control_active_zone"),
                "confirmed_watering": (
                    bool(registration["control_confirmed_watering"])
                    if registration.get("control_confirmed_watering")
                    is not None
                    else None
                ),
                "result": registration.get("control_last_result"),
            },
        }
        self._next_event_id += 1
        self._events.append(event)
        if self._store:
            self._store.append(event)
        self._event_condition.notify_all()

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
                state.get("rf_trailer_valid") is not True
                or state.get("rf_frame_accepted") is not True
                or
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
        known_rejoin: bool = False,
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
            self._active_pairing_rf_identity = None
            self._active_pairing_control_profile = None
            self._active_pairing_expected_valve_endpoint = None
            self._active_pairing_confirmed_valve_endpoint = None
            self._active_pairing_confirmation_observed_at = None
            self._active_pairing_confirmation_receiver = None
            self._active_pairing_confirmed_sensor_endpoint = None
            self._active_pairing_sensor_confirmation_observed_at = None
            self._active_pairing_sensor_confirmation_receiver = None
            self._active_pairing_sensor_identity_mismatch_at = None
            if node_id is not None:
                nodes = {item["node_id"]: item for item in self._pairing_nodes()}
                if node_id not in nodes:
                    self._pairing.stop()
                    raise ValueError("selected radio node cannot transmit pairing")
                if self._node_command_sender is None:
                    self._pairing.stop()
                    raise RuntimeError("radio-node command transport is unavailable")
                automatic = profile_id == AUTOMATIC_HCS026_PROFILE_ID
                automatic_valve = (
                    profile_id == AUTOMATIC_HTV405_PROFILE_ID
                    and not str(factory_endpoint or "").strip()
                )
                valve_candidate = profile_id in {
                    AUTOMATIC_HTV145_PROFILE_ID,
                    AUTOMATIC_HTV405_PROFILE_ID,
                }
                if known_rejoin and profile_id != AUTOMATIC_HTV405_PROFILE_ID:
                    self._pairing.stop()
                    raise ValueError(
                        "known_rejoin is only valid for an HTV405 association"
                    )
                valve_profile = None
                selected_controller_endpoint = self.rf_identity.controller_endpoint
                selected_companion_endpoint = self.rf_identity.companion_endpoint
                if valve_candidate:
                    explicit_controller = str(valve_route or "").strip().lower()
                    explicit_companion = str(companion_endpoint or "").strip().lower()
                    if bool(explicit_controller) != bool(explicit_companion):
                        self._pairing.stop()
                        raise ValueError(
                            "valve controller and companion endpoints must be supplied together"
                        )
                    if explicit_controller:
                        selected_controller_endpoint = explicit_controller
                        selected_companion_endpoint = explicit_companion
                    if not automatic_valve:
                        try:
                            builder = (
                                build_htv145_profile
                                if profile_id == AUTOMATIC_HTV145_PROFILE_ID
                                else build_htv405_profile
                            )
                            valve_profile = builder(
                                factory_endpoint=str(factory_endpoint or ""),
                                valve_route=selected_controller_endpoint,
                                companion_endpoint=selected_companion_endpoint,
                            )
                        except ValueError:
                            self._pairing.stop()
                            raise ValueError(
                                "invalid valve association identifiers"
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
                    selected_controller_endpoint = LEGACY_STOCK_CONTROLLER_ENDPOINT
                    selected_companion_endpoint = LEGACY_STOCK_COMPANION_ENDPOINT
                    clock_lead_seconds = profile.clock_lead_seconds
                required_capability = self._pairing_capability(
                    profile_id,
                    automatic_discovery=automatic_valve,
                )
                if required_capability not in nodes[node_id].get(
                    "capabilities", []
                ):
                    self._pairing.stop()
                    raise ValueError(
                        "selected radio-node firmware does not support this "
                        "pairing profile"
                    )
                if (
                    required_capability == "sensor_pairing_tx"
                    and int(nodes[node_id].get("routine_ack_assigned_sensors") or 0)
                    >= MAXIMUM_ROUTINE_ACK_ASSIGNMENTS
                ):
                    self._pairing.stop()
                    raise ValueError(
                        "selected radio node has no sensor acknowledgement capacity"
                    )
                if not self._node_supports_rf_controller_identity(
                    nodes[node_id],
                    selected_controller_endpoint,
                    selected_companion_endpoint,
                ):
                    self._pairing.stop()
                    raise ValueError(
                        "selected radio-node firmware does not support the "
                        "custom RF controller identity"
                    )
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
                if not automatic and not automatic_valve:
                    command["factory_endpoint"] = (
                        valve_profile.factory_endpoint
                        if valve_profile is not None
                        else profile.factory_endpoint
                    )
                if valve_candidate:
                    command["valve_route"] = selected_controller_endpoint
                    command["companion_endpoint"] = selected_companion_endpoint
                    if known_rejoin:
                        command["known_rejoin"] = True
                elif automatic:
                    command["controller_endpoint"] = selected_controller_endpoint
                    command["companion_endpoint"] = selected_companion_endpoint
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
                self._active_pairing_rf_identity = {
                    "controller_endpoint": selected_controller_endpoint,
                    "companion_endpoint": selected_companion_endpoint,
                }
                if valve_candidate:
                    self._active_pairing_control_profile = {
                        "companion_endpoint": selected_companion_endpoint,
                        # The local association reports selector byte 0x05 on
                        # the selector-2 carrier branch. Store the body value;
                        # the carrier is represented independently.
                        "selector": 0x05,
                        "frequency_offset_hz": int(
                            command["frequency_offset_hz"]
                        ),
                    }
                if valve_profile is not None:
                    self._active_pairing_expected_valve_endpoint = (
                        valve_profile.paired_endpoint
                    )
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
        valve_pairing_active = self._active_pairing_profile_id in {
            AUTOMATIC_HTV145_PROFILE_ID,
            AUTOMATIC_HTV405_PROFILE_ID,
        }
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
            # A valve link may already be present from an earlier stock or
            # local association. Its mere presence is not evidence that the
            # valve accepted this session's assignment.  Once the selected
            # node has transmitted at least one reply, however, a strict link
            # frame for the expected paired endpoint is session-scoped proof
            # of acceptance.  The retained 18-row stock transcript is a model
            # of post-association traffic, not a minimum completion counter.
            observed_valve_completed = (
                valve_pairing_active
                and isinstance(reported_endpoint, str)
                and self._active_pairing_confirmed_valve_endpoint
                == reported_endpoint.lower()
                and int(selected_node.get("pairing_completed_steps") or 0) > 0
            )
            if observed_valve_completed:
                completed_endpoint = reported_endpoint.lower()
                stage = "valve_pairing_completed"
            elif node_state == "failed":
                stage = "transmitter_failed"
            elif node_state == "completed":
                if (
                    valve_pairing_active
                    and isinstance(reported_endpoint, str)
                    and re.fullmatch(
                        r"[89a-f][0-9a-f]{5}(?:13|8f)", reported_endpoint
                    )
                ):
                    stage = "waiting_for_terminal_confirmation"
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
                if (
                    not valve_pairing_active
                    and stage != "valve_pairing_completed"
                ):
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
        sensor_confirmation_required = (
            selected_node is not None
            and not valve_pairing_active
        )
        if sensor_confirmation_required and completed_endpoint is not None:
            if self._active_pairing_confirmed_sensor_endpoint != completed_endpoint:
                completed_endpoint = None
                completed_existing_record = False
                stage = (
                    "controller_identity_mismatch"
                    if self._active_pairing_sensor_identity_mismatch_at is not None
                    else "waiting_for_controller_confirmation"
                )
        active_identity = self._active_pairing_rf_identity or {
            "controller_endpoint": self.rf_identity.controller_endpoint,
            "companion_endpoint": self.rf_identity.companion_endpoint,
        }
        return {
            "available": True,
            "supported_profiles": [
                automatic_hcs026_profile_metadata(),
                automatic_htv145_profile_metadata(),
                automatic_htv405_profile_metadata(),
            ],
            "transmitter_available": bool(pairing_nodes),
            "transmitter_required": True,
            "pairing_nodes": pairing_nodes,
            "selected_node_id": self._active_pairing_node_id,
            "active_profile_id": self._active_pairing_profile_id,
            "rf_controller_identity": {
                **active_identity,
                "mode": (
                    "generated_local"
                    if active_identity["companion_endpoint"]
                    == self.rf_identity.companion_endpoint
                    else "retained_association"
                ),
            },
            "command_id": self._active_pairing_command_id,
            "transmit_performed": self._active_pairing_node_id is not None,
            "stage": stage,
            "completed_endpoint": completed_endpoint,
            "completed_existing_record": completed_existing_record,
            "valve_confirmation_observed_at": (
                self._active_pairing_confirmation_observed_at
            ),
            "valve_confirmation_receiver": (
                self._active_pairing_confirmation_receiver
            ),
            "sensor_confirmation_observed_at": (
                self._active_pairing_sensor_confirmation_observed_at
            ),
            "sensor_confirmation_receiver": (
                self._active_pairing_sensor_confirmation_receiver
            ),
            "sensor_controller_identity_mismatch_observed": (
                self._active_pairing_sensor_identity_mismatch_at is not None
            ),
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
                if self._active_pairing_confirmed_sensor_endpoint != endpoint:
                    raise RuntimeError(
                        "paired sensor has not confirmed the active RF "
                        "controller identity"
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
                    **(
                        self._active_pairing_rf_identity
                        or {
                            "controller_endpoint": LEGACY_STOCK_CONTROLLER_ENDPOINT,
                            "companion_endpoint": LEGACY_STOCK_COMPANION_ENDPOINT,
                        }
                    ),
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

    def complete_pairing(
        self,
        *,
        endpoint: str,
        name: str,
        area: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Persist metadata for the device proven by the active RF session."""
        with self._lock:
            valve_profile = self._active_pairing_profile_id in {
                AUTOMATIC_HTV145_PROFILE_ID,
                AUTOMATIC_HTV405_PROFILE_ID,
            }
        if not valve_profile:
            return self.complete_hcs026_pairing(
                endpoint=endpoint,
                name=name,
                area=area,
                now=now,
            )
        return self._complete_valve_pairing(
            endpoint=endpoint,
            name=name,
            area=area,
            now=now,
        )

    def _complete_valve_pairing(
        self,
        *,
        endpoint: str,
        name: str,
        area: str | None,
        now: datetime | None,
    ) -> dict[str, Any]:
        """Name a valve after command-scoped valve-originated confirmation."""
        endpoint = endpoint.strip().lower()
        name = _clean_label(name, "name")
        area = _clean_optional_label(area, "area")
        timestamp = (now or datetime.now(timezone.utc)).isoformat()
        with self._lock:
            if self._pairing is None or self._store is None:
                raise RuntimeError("persistent pairing state is unavailable")
            if self._active_pairing_profile_id not in {
                AUTOMATIC_HTV145_PROFILE_ID,
                AUTOMATIC_HTV405_PROFILE_ID,
            }:
                raise RuntimeError("active pairing session is not for a valve")
            if (
                endpoint != self._active_pairing_expected_valve_endpoint
                or endpoint != self._active_pairing_confirmed_valve_endpoint
                or self._active_pairing_confirmation_observed_at is None
            ):
                raise RuntimeError(
                    "paired valve has not confirmed the active RF controller identity"
                )
            registration = next(
                (
                    item
                    for item in self._store.valve_registry()
                    if item["valve_endpoint"] == endpoint
                ),
                None,
            )
            if registration is None:
                raise KeyError(endpoint)
            updated = self._store.update_valve_registry_device(
                str(registration["device_id"]),
                name=name,
                area=area,
                updated_at=timestamp,
            )
            self._refresh_registry_catalog()
            self._ensure_registered_valve_devices()
            device_id = str(updated["device_id"])
            if device_id in self._devices:
                self._devices[device_id]["name"] = name
                self._devices[device_id]["area"] = area
            if self._active_pairing_profile_id == AUTOMATIC_HTV405_PROFILE_ID:
                # Terminal valve evidence is sufficient for HA to finish the
                # naming flow, but the radio node may still owe later replies
                # in the bounded 18-step association transcript. Release the
                # gateway session without transmitting a cancellation; the
                # node will complete or expire its own bounded session.
                self._release_active_pairing_node()
            else:
                self._cancel_active_pairing_node()
            self._pairing.stop()
            return updated

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
        if (
            pairing_state == "paired"
            and self._active_pairing_node_id is not None
            and self._active_pairing_profile_id
            not in {AUTOMATIC_HTV145_PROFILE_ID, AUTOMATIC_HTV405_PROFILE_ID}
            and self._active_pairing_rf_identity is not None
        ):
            observed_controller = state.get("rf_endpoint_a")
            expected_controller = self._active_pairing_rf_identity.get(
                "controller_endpoint"
            )
            if not isinstance(observed_controller, str) or (
                observed_controller.strip().lower() != expected_controller
            ):
                self._active_pairing_sensor_identity_mismatch_at = timestamp
                return
            message_type = state.get(
                "rf_message_type", state.get("message_type")
            )
            if isinstance(message_type, int) and (message_type & 0x7F) == 3:
                if isinstance(paired, str):
                    self._active_pairing_confirmed_sensor_endpoint = (
                        paired.strip().lower()
                    )
                    self._active_pairing_sensor_confirmation_observed_at = (
                        timestamp
                    )
                    receiver = state.get(
                        "rf_receiver_id", state.get("rf_node_id")
                    )
                    if isinstance(receiver, str):
                        self._active_pairing_sensor_confirmation_receiver = (
                            receiver
                        )
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
        """Return connected protocol-v2 nodes advertising any pairing family."""
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
                and any(
                    capability in node.get("capabilities", [])
                    for capability in (
                        "sensor_pairing_tx",
                        "valve_pairing_tx_candidate",
                        "htv405_auto_identity_pairing",
                        "htv145_pairing_tx_candidate",
                    )
                )
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
            result.append(item)
        return result

    @staticmethod
    def _pairing_capability(
        profile_id: str, *, automatic_discovery: bool = False
    ) -> str:
        """Map a pairing profile to the node capability that contains it."""
        if profile_id == AUTOMATIC_HTV405_PROFILE_ID:
            if automatic_discovery:
                return "htv405_auto_identity_pairing"
            return "valve_pairing_tx_candidate"
        if profile_id == AUTOMATIC_HTV145_PROFILE_ID:
            return "htv145_pairing_tx_candidate"
        return "sensor_pairing_tx"

    def _cancel_active_pairing_node(self) -> None:
        """Best-effort disarm for the node selected by the current session."""
        self._clear_active_pairing_node(send_cancel=True)

    def _release_active_pairing_node(self) -> None:
        """Forget gateway ownership while a bounded node session finishes."""
        self._clear_active_pairing_node(send_cancel=False)

    def _clear_active_pairing_node(self, *, send_cancel: bool) -> None:
        """Clear gateway pairing state and optionally cancel the node session."""
        node_id = self._active_pairing_node_id
        command_id = self._active_pairing_command_id
        sender = self._node_command_sender
        if (
            send_cancel
            and node_id is not None
            and command_id is not None
            and sender is not None
        ):
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
        self._active_pairing_rf_identity = None
        self._active_pairing_control_profile = None
        self._active_pairing_expected_valve_endpoint = None
        self._active_pairing_confirmed_valve_endpoint = None
        self._active_pairing_confirmation_observed_at = None
        self._active_pairing_confirmation_receiver = None
        self._active_pairing_confirmed_sensor_endpoint = None
        self._active_pairing_sensor_confirmation_observed_at = None
        self._active_pairing_sensor_confirmation_receiver = None
        self._active_pairing_sensor_identity_mismatch_at = None

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
            try:
                existing = self._store.registry_device(device_id)
            except KeyError:
                valve = next(
                    (
                        item
                        for item in self._store.valve_registry()
                        if item["device_id"] == device_id
                    ),
                    None,
                )
                if valve is None:
                    raise
                next_name = (
                    str(valve["name"])
                    if name is None
                    else _clean_label(name, "name")
                )
                next_area = (
                    valve["area"]
                    if area is _UNSET
                    else _clean_optional_label(area, "area")
                )
                timestamp = (now or datetime.now(timezone.utc)).isoformat()
                updated = self._store.update_valve_registry_device(
                    device_id,
                    name=next_name,
                    area=next_area,
                    updated_at=timestamp,
                )
                self._refresh_registry_catalog()
                if device_id in self._devices:
                    self._devices[device_id]["name"] = updated["name"]
                    self._devices[device_id]["area"] = updated["area"]
                return updated
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
            try:
                existing = self._store.registry_device(device_id)
            except KeyError:
                suppressed_at = datetime.now(timezone.utc).isoformat()
                try:
                    valve_registration = next(
                        (
                            item
                            for item in self._store.valve_registry()
                            if item["device_id"] == device_id
                        ),
                        None,
                    )
                    if valve_registration is not None:
                        self._revoke_htv405_ack_locked(valve_registration)
                    forgotten_valve = self._store.forget_valve_registry_device(
                        device_id,
                        suppressed_at=suppressed_at,
                    )
                    result = {
                        **forgotten_valve,
                        "endpoint": forgotten_valve["valve_endpoint"],
                    }
                except KeyError:
                    result = self._store.forget_observed_device(
                        device_id,
                        suppressed_at=suppressed_at,
                    )
                self._refresh_registry_catalog()
                self._devices.pop(device_id, None)
                self._memory_metrics.pop(device_id, None)
                self._memory_reception_metrics.pop(device_id, None)
                return result
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
        association_peers = {self.rf_identity.controller_endpoint}
        if self._store is not None:
            association_peers.update(
                str(item["controller_endpoint"])
                for item in self._store.ack_assignments()
                if item.get("controller_endpoint")
            )
        self.catalog = DeviceCatalog(
            sensors=self.catalog.sensors,
            valves=self.catalog.valves,
            hcs026_pairing_peers=(
                self.catalog.hcs026_pairing_peers | association_peers
            ),
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
            state = copy.deepcopy(event["state"])
            restored_event_id = event["event_id"]
            restored_observed_at = event["observed_at"]
            # Device snapshots retain the decoder projection that was current
            # when the frame arrived. Re-run only accepted HTV145 snapshots so
            # receive-side protocol corrections can clear stale watering state
            # and backfill supported battery/usage fields after an upgrade.
            if event.get("model") == HTV145_MODEL:
                raw = event.get("raw")
                if isinstance(raw, str):
                    try:
                        refreshed = normalize_row(
                            {"len": len(raw) * 4, "data": raw},
                            catalog=self.catalog,
                        )
                    except (KeyError, TypeError, ValueError):
                        refreshed = {}
                    valve = self.catalog.valve_link(
                        str(refreshed.get("endpoint_a", "")),
                        str(refreshed.get("endpoint_b", "")),
                    )
                    if (
                        refreshed.get("trailer_valid") is True
                        and valve is not None
                        and valve.device_id == device_id
                    ):
                        if (
                            "valve_command" in refreshed
                            and "is_watering" not in refreshed
                        ):
                            # Older decoders persisted controller requests as
                            # device state. Recover the newest independently
                            # valve-originated state instead of restoring a
                            # locally transmitted request as watering proof.
                            for candidate in reversed(self._events):
                                if candidate.get("device_id") != device_id:
                                    continue
                                candidate_raw = candidate.get("raw")
                                if not isinstance(candidate_raw, str):
                                    continue
                                try:
                                    candidate_decoded = normalize_row(
                                        {
                                            "len": len(candidate_raw) * 4,
                                            "data": candidate_raw,
                                        },
                                        catalog=self.catalog,
                                    )
                                except (KeyError, TypeError, ValueError):
                                    continue
                                if not isinstance(
                                    candidate_decoded.get("is_watering"),
                                    bool,
                                ):
                                    continue
                                state = copy.deepcopy(candidate["state"])
                                refreshed = candidate_decoded
                                restored_event_id = candidate["event_id"]
                                restored_observed_at = candidate["observed_at"]
                                state["raw"] = candidate_raw
                                break
                        for key in (
                            "valve_state",
                            "is_watering",
                            "duration_seconds",
                            "last_usage_liters",
                            "battery_low",
                            "battery_status",
                            "battery_percent",
                        ):
                            if key in refreshed:
                                state[key] = refreshed[key]
            elif event.get("model") == "HTV405FRF":
                retained = (
                    self._store.device_observation_events(device_id)
                    if self._store is not None
                    else [
                        candidate
                        for candidate in self._events
                        if candidate.get("event_type")
                        == "device_observation"
                        and candidate.get("device_id") == device_id
                    ]
                )
                canonical_state: dict[str, Any] = {}
                for candidate in retained:
                    if frame_accepted(candidate) is False:
                        continue
                    candidate_state = candidate.get("state")
                    if not isinstance(candidate_state, dict):
                        continue
                    canonical_state = _merge_htv405_zone_state(
                        candidate_state,
                        canonical_state,
                    )
                if canonical_state:
                    state = canonical_state
            device = {
                "device_id": event["device_id"],
                "name": (
                    registry_metadata["name"]
                    if registry_metadata is not None
                    else event["name"]
                ),
                "model": event["model"],
                "available": True,
                "last_event_id": restored_event_id,
                "observed_at": restored_observed_at,
                "state": state,
            }
            if registry_metadata is not None:
                device["area"] = registry_metadata.get("area")
            self._devices[event["device_id"]] = device
            if self._store is not None and event.get("model") == "HTV405FRF":
                self._store.update_device_snapshot_state(event, state)

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
        if (
            event.get("model") == "HTV405FRF"
            and event.get("state", {}).get("rf_trailer_valid") is not True
        ):
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
