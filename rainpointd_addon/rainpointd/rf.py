"""RainPoint 2-FSK frame normalization and confirmed HCS026 fields."""

from __future__ import annotations

import binascii
from typing import Any

from .device_catalog import DeviceCatalog, LEGACY_HOME_CATALOG
from .valve_protocol import (
    ValveLink,
    decode_duration,
    decode_htv145_command_response,
    decode_htv145_gateway_command,
    decode_htv145_state_report,
    decode_htv145_terminal_idle_report,
    decode_htv405_control_frame,
)


SYNC = bytes.fromhex("79f4882f28")
FRAME_BYTES = 38
# HCS026 extended reports replace the normal 0x24 family suffix with the
# catalog product code 0x48. Canonicalize only identities already established
# by ordinary telemetry so a marker-like payload cannot create a new device.
HCS026_PRODUCT_CODE = 0x48
HCS026_FACTORY_BROADCAST = "80000000"
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


def _canonical_hcs026_endpoint(
    endpoint: bytes, catalog: DeviceCatalog
) -> str | None:
    """Return the established endpoint for normal or product-code reports."""
    endpoint_hex = endpoint.hex()
    if endpoint_hex in catalog.sensor_endpoints:
        return endpoint_hex
    if endpoint[-1] != HCS026_PRODUCT_CODE:
        return None
    ordinary_endpoint = (endpoint[:-1] + bytes([HCS026_PRODUCT_CODE >> 1])).hex()
    return (
        ordinary_endpoint
        if ordinary_endpoint in catalog.sensor_endpoints
        else None
    )


def _compact_status_fields(frame: bytes) -> dict[str, Any]:
    """Decode catalog-correlated status TLVs without assigning a device."""
    body = frame[13:-2]
    result: dict[str, Any] = {}
    for index in range(len(body) - 1):
        # 0x88 is the compact type-10/U8 header. Ordinary product-code reports
        # prefix it with field code 10. Other retained status frames prefix it
        # with a slot-like byte but immediately follow the value with the
        # type-32 signed RSSI header, which makes the sequence unambiguous.
        if body[index] != 0x88:
            continue
        has_field_code = index > 0 and body[index - 1] == 0x0A
        has_rssi = index + 3 < len(body) and body[index + 2] == 0xE0
        if not has_field_code and not has_rssi:
            continue
        moisture = body[index + 1]
        if moisture <= 100:
            result["status_soil_moisture_percent"] = moisture
        # Compact type 32 / signed-byte RSSI can immediately follow moisture.
        if has_rssi:
            raw_rssi = body[index + 3]
            hub_rssi = raw_rssi - 256 if raw_rssi > 127 else raw_rssi
            if -120 <= hub_rssi <= 0:
                result["hub_rssi_db"] = hub_rssi
        break
    return result


def _associated_hcs026_fields(frame: bytes) -> dict[str, Any]:
    """Decode a strict, unassigned controller-relay moisture report.

    The stock installation repeatedly relays one associated HCS026 reading
    through a valve/controller route rather than the sensor's ordinary RF
    endpoint.  The relay is useful migration evidence, but the RF envelope
    alone does not identify which sensor is associated.  Retain the value
    under an explicitly unassigned key so it cannot update a sensor entity.
    """
    if len(frame) != FRAME_BYTES:
        return {}
    if _trailer_fields(frame).get("trailer_valid") is not True:
        return {}
    if (
        frame[15:20] != bytes.fromhex("0405818005")
        or frame[20] & 0x7F != 0x44
        or frame[22] & 0x7F != 0x70
        or any(frame[25:36])
    ):
        return {}
    percent = frame[21] * 2 + int(bool(frame[22] & 0x80))
    if not 0 <= percent <= 100:
        return {}
    return {"associated_soil_moisture_percent": percent}


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


def _hcs026_routine_ack_candidate(
    frame: bytes, catalog: DeviceCatalog
) -> dict[str, Any]:
    """Identify the observed stock-gateway routine acknowledgement shape.

    Same-file IQ establishes that these reversed endpoint frames originate at
    the gateway after sensor reports. Byte 17 remains an unknown constant, not
    a sensor battery field.
    """
    if len(frame) != FRAME_BYTES:
        return {}
    endpoint = frame[5:9].hex()
    if endpoint not in catalog.sensor_endpoints:
        return {}
    companion = frame[9:13]
    if companion[0] & 0x80:
        return {}
    controller = (bytes([companion[0] | 0x80]) + companion[1:]).hex()
    if controller not in catalog.hcs026_pairing_peers:
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
        "routine_ack_endpoint": endpoint,
        "routine_ack_message": frame[13] & 0x7F,
        "routine_ack_body_code": status,
        "routine_ack_controller_endpoint": controller,
        "routine_ack_companion_endpoint": companion.hex(),
    }


