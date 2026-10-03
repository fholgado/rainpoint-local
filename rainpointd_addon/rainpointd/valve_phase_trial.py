"""Durable journal for an explicitly admitted installed-valve phase canary.

Admission/transport integration must verify the registry owner, a fresh idle
state, no later/unresolved command, schedule exclusion and signed capabilities.
Call under the gateway lock. Never import this as a generic recovery policy.
"""
from __future__ import annotations

import copy
from datetime import datetime
import json
import re
import uuid
from .valve_protocol import decode_htv405_control_frame
from .valve_command_phase import decode_envelope

KEY = "valve_adjacent_phase_trial_v1"


def assert_node_available(store, node_id):
    """Stop production reservations before they alter an experimental owner."""
    if store is None:
        return
    if store.native_valve_node_owned(node_id):
        raise RuntimeError("radio has an exclusive native counter owner")
    records = json.loads(store.metadata_value(KEY) or "{}")
    if any(r["identity"]["node_id"] == node_id and r["state"] not in ("released", "recovered")
           for r in records.values()):
        raise RuntimeError("radio has an unresolved full-phase trial")


def packet(frame):
    envelope = decode_envelope(frame)
    return (envelope.raw, envelope.command, envelope.phase, envelope.data) if envelope else None


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timezone-aware observation required")
    return parsed


def positive_open_mode(mode, *, model, port):
    """Stock mode or the captured generated four-zone outlet/state nibble."""
    return mode == 0x21 or (model == 'HTV405FRF' and mode == ((port << 5) | 1))


