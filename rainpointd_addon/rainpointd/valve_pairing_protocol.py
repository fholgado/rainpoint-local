"""Evidence-backed HTV405 enrollment profile construction.

The profile requires identities from the association under test. It never
supplies installation-default controller or valve endpoints and it cannot
transmit or construct watering commands.
"""

from __future__ import annotations

import binascii
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from .rf_identity import controller_endpoint_for


SYNC = bytes.fromhex("79f4882f28")
FRAME_BYTES = 38
AUTOMATIC_HTV405_PROFILE_ID = "htv405_auto_candidate_v1"
AUTOMATIC_HTV145_PROFILE_ID = "htv145_auto_candidate_v1"
CALIBRATED_FREQUENCY_OFFSET_HZ = 97_154
HTV145_CALIBRATED_FREQUENCY_OFFSET_HZ = 122_759
HTV145_INITIAL_REPLY_TARGET_HZ = 433_581_558
HTV145_ROUTINE_REPLY_TARGET_HZ = 434_351_500
HTV145_INITIAL_REPLY_CHANNEL_HZ = 433_501_466
INITIAL_REPLY_TARGET_HZ = 433_556_430
ROUTINE_REPLY_TARGET_HZ = 433_471_408
# These are the evidence-derived profile centers compiled into the node. The
# gateway-supplied correction is node-specific and applied on top of them.
INITIAL_REPLY_CHANNEL_HZ = 433_511_445
ROUTINE_REPLY_CHANNEL_HZ = 433_426_408
INITIAL_DEVIATION_HZ = 35_004
ROUTINE_DEVIATION_HZ = 41_260
HTV145_INITIAL_DEVIATION_HZ = ROUTINE_DEVIATION_HZ
WAKE_SYMBOLS = 320
SYMBOL_RATE_SPS = 20_000
# A continuous 2.0 Msps capture measured 50.656 ms of silence between the end
# of the 31.23 ms factory announcement and the stock assignment reply. A local
# continuous trial placed the 50 ms software candidate about 1.3 ms late after
# transmit setup, so 49 ms is the closest whole-millisecond firmware target.
REPLY_DELAY_MS = 49
REPLY_DEADLINE_MS = 250
HTV145_SELECTOR6_ROUTINE_REPLY_CHANNEL_HZ = 434_306_378
HTV145_CONFIGURATION_START_DELAY_MS = 3_054.85
HTV145_CONFIGURATION_WAKE_SYMBOLS = 2_400


@dataclass(frozen=True)
class ValvePairingStep:
    request_kind: str
    request_body: bytes
    reply_body: bytes | None
    trailer_residual: int | None
    channel_center_hz: int
    deviation_hz: int
    wake_symbols: int = WAKE_SYMBOLS
    reply_deadline_ms: int = REPLY_DEADLINE_MS
    reply_to_valve_route: bool = False


@dataclass(frozen=True)
class ValvePairingProfile:
    profile_id: str
    model: str
    factory_endpoint: str
    paired_endpoint: str
    valve_route: str
    companion_endpoint: str
    reply_delay_ms: int
    steps: tuple[ValvePairingStep, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "model": self.model,
            "factory_endpoint": self.factory_endpoint,
            "paired_endpoint": self.paired_endpoint,
            "valve_route": self.valve_route,
            "companion_endpoint": self.companion_endpoint,
            "reply_delay_ms": self.reply_delay_ms,
            "step_count": len(self.steps),
            "automatic_discovery": True,
            "experimental": True,
            "transmit_enabled": True,
            "valve_control_enabled": False,
            "steps": [
                {
                    **asdict(step),
                    "request_body": step.request_body.hex(),
                    "reply_body": (
                        step.reply_body.hex() if step.reply_body is not None else None
                    ),
                }
                for step in self.steps
            ],
        }


def _step(
    request_kind: str,
    request_body: str,
    reply_body: str | None,
    residual: int | None,
    *,
    initial: bool = False,
    reply_to_valve_route: bool = False,
    channel_center_hz: int | None = None,
    deviation_hz: int | None = None,
) -> ValvePairingStep:
    request = bytes.fromhex(request_body)
    reply = bytes.fromhex(reply_body) if reply_body is not None else None
    if len(request) != 23 or (reply is not None and len(reply) != 23):
        raise ValueError("valve pairing bodies must contain 23 bytes")
    return ValvePairingStep(
        request_kind=request_kind,
        request_body=request,
        reply_body=reply,
        trailer_residual=residual,
        channel_center_hz=(
            channel_center_hz
            if channel_center_hz is not None
            else INITIAL_REPLY_CHANNEL_HZ
            if initial
            else ROUTINE_REPLY_CHANNEL_HZ
        ),
        deviation_hz=(
            deviation_hz
            if deviation_hz is not None
            else INITIAL_DEVIATION_HZ
            if initial
            else ROUTINE_DEVIATION_HZ
        ),
        reply_to_valve_route=reply_to_valve_route,
    )


