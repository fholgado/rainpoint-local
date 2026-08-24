"""Hardware-independent duration-bounded valve safety state machine.

This module emits symbolic actions only. It is deliberately not connected to
the HTTP API, serial transport, command frame builder, or radio hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SafetyState(str, Enum):
    BOOT = "boot"
    IDLE = "idle"
    OPEN_PENDING = "open_pending"
    RUN_UNCONFIRMED = "run_unconfirmed"
    WATERING = "watering"
    CLOSE_PENDING = "close_pending"
    UNKNOWN = "unknown"
    FAULT = "fault"


class ActionKind(str, Enum):
    SEND_OPEN = "send_open"
    SEND_CLOSE = "send_close"
    REPORT_FAULT = "report_fault"


@dataclass(frozen=True)
class SafetyAction:
    kind: ActionKind
    reason: str
    duration_seconds: int | None = None
    attempt: int | None = None
    zone: int | None = None


class ValveSafetyController:
    """Enforce bounded opens without speculative recovery transmissions."""

    def __init__(
        self,
        *,
        user_max_seconds: int,
        absolute_max_seconds: int = 3_600,
        acknowledgement_timeout_seconds: float = 1.5,
        completion_grace_seconds: float = 15.0,
        close_retry_seconds: float = 1.5,
        minimum_command_interval_seconds: float = 15.0,
        max_fast_close_attempts: int = 5,
        fault_retry_seconds: float = 10.0,
        zone_count: int = 1,
    ) -> None:
        if user_max_seconds <= 0:
            raise ValueError("user maximum must be positive")
        if absolute_max_seconds <= 0:
            raise ValueError("absolute maximum must be positive")
        if user_max_seconds > absolute_max_seconds:
            raise ValueError("user maximum cannot exceed absolute maximum")
        if (
            acknowledgement_timeout_seconds <= 0
            or completion_grace_seconds < 0
            or close_retry_seconds <= 0
        ):
            raise ValueError("timeouts must be positive")
        if minimum_command_interval_seconds < 0:
            raise ValueError("minimum command interval cannot be negative")
        if max_fast_close_attempts < 1 or fault_retry_seconds <= 0:
            raise ValueError("retry settings must be positive")
        if zone_count not in range(1, 5):
            raise ValueError("zone count must be between 1 and 4")

        self.user_max_seconds = user_max_seconds
        self.absolute_max_seconds = absolute_max_seconds
        self.acknowledgement_timeout_seconds = acknowledgement_timeout_seconds
        self.completion_grace_seconds = completion_grace_seconds
        self.close_retry_seconds = close_retry_seconds
        self.minimum_command_interval_seconds = minimum_command_interval_seconds
        self.max_fast_close_attempts = max_fast_close_attempts
        self.fault_retry_seconds = fault_retry_seconds
        self.zone_count = zone_count
        self.state = SafetyState.BOOT
        self.run_deadline: float | None = None
        self.completion_deadline: float | None = None
        self.acknowledgement_deadline: float | None = None
        self.next_close_attempt: float | None = None
        self.close_attempts = 0
        self.requested_zone: int | None = None
        self.last_command_at: float | None = None
        self.pending_close_reason: str | None = None

    def start(self, now: float) -> tuple[SafetyAction, ...]:
        """Start observation-only; a restart must never create RF traffic."""
        if self.state is not SafetyState.BOOT:
            raise RuntimeError("safety controller has already started")
        self.state = SafetyState.IDLE
        return ()

    def request_open(
        self, duration_seconds: int, now: float, *, zone: int = 1
    ) -> tuple[SafetyAction, ...]:
        """Arm one mutually exclusive zone before emitting an open action."""
        if self.state is not SafetyState.IDLE:
            raise RuntimeError(f"cannot open while state is {self.state.value}")
        if (
            self.last_command_at is not None
            and now
            < self.last_command_at + self.minimum_command_interval_seconds
        ):
            raise RuntimeError("minimum valve command interval has not elapsed")
        if zone not in range(1, self.zone_count + 1):
            raise ValueError(
                f"zone must be between 1 and {self.zone_count}"
            )
        if duration_seconds <= 0 or duration_seconds % 60:
            raise ValueError("duration must be a positive whole minute")
        maximum = min(self.user_max_seconds, self.absolute_max_seconds)
        if duration_seconds > maximum:
            raise ValueError(f"duration exceeds {maximum}-second safety limit")

        self.run_deadline = now + duration_seconds
        self.completion_deadline = (
            self.run_deadline + self.completion_grace_seconds
        )
        self.acknowledgement_deadline = (
            now + self.acknowledgement_timeout_seconds
        )
        self.state = SafetyState.OPEN_PENDING
        self.requested_zone = zone
        self.last_command_at = now
        return (
            SafetyAction(
                ActionKind.SEND_OPEN,
                "user_request",
                duration_seconds=duration_seconds,
                zone=zone,
            ),
        )

    def request_close(self, now: float) -> tuple[SafetyAction, ...]:
        """Begin an explicit early-stop sequence unless one is active."""
        if self.state is SafetyState.BOOT:
            self.start(now)
        if self.state in (SafetyState.CLOSE_PENDING, SafetyState.FAULT):
            return ()
        return self._begin_close(now, "user_request")

    def client_lost(self, now: float) -> tuple[SafetyAction, ...]:
        """Do nothing: the valve's transmitted duration bounds the run."""
        return ()

    def observe_valve(
        self, *, watering: bool, now: float
    ) -> tuple[SafetyAction, ...]:
        """Advance state only from observed valve state, not transmit success."""
        if not watering:
            self._clear_to_idle()
            return ()

        if self.state in (
            SafetyState.OPEN_PENDING,
            SafetyState.RUN_UNCONFIRMED,
        ):
            if self._completion_is_overdue(now):
                return self._begin_close(now, "overdue_watering_observed")
            self.state = SafetyState.WATERING
            self.acknowledgement_deadline = None
            return ()
        if self.state is SafetyState.WATERING:
            if self._completion_is_overdue(now):
                return self._begin_close(now, "overdue_watering_observed")
            return ()
        if self.state in (SafetyState.CLOSE_PENDING, SafetyState.FAULT):
            return ()
        if self.state is SafetyState.UNKNOWN and self._completion_is_overdue(
            now
        ):
            return self._begin_close(now, "overdue_watering_observed")
        self.state = SafetyState.UNKNOWN
        return (
            SafetyAction(
                ActionKind.REPORT_FAULT,
                "watering_observed_without_bounded_run_context",
            ),
        )

    def tick(self, now: float) -> tuple[SafetyAction, ...]:
        """Evaluate confirmation, bounded-run, and close-retry deadlines."""
        if (
            self.state is SafetyState.OPEN_PENDING
            and self.acknowledgement_deadline is not None
            and now >= self.acknowledgement_deadline
        ):
            # The open may have succeeded, but its requested duration already
            # bounds the run. Preserve that deadline and stop transmitting
            # until authenticated state restores the counter.
            self.state = SafetyState.RUN_UNCONFIRMED
            self.acknowledgement_deadline = None
            return (
                SafetyAction(
                    ActionKind.REPORT_FAULT,
                    "open_confirmation_missing_bounded_run",
                ),
            )
        if (
            self.state
            in (
                SafetyState.OPEN_PENDING,
                SafetyState.RUN_UNCONFIRMED,
                SafetyState.WATERING,
            )
            and self._completion_is_overdue(now)
        ):
            # A missing idle report is not proof that the bounded run failed
            # to stop. Mark it unknown; only a fresh positive watering report
            # after this point is evidence for an anomaly close.
            self.state = SafetyState.UNKNOWN
            self.acknowledgement_deadline = None
            return (
                SafetyAction(
                    ActionKind.REPORT_FAULT,
                    "bounded_run_completion_unobserved",
                ),
            )
        if (
            self.state in (SafetyState.CLOSE_PENDING, SafetyState.FAULT)
            and self.next_close_attempt is not None
            and now >= self.next_close_attempt
        ):
            return self._retry_close(now)
        return ()

    def _begin_close(
        self, now: float, reason: str
    ) -> tuple[SafetyAction, ...]:
        self.state = SafetyState.CLOSE_PENDING
        self.acknowledgement_deadline = None
        self.pending_close_reason = reason
        earliest = (
            self.last_command_at + self.minimum_command_interval_seconds
            if self.last_command_at is not None
            else now
        )
        if now < earliest:
            self.close_attempts = 0
            self.next_close_attempt = earliest
            return ()
        return self._emit_close(now, reason)

    def _emit_close(
        self, now: float, reason: str
    ) -> tuple[SafetyAction, ...]:
        self.close_attempts += 1
        self.last_command_at = now
        self.next_close_attempt = now + max(
            self.close_retry_seconds, self.minimum_command_interval_seconds
        )
        return tuple(
            SafetyAction(
                ActionKind.SEND_CLOSE,
                reason,
                attempt=self.close_attempts,
                zone=zone,
            )
            for zone in range(1, self.zone_count + 1)
        )

    def _retry_close(self, now: float) -> tuple[SafetyAction, ...]:
        reason = (
            self.pending_close_reason
            if self.close_attempts == 0 and self.pending_close_reason is not None
            else "close_not_confirmed"
        )
        actions = list(self._emit_close(now, reason))
        if (
            self.state is SafetyState.CLOSE_PENDING
            and self.close_attempts >= self.max_fast_close_attempts
        ):
            self.state = SafetyState.FAULT
            actions.append(
                SafetyAction(
                    ActionKind.REPORT_FAULT,
                    "valve_failed_to_confirm_idle",
                    attempt=self.close_attempts,
                )
            )
            self.next_close_attempt = now + max(
                self.fault_retry_seconds,
                self.minimum_command_interval_seconds,
            )
        elif self.state is SafetyState.FAULT:
            self.next_close_attempt = now + max(
                self.fault_retry_seconds,
                self.minimum_command_interval_seconds,
            )
        return tuple(actions)

    def _clear_to_idle(self) -> None:
        self.state = SafetyState.IDLE
        self.run_deadline = None
        self.completion_deadline = None
        self.acknowledgement_deadline = None
        self.next_close_attempt = None
        self.close_attempts = 0
        self.requested_zone = None
        self.pending_close_reason = None

    def _completion_is_overdue(self, now: float) -> bool:
        return (
            self.completion_deadline is not None
            and now >= self.completion_deadline
        )
