"""Bind HTV213 enrollment to the existing gateway/HA pairing contract.

No additional wizard or watering. Only fully capable, explicitly calibrated
radios with an available ownership slot can enroll this model. Carrier profiles
are not copied from an installation-default endpoint.
"""
from __future__ import annotations

import re

from . import htv213_enrollment as enrollment, htv213_owner as owner
from .htv213_control_transport import CAPABILITY as control_capability, IDLE_RECOVERY_CAPABILITY


REQUIRED_CAPABILITIES = frozenset({enrollment.CAPABILITY, owner.CAPABILITY,
    owner.REJOIN_CAPABILITY, owner.IDLE_RESUME_CAPABILITY, control_capability,
    IDLE_RECOVERY_CAPABILITY, "htv213_pairing_experiment", "htv213_duration_3600"})


def node_unavailable_reason(gateway, node):
    """One read-only eligibility policy shared by HA choices and admission."""
    if not (node.get("managed") and node.get("authenticated") and node.get("connected")
            and node.get("protocol_version") == 2
            and REQUIRED_CAPABILITIES <= set(node.get("capabilities", []))):
        return "selected radio needs matching HTV213 enrollment and recovery firmware"
    node_id = node["node_id"]
    if gateway._store is None:
        return "persistent pairing registry required"
    if (gateway._store.ack_assignments(node_id)
            or any(v.get("control_node_id") == node_id for v in gateway._store.valve_registry())
            or any(r["node_id"] == node_id and r.get("revoked") is not True
                   for r in owner.records(gateway).values())):
        return "selected radio already owns a device; a dedicated available radio is required"
    try:
        enrollment.EnrollmentJournal(gateway._store).profile(node_id, 2)
    except ValueError:
        return "selected radio has no saved HTV213 carrier calibration"
    return None


def selected(gateway):
    if gateway._active_pairing_profile_id is not None:
        return gateway._active_pairing_profile_id == enrollment.PROFILE_ID
    if gateway._store is None or gateway._pairing is None or gateway._pairing.status().get("active"):
        return False
    # Recover the pending UI epoch after gateway restart without replaying RF.
    record = enrollment.EnrollmentJournal(gateway._store).current()
    return bool(record and record["state"] != "complete")


def completed_request(gateway, endpoint):
    if gateway._active_pairing_profile_id is not None or gateway._pairing.status().get("active"):
        return False
    record = enrollment.EnrollmentJournal(gateway._store).current()
    return bool(record and record["state"] == "complete" and
                record["result"]["configuration"]["valve_endpoint"] == endpoint)


def start(gateway, *, node_id, duration_seconds, factory_endpoint=None, now=None):
    from .htv213_pairing import busy
    if gateway._store is None or gateway._pairing is None or gateway._node_command_sender is None:
        raise RuntimeError("persistent pairing and node transport required")
    if type(duration_seconds) is not int or not 10 <= duration_seconds <= 300:
        raise ValueError("HTV213 enrollment duration must be 10–300 seconds")
    node = next((n for n in gateway.nodes() if n["node_id"] == node_id), {})
    reason = node_unavailable_reason(gateway, node)
    if reason:
        raise ValueError(reason)
    if gateway._pairing.status(now=now).get("active") or busy(gateway) or gateway._ack_ownership.snapshot() or any(n.get("tx_armed") for n in gateway.nodes()):
        raise ValueError("finish active pairing, control or ownership changes")
    saved = owner.records(gateway)
    replacement_key = None
    if factory_endpoint:
        if not isinstance(factory_endpoint, str) or not re.fullmatch(r"[0-7][0-9a-f]{7}", factory_endpoint) or int(factory_endpoint, 16) == 0:
            raise ValueError("exact unpaired HTV213 identity required")
        replacement_key = gateway.rf_identity.controller_endpoint + ":" + f"{int(factory_endpoint, 16) | 0x80000000:08x}"
        if replacement_key not in saved:
            raise ValueError("re-pair target has no existing association")
    journal = enrollment.EnrollmentJournal(gateway._store)
    address = journal.address(gateway.rf_identity.controller_endpoint, replacement_key=replacement_key)
    command = journal.profile(node_id, address).command(
        controller=gateway.rf_identity.controller_endpoint, companion=gateway.rf_identity.companion_endpoint,
        duration_seconds=duration_seconds, now=now)
    journal.begin(node_id, command, replacement_key=replacement_key, now=now)
    gateway._pairing.start(duration_seconds, now=now)
    gateway._active_pairing_node_id = node_id
    gateway._active_pairing_command_id = command["command_id"]
    gateway._active_pairing_profile_id = enrollment.PROFILE_ID
    gateway._active_pairing_rf_identity = dict(controller_endpoint=command["controller_endpoint"], companion_endpoint=command["companion_endpoint"])
    try:
        gateway._node_command_sender(node_id, command)
    except (ConnectionError, KeyError, RuntimeError, ValueError):
        journal.transition(node_id, command["command_id"], "dispatch_failed")
        raise
    return snapshot(gateway, now=now)