HTV405_STEPS = (
    _step("factory_announcement", "00808402ff93130000bd84800000000000000000000000", "80c08585030270009d97918d0100800000000000000000", 0x4F03, initial=True),
    _step("paired_message_1", "010107822580804f800000004080005680000000000000", "8141010000800000000000000000000000000000000000", 0x4F03),
    _step("paired_message_1_repeat", "018107820581004f800000004080005680000000000000", "81c1010000800000000000000000000000000000000000", 0xC713),
    _step("paired_message_2", "020107820581804f800000004080005680000000000000", "8241010000800000000000000000000000000000000000", 0xC713),
    _step("paired_message_2_repeat", "028107820582004f800000004080005680000000000000", None, None),
    _step("paired_message_3", "030107820582004f800000004080005680000000000000", "8341010001000000000000000000000000000000000000", 0xC713),
    _step("paired_message_3_short", "0382810200800000000000000000000000000000000000", "83c287802c0105000f0000000000000000000000000000", 0xC713),
    _step("paired_message_4_short", "0402810201000000000000000000000000000000000000", "844287802c0105000f0000000000000000000000000000", 0x4F03),
    _step("paired_message_4_short_repeat", "0482810201800000000000000000000000000000000000", "84c287802c0105000f0000000000000000000000000000", 0xC713),
    _step("paired_message_5_short", "0502810202000000000000000000000000000000000000", "854287802c0105000f0000000000000000000000000000", 0x4F03),
    _step("paired_message_5", "0583018200800000000000000000000000000000000000", "85c3008000000000000000000000000000000000000000", 0xC713),
    _step("paired_message_6", "0603018201000000000000000000000000000000000000", "8643008000000000000000000000000000000000000000", 0xC713),
    _step("paired_message_6_repeat", "0683018201800000000000000000000000000000000000", "86c3008000000000000000000000000000000000000000", 0x4F03),
    _step("paired_message_7", "0703018202000000000000000000000000000000000000", "8743008000000000000000000000000000000000000000", 0xC713),
    _step("paired_message_7_extended", "07ac809900000000000000000000000000000000000000", "87ec878019063232323232323232323232320000000000", 0xC713),
    _step("paired_message_8_extended", "082c809980000000000000000000000000000000000000", "886c878019863232323232323232323232320000000000", 0xC713),
    _step("paired_message_8_extended_repeat", "08ac809a00000000000000000000000000000000000000", "88ec87801a063232323232323232323232320000000000", 0xC713),
    _step("paired_message_9_extended", "092c809a80000000000000000000000000000000000000", "896c87801a863232323232323232323232320000000000", 0xC713),
)

# Complete six-stage counter-0/selector-6 transcript from the controlled
# app-first stock enrollment on 2026-09-01. The delayed 81/10 controller
# command between rows one and two is constructed by the radio firmware.
HTV145_FACTORY_REQUEST_BODY = bytes.fromhex(
    "80808402ff8f970080bf06000000000000000000000000"
)
HTV145_ASSIGNMENT_REPLY_BODY = bytes.fromhex(
    "80c0858500867000f865210d0100800000000000000000"
)
HTV145_STEPS = (
    _step(
        "factory_announcement",
        HTV145_FACTORY_REQUEST_BODY.hex(),
        HTV145_ASSIGNMENT_REPLY_BODY.hex(),
        0xC713,
        initial=True,
        reply_to_valve_route=True,
        channel_center_hz=HTV145_INITIAL_REPLY_CHANNEL_HZ,
        deviation_hz=HTV145_INITIAL_DEVIATION_HZ,
    ),
    _step(
        "paired_message_1",
        "810107862580804f800000004080005680000000000000",
        "8141010000800000000000000000000000000000000000",
        0x4F03,
        reply_to_valve_route=True,
        channel_center_hz=HTV145_SELECTOR6_ROUTINE_REPLY_CHANNEL_HZ,
    ),
    _step(
        "controller_configuration_response",
        "8150008000000000000000000000000000000000000000",
        None,
        None,
        channel_center_hz=HTV145_SELECTOR6_ROUTINE_REPLY_CHANNEL_HZ,
    ),
    _step(
        "paired_short_message",
        "8182810600800000000000000000000000000000000000",
        "81c287802c0105000f0000000000000000000000000000",
        0x4F03,
        reply_to_valve_route=True,
        channel_center_hz=HTV145_SELECTOR6_ROUTINE_REPLY_CHANNEL_HZ,
    ),
    _step(
        "paired_controller_message",
        "8203018600800000000000000000000000000000000000",
        "8243008000000000000000000000000000000000000000",
        0x4F03,
        reply_to_valve_route=True,
        channel_center_hz=HTV145_SELECTOR6_ROUTINE_REPLY_CHANNEL_HZ,
    ),
    _step(
        "paired_extended_message",
        "82ac809900000000000000000000000000000000000000",
        "82ec818019000000000000000000000000000000000000",
        0x4F03,
        reply_to_valve_route=True,
        channel_center_hz=HTV145_SELECTOR6_ROUTINE_REPLY_CHANNEL_HZ,
    ),
)


