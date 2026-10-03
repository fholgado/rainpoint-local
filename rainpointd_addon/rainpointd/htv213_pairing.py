"""Explicit dry-canary admission; never registers a valve or enables controls."""
from __future__ import annotations

import re
import time
import uuid
from datetime import datetime

from .htv213_enrollment import parameters

CAPABILITY = "htv213_pairing_experiment"


def busy(gateway):
    return time.monotonic() < getattr(gateway, "_htv213_experiment_deadline", 0)


def build_command(request, *, controller, companion):
    if request.get("dry_valve_confirmed") is not True:
        raise ValueError("confirm the HTV213 is dry before this experiment")
    factory = request.get("factory_endpoint", "")
    if not isinstance(factory, str) or not re.fullmatch(r"[0-7][0-9a-f]{7}", factory) or int(factory,16)==0:
        raise ValueError("an exact factory endpoint is required")
    values = parameters(request, controller=controller, companion=companion)
    return {"type":"htv213_pairing_start", "command_id":uuid.uuid4().hex,
            "factory_endpoint":factory,
            "local_clock":datetime.now().astimezone().strftime("%Y%m%d%H%M%S"),
            **values}


def start(gateway, request):
    """Require an unassigned test node and no active enrollment anywhere."""
    with gateway._lock:
        if gateway._store is None:
            raise RuntimeError("persistent gateway registry required")
        node_id=request.get("node_id")
        node=next((n for n in gateway.nodes() if n["node_id"]==node_id),{})
        if not (node.get("managed") and node.get("authenticated") and node.get("connected")
                and CAPABILITY in node.get("capabilities",[])):
            raise ValueError("selected node needs the HTV213 canary firmware")
        if (gateway.pairing().get("active") or any(n.get("tx_armed") for n in gateway.nodes())
                or gateway._ack_ownership.snapshot()):
            raise ValueError("another pairing or ownership operation is active")
        if busy(gateway):
            raise ValueError("HTV213 experiment already requested; cancel or await its bounded window")
        if (gateway._store.ack_assignments(node_id) or any(
                v.get("control_node_id")==node_id for v in gateway._store.valve_registry())):
            raise ValueError("HTV213 experiments require an unassigned test node")
        command=build_command(request, controller=gateway.rf_identity.controller_endpoint,
                              companion=gateway.rf_identity.companion_endpoint)
        paired=f'{int(command["factory_endpoint"],16)|0x80000000:08x}'
        if gateway.endpoint_suppressed(paired) or any(
                v.get("valve_endpoint")==paired for v in gateway._store.valve_registry()):
            raise ValueError("target is suppressed or already locally owned")
        if gateway._node_command_sender is None:
            raise RuntimeError("radio-node transport unavailable")
        status={"command_id":command["command_id"],"state":"requested", "operational":False}
        gateway._htv213_experiment_deadline=time.monotonic()+command["duration_seconds"]+5
        gateway._htv213_experiment_owner=(node_id,command["command_id"])
        gateway.update_node(node_id,htv213_pairing=status)
        try:
            gateway._node_command_sender(node_id,command)
        except (ConnectionError,KeyError,RuntimeError,ValueError):
            gateway.update_node(node_id,htv213_pairing={**status,"state":"dispatch_failed"})
            raise
        return status


def observe(gateway,node_id,message):
    with gateway._lock:
        node=gateway._nodes.get(node_id,{})
        prior=node.get("htv213_pairing",{})
        if (not prior or prior.get("command_id")!=message.get("command_id") or
                getattr(gateway,"_htv213_experiment_owner",None)!=(node_id,message.get("command_id"))):
            return
        state=message.get("state")
        if state not in {"armed","observed","failed","disarmed"}:
            return
        fields={key:message[key] for key in ("reports","settings_sent","plans_sent","replies_sent","failure")
                if type(message.get(key)) is int and 0 <= message[key] <= 64}
        gateway.update_node(node_id,tx_armed=state=="armed",
            htv213_pairing={"command_id":prior["command_id"],"state":state,
                           "operational":False,**fields})
        if state in {"observed","failed","disarmed"}:
            gateway._htv213_experiment_deadline=0


def observe_error(gateway, node_id, message):
    """A rejected candidate command is not an ordinary pairing failure."""
    with gateway._lock:
        prior=gateway._nodes.get(node_id,{}).get("htv213_pairing",{})
        if not prior or prior.get("command_id")!=message.get("command_id"):
            return False
        # Preserve the bounded lease: a cancellation rejection does not prove
        # the radio stopped transmitting. Only authoritative status clears it.
        gateway.update_node(node_id,htv213_pairing={**prior,"state":"command_rejected",
                                                  "operational":False})
        return True


def cancel(gateway, request):
    with gateway._lock:
        node_id=request.get("node_id")
        prior=gateway._nodes.get(node_id,{}).get("htv213_pairing",{})
        if not prior or prior.get("command_id")!=request.get("command_id"):
            raise ValueError("HTV213 session changed; cancellation ignored")
        gateway._node_command_sender(node_id,{"type":"htv213_pairing_cancel", "command_id":prior["command_id"]})
        return {"state":"cancellation_requested", "command_id":prior["command_id"]}
