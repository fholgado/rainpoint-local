"""Authenticated, unassigned-node dry trials; never production valve controls."""
from __future__ import annotations

import time
from . import htv213_pairing
from .htv213_control_trial import ControlJournal

CAPABILITY = "htv213_control_experiment"


def eligible(gateway, node_id):
    if gateway._store is None or gateway._node_command_sender is None:
        raise RuntimeError("persistent registry and node transport required")
    node = next((n for n in gateway.nodes() if n["node_id"] == node_id), {})
    if not (node.get("managed") and node.get("authenticated") and node.get("connected")
            and CAPABILITY in node.get("capabilities", [])):
        raise ValueError("selected node needs the HTV213 dry-control canary")
    if (gateway._store.ack_assignments(node_id) or any(
            v.get("control_node_id") == node_id for v in gateway._store.valve_registry())):
        raise ValueError("dry control requires an unassigned test node")
    return node


def start(gateway, request):
    with gateway._lock:
        node_id = request.get("node_id")
        node = eligible(gateway, node_id)
        if (type(request.get("seconds")) is int and request["seconds"] > 120
                and "htv213_duration_3600" not in node.get("capabilities", [])):
            raise ValueError("radio firmware does not support the requested duration")
        if (htv213_pairing.busy(gateway) or gateway.pairing().get("active")
                or any(n.get("tx_armed") for n in gateway.nodes()) or gateway._ack_ownership.snapshot()):
            raise ValueError("another experiment, pairing or ownership operation is active")
        # Same explicit identity/carrier/clock validation as the frozen pairing
        # admission; this builds data only and never sends an assignment.
        command = htv213_pairing.build_command(request,
            controller=gateway.rf_identity.controller_endpoint,
            companion=gateway.rf_identity.companion_endpoint)
        paired = f'{int(command["factory_endpoint"], 16) | 0x80000000:08x}'
        if gateway.endpoint_suppressed(paired) or any(
                v.get("valve_endpoint") == paired for v in gateway._store.valve_registry()):
            raise ValueError("target is suppressed or already locally owned")
        journal = ControlJournal(gateway._store)
        key = journal.seed(node_id=node_id, controller=command["controller_endpoint"], valve=paired,
                           selector=command["assigned_selector"],
                           acknowledged_phase=request.get("acknowledged_phase"),
                           evidence_id=request.get("pairing_evidence_id"))
        if "counter_boundary" in request:
            from . import htv213_device, htv213_owner
            proof = request["counter_boundary"]
            if not isinstance(proof, dict) or "crc_retrial" in request:
                raise ValueError("explicit counter-boundary authorization required")
            retained = htv213_owner.records(gateway).get(key, {})
            device = htv213_device.project(gateway).get(retained.get("device_id"), {})
            state = device.get("state", {})
            if (not device.get("available") or
                    any(state.get(f"zone_{p}_is_watering") is not False for p in (1, 2))):
                raise ValueError("counter boundary requires a qualified owner and fresh idle on both outlets")
            tx = journal.reserve_boundary_probe(key,
                prior_command_id=proof.get("prior_command_id"), authorization_id=proof.get("authorization_id"),
                port=request.get("port"), seconds=request.get("seconds"),
                dry_confirmed=request.get("dry_valve_confirmed"))
        elif "crc_retrial" in request:
            proof = request["crc_retrial"]
            if (node.get("firmware_version") != "0.19.0-htv213-control.2"
                    or not isinstance(proof, dict)):
                raise ValueError("CRC retrial requires the corrected isolated canary and audit record")
            tx = journal.reserve_crc_retrial(key,
                prior_command_id=proof.get("prior_command_id"),
                evidence_sha256=proof.get("evidence_sha256"),
                authorization_id=proof.get("authorization_id"),
                port=request.get("port"), seconds=request.get("seconds"),
                dry_confirmed=request.get("dry_valve_confirmed"))
        else:
            tx = journal.reserve(key, action="open", port=request.get("port"), seconds=request.get("seconds"),
                                 dry_confirmed=request.get("dry_valve_confirmed"))
        command.update(type="htv213_control_probe_open", command_id=tx["command_id"],
                       port=tx["port"], seconds=tx["requested_seconds"], phase=tx["phase"])
        return dispatch(gateway, node_id, key, tx, command, tx["requested_seconds"] + 65)


