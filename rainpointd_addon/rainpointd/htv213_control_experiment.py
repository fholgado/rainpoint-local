"""Authenticated, unassigned-node dry trials; never production valve controls."""
from __future__ import annotations

from . import htv213_pairing
from .htv213_control_trial import ControlJournal

from .htv213_control_transport import CAPABILITY, eligible, dispatch, observe, observe_error


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