def snapshot(gateway, *, now=None):
    record = enrollment.EnrollmentJournal(gateway._store).current(now)
    if record is None:
        raise RuntimeError("HTV213 enrollment record missing")
    state = record["state"]
    stages = {"requested": "transmitter_armed", "armed": "pairing_exchange_in_progress",
        "accepted": "valve_pairing_completed", "complete": "valve_pairing_completed",
        "failed": "transmitter_failed", "command_rejected": "transmitter_failed",
        "dispatch_failed": "transmitter_failed", "cancelled": "inactive", "expired": "inactive"}
    result = record.get("result") or {}
    stage = stages.get(state, "pairing_exchange_in_progress")
    if state == "armed" and record.get("awaiting_confirmation"):
        stage = "waiting_for_terminal_confirmation"
    profiles = gateway._pairing_snapshot(now=now)["supported_profiles"]
    return dict(available=True, supported_profiles=profiles, transmitter_available=True,
        transmitter_required=True, pairing_nodes=gateway._pairing_nodes(),
        selected_node_id=record["node_id"], active_profile_id=enrollment.PROFILE_ID,
        command_id=record["command"]["command_id"], scoped_cancellation=True,
        transmit_performed=True, active=state not in {"complete", "failed", "expired", "cancelled"},
        stage=stage,
        completed_endpoint=result.get("configuration", {}).get("valve_endpoint") if state in {"accepted", "complete"} else None,
        completed_existing_record=(record.get("replacement_key") is not None or
            result.get("association_key") in record.get("revoked_keys", [])),
        candidates=[], new_records=[], records=[], error=record.get("error"))


def observe(gateway, node_id, message):
    with gateway._lock:
        if not selected(gateway):
            return False
        node = gateway._nodes.get(node_id, {})
        if not (node.get("connected") and node.get("authenticated") and enrollment.CAPABILITY in node.get("capabilities", [])):
            return False
        journal = enrollment.EnrollmentJournal(gateway._store)
        if not journal.observe(node_id, message):
            return False
        record = journal.current()
        if record["state"] in {"failed", "cancelled", "expired"}:
            gateway._pairing.stop()
        gateway.update_node(node_id, tx_armed=record["state"] == "armed")
        gateway.notify_node_update(node_id, "htv213_enrollment_changed")
        return True


def observe_error(gateway, node_id, message):
    if not selected(gateway):
        return False
    journal = enrollment.EnrollmentJournal(gateway._store)
    record = journal.current()
    if node_id != record["node_id"] or message.get("command_id") != record["command"]["command_id"] or record["state"] in {"accepted", "complete", "failed", "expired", "cancelled"}:
        return False
    journal.transition(node_id, message["command_id"], "command_rejected")
    gateway.notify_node_update(node_id, "htv213_enrollment_changed")
    return True


def cancel(gateway, command_id=None):
    journal = enrollment.EnrollmentJournal(gateway._store)
    record = journal.current()
    actual = record["command"]["command_id"]
    if command_id is not None and command_id != actual:
        raise ValueError("pairing session changed; cancellation ignored")
    if record["state"] in {"cancelled", "expired", "failed", "complete", "cancellation_requested"}:
        return snapshot(gateway)
    if record["state"] == "accepted":
        # The positive completion receipt already proves this radio session
        # terminal. Back/cancel abandons naming without another RF command.
        journal.transition(record["node_id"], actual, "cancelled")
        gateway._pairing.stop()
        return snapshot(gateway)
    journal.transition(record["node_id"], actual, "cancellation_requested")
    gateway._node_command_sender(record["node_id"], dict(type="htv213_pairing_cancel", command_id=actual))
    return snapshot(gateway)


def complete(gateway, *, endpoint, name, area=None):
    journal = enrollment.EnrollmentJournal(gateway._store)
    record = journal.current()
    if not record or record.get("result", {}).get("configuration", {}).get("valve_endpoint") != endpoint:
        raise ValueError("paired valve has not confirmed this enrollment")
    node_id = record["node_id"]
    node = gateway._nodes.get(node_id, {})
    if not (node.get("connected") and node.get("authenticated")):
        raise ValueError("selected radio is unavailable")
    if gateway.endpoint_suppressed(endpoint):
        raise ValueError("valve endpoint is suppressed")
    was_complete = record["state"] == "complete"
    saved = journal.complete(node_id, record["command"]["command_id"], name=name, area=area)
    gateway._release_active_pairing_node()
    gateway._pairing.stop()
    if not was_complete:
        prior_control = getattr(gateway, "_htv213_control_owner", None)
        key = record["result"]["association_key"]
        if prior_control and prior_control[2] == key:
            gateway._htv213_control_owner = None
        try:
            owner.restore(gateway, node_id)
        except (ConnectionError, KeyError, RuntimeError, ValueError):
            # The durable association remains authoritative. A subsequent
            # authenticated reconnect sends configuration, never enrollment.
            gateway.update_node(node_id, htv213_owner=dict(state="pending", command_id=saved["command"]["command_id"]))
    gateway.notify_node_update(node_id, "htv213_device_added")
    return owner_device(gateway, saved)


def owner_device(gateway, saved):
    from .htv213_device import project
    return project(gateway)[saved["device_id"]]
