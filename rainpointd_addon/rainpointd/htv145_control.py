"""Persistent, disabled-by-default HTV145 single-zone control candidate.

This module is deliberately not imported by the Home Assistant or HTTP API.
It coordinates an explicitly selected research radio node and the compile-time
gated ESP32 candidate. One gateway command creates one bounded RF burst; a
restart never replays an unresolved reservation.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

from .storage import SQLiteEventStore
from .valve_protocol import (
    TRAILER_RESIDUES,
    ValveLink,
    decode_htv145_command_response,
    decode_htv145_gateway_command,
    decode_htv145_state_report,
)


_ENDPOINT = re.compile(r"[0-9a-f]{8}\Z")
_NODE_ID = re.compile(r"rp-[0-9a-f]{12}\Z")


@dataclass(frozen=True)
class Htv145ControlProfile:
    """Association-specific RF identity and selected nearby radio node."""

    node_id: str
    controller_endpoint: str
    valve_endpoint: str
    center_hz: int
    power_dbm: int
    invert: bool
    trailer_residual: int

    def __post_init__(self) -> None:
        if not _NODE_ID.fullmatch(self.node_id):
            raise ValueError("invalid HTV145 radio node id")
        endpoints = (self.controller_endpoint, self.valve_endpoint)
        if any(not _ENDPOINT.fullmatch(value) for value in endpoints):
            raise ValueError("HTV145 endpoints must be lowercase hexadecimal")
        if self.controller_endpoint == self.valve_endpoint:
            raise ValueError("HTV145 endpoints must differ")
        if not 400_000_000 <= self.center_hz <= 500_000_000:
            raise ValueError("HTV145 center frequency is outside bench bounds")
        if not -30 <= self.power_dbm <= 10:
            raise ValueError("HTV145 transmit power is outside CC1101 bounds")
        if not isinstance(self.invert, bool):
            raise ValueError("HTV145 inversion flag must be a boolean")
        if self.trailer_residual not in TRAILER_RESIDUES:
            raise ValueError("unknown HTV145 trailer residual")

    @property
    def link(self) -> ValveLink:
        return ValveLink(
            bytes.fromhex(self.controller_endpoint),
            bytes.fromhex(self.valve_endpoint),
        )


class Htv145ControlCoordinator:
    """Persist and confirm at-most-once HTV145 logical commands.

    Transmit is off unless ``enabled=True`` is supplied by an isolated caller.
    There is intentionally no configuration option or public server route that
    constructs an enabled instance.
    """

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

    def configure(
        self, profile: Htv145ControlProfile, *, observed_at: str
    ) -> dict[str, Any]:
        """Persist a profile without enabling or transmitting anything."""
        return self.store.configure_htv145_control(
            valve_endpoint=profile.valve_endpoint,
            controller_endpoint=profile.controller_endpoint,
            node_id=profile.node_id,
            center_hz=profile.center_hz,
            power_dbm=profile.power_dbm,
            invert=profile.invert,
            trailer_residual=profile.trailer_residual,
            updated_at=observed_at,
        )

    def synchronize_from_passive_command(
        self,
        profile: Htv145ControlProfile,
        frame: bytes,
        *,
        observed_at: str,
    ) -> dict[str, Any]:
        """Synchronize only from a structurally valid command on this link."""
        decoded = decode_htv145_gateway_command(frame, profile.link)
        if decoded is None:
            raise ValueError("frame is not a matching HTV145 gateway command")
        return self.store.synchronize_htv145_control_counter(
            valve_endpoint=profile.valve_endpoint,
            next_sequence=int(decoded["next_sequence"]),
            source="passive_stock_command",
            observed_at=observed_at,
        )

    def start(
        self, profile: Htv145ControlProfile, *, observed_at: str
    ) -> tuple[dict[str, Any], ...]:
        """Restore node configuration/counter, never an actuator command.

        An unresolved durable reservation is not replayed after restart. It
        must first be resolved by valve evidence or explicitly failed.
        """
        self._require_enabled()
        state = self._state(profile.valve_endpoint)
        self._require_profile(state, profile)
        if state["pending_command_id"] is not None:
            raise RuntimeError(
                "unresolved HTV145 command retained; startup will not replay it"
            )
        configure = self._command(
            "htv145_control_configure",
            controller_endpoint=profile.controller_endpoint,
            valve_endpoint=profile.valve_endpoint,
            center_hz=profile.center_hz,
            power_dbm=profile.power_dbm,
            invert=profile.invert,
            trailer_residual=profile.trailer_residual,
        )
        commands = [configure]
        if state["counter_synchronized"]:
            commands.append(
                self._command(
                    "htv145_control_sync",
                    next_sequence=state["next_sequence"],
                )
            )
        for command in commands:
            self.sender(profile.node_id, command)
        return tuple(commands)

    def request_open(
        self,
        profile: Htv145ControlProfile,
        *,
        duration_seconds: int,
        started_at: str,
    ) -> dict[str, Any]:
        """Reserve and dispatch one duration-bounded logical open."""
        if duration_seconds < 60 or duration_seconds > 3_600:
            raise ValueError("HTV145 run must be between 60 and 3600 seconds")
        if duration_seconds % 60:
            raise ValueError("HTV145 run must use whole minutes")
        expected_idle_at = (
            datetime.fromisoformat(started_at)
            + timedelta(seconds=duration_seconds)
        ).isoformat()
        return self._reserve_and_send(
            profile,
            action="open",
            duration_seconds=duration_seconds,
            started_at=started_at,
            expected_idle_at=expected_idle_at,
        )

    def request_close(
        self, profile: Htv145ControlProfile, *, started_at: str
    ) -> dict[str, Any]:
        """Reserve and dispatch one explicit early-stop command."""
        return self._reserve_and_send(
            profile,
            action="close",
            duration_seconds=None,
            started_at=started_at,
            expected_idle_at=None,
        )

    def observe_frame(
        self,
        profile: Htv145ControlProfile,
        frame: bytes,
        *,
        observed_at: str,
    ) -> dict[str, Any]:
        """Persist state and resolve a reservation only with matching evidence."""
        state = self._state(profile.valve_endpoint)
        self._require_profile(state, profile)
        response = decode_htv145_command_response(frame, profile.link)
        if response is not None:
            if state["pending_command_id"] is None:
                raise ValueError("HTV145 response has no durable reservation")
            return self.store.confirm_htv145_command(
                valve_endpoint=profile.valve_endpoint,
                command_id=state["pending_command_id"],
                sequence=int(response["sequence"]),
                watering=bool(response["watering"]),
                confirmation="matching_immediate_response",
                observed_at=observed_at,
                frame=frame.hex(),
            )
        report = decode_htv145_state_report(frame, profile.link)
        if report is None:
            raise ValueError("frame is not matching HTV145 valve evidence")
        watering = bool(report["watering"])
        if state["pending_command_id"] is not None:
            expected_watering = state["pending_action"] == "open"
            if watering == expected_watering:
                # The report's sequence belongs to the telemetry stream. The
                # confirmed counter is the exact sequence already reserved.
                return self.store.confirm_htv145_command(
                    valve_endpoint=profile.valve_endpoint,
                    command_id=state["pending_command_id"],
                    sequence=state["pending_sequence"],
                    watering=watering,
                    confirmation="matching_independent_state_report",
                    observed_at=observed_at,
                    frame=frame.hex(),
                )
        return self.store.observe_htv145_control_state(
            valve_endpoint=profile.valve_endpoint,
            watering=watering,
            observed_at=observed_at,
            frame=frame.hex(),
        )

    def observe_candidate_status(
        self,
        profile: Htv145ControlProfile,
        message: dict[str, Any],
        *,
        observed_at: str,
    ) -> dict[str, Any] | None:
        """Resolve/fail a durable reservation from a node candidate report."""
        message_type = message.get("type")
        if message_type not in {
            "htv145_control_candidate",
            "command_error",
        }:
            return None
        if message.get("node_id") != profile.node_id:
            return None
        state = self._state(profile.valve_endpoint)
        command_id = message.get("command_id")
        if not isinstance(command_id, str) or command_id != state["pending_command_id"]:
            return None
        if message_type == "command_error":
            error = message.get("error")
            if not isinstance(error, str) or "htv145" not in error:
                return None
            return self.store.fail_htv145_command(
                valve_endpoint=profile.valve_endpoint,
                command_id=command_id,
                reason=f"node_rejected_{error}_counter_unsynchronized",
                observed_at=observed_at,
            )
        status = message.get("state")
        frame_hex = message.get("frame")
        if status == "confirmed" and isinstance(frame_hex, str):
            try:
                frame = bytes.fromhex(frame_hex)
            except ValueError as error:
                raise ValueError("candidate returned invalid frame hex") from error
            return self.observe_frame(profile, frame, observed_at=observed_at)
        if status in {
            "transmit_failed",
            "response_receiver_tune_failed",
            "confirmation_timeout_counter_unsynchronized",
            "gateway_connection_lost_counter_unsynchronized",
            "conflicting_command_response",
        }:
            failure_class = message.get("failure_class")
            reason = str(status)
            if isinstance(failure_class, str) and failure_class:
                reason = f"{reason}:{failure_class}"
            return self.store.fail_htv145_command(
                valve_endpoint=profile.valve_endpoint,
                command_id=command_id,
                reason=reason,
                observed_at=observed_at,
            )
        return None

    def _reserve_and_send(
        self,
        profile: Htv145ControlProfile,
        *,
        action: str,
        duration_seconds: int | None,
        started_at: str,
        expected_idle_at: str | None,
    ) -> dict[str, Any]:
        self._require_enabled()
        state = self._state(profile.valve_endpoint)
        self._require_profile(state, profile)
        command_id = uuid.uuid4().hex
        reservation = self.store.reserve_htv145_command(
            valve_endpoint=profile.valve_endpoint,
            command_id=command_id,
            action=action,
            duration_seconds=duration_seconds,
            started_at=started_at,
            expected_idle_at=expected_idle_at,
        )
        fields: dict[str, Any] = {
            "expected_sequence": reservation["pending_sequence"]
        }
        if duration_seconds is not None:
            fields["duration_seconds"] = duration_seconds
        command = self._command(
            f"htv145_control_{action}", command_id=command_id, **fields
        )
        try:
            # This is one logical send. The ESP32 owns the one bounded burst of
            # byte-identical RF attempts and stops it on a valid response.
            self.sender(profile.node_id, command)
        except Exception:
            self.store.fail_htv145_command(
                valve_endpoint=profile.valve_endpoint,
                command_id=command_id,
                reason="node_dispatch_failed_counter_unsynchronized",
                observed_at=started_at,
            )
            raise
        return command

    def _state(self, valve_endpoint: str) -> dict[str, Any]:
        states = self.store.htv145_control_states(valve_endpoint)
        if not states:
            raise KeyError(valve_endpoint)
        return states[0]

    @staticmethod
    def _require_profile(
        state: dict[str, Any], profile: Htv145ControlProfile
    ) -> None:
        fields = {
            "node_id": profile.node_id,
            "controller_endpoint": profile.controller_endpoint,
            "valve_endpoint": profile.valve_endpoint,
            "center_hz": profile.center_hz,
            "power_dbm": profile.power_dbm,
            "invert": profile.invert,
            "trailer_residual": profile.trailer_residual,
        }
        if any(state[key] != value for key, value in fields.items()):
            raise ValueError("HTV145 profile differs from durable association")

    @staticmethod
    def _command(command_type: str, **fields: Any) -> dict[str, Any]:
        return {
            "type": command_type,
            "command_id": fields.pop("command_id", uuid.uuid4().hex),
            **fields,
        }

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise PermissionError("HTV145 transmit candidate is disabled")
