"""Explicit two-run phase experiment on an existing valve association."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from .valve_phase_trial import KEY, PhaseTrialJournal, assert_node_available, packet, timestamp
from .storage import HTV405_ACTIVE_TRANSACTION_STATES

CAPABILITY = "valve_phase_trial"


def records(gateway):
    return json.loads(gateway._store.metadata_value(KEY) or "{}") if gateway._store else {}


def eligible(gateway, device_id, now):
    if gateway._store is None or gateway._node_command_sender is None:
        raise RuntimeError("persistent registry and authenticated node transport required")
    registration = next((r for r in gateway._store.valve_registry() if r["device_id"] == device_id), None)
    if not registration or registration["model"] not in ("HTV145FRF", "HTV405FRF"):
        raise ValueError("select an existing one- or four-zone association")
    node_id = registration.get("control_node_id")
    device = gateway._devices.get(device_id, {})
    state = device.get("state", {})
    if registration["model"] == "HTV145FRF":
        profile = gateway._htv145_profile_for_device(device)
        if profile is None or not profile.command_marker_inverted or profile.invert:
            raise ValueError("trial requires the qualified odd-open one-zone profile")
        node_id = profile.node_id
        retained = gateway._store.htv145_control_states(profile.storage_key)[0]
        counter = retained.get("next_sequence")
        if not retained.get("counter_synchronized") or retained.get("pending_command_id") or retained.get("revocation_command_id"):
            raise ValueError("one-zone counter must be synchronized and idle")
        if gateway._store.htv145_counter_sync(profile.storage_key).get("state") in ("waiting_for_report", "syncing"):
            raise ValueError("one-zone counter recovery is queued")
        storage_key = profile.storage_key
        endpoints = [profile.controller_endpoint, profile.valve_endpoint]
        latest_send = retained.get("last_command_started_at")
        next_counter = counter & 31 if type(counter) is int else None
        idle = state.get("is_watering") is False
    else:
        if (registration.get("control_pending_command_id") or registration.get("control_recovery_sequence") is not None
                or registration.get("control_transaction_state") in HTV405_ACTIVE_TRANSACTION_STATES):
            raise ValueError("four-zone control or recovery is unresolved")
        storage_key = registration["valve_endpoint"]
        endpoints = [registration["valve_endpoint"], registration.get("control_companion_endpoint")]
        latest_send = registration.get("control_last_command_started_at")
        next_counter = registration.get("control_next_sequence")
        idle = all(state.get(f"zone_{p}_is_watering") is False for p in range(1, 5))
    node = next((n for n in gateway.nodes() if n["node_id"] == node_id), {})
    if not (node.get("managed") and node.get("connected") and node.get("authenticated")
            and node.get("tx_armed") is not True and CAPABILITY in node.get("capabilities", [])):
        raise ValueError("association owner requires the signed phase-trial firmware")
    seen = device.get("observed_at") or device.get("last_seen")
    if (not device.get("available") or not idle or not seen or
            not 0 <= (timestamp(now)-timestamp(seen)).total_seconds() <= 3600):
        raise ValueError("trial requires independent fresh idle on the selected valve")
    if gateway.pairing().get("active") or gateway._ack_ownership.snapshot():
        raise ValueError("pairing or ownership changes are active")
    return dict(device_id=device_id, model=registration["model"], node_id=node_id,
                endpoints=endpoints, storage_key=storage_key, next_counter=next_counter,
                latest_send=latest_send)


def act(gateway, action, request, *, now=None):
    observed = (now or datetime.now(timezone.utc)).isoformat()
    with gateway._lock:
        if action == "prepare":
            selected = eligible(gateway, request.get("device_id"), observed)
            port=request.get("port",1)
            if type(port) is not int or not 1 <= port <= (4 if selected["model"]=="HTV405FRF" else 1):
                raise ValueError("invalid trial port for model")
            node=next(n for n in gateway.nodes() if n["node_id"]==selected["node_id"])
            if port!=1 and "valve_phase_trial_ports" not in node.get("capabilities",[]):
                raise ValueError("signed multi-port trial firmware required")
            assert_node_available(gateway._store, selected["node_id"])
            baseline_at = request.get("baseline_observed_at")
            if (not baseline_at or timestamp(baseline_at) > timestamp(observed)
                    or (selected["latest_send"] and timestamp(baseline_at) < timestamp(selected["latest_send"]))):
                raise ValueError("baseline must follow the latest production transmission")
            command = packet(request.get("request_frame"))
            response = packet(request.get("response_frame"))
            if (not command or not response or
                    [command[0][5:9].hex(), command[0][9:13].hex()] != selected["endpoints"]
                    or (command[2]+1)//2 != selected["next_counter"]):
                raise ValueError("baseline does not match the retained association and counter")
            route = [response[0][5:9].hex(), response[0][9:13].hex()]
            key = PhaseTrialJournal(gateway._store).prepare(
                authorization_id=request.get("authorization_id"), model=selected["model"],
                node_id=selected["node_id"], request_frame=request.get("request_frame"),
                response_frame=request.get("response_frame"), report_route=route,
                selector=request.get("selector"), evidence_id=request.get("evidence_id"),
                now=observed, expires_at=(timestamp(observed)+timedelta(minutes=15)).isoformat(),
                admission=selected, port=port)
            return public(PhaseTrialJournal(gateway._store).snapshot(key), key)
        key = request.get("authorization_id")
        journal = PhaseTrialJournal(gateway._store)
        record = journal.snapshot(key)
        if action == "status":
            journal.expire(key, now=observed)
            return public(journal.snapshot(key), key)
        selected = eligible(gateway, record["identity"]["admission"]["device_id"], observed)
        admitted = record["identity"]["admission"]
        if any(selected[k] != admitted[k] for k in ("node_id", "model", "endpoints", "storage_key")):
            raise ValueError("trial association changed")
        if action == "recover":
            from .valve_phase_recovery import evidence_for
            node = next(n for n in gateway.nodes() if n["node_id"] == selected["node_id"])
            if "valve_phase_trial_recovery" not in node.get("capabilities", []):
                raise ValueError("signed recovery firmware required")
            if selected["latest_send"] != admitted["latest_send"]:
                raise ValueError("production transmission changed during trial")
            evidence = evidence_for(gateway, record, request.get("event_ids"), observed)
            record = gateway._store.recover_valve_phase_trial(key, evidence=evidence, observed_at=observed)
            command = dict(type="valve_phase_trial_recover", command_id=record["recovery"]["command_id"],
                authorization_id=key, attempted_command_id=record["transactions"][0]["command_id"],
                model=selected["model"], endpoint_a=selected["endpoints"][0], endpoint_b=selected["endpoints"][1])
            for label, item in evidence.items():
                command[label+"_frame"] = item["frame"]
                command[label+"_age_ms"] = item["age_ms"]
            gateway._node_command_sender(selected["node_id"], command)
            return public(journal.snapshot(key), key)
        if action == "open":
            port=record["identity"].get("port",1)
            node=next(n for n in gateway.nodes() if n["node_id"]==selected["node_id"])
            if port!=1 and "valve_phase_trial_ports" not in node.get("capabilities",[]):
                raise ValueError("signed multi-port trial firmware required")
            # Ordinary four-zone telemetry deliberately invalidates its legacy
            # counter on an unreserved open. Keep that behavior: the journal,
            # not telemetry, owns experimental phases until atomic release.
            telemetry_invalidated = (selected["model"] == "HTV405FRF"
                and selected["next_counter"] is None and record["state"] == "between_runs"
                and len(record["transactions"]) == 1
                and all(record["transactions"][0].get(k) for k in ("ack_at", "watering_at", "idle_at")))
            if (selected["latest_send"] != admitted["latest_send"] or
                    (selected["next_counter"] != admitted["next_counter"] and not telemetry_invalidated)):
                raise ValueError("production counter changed during trial")
            tx = journal.reserve(key, now=observed)
            command = dict(type="valve_phase_trial_open", command_id=tx["command_id"],
                authorization_id=key, model=selected["model"], endpoint_a=selected["endpoints"][0],
                endpoint_b=selected["endpoints"][1], phase=tx["phase"],
                ordinal=len(journal.snapshot(key)["transactions"]), seconds=60,
                selector=record["identity"]["selector"], port=port)
            journal.dispatch(key, tx, now=observed,
                sender=lambda *_: gateway._node_command_sender(selected["node_id"], command))
        elif action == "release":
            record = gateway._store.release_valve_phase_trial(key, observed_at=observed)
            gateway._node_command_sender(selected["node_id"], dict(type="valve_phase_trial_release",
                command_id=record["release_command_id"], authorization_id=key,
                model=selected["model"], endpoint_a=selected["endpoints"][0], endpoint_b=selected["endpoints"][1]))
        else:
            raise ValueError("unsupported phase-trial action")
        return public(journal.snapshot(key), key)


def public(record, key):
    return dict(authorization_id=key, state=record["state"],
                runs=len(record["transactions"]), maximum_runs=2, seconds_per_run=60,
                next_phase=record["next_phase"], failure=record.get("failure"))


def observe(gateway, node_id, message):
    with gateway._lock:
        key = message.get("authorization_id")
        record = records(gateway).get(key)
        if not record or record["identity"]["node_id"] != node_id:
            return
        journal = PhaseTrialJournal(gateway._store)
        if message.get("stage") == 7:
            journal.acknowledge_recovery(key, node_id=node_id, phase=message.get("phase"),
                                         command_id=message.get("command_id"))
        elif message.get("stage") == 6:
            journal.acknowledge_release(key, node_id=node_id, phase=message.get("phase"))
        elif message.get("stage") == 5:
            journal.fail(key, "radio_trial_failed")
        elif isinstance(message.get("frame"), str):
            journal.observe(key, node_id=node_id, frame=message["frame"],
                            observed_at=datetime.now(timezone.utc).isoformat())
        gateway.update_node(node_id, valve_phase_trial=public(journal.snapshot(key), key))


def authorize_send(gateway, node_id, message):
    kind = message.get("type", "")
    if kind.startswith("valve_phase_trial_"):
        return
    if (kind == "pairing_start" or kind.startswith("valve_control_") or
            kind.startswith("htv145_control_") and kind not in ("htv145_control_configure", "htv145_control_status")):
        assert_node_available(gateway._store, node_id)
