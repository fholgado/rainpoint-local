"""Dry first-control qualification, independent of public watering authority.

Pairing supplies the association, never a counter. One explicit request leases
the selected ACK owner and queues the existing close-only idle anchor. Separate
actions permit exactly two 60-second opens: automatic stop, then early stop.
Only positive command responses and independent idle reports complete the gate.
Persisted unfinished tests are interrupted on restart; no action is replayed.
"""
from dataclasses import asdict
from datetime import datetime, timedelta

from .valve_protocol import decode_htv145_command_response, decode_htv145_state_report


TERMINAL = {"complete", "failed", "interrupted", "awaiting_consent"}


class Htv145Qualification:
    def __init__(self, runtime):
        self.runtime = runtime
        self.store = runtime.coordinator.store
        for data in self.store.htv145_qualifications():
            if data["state"] not in TERMINAL:
                self._fail(data, "gateway_restarted", state="interrupted")

    def _save(self, data):
        self.store.save_htv145_qualification(data["profile"]["valve_endpoint"], data)

    def _fail(self, data, reason, *, state="failed"):
        data.update(state=state, reason=reason)
        endpoint = data["profile"]["valve_endpoint"]
        sync = self.store.htv145_counter_sync(endpoint)
        if sync.get("state") == "waiting_for_report":
            sync.update(state="cancelled", deadline=None, reason="qualification_stopped")
            self.store.save_htv145_counter_sync(endpoint, sync)
        self._save(data)
        return data

    def qualified(self, profile):
        data = self.store.htv145_qualification(profile.valve_endpoint)
        # Associations enrolled through the pre-existing positive-exchange path
        # retain their qualification. A new trial never inherits that authority.
        return not data or (data["state"] == "complete" and data["profile"] == asdict(profile))

    def prepare(self, profile, *, now):
        node = self.runtime._ready_node(profile)
        if "htv145_idle_anchor" not in node.get("capabilities", []):
            raise RuntimeError("qualification requires idle-anchor firmware")
        if not (profile.command_marker_inverted and profile.trailer_residual == 0x4f03
                and profile.close_trailer_residual == 0x4f03 and profile.report_ack_center_hz):
            raise ValueError("qualification requires the validated selector-6 recipe")
        for old in self.store.htv145_control_states():
            if (old["controller_endpoint"] == profile.controller_endpoint
                    or old["valve_endpoint"] == profile.valve_endpoint
                    or old["node_id"] == profile.node_id):
                raise RuntimeError("revoke existing control/ACK ownership before qualification")
        data = {"state": "waiting_for_idle", "reason": "new_owner_idle_required",
                "profile": asdict(profile), "started_at": now,
                "deadline": (datetime.fromisoformat(now) + timedelta(minutes=15)).isoformat(),
                "node_epoch": node.get("connected_at"), "open_count": 0,
                "automatic_stop_verified": False, "evidence": []}
        # Save the public-control block before provisioning any radio ownership.
        self._save(data)
        try:
            self.runtime.coordinator.configure(profile, observed_at=now)
            self.runtime.restore(profile, now=now)
            self.runtime.counter_sync.configure(profile, {"enabled": False}, now=now)
            self.runtime.counter_sync.request(profile, now=now, wait_seconds=600)
        except Exception:
            self._fail(data, "qualification_prepare_failed")
            raise
        return data

    def status(self, profile, *, now):
        data = self.store.htv145_qualification(profile.valve_endpoint)
        if not data or data["state"] in TERMINAL:
            return data
        if data["profile"] != asdict(profile):
            return self._fail(data, "association_changed")
        try:
            node = self.runtime._ready_node(profile)
        except RuntimeError:
            return self._fail(data, "owner_unavailable")
        if node.get("connected_at") != data["node_epoch"]:
            return self._fail(data, "owner_reconnected")
        if datetime.fromisoformat(now) >= datetime.fromisoformat(data["deadline"]):
            return self._fail(data, "qualification_expired")
        state = self.runtime.coordinator.readiness(profile, observed_at=now)["state"]
        if data["state"] == "waiting_for_idle":
            sync = self.store.htv145_counter_sync(profile.valve_endpoint)
            if sync.get("state") == "ready" and state["counter_synchronized"]:
                data.update(state="ready_for_automatic_stop_test", reason="idle_anchor_confirmed",
                            anchor_frame=sync.get("response_frame"))
                self._save(data)
            elif sync.get("state") in {"failed", "cancelled"}:
                return self._fail(data, "idle_anchor_failed")
        elif data["state"] in {"opening", "closing"} and not state["pending_command_id"]:
            return self._fail(data, "positive_command_response_not_observed")
        elif data["state"] in {"watering", "waiting_final_idle"}:
            if datetime.fromisoformat(now) > datetime.fromisoformat(data["open_started_at"]) + timedelta(seconds=90):
                return self._fail(data, "independent_idle_not_observed")
        return data

    def action(self, profile, action, *, now):
        data = self.status(profile, now=now)
        if not data or data["state"] in TERMINAL:
            raise RuntimeError("no active dry qualification")
        if action == "open":
            if data["state"] not in {"ready_for_automatic_stop_test", "ready_for_early_stop_test"} or data["open_count"] >= 2:
                raise RuntimeError("qualification is not ready for another open")
            if not self.runtime.coordinator.readiness(profile, observed_at=now)["ready"]:
                raise RuntimeError("qualification counter or idle state is not ready")
            data.update(state="opening", open_count=data["open_count"] + 1, open_started_at=now)
        elif action == "close":
            if (data["state"] != "watering" or data["open_count"] != 2
                    or (datetime.fromisoformat(now) - datetime.fromisoformat(data["open_started_at"])).total_seconds() < 15):
                raise RuntimeError("early close requires the second run and 15-second spacing")
            data.update(state="closing")
        else:
            raise ValueError("unsupported qualification action")
        self._save(data)
        try:
            coordinator = self.runtime.coordinator
            command = (coordinator.request_open(profile, duration_seconds=60, started_at=now)
                       if action == "open" else coordinator.request_close(profile, started_at=now))
        except Exception:
            self._fail(data, "command_dispatch_failed")
            raise
        data.update(command_id=command["command_id"], expected_sequence=command["expected_sequence"], command_started_at=now)
        self._save(data)
        return data

    def bootstrap(self, profile, *, now, commissioning=False):
        """One explicit dry trial of the captured first-open candidate, not a seed.

        Kept separate from normal opens and the close-only synchronization API.
        Experimental firmware must advertise support; no arbitrary counter,
        duration, automatic retry, or successful qualification is implied.
        """
        node = self.runtime._ready_node(profile)
        capability = "htv145_commissioning" if commissioning else "htv145_bootstrap_trial"
        if capability not in node.get("capabilities", []):
            raise RuntimeError("bootstrap requires explicitly enabled trial firmware")
        data = self.store.htv145_qualification(profile.valve_endpoint)
        if (not data or data["profile"] != asdict(profile) or data["state"] != "failed"
                or data["reason"] != "idle_anchor_failed" or data["open_count"] != 0
                or data.get("bootstrap_attempted")):
            raise RuntimeError("bootstrap requires an unused failed idle-anchor qualification")
        status = self.runtime.coordinator.readiness(profile, observed_at=now)
        if (not status["fresh_state"] or status["state"]["confirmed_watering"] is not False
                or status["state"]["pending_command_id"] or status["anomaly"]):
            raise RuntimeError("bootstrap requires fresh idle and no unresolved operation")
        data.update(state="opening", reason="unverified_first_open_trial", bootstrap_attempted=True,
                    open_count=1, open_started_at=now, command_started_at=now,
                    node_epoch=node.get("connected_at"),
                    deadline=(datetime.fromisoformat(now) + timedelta(minutes=15)).isoformat())
        self._save(data)
        try:
            command = self.runtime.coordinator.request_bootstrap_open(profile, started_at=now, commissioning=commissioning)
        except Exception:
            self._fail(data, "bootstrap_dispatch_failed")
            raise
        data.update(command_id=command["command_id"], expected_sequence=0x81)
        self._save(data)
        return data

    def observe(self, profile, frame, *, now):
        data = self.store.htv145_qualification(profile.valve_endpoint)
        if not data or data["state"] in TERMINAL or data["profile"] != asdict(profile):
            return
        stamp = datetime.fromisoformat(now)
        try:
            node = self.runtime._ready_node(profile)
        except RuntimeError:
            self._fail(data, "owner_unavailable")
            return
        if node.get("connected_at") != data["node_epoch"]:
            self._fail(data, "owner_reconnected")
            return
        if stamp >= datetime.fromisoformat(data["deadline"]):
            self._fail(data, "qualification_expired")
            return
        response = decode_htv145_command_response(frame, profile.link)
        if data["state"] in {"opening", "closing"} and response is not None:
            expected_watering = data["state"] == "opening"
            state = self.store.htv145_control_states(profile.valve_endpoint)[0]
            if (not state["counter_synchronized"] or state["pending_command_id"]
                    or response["sequence"] != data.get("expected_sequence")
                    or response["watering"] != expected_watering
                    or not response["command_marker_inverted"]
                    or not 0 <= (stamp - datetime.fromisoformat(data["command_started_at"])).total_seconds() <= 3.5
                    or (expected_watering and frame[27:30] != bytes.fromhex("9e0000"))):
                return
            data["evidence"].append({"action": "open" if expected_watering else "close", "frame": frame.hex(), "observed_at": now})
            if expected_watering and data.get("bootstrap_attempted") and data["open_count"] == 1:
                sync = self.store.htv145_counter_sync(profile.valve_endpoint)
                sync.update(state="ready", reason="positive_first_open_response", command_id=None,
                            deadline=None, last_success_at=now, response_frame=frame.hex())
                self.store.save_htv145_counter_sync(profile.valve_endpoint, sync)
            data.update(state="watering" if expected_watering else "waiting_final_idle", positive_response_at=now)
            self._save(data)
            return
        report = decode_htv145_state_report(frame, profile.link)
        if report is None or report["watering"] or data["state"] not in {"watering", "waiting_final_idle"}:
            return
        if stamp <= datetime.fromisoformat(data["positive_response_at"]):
            return
        elapsed = (stamp - datetime.fromisoformat(data["open_started_at"])).total_seconds()
        if data["state"] == "watering" and data["open_count"] == 1 and 60 <= elapsed <= 90:
            data.update(state="ready_for_early_stop_test", automatic_stop_verified=True)
        elif data["state"] == "waiting_final_idle" and data["automatic_stop_verified"] and elapsed < 60:
            data.update(state="complete", reason="positive_controls_and_independent_stops_verified", completed_at=now)
        else:
            self._fail(data, "unexpected_idle_timing")
            return
        data["evidence"].append({"action": "independent_idle", "frame": frame.hex(), "observed_at": now})
        self._save(data)