def _endpoint(value: str, name: str) -> bytes:
    try:
        endpoint = bytes.fromhex(value)
    except ValueError as error:
        raise ValueError(f"{name} must be hexadecimal") from error
    if len(endpoint) != 4:
        raise ValueError(f"{name} must contain exactly four bytes")
    return endpoint


def build_htv405_profile(
    *, factory_endpoint: str, valve_route: str, companion_endpoint: str
) -> ValvePairingProfile:
    """Build one association-specific receive/transmit enrollment profile."""
    factory = _endpoint(factory_endpoint, "factory_endpoint")
    route = _endpoint(valve_route, "valve_route")
    companion = _endpoint(companion_endpoint, "companion_endpoint")
    if factory[0] & 0x80 or factory[-1] != 0x13:
        raise ValueError("factory_endpoint is not an observed HTV405 identity")
    if route == bytes(4) or companion == bytes(4):
        raise ValueError("association routes cannot be zero")
    if route.hex() != controller_endpoint_for(companion.hex()):
        raise ValueError("valve_route does not match companion_endpoint")
    paired = bytes([factory[0] | 0x80]) + factory[1:]
    return ValvePairingProfile(
        profile_id=AUTOMATIC_HTV405_PROFILE_ID,
        model="HTV405FRF",
        factory_endpoint=factory.hex(),
        paired_endpoint=paired.hex(),
        valve_route=route.hex(),
        companion_endpoint=companion.hex(),
        reply_delay_ms=REPLY_DELAY_MS,
        steps=HTV405_STEPS,
    )


def build_htv145_profile(
    *, factory_endpoint: str, valve_route: str, companion_endpoint: str
) -> ValvePairingProfile:
    """Build an association-specific HTV145 assignment probe profile."""
    factory = _endpoint(factory_endpoint, "factory_endpoint")
    route = _endpoint(valve_route, "valve_route")
    companion = _endpoint(companion_endpoint, "companion_endpoint")
    if factory[0] & 0x80 or factory[-1] != 0x8F:
        raise ValueError("factory_endpoint is not an observed HTV145 identity")
    if route == bytes(4) or companion == bytes(4):
        raise ValueError("association routes cannot be zero")
    if route.hex() != controller_endpoint_for(companion.hex()):
        raise ValueError("valve_route does not match companion_endpoint")
    paired = bytes([factory[0] | 0x80]) + factory[1:]
    return ValvePairingProfile(
        profile_id=AUTOMATIC_HTV145_PROFILE_ID,
        model="HTV145FRF",
        factory_endpoint=factory.hex(),
        paired_endpoint=paired.hex(),
        valve_route=route.hex(),
        companion_endpoint=companion.hex(),
        reply_delay_ms=REPLY_DELAY_MS,
        steps=HTV145_STEPS,
    )


def frame_for_step(
    profile: ValvePairingProfile,
    index: int,
    *,
    local_clock: datetime | None = None,
) -> bytes | None:
    """Construct one reply while preserving its captured trailer family."""
    step = profile.steps[index]
    if step.reply_body is None or step.trailer_residual is None:
        return None
    paired = bytes.fromhex(profile.paired_endpoint)
    destination = bytes.fromhex(
        profile.valve_route
        if step.reply_to_valve_route
        else profile.companion_endpoint
    )
    body = bytearray(step.reply_body)
    if index == 0 and local_clock is not None:
        packed_time = (
            local_clock.hour << 11
            | local_clock.minute << 5
            | local_clock.second // 2
        )
        packed_date = (
            (local_clock.year - 2020) << 9
            | local_clock.month << 5
            | local_clock.day
        )
        def preserve_marker(value: int, template: int) -> int:
            return (value & 0x7F) | (template & 0x80)

        if profile.profile_id == AUTOMATIC_HTV145_PROFILE_ID:
            body[8] = preserve_marker(packed_time, body[8])
            body[9] = preserve_marker(packed_time >> 8, body[9])
            body[10] = preserve_marker(packed_date, body[10])
            body[11] = preserve_marker(packed_date >> 8, body[11])
        else:
            body[8] = (packed_time & 0x7F) | 0x80
            body[9] = (packed_time >> 8) | 0x80
            body[10] = (packed_date & 0x7F) | 0x80
            body[11] = packed_date >> 8
    payload = SYNC + paired + destination + bytes(body)
    trailer = binascii.crc_hqx(payload, 0) ^ step.trailer_residual
    return payload + trailer.to_bytes(2, "big")


