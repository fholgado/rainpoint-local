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


SYNC = bytes.fromhex("79f4882f28")
FRAME_BYTES = 38
AUTOMATIC_HTV405_PROFILE_ID = "htv405_auto_candidate_v1"
CALIBRATED_FREQUENCY_OFFSET_HZ = 97_154
INITIAL_REPLY_TARGET_HZ = 433_506_030
ROUTINE_REPLY_TARGET_HZ = 434_351_001
# These are the evidence-derived profile centers compiled into the node. The
# gateway-supplied correction is node-specific and applied on top of them.
INITIAL_REPLY_CHANNEL_HZ = 433_461_030
ROUTINE_REPLY_CHANNEL_HZ = 434_306_001
INITIAL_DEVIATION_HZ = 35_004
ROUTINE_DEVIATION_HZ = 41_260
WAKE_SYMBOLS = 320
SYMBOL_RATE_SPS = 20_000
# A continuous 2.0 Msps capture measured 50.656 ms of silence between the end
# of the 31.23 ms factory announcement and the stock assignment reply.
REPLY_DELAY_MS = 50
REPLY_DEADLINE_MS = 250


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
) -> ValvePairingStep:
    request = bytes.fromhex(request_body)
    reply = bytes.fromhex(reply_body) if reply_body is not None else None
    if len(request) != 23 or (reply is not None and len(reply) != 23):
        raise ValueError("HTV405 pairing bodies must contain 23 bytes")
    return ValvePairingStep(
        request_kind=request_kind,
        request_body=request,
        reply_body=reply,
        trailer_residual=residual,
        channel_center_hz=(
            INITIAL_REPLY_CHANNEL_HZ if initial else ROUTINE_REPLY_CHANNEL_HZ
        ),
        deviation_hz=(INITIAL_DEVIATION_HZ if initial else ROUTINE_DEVIATION_HZ),
    )


HTV405_STEPS = (
    _step("factory_announcement", "00808402ff93130000bd84800000000000000000000000", "80c08585030670009d97118d0080800000000000000000", 0xC713, initial=True),
    _step("paired_message_1", "010107862580804f800000004080005680000000000000", "8141010000800000000000000000000000000000000000", 0x4F03),
    _step("paired_message_1_repeat", "018107860581004f800000004080005680000000000000", "81c1010000800000000000000000000000000000000000", 0xC713),
    _step("paired_message_2", "020107860581804f800000004080005680000000000000", "8241010000800000000000000000000000000000000000", 0xC713),
    _step("paired_message_2_repeat", "028107860582004f800000004080005680000000000000", None, None),
    _step("paired_message_3", "030107860582004f800000004080005680000000000000", "8341010001000000000000000000000000000000000000", 0xC713),
    _step("paired_message_3_short", "0382810600800000000000000000000000000000000000", "83c287802c0105000f0000000000000000000000000000", 0xC713),
    _step("paired_message_4_short", "0402810601000000000000000000000000000000000000", "844287802c0105000f0000000000000000000000000000", 0x4F03),
    _step("paired_message_4_short_repeat", "0482810601800000000000000000000000000000000000", "84c287802c0105000f0000000000000000000000000000", 0xC713),
    _step("paired_message_5_short", "0502810602000000000000000000000000000000000000", "854287802c0105000f0000000000000000000000000000", 0x4F03),
    _step("paired_message_5", "0583018600800000000000000000000000000000000000", "85c3008000000000000000000000000000000000000000", 0xC713),
    _step("paired_message_6", "0603018601000000000000000000000000000000000000", "8643008000000000000000000000000000000000000000", 0xC713),
    _step("paired_message_6_repeat", "0683018601800000000000000000000000000000000000", "86c3008000000000000000000000000000000000000000", 0x4F03),
    _step("paired_message_7", "0703018602000000000000000000000000000000000000", "8743008000000000000000000000000000000000000000", 0xC713),
    _step("paired_message_7_extended", "07ac809900000000000000000000000000000000000000", "87ec878019063232323232323232323232320000000000", 0xC713),
    _step("paired_message_8_extended", "082c809980000000000000000000000000000000000000", "886c878019863232323232323232323232320000000000", 0xC713),
    _step("paired_message_8_extended_repeat", "08ac809a00000000000000000000000000000000000000", "88ec87801a063232323232323232323232320000000000", 0xC713),
    _step("paired_message_9_extended", "092c809a80000000000000000000000000000000000000", "896c87801a863232323232323232323232320000000000", 0xC713),
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
    companion = bytes.fromhex(profile.companion_endpoint)
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
        body[8] = (packed_time & 0x7F) | 0x80
        body[9] = packed_time >> 8
        body[10] = packed_date & 0xFF
        body[11] = (packed_date >> 8) | 0x80
    payload = SYNC + paired + companion + bytes(body)
    trailer = binascii.crc_hqx(payload, 0) ^ step.trailer_residual
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
    return (
        endpoints_match
        and frame[13:36] == step.request_body
        and residual in {0xC713, 0x4F03}
    )


def automatic_htv405_profile_metadata() -> dict[str, Any]:
    """Describe the explicit experimental valve-pairing contract."""
    return {
        "profile_id": AUTOMATIC_HTV405_PROFILE_ID,
        "model": "HTV405FRF",
        "automatic_discovery": True,
        "experimental": True,
        "transmit_enabled": True,
        "valve_control_enabled": False,
        "association_inputs_required": [
            "factory_endpoint",
            "valve_route",
            "companion_endpoint",
        ],
        "step_count": len(HTV405_STEPS),
        "reply_delay_ms": REPLY_DELAY_MS,
        "calibrated_frequency_offset_hz": CALIBRATED_FREQUENCY_OFFSET_HZ,
        "initial_reply_target_hz": INITIAL_REPLY_TARGET_HZ,
        "routine_reply_target_hz": ROUTINE_REPLY_TARGET_HZ,
        "evidence": "isolated stock re-enrollment captured 2026-08-17",
    }
