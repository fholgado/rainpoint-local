"""RainPoint 2-FSK frame normalization and confirmed HCS026 fields."""

from __future__ import annotations

import binascii
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
# HCS026 extended reports replace the normal 0x24 family suffix with the
# catalog product code 0x48. Canonicalize only identities already established
# by ordinary telemetry so a marker-like payload cannot create a new device.
HCS026_PRODUCT_CODE = 0x48
HCS026_COMPANION_ENDPOINT = "39840280"
# Ordinary 38-byte frames use CRC-CCITT (poly 0x1021, init 0) over bytes
# 0..35. The transmitted trailer differs by one of two unresolved residues.
# Both residues occur across prefix lengths and with open/close traffic.
TRAILER_RESIDUES = {0xC713, 0x4F03}
FLEX_DECODER = (
    "n=RainPoint,m=FSK_PCM,s=50,l=50,r=50000,"
    "bits>=620,match={40}79f4882f28"
)


def _row_bits(row: dict[str, Any]) -> str:
    """Return exactly the valid bits from an rtl_433 bit row."""
    bit_count = int(row["len"])
    bits = "".join(f"{int(nibble, 16):04b}" for nibble in row["data"])
    if len(bits) < bit_count:
        raise ValueError("rtl_433 row contains fewer bits than advertised")
    return bits[:bit_count]


def _canonical_hcs026_endpoint(endpoint: bytes) -> str | None:
    """Return the established endpoint for normal or product-code reports."""
    endpoint_hex = endpoint.hex()
    if endpoint_hex in HCS026_ENDPOINTS:
        return endpoint_hex
    if endpoint[-1] != HCS026_PRODUCT_CODE:
        return None
    ordinary_endpoint = (endpoint[:-1] + bytes([HCS026_PRODUCT_CODE >> 1])).hex()
    return ordinary_endpoint if ordinary_endpoint in HCS026_ENDPOINTS else None


def _compact_status_fields(frame: bytes) -> dict[str, Any]:
    """Decode catalog-correlated status TLVs without assigning a device."""
    body = frame[13:-2]
    result: dict[str, Any] = {}
    for index in range(len(body) - 2):
        # Field code 10 followed by compact type-10/U8 header and value.
        if body[index : index + 2] != b"\x0a\x88":
            continue
        moisture = body[index + 2]
        if moisture <= 100:
            result["status_soil_moisture_percent"] = moisture
        # Compact type 32 / signed-byte RSSI can immediately follow moisture.
        if index + 4 < len(body) and body[index + 3] == 0xE0:
            raw_rssi = body[index + 4]
            hub_rssi = raw_rssi - 256 if raw_rssi > 127 else raw_rssi
            if -120 <= hub_rssi <= 0:
                result["hub_rssi_db"] = hub_rssi
        break
    return result


def _trailer_fields(frame: bytes) -> dict[str, Any]:
    """Return the observed CRC-CCITT residual for a normalized frame."""
    if len(frame) != FRAME_BYTES:
        return {}
    computed = binascii.crc_hqx(frame[:-2], 0)
    observed = int.from_bytes(frame[-2:], "big")
    residual = computed ^ observed
    return {
        "trailer_residual": f"{residual:04x}",
        "trailer_valid": residual in TRAILER_RESIDUES,
    }


def _hcs026_battery_candidate(frame: bytes) -> dict[str, Any]:
    """Retain the provisional HCS026 heartbeat battery field.

    All 358 companion heartbeats in the retained capture used status 1 while
    the independently observed stock entities reported normal/100%. A
    controlled low-battery transition is still required before this can be a
    supported device field.
    """
    if len(frame) != FRAME_BYTES:
        return {}
    endpoint = frame[5:9].hex()
    if endpoint not in HCS026_ENDPOINTS:
        return {}
    if frame[9:13].hex() != HCS026_COMPANION_ENDPOINT:
        return {}
    if (
        frame[14] & 0x7F != 0x41
        or frame[15] != 0x81
        or frame[16] != 0x00
        or frame[18] != 0x00
    ):
        return {}
    status = frame[17]
    if status > 4:
        return {}
    return {
        "battery_endpoint": endpoint,
        "battery_status_candidate": status,
        "battery_percent_candidate": 100 if status in (0, 1) else 10,
    }


def _soil_moisture(frame: bytes) -> int | None:
    """Decode either field position confirmed in HCS026FRF reports."""
    if len(frame) != FRAME_BYTES:
        return None
    canonical_endpoint = _canonical_hcs026_endpoint(frame[9:13])
    if canonical_endpoint is None:
        return None
    # A retained Front Yard Sensor 2 report used the full HCS02x product code
    # in its endpoint suffix and carried a HomGar-style one-byte type-10 TLV:
    # 0x88 0x4f -> STA_RH/soil moisture, 79 percent. Its normal-endpoint
    # acknowledgement followed 180 ms later.
    if frame[12] == HCS026_PRODUCT_CODE:
        return _compact_status_fields(frame).get("status_soil_moisture_percent")
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
    """Locate sync and normalize any observed wake/prefix length."""
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
    result.update(_trailer_fields(frame))
    canonical_endpoint_b = _canonical_hcs026_endpoint(frame[9:13])
    if canonical_endpoint_b and canonical_endpoint_b != result["endpoint_b"]:
        result["canonical_endpoint_b"] = canonical_endpoint_b
        result["product_code"] = frame[12]
    result.update(_compact_status_fields(frame))
    result.update(_hcs026_battery_candidate(frame))
    moisture = _soil_moisture(frame)
    if moisture is not None:
        result["soil_moisture_percent"] = moisture
    result.update(_valve_fields(frame))
    return result
