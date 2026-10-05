"""Durable reply ownership for a qualified HTV213 test association.

No command phase allocation, implicit re-pairing or opening occurs here.
Commands remain in the independent control journal. Fresh authenticated node
sessions receive only the retained reply configuration, never an open replay.
"""
from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timezone

from . import htv213_pairing
from .htv213_control_transport import eligible
from .htv213_control import ControlJournal, packet

KEY = "htv213_reply_owner_v1"
CAPABILITY = "htv213_routine_owner"
REJOIN_CAPABILITY = "htv213_retained_rejoin_v1"
IDLE_RESUME_CAPABILITY = "htv213_idle_recovery_resume_v1"


def reply_configuration(command):
    """Carry forward the original canary's known configuration, not RF guesses.

    Old owner records were created with these exact empty-plan defaults. A
    changed configuration must be supplied explicitly through configure_recovery.
    """
    from .valve_recovery import configuration
    factory = command["factory_endpoint"]
    return configuration(dict(model="HTV213FRF", factory_endpoint=factory,
        valve_endpoint=f'{int(factory,16) | 0x80000000:08x}',
        controller_endpoint=command["controller_endpoint"], node_id=command["node_id"],
        selector=command["assigned_selector"], revision=2, address=command["device_address"],
        timing_raw=command["timing_raw"],
        ports=[dict(settings="58020a001e00" + "00" * 8, empty_plan=True) for _ in range(2)]))


def apply_reply_configuration(command, config, enabled):
    command["configuration_revision"] = config["revision"]
    command["retained_rejoin_enabled"] = enabled
    for index, port in enumerate(config["ports"], 1):
        command[f"port_{index}_settings"] = port["settings"]
        command[f"port_{index}_empty_plan"] = port["empty_plan"]


def configure_recovery(gateway, request):
    """Explicit canary opt-in on an existing reply owner; never enroll or open."""
    from .valve_recovery import configuration
    with gateway._lock:
        saved = records(gateway)
        key = request.get("association_key")
        if not isinstance(key, str):
            raise ValueError("existing association_key required")
        record = saved.get(key)
        enabled = request.get("enabled")
        if not record or record.get("revoking") or type(enabled) is not bool:
            raise ValueError("existing reply owner and explicit enabled flag required")
        node_id = record["node_id"]
        node = gateway._nodes.get(node_id, {})
        if not (node.get("connected") and node.get("authenticated") and
                REJOIN_CAPABILITY in node.get("capabilities", [])):
            raise ValueError("retained-rejoin firmware required")
        command = record["command"]
        config = configuration(request.get("configuration"))
        expected = record.get("configuration") or reply_configuration({**command, "node_id": node_id})
        if any(config[field] != expected[field] for field in (
                "model", "factory_endpoint", "valve_endpoint", "controller_endpoint",
                "node_id", "selector", "address", "timing_raw")):
            raise ValueError("retained configuration must match the existing association")
        if (gateway.endpoint_suppressed(config["valve_endpoint"]) or
                ControlJournal(gateway._store).snapshot(key)["state"] != "complete" or
                htv213_pairing.busy(gateway) or node.get("tx_armed") or
                gateway._store.ack_assignments(node_id) or any(
                    r.get("control_node_id") == node_id for r in gateway._store.valve_registry())):
            raise ValueError("idle exclusive reply owner required")
        record["configuration"] = config
        apply_reply_configuration(command, config, enabled)
        gateway._store.save_htv213_owner(json.dumps(saved, sort_keys=True))
        restore(gateway, node_id)
        return dict(state="owner_pending", command_id=command["command_id"],
                    retained_rejoin_enabled=enabled, operational=False)


def records(gateway):
    return json.loads(gateway._store.metadata_value(KEY) or "{}") if gateway._store else {}


def configure(gateway, request):
    with gateway._lock:
        node_id = request.get("node_id")
        node = eligible(gateway, node_id)
        if CAPABILITY not in node.get("capabilities", []):
            raise ValueError("HTV213 reply-owner firmware required")
        if htv213_pairing.busy(gateway) or any(n.get("tx_armed") for n in gateway.nodes()):
            raise ValueError("wait for the bounded trial to finish")
        command = htv213_pairing.build_command(request,
            controller=gateway.rf_identity.controller_endpoint,
            companion=gateway.rf_identity.companion_endpoint)
        valve = f'{int(command["factory_endpoint"],16) | 0x80000000:08x}'
        key = command["controller_endpoint"] + ":" + valve
        state = ControlJournal(gateway._store).snapshot(key)
        if (state["state"] != "complete" or state["identity"]["node_id"] != node_id
                or state["transaction"]["command_id"] != request.get("trial_command_id")
                or state["identity"]["selector"] != command["assigned_selector"]
                or gateway.endpoint_suppressed(valve)):
            raise ValueError("matching completed dry control evidence required")
        saved = records(gateway)
        if key in saved or any(r["node_id"] == node_id for r in saved.values()):
            raise ValueError("existing owner must be restored or revoked, not replaced")
        command.update(type="htv213_owner_set", port=1, seconds=60)
        config = reply_configuration({**command, "node_id": node_id})
        apply_reply_configuration(command, config, False)
        saved[key] = dict(node_id=node_id, command=command, ports={}, configuration=config,
                          evidence_command_id=state["transaction"]["command_id"])
        gateway._store.save_htv213_owner(json.dumps(saved, sort_keys=True))
        restore(gateway, node_id)
        return {"state": "owner_pending", "command_id": command["command_id"], "operational": False}


