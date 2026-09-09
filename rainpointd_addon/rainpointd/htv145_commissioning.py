"""Device-based onboarding, separate from normal watering and RF research.

Only accepted pairing supplies the association/owner. Explicit consent permits
two bounded tests, each requiring positive RF evidence. Polling never retries a
reserved action; closing the flow or restarting interrupts the test sequence.
"""
from dataclasses import asdict
from datetime import datetime, timedelta
import json
import uuid

from .htv145_control import Htv145ControlProfile

# Qualified selector-6 control and report-ACK tune, distinct from assignment TX.
# See htv145_custom_identity_first_open_20260908.json; no household identity.
CONTROL_CENTER_HZ = 434_398_811
REPORT_ACK_CENTER_HZ = 433_518_905
FINISHED = {"awaiting_consent", "complete", "failed", "interrupted"}


class Htv145Commissioning:
    def __init__(self, runtime):
        self.runtime = runtime
        self.store = runtime.coordinator.store
        self.epoch = uuid.uuid4().hex

    def _load(self, device_id):
        return json.loads(self.store.metadata_value(f"htv145_commissioning:{device_id}") or "{}")

    def _save(self, data):
        self.store.set_metadata_value(f"htv145_commissioning:{data['device_id']}", json.dumps(data))
        return data

    def record_pairing(self, registration, node_id, command_id):
        """Called only after command-scoped valve-originated pairing evidence."""
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
                "pairing_command_id": command_id, "state": "awaiting_consent",
                "reason": "paired_control_test_required"}
        if any(p.controller_endpoint != profile.controller_endpoint and
               (p.valve_endpoint == profile.valve_endpoint or p.node_id == profile.node_id)
               for p in self.runtime.profiles()):
            # The current runtime has one single-zone slot per controller/node.
            # Never overwrite another physical valve's qualification or owner.
            data.update(state="failed", reason="single_valve_capacity_in_use")
            return self._save(data)
        # Invalidate qualification, not counters by inference. Existing ACK
        # ownership must still be explicitly revoked and confirmed before moving.
        self.store.save_htv145_qualification(profile.valve_endpoint,
            {"state": "awaiting_consent", "reason": data["reason"], "profile": asdict(profile)})
        return self._save(data)

    def _fail(self, data, reason, *, state="failed"):
        data.update(state=state, reason=reason)
        q = self.store.htv145_qualification(data["profile"]["valve_endpoint"])
        if q and q.get("profile") == data["profile"] and q.get("state") != "complete":
            self.runtime.qualification._fail(q, reason, state=state)
        return self._save(data)

    def status(self, registration, *, now):
        data = self._load(registration["device_id"])
        if not data:
            return {"state": "not_required", "reason": "no_pending_onboarding"}
        profile = data["profile"]
        if (registration["model"] != "HTV145FRF" or
                registration["valve_endpoint"] != profile["controller_endpoint"] or
                registration["controller_endpoint"] != profile["valve_endpoint"]):
            return self._fail(data, "association_changed")
        qualification = self.store.htv145_qualification(profile["valve_endpoint"])
        if (data["state"] == "verifying" and qualification.get("profile") == profile
                and qualification.get("state") == "complete"):
            data.update(state="complete", reason=qualification["reason"])
            return self._save(data)
        if data["state"] not in FINISHED:
            if data.get("epoch") != self.epoch:
                return self._fail(data, "gateway_restarted", state="interrupted")
            if datetime.fromisoformat(now) >= datetime.fromisoformat(data["deadline"]):
                return self._fail(data, "commissioning_expired")
        return data

    def act(self, registration, action, *, now, consent=False):
        data = self.status(registration, now=now)
        if action == "status":
            return data
        if data["state"] == "not_required":
            raise ValueError("device has no pending onboarding")
        profile = Htv145ControlProfile(**data["profile"])
        if action == "cancel":
            if data["state"] not in FINISHED:
                return self._fail(data, "user_cancelled", state="interrupted")
            return data
        if action == "begin":
            if consent is not True:
                raise ValueError("explicit test-watering consent required")
            if data["state"] != "awaiting_consent":
                raise RuntimeError("test already started; inspect its outcome before re-pairing")
            node = self.runtime._ready_node(profile)
            if "htv145_commissioning" not in node.get("capabilities", []):
                raise RuntimeError("update the selected radio firmware before testing")
            data.update(state="releasing_previous_owner", reason="confirming_ack_ownership",
                        epoch=self.epoch, consent_at=now, node_epoch=node.get("connected_at"),
                        deadline=(datetime.fromisoformat(now) + timedelta(minutes=15)).isoformat())
            self._save(data)
        elif action != "advance":
            raise ValueError("unsupported commissioning action")
        if data["state"] in FINISHED:
            return data
        try:
            node = self.runtime._ready_node(profile)
            if node.get("connected_at") != data["node_epoch"]:
                return self._fail(data, "owner_reconnected", state="interrupted")
            if data["state"] == "releasing_previous_owner":
                conflicts = [p for p in self.runtime.profiles() if
                             p.controller_endpoint == profile.controller_endpoint or
                             p.valve_endpoint == profile.valve_endpoint or p.node_id == profile.node_id]
                if conflicts:
                    for old in conflicts:
                        if old.controller_endpoint != profile.controller_endpoint:
                            return self._fail(data, "radio_or_gateway_already_owns_another_single_valve")
                        state = self.store.htv145_control_states(old.valve_endpoint)[0]
                        if not state["revocation_command_id"]:
                            self.runtime.revoke(old)
                    return data
                self.runtime.qualification.prepare(profile, now=now)
                data.update(state="verifying", reason="waiting_for_fresh_idle")
                return self._save(data)
            q = self.runtime.qualification.status(profile, now=now)
            if q["state"] == "complete":
                data.update(state="complete", reason=q["reason"])
                return self._save(data)
            if q["state"] == "failed" and q.get("reason") == "idle_anchor_failed" and not q.get("bootstrap_attempted"):
                # Fixed first-open initialization is not counter guessing. It
                # is attempted once, after explicit consent and a failed anchor.
                state = self.runtime.coordinator.readiness(profile, observed_at=now)["state"]
                previous = state.get("last_command_started_at")
                if previous and (datetime.fromisoformat(now) - datetime.fromisoformat(previous)).total_seconds() < 20:
                    data.update(reason="waiting_for_command_interval")
                    return self._save(data)
                q = self.runtime.qualification.bootstrap(profile, now=now, commissioning=True)
            elif q["state"] in {"failed", "interrupted"}:
                return self._fail(data, q["reason"], state=q["state"])
            elif q["state"] in {"ready_for_automatic_stop_test", "ready_for_early_stop_test"}:
                state = self.runtime.coordinator.readiness(profile, observed_at=now)["state"]
                previous = state.get("last_command_started_at")
                if not previous or (datetime.fromisoformat(now) - datetime.fromisoformat(previous)).total_seconds() >= 20:
                    q = self.runtime.qualification.action(profile, "open", now=now)
            elif q["state"] == "watering" and q["open_count"] == 2:
                if (datetime.fromisoformat(now) - datetime.fromisoformat(q["open_started_at"])).total_seconds() >= 20:
                    q = self.runtime.qualification.action(profile, "close", now=now)
            data.update(reason=q["state"], qualification_state=q["state"])
            return self._save(data)
        except (RuntimeError, ValueError, ConnectionError, PermissionError, KeyError) as err:
            self._fail(data, str(err))
            raise
