"""Durable HTV213 command phases and RF-confirmed transaction state.

Caller holds the gateway lock and verifies authenticated association ownership.
A reservation is committed before transmission; reconnects and routine reports
never reseed the master phase or replay an attempted command. Experimental
counter jumps and corrected-frame retries live in htv213_control_trial instead.
"""
from __future__ import annotations

import copy
import binascii
import json
import re
import uuid
from datetime import datetime, timezone

# Keep the existing key and record format: promotion must not reset counters.
KEY = "htv213_dry_control_trial_v1"
# Stock generator plus the captured 62/63/0/1 dry trial. Normal enrollment
# records this model policy, not a fabricated per-association trial result.
MODEL_PHASE_POLICY = "htv213_modulo64_v1"


def wraps(record):
    return (record.get("phase_policy") == MODEL_PHASE_POLICY or
            (record.get("counter_boundary") or {}).get("complete") is True)


def packet(frame):
    """Only checksum-valid, ordinary native-51 envelopes."""
    try:
        raw = bytes.fromhex(frame)
    except (ValueError, TypeError):
        return None
    if len(raw) != 38 or raw[:5] != bytes.fromhex("79f4882f28"):
        return None
    if binascii.crc_hqx(raw[:36], 0) ^ int.from_bytes(raw[36:], "big") not in (0xc713, 0x4f03):
        return None
    native = bytes(((raw[i + 4] << 1) | (raw[i + 5] >> 7)) & 255 for i in range(32))
    length = native[11] & 31
    if native[0] != 0x51 or length > 20:
        return None
    return raw, native[10], native[9] & 63, native[12:12 + length]


def initial_record(*, node_id, controller, valve, selector, acknowledged_phase, evidence_id):
    """Validate one explicit seed and prepare its durable record without IO."""
    if not isinstance(node_id, str) or not re.fullmatch(r"rp-[0-9a-f]{12}", node_id):
        raise ValueError("explicit radio node required")
    for value in (controller, valve):
        if (not isinstance(value, str) or not re.fullmatch(r"[89a-f][0-9a-f]{7}", value)
                or value == "80000000"):
            raise ValueError("explicit paired endpoint required")
    if controller == valve:
        raise ValueError("controller and valve must differ")
    if type(selector) is not int or not 1 <= selector <= 15:
        raise ValueError("explicit retained selector required")
    if type(acknowledged_phase) is not int or not 0 <= acknowledged_phase < 63:
        raise ValueError("explicit acknowledged phase required; wrap not qualified")
    if not isinstance(evidence_id, str) or not re.fullmatch(r"[0-9a-f]{32}", evidence_id):
        raise ValueError("pairing evidence reference required")
    identity = dict(node_id=node_id, controller=controller, valve=valve,
                    selector=selector, evidence_id=evidence_id, seed_phase=acknowledged_phase)
    return {"identity": identity, "next_phase": acknowledged_phase + 1,
            "state": "ready", "transaction": None, "history": []}