def htv145_configuration_frame(
    profile: ValvePairingProfile, *, counter_offset: int = 0
) -> bytes:
    """Construct the counter-0/selector-6 long-wake controller command."""
    if profile.profile_id != AUTOMATIC_HTV145_PROFILE_ID:
        raise ValueError("HTV145 configuration requires an HTV145 profile")
    if not 0 <= counter_offset <= 0x7F:
        raise ValueError("counter_offset must fit the seven-bit counter")
    body = bytearray(23)
    body[0] = 0x80 | ((0x81 + counter_offset) & 0x7F)
    body[1:4] = bytes.fromhex("100101")
    payload = (
        SYNC
        + bytes.fromhex(profile.paired_endpoint)
        + bytes.fromhex(profile.valve_route)
        + bytes(body)
    )
    trailer = binascii.crc_hqx(payload, 0) ^ 0xC713
    return payload + trailer.to_bytes(2, "big")


def request_matches(
    profile: ValvePairingProfile, index: int, frame: bytes
) -> bool:
    """Match the exact captured request body with association substitutions."""
    if len(frame) != FRAME_BYTES or not frame.startswith(SYNC):
        return False
    step = profile.steps[index]
    factory = bytes.fromhex(profile.factory_endpoint)
    paired = bytes.fromhex(profile.paired_endpoint)
    route = bytes.fromhex(profile.valve_route)
    if index == 0:
        endpoints_match = frame[5:9] == bytes.fromhex("80000000") and frame[9:13] == factory
    else:
        endpoints_match = frame[5:9] == route and frame[9:13] == paired
    residual = binascii.crc_hqx(frame[:-2], 0) ^ int.from_bytes(frame[-2:], "big")
    body_matches = (
        frame[15:36] == step.request_body[2:]
        if index == 0
        else frame[13:36] == step.request_body
    )
    return endpoints_match and body_matches and residual in {0xC713, 0x4F03}


def automatic_htv405_profile_metadata() -> dict[str, Any]:
    """Describe the explicit experimental valve-pairing contract."""
    return {
        "profile_id": AUTOMATIC_HTV405_PROFILE_ID,
        "model": "HTV405FRF",
        "device_category": "valve",
        "display_name": "HTV405 4-zone water timer",
        "user_pairing_supported": True,
        "required_node_capability": "htv405_auto_identity_pairing",
        "automatic_discovery": True,
        "experimental": True,
        "transmit_enabled": True,
        "valve_control_enabled": False,
        "association_inputs_required": [],
        "controller_identity_default": "persistent_local_gateway",
        "retained_association_identity_optional": True,
        "step_count": len(HTV405_STEPS),
        "reply_delay_ms": REPLY_DELAY_MS,
        "calibrated_frequency_offset_hz": CALIBRATED_FREQUENCY_OFFSET_HZ,
        "initial_reply_target_hz": INITIAL_REPLY_TARGET_HZ,
        "routine_reply_target_hz": ROUTINE_REPLY_TARGET_HZ,
        "evidence": "isolated stock re-enrollment captured 2026-08-17",
    }


def automatic_htv145_profile_metadata() -> dict[str, Any]:
    """Describe the bounded, research-only HTV145 enrollment profile."""
    return {
        "profile_id": AUTOMATIC_HTV145_PROFILE_ID,
        "model": "HTV145FRF",
        "device_category": "valve",
        "display_name": "HTV145 single-zone water timer",
        "user_pairing_supported": False,
        "required_node_capability": "htv145_pairing_tx_candidate",
        "automatic_discovery": False,
        "experimental": True,
        "transmit_enabled": True,
        "valve_control_enabled": False,
        "association_inputs_required": [
            "factory_endpoint",
            "valve_route",
            "companion_endpoint",
        ],
        "controller_identity_default": "retained_association",
        "retained_association_identity_optional": False,
        "step_count": len(HTV145_STEPS),
        "reply_delay_ms": REPLY_DELAY_MS,
        "calibrated_frequency_offset_hz": HTV145_CALIBRATED_FREQUENCY_OFFSET_HZ,
        "initial_reply_target_hz": HTV145_INITIAL_REPLY_TARGET_HZ,
        "routine_reply_target_hz": HTV145_ROUTINE_REPLY_TARGET_HZ,
        "configuration_start_delay_ms": HTV145_CONFIGURATION_START_DELAY_MS,
        "configuration_wake_symbols": HTV145_CONFIGURATION_WAKE_SYMBOLS,
        "evidence": (
            "complete successful stock-gateway enrollment captured "
            "continuously on 2026-08-25; local physical validation pending"
        ),
    }
