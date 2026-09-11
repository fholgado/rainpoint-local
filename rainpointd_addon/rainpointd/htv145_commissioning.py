"""Configure an accepted single-zone association without test watering.

Provision one ACK owner; confirm revocation before moving it. Confirmed fresh
pairing initializes the first command counter, separately from response evidence.
The optional research qualification harness remains separate from onboarding.
"""
from dataclasses import asdict
from datetime import datetime, timedelta
import json

from .htv145_control import Htv145ControlProfile
from .valve_protocol import decode_htv145_state_report

CONTROL_CENTER_HZ = 434_398_811
REPORT_ACK_CENTER_HZ = 433_518_905
FINISHED = {"awaiting_setup", "ready", "complete", "failed", "interrupted"}


class Htv145Commissioning:
    def __init__(self, runtime):
        self.runtime = runtime
        self.store = runtime.coordinator.store

    def _load(self, device_id):
        return json.loads(self.store.metadata_value(f"htv145_commissioning:{device_id}") or "{}")

    def _save(self, data):
        self.store.set_metadata_value(f"htv145_commissioning:{data['device_id']}", json.dumps(data))
        return data

    def record_pairing(self, registration, node_id, command_id, *, observed_at=None, frame=None):
        """Only command-scoped valve-originated pairing evidence enters here."""
        old = self._load(registration["device_id"])
        if old.get("pairing_command_id") == command_id:
            return old
        profile = Htv145ControlProfile(node_id=node_id,
            controller_endpoint=registration["valve_endpoint"],
            valve_endpoint=registration["controller_endpoint"],
            center_hz=CONTROL_CENTER_HZ, power_dbm=10, invert=False,
            trailer_residual=0x4f03, command_marker_inverted=True,
            report_ack_center_hz=REPORT_ACK_CENTER_HZ)
        data = {"device_id": registration["device_id"], "profile": asdict(profile),
                "pairing_command_id": command_id, "state": "awaiting_setup",
                "reason": "paired_owner_setup_required"}
        # Only the active command-scoped pairing acceptance caller supplies this
        # evidence. Old onboarding records, boot reports and status reads cannot
        # acquire a seed retroactively. The seed is spent atomically with SQL.
        if observed_at is not None and frame is not None:
            stamp = datetime.fromisoformat(observed_at)
            report = decode_htv145_state_report(bytes.fromhex(frame), profile.link)
            if stamp.tzinfo is None or report is None:
                raise ValueError("pairing initialization requires matching timestamped valve evidence")
            data.update(counter_seed_state="pending", pairing_confirmed_at=observed_at,
                        pairing_report_frame=frame)
        other_owners = [p for p in self.runtime.profiles()
                        if p.controller_endpoint != profile.controller_endpoint and p.node_id == profile.node_id]
        capacity = 8 if "htv145_multi_valve" in self.runtime.node(node_id).get("capabilities", []) else 1
        if len(other_owners) >= capacity:
            data.update(state="failed", reason="single_valve_capacity_in_use")
            return self._save(data)
        self.store.save_htv145_qualification(profile.storage_key,
            {"state": "awaiting_setup", "reason": data["reason"], "profile": asdict(profile)})
        return self._save(data)

    def status(self, registration, *, now):
        data = self._load(registration["device_id"])
        if not data:
            return {"state": "not_required", "reason": "no_pending_onboarding"}
        profile = data["profile"]
        if (registration["model"] != "HTV145FRF" or
                registration["valve_endpoint"] != profile["controller_endpoint"] or
                registration["controller_endpoint"] != profile["valve_endpoint"]):
            data.update(state="failed", reason="association_changed")
            return self._save(data)
        # Retire the old automatic watering experiment without replaying it.
        if data["state"] in {"awaiting_consent", "verifying"} or (
                data["state"] == "releasing_previous_owner" and not data.get("setup_only")):
            data.update(state="awaiting_setup", reason="paired_owner_setup_required")
            return self._save(data)
        if data["state"] not in FINISHED and datetime.fromisoformat(now) >= datetime.fromisoformat(data["deadline"]):
            data.update(state="failed", reason="setup_expired")
            return self._save(data)
        return data

    def act(self, registration, action, *, now, consent=False):
        data = self.status(registration, now=now)
        if action == "status" or data["state"] in {"not_required", "ready", "complete"}:
            return data
        if action == "cancel":
            if data["state"] not in FINISHED:
                data.update(state="interrupted", reason="user_cancelled")
                self._save(data)
            return data
        # Old clients' begin now performs setup only; it never starts experiments.
        if action in {"enable", "begin"}:
            if data["state"] in {"awaiting_setup", "failed", "interrupted"}:
                if data.get("reason") in {"association_changed", "single_valve_capacity_in_use"}:
                    raise RuntimeError(data["reason"])
                data.update(state="configuring" if data.get("profile_configured") else "releasing_previous_owner",
                            reason="confirming_ack_ownership",
                            setup_only=True,
                            deadline=(datetime.fromisoformat(now) + timedelta(minutes=5)).isoformat())
                self._save(data)
        elif action != "advance":
            raise ValueError("unsupported commissioning action")
        if data["state"] in FINISHED:
            return data
        profile = Htv145ControlProfile(**data["profile"])
        self.runtime._ready_node(profile)
        if data["state"] == "releasing_previous_owner":
            conflicts = [p for p in self.runtime.profiles() if
                         p.controller_endpoint == profile.controller_endpoint]
            for old in conflicts:
                if old.controller_endpoint != profile.controller_endpoint:
                    raise RuntimeError("radio_or_gateway_already_owns_another_single_valve")
                state = self.store.htv145_control_states(old.storage_key)[0]
                if state["pending_command_id"]:
                    raise RuntimeError("finish the pending valve command before setup")
                if not state["revocation_command_id"]:
                    self.runtime.revoke(old)
            if conflicts:
                return data
            data.update(state="configuring", reason="configuring_ack_owner")
            self._save(data)
        # Repeated setup preserves the durable reservation and never re-seeds it.
        existing = self.store.htv145_control_states(profile.storage_key)
        if existing:
            if self.runtime.coordinator.restored_profile(existing[0]) != profile:
                raise RuntimeError("association_changed_during_setup")
        else:
            self.runtime.coordinator.configure(profile, observed_at=now)
        data["profile_configured"] = True
        self._save(data)
        self.store.initialize_htv145_pairing_counter(
            device_id=registration["device_id"], pairing_command_id=data["pairing_command_id"],
            observed_at=now)
        data = self._load(registration["device_id"])
        # Restore observed physical state independently; never infer idle from
        # pairing or from an outbound sync/configure message.
        if data.get("counter_seed_state") == "applied":
            current = self.store.htv145_control_states(profile.storage_key)[0]
            if current["confirmed_at"] is None and not current["pending_command_id"]:
                self.runtime.coordinator.observe_frame(profile,
                    bytes.fromhex(data["pairing_report_frame"]), observed_at=data["pairing_confirmed_at"])
        self.runtime.restore(profile, now=now)
        self.store.save_htv145_qualification(profile.storage_key, {
            "state": "enabled", "reason": "accepted_pairing_owner_configured",
            "profile": asdict(profile), "physical_verification": "user_check_recommended"})
        data.update(state="ready", reason="owner_configured")
        return self._save(data)