def _hcs026_pairing_fields(
    frame: bytes, catalog: DeviceCatalog
) -> dict[str, Any]:
    """Decode the validated HCS026 factory/paired enrollment layout.

    Two controlled sensors showed a four-byte factory identity whose first
    byte gains bit 7 after enrollment. Factory announcements use 80000000 as
    the other endpoint. Paired reports use the established b9840280 RainPoint
    gateway. Moisture and battery fields are decoded separately from their
    marker-relative report layout.
    """
    if len(frame) != FRAME_BYTES or frame[12] != 0x24:
        return {}
    endpoint_a = frame[5:9].hex()
    endpoint_b = frame[9:13]
    message_type = frame[13] & 0x7F

    if (
        endpoint_a == HCS026_FACTORY_BROADCAST
        and not endpoint_b[0] & 0x80
        and message_type in {1, 2, 4}
    ):
        return {
            "hcs026_factory_endpoint": endpoint_b.hex(),
            "hcs026_pairing_state": "factory",
        }

    if (
        endpoint_a not in catalog.hcs026_pairing_peers
        or not endpoint_b[0] & 0x80
        or message_type not in {1, 2, 3, 4, 5, 6}
    ):
        return {}

    factory = bytes([endpoint_b[0] & 0x7F]) + endpoint_b[1:]
    return {
        "hcs026_factory_endpoint": factory.hex(),
        "hcs026_paired_endpoint": endpoint_b.hex(),
        "hcs026_pairing_state": "paired",
    }


def _hcs026_report_fields(
    frame: bytes, catalog: DeviceCatalog
) -> dict[str, Any]:
    """Decode marker-relative moisture and categorical battery fields."""
    if len(frame) != FRAME_BYTES:
        return {}
    canonical_endpoint = _canonical_hcs026_endpoint(frame[9:13], catalog)
    paired_endpoint = bool(
        frame[12] == 0x24
        and frame[5:9].hex() in catalog.hcs026_pairing_peers
        and frame[9] & 0x80
        and (frame[13] & 0x7F) in {1, 2, 3, 4, 5, 6}
    )
    if canonical_endpoint is None and not paired_endpoint:
        return {}
    # A retained Front Yard Sensor 2 report used the full HCS02x product code
    # in its endpoint suffix and carried a HomGar-style one-byte type-10 TLV:
    # 0x88 0x4f -> STA_RH/soil moisture, 79 percent. Its normal-endpoint
    # acknowledgement followed 180 ms later.
    if frame[12] == HCS026_PRODUCT_CODE:
        moisture = _compact_status_fields(frame).get(
            "status_soil_moisture_percent"
        )
        return (
            {"soil_moisture_percent": moisture}
            if moisture is not None
            else {}
        )
    for marker_index in (20, 18):
        if frame[marker_index] & 0x7F != 0x44:
            continue
        percent = frame[marker_index + 1] * 2 + (
            1 if frame[marker_index + 2] & 0x80 else 0
        )
        if 0 <= percent <= 100:
            result: dict[str, Any] = {"soil_moisture_percent": percent}
            # The controlled full/low/full transition established bit 0x04 in
            # the byte immediately before the moisture marker. Its absolute
            # position shifts with the two observed HCS026 report layouts.
            # Only trailer-valid reports may update supported battery state.
            if _trailer_fields(frame).get("trailer_valid") is True:
                battery_normal = bool(frame[marker_index - 1] & 0x04)
                result.update(
                    {
                        "battery_low": not battery_normal,
                        "battery_status": 1 if battery_normal else 2,
                        "battery_percent": 100 if battery_normal else 10,
                    }
                )
            return result
    return {}


def _packed_valve_usage_tenths(
    first: int, second: int, extension: int
) -> int:
    """Decode the packed HTV145 last-session usage value."""
    half_tenths = (
        ((second & 0x7F) << 8)
        | (first & 0x7F)
        | (extension & 0x80)
    )
    return half_tenths * 2 + int(bool(second & 0x80))


