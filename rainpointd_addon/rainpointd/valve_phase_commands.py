"""Durable full-phase allocation behind the candidate control adapter.

The adapter is opt-in and candidate firmware only; production remains legacy.
It enforces exclusive ownership, independent state and radio receipts. Call
under the gateway lock.
This journal owns request identity/bytes, not watering state or recovery policy.
"""
from __future__ import annotations

import copy
from datetime import datetime
import json
import uuid

from .valve_command_phase import build_command, decode_envelope, matches_positive_result
from .valve_protocol import ValveLink
from .valve_phase_trial import assert_node_available

PREFIX = "valve_native_phase_commands_v1:"


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timezone-aware command timestamp required")
    return parsed


class FullPhaseCommandJournal:
    """One association's exact request reservations, preserved across restart.

    prepare() accepts a matched *latest* owner-authenticated RF exchange, not a
    telemetry phase or pairing reset assumption. Its caller must establish that
    provenance; this class validates frame/context and durable legacy state.
    Dispatch consumes the reservation before invoking the supplied transport.
    Missing/negative confirmation leaves it uncertain, with no retry or reseed.
    """
    def __init__(self, store, *, model: str, storage_key: str):
        if model not in ("HTV145FRF", "HTV405FRF"):
            raise ValueError("unsupported full-phase model")
        self.store, self.model, self.storage_key = store, model, storage_key
        self.key = PREFIX + model + ":" + storage_key

    def snapshot(self) -> dict | None:
        saved = self.store.metadata_value(self.key)
        return json.loads(saved) if saved is not None else None

    def _load(self):
        saved = self.store.metadata_value(self.key)
        if saved is None:
            raise RuntimeError("positive latest command exchange required")
        return saved, json.loads(saved)

    def _save(self, expected, record):
        self.store.compare_and_save_valve_command_phase(self.key, expected=expected,
            payload=json.dumps(record, sort_keys=True), model=self.model,
            storage_key=self.storage_key, legacy_state=record["legacy_state"])

    def prepare(self, *, node_id: str, request_frame: str, response_frame: str,
                baseline_at: str, now: str, port: int) -> dict:
        previous = self.store.metadata_value(self.key)
        if previous is not None:
            old = json.loads(previous)
            if old.get("active") or old.get("state") != "handed_back":
                raise RuntimeError("phase journal already exists; never reseed it")
        current = self.store.valve_phase_migration_state(self.model, self.storage_key)
        if node_id != current["node_id"] or not node_id:
            raise ValueError("positive exchange must belong to the retained owner")
        assert_node_available(self.store, node_id)
        maintenance = current["maintenance"]
        if (current["pending"] or current.get("revocation") or current.get("recovery")
                or current.get("maintenance_command")
                or maintenance not in (None, "completed", "confirmed", "failed", "idle", "ready", "cancelled")):
            raise RuntimeError("legacy command or maintenance is unresolved")
        if current["next_counter"] is None or (self.model == "HTV145FRF" and
                (not current["synchronized"] or current["source"] != "matching_immediate_response")):
            raise RuntimeError("authenticated legacy counter required")
        if (not current["latest_send"] or
                not _time(current["latest_send"]) <= _time(baseline_at) <= _time(now)):
            raise ValueError("positive baseline must follow the latest legacy send")
        request, response = decode_envelope(request_frame), decode_envelope(response_frame)
        if not request or not response or not matches_positive_result(
                request, response, model=self.model, port=port):
            raise ValueError("matching positive command result required")
        profile = current["profile"]
        if self.model == "HTV145FRF":
            a, b = profile["controller_endpoint"], profile["valve_endpoint"]
            counter = current["next_counter"] & 31
            expected_low_bit = int((request.data[2] == 1) == profile["command_marker_inverted"])
            residue = profile["trailer_residual"] if request.data[2] else profile["close_trailer_residual"]
            selector = None
        else:
            a, b = profile["valve_endpoint"], profile["control_companion_endpoint"]
            counter = current["next_counter"]
            expected_low_bit = request.data[2]
            residue, selector = 0x4f03, profile["control_selector"]
        link = ValveLink(bytes.fromhex(a), bytes.fromhex(b))
        action = "open" if request.data[2] else "close"
        seconds = int.from_bytes(request.data[3:5], "little") if action == "open" else None
        expected_request = build_command(model=self.model, link=link, phase=request.phase,
            action=action, port=port, duration_seconds=seconds, residue=residue, selector=selector)
        projected_counter = ((request.phase >> 1) + int(action == "open")) & 31
        if (request.raw != expected_request or request.phase & 1 != expected_low_bit
                or projected_counter != counter):
            raise ValueError("baseline does not match the current legacy recipe/profile/counter")
        record = dict(encoding="native-six-bit-v1", node_id=node_id,
            model=self.model, storage_key=self.storage_key,
            legacy_state=current, baseline_request=request_frame, baseline_response=response_frame,
            baseline_at=baseline_at, prepared_at=now, next_phase=(request.phase + 1) & 63,
            state="ready", pending=None, commands=[], failure=None)
        self._save(previous, record)
        return copy.deepcopy(record)

    def reserve(self, *, action: str, port: int, duration_seconds: int | None, now: str) -> dict:
        saved, record = self._load()
        if record["state"] != "ready" or record["pending"] is not None:
            raise RuntimeError("phase command unresolved; do not allocate another command")
        if record["next_phase"] == 0:
            raise RuntimeError("same-action rollover requires separate model qualification")
        previous = (record["commands"][-1]["attempted_at"] or record["commands"][-1]["reserved_at"]
                    if record["commands"] else record["baseline_at"])
        if (_time(now) - _time(previous)).total_seconds() < 15:
            raise RuntimeError("commands require a 15-second hardware interval")
        profile = record["legacy_state"]["profile"]
        if self.model == "HTV145FRF":
            a, b = profile["controller_endpoint"], profile["valve_endpoint"]
            residue = profile["trailer_residual"] if action == "open" else profile["close_trailer_residual"]
            selector = None
        else:
            a, b = profile["valve_endpoint"], profile["control_companion_endpoint"]
            residue, selector = 0x4f03, profile["control_selector"]
        frame = build_command(model=self.model, link=ValveLink(bytes.fromhex(a), bytes.fromhex(b)),
            phase=record["next_phase"], action=action, port=port,
            duration_seconds=duration_seconds, residue=residue, selector=selector)
        command = dict(command_id=uuid.uuid4().hex, phase=record["next_phase"], action=action,
            port=port, duration_seconds=duration_seconds, frame=frame.hex(), reserved_at=now,
            attempted_at=None, result_at=None, result_frame=None)
        record["commands"].append(command)
        record.update(next_phase=(command["phase"] + 1) & 63,
                      pending=command["command_id"], state="reserved")
        self._save(saved, record)  # Exact bytes and consumed phase precede every possible send.
        return copy.deepcopy(command)

    def dispatch(self, command_id: str, *, now: str, sender) -> None:
        saved, record = self._load()
        tx = record["commands"][-1]
        if record["state"] != "reserved" or record["pending"] != command_id:
            raise RuntimeError("command already attempted or reservation mismatched")
        if not 0 <= (_time(now) - _time(tx["reserved_at"])).total_seconds() <= 5:
            raise RuntimeError("reservation expired; never replay it after restart")
        tx["attempted_at"] = now
        record["state"] = "awaiting_result"
        self._save(saved, record)
        # The adapter may authorize one bounded *byte-identical* radio burst.
        # An exception cannot undo attempted_at or create a fresh phase retry.
        sender(record["node_id"], copy.deepcopy(tx))

    def observe_result(self, *, node_id: str, frame: str, observed_at: str) -> bool:
        saved, record = self._load()
        if record["state"] != "awaiting_result" or node_id != record["node_id"]:
            return False
        tx = record["commands"][-1]
        age = (_time(observed_at) - _time(tx["attempted_at"])).total_seconds()
        if not 0 <= age <= 15:
            return False
        request, response = decode_envelope(tx["frame"]), decode_envelope(frame)
        if (not response or response.command != 0xa1 or len(response.data) != 13
                or response.phase != tx["phase"]):
            return False
        a, b = request.route
        expected_route = (b if self.model == "HTV145FRF" else bytes((b[0] | 128,)) + b[1:], a)
        if response.route != expected_route:
            return False
        if response.data[0]:
            tx.update(result_at=observed_at, result_frame=frame, native_result=response.data[0])
            record.update(state="uncertain", failure="negative_native_result")
        elif matches_positive_result(request, response, model=self.model, port=tx["port"]):
            tx.update(result_at=observed_at, result_frame=frame, native_result=0)
            record.update(state="ready", pending=None)
        else:
            return False
        self._save(saved, record)
        return True

    def expire(self, *, now: str) -> bool:
        saved, record = self._load()
        if record["state"] not in ("reserved", "awaiting_result"):
            return False
        tx = record["commands"][-1]
        limit, since = (15, tx["attempted_at"]) if tx["attempted_at"] else (5, tx["reserved_at"])
        if (_time(now) - _time(since)).total_seconds() <= limit:
            return False
        record.update(state="uncertain", failure="missing_result" if tx["attempted_at"] else "undispatched_reservation")
        self._save(saved, record)
        return True
