"""HTV213 command transport and authenticated radio-status correlation.

Shared by HA controls and research admission. Select normal wire commands for
unified firmware and preserve the deployed test-firmware protocol for older nodes.
Command acceptance always comes from the durable RF journal, not API success.
"""
from __future__ import annotations

import time
from .htv213_control import ControlJournal

# Existing deployed capability; do not relabel the protocol during extraction.
CAPABILITY = "htv213_control_experiment"
IDLE_RECOVERY_CAPABILITY = "htv213_idle_recovery_v1"
NORMAL_CONTROL_CAPABILITY = "htv213_control_v1"
SHARED_RADIO_CAPABILITY = "htv213_shared_radio_v1"
OWNER_CAPACITY = 8


def remember(gateway, node_id, command_id, association_key):
    owners = getattr(gateway, "_htv213_control_owners", {})
    owners = {key: value for key, value in owners.items() if value != association_key}
    owners[(node_id, command_id)] = association_key
    gateway._htv213_control_owners = owners
    gateway._htv213_control_owner = (node_id, command_id, association_key)


def response_owner(gateway, node_id, command_id):
    if not isinstance(command_id, str):
        return None
    key = getattr(gateway, "_htv213_control_owners", {}).get((node_id, command_id))
    if key:
        return node_id, command_id, key
    legacy = getattr(gateway, "_htv213_control_owner", None)
    return legacy if legacy and legacy[:2] == (node_id, command_id) else None


def command_type(node, action):
    """Select ordinary wire commands, retaining compatibility with control.12."""
    if action not in {"open", "close"}:
        raise ValueError("unsupported HTV213 control action")
    prefix = ("htv213_control_" if NORMAL_CONTROL_CAPABILITY in node.get("capabilities", [])
              else "htv213_control_probe_")
    return prefix + action


def eligible(gateway, node_id):
    if gateway._store is None or gateway._node_command_sender is None:
        raise RuntimeError("persistent registry and node transport required")
    node = next((n for n in gateway.nodes() if n["node_id"] == node_id), {})
    if not (node.get("managed") and node.get("authenticated") and node.get("connected")
            and {CAPABILITY, NORMAL_CONTROL_CAPABILITY} & set(node.get("capabilities", []))):
        raise ValueError("selected node needs compatible HTV213 control firmware")
    if (SHARED_RADIO_CAPABILITY not in node.get("capabilities", []) and
            (gateway._store.ack_assignments(node_id) or any(
             v.get("control_node_id") == node_id for v in gateway._store.valve_registry()))):
        raise ValueError("update radio firmware to share HTV213 control with other devices")
    return node


def dispatch(gateway, node_id, key, tx, command, lease_seconds):
    gateway._htv213_experiment_deadline = time.monotonic() + lease_seconds
    gateway._htv213_experiment_owner = (node_id, tx["command_id"])
    remember(gateway, node_id, tx["command_id"], key)
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
        owner = response_owner(gateway, node_id, message.get("command_id"))
        if not owner:
            return
        state = message.get("state")
        if state not in {"transmitting", "awaiting_response", "open_confirmed", "close_awaiting_response",
                         "close_confirmed", "complete", "uncertain", "overdue", "cancelled", "recovered_idle"}:
            return
        journal = ControlJournal(gateway._store)
        current = journal.snapshot(owner[2])
        if ((current.get("transaction") or {}).get("command_id") != message.get("command_id")
                or current["identity"]["node_id"] != node_id):
            return  # A fresh enrollment superseded the old in-memory command.
        if isinstance(message.get("frame"), str):
            journal.observe(owner[2], node_id=node_id, frame=message["frame"])
        if state == "recovered_idle":
            from . import htv213_owner
            node = gateway._nodes.get(node_id, {})
            association = htv213_owner.records(gateway).get(owner[2], {})
            status = htv213_owner.node_status(node, association)
            if (node.get("connected") and node.get("authenticated") and
                    IDLE_RECOVERY_CAPABILITY in node.get("capabilities", []) and
                    not association.get("revoking") and association.get("node_id") == node_id and
                    status.get("state") == "ready" and
                    status.get("command_id") == association.get("command", {}).get("command_id")):
                journal.recover_idle(owner[2], node_id=node_id, command_id=owner[1],
                                     ports=association.get("ports", {}))
        record = journal.snapshot(owner[2])
        terminal = state in {"complete", "overdue", "cancelled", "recovered_idle"}
        armed = message.get("tx_armed")
        gateway.update_node(node_id, tx_armed=armed if type(armed) is bool else not terminal, htv213_control={
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
        owner = response_owner(gateway, node_id, message.get("command_id"))
        if not owner:
            return False
        prior = gateway._nodes.get(node_id, {}).get("htv213_control", {})
        gateway.update_node(node_id, htv213_control={**prior, "node_state": "command_rejected"})
        # Keep the lease and indeterminate journal: an error is not RF proof.
        return True