class ControlJournal:
    def __init__(self, store):
        self.store = store

    def _records(self):
        return json.loads(self.store.metadata_value(KEY) or "{}")

    def _save(self, records):
        self.store.save_htv213_control_trial(json.dumps(records, sort_keys=True))

    def seed(self, *, node_id, controller, valve, selector, acknowledged_phase, evidence_id):
        """Explicit evidence-backed seed, not a restart/rejoin/idle reset."""
        record = initial_record(node_id=node_id, controller=controller, valve=valve,
            selector=selector, acknowledged_phase=acknowledged_phase, evidence_id=evidence_id)
        key = controller + ":" + valve
        records = self._records()
        if key in records:
            if records[key]["identity"] != record["identity"]:
                raise ValueError("existing association cannot be reseeded or moved implicitly")
            return key  # Reopening the same evidence never resets next_phase.
        records[key] = record
        self._save(records)
        return key

    def snapshot(self, key):
        return copy.deepcopy(self._records()[key])

    def reserve(self, key, *, action, port, seconds):
        """Reserve an ordinary command; no phase override or retry interface."""
        if type(port) is not int or port not in (1, 2):
            raise ValueError("HTV213 port must be 1 or 2")
        if action not in ("open", "close") or type(seconds) is not int:
            raise ValueError("invalid control request")
        if (action == "open" and not 1 <= seconds <= 3600) or (action == "close" and seconds != 0):
            raise ValueError("bounded open or explicit close required")
        records = self._records()
        record = records[key]
        boundary = record.get("counter_boundary") or {}
        if boundary and not boundary.get("complete"):
            raise ValueError("explicit counter-boundary experiment in progress")
        wrap_qualified = wraps(record)
        if record["next_phase"] > 63 and not wrap_qualified:
            raise ValueError("counter wrap requires separate qualification")
        prior = record["transaction"]
        if action == "open":
            if record["state"] not in ("ready", "complete"):
                raise ValueError("prior command unresolved; no automatic resend or new open")
            duration = seconds
        else:
            if (record["state"] != "open_confirmed" or not prior or prior["port"] != port
                    or prior["idle"] or prior["action"] != "open"):
                raise ValueError("close requires this port's confirmed active open")
            duration = prior["requested_seconds"]
        phase = record["next_phase"] & 63 if wrap_qualified else record["next_phase"]
        transaction = {"command_id": uuid.uuid4().hex, "phase": phase,
                       "action": action, "port": port, "requested_seconds": duration,
                       "reserved_at": datetime.now(timezone.utc).isoformat(),
                       "acknowledged": False, "idle": False, "summary": False}
        if prior:
            record["history"].append(prior)
        record["next_phase"] = (phase + 1) & 63 if wrap_qualified else phase + 1
        record["transaction"] = transaction
        record["state"] = "reserved"
        self._save(records)  # Must succeed before a caller can transmit.
        return copy.deepcopy(transaction)

    def dispatch(self, key, transaction, sender):
        """Exactly once in this process; persist the attempt before callback."""
        records = self._records()
        record = records[key]
        if record["state"] != "reserved" or record["transaction"] != transaction:
            raise ValueError("stale, changed or already attempted transaction")
        record["state"] = "indeterminate"
        self._save(records)
        # Success here is still not RF acceptance. Exceptions leave the durable
        # indeterminate mark; no rollback, duplicate dispatch or inferred close.
        sender(copy.deepcopy(record["identity"]), copy.deepcopy(transaction))

    def observe(self, key, *, node_id, frame):
        """Only authenticated owner traffic should be passed by the caller."""
        decoded = packet(frame)
        if decoded is None:
            return False
        raw, command, phase, data = decoded
        records = self._records()
        record = records[key]
        identity = record["identity"]
        tx = record["transaction"]
        if (node_id != identity["node_id"] or raw[5:9].hex() != identity["controller"]
                or raw[9:13].hex() != identity["valve"] or tx is None
                or record["state"] in ("ready", "reserved", "complete")
                or raw[13] & 0x20):
            return False
        if command == 0xa1:
            if (phase != tx["phase"] or len(data) != 13 or data[0] != 0
                    or int.from_bytes(data[11:13], "little") != tx["requested_seconds"]):
                return False
            remaining = int.from_bytes(data[8:10], "little")
            if tx["action"] == "open":
                if data[1] != 0x21 or not 1 <= remaining <= tx["requested_seconds"] + 1:
                    return False
                record["state"] = "open_confirmed"
            else:
                if data[1] != 0x20 or remaining != 0:
                    return False
                record["state"] = "close_confirmed"
            tx["acknowledged"] = True
        elif command == 2:
            if (len(data) != 15 or data[0] != identity["selector"] or data[2] != tx["port"] or data[3] != 0
                    or data[10:12] != b"\0\0" or data[13:15] != b"\0\0"
                    or not tx["acknowledged"]):
                return False
            tx["idle"] = True
        elif command == 4:
            if (len(data) != 14 or data[0] != identity["selector"] or data[1] != tx["port"] or data[2] != 1 or data[7] != 0x21
                    or not tx["acknowledged"] or not tx["idle"]):
                return False
            elapsed = int.from_bytes(data[12:14], "little")
            if (elapsed > tx["requested_seconds"] or
                    (tx["action"] == "open" and elapsed != tx["requested_seconds"])):
                return False
            tx["summary"] = True
            tx["elapsed_seconds"] = elapsed
            record["state"] = "complete"
            boundary = tx.get("counter_boundary")
            if boundary and boundary["step"] == 3:
                record["counter_boundary"]["complete"] = True
        else:
            return False
        self._save(records)
        return True
