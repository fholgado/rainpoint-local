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


def decode_htv405_control_frame(frame: bytes) -> dict[str, int | bool] | None:
    """Decode the passively validated HTV405 four-zone control body.

    The layout is based on crossed stock-gateway and local-gateway trials. The
    paired logical address occupies the low seven bits of byte 16; captures at
    app addresses 2 and 6 carried 0x82 and 0x86 respectively.
    """
    if len(frame) != FRAME_BYTES:
        return None
    logical_address = frame[16] & 0x7F
    if (
        frame[15] != 0x07
        or not frame[16] & 0x80
        or logical_address == 0
        # Stock-controlled captures used selector 0x85. A valve enrolled by
        # the local bridge uses the same body layout with selector 0x05. The
        # high bit is therefore association state, not part of the model/type
        # discriminator.
        or frame[17] & 0x7F != 0x05
        or frame[20] & 0x7F != 0x4F
        or frame[25] != 0x40
        or frame[28] != 0x56
    ):
        return None

    # Stock/selector-6 reports use a pair index plus odd/even bit. Locally
    # enrolled selector-2 reports instead expose the one-based port directly
    # in byte 19 bits 4--6 (0x10, 0x20, 0x30, 0x40). Both layouts were crossed
    # against accepted Zone 1--4 commands.
    watering = bool(frame[20] & 0x80)
    local_zone = (frame[19] & 0x70) >> 4
    direct_local_layout = (
        frame[17] == 0x05
        and frame[19] & 0x0F == 0
        and (
            watering
            or (frame[18] == 0x80 and frame[19] == 0x80)
        )
    )
    if direct_local_layout:
        # Locally associated idle reports clear the direct port nibble. Zone 0
        # therefore means "no active outlet" and lets the stateful transport
        # clear whichever of the four mutually exclusive outlets was active.
        # Older captured/synthetic selector-2 reports retain the stock
        # pair/odd layout and are distinguished by their low-nibble marker.
        zone = local_zone
    else:
        zone = (frame[18] & 0x7F) * 2 + int(bool(frame[19] & 0x80))
    if zone not in range(1, 5) and not (zone == 0 and not watering):
        return None

    result: dict[str, int | bool] = {
        "zone": zone,
        "is_watering": watering,
    }
    if watering:
        duration_units = frame[29] & 0x7F
        if duration_units:
            result["duration_seconds"] = duration_units * 2
        # Across all eight opens this value was the requested duration minus
        # the elapsed app-to-radio delay, also in two-second units.
        result["remaining_seconds"] = (frame[26] & 0x7F) * 2
    return result


def is_htv405_link_frame(frame: bytes) -> bool:
    """Recognize a strict HTV405 paired-link report without inferring state.

    Periodic reports from a locally enrolled valve use selector 0x07. Their
    pair/odd fields cycle and therefore must not be interpreted as zone state,
    but the stable structural markers are sufficient to persist the RF link.
    """
    if len(frame) != FRAME_BYTES:
        return False
    return bool(
        frame[15] == 0x07
        and frame[16] & 0x80
        and frame[16] & 0x7F
        and frame[17] & 0x7F in {0x05, 0x07}
        and frame[20] & 0x7F == 0x4F
        and frame[25] == 0x40
        and frame[28] == 0x56
    )


def build_htv405_close_frame(
    link: ValveLink,
    *,
    sequence: int,
    zone: int,
    selector: int,
    repeat: bool,
    residue: int,
) -> bytes:
    """Build one offline HTV405 idempotent-close candidate.

    This remains deliberately disconnected from every transport. Sequence,
    association selector, endpoints, repeat phase, and trailer residue must all
    come from the isolated valve session being tested.
    """
    if sequence not in range(0x20):
        raise ValueError("HTV405 sequence must be in the observed 0x00..0x1f range")
    if zone not in range(1, 5):
        raise ValueError("HTV405 zone must be between 1 and 4")
    if selector not in (0x05, 0x85):
        raise ValueError("HTV405 selector must come from an observed association")
    zone_pair = 0x80 | (zone // 2)
    odd_zone = 0x80 if zone % 2 else 0x00
    body = bytes(
        (
            sequence,
            0x81 if repeat else 0x01,
            0x07,
            0x82,
            selector,
            zone_pair,
            odd_zone,
            0x4F,
            0x80,
            0x00,
            0x00,
            0x00,
            0x40,
            0x80,
            0x00,
            0x56,
            0x80,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
        )
    )
    return _finish_frame(
        SYNC + link.controller_endpoint + link.valve_endpoint + body,
        residue,
    )


def htv405_close_candidates(
    link: ValveLink, *, sequence: int, zone: int, selector: int
) -> tuple[bytes, ...]:
    """Return all unresolved close phases without transmitting any of them."""
    return tuple(
        build_htv405_close_frame(
            link,
            sequence=sequence,
            zone=zone,
            selector=selector,
            repeat=repeat,
            residue=residue,
        )
        for repeat in (False, True)
        for residue in TRAILER_RESIDUES
    )


def next_htv405_phase(frame: bytes) -> tuple[int, bool]:
    """Return the sequence/repeat phase following one paired-link report."""
    if not is_htv405_link_frame(frame):
        raise ValueError("frame is not a recognized HTV405 paired-link report")
    sequence = frame[13] & 0x1F
    repeated = bool(frame[14] & 0x80)
    return (((sequence + 1) & 0x1F), False) if repeated else (sequence, True)


def htv405_phase_state(frame: bytes) -> dict[str, int | bool]:
    """Expose the lower-channel telemetry phase without implying TX state.

    The valve's periodic report counter is independent of the counter used by
    gateway commands.  Keeping the historical function name avoids a storage
    migration dependency, while the returned field names make that boundary
    explicit to every caller.
    """
    next_sequence_value, next_repeat = next_htv405_phase(frame)
    return {
        "rf_telemetry_sequence": frame[13] & 0x1F,
        "rf_telemetry_repeat": bool(frame[14] & 0x80),
        "rf_next_telemetry_sequence": next_sequence_value,
        "rf_next_telemetry_repeat": next_repeat,
    }


def decode_htv405_gateway_command_response(
    frame: bytes,
) -> dict[str, int | bool] | None:
    """Decode an authenticated high-carrier HTV405 command response.

    This envelope was physically validated for accepted opens on Zones 1--4
    and a Zone 1 close. It proves resulting watering state, accepted controller
    counter, and the selected zone.
    """
    if len(frame) != FRAME_BYTES or not frame.startswith(SYNC):
        return None
    residual = binascii.crc_hqx(frame[:-2], 0) ^ int.from_bytes(
        frame[-2:], "big"
    )
    if residual not in TRAILER_RESIDUES:
        return None
    if (
        frame[14] & 0x7F != 0x50
        or frame[15] != 0x86
        or frame[17] & 0x0F
        or frame[17] >> 4 not in range(1, 5)
        or frame[18] & 0x7F != 0x4F
        or frame[23] != 0x40
        or frame[26] != 0x56
        or (frame[14] ^ frame[18]) & 0x80
    ):
        return None
    sequence = frame[13] & 0x1F
    return {
        "rf_control_response_sequence": sequence,
        "rf_next_control_sequence": (sequence + 1) & 0x1F,
        "rf_control_response_zone": frame[17] >> 4,
        "rf_control_response_watering": bool(frame[18] & 0x80),
    }


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