def restore(gateway, node_id):
    """Called once for an authenticated connection. Sends configuration only."""
    with gateway._lock:
        node = gateway._nodes.get(node_id, {})
        if not (node.get("connected") and node.get("authenticated")
                and CAPABILITY in node.get("capabilities", [])):
            return
        saved = records(gateway)
        for key, record in saved.items():
            if record["node_id"] != node_id:
                continue
            if record.get("revoking"):
                gateway._node_command_sender(node_id, {"type": "htv213_owner_clear",
                    "command_id": uuid.uuid4().hex,
                    "owner_id": record["command"]["command_id"]})
                continue
            if gateway.endpoint_suppressed(key.split(":")[1]):
                continue
            # Never restore an owner onto a node subsequently assigned elsewhere.
            if (gateway._store.ack_assignments(node_id) or any(
                    r.get("control_node_id") == node_id for r in gateway._store.valve_registry())):
                continue
            command = copy.deepcopy(record["command"])
            config = record.get("configuration") or reply_configuration({**command, "node_id": node_id})
            rejoin = command.get("retained_rejoin_enabled", False)
            # A downgrade must not restore an unqualified recovery owner.
            original = reply_configuration({**command, "node_id": node_id})
            if (rejoin or config != original) and REJOIN_CAPABILITY not in node.get("capabilities", []):
                continue
            apply_reply_configuration(command, config, rejoin)
            if "configuration" not in record:
                # Freeze the original canary defaults before sending the
                # upgraded payload; later code must not reinterpret them.
                record["configuration"] = config
                apply_reply_configuration(record["command"], config, rejoin)
                gateway._store.save_htv213_owner(json.dumps(saved, sort_keys=True))
            command["local_clock"] = datetime.now().astimezone().strftime("%Y%m%d%H%M%S")
            # Resume observation from the durable journal, including after a
            # reboot. This is owner configuration, never an open replay. The
            # radio must collect new idle reports from BOTH outlets.
            control = ControlJournal(gateway._store)._records().get(key, {})
            identity = control.get("identity", {})
            tx = control.get("transaction") or {}
            boundary = control.get("counter_boundary") or {}
            if (IDLE_RESUME_CAPABILITY in node.get("capabilities", []) and
                    control.get("state") == "indeterminate" and tx.get("action") == "open" and
                    tx.get("acknowledged") is False and not (boundary and not boundary.get("complete")) and
                    identity.get("node_id") == node_id and
                    identity.get("controller") == config["controller_endpoint"] and
                    identity.get("valve") == config["valve_endpoint"] and
                    identity.get("selector") == config["selector"] and
                    (not record.get("enrollment_id") or
                     record["enrollment_id"] == identity.get("evidence_id"))):
                command.update(recovery_command_id=tx["command_id"], recovery_phase=tx["phase"],
                               recovery_port=tx["port"], recovery_seconds=tx["requested_seconds"])
                gateway._htv213_control_owner = (node_id, tx["command_id"], key)
            gateway.update_node(node_id, htv213_owner={"state": "pending", "command_id": command["command_id"]})
            gateway._node_command_sender(node_id, command)


def observe(gateway, node_id, message):
    with gateway._lock:
        saved = records(gateway)
        match = next(((key,r) for key,r in saved.items() if r["node_id"] == node_id and
                      r["command"]["command_id"] == message.get("command_id")), None)
        node = gateway._nodes.get(node_id, {})
        if not match or not (node.get("connected") and node.get("authenticated")):
            return
        if type(message.get("enabled")) is not bool:
            return
        key, record = match
        enabled = message["enabled"]
        if record.get("revoking"):
            if not enabled:
                record["revoked"] = True
                gateway._store.save_htv213_owner(json.dumps(saved, sort_keys=True))
            return
        if REJOIN_CAPABILITY in node.get("capabilities", []) and (
                message.get("retained_rejoin_enabled") is not record["command"].get("retained_rejoin_enabled", False) or
                message.get("configuration_revision") != record["configuration"]["revision"]):
            return
        status = {"state": "ready" if enabled else "disabled", "command_id": message["command_id"]}
        status["retained_rejoin_enabled"] = record["command"].get("retained_rejoin_enabled", False)
        decoded = packet(message.get("frame"))
        if decoded:
            raw, command, phase, data = decoded
            controller, valve = key.split(":")
            if raw[5:9].hex() != controller or raw[9:13].hex() != valve or raw[13] & 0x20:
                return
            now = datetime.now(timezone.utc).isoformat()
            if (command == 2 and len(data) == 15 and data[0] == record["command"]["assigned_selector"]
                    and data[2] in (1,2) and data[3] in (0,0x21)):
                remaining = int.from_bytes(data[10:12], "little")
                requested = int.from_bytes(data[13:15], "little")
                if (data[3] == 0 and (remaining or requested)) or remaining > requested+1:
                    return
                record["ports"][str(data[2])] = dict(watering=data[3]==0x21,
                    remaining_seconds=remaining, requested_seconds=requested, observed_at=now,
                    phase=phase)
            record["last_seen"] = now
            # Ordinary retained reports may complete an acknowledged run after
            # gateway reconnect. They never allocate or reset master phases.
            ControlJournal(gateway._store).observe(key, node_id=node_id, frame=message["frame"])
            gateway._store.save_htv213_owner(json.dumps(saved, sort_keys=True))
            status.update(last_seen=now, ports=copy.deepcopy(record["ports"]))
        else:
            status.update(ports=copy.deepcopy(record["ports"]))
        gateway.update_node(node_id, htv213_owner=status)
        if record.get("device_id"):
            gateway.notify_node_update(node_id, "htv213_report")
