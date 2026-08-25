"""Durable, disabled-by-default HTV405 supervised control coordinator."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from .storage import SQLiteEventStore


_ENDPOINT = re.compile(r"[0-9a-f]{8}\Z")
_NODE_ID = re.compile(r"rp-[0-9a-f]{12}\Z")
HTV405_CONTROL_BASE_CENTER_HZ = 433_421_373
HTV405_RESPONSE_WINDOW_SECONDS = 5.0


@dataclass(frozen=True)
class Htv405ControlProfile:
    """Association-specific identity and selected nearby radio node."""

    node_id: str
    controller_endpoint: str
    valve_endpoint: str
    companion_endpoint: str
    selector: int
    frequency_offset_hz: int

    def __post_init__(self) -> None:
        if not _NODE_ID.fullmatch(self.node_id):
            raise ValueError("invalid HTV405 radio node id")
        endpoints = (
            self.controller_endpoint,
            self.valve_endpoint,
            self.companion_endpoint,
        )
        if any(not _ENDPOINT.fullmatch(value) for value in endpoints):
            raise ValueError("HTV405 endpoints must be lowercase hexadecimal")
        if len(set(endpoints)) != len(endpoints):
            raise ValueError("HTV405 endpoints must be distinct")
        if self.selector not in {0x05, 0x85}:
            raise ValueError("HTV405 selector is not physically validated")
        if not -1_500_000 <= self.frequency_offset_hz <= 1_500_000:
            raise ValueError("HTV405 frequency offset is outside bounds")


class Htv405ControlCoordinator:
    """Reserve and dispatch at-most-once, duration-bounded HTV405 commands."""

    def __init__(
        self,
        *,
        store: SQLiteEventStore,
        sender: Callable[[str, dict[str, Any]], None],
        enabled: bool = False,
    ) -> None:
        self.store = store
        self.sender = sender
        self.enabled = enabled

    def request_open(
        self,
        profile: Htv405ControlProfile,
        *,
        zone: int,
        duration_seconds: int,
        started_at: str,
    ) -> dict[str, Any]:
        """Reserve and dispatch one bounded open for exactly one zone."""
        return self._reserve_and_send(
            profile,
            action="open",
            zone=zone,
            duration_seconds=duration_seconds,
            started_at=started_at,
        )

    def request_close(
        self,
        profile: Htv405ControlProfile,
        *,
        zone: int,
        started_at: str,
    ) -> dict[str, Any]:
        """Reserve and dispatch an explicit early stop for the active zone."""
        return self._reserve_and_send(
            profile,
            action="close",
            zone=zone,
            duration_seconds=None,
            started_at=started_at,
        )

    def _reserve_and_send(
        self,
        profile: Htv405ControlProfile,
        *,
        action: str,
        zone: int,
        duration_seconds: int | None,
        started_at: str,
    ) -> dict[str, Any]:
        self._require_enabled()
        self._require_profile(profile)
        command_id = uuid.uuid4().hex
        reservation = self.store.reserve_htv405_command(
            valve_endpoint=profile.valve_endpoint,
            node_id=profile.node_id,
            command_id=command_id,
            action=action,
            zone=zone,
            duration_seconds=duration_seconds,
            started_at=started_at,
        )
        sequence = int(reservation["control_pending_sequence"])
        commands = (
            self._command(
                "valve_control_configure",
                command_id=command_id,
                controller_endpoint=profile.controller_endpoint,
                valve_endpoint=profile.valve_endpoint,
                companion_endpoint=profile.companion_endpoint,
                selector=profile.selector,
                frequency_offset_hz=profile.frequency_offset_hz,
            ),
            self._command(
                "valve_control_sync",
                command_id=command_id,
                next_sequence=sequence,
            ),
            self._command(
                f"valve_control_{action}",
                command_id=command_id,
                zone=zone,
                expected_sequence=sequence,
                **(
                    {"duration_seconds": duration_seconds}
                    if duration_seconds is not None
                    else {}
                ),
            ),
        )
        try:
            for command in commands:
                self.sender(profile.node_id, command)
        except Exception:
            self.store.fail_htv405_command(
                valve_endpoint=profile.valve_endpoint,
                node_id=profile.node_id,
                command_id=command_id,
                reason="node_dispatch_failed_counter_unsynchronized",
                observed_at=started_at,
            )
            raise
        expected_idle_at = None
        if duration_seconds is not None:
            expected_idle_at = (
                datetime.fromisoformat(started_at)
                + timedelta(seconds=duration_seconds)
            ).isoformat()
        return {
            "command_id": command_id,
            "action": action,
            "zone": zone,
            "duration_seconds": duration_seconds,
            "expected_idle_at": expected_idle_at,
            "state": "pending_authenticated_response",
        }

    def _require_profile(self, profile: Htv405ControlProfile) -> None:
        registration = next(
            (
                item
                for item in self.store.valve_registry()
                if item["valve_endpoint"] == profile.valve_endpoint
            ),
            None,
        )
        if registration is None:
            raise KeyError(profile.valve_endpoint)
        expected = {
            "control_node_id": profile.node_id,
            "controller_endpoint": profile.controller_endpoint,
            "control_companion_endpoint": profile.companion_endpoint,
            "control_selector": profile.selector,
            "control_frequency_offset_hz": profile.frequency_offset_hz,
        }
        if any(registration.get(key) != value for key, value in expected.items()):
            raise ValueError("HTV405 profile differs from durable association")

    @staticmethod
    def _command(command_type: str, **fields: Any) -> dict[str, Any]:
        return {
            "type": command_type,
            "command_id": fields.pop("command_id", uuid.uuid4().hex),
            **fields,
        }

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise PermissionError("HTV405 supervised control is disabled")
