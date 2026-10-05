"""Model-specific HTV213 enrollment parameters, without research admission.

HA supplies a node/model; the gateway resolves an unused address and this
radio's calibrated centers before building the command. Firmware discovers
the factory endpoint from a matching announcement. The journal validates RF
completion and atomically saves enrollment, reply ownership and the control
seed. It never sends RF or authorizes watering; model qualification remains
separate from this source-prepared native HA flow.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import copy
import json
import re
import uuid

from .htv213_control import packet
from .rf_identity import controller_endpoint_for

CAPABILITY = "htv213_auto_identity_pairing"
PROFILE_ID = "htv213_auto_candidate_v1"
KEY = "htv213_enrollment_v1"
# Qualified on control.12; gateway eligibility still requires this radio's
# complete firmware capabilities, calibration and exclusive ownership slot.
USER_PAIRING_SUPPORTED = True
# The unchanged legacy assignment recipes encode these slots (native 81 data
# byte 1): HTV145=1, HTV405=6, HCS026=6. Reserve them even before those models
# are installed; later legacy pairing must not collide with a new HTV213 slot.
LEGACY_ADDRESSES = frozenset({1, 6})
CONFIRMATION_WAIT_SECONDS = 600


def profile_metadata():
    return dict(profile_id=PROFILE_ID, model="HTV213FRF", device_category="valve",
        display_name="HTV213FRF two-zone valve", required_node_capability=CAPABILITY,
        automatic_discovery=True, user_pairing_supported=USER_PAIRING_SUPPORTED,
        maximum_duration_seconds=300)


def parameters(request, *, controller, companion):
    """Validate the common RF recipe used by explicit and discovery enrollment."""
    if (not isinstance(controller, str) or not isinstance(companion, str) or
            controller_endpoint_for(companion) != controller):
        raise ValueError("invalid local controller identity")
    bounds = {
        "duration_seconds": (10, 300), "device_address": (1, 255),
        "assigned_selector": (1, 15), "timing_raw": (1, 65535),
        "notification_phase": (1, 63), "initial_center_hz": (433000000, 435000000),
        "routine_center_hz": (433000000, 435000000),
        "reply_delay_us": (20000, 150000), "notification_delay_ms": (500, 5000),
    }
    values = {}
    for key, (low, high) in bounds.items():
        value = request.get(key)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"explicit bounded {key} is required")
        values[key] = value
    # Selector 11 is 110 kHz below the selector-12 reference. Both assignment
    # carriers must be valid before the node prepares its fast-hop cache.
    if values["initial_center_hz"] - 110000 < 433000000:
        raise ValueError("derived assignment carrier is out of range")
    power = request.get("power_dbm")
    if type(power) is not int or power not in {-30, -20, -15, -10, -6, 0, 5, 7, 10}:
        raise ValueError("explicit supported power_dbm is required")
    return dict(controller_endpoint=controller, companion_endpoint=companion,
                power_dbm=power, **values)


@dataclass(frozen=True)
class EnrollmentProfile:
    address: int
    initial_center_hz: int
    routine_center_hz: int
    selector: int = 11
    timing_raw: int = 480
    notification_phase: int = 2
    reply_delay_us: int = 49000
    notification_delay_ms: int = 1000
    # Preserve the successful canary's level when the ordinary journal builds
    # a recipe without overrides; higher power is not enrollment-qualified.
    power_dbm: int = 0

    def command(self, *, controller, companion, duration_seconds=120, now=None):
        # The ordinary journal seeds the next phase without implicit wrap.
        # Keep the explicit research recipe's 1..63 range separate.
        if self.notification_phase == 63:
            raise ValueError("normal enrollment requires a seedable notification phase")
        values = parameters(dict(duration_seconds=duration_seconds,
            device_address=self.address, assigned_selector=self.selector,
            timing_raw=self.timing_raw, notification_phase=self.notification_phase,
            initial_center_hz=self.initial_center_hz, routine_center_hz=self.routine_center_hz,
            reply_delay_us=self.reply_delay_us, notification_delay_ms=self.notification_delay_ms,
            power_dbm=self.power_dbm), controller=controller, companion=companion)
        clock = now or datetime.now().astimezone()
        return dict(type="htv213_enrollment_start", command_id=uuid.uuid4().hex,
                    local_clock=clock.strftime("%Y%m%d%H%M%S"), **values)


def _configuration_ack(command, status, state):
    """Validate the configuration exchange before waiting or completing."""
    command_id = command.get("command_id")
    if (command.get("type") != "htv213_enrollment_start" or
            not isinstance(command_id, str) or not re.fullmatch(r"[0-9a-f]{32}", command_id)):
        raise ValueError("normal enrollment command required")
    values = parameters(command, controller=command.get("controller_endpoint"),
                        companion=command.get("companion_endpoint"))
    if values["notification_phase"] == 63:
        raise ValueError("normal enrollment requires a seedable notification phase")
    factory = status.get("factory_endpoint")
    if (status.get("command_id") != command_id or status.get("state") != state or
            status.get("notification_accepted") is not True or
            any(type(status.get(field)) is not int or status[field] != 3
                for field in ("reports", "settings_sent", "plans_sent")) or
            not isinstance(factory, str) or not re.fullmatch(r"[0-7][0-9a-f]{7}", factory) or
            int(factory, 16) == 0):
        raise ValueError("complete correlated two-port enrollment required")
    paired = f"{int(factory, 16) | 0x80000000:08x}"
    ack = packet(status.get("notification_ack_frame"))
    if (ack is None or ack[0][5:9].hex() != values["controller_endpoint"] or
            ack[0][9:13].hex() != paired or ack[0][13] & 0x20):
        raise ValueError("valve-originated enrollment proof required")
    if ack[1:] != (0xa0, values["notification_phase"], b"\0"):
        raise ValueError("positive full-phase configuration ACK required")
    return values, factory, paired, ack


def completed_association(*, node_id, command, status):
    """Prepare retained configuration and phase seed from correlated RF proof.

    The caller authenticates the selected node and atomically persists the
    returned configuration/seed with its enrollment record. This function does
    not mutate a registry, reset an existing journal or enable controls.
    """
    from .valve_recovery import configuration
    if not isinstance(node_id, str) or not re.fullmatch(r"rp-[0-9a-f]{12}", node_id):
        raise ValueError("selected radio node required")
    values, factory, paired, ack = _configuration_ack(command, status, "observed")
    command_id = command["command_id"]
    report = packet(status.get("completion_frame"))
    if (report is None or report[0][5:9].hex() != values["controller_endpoint"] or
            report[0][9:13].hex() != paired or report[0][13] & 0x20):
        raise ValueError("valve-originated enrollment proof required")
    data = report[3]
    if (report[1] != 2 or len(data) != 15 or data[0] != values["assigned_selector"] or
            data[2] not in (1, 2) or data[3] not in (0, 0x21)):
        raise ValueError("post-configuration valve report required")
    remaining = int.from_bytes(data[10:12], "little")
    requested = int.from_bytes(data[13:15], "little")
    if (data[3] == 0 and (remaining or requested)) or remaining > requested + 1:
        raise ValueError("invalid post-configuration watering fields")
    config = configuration(dict(model="HTV213FRF", factory_endpoint=factory,
        valve_endpoint=paired, controller_endpoint=values["controller_endpoint"],
        node_id=node_id, selector=values["assigned_selector"], revision=2,
        address=values["device_address"], timing_raw=values["timing_raw"],
        ports=[dict(settings="58020a001e00" + "00" * 8, empty_plan=True) for _ in range(2)]))
    seed = dict(node_id=node_id, controller=values["controller_endpoint"], valve=paired,
                selector=values["assigned_selector"], acknowledged_phase=ack[2], evidence_id=command_id)
    return dict(association_key=values["controller_endpoint"] + ":" + paired,
                configuration=config, control_seed=seed)


class EnrollmentJournal:
    """Durable enrollment epochs; caller holds the gateway's transaction lock.

    No RF or implicit counter reset. Only authenticated, command-correlated
    completion proof can replace a revoked association. Restart never resends
    enrollment; naming the same completed epoch cannot reseed its counter.
    """
    def __init__(self, store):
        self.store = store

    def _load(self):
        from .htv213_control import KEY as control_key
        from .htv213_owner import KEY as owner_key
        expected = {key: self.store.metadata_value(key) for key in (KEY, owner_key, control_key)}
        enrollment = json.loads(expected[KEY] or '{"radios":{},"sessions":{},"current":null}')
        return enrollment, json.loads(expected[owner_key] or "{}"), json.loads(expected[control_key] or "{}"), expected

    def _save(self, expected, enrollment, owners=None, controls=None):
        from .htv213_control import KEY as control_key
        from .htv213_owner import KEY as owner_key
        updates = {KEY: json.dumps(enrollment, sort_keys=True)}
        if owners is not None:
            updates[owner_key] = json.dumps(owners, sort_keys=True)
        if controls is not None:
            updates[control_key] = json.dumps(controls, sort_keys=True)
        self.store.save_htv213_enrollment(expected, updates)

    def configure_radio(self, node_id, *, initial_center_hz, routine_center_hz):
        if not isinstance(node_id, str) or not re.fullmatch(r"rp-[0-9a-f]{12}", node_id):
            raise ValueError("selected radio node required")
        if (type(initial_center_hz) is not int or not 433110000 <= initial_center_hz <= 435000000
                or type(routine_center_hz) is not int or not 433000000 <= routine_center_hz <= 435000000):
            raise ValueError("explicit calibrated radio carriers required")
        enrollment, _, _, expected = self._load()
        current = self.current()
        if current and current["state"] not in {"complete", "failed", "expired", "cancelled"}:
            raise ValueError("finish enrollment before changing radio calibration")
        enrollment["radios"][node_id] = dict(initial_center_hz=initial_center_hz, routine_center_hz=routine_center_hz)
        self._save(expected, enrollment)

    def profile(self, node_id, address):
        values = self._load()[0]["radios"].get(node_id)
        if values is None:
            raise ValueError("selected radio has no saved HTV213 carrier calibration")
        return EnrollmentProfile(address=address, **values)

    def address(self, controller, *, replacement_key=None):
        """Allocate around frozen legacy recipes, retained state and attempts.

        A failed/expired window may have sent an assignment, so its slot is
        retained too. Never rewrite another model's proven assignment bytes.
        """
        from .valve_recovery import KEY as recovery_key, configuration
        from .htv213_owner import reply_configuration
        enrollment, owners, _, _ = self._load()
        occupied = set(LEGACY_ADDRESSES)
        for record in json.loads(self.store.metadata_value(recovery_key) or "{}").values():
            config = configuration(record["configuration"])
            if config["controller_endpoint"] == controller:
                occupied.add(config["address"])
        target_address = None
        for key, record in owners.items():
            config = configuration(record.get("configuration") or
                                   reply_configuration({**record["command"], "node_id": record["node_id"]}))
            if config["controller_endpoint"] != controller:
                continue
            if key == replacement_key:
                target_address = config["address"]
            else:
                occupied.add(config["address"])
        if replacement_key is not None:
            if target_address is None or target_address in occupied:
                raise ValueError("re-pair slot conflicts with retained or legacy configuration")
            return target_address
        for record in enrollment["sessions"].values():
            if record["command"]["controller_endpoint"] == controller:
                occupied.add(record["command"]["device_address"])
        address = next((value for value in range(1, 256) if value not in occupied), None)
        if address is None:
            raise ValueError("no available device address")
        return address

    def current(self, now=None):
        enrollment = self._load()[0]
        record = enrollment["sessions"].get(enrollment["current"])
        if record is None:
            return None
        record = copy.deepcopy(record)
        now = now or datetime.now(timezone.utc)
        if (record["state"] not in {"accepted", "complete", "failed", "cancelled"}
                and now >= datetime.fromisoformat(record["expires_at"])):
            record["state"] = "expired"
        return record

    def begin(self, node_id, command, *, replacement_key=None, now=None):
        now = now or datetime.now(timezone.utc)
        # Reuse the recipe validation, including a seedable notification phase.
        if command.get("type") != "htv213_enrollment_start" or not re.fullmatch(r"[0-9a-f]{32}", str(command.get("command_id", ""))):
            raise ValueError("normal enrollment command required")
        if not isinstance(node_id, str) or not re.fullmatch(r"rp-[0-9a-f]{12}", node_id):
            raise ValueError("selected radio node required")
        values = parameters(command, controller=command.get("controller_endpoint"), companion=command.get("companion_endpoint"))
        if values["notification_phase"] == 63:
            raise ValueError("normal enrollment requires a seedable notification phase")
        enrollment, owners, _, expected = self._load()
        current = self.current(now)
        if current and current["state"] not in {"complete", "failed", "expired", "cancelled"}:
            raise ValueError("another enrollment is active")
        if command["command_id"] in enrollment["sessions"]:
            raise ValueError("enrollment command ID already attempted")
        if any(r["node_id"] == node_id and r.get("revoked") is not True for r in owners.values()):
            raise ValueError("revoke the old reply owner before enrollment")
        if replacement_key is not None:
            old = owners.get(replacement_key)
            if not old or old.get("revoking") is not True or old.get("revoked") is not True:
                raise ValueError("re-pair requires acknowledged old-owner revocation")
        record = dict(node_id=node_id, command=copy.deepcopy(command), state="requested",
            started_at=now.isoformat(), expires_at=(now + timedelta(seconds=command["duration_seconds"] + 5)).isoformat(),
            replacement_key=replacement_key,
            revoked_keys=[key for key, old in owners.items() if old.get("revoking") is True and old.get("revoked") is True])
        enrollment["sessions"][command["command_id"]] = record
        enrollment["current"] = command["command_id"]
        self._save(expected, enrollment)
        return copy.deepcopy(record)

    def transition(self, node_id, command_id, state):
        if state not in {"dispatch_failed", "cancellation_requested", "command_rejected", "cancelled"}:
            raise ValueError("invalid enrollment transition")
        enrollment, _, _, expected = self._load()
        record = self.current()
        if not record or record["node_id"] != node_id or record["command"]["command_id"] != command_id:
            raise ValueError("enrollment session changed")
        if record["state"] in {"complete", "failed", "expired", "cancelled"}:
            raise ValueError("enrollment already terminal")
        if state == "cancelled" and record["state"] != "accepted":
            raise ValueError("radio terminal proof required before local cancellation")
        enrollment["sessions"][command_id]["state"] = state
        self._save(expected, enrollment)

    def observe(self, node_id, status, *, now=None):
        now = now or datetime.now(timezone.utc)
        enrollment, _, _, expected = self._load()
        record = self.current(now)
        if (not record or record["node_id"] != node_id or record["command"]["command_id"] != status.get("command_id")
                or record["state"] in {"accepted", "complete", "failed", "expired", "cancelled"}):
            return False
        state = status.get("state")
        if state not in {"armed", "observed", "failed", "disarmed"}:
            return False
        if state == "observed":
            try:
                result = completed_association(node_id=node_id, command=record["command"], status=status)
                if record["replacement_key"] and record["replacement_key"] != result["association_key"]:
                    raise ValueError("re-pair completed for a different valve")
            except ValueError as error:
                record.update(state="failed", error=str(error))
            else:
                record.update(state="accepted", proof=copy.deepcopy(status), result=result)
        else:
            record.update(state="cancelled" if state == "disarmed" else state)
            if (state == "armed" and status.get("awaiting_confirmation") is True
                    and not record.get("awaiting_confirmation")):
                try:
                    _configuration_ack(record["command"], status, "armed")
                except ValueError:
                    pass
                else:
                    # One deadline per epoch; repeated progress cannot extend
                    # it. The radio remains authoritative for its own timeout.
                    record.update(awaiting_confirmation=True,
                        confirmation_started_at=now.isoformat(),
                        expires_at=(now + timedelta(seconds=CONFIRMATION_WAIT_SECONDS + 5)).isoformat())
            if state == "failed":
                record["error"] = "Radio enrollment failed"
        enrollment["sessions"][record["command"]["command_id"]] = record
        self._save(expected, enrollment)
        return True

    def complete(self, node_id, command_id, *, name, area=None):
        from .htv213_control import initial_record, MODEL_PHASE_POLICY
        from .htv213_owner import apply_reply_configuration
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError("device name required (1–100 characters)")
        if area is not None and (not isinstance(area, str) or not 1 <= len(area.strip()) <= 100):
            raise ValueError("invalid device area")
        enrollment, owners, controls, expected = self._load()
        record = enrollment["sessions"].get(command_id)
        if not record or record["node_id"] != node_id or record["state"] not in {"accepted", "complete"}:
            raise ValueError("complete correlated enrollment required")
        result = completed_association(node_id=node_id, command=record["command"], status=record["proof"])
        key, config = result["association_key"], result["configuration"]
        if record["state"] == "complete":
            # Replaying the naming request never sends configuration or resets
            # a counter, even after later successful watering commands.
            current_owner = owners.get(key)
            if not current_owner or current_owner.get("enrollment_id") != command_id:
                raise ValueError("enrollment has been superseded")
            return copy.deepcopy(current_owner)
        if enrollment["current"] != command_id:
            raise ValueError("enrollment has been superseded")
        old = owners.get(key)
        if key in controls or old:
            explicit_repair = record["replacement_key"] == key or key in record.get("revoked_keys", [])
            if (not explicit_repair or not old or
                    old.get("revoking") is not True or old.get("revoked") is not True):
                raise ValueError("existing association requires explicit revoked-owner re-pair")
        if any(k != key and r["node_id"] == node_id and r.get("revoked") is not True for k, r in owners.items()):
            raise ValueError("radio acquired another reply owner")
        if old:
            record["replaced"] = dict(owner=copy.deepcopy(old), control=copy.deepcopy(controls.get(key)))
        command = {**record["command"], "factory_endpoint": config["factory_endpoint"],
                   "type": "htv213_owner_set", "port": 1, "seconds": 60}
        apply_reply_configuration(command, config, True)
        owner = dict(node_id=node_id, command=command, ports={}, configuration=config,
            enrollment_id=command_id, evidence_command_id=command_id,
            device_id=old.get("device_id") if old and old.get("device_id") else "local-htv213-" + config["valve_endpoint"],
            name=name.strip(), area=area.strip() if area is not None else None)
        owners[key] = owner
        controls[key] = initial_record(**result["control_seed"])
        controls[key]["phase_policy"] = MODEL_PHASE_POLICY
        record.update(state="complete", completed_at=datetime.now(timezone.utc).isoformat())
        self._save(expected, enrollment, owners, controls)
        return copy.deepcopy(owner)
