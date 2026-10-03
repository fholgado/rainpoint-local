"""HTV213 command transport and authenticated radio-status correlation.

Shared by HA controls and research admission. Preserve the current canary wire
commands, capability and exclusive-node policy until normal model enrollment
is qualified; extracting this adapter does not enable production support.
Command acceptance always comes from the durable RF journal, not API success.
"""
from __future__ import annotations

import time
from .htv213_control import ControlJournal

# Existing deployed capability; do not relabel the protocol during extraction.
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