def _valve_fields(
    frame: bytes, catalog: DeviceCatalog
) -> dict[str, Any]:
    """Decode confirmed receive-only HTV145 command and usage fields."""
    if len(frame) != FRAME_BYTES:
        return {}
    endpoint_a = frame[5:9].hex()
    endpoint_b = frame[9:13].hex()

    valve = catalog.valve_link(endpoint_a, endpoint_b)
    if valve is None:
        return {}

    if (
        endpoint_a == valve.controller_endpoint
        and endpoint_b == valve.valve_endpoint
    ):
        if valve.model.upper() == "HTV405FRF":
            decoded = decode_htv405_control_frame(frame)
            if decoded is None:
                return {}
            watering = bool(decoded["is_watering"])
            return {
                **decoded,
                "valve_state": "watering" if watering else "idle",
            }
        link = ValveLink(
            bytes.fromhex(valve.controller_endpoint),
            bytes.fromhex(valve.valve_endpoint),
        )
        command = decode_htv145_gateway_command(frame, link)
        if command is None:
            return {}
        # A controller request is intent, never device state. In particular,
        # an SDR can hear our own local request even when the valve rejects it.
        # Retain the request for protocol/counter analysis without publishing
        # watering state until a valve-originated response or report arrives.
        result: dict[str, Any] = {
            "valve_command": "open" if command["watering"] else "close",
            "command_sequence": command["sequence"],
        }
        if command["watering"]:
            result["requested_duration_seconds"] = command[
                "duration_seconds"
            ]
        return result

    if (
        endpoint_a == valve.valve_endpoint
        and endpoint_b == valve.controller_endpoint
    ):
        link = ValveLink(
            bytes.fromhex(valve.controller_endpoint),
            bytes.fromhex(valve.valve_endpoint),
        )
        command_response = decode_htv145_command_response(frame, link)
        if command_response is not None:
            watering = bool(command_response["watering"])
            result: dict[str, Any] = {
                "is_watering": watering,
                "valve_state": "watering" if watering else "idle",
                "command_response_sequence": command_response["sequence"],
            }
            try:
                duration_seconds = decode_duration(frame[27:29])
            except ValueError:
                pass
            else:
                result["duration_seconds"] = duration_seconds
            return result

        # A terminal/summary response family omits the 0x4f marker but carries
        # the same packed usage value at bytes 24-26.  Bytes 28-29 repeat the
        # requested duration in two-second units.  Five exact cloud/RF
        # correlations cover 81.9-106.3 L, including today's low-battery
        # 600-second run.  Battery is intentionally not decoded here: full and
        # low cloud states share the stable bytes in this response layout.
        terminal = decode_htv145_terminal_idle_report(frame, link)
        if terminal is not None:
            tenths_liters = _packed_valve_usage_tenths(
                frame[24], frame[25], frame[26]
            )
            if not 0 <= tenths_liters <= 100_000:
                return {}
            result = {
                "is_watering": False,
                "valve_state": "idle",
                "last_usage_liters": round(tenths_liters / 10, 1),
            }
            result["duration_seconds"] = terminal["duration_seconds"]
            return result

        # 0x4f/0xcf marks last-session usage. The following bytes hold a
        # packed half-value plus an odd-value flag, in tenths of a liter.
        state_report = decode_htv145_state_report(frame, link)
        if state_report is None:
            return {}
        # Bit 7 of the first packed byte is overloaded. Cloud/RF correlation
        # showed that frame[23] bit 7 selects whether it is value bit 7 or an
        # overlay flag; frame[22] bit 7 remains the odd-tenths flag.
        tenths_liters = _packed_valve_usage_tenths(
            frame[21], frame[22], frame[23]
        )
        if 0 <= tenths_liters <= 100_000:
            battery_low = bool(frame[17] & 0x08)
            watering = bool(state_report["watering"])
            result = {
                "is_watering": watering,
                "valve_state": "watering" if watering else "idle",
                "last_usage_liters": round(tenths_liters / 10, 1),
                "battery_low": battery_low,
                "battery_status": 2 if battery_low else 1,
                "battery_percent": 10 if battery_low else 100,
            }
            try:
                duration_seconds = decode_duration(frame[29:31])
            except ValueError:
                pass
            else:
                result["duration_seconds"] = duration_seconds
            return result
    return {}


def normalize_row(
    row: dict[str, Any], *, catalog: DeviceCatalog = LEGACY_HOME_CATALOG
) -> dict[str, Any]:
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
    canonical_endpoint_b = _canonical_hcs026_endpoint(frame[9:13], catalog)
    if canonical_endpoint_b and canonical_endpoint_b != result["endpoint_b"]:
        result["canonical_endpoint_b"] = canonical_endpoint_b
        result["product_code"] = frame[12]
    result.update(_compact_status_fields(frame))
    result.update(_associated_hcs026_fields(frame))
    result.update(_hcs026_routine_ack_candidate(frame, catalog))
    result.update(_hcs026_pairing_fields(frame, catalog))
    result.update(_hcs026_report_fields(frame, catalog))
    result.update(_valve_fields(frame, catalog))
    return result
