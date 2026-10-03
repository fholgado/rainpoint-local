"""Durable retained-valve recovery, independent of enrollment/control counters.

The gateway lock serializes this module. RF observations never create an
association or supply configuration. Production has no qualified assignment
profile yet: requests are diagnosed, not sent through a fresh pairing path.
"""
from __future__ import annotations

import binascii
import copy
from datetime import datetime, timedelta, timezone
import json
import re
import uuid

KEY = "valve_recovery_v1"
PORTS = {"HTV145FRF": 1, "HTV213FRF": 2, "HTV405FRF": 4}
CAPABILITY = "retained_valve_recovery_v1"
# Populate only after model-specific assignment/carrier/timing qualification.
QUALIFIED_PROFILES: dict[str, str] = {}


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("recovery timestamps must include a timezone")
    return result.astimezone(timezone.utc)


def endpoint(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{8}", value):
        raise ValueError("invalid recovery endpoint")
    if value in {"00000000", "80000000"}:
        raise ValueError("broadcast is not a recovery identity")
    return value


def configuration(value):
    """Validate explicit retained state; no captured or guessed defaults."""
    result = copy.deepcopy(value)
    required = {"model", "factory_endpoint", "controller_endpoint", "valve_endpoint",
                "node_id", "selector", "revision", "address", "timing_raw", "ports"}
    if not isinstance(result, dict) or set(result) != required:
        raise ValueError("incomplete retained valve configuration")
    if result["model"] not in PORTS:
        raise ValueError("unsupported recovery model")
    for key in ("factory_endpoint", "controller_endpoint", "valve_endpoint"):
        endpoint(result[key])
    factory = bytes.fromhex(result["factory_endpoint"])
    paired = bytes.fromhex(result["valve_endpoint"])
    if factory[0] & 128 or bytes((factory[0] | 128,)) + factory[1:] != paired:
        raise ValueError("factory/paired identity mismatch")
    if result["controller_endpoint"] == result["valve_endpoint"]:
        raise ValueError("controller and valve must differ")
    if not isinstance(result["node_id"], str) or not re.fullmatch(r"rp-[0-9a-f]{12}", result["node_id"]):
        raise ValueError("invalid recovery owner")
    for key, minimum, maximum in (("selector", 1, 15), ("revision", 1, 255),
                                   ("address", 1, 255), ("timing_raw", 0, 65535)):
        if type(result[key]) is not int or not minimum <= result[key] <= maximum:
            raise ValueError("invalid retained " + key)
    if not isinstance(result["ports"], list) or len(result["ports"]) != PORTS[result["model"]]:
        raise ValueError("wrong retained port count")
    for port in result["ports"]:
        if not isinstance(port, dict) or set(port) != {"settings", "empty_plan"}:
            raise ValueError("invalid retained port configuration")
        if (not isinstance(port["settings"], str)
                or not re.fullmatch(r"[0-9a-f]{28}", port["settings"])
                or port["empty_plan"] is not True):
            raise ValueError("only explicit settings and known empty plans are supported")
    return result


def packet(frame):
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
    if length > 20:
        return None
    return raw, native[10], native[9] & 63, native[12:12 + length]


class ValveRecovery:
    def __init__(self, store, nodes, eligibility, sender, *, profiles=None):
        self.store, self.nodes = store, nodes
        self.eligibility, self.sender = eligibility, sender
        self.profiles = dict(QUALIFIED_PROFILES if profiles is None else profiles)
        self._reload()

    def _reload(self):
        # Registry deletion removes this metadata in the same transaction.
        # Refresh before decisions so removal/re-add cannot revive stale RAM.
        self.records = json.loads(self.store.metadata_value(KEY) or "{}")
        # Corrupt retained state is not an invitation to rebuild it from RF.
        for key, record in self.records.items():
            if configuration(record["configuration"])["factory_endpoint"] != key:
                raise ValueError("corrupt retained recovery association")

    def _save(self, records):
        # Commit before swapping RAM or sending. Failed commits leave both the
        # old in-memory state and the old durable snapshot authoritative.
        self.store.save_valve_recovery(json.dumps(records, sort_keys=True))
        self.records = records

    def configure(self, value):
        self._reload()
        config = configuration(value)
        reason = self.eligibility(config)
        if reason:
            raise ValueError(reason)
        key = config["factory_endpoint"]
        previous = self.records.get(key)
        if previous and previous["configuration"] == config:
            return self.snapshot(key)[0]
        if (previous and previous.get("expires_at") and
                datetime.now(timezone.utc) < timestamp(previous["expires_at"])):
            raise RuntimeError("wait for bounded recovery to expire before replacing configuration")
        records = copy.deepcopy(self.records)
        records[key] = {"configuration": config, "generation": uuid.uuid4().hex,
                        "state": "waiting_for_announcement", "reason": None,
                        "seen": [], "progress": {"reports": [], "settings": [], "plans": []}}
        self._save(records)
        return self.snapshot(key)[0]

    def snapshot(self, factory=None):
        self._reload()
        result = []
        for key, record in self.records.items():
            if factory is not None and key != factory:
                continue
            result.append({"factory_endpoint": key,
                "model": record["configuration"]["model"],
                "node_id": record["configuration"]["node_id"],
                "state": record["state"], "reason": record.get("reason"),
                "progress": copy.deepcopy(record["progress"]),
                "started_at": record.get("started_at"),
                "expires_at": record.get("expires_at"),
                "command_id": record.get("command_id")})
        return result

    def observe(self, frame, node_id, observed_at):
        self._reload()
        if not self.records:
            return None
        decoded = packet(frame)
        if decoded is None:
            return None
        raw, command, phase, data = decoded
        try:
            now = timestamp(observed_at)
        except (ValueError, TypeError, AttributeError):
            return None
        for key, old in self.records.items():
            config = old["configuration"]
            announcement = (command == 1 and len(data) == 8 and data[1] == 255
                            and not (raw[13] & 0x20)  # Native P9 bit 0x40.
                            and raw[5:9] == bytes.fromhex("80000000")
                            and raw[9:13].hex() == key)
            addressed = (command in (2, 5, 6)
                         and raw[5:9].hex() == config["controller_endpoint"]
                         and raw[9:13].hex() == config["valve_endpoint"])
            if not announcement and not addressed:
                continue
            node = self.nodes.get(config["node_id"], {})
            # An observer elsewhere may hear the device, but cannot authorize
            # or confirm recovery on behalf of the configured owner.
            if node_id != config["node_id"] or not (node.get("connected") is True
                                                     and node.get("authenticated") is True):
                return None
            reason = self.eligibility(config)
            if reason:
                records = copy.deepcopy(self.records)
                records[key].update(state="blocked", reason=reason)
                if records != self.records:
                    self._save(records)
                return self.snapshot(key)[0]
            if old.get("started_at") and now < timestamp(old["started_at"]):
                return None
            active = old.get("expires_at") and now < timestamp(old["expires_at"])
            records = copy.deepcopy(self.records)
            record = records[key]
            if announcement and not active:
                record.update(state="announcement_observed", reason=None,
                    started_at=now.isoformat(), expires_at=(now + timedelta(seconds=90)).isoformat(),
                    seen=[], progress={"reports": [], "settings": [], "plans": []},
                    command_id=None, session=node.get("connected_at"))
            elif not active:
                return None
            if record.get("session") != node.get("connected_at"):
                record.update(state="interrupted", reason="owner_connection_changed")
                self._save(records)
                return self.snapshot(key)[0]
            fingerprint = f"{command}:{phase}:{data.hex()}"
            if fingerprint in record["seen"]:
                return self.snapshot(key)[0]
            if len(record["seen"]) >= 64:
                return self.snapshot(key)[0]  # Bounded session, not a traffic log.
            if addressed:
                expected_length = {2: 15, 5: 2, 6: 3}[command]
                if len(data) != expected_length or data[0] != config["selector"]:
                    return None
                port = data[2 if command == 2 else 1]
                if not 1 <= port <= PORTS[config["model"]] or (command == 6 and data[2] != 0):
                    return None
                progress = record["progress"][{2: "reports", 5: "settings", 6: "plans"}[command]]
                if port not in progress:
                    progress.append(port)
                    progress.sort()
                record["state"] = "addressed_progress"
                # Requests prove reception/progress, NOT our reply's delivery
                # or complete enrollment; successful control is separate.
            record["seen"].append(fingerprint)
            intent = None
            if announcement and record.get("command_id") is None:
                profile = self.profiles.get(config["model"])
                if not profile:
                    record.update(state="blocked", reason="assignment_profile_unqualified")
                elif CAPABILITY not in node.get("capabilities", []) or not node.get("connected_at"):
                    record.update(state="blocked", reason="owner_firmware_incompatible")
                elif abs((datetime.now(timezone.utc) - now).total_seconds()) > 30:
                    record.update(state="blocked", reason="stale_observation")
                else:
                    record.update(state="requested", reason=None, command_id=uuid.uuid4().hex)
                    intent = {"type": "valve_recovery_start", "profile": profile,
                        "command_id": record["command_id"], "generation": record["generation"],
                        "session": record["session"], "duration_seconds": 90,
                        "configuration": copy.deepcopy(config)}
            self._save(records)
            if intent is not None:
                try:
                    self.sender(config["node_id"], intent)
                except (ConnectionError, KeyError, RuntimeError, ValueError):
                    failed = copy.deepcopy(self.records)
                    failed[key].update(state="delivery_unknown", reason="command_delivery_failed")
                    self._save(failed)
            return self.snapshot(key)[0]
        return None
