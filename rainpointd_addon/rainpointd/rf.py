"""RainPoint 2-FSK frame normalization and confirmed HCS026 fields."""

from __future__ import annotations

from typing import Any


SYNC = bytes.fromhex("79f4882f28")
FRAME_BYTES = 38
HUB_ENDPOINT = "b42d008f"
VALVE_ENDPOINT = "b9840280"
HCS026_ENDPOINTS = {
    "9ce58024",
    "c4e50024",
    "ce628024",
    "d1e28024",
}
FLEX_DECODER = (
    "n=RainPoint,m=FSK_PCM,s=48,l=48,r=49152,"
    "bits>=620,match={40}79f4882f28"
)


def _row_bits(row: dict[str, Any]) -> str:
    """Return exactly the valid bits from an rtl_433 bit row."""
    bit_count = int(row["len"])
    bits = "".join(f"{int(nibble, 16):04b}" for nibble in row["data"])
    if len(bits) < bit_count:
        raise ValueError("rtl_433 row contains fewer bits than advertised")
    return bits[:bit_count]


def _soil_moisture(frame: bytes) -> int | None:
    """Decode either field position confirmed in HCS026FRF reports."""
    if len(frame) != FRAME_BYTES:
        return None
    if frame[9:13].hex() not in HCS026_ENDPOINTS:
        return None
    for marker_index in (20, 18):
        if frame[marker_index] & 0x7F != 0x44:
            continue
        percent = frame[marker_index + 1] * 2 + (
            1 if frame[marker_index + 2] & 0x80 else 0
        )
        if 0 <= percent <= 100:
            return percent
    return None


def _valve_fields(frame: bytes) -> dict[str, Any]:
    """Decode confirmed receive-only HTV145 command and usage fields."""
    if len(frame) != FRAME_BYTES:
        return {}
    endpoint_a = frame[5:9].hex()
    endpoint_b = frame[9:13].hex()

    if endpoint_a == HUB_ENDPOINT and endpoint_b == VALVE_ENDPOINT:
        # The open/close flag is the high bit of byte 14. Open commands carry
        # the requested duration at bytes 19-20 in two-second units.
        if frame[14] & 0x7F != 0x10:
            return {}
        watering = not bool(frame[14] & 0x80)
        result: dict[str, Any] = {
            "is_watering": watering,
            "valve_state": "watering" if watering else "idle",
        }
        if watering:
            duration_seconds = int.from_bytes(frame[19:21], "little") * 2
            if 0 < duration_seconds <= 24 * 60 * 60:
                result["duration_seconds"] = duration_seconds
        return result

    if endpoint_a == VALVE_ENDPOINT and endpoint_b == HUB_ENDPOINT:
        # 0x4f/0xcf marks last-session usage. The following bytes hold a
        # packed half-value plus an odd-value flag, in tenths of a liter.
        if frame[20] & 0x7F != 0x4F:
            return {}
        half_tenths = ((frame[22] & 0x7F) << 8) | (frame[21] & 0x7F)
        tenths_liters = half_tenths * 2 + int(bool(frame[22] & 0x80))
        if 0 <= tenths_liters <= 100_000:
            return {"last_usage_liters": round(tenths_liters / 10, 1)}
    return {}


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Locate sync and normalize either observed preamble length."""
    bits = _row_bits(row)
    sync_bits = "".join(f"{byte:08b}" for byte in SYNC)
    sync_offset = bits.find(sync_bits)
    inverted = False

    if sync_offset < 0:
        inverted_bits = bits.translate(str.maketrans("01", "10"))
        sync_offset = inverted_bits.find(sync_bits)
        if sync_offset < 0:
            raise ValueError("RainPoint sync word not found")
        bits = inverted_bits
        inverted = True

    framed_bits = bits[sync_offset:]
    full_bytes = bytes(
        int(framed_bits[index : index + 8], 2)
        for index in range(0, len(framed_bits) - 7, 8)
    )
    if len(full_bytes) < FRAME_BYTES:
        raise ValueError(
            f"truncated RainPoint frame: {len(full_bytes)} of {FRAME_BYTES} bytes"
        )

    frame = full_bytes[:FRAME_BYTES]
    result = {
        "bit_count": len(bits),
        "preamble_bits": sync_offset,
        "inverted": inverted,
        "frame_bits": len(framed_bits),
        "trailing_bits": len(framed_bits) - FRAME_BYTES * 8,
        "frame_hex": frame.hex(),
        "sync": frame[:5].hex(),
        "endpoint_a": frame[5:9].hex(),
        "endpoint_b": frame[9:13].hex(),
        "message_type": frame[13],
        "message_body": frame[13:-2].hex(),
        "trailer": frame[-2:].hex(),
    }
    moisture = _soil_moisture(frame)
    if moisture is not None:
        result["soil_moisture_percent"] = moisture
    result.update(_valve_fields(frame))
    return result