class PhaseTrialJournal:
    def __init__(self, store):
        self.store = store

    def _records(self):
        return json.loads(self.store.metadata_value(KEY) or "{}")

    def _save(self, records):
        self.store.save_valve_phase_trial(json.dumps(records, sort_keys=True))

    def snapshot(self, key):
        return copy.deepcopy(self._records()[key])

    def prepare(self, *, authorization_id, model, node_id, request_frame,
                response_frame, report_route, selector, evidence_id, now, expires_at,
                admission=None, port=1):
        """Retain an explicit baseline; never seed from a telemetry counter.

        Caller must tie these bytes to the selected registry association and
        prove there was no subsequent send. This method supplies no admission.
        """
        for value in (authorization_id, evidence_id):
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
                raise ValueError("explicit authorization and evidence references required")
        if model not in ("HTV145FRF", "HTV405FRF"):
            raise ValueError("one- or four-zone model required")
        if type(port) is not int or not 1 <= port <= (4 if model=="HTV405FRF" else 1):
            raise ValueError("invalid trial port for model")
        if not isinstance(node_id, str) or not re.fullmatch(r"rp-[0-9a-f]{12}", node_id):
            raise ValueError("explicit authenticated owner required")
        if type(selector) is not int or not 1 <= selector <= 15:
            raise ValueError("retained selector required")
        if (not isinstance(report_route, list) or len(report_route) != 2 or
                any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{8}", v)
                    or v in ("00000000", "80000000") for v in report_route) or
                report_route[0] == report_route[1]):
            raise ValueError("explicit report route required")
        if not 120 <= (timestamp(expires_at)-timestamp(now)).total_seconds() <= 3600:
            raise ValueError("trial permission must expire within an hour")
        request, response = packet(request_frame), packet(response_frame)
        if (not request or not response or request[1] != 0x21 or response[1] != 0xa1
                or request[2] != response[2] or len(response[3]) != 13 or response[3][0] != 0
                or len(request[3]) not in (3, 5)
                or not (request[3][:2] == bytes((port,2)) or
                    (model=='HTV405FRF' and request[3][:2]==bytes((1,port<<1))))
                or request[3][2] not in (0, 1)
                or len(request[3]) != (5 if request[3][2] else 3)
                or (not positive_open_mode(response[3][1],model=model,port=port)
                    if request[3][2] else response[3][1]!=0x20)
                or (request[3][2] and (not 1 <= int.from_bytes(request[3][3:5], "little") <= 3600
                    or response[3][11:13] != request[3][3:5]))):
            raise ValueError("matching positive selected-outlet command baseline required")
        # HTV145 reverses routes. HTV405 returns companion-with-role to source.
        a, b = request[0][5:9], request[0][9:13]
        expected_a = b if model == "HTV145FRF" else bytes((b[0] | 128,)) + b[1:]
        if (a in (bytes(4), bytes.fromhex("80000000"))
                or b in (bytes(4), bytes.fromhex("80000000")) or a == b
                or response[0][5:13] != expected_a + a
                or report_route != [expected_a.hex(), a.hex()]):
            raise ValueError("baseline response belongs to another association")
        if request[2] >= 61:
            raise ValueError("phase-zero boundary testing requires separate authorization")
        records = self._records()
        identity = dict(model=model, node_id=node_id, request_route=[a.hex(), b.hex()],
                        response_route=[expected_a.hex(), a.hex()], report_route=report_route,
                        selector=selector, evidence_id=evidence_id, port=port)
        if admission is not None:
            identity["admission"] = copy.deepcopy(admission)
        if authorization_id in records:
            raise ValueError("authorization is already recorded; never reseed")
        if any(r["identity"]["request_route"] == identity["request_route"] and
               r["state"] not in ("released", "recovered") for r in records.values()):
            raise ValueError("association has an unresolved trial")
        records[authorization_id] = dict(identity=identity, baseline_request=request_frame,
            baseline_response=response_frame, initial_phase=(request[2]+1)&63,
            next_phase=(request[2]+1)&63, prepared_at=now, expires_at=expires_at,
            state="ready", transactions=[])
        self._save(records)
        return authorization_id

    def reserve(self, key, *, now):
        records = self._records(); record = records[key]
        if (record["state"] not in ("ready", "between_runs") or
                len(record["transactions"]) >= 2):
            raise ValueError("trial unresolved or watering allowance exhausted")
        if (timestamp(now) < timestamp(record["prepared_at"]) or
                (timestamp(record["expires_at"])-timestamp(now)).total_seconds() < 125):
            raise ValueError("insufficient permission window for one bounded run")
        if record["transactions"] and timestamp(now) <= timestamp(record["transactions"][-1]["idle_at"]):
            raise ValueError("next run must follow independently confirmed idle")
        tx = dict(command_id=uuid.uuid4().hex, phase=record["next_phase"], port=record["identity"].get("port",1),
                  seconds=60, reserved_at=now, attempted_at=None, ack_at=None,
                  watering_at=None, idle_at=None)
        record["transactions"].append(tx)
        record.update(state="reserved", next_phase=(tx["phase"]+1)&63)
        self._save(records)
        return copy.deepcopy(tx)

    def dispatch(self, key, tx, *, now, sender):
        records = self._records(); record = records[key]
        if record["state"] != "reserved" or record["transactions"][-1] != tx:
            raise ValueError("stale or already attempted reservation")
        if not 0 <= (timestamp(now)-timestamp(tx["reserved_at"])).total_seconds() <= 5:
            raise ValueError("reservation expired; never replay it after restart")
        record["state"] = "attempted"
        record["transactions"][-1]["attempted_at"] = now
        self._save(records)  # Failure/exception after this point cannot resend.
        sender(copy.deepcopy(record["identity"]), copy.deepcopy(record["transactions"][-1]))

    def expire(self, key, *, now):
        records = self._records(); record = records[key]
        if record["state"] not in ("attempted", "observing"):
            return False
        tx = record["transactions"][-1]
        age = (timestamp(now)-timestamp(tx["attempted_at"])).total_seconds()
        if (not tx["ack_at"] and age > 15) or age > 125:
            record.update(state="failed", failure="missing_confirmation")
            self._save(records)
            return True
        return False

    def observe(self, key, *, node_id, frame, observed_at):
        records = self._records(); record = records[key]
        if record["state"] not in ("attempted", "observing"):
            return False
        parsed = packet(frame)
        if not parsed or node_id != record["identity"]["node_id"]:
            return False
        raw, command, phase, data = parsed
        tx = record["transactions"][-1]; identity = record["identity"]
        age = (timestamp(observed_at)-timestamp(tx["attempted_at"])).total_seconds()
        if age < 0: return False
        route = [raw[5:9].hex(), raw[9:13].hex()]
        if command == 0xa1:
            if route != identity["response_route"] or phase != tx["phase"] or len(data) != 13:
                return False
            if self.expire(key, now=observed_at): return False
            if data[0] != 0:
                record.update(state="failed", failure="negative_response", native_result=data[0])
                self._save(records)
                return True
            if (not positive_open_mode(data[1],model=identity['model'],port=tx['port']) or int.from_bytes(data[11:13], "little") != 60 or
                    not 1 <= int.from_bytes(data[8:10], "little") <= 61):
                return False
            if not tx["ack_at"]:
                tx.update(ack_at=observed_at, ack_frame=frame)
        elif command == 2:
            if (route != identity["report_route"] or len(data) != 15 or
                    data[0] != identity["selector"]):
                return False
            if self.expire(key, now=observed_at): return False
            remaining = int.from_bytes(data[10:12], "little")
            requested = int.from_bytes(data[13:15], "little")
            four = decode_htv405_control_frame(raw) if identity['model']=='HTV405FRF' else None
            active = (four['is_watering'] and four['zone']==tx['port']) if four else data[2]==tx['port'] and data[3]==0x21
            idle = (not four['is_watering'] and four['zone'] in (0,tx['port'])) if four else data[2]==tx['port'] and data[3]==0
            if active and requested == 60 and 0 < remaining <= 61:
                if not tx["watering_at"]:
                    tx.update(watering_at=observed_at, watering_frame=frame)
            elif (idle and remaining == requested == 0 and tx["watering_at"]
                    and timestamp(observed_at) > timestamp(tx["watering_at"]) and age >= 55):
                tx.update(idle_at=observed_at, idle_frame=frame)
            else: return False
        else:
            return False
        record["state"] = "observing"
        if all(tx[k] for k in ("ack_at", "watering_at", "idle_at")):
            record["state"] = "complete" if len(record["transactions"]) == 2 else "between_runs"
        self._save(records)
        return True

    def fail(self, key, reason):
        records = self._records()
        if records[key]["state"] not in ("complete", "releasing", "released", "recovering", "recovered"):
            records[key].update(state="failed", failure=reason)
            self._save(records)

    def acknowledge_release(self, key, *, node_id, phase):
        records = self._records(); record = records[key]
        if (record["state"] != "releasing" or node_id != record["identity"]["node_id"]
                or phase != record["transactions"][-1]["phase"]):
            return False
        record["state"] = "released"
        self._save(records)
        return True

    def acknowledge_recovery(self, key, *, node_id, phase, command_id):
        records = self._records(); record = records[key]
        if (record["state"] != "recovering" or node_id != record["identity"]["node_id"]
                or phase != record["transactions"][-1]["phase"]
                or command_id != record["recovery"]["command_id"]):
            return False
        record["state"] = "recovered"
        self._save(records)
        return True
