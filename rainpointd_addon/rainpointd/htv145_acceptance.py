"""Auditable, disabled-by-default HTV145 dry-valve acceptance harness.

The harness is not connected to Home Assistant valve entities. Its private
research route requires the add-on's management token plus an explicit runtime
gate. It performs one duration-bounded logical open, records every decision,
and accepts success only after positive open evidence followed by an
independent idle report.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

from .htv145_control import Htv145ControlCoordinator, Htv145ControlProfile


class Htv145DryValveAcceptance:
    """Coordinate one real, dry HTV145 command and retain an audit transcript."""

    def __init__(
        self,
        *,
        coordinator: Htv145ControlCoordinator,
        profile: Htv145ControlProfile,
        enabled: bool = False,
        idle_grace_seconds: int = 30,
    ) -> None:
        if idle_grace_seconds < 0 or idle_grace_seconds > 300:
            raise ValueError("idle grace must be between 0 and 300 seconds")
        self.coordinator = coordinator
        self.profile = profile
        self.enabled = enabled
        self.idle_grace_seconds = idle_grace_seconds
        self._audit: list[dict[str, Any]] = []
        self._prepared = False
        self._command_id: str | None = None
        self._expected_idle_at: str | None = None
        self._open_confirmed_at: str | None = None
        self._idle_confirmed_at: str | None = None

    def prepare(
        self,
        *,
        idle_frame: bytes,
        passive_command_frame: bytes,
        observed_at: str,
        idle_observed_at: str | None = None,
        passive_command_observed_at: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Select/configure the node and authenticate the outbound counter."""
        self._require_enabled()
        if self._prepared or self._command_id is not None:
            raise RuntimeError("HTV145 acceptance trial is already prepared")
        configured = self.coordinator.configure(
            self.profile, observed_at=observed_at
        )
        idle_evidence_at = idle_observed_at or observed_at
        command_evidence_at = passive_command_observed_at or observed_at
        idle = self.coordinator.observe_frame(
            self.profile, idle_frame, observed_at=idle_evidence_at
        )
        synchronized = self.coordinator.synchronize_from_passive_command(
            self.profile,
            passive_command_frame,
            observed_at=command_evidence_at,
        )
        node_commands = self.coordinator.start(
            self.profile, observed_at=observed_at
        )
        self._prepared = True
        self._record(
            "prepared",
            observed_at,
            selected_node_id=self.profile.node_id,
            counter_source=synchronized["counter_source"],
            next_sequence=synchronized["next_sequence"],
            confirmed_idle=idle["confirmed_watering"] is False,
            idle_evidence_at=idle_evidence_at,
            passive_command_evidence_at=command_evidence_at,
            node_command_types=[item["type"] for item in node_commands],
            profile=configured,
        )
        return node_commands

    def open_once(
        self, *, duration_seconds: int, started_at: str
    ) -> dict[str, Any]:
        """Dispatch exactly one logical duration-bounded open."""
        self._require_enabled()
        if not self._prepared:
            raise RuntimeError("HTV145 acceptance trial is not prepared")
        if self._command_id is not None:
            raise RuntimeError("HTV145 acceptance permits exactly one open")
        command = self.coordinator.request_open(
            self.profile,
            duration_seconds=duration_seconds,
            started_at=started_at,
        )
        self._command_id = str(command["command_id"])
        self._expected_idle_at = (
            datetime.fromisoformat(started_at)
            + timedelta(seconds=duration_seconds)
        ).isoformat()
        self._record(
            "open_dispatched",
            started_at,
            command_id=self._command_id,
            logical_dispatch_count=1,
            expected_sequence=command["expected_sequence"],
            duration_seconds=duration_seconds,
            expected_idle_at=self._expected_idle_at,
        )
        return command

    def observe_frame(self, frame: bytes, *, observed_at: str) -> dict[str, Any]:
        """Record positive valve evidence without inferring state from dispatch."""
        self._require_enabled()
        if self._command_id is None:
            raise RuntimeError("HTV145 open has not been dispatched")
        state = self.coordinator.observe_frame(
            self.profile, frame, observed_at=observed_at
        )
        watering = state["confirmed_watering"]
        if watering is True:
            self._open_confirmed_at = observed_at
            phase = "open_confirmed"
        elif watering is False and self._open_confirmed_at is not None:
            self._idle_confirmed_at = observed_at
            phase = "automatic_idle_confirmed"
        else:
            phase = "idle_observed_without_open_confirmation"
        self._record(
            phase,
            observed_at,
            confirmation_source=state.get("counter_source"),
            counter_synchronized=state["counter_synchronized"],
            next_sequence=state["next_sequence"],
            raw=frame.hex(),
        )
        return state

    def observe_candidate_status(
        self, message: dict[str, Any], *, observed_at: str
    ) -> dict[str, Any] | None:
        """Retain bounded-attempt diagnostics emitted by the selected node."""
        self._require_enabled()
        state = self.coordinator.observe_candidate_status(
            self.profile, message, observed_at=observed_at
        )
        if state is not None:
            watering = state.get("confirmed_watering")
            if watering is True:
                self._open_confirmed_at = observed_at
            elif watering is False and self._open_confirmed_at is not None:
                self._idle_confirmed_at = observed_at
        self._record(
            "candidate_status",
            observed_at,
            node_state=message.get("state"),
            failure_class=message.get("failure_class"),
            attempts_sent=message.get("attempts_sent"),
            matching_route_frames=message.get("matching_route_frames"),
            invalid_trailer_frames=message.get("invalid_trailer_frames"),
        )
        return state

    def report(self, *, finished_at: str) -> dict[str, Any]:
        """Return a self-contained acceptance verdict and immutable transcript."""
        expected = (
            datetime.fromisoformat(self._expected_idle_at)
            if self._expected_idle_at is not None
            else None
        )
        idle = (
            datetime.fromisoformat(self._idle_confirmed_at)
            if self._idle_confirmed_at is not None
            else None
        )
        automatic_idle_in_window = (
            expected is not None
            and idle is not None
            and expected <= idle <= expected + timedelta(
                seconds=self.idle_grace_seconds
            )
        )
        checks = {
            "selected_node_configured": self._prepared,
            "counter_synchronized_from_passive_command": any(
                item["event"] == "prepared"
                and item.get("counter_source") == "passive_stock_command"
                for item in self._audit
            ),
            "one_logical_open_dispatched": sum(
                item["event"] == "open_dispatched" for item in self._audit
            ) == 1,
            "open_confirmed_by_valve_evidence": self._open_confirmed_at is not None,
            "automatic_idle_confirmed_in_window": automatic_idle_in_window,
        }
        return {
            "schema_version": 1,
            "model": "HTV145FRF",
            "finished_at": finished_at,
            "selected_node_id": self.profile.node_id,
            "command_id": self._command_id,
            "expected_idle_at": self._expected_idle_at,
            "open_confirmed_at": self._open_confirmed_at,
            "idle_confirmed_at": self._idle_confirmed_at,
            "checks": checks,
            "passed": all(checks.values()),
            "audit": deepcopy(self._audit),
        }

    def _record(self, event: str, observed_at: str, **fields: Any) -> None:
        self._audit.append({"event": event, "observed_at": observed_at, **fields})

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise PermissionError("HTV145 dry-valve acceptance is disabled")
