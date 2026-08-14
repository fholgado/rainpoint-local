"""Pure HTV145 valve frame construction with no radio transmit path."""

from __future__ import annotations

import binascii
from dataclasses import dataclass


SYNC = bytes.fromhex("79f4882f28")
FRAME_BYTES = 38
TRAILER_RESIDUES = (0xC713, 0x4F03)


@dataclass(frozen=True)
class ValveLink:
    """Association-specific controller and valve RF identities.

    There are intentionally no installation defaults.  A link must come from
    the valve enrollment being analyzed so an offline candidate cannot silently
    target the installed production valve.
    """

    controller_endpoint: bytes
    valve_endpoint: bytes

    def __post_init__(self) -> None:
        for name, endpoint in (
            ("controller_endpoint", self.controller_endpoint),
            ("valve_endpoint", self.valve_endpoint),
        ):
            if not isinstance(endpoint, bytes) or len(endpoint) != 4:
                raise ValueError(f"{name} must contain exactly four bytes")
        if self.controller_endpoint == self.valve_endpoint:
            raise ValueError("controller and valve endpoints must differ")


def encode_duration(duration_seconds: int) -> bytes:
    """Encode a confirmed whole-minute HTV145 watering duration.

    Captures correlated to Home Assistant show that the duration is stored in
    two-second units while bit 7 of the low byte is always asserted. Limiting
    construction to whole minutes makes that overlaid bit unambiguous.
    """
    if duration_seconds <= 0 or duration_seconds > 24 * 60 * 60:
        raise ValueError("duration must be between 60 seconds and 24 hours")
    if duration_seconds % 60:
        raise ValueError("only confirmed whole-minute durations are supported")
    units = duration_seconds // 2
    encoded = bytearray(units.to_bytes(2, "little"))
    encoded[0] |= 0x80
    return bytes(encoded)


def decode_duration(encoded: bytes) -> int:
    """Decode an HTV145 duration using confirmed whole-minute constraints."""
    if len(encoded) != 2:
        raise ValueError("duration must contain exactly two bytes")
    raw = int.from_bytes(encoded, "little")
    candidates = {raw * 2, (raw & ~0x80) * 2}
    confirmed = [
        value
        for value in candidates
        if 0 < value <= 24 * 60 * 60 and value % 60 == 0
    ]
    if len(confirmed) != 1:
        raise ValueError("duration is ambiguous outside whole-minute encoding")
    return confirmed[0]


def _validate_sequence(sequence: int) -> None:
    if sequence < 0x80 or sequence > 0x9F:
        raise ValueError("sequence must be in the observed 0x80..0x9f range")


def next_sequence(sequence: int) -> int:
    """Advance the observed five-bit transaction counter."""
    _validate_sequence(sequence)
    return 0x80 | ((sequence + 1) & 0x1F)


def _finish_frame(payload: bytes, residue: int) -> bytes:
    if len(payload) != FRAME_BYTES - 2:
        raise ValueError("ordinary frame payload must contain 36 bytes")
    if residue not in TRAILER_RESIDUES:
        raise ValueError("unknown ordinary-frame trailer residue")
    trailer = binascii.crc_hqx(payload, 0) ^ residue
    return payload + trailer.to_bytes(2, "big")


def build_open_frame(
    link: ValveLink, sequence: int, duration_seconds: int, residue: int
) -> bytes:
    """Build one offline HTV145 open-command candidate."""
    _validate_sequence(sequence)
    body = bytes((sequence, 0x10, 0x82, 0x80, 0x81, 0x00))
    body += encode_duration(duration_seconds)
    body += bytes(15)
    return _finish_frame(
        SYNC + link.controller_endpoint + link.valve_endpoint + body, residue
    )


def build_close_frame(link: ValveLink, sequence: int, residue: int) -> bytes:
    """Build one offline HTV145 close-command candidate."""
    _validate_sequence(sequence)
    body = bytes((sequence, 0x90, 0x81, 0x80, 0x81, 0x00)) + bytes(17)
    return _finish_frame(
        SYNC + link.controller_endpoint + link.valve_endpoint + body, residue
    )


def open_candidates(
    link: ValveLink, sequence: int, duration_seconds: int
) -> tuple[bytes, bytes]:
    """Return both unresolved trailer candidates without transmitting either."""
    return tuple(
        build_open_frame(link, sequence, duration_seconds, residue)
        for residue in TRAILER_RESIDUES
    )


def close_candidates(link: ValveLink, sequence: int) -> tuple[bytes, bytes]:
    """Return both unresolved trailer candidates without transmitting either."""
    return tuple(
        build_close_frame(link, sequence, residue) for residue in TRAILER_RESIDUES
    )
