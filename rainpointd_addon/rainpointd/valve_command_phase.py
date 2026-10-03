"""Phase-independent valve codec; no transport, admission or watering policy.

The phase is a six-bit request identifier, not an action or telemetry counter.
Normalized windows are not complete on-air symbol streams. Builders preserve
the qualified local command bodies; stock four-zone bodies differ.
"""
from __future__ import annotations

import binascii
from dataclasses import dataclass

from .valve_protocol import (
    FRAME_BYTES, SYNC, TRAILER_RESIDUES, ValveLink,
    build_close_frame, build_open_frame,
)


@dataclass(frozen=True)
class CommandEnvelope:
    raw: bytes
    command: int
    phase: int
    data: bytes

    @property
    def route(self) -> tuple[bytes, bytes]:
        return self.raw[5:9], self.raw[9:13]


def decode_envelope(frame: str | bytes) -> CommandEnvelope | None:
    """Validate an ordinary window without conferring counter authority."""
    try:
        raw = bytes.fromhex(frame) if isinstance(frame, str) else frame
    except ValueError:
        return None
    if not isinstance(raw, bytes) or len(raw) != FRAME_BYTES or raw[:5] != SYNC:
        return None
    residue = binascii.crc_hqx(raw[:36], 0) ^ int.from_bytes(raw[36:], "big")
    if residue not in TRAILER_RESIDUES:
        return None
    native = bytes(((raw[i + 4] << 1) | (raw[i + 5] >> 7)) & 255 for i in range(32))
    length = native[11] & 31
    if native[0] != 0x51 or length > 20 or native[9] & 0x40:
        return None
    return CommandEnvelope(raw, native[10], native[9] & 63, native[12:12 + length])


def build_command(*, model: str, link: ValveLink, phase: int, action: str,
                  port: int, duration_seconds: int | None, residue: int,
                  selector: int | None = None) -> bytes:
    """Build one exact local request, with no retry or synchronization policy."""
    if model not in ("HTV145FRF", "HTV405FRF"):
        raise ValueError("unsupported phase command model")
    if type(phase) is not int or phase not in range(64):
        raise ValueError("native phase must be an integer in 0..63")
    if type(port) is not int or port not in range(1, 5 if model == "HTV405FRF" else 2):
        raise ValueError("invalid model port")
    if action not in ("open", "close"):
        raise ValueError("command action must be open or close")
    if model == "HTV405FRF" and (selector not in (5, 0x85) or residue != 0x4f03):
        raise ValueError("four-zone commands require the retained selector and trailer")
    if action == "open":
        if (type(duration_seconds) is not int or not 60 <= duration_seconds <= 3600
                or duration_seconds % 60):
            raise ValueError("open requires 1..60 whole minutes")
    elif duration_seconds is not None:
        raise ValueError("close cannot carry a duration")
    if any(v in (bytes(4), bytes.fromhex("80000000")) for v in
           (link.controller_endpoint, link.valve_endpoint)):
        raise ValueError("association-specific endpoints required")
    sequence = 0x80 | (phase >> 1)
    marker_inverted = bool(phase & 1) == (action == "open")
    frame = (build_open_frame(link, sequence, duration_seconds, residue,
                             command_marker_inverted=marker_inverted)
             if action == "open" else
             build_close_frame(link, sequence, residue, command_marker_inverted=marker_inverted))
    if model == "HTV405FRF":
        raw = bytearray(frame)
        raw[17] = 0x80 | port  # Retain generated-association packing, not stock port packing.
        raw[-2:] = (binascii.crc_hqx(raw[:-2], 0) ^ residue).to_bytes(2, "big")
        frame = bytes(raw)
    return frame


def matches_positive_result(request: CommandEnvelope, response: CommandEnvelope,
                            *, model: str, port: int) -> bool:
    """Match a positive native a1 to retained request context, not phase parity.

    Stock mode 0x21/0x20 contains no outlet identity. Never label its high nibble
    as a port. Local HTV405 mode may contain an outlet; require it to match.
    A negative result is not synchronization evidence. Physical state remains
    a separate observation even when this function returns True.
    """
    if (model not in ("HTV145FRF", "HTV405FRF") or type(port) is not int
            or port not in range(1, 5 if model == "HTV405FRF" else 2)
            or request.command != 0x21 or response.command != 0xa1
            or request.phase != response.phase or len(response.data) != 13
            or response.data[0] != 0 or len(request.data) not in (3, 5)):
        return False
    body = request.data
    if not (body[:2] == bytes((port, 2)) or
            (model == "HTV405FRF" and body[:2] == bytes((1, port << 1)))):
        return False
    if body[2] not in (0, 1) or len(body) != (5 if body[2] else 3):
        return False
    source, target = request.route
    response_source = (target if model == "HTV145FRF" else
                       bytes((target[0] | 128,)) + target[1:])
    if response.route != (response_source, source):
        return False
    mode = response.data[1]
    allowed_modes = (0x20 | body[2],)
    if model == "HTV405FRF":
        allowed_modes += ((port << 5) | body[2],)
    if mode not in allowed_modes:
        return False
    if body[2]:
        seconds = int.from_bytes(body[3:5], "little")
        if (not 60 <= seconds <= 3600 or seconds % 60
                or response.data[11:13] != body[3:5]
                or not 0 < int.from_bytes(response.data[8:10], "little") <= seconds + 1):
            return False
    # A close reply can retain the previous run's duration; do not invent a zero rule.
    return True
