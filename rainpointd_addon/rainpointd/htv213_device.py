"""HA projection for qualified canary and staged normal HTV213 associations.

The persisted reply owner supplies all RF parameters. HA supplies only an
outlet and duration; transport success never becomes reported watering. This
adapter admits committed, RF-confirmed enrollments independently of model-menu
visibility. Unpublished models can be qualified through the normal controls;
publishing the pairing profile remains a separate release decision.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

from . import htv213_owner as owner, htv213_control_transport as control
from .htv213_control import ControlJournal, wraps

MODEL = "HTV213FRF"
FRESH_SECONDS = 1200


def _age(value, now):
    try:
        stamp = datetime.fromisoformat(value)
        return (now - stamp).total_seconds() if stamp.tzinfo else float("inf")
    except (TypeError, ValueError):
        return float("inf")


def _find(gateway, device_id):
    return next(((key, record) for key, record in owner.records(gateway).items()
                 if record.get("device_id") == device_id and not record.get("revoking")), None)


def publish(gateway, request):
    """Make an already qualified, currently idle association visible to HA."""
    with gateway._lock:
        key = request.get("association_key")
        records = owner.records(gateway)
        record = records.get(key)
        if not record or record.get("revoking"):
            raise ValueError("active HTV213 reply ownership required")
        node = control.eligible(gateway, record["node_id"])
        if node.get("htv213_owner", {}).get("state") != "ready":
            raise ValueError("radio has not acknowledged retained ownership")
        now = datetime.now(timezone.utc)
        if any(record["ports"].get(str(port), {}).get("watering") is not False or
               not 0 <= _age(record["ports"][str(port)].get("observed_at"), now) <= FRESH_SECONDS
               for port in (1, 2)):
            raise ValueError("fresh valve-originated idle reports for both outlets required")
        journal = ControlJournal(gateway._store).snapshot(key)
        trials = journal["history"] + [journal["transaction"]]
        if (journal["state"] != "complete" or
                {tx["port"] for tx in trials if tx and tx["acknowledged"] and tx["summary"]} != {1, 2}
                or not any(tx and tx["action"] == "close" and tx["acknowledged"] and tx["summary"]
                           for tx in trials)):
            raise ValueError("both outlet runs and explicit stop evidence required")
        name = request.get("name")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError("device name required (1–100 characters)")
        record.update(device_id="local-htv213-" + key.split(":")[1], name=name.strip())
        gateway._store.save_htv213_owner(json.dumps(records, sort_keys=True))
        gateway.notify_node_update(record["node_id"], "htv213_device_added")
        return project(gateway, now)[record["device_id"]]


def project(gateway, now=None):
    now = now or datetime.now(timezone.utc)
    devices = {}
    for key, record in owner.records(gateway).items():
        device_id = record.get("device_id")
        if not device_id or record.get("revoking"):
            continue
        journal = ControlJournal(gateway._store).snapshot(key)
        tx = journal.get("transaction") or {}
        age = _age(tx.get("reserved_at"), now)
        unresolved = journal["state"] not in {"ready", "complete"}
        node = gateway._nodes.get(record["node_id"], {})
        owner_status = node.get("htv213_owner", {})
        connected = bool(node.get("connected") and node.get("authenticated") and
                         owner.CAPABILITY in node.get("capabilities", []) and
                         owner_status.get("state") == "ready" and
                         owner_status.get("command_id") == record["command"]["command_id"])
        state = {"device_kind": "valve", "rf_control_enabled": True,
                 "rf_control_node_id": record["node_id"], "rf_control_qualification": "normal_enrollment" if record.get("enrollment_id") else "dry_canary",
                 "rf_control_duration_min_minutes": 1,
                 "rf_control_duration_max_minutes": 60 if "htv213_duration_3600" in node.get("capabilities", []) else 2,
                 "rf_control_duration_step_minutes": 1}
        for port in (1, 2):
            report = record["ports"].get(str(port), {})
            fresh = 0 <= _age(report.get("observed_at"), now) <= FRESH_SECONDS
            # A pre-command idle report is not evidence that an attempted open
            # failed. Preserve the other outlet, but require a new target-port
            # report before presenting its current state (even after an ACK).
            superseded_idle = (unresolved and tx.get("action") == "open" and
                tx.get("port") == port and report.get("watering") is False and
                _age(report.get("observed_at"), now) >= age)
            fresh = fresh and not superseded_idle
            state[f"zone_{port}_is_watering"] = report.get("watering") if fresh else None
            state[f"zone_{port}_remaining_seconds"] = report.get("remaining_seconds") if fresh else None
        watering = [state[f"zone_{port}_is_watering"] for port in (1, 2)]
        state["is_watering"] = True if True in watering else False if watering == [False, False] else None
        state["active_zone"] = next((p for p in (1, 2) if state[f"zone_{p}_is_watering"]), None)
        # Never infer close from elapsed wall-clock time or an API return.
        state["valve_state"] = "watering" if state["is_watering"] is True else "idle" if state["is_watering"] is False else "unknown"
        rejected = (node.get("htv213_control") or {}).get("node_state") in {"command_rejected", "uncertain", "cancelled", "overdue"}
        pending = unresolved and not tx.get("acknowledged") and age < 10 and connected and not rejected
        failed = unresolved and not tx.get("acknowledged") and not pending
        deadline_passed = unresolved and age > tx.get("requested_seconds", 0) + 65
        overdue = deadline_passed and not tx.get("idle")
        missing_summary = deadline_passed and tx.get("idle") and not tx.get("summary")
        failed = failed or missing_summary
        phase = ("failed" if failed or overdue else "awaiting_confirmation" if pending else
                 "watering_confirmed" if journal["state"] == "open_confirmed" else
                 "confirmed" if journal["state"] == "complete" else journal["state"])
        boundary_active = bool(journal.get("counter_boundary") and not journal["counter_boundary"].get("complete"))
        start = (connected and not unresolved and not boundary_active and
                 watering == [False, False] and
                 (journal["next_phase"] <= 63 or wraps(journal)))
        same_session = (_age(node.get("connected_at"), now) >= age)
        stop = (connected and same_session and not boundary_active and journal["state"] == "open_confirmed"
                and not tx.get("idle") and not overdue)
        reason = ("Radio unavailable" if not connected else "Command awaiting valve response" if pending else
                  "Valve confirmed idle; completion summary missing; no automatic retry" if missing_summary else
                  "Counter/command requires investigation; no automatic retry" if failed or overdue else
                  "Explicit counter-boundary experiment in progress" if boundary_active else
                  "Waiting for confirmed idle on both outlets" if not start else None)
        state.update(rf_control_available=bool(start or stop), rf_control_start_available=start,
            rf_control_unavailable_reason=reason, rf_control_start_unavailable_reason=reason,
            rf_control_command_pending=pending, rf_control_transaction_active=pending,
            rf_control_transaction_state=phase, rf_control_transaction_id=tx.get("command_id"),
            rf_control_transaction_action=tx.get("action"), rf_control_transaction_zone=tx.get("port"),
            rf_control_transaction_duration_seconds=tx.get("requested_seconds"),
            rf_control_transaction_status=reason or "Ready", rf_control_transaction_error=reason if failed or overdue else None,
            rf_control_overdue=overdue, rf_control_completion_missing=bool(missing_summary),
            rf_retained_command_counter=journal["next_phase"],
            rf_retained_counter_status="Ready" if start else reason or "Watering in progress")
        devices[device_id] = dict(device_id=device_id, model=MODEL, name=record["name"], area=record.get("area"),
            available=connected, reporting=connected and 0 <= _age(record.get("last_seen"), now) <= FRESH_SECONDS,
            observed_at=record.get("last_seen"), capabilities=["bounded_valve_control", "forget"], state=state)
    return devices


def request(gateway, device_id, action, port, seconds=None):
    with gateway._lock:
        found = _find(gateway, device_id)
        if not found:
            raise KeyError(device_id)
        key, record = found
        if type(port) is not int or port not in (1, 2):
            raise ValueError("HTV213 has exactly two outlets")
        control.eligible(gateway, record["node_id"])
        if gateway.pairing().get("active") or gateway._ack_ownership.snapshot():
            raise ValueError("finish pairing or ownership changes before valve control")
        state = project(gateway)[device_id]["state"]
        journal = ControlJournal(gateway._store)
        if action == "open":
            if not state["rf_control_start_available"]:
                raise ValueError(state["rf_control_start_unavailable_reason"])
            if type(seconds) is not int or not 1 <= seconds <= state["rf_control_duration_max_minutes"] * 60:
                raise ValueError("duration exceeds the selected radio capability")
            tx = journal.reserve(key, action=action, port=port, seconds=seconds)
            command = copy.deepcopy(record["command"])
            command.update(type="htv213_control_probe_open", command_id=tx["command_id"],
                local_clock=datetime.now().astimezone().strftime("%Y%m%d%H%M%S"),
                port=port, seconds=seconds, phase=tx["phase"])
        elif action == "close":
            if not state["rf_control_available"] or state["rf_control_transaction_state"] != "watering_confirmed":
                raise ValueError("close requires a confirmed active run on this owner")
            prior = journal.snapshot(key)["transaction"]
            tx = journal.reserve(key, action=action, port=port, seconds=0)
            command = dict(type="htv213_control_probe_close", command_id=tx["command_id"],
                           open_command_id=prior["command_id"], phase=tx["phase"])
        else:
            raise ValueError("unsupported valve action")
        try:
            return control.dispatch(gateway, record["node_id"], key, tx, command, tx["requested_seconds"] + 65)
        finally:
            gateway.notify_node_update(record["node_id"], "htv213_control_changed")


def forget(gateway, device_id):
    """Hide immediately; retain a revoke tombstone until radio acknowledgement.

    The old owner is never restored or available for reassignment while its
    tombstone is pending. Command history/counter evidence is retained.
    """
    with gateway._lock:
        found = _find(gateway, device_id)
        if not found:
            raise KeyError(device_id)
        key, record = found
        journal = ControlJournal(gateway._store).snapshot(key)
        if journal["state"] not in {"ready", "complete"} or any(r.get("watering") for r in record["ports"].values()):
            raise ValueError("finish the active or unresolved valve transaction first")
        records = owner.records(gateway)
        records[key]["revoking"] = True
        gateway._store.save_htv213_owner(json.dumps(records, sort_keys=True))
        owner.restore(gateway, record["node_id"])
        gateway.notify_node_update(record["node_id"], "htv213_device_removed")
        return dict(device_id=device_id, endpoint=key.split(":")[1], ownership_cleanup_pending=True)
