"""Model-specific HTV213 enrollment parameters, without research admission.

HA supplies a node/model; the gateway resolves an unused address and this
radio's calibrated centers before building the command. Firmware discovers
the factory endpoint from a matching announcement. Nothing here registers a
device, sends RF or authorizes watering. Normal UI binding remains pending.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
import uuid

from .htv213_control import packet
from .rf_identity import controller_endpoint_for

CAPABILITY = "htv213_auto_identity_pairing"


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
    power_dbm: int = 10

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


def completed_association(*, node_id, command, status):
    """Prepare retained configuration and phase seed from correlated RF proof.

    The caller authenticates the selected node and atomically persists the
    returned configuration/seed with its enrollment record. This function does
    not mutate a registry, reset an existing journal or enable controls.
    """
    from .valve_recovery import configuration
    if not isinstance(node_id, str) or not re.fullmatch(r"rp-[0-9a-f]{12}", node_id):
        raise ValueError("selected radio node required")
    command_id = command.get("command_id")
    if (command.get("type") != "htv213_enrollment_start" or
            not isinstance(command_id, str) or not re.fullmatch(r"[0-9a-f]{32}", command_id)):
        raise ValueError("normal enrollment command required")
    values = parameters(command, controller=command.get("controller_endpoint"),
                        companion=command.get("companion_endpoint"))
    if values["notification_phase"] == 63:
        raise ValueError("normal enrollment requires a seedable notification phase")
    factory = status.get("factory_endpoint")
    if (status.get("command_id") != command_id or status.get("state") != "observed" or
            status.get("notification_accepted") is not True or
            any(type(status.get(field)) is not int or status[field] != 3
                for field in ("reports", "settings_sent", "plans_sent")) or
            not isinstance(factory, str) or not re.fullmatch(r"[0-7][0-9a-f]{7}", factory) or
            int(factory, 16) == 0):
        raise ValueError("complete correlated two-port enrollment required")
    paired = f"{int(factory, 16) | 0x80000000:08x}"
    ack = packet(status.get("notification_ack_frame"))
    report = packet(status.get("completion_frame"))
    for decoded in (ack, report):
        if (decoded is None or decoded[0][5:9].hex() != values["controller_endpoint"] or
                decoded[0][9:13].hex() != paired or decoded[0][13] & 0x20):
            raise ValueError("valve-originated enrollment proof required")
    if ack[1:] != (0xa0, values["notification_phase"], b"\0"):
        raise ValueError("positive full-phase configuration ACK required")
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
