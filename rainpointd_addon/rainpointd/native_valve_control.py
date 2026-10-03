"""Candidate standard-control adapter for durable native six-bit ownership.

No CLI/config/UI switch activates this path. The explicit source-only gateway
flag and a matched retained exchange are required for qualification. Once an
epoch owns a radio, disabling that flag never falls back to the old allocator.
Restart only observes receipts; it never replays an attempted OPEN or CLOSE.
"""
from __future__ import annotations

from datetime import timedelta
import uuid

from .valve_command_phase import decode_envelope, matches_positive_result
from .valve_phase_commands import FullPhaseCommandJournal, _time
from .valve_protocol import decode_htv405_control_frame

CAPABILITY = "valve_native_phase_v1"
HANDOFF_CAPABILITY = "valve_native_handoff_v1"
SCOPE_CAPABILITY = "valve_native_scope_v1"


class NativeValveControl:
    def __init__(self, store, node, sender, *, enabled=False):
        self.store, self.node, self.sender, self.enabled = store, node, sender, enabled
        self.receipted_nodes = set()  # Never restore session readiness from SQLite.

    def disconnect(self, node_id):
        self.receipted_nodes.discard(node_id)

    def _journal(self, record):
        return FullPhaseCommandJournal(self.store, model=record["model"],
                                       storage_key=record["storage_key"])

    def owner(self, *, device_id=None, node_id=None):
        return next((r for r in self.store.native_valve_commands() if r.get("active")
            and (device_id is None or r["device_id"] == device_id)
            and (node_id is None or r["node_id"] == node_id)), None)

    def _available(self, record):
        node = self.node(record["node_id"])
        return (self.enabled and node.get("connected") is True and node.get("authenticated") is True
                and CAPABILITY in node.get("capabilities", [])
                and (not record.get("qualification") or SCOPE_CAPABILITY in node.get("capabilities", []))
                and node.get("rf_mode", "normal") == "normal"
                and node.get("tx_armed") is not True and node.get("node_reboot_pending") is not True
                and node.get("radio_ready") is not False)

    def activate(self, *, model, storage_key, device_id, node_id, request_frame,
                 response_frame, baseline_at, idle_frame, idle_at, port, now,
                 qualification_seconds=None, maximum_commands=None):
        """Caller proves latest owner-authenticated baseline in the RF journal.

        A fresh *native 02 idle report* is mandatory, not a reducer timestamp or
        an a1 accepted result. Admission takes the whole radio exclusively for
        this first candidate; multi-association radio qualification is separate.
        """
        candidate = dict(node_id=node_id)
        qualification = None
        if qualification_seconds is not None or maximum_commands is not None:
            if (type(qualification_seconds) is not int or not 120 <= qualification_seconds <= 900
                    or type(maximum_commands) is not int or not 1 <= maximum_commands <= 2):
                raise ValueError("qualification requires a 120..900-second window and one or two opens")
            qualification = dict(port=port, maximum_commands=maximum_commands,
                expires_at=(_time(now)+timedelta(seconds=qualification_seconds)).isoformat())
        if not self._available(candidate):
            raise RuntimeError("native candidate firmware and explicit opt-in required")
        if qualification and SCOPE_CAPABILITY not in self.node(node_id).get("capabilities", []):
            raise RuntimeError("radio must independently enforce the bounded qualification")
        if self.owner(node_id=node_id):
            raise RuntimeError("radio already has a native owner")
        if (not _time(baseline_at) <= _time(idle_at) <= _time(now)
                or not 0 <= (_time(now) - _time(idle_at)).total_seconds() <= 120):
            raise ValueError("fresh independent idle required")
        idle = decode_envelope(idle_frame)
        if not idle or idle.command != 2 or len(idle.data) != 15 or not 1 <= idle.data[0] <= 15:
            raise ValueError("independent native idle report required")
        selector = idle.data[0]
        preview = dict(model=model, baseline_request=request_frame, baseline_response=response_frame,
            selector=selector, legacy_state=self.store.valve_phase_migration_state(model, storage_key))
        physical = self._physical(preview, idle_frame)
        if physical is None or physical["watering"] or physical["port"] not in (0, port):
            raise ValueError("native idle report belongs to another owner/outlet")
        journal = FullPhaseCommandJournal(self.store, model=model, storage_key=storage_key)
        record = journal.prepare(node_id=node_id, request_frame=request_frame,
            response_frame=response_frame, baseline_at=baseline_at, now=now, port=port)
        # Retain the observed report selector separately from request carrier/phase.
        record.update(device_id=device_id, epoch=uuid.uuid4().hex, active=True, selector=selector,
                      radio_ready=False, receipt=None, transaction=None, physical=None, run=None,
                      qualification=qualification, admission_port=port)
        record["physical"] = {**physical, "observed_at": idle_at, "frame": idle_frame}
        saved, _ = journal._load()
        journal._save(saved, record)  # Exclusive ownership precedes the adoption write.
        self.sender(node_id, dict(type="valve_native_adopt", command_id=record["epoch"],
            epoch=record["epoch"], model=model, endpoint_a=request_frame[10:18],
            endpoint_b=request_frame[18:26], request_frame=request_frame,
            response_frame=response_frame, next_phase=record["next_phase"], port=port,
            selector=record["legacy_state"]["profile"]["control_selector"] if model=="HTV405FRF" else selector,
            report_selector=selector, qualification_seconds=qualification_seconds or 0,
            maximum_commands=maximum_commands or 0))
        return record

    def request(self, record, *, action, port, duration_seconds, now, qualification_epoch=None):
        scope = record.get("qualification")
        if scope and (qualification_epoch != record["epoch"] or action != "open"
                or port != scope["port"] or duration_seconds != 60
                or _time(now) >= _time(scope["expires_at"])
                or len(record["commands"]) >= scope["maximum_commands"]
                or record.get("qualification_rf_disabled")):
            raise PermissionError("native qualification scope is exhausted, expired or unauthorized")
        if not self._available(record) or not record["radio_ready"] or record["node_id"] not in self.receipted_nodes:
            raise RuntimeError("native radio receipt unavailable; no legacy fallback")
        if self.projection(record, now=now)["rf_control_transaction_active"]:
            raise RuntimeError("native command awaiting evidence")
        physical = record.get("physical")
        if record["state"] != "ready":
            raise RuntimeError("native command uncertain; verified recovery required")
        ready = self.projection(record, now=now, qualification_epoch=qualification_epoch)
        if not ready["rf_control_available"]:
            raise RuntimeError(ready["rf_control_unavailable_reason"])
        if (not physical or not 0 <= (_time(now)-_time(physical["observed_at"])).total_seconds() <= 120
                or (action == "open" and physical["watering"])
                or (action == "close" and physical["watering"] and physical["port"] != port)):
            raise RuntimeError("fresh selected valve state required")
        journal = self._journal(record)
        tx = journal.reserve(action=action, port=port, duration_seconds=duration_seconds, now=now)
        saved, record = journal._load()
        record["transaction"] = dict(id=tx["command_id"], state="waiting_for_confirmation",
            action=action, zone=port, duration_seconds=duration_seconds, started_at=now,
            updated_at=now, accepted_at=None, physical_at=None, error=None)
        record["receipt"] = None
        journal._save(saved, record)
        def send(node_id, command):
            self.sender(node_id, dict(type="valve_native_command", epoch=record["epoch"],
                model=record["model"], **command))
        try:
            journal.dispatch(tx["command_id"], now=now, sender=send)
        except Exception:
            # A write error may have happened after the radio received bytes.
            # Retain the attempted frame and fail immediately, without replay.
            saved, failed = journal._load()
            self._fail(failed, "transport_dispatch_uncertain", now)
            journal._save(saved, failed)
            raise
        return dict(state="pending_valve_evidence", command_id=tx["command_id"])

    def authorize(self, node_id, message):
        record = self.owner(node_id=node_id)
        if not record or message.get("epoch") != record["epoch"]:
            raise ValueError("native command has no retained exclusive epoch")
        if message["type"] == "valve_native_status":
            return
        if not self._available(record):
            raise RuntimeError("native candidate unavailable")
        if message["type"] in ("valve_native_recover", "valve_native_handback"):
            operation = record.get("handoff") or {}
            if (HANDOFF_CAPABILITY not in self.node(node_id).get("capabilities", [])
                    or operation.get("state") not in ("requested", "uncertain")
                    or message != operation.get("message")):
                raise ValueError("native maintenance differs from retained proof")
            return
        if message["type"] == "valve_native_adopt":
            scope = record.get("qualification")
            expected_seconds = int((_time(scope["expires_at"])-_time(record["prepared_at"])).total_seconds()) if scope else 0
            if (record["commands"] or message.get("command_id") != record["epoch"]
                    or message.get("request_frame") != record["baseline_request"]
                    or message.get("response_frame") != record["baseline_response"]
                    or message.get("next_phase") != record["next_phase"]
                    or message.get("model") != record["model"]
                    or message.get("port") != record["admission_port"]
                    or message.get("report_selector") != record["selector"]
                    or message.get("selector") != (record["legacy_state"]["profile"]["control_selector"]
                        if record["model"]=="HTV405FRF" else record["selector"])
                    or message.get("maximum_commands", 0) != (scope["maximum_commands"] if scope else 0)
                    or message.get("qualification_seconds", 0) != expected_seconds):
                raise ValueError("adoption differs from durable baseline")
            return
        tx = record["commands"][-1] if record["commands"] else None
        if (record["state"] != "awaiting_result" or not tx
                or any(message.get(k) != tx[k] for k in
                       ("command_id", "frame", "phase", "action", "port", "duration_seconds"))):
            raise ValueError("native dispatch differs from durable attempted bytes")

    def maintain(self, record, *, operation, now):
        """Explicit no-RF recovery or legacy handback, never a phase guess.

        Recovery repairs missing physical confirmation only. A durable positive
        result must already be known at both gateway and radio. Late idle cannot
        turn the original failed watering transaction into success.
        """
        if operation not in ("recover", "handback"):
            raise ValueError("unsupported native maintenance")
        if (not self._available(record) or record["node_id"] not in self.receipted_nodes
                or HANDOFF_CAPABILITY not in self.node(record["node_id"]).get("capabilities", [])):
            raise RuntimeError("fresh handoff-capable owner receipt required")
        previous = record.get("handoff") or {}
        if previous.get("state") in ("requested", "uncertain"):
            if previous["kind"] != operation:
                raise RuntimeError("a different native handoff is unresolved")
            # Only an explicitly requested byte-identical no-RF retry is allowed.
            self.sender(record["node_id"], previous["message"])
            return previous
        tx = record["commands"][-1] if record["commands"] else None
        receipt, physical = record.get("receipt") or {}, record.get("physical") or {}
        if (not tx or not tx["result_at"] or not tx["result_frame"]
                or not matches_positive_result(decode_envelope(tx["frame"]), decode_envelope(tx["result_frame"]),
                    model=record["model"], port=tx["port"])
                or receipt.get("stage") != "accepted" or receipt.get("command_id") != tx["command_id"]
                or receipt.get("frame") != tx["frame"]):
            raise RuntimeError("exact persisted positive command result required")
        if (physical.get("watering") is not False or physical.get("port") not in (0, tx["port"])
                or not physical.get("frame") or not 0 <= (_time(now)-_time(physical["observed_at"])).total_seconds() <= 120
                or _time(physical["observed_at"]) < _time(tx["result_at"])
                or (tx["action"] == "open" and _time(physical["observed_at"]) <
                    _time(tx["attempted_at"]) + timedelta(seconds=tx["duration_seconds"]))):
            raise RuntimeError("fresh independent post-command idle required")
        if operation == "recover":
            if record["state"] != "uncertain" or record["failure"] != "missing_independent_confirmation":
                raise RuntimeError("uncertain counter or native rejection cannot be recovered by idle")
        elif (record["state"] != "ready" or (record.get("transaction") or {}).get("state") != "confirmed"
                or tx["phase"] > 62 or (tx["action"] == "close" and tx["phase"] & 1)):
            raise RuntimeError("qualified legacy return recipe required")
        command_id = uuid.uuid4().hex
        message = dict(type="valve_native_"+operation, command_id=command_id, epoch=record["epoch"],
            model=record["model"], attempted_command_id=tx["command_id"], phase=tx["phase"],
            frame=tx["frame"], result_frame=tx["result_frame"], idle_frame=physical["frame"])
        journal = self._journal(record)
        saved, record = journal._load()
        if previous:
            record.setdefault("maintenance_history", []).append(previous)
        handoff = dict(id=command_id, kind=operation, state="requested", requested_at=now,
            message=message, idle_at=physical["observed_at"], legacy_counter=(tx["phase"]+1)//2,
            previous_failure=record["failure"], previous_transaction=record.get("transaction"))
        record.update(handoff=handoff, state="recovering" if operation=="recover" else "handing_back")
        journal._save(saved, record)
        try:
            self.sender(record["node_id"], message)
        except Exception:
            saved, record = journal._load()
            record["handoff"].update(state="uncertain", error="native_handoff_transport_uncertain")
            journal._save(saved, record)
            raise
        return handoff

    def receipt(self, node_id, message, *, now):
        record = self.owner(node_id=node_id)
        if not record or message.get("epoch") != record["epoch"]:
            return False
        journal = self._journal(record)
        saved, record = journal._load()
        stage = message.get("stage")
        if record.get("qualification"):
            remaining = message.get("qualification_remaining_ms")
            if type(remaining) is not int or not 0 <= remaining <= 900_000:
                return False
            record["qualification_rf_disabled"] = remaining == 0
        handoff = record.get("handoff") or {}
        if handoff.get("state") in ("requested", "uncertain"):
            tx = record["commands"][-1]
            expected_stage = "released" if handoff["kind"]=="handback" else "accepted"
            if (message.get("maintenance_id") == handoff["id"] and message.get("maintenance_kind") == handoff["kind"]
                    and stage == expected_stage and message.get("command_id") == tx["command_id"]
                    and message.get("frame") == tx["frame"] and message.get("phase") == tx["phase"]):
                if handoff["kind"] == "handback":
                    if type(message.get("legacy_counter")) is not int or message["legacy_counter"] != handoff["legacy_counter"]:
                        return False
                    self.store.complete_native_valve_handback(journal.key, expected=saved, observed_at=now)
                    self.receipted_nodes.discard(node_id)
                else:
                    record["handoff"].update(state="completed", completed_at=now)
                    record.update(state="ready", pending=None, failure=None)
                    journal._save(saved, record)
                    self.receipted_nodes.add(node_id)
                return True
            if message.get("maintenance_id") is not None:
                return False  # An unrelated maintenance receipt is not ordinary readiness.
        if not record["commands"]:
            if (stage != "ready" or message.get("phase") != record["next_phase"]
                    or message.get("command_id") != record["epoch"]):
                return False
            record["radio_ready"] = True
        else:
            tx = record["commands"][-1]
            if (message.get("command_id") != tx["command_id"] or message.get("frame") != tx["frame"]
                    or message.get("phase") != tx["phase"] or stage not in ("attempted", "accepted", "uncertain")):
                return False
            # The radio receipt is a durable send record, not independent RF proof.
            record["receipt"] = dict(command_id=tx["command_id"], frame=tx["frame"], stage=stage)
            if stage == "uncertain":
                self._fail(record, "radio_attempt_uncertain", now)
            self._complete(record, now)
        remaining = message.get("minimum_interval_ms")
        if remaining is not None:
            if type(remaining) is not int or not 0 <= remaining <= 15_000:
                return False
            record["radio_not_before"] = (_time(now) + timedelta(milliseconds=remaining)).isoformat()
        journal._save(saved, record)
        if stage in ("ready", "accepted"):
            self.receipted_nodes.add(node_id)
        return True

    def error(self, node_id, message, *, now):
        record = self.owner(node_id=node_id)
        if not record:
            return False
        expected = record["commands"][-1]["command_id"] if record["commands"] else record["epoch"]
        handoff = record.get("handoff") or {}
        if handoff.get("state") in ("requested", "uncertain") and message.get("command_id") == handoff["id"]:
            journal = self._journal(record)
            saved, record = journal._load()
            record["handoff"].update(state="uncertain", error="native_handoff_rejected")
            journal._save(saved, record)
            return True
        if message.get("command_id") != expected:
            return False
        journal = self._journal(record)
        saved, record = journal._load()
        self._fail(record, "radio_rejected_native_command", now)
        journal._save(saved, record)
        return True

    def _physical(self, record, frame):
        report = decode_envelope(frame)
        baseline = decode_envelope(record["baseline_response"])
        if not report or report.command != 2 or len(report.data) != 15 or report.route != baseline.route:
            return None
        selector = record["selector"]
        if report.data[0] != selector:
            return None
        data = report.data
        if record["model"] == "HTV405FRF":
            # Routine subtype 0e cycles its index independently of outlet.
            # Only the fully idle form is qualified here: no run marker and
            # both timer fields zero. Never infer a port from that index.
            if (data[1] == 0x0e and data[3] == 0 and data[4] == 0x9f
                    and data[8:10] == bytes.fromhex("0081") and data[12] == 0xad
                    and not any(data[10:12] + data[13:15])):
                return dict(watering=False, port=0, remaining=0, requested=0)
            decoded = decode_htv405_control_frame(report.raw)
            if not decoded or not isinstance(decoded.get("is_watering"), bool):
                return None
            watering, port = decoded["is_watering"], decoded["zone"]
        else:
            if data[2] != 1 or data[3] not in (0, 0x21):
                return None
            watering, port = data[3] == 0x21, 1
        remaining, requested = int.from_bytes(data[10:12], "little"), int.from_bytes(data[13:15], "little")
        if (not watering and (remaining or requested)) or (watering and not 0 < remaining <= requested + 1 <= 3601):
            return None
        return dict(watering=watering, port=port, remaining=remaining, requested=requested)

    def observe(self, node_id, frame, *, now):
        record = self.owner(node_id=node_id)
        if not record:
            return False
        previous = record
        envelope = decode_envelope(frame)
        baseline = decode_envelope(record["baseline_response"])
        if not envelope or envelope.command not in (2, 0xa1) or envelope.route != baseline.route:
            return False
        journal = self._journal(record)
        self.tick(record, now=now)
        matched = journal.observe_result(node_id=node_id, frame=frame, observed_at=now)
        saved, record = journal._load()
        if envelope.command == 0xa1 and len(envelope.data) == 13 and not matched:
            known = frame == record["baseline_response"] or any(
                frame == command["result_frame"] or matches_positive_result(
                    decode_envelope(command["frame"]), envelope, model=record["model"], port=command["port"])
                for command in record["commands"])
            if not known:
                self._fail(record, "unrecognized_native_result", now)
        tx = record.get("transaction")
        if tx and record["commands"][-1]["result_at"]:
            if record["state"] == "uncertain":
                self._fail(record, record["failure"], now)
            else:
                tx["accepted_at"] = record["commands"][-1]["result_at"]
        physical = self._physical(record, frame)
        if physical and (not record.get("physical") or _time(now) > _time(record["physical"]["observed_at"])):
            record["physical"] = {**physical, "observed_at": now, "frame": frame}
            if not physical["watering"] and physical["port"] in (0, (record.get("run") or {}).get("port")):
                record["run"] = None
            if tx and tx["state"] == "waiting_for_confirmation" and _time(now) > _time(tx["started_at"]):
                if ((tx["action"] == "open" and physical["watering"] and physical["port"] == tx["zone"]
                        and physical["requested"] == tx["duration_seconds"])
                        or (tx["action"] == "close" and not physical["watering"]
                            and physical["port"] in (0, tx["zone"]))):
                    tx["physical_at"] = now
        self._complete(record, now)
        journal._save(saved, record)
        return record != previous

    @staticmethod
    def _fail(record, reason, now):
        record.update(state="uncertain", failure=reason)
        if record.get("transaction"):
            record["transaction"].update(state="failed", error=reason, updated_at=now)

    @staticmethod
    def _complete(record, now):
        tx = record.get("transaction")
        if (tx and tx["state"] == "waiting_for_confirmation" and tx["accepted_at"]
                and tx["physical_at"] and (record.get("receipt") or {}).get("stage") == "accepted"):
            tx.update(state="confirmed", updated_at=now)
            if tx["action"] == "open" and (record.get("physical") or {}).get("watering"):
                record["run"] = dict(command_id=tx["id"], port=tx["zone"], started_at=tx["started_at"],
                    expected_idle_at=(_time(tx["started_at"])+timedelta(seconds=tx["duration_seconds"])).isoformat())

    def tick(self, record, *, now):
        journal = self._journal(record)
        journal.expire(now=now)
        saved, record = journal._load()
        tx = record.get("transaction")
        handoff = record.get("handoff") or {}
        if handoff.get("state") == "requested" and (_time(now)-_time(handoff["requested_at"])).total_seconds() > 15:
            record["handoff"].update(state="uncertain", error="native_handoff_confirmation_missing")
            journal._save(saved, record)
            return record
        if tx and tx["state"] == "waiting_for_confirmation" and (
                record["state"] == "uncertain" or (_time(now)-_time(tx["started_at"])).total_seconds() > 15):
            self._fail(record, record.get("failure") or "missing_independent_confirmation", now)
            journal._save(saved, record)
        return record

    def notification_deadline(self, record, *, now):
        """Next evidence/spacing deadline; never an actuator or retry timer."""
        tx = record.get("transaction") or {}
        handoff = record.get("handoff") or {}
        if handoff.get("state") == "requested":
            return _time(handoff["requested_at"]) + timedelta(seconds=15.01)
        if tx.get("state") == "waiting_for_confirmation":
            return _time(tx["started_at"]) + timedelta(seconds=15.01)
        deadlines = []
        if record["state"] == "ready":
            previous = (record["commands"][-1]["attempted_at"] or record["commands"][-1]["reserved_at"]
                        if record["commands"] else record["baseline_at"])
            ready_at = _time(previous) + timedelta(seconds=15)
            if record.get("radio_not_before"):
                ready_at = max(ready_at, _time(record["radio_not_before"]))
            if ready_at > _time(now):
                deadlines.append(ready_at)
        if record.get("run"):
            overdue_at = _time(record["run"]["expected_idle_at"]) + timedelta(seconds=30.01)
            if overdue_at > _time(now):
                deadlines.append(overdue_at)
        return min(deadlines) if deadlines else None

    def projection(self, record, *, now, qualification_epoch=None):
        tx, physical = record.get("transaction") or {}, record.get("physical") or {}
        handoff = record.get("handoff") or {}
        busy = tx.get("state") == "waiting_for_confirmation" or handoff.get("state") == "requested"
        previous = ((record["commands"][-1]["attempted_at"] or record["commands"][-1]["reserved_at"])
                    if record["commands"] else record["baseline_at"])
        interval_ready = (_time(now)-_time(previous)).total_seconds() >= 15 and (
            not record.get("radio_not_before") or _time(now) >= _time(record["radio_not_before"]))
        scope = record.get("qualification")
        scope_available = not scope or (qualification_epoch == record["epoch"] and
            _time(now) < _time(scope["expires_at"]) and len(record["commands"]) < scope["maximum_commands"]
            and not record.get("qualification_rf_disabled"))
        available = bool(scope_available and self._available(record) and record["radio_ready"] and record["node_id"] in self.receipted_nodes and
                         record["state"] == "ready" and record["next_phase"] != 0 and not busy and interval_ready)
        fresh = physical and 0 <= (_time(now)-_time(physical["observed_at"])).total_seconds() <= 120
        result = dict(rf_control_enabled=True, rf_control_available=available,
            rf_control_start_available=bool(available and fresh and not physical["watering"]),
            rf_control_transaction_active=busy, rf_control_command_pending=busy,
            rf_control_counter_source="native_six_bit_journal", rf_control_pending_sequence=record["next_phase"],
            rf_control_encoding="native-six-bit-v1", rf_next_native_command_phase=record["next_phase"],
            rf_next_control_sequence=None, rf_retained_counter_restore_available=False,
            rf_retained_command_counter=None, rf_htv145_counter_sync_supported=False,
            rf_retained_counter_status="Native counter ready" if available else "Native control blocked",
            rf_control_transaction_id=tx.get("id"), rf_control_transaction_state=tx.get("state", "idle"),
            rf_control_transaction_action=tx.get("action"), rf_control_transaction_zone=tx.get("zone"),
            rf_control_transaction_duration_seconds=tx.get("duration_seconds"),
            rf_control_transaction_started_at=tx.get("started_at"), rf_control_transaction_updated_at=tx.get("updated_at"),
            rf_control_transaction_error=tx.get("error"),
            rf_control_transaction_status="Waiting for valve evidence" if busy else
                "Command failed; recovery required" if record["state"] == "uncertain" else
                "Valve response and state confirmed" if tx.get("state") == "confirmed" else "Native counter ready",
            rf_control_unavailable_reason=None if available else record.get("failure") or
                ("native_qualification_locked" if not scope_available else
                 "native_rollover_unqualified" if record["next_phase"] == 0 else
                 "native_command_interval" if not interval_ready else "native_radio_not_ready"),
            rf_control_start_unavailable_reason=None if available and fresh and not physical["watering"] else
                record.get("failure") or "waiting_for_fresh_idle",
            rf_control_confirmed_at=physical.get("observed_at"), rf_control_overdue=False,
            rf_htv145_counter_sync_available=False, rf_morning_sync_supported=False,
            rf_control_resync_supported=False, rf_control_resync_active=False,
            rf_morning_sync_available=False, rf_morning_sync_active=False,
            rf_control_duration_min_minutes=1, rf_control_duration_max_minutes=60, rf_control_duration_step_minutes=1)
        if physical:
            result["is_watering"] = physical["watering"]
            result["active_zone"] = physical["port"] if physical["watering"] else 0
            for port in range(1, 5 if record["model"] == "HTV405FRF" else 2):
                result[f"zone_{port}_is_watering"] = physical["watering"] and physical["port"] == port
        if record.get("run"):
            expected = record["run"]["expected_idle_at"]
            result["rf_control_expected_idle_at"] = expected
            result["rf_control_overdue"] = bool(physical.get("watering") and
                _time(now) > _time(expected) + timedelta(seconds=30))
        if handoff.get("state") in ("requested", "uncertain"):
            result.update(rf_native_handoff_state=handoff["state"], rf_native_handoff_kind=handoff["kind"],
                rf_control_transaction_state="verifying" if handoff["state"]=="requested" else "unresolved",
                rf_control_transaction_status="Verifying native counter handoff" if handoff["state"]=="requested" else "Native handoff unresolved",
                rf_control_transaction_error=handoff.get("error"),
                rf_control_start_unavailable_reason=handoff.get("error") or "native_handoff_pending",
                rf_control_unavailable_reason=handoff.get("error") or "native_handoff_pending")
        return result
