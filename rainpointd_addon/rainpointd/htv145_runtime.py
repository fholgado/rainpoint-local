"""One durable HTV145 association per radio, with explicit close-only counter recovery.

The management route remains gated pending repeated dry RF qualification.
A positive exchange enrolls control independently of the six-row pairing log.
Startup and status never send actuator commands. Explicit or scheduled sync
waits for new owner telemetry before dispatching a close-only anchor.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from .htv145_control import Htv145ControlCoordinator, Htv145ControlProfile
from .htv145_counter_sync import Htv145CounterSync
from .valve_protocol import decode_htv145_state_report


class Htv145Runtime:
    def __init__(self, coordinator: Htv145ControlCoordinator,
                 node: Callable[[str], dict[str, Any]]) -> None:
        self.coordinator = coordinator
        self.node = node
        self.restored: dict[str, Any] = {}
        self.counter_sync = Htv145CounterSync(coordinator, self._ready_node)

    def profiles(self) -> list[Htv145ControlProfile]:
        return [self.coordinator.restored_profile(state)
                for state in self.coordinator.store.htv145_control_states()
                if state["report_ack_center_hz"] is not None]

    def _ready_node(self, profile: Htv145ControlProfile) -> dict[str, Any]:
        node = self.node(profile.node_id)
        if not (node.get("connected") is True and node.get("authenticated") is True
                and node.get("tx_armed") is not True
                and "htv145_report_ack_tx" in node.get("capabilities", [])
                and "htv145_control_tx_candidate" in node.get("capabilities", [])):
            raise RuntimeError("selected HTV145 control/ACK owner is unavailable")
        return node

    def enroll(self, profile: Htv145ControlProfile, *, command: bytes, response: bytes,
               idle: bytes, exchange_at: str, idle_at: str, now: str) -> dict[str, Any]:
        self._ready_node(profile)
        # Only the locally accepted selector-6 recipe is eligible. Historical
        # branch decoders remain available for offline capture analysis.
        if not (profile.command_marker_inverted and profile.trailer_residual == 0x4f03
                and profile.close_trailer_residual == 0x4f03 and profile.report_ack_center_hz):
            raise ValueError("HTV145 runtime requires the accepted selector-6 recipe")
        report = decode_htv145_state_report(idle, profile.link)
        if report is None or report["watering"]:
            raise ValueError("HTV145 enrollment requires an independent idle report")
        times = [datetime.fromisoformat(value) for value in (exchange_at, idle_at, now)]
        if any(value.tzinfo is None for value in times) or not times[0] <= times[1] <= times[2]:
            raise ValueError("HTV145 evidence timestamps are out of order")
        if (times[2] - times[1]).total_seconds() > 3600:
            raise ValueError("HTV145 idle evidence is stale")
        states = self.coordinator.store.htv145_control_states()
        if any(s["report_ack_center_hz"] is not None and
               (s["valve_endpoint"] == profile.valve_endpoint or s["node_id"] == profile.node_id)
               for s in states):
            raise RuntimeError("revoke existing HTV145 ownership before enrollment")
        previous = next((s for s in states if s["valve_endpoint"] == profile.valve_endpoint), None)
        if previous is not None:
            # Pre-ACK dry trials have no report owner to revoke. Preserve the
            # association and unresolved work, even when retiring an old trial.
            if (previous["controller_endpoint"] != profile.controller_endpoint or
                    previous["pending_command_id"] or previous["revocation_command_id"]):
                raise RuntimeError("legacy HTV145 trial must be settled on the same association before enrollment")
            if previous["node_id"] != profile.node_id:
                old_node = self.node(previous["node_id"])
                capabilities = old_node.get("capabilities")
                if not (old_node.get("connected") is True and old_node.get("authenticated") is True
                        and isinstance(capabilities, list)
                        and "htv145_control_tx_candidate" not in capabilities
                        and "htv145_report_ack_tx" not in capabilities):
                    raise RuntimeError("legacy HTV145 owner must have verified removal of control/ACK support")
            if (previous["last_command_started_at"] and
                    times[0] <= datetime.fromisoformat(previous["last_command_started_at"])):
                raise ValueError("HTV145 exchange predates the last local command")
        # Validate the entire exchange before persisting the owner.
        from .valve_protocol import decode_htv145_gateway_command, decode_htv145_command_response
        request = decode_htv145_gateway_command(command, profile.link)
        reply = decode_htv145_command_response(response, profile.link)
        if request is None or reply is None or any(request[k] != reply[k] for k in
                ("sequence", "watering", "command_marker_inverted")) or not reply["command_marker_inverted"]:
            raise ValueError("HTV145 enrollment requires a matching positive exchange")
        self.coordinator.configure(profile, observed_at=now)
        self.coordinator.synchronize_from_exchange(profile, command, response, observed_at=exchange_at)
        self.coordinator.observe_frame(profile, idle, observed_at=idle_at)
        self.restore(profile, now=now)
        return self.status(profile, now=now)

    def restore(self, profile: Htv145ControlProfile, *, now: str) -> None:
        node = self._ready_node(profile)
        epoch = (node.get("connected_at"), node.get("firmware_version"))
        if self.restored.get(profile.valve_endpoint) == epoch:
            return
        status = self.coordinator.readiness(profile, observed_at=now)
        if status["state"]["revocation_command_id"]:
            raise RuntimeError("HTV145 ownership revocation is pending")
        self.coordinator.start(profile, observed_at=now)
        self.restored[profile.valve_endpoint] = epoch

    def status(self, profile: Htv145ControlProfile, *, now: str) -> dict[str, Any]:
        result = self.coordinator.readiness(profile, observed_at=now)
        try:
            self._ready_node(profile)
            available = True
        except RuntimeError:
            available = False
        result.update(owner_available=available, ready=result["ready"] and available,
                      pairing_terminal_step_required=False, qualification="dry_selector6")
        result["counter_sync"] = self.counter_sync.status(profile, now=now)
        return result

    def restore_retained_counter(self, profile: Htv145ControlProfile, *, now: str) -> dict[str, Any]:
        """Explicitly reload known state into the owner; never transmit an RF probe."""
        status = self.status(profile, now=now)
        if not status["ready"]:
            raise RuntimeError("counter restore requires a known counter, fresh idle state and available owner")
        commands = self.coordinator.start(profile, observed_at=now)
        return {"state": "retained_counter_restore_requested",
                "next_sequence": status["next_sequence"],
                "command_id": commands[-1]["command_id"], "rf_transmitted": False}

    def request(self, profile: Htv145ControlProfile, action: str, *, now: str,
                duration_seconds: int | None = None) -> dict[str, Any]:
        self.restore(profile, now=now)
        status = self.status(profile, now=now)
        if status["state"]["revocation_command_id"]:
            raise RuntimeError("HTV145 ownership revocation is pending")
        if action == "open":
            if not status["ready"]:
                raise RuntimeError("HTV145 is not ready; inspect counter/state/owner status")
            return self.coordinator.request_open(profile, duration_seconds=duration_seconds, started_at=now)
        if action == "close":
            if status["fresh_state"] and status["state"]["confirmed_watering"] is False:
                return {"type": "htv145_control_noop", "reason": "already_idle"}
            return self.coordinator.request_close(profile, started_at=now)
        raise ValueError("unsupported HTV145 control action")

    def revoke(self, profile: Htv145ControlProfile) -> None:
        self._ready_node(profile)
        state = self.coordinator.store.htv145_control_states(profile.valve_endpoint)[0]
        if state["pending_command_id"]:
            raise RuntimeError("cannot revoke HTV145 owner while command pending")
        # No second owner can be configured until revocation is confirmed by
        # the node. The gateway keeps the profile until that status arrives.
        command = self.coordinator._command("htv145_control_revoke",
            controller_endpoint=profile.controller_endpoint, valve_endpoint=profile.valve_endpoint)
        self.coordinator.store.reserve_htv145_revocation(profile.valve_endpoint, command["command_id"])
        self.coordinator.sender(profile.node_id, command)

    def observe_node(self, node_id: str, message: dict[str, Any], *, now: str) -> None:
        for profile in self.profiles():
            if profile.node_id != node_id:
                continue
            state = self.coordinator.store.htv145_control_states(profile.valve_endpoint)[0]
            if (state["revocation_command_id"] and message.get("command_id") == state["revocation_command_id"] and
                    message.get("state") == "revoked" and
                    message.get("controller_endpoint") == profile.controller_endpoint and
                    message.get("valve_endpoint") == profile.valve_endpoint):
                self.coordinator.store.delete_htv145_control(profile.valve_endpoint)
                self.restored.pop(profile.valve_endpoint, None)
                return
            try:
                self.coordinator.observe_candidate_status(profile, message, observed_at=now)
            except (KeyError, ValueError):
                pass

    def observe_counter_sync_report(self, frame: bytes, node_id: str | None, *, now: str) -> None:
        # Run before cross-radio deduplication: only the assigned owner can
        # authorize the anchor, even if a neighboring receiver reported first.
        for profile in self.profiles():
            try:
                self.counter_sync.observe(profile, frame, node_id, now=now)
            except (KeyError, ValueError, RuntimeError, PermissionError, ConnectionError):
                pass

    def observe_frame(self, frame: bytes, *, now: str) -> None:
        for profile in self.profiles():
            try:
                self.coordinator.observe_frame(profile, frame, observed_at=now)
            except (KeyError, ValueError):
                pass

    def tick(self, *, now: str) -> None:
        for profile in self.profiles():
            self.coordinator.readiness(profile, observed_at=now)
            try:
                self.restore(profile, now=now)
                self.counter_sync.tick(profile, now=now)
            except (RuntimeError, ConnectionError, ValueError, PermissionError):
                self.restored.pop(profile.valve_endpoint, None)
