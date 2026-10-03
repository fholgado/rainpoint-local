"""Explicit incident repair, never a watering retry or generic counter policy."""
from .valve_phase_trial import packet, timestamp


def evidence_for(gateway, record, event_ids, observed_at):
    if (record["state"] not in ("failed", "recovering")
            or record.get("failure") not in ("missing_confirmation", "radio_trial_failed")
            or record["identity"]["model"] != "HTV145FRF"
            or len(record["transactions"]) != 1 or record["transactions"][0]["phase"] != 2):
        raise ValueError("not the recoverable first phase-2 HTV145 trial")
    if (not isinstance(event_ids, list) or len(event_ids) != 3
            or any(type(v) is not int or v < 1 for v in event_ids)
            or event_ids != sorted(set(event_ids))):
        raise ValueError("three ordered retained RF event IDs required")
    identity = record["identity"]; tx = record["transactions"][0]
    device_id = identity["admission"]["device_id"]
    nodes = {n["node_id"] for n in gateway.nodes() if n.get("managed") and n.get("authenticated")}
    proof = {}
    for label, event_id in zip(("ack", "watering", "idle"), event_ids):
        rows = gateway._store.events(since=event_id-1, limit=1)
        if not rows or rows[0]["event_id"] != event_id:
            raise ValueError("retained RF evidence missing")
        event = rows[0]; state = event.get("state", {})
        parsed = packet(event.get("raw"))
        if (event.get("event_type") != "device_observation" or event.get("device_id") != device_id
                or state.get("rf_frame_accepted") is not True or not parsed
                or state.get("rf_node_id") not in nodes
                or label in ("ack", "idle") and state.get("rf_node_id") != identity["node_id"]):
            raise ValueError("accepted RF evidence from the associated owner required")
        raw, command, phase, data = parsed
        if [raw[5:9].hex(), raw[9:13].hex()] != identity["response_route"]:
            raise ValueError("evidence route mismatch")
        age = round((timestamp(event["observed_at"])-timestamp(tx["attempted_at"])).total_seconds()*1000)
        if not 0 <= age <= 125000 or timestamp(event["observed_at"]) > timestamp(observed_at):
            raise ValueError("evidence outside attempted run")
        if label == "ack":
            valid = (command == 0xa1 and phase == 2 and len(data) == 13 and data[:2] == b"\x00\x21"
                and int.from_bytes(data[11:13], "little") == 60
                and 1 <= int.from_bytes(data[8:10], "little") <= 61 and age <= 15000)
        else:
            valid = command == 2 and len(data) == 15 and data[0] == identity["selector"] and data[2] == 1
            if valid:
                remaining, requested = int.from_bytes(data[10:12], "little"), int.from_bytes(data[13:15], "little")
                valid = ((data[3] == 0x21 and requested == 60 and 1 <= remaining <= 61) if label == "watering"
                         else (data[3] == 0 and remaining == requested == 0 and age >= 55000))
        if not valid:
            raise ValueError("evidence does not prove acknowledged 60-second run and automatic stop")
        proof[label] = dict(event_id=event_id, frame=event["raw"], observed_at=event["observed_at"],
            age_ms=age, node_id=state["rf_node_id"])
    if not proof["ack"]["age_ms"] < proof["watering"]["age_ms"] < proof["idle"]["age_ms"]:
        raise ValueError("evidence chronology mismatch")
    # Refuse a stale anchor if any later accepted result or watering report
    # invalidates it. Query only the selected device after this ACK.
    for event in gateway._store.device_observation_events(device_id, since=event_ids[0]):
        p = packet(event.get("raw"))
        if not p or event.get("state", {}).get("rf_frame_accepted") is not True:
            continue
        raw, kind, phase, data = p
        if [raw[5:9].hex(), raw[9:13].hex()] != identity["response_route"]:
            continue
        if kind == 0xa1 and (event["raw"] != proof["ack"]["frame"]
                or (timestamp(event["observed_at"])-timestamp(tx["attempted_at"])).total_seconds() > 15):
            raise ValueError("later command response invalidates recovery anchor")
        if (kind == 2 and len(data) == 15 and data[2] == 1 and data[3] != 0
                and timestamp(event["observed_at"]) > timestamp(proof["idle"]["observed_at"])):
            raise ValueError("watering after selected idle invalidates recovery")
    return proof