def dispatch(gateway, node_id, key, tx, command, lease_seconds):
    gateway._htv213_experiment_deadline = time.monotonic() + lease_seconds
    gateway._htv213_experiment_owner = (node_id, tx["command_id"])
    gateway._htv213_control_owner = (node_id, tx["command_id"], key)
    status = {"command_id": tx["command_id"], "state": "reserved", "phase": tx["phase"],
              "port": tx["port"], "operational": False}
    gateway.update_node(node_id, htv213_control=status)
    try:
        ControlJournal(gateway._store).dispatch(key, tx,
            lambda _identity, _tx: gateway._node_command_sender(node_id, command))
    finally:
        # Transport return (or exception) says nothing about RF acceptance.
        state = ControlJournal(gateway._store).snapshot(key)["state"]
        gateway.update_node(node_id, htv213_control={**status, "state": state})
    return {**status, "state": "indeterminate"}


def close(gateway, request):
    with gateway._lock:
        node_id = request.get("node_id")
        eligible(gateway, node_id)
        owner = getattr(gateway, "_htv213_control_owner", None)
        if not owner or owner[:2] != (node_id, request.get("open_command_id")):
            raise ValueError("close must match the current dry open")
        journal = ControlJournal(gateway._store)
        tx = journal.reserve(owner[2], action="close", port=request.get("port"), seconds=0,
                             dry_confirmed=request.get("dry_valve_confirmed"))
        command = {"type": "htv213_control_probe_close", "command_id": tx["command_id"],
                   "open_command_id": request["open_command_id"], "phase": tx["phase"]}
        return dispatch(gateway, node_id, owner[2], tx, command, tx["requested_seconds"] + 65)


def observe(gateway, node_id, message):
    with gateway._lock:
        owner = getattr(gateway, "_htv213_control_owner", None)
        if not owner or owner[:2] != (node_id, message.get("command_id")):
            return
        state = message.get("state")
        if state not in {"transmitting", "awaiting_response", "open_confirmed", "close_awaiting_response",
                         "close_confirmed", "complete", "uncertain", "overdue", "cancelled"}:
            return
        journal = ControlJournal(gateway._store)
        if isinstance(message.get("frame"), str):
            journal.observe(owner[2], node_id=node_id, frame=message["frame"])
        record = journal.snapshot(owner[2])
        terminal = state in {"complete", "overdue", "cancelled"}
        gateway.update_node(node_id, tx_armed=not terminal, htv213_control={
            "command_id": owner[1], "state": record["state"], "node_state": state,
            "phase": record["transaction"]["phase"], "port": record["transaction"]["port"],
            "operational": False, "acknowledged": record["transaction"]["acknowledged"],
            "idle": record["transaction"]["idle"], "summary": record["transaction"]["summary"]})
        if terminal:
            gateway._htv213_experiment_deadline = 0
        gateway.notify_node_update(node_id, "htv213_control_changed")


def observe_error(gateway, node_id, message):
    """Expose rejection without reclaiming an attempted phase or enabling retry."""
    with gateway._lock:
        owner = getattr(gateway, "_htv213_control_owner", None)
        if not owner or owner[:2] != (node_id, message.get("command_id")):
            return False
        prior = gateway._nodes.get(node_id, {}).get("htv213_control", {})
        gateway.update_node(node_id, htv213_control={**prior, "node_state": "command_rejected"})
        # Keep the lease and indeterminate journal: an error is not RF proof.
        return True
