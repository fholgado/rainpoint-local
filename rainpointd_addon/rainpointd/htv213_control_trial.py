"""Durable journal for explicitly admitted experimental dry controls.

Caller must hold the gateway lock and verify exact dry association/ownership.
Radio replies cannot seed an association. A reserved phase is never retried by
this module, including after restart or an indeterminate transport exception.
"""
from __future__ import annotations

import copy
import binascii
import json
import re
import uuid
from datetime import datetime, timezone

KEY = "htv213_dry_control_trial_v1"


def packet(frame):
    """Only checksum-valid, ordinary native-51 envelopes from the canary."""
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


class ControlJournal:
    def __init__(self, store):
        self.store = store

    def _records(self):
        return json.loads(self.store.metadata_value(KEY) or "{}")

    def _save(self, records):
        self.store.save_htv213_control_trial(json.dumps(records, sort_keys=True))

    def seed(self, *, node_id, controller, valve, selector, acknowledged_phase, evidence_id):
        """Explicit evidence-backed seed, not a restart/rejoin/idle reset."""
        if not isinstance(node_id, str) or not re.fullmatch(r"rp-[0-9a-f]{12}", node_id):
            raise ValueError("explicit test node required")
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
        key = controller + ":" + valve
        records = self._records()
        identity = dict(node_id=node_id, controller=controller, valve=valve,
                        selector=selector, evidence_id=evidence_id, seed_phase=acknowledged_phase)
        if key in records:
            if records[key]["identity"] != identity:
                raise ValueError("existing trial cannot be reseeded or moved implicitly")
            return key  # Reopening the same evidence never resets next_phase.
        records[key] = {"identity": identity, "next_phase": acknowledged_phase + 1,
                        "state": "ready", "transaction": None, "history": []}
        self._save(records)
        return key

    def snapshot(self, key):
        return copy.deepcopy(self._records()[key])

    def reserve(self, key, *, action, port, seconds, dry_confirmed):
        if dry_confirmed is not True:
            raise ValueError("dry test confirmation required")
        if type(port) is not int or port not in (1, 2):
            raise ValueError("HTV213 port must be 1 or 2")
        if action not in ("open", "close") or type(seconds) is not int:
            raise ValueError("invalid dry control request")
        if (action == "open" and not 1 <= seconds <= 3600) or (action == "close" and seconds != 0):
            raise ValueError("bounded dry open or explicit close required")
        records = self._records()
        record = records[key]
        boundary = record.get("counter_boundary") or {}
        if boundary and not boundary.get("complete"):
            raise ValueError("explicit counter-boundary experiment in progress")
        wrap_qualified = boundary.get("complete") is True
        if record["next_phase"] > 63 and not wrap_qualified:
            raise ValueError("counter wrap requires separate qualification")
        prior = record["transaction"]
        if action == "open":
            if record["state"] not in ("ready", "complete"):
                raise ValueError("prior trial unresolved; no automatic resend or new open")
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

    def reserve_boundary_probe(self, key, *, prior_command_id, authorization_id, port,
                               seconds, dry_confirmed):
        """Once-only 62,63,0,1 dry experiment; never a normal recovery policy.

        Preserve the real prior next phase instead of fabricating a successful
        seed. Each step needs the previous genuine ACK, idle and summary. An
        uncertain send cannot advance, restart this sequence or reuse its phase.
        """
        if (dry_confirmed is not True or type(port) is not int or port not in (1, 2)
                or type(seconds) is not int or seconds != 60):
            raise ValueError("counter boundary requires one-minute dry controls")
        for value in (prior_command_id, authorization_id):
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
                raise ValueError("explicit prior transaction and authorization required")
        records = self._records()
        record = records[key]
        prior = record["transaction"]
        if (record["state"] != "complete" or not prior or
                prior["command_id"] != prior_command_id or
                not all(prior.get(f) for f in ("acknowledged", "idle", "summary"))):
            raise ValueError("prior boundary step must be genuinely complete")
        boundary = record.get("counter_boundary")
        if boundary is None:
            boundary = dict(authorization_id=authorization_id, port=port,
                            origin_next_phase=record["next_phase"], reserved_steps=0, complete=False)
        elif (boundary["authorization_id"] != authorization_id or boundary["port"] != port
              or boundary["reserved_steps"] >= 4 or boundary["complete"]):
            raise ValueError("counter-boundary authorization exhausted or changed")
        step = boundary["reserved_steps"]
        phase = (62, 63, 0, 1)[step]
        tx = dict(command_id=uuid.uuid4().hex, phase=phase, action="open", port=port,
                  requested_seconds=seconds, reserved_at=datetime.now(timezone.utc).isoformat(),
                  acknowledged=False, idle=False, summary=False,
                  counter_boundary=dict(authorization_id=authorization_id, step=step,
                                        prior_next_phase=record["next_phase"]))
        record["history"].append(prior)
        boundary["reserved_steps"] += 1
        record.update(transaction=tx, state="reserved", next_phase=phase + 1, counter_boundary=boundary)
        self._save(records)
        return copy.deepcopy(tx)

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

    def reserve_crc_retrial(self, key, *, prior_command_id, evidence_sha256,
                            authorization_id, port, seconds, dry_confirmed):
        """One manual corrected-frame experiment, never recovery policy.

        Admission requires a separately reviewed capture proving the original
        CRC was malformed. Keep the original attempt and its phase reservation;
        this tests the same command with the corrected physical final symbol.
        The digest is an audit reference, not automatic RF proof validation.
        """
        if (dry_confirmed is not True or type(port) is not int or port not in (1, 2)
                or type(seconds) is not int or not 1 <= seconds <= 120):
            raise ValueError("bounded dry retrial required")
        for value, length in ((prior_command_id, 32), (evidence_sha256, 64), (authorization_id, 32)):
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{%d}" % length, value):
                raise ValueError("explicit prior attempt, CRC evidence and authorization required")
        records = self._records()
        record = records[key]
        prior = record["transaction"]
        if (record["state"] != "indeterminate" or not prior
                or prior["command_id"] != prior_command_id or prior["action"] != "open"
                or prior["acknowledged"] or prior["port"] != port
                or prior["requested_seconds"] != seconds or prior.get("crc_retrial")
                or any(tx.get("crc_retrial") for tx in record["history"])):
            raise ValueError("CRC retrial requires the original unconfirmed open; once only")
        tx = copy.deepcopy(prior)
        tx.update(command_id=uuid.uuid4().hex, crc_retrial={
            "prior_command_id": prior_command_id, "evidence_sha256": evidence_sha256,
            "authorization_id": authorization_id})
        record["history"].append(prior)
        record["transaction"] = tx
        record["state"] = "reserved"
        self._save(records)
        return copy.deepcopy(tx)

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
