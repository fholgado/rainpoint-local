"""Explicitly gated, duration-bounded HTV405 control coordinator.

This module connects the duration-bounded safety state machine to authenticated
radio-node command vocabulary.  It is intentionally not imported by the HTTP
API or Home Assistant integration, and construction defaults to disabled.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from .safety import ActionKind, SafetyAction, SafetyState, ValveSafetyController


_ENDPOINT = re.compile(r"[0-9a-f]{8}\Z")
_NODE_ID = re.compile(r"rp-[0-9a-f]{12}\Z")


@dataclass(frozen=True)
class BenchValveControlProfile:
    """One locally enrolled, physically validated control association."""

    node_id: str
    controller_endpoint: str
    valve_endpoint: str
    companion_endpoint: str
    selector: int
    frequency_offset_hz: int

    def __post_init__(self) -> None:
        if not _NODE_ID.fullmatch(self.node_id):
            raise ValueError("invalid control node id")
        endpoints = (
            self.controller_endpoint,
            self.valve_endpoint,
            self.companion_endpoint,
        )
        if any(not _ENDPOINT.fullmatch(value) for value in endpoints):
            raise ValueError("control endpoints must be lowercase hexadecimal")
        if len(set(endpoints)) != len(endpoints):
            raise ValueError("control endpoints must be distinct")
        if self.selector not in {0x05, 0x85}:
            raise ValueError("selector must come from a proven association")
        if not -1_500_000 <= self.frequency_offset_hz <= 1_500_000:
            raise ValueError("control frequency offset is outside bench bounds")


class BenchValveControlSession:
    """Drive one four-zone valve through authenticated node commands.

    The session never advances its counter from transmit success.  A matching
    over-air response supplied to :meth:`observe_response` is the only event
    that advances the sequence or valve state.
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        profile: BenchValveControlProfile,
        next_sequence: int,
        sender: Callable[[str, dict[str, Any]], None],
        user_max_seconds: int = 1_800,
    ) -> None:
        if next_sequence not in range(0x20):
            raise ValueError("next control sequence must be in 0x00..0x1f")
        self.enabled = enabled
        self.profile = profile
        self.next_sequence = next_sequence
        self.sender = sender
        self.safety = ValveSafetyController(
            user_max_seconds=user_max_seconds,
            zone_count=4,
            minimum_command_interval_seconds=15,
        )
        self.pending_sequence: int | None = None
        self.pending_kind: ActionKind | None = None
        self.pending_zone: int | None = None
        self.pending_attempt = 0
        self.counter_synchronized = True
        self.last_fault: str | None = None
        self.started = False

    @property
    def state(self) -> SafetyState:
        return self.safety.state

    def start(self, now: float) -> tuple[dict[str, Any], ...]:
        """Restore the counter without transmitting an actuator command."""
        self._require_enabled()
        if self.started:
            raise RuntimeError("bench valve session has already started")
        self.started = True
        commands = [
            self._command(
                "valve_control_configure",
                controller_endpoint=self.profile.controller_endpoint,
                valve_endpoint=self.profile.valve_endpoint,
                companion_endpoint=self.profile.companion_endpoint,
                selector=self.profile.selector,
                frequency_offset_hz=self.profile.frequency_offset_hz,
            ),
            self._command(
                "valve_control_sync", next_sequence=self.next_sequence
            ),
        ]
        commands.extend(self._dispatch(self.safety.start(now)))
        return tuple(commands)

    def request_open(
        self, duration_seconds: int, now: float, *, zone: int
    ) -> tuple[dict[str, Any], ...]:
        self._require_ready()
        if self.pending_sequence is not None:
            raise RuntimeError("a valve response is still pending")
        if not self.counter_synchronized:
            raise RuntimeError("the valve control counter is not synchronized")
        return self._dispatch(
            self.safety.request_open(duration_seconds, now, zone=zone)
        )

    def request_close(
        self, now: float, *, zone: int | None = None
    ) -> tuple[dict[str, Any], ...]:
        self._require_ready()
        if self.pending_sequence is not None or not self.counter_synchronized:
            raise RuntimeError("the valve control counter is not synchronized")
        return self._dispatch(self.safety.request_close(now, zone=zone))

    def tick(self, now: float) -> tuple[dict[str, Any], ...]:
        self._require_ready()
        return self._dispatch(self.safety.tick(now))

    def observe_response(
        self, *, sequence: int, zone: int, watering: bool, now: float
    ) -> tuple[dict[str, Any], ...]:
        """Accept a response already structurally validated by the gateway."""
        self._require_ready()
        if (
            self.pending_sequence is None
            or sequence != self.pending_sequence
            or zone != self.pending_zone
            or not isinstance(watering, bool)
        ):
            raise ValueError("response does not match the pending command")
        self.next_sequence = (sequence + 1) & 0x1F
        self.pending_sequence = None
        self.pending_kind = None
        self.pending_zone = None
        self.pending_attempt = 0
        self.counter_synchronized = True
        return self._dispatch(
            self.safety.observe_valve(watering=watering, now=now)
        )

    def observe_telemetry(
        self, *, watering: bool, now: float
    ) -> tuple[dict[str, Any], ...]:
        """Observe valve state without treating telemetry as a counter ACK."""
        self._require_ready()
        if not isinstance(watering, bool):
            raise ValueError("watering must be a boolean")
        return self._dispatch(
            self.safety.observe_valve(watering=watering, now=now)
        )

    def _dispatch(
        self, actions: tuple[SafetyAction, ...]
    ) -> tuple[dict[str, Any], ...]:
        commands: list[dict[str, Any]] = []
        for action in actions:
            if action.kind is ActionKind.REPORT_FAULT:
                self.last_fault = action.reason
                if action.reason == "open_confirmation_missing_bounded_run":
                    self.counter_synchronized = False
                continue
            if action.zone not in range(1, 5):
                raise RuntimeError("control action has no validated zone")
            if self.pending_sequence is not None:
                if (
                    action.kind is ActionKind.SEND_CLOSE
                    and self.pending_kind is ActionKind.SEND_CLOSE
                ):
                    # Repeating the exact idempotent early-stop is safe under
                    # either outcome: it is accepted if the first frame was
                    # lost and stale if the first frame advanced the counter.
                    # Never guess the post-command counter.
                    sequence = self.pending_sequence
                else:
                    self.last_fault = "control_counter_unknown_no_command_sent"
                    self.counter_synchronized = False
                    continue
            elif not self.counter_synchronized:
                self.last_fault = "control_counter_unknown_no_command_sent"
                continue
            else:
                sequence = self.next_sequence
            if action.kind is ActionKind.SEND_OPEN:
                command = self._command(
                    "valve_control_open",
                    zone=action.zone,
                    duration_seconds=action.duration_seconds,
                    expected_sequence=sequence,
                )
            else:
                command = self._command(
                    "valve_control_close",
                    zone=action.zone,
                    expected_sequence=sequence,
                )
            commands.append(command)
            self.pending_sequence = sequence
            self.pending_kind = action.kind
            self.pending_zone = action.zone
            self.pending_attempt = int(action.attempt or 1)
        return tuple(commands)

    def _command(self, command_type: str, **fields: Any) -> dict[str, Any]:
        command = {
            "type": command_type,
            "command_id": uuid.uuid4().hex,
            **fields,
        }
        self.sender(self.profile.node_id, command)
        return command

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise PermissionError("bench valve control is disabled")

    def _require_ready(self) -> None:
        self._require_enabled()
        if not self.started:
            raise RuntimeError("bench valve session has not started")
