#!/usr/bin/env python3
"""Small standalone decoder for captured RainPoint RF status payloads.

This intentionally covers only the two models observed in this installation:

* HTV145FRF irrigation valve
* HCS026FRF soil-moisture sensor

It is independent of Home Assistant and the HomGar cloud integration.
"""

from __future__ import annotations

import argparse
import json
import struct
from datetime import datetime
from typing import Any


TYPE_NAMES = {
    2: "alarm",
    10: "humidity",
    15: "last_usage",
    19: "duration",
    21: "event_time",
    30: "work_state",
    31: "battery",
    32: "rssi",
    54: "report_time",
}

WORK_MODES = {
    0: "idle",
    1: "irrigation",
    2: "mist",
    3: "cycle",
    7: "soak",
}

BATTERY_PERCENT = {
    0: 100,
    1: 100,
    2: 10,
    3: 10,
    4: 10,
}


def _parse_frame(frame: str) -> bytes:
    cleaned = frame.strip()
    if "#" not in cleaned:
        raise ValueError("expected a RainPoint payload containing '#'")
    prefix, payload_hex = cleaned.split("#", 1)
    if len(prefix) != 2 or not prefix.isdigit():
        raise ValueError(f"unsupported payload prefix: {prefix!r}")
    try:
        return bytes.fromhex(payload_hex)
    except ValueError as exc:
        raise ValueError("payload after '#' is not valid hexadecimal") from exc


def parse_tlv(frame: str) -> list[dict[str, Any]]:
    """Parse the compact RainPoint TLV stream without model interpretation."""
    data = _parse_frame(frame)
    entries: list[dict[str, Any]] = []
    offset = 0

    while offset < len(data):
        header = data[offset]
        start = offset

        if header & 0x80 == 0:
            type_code = (header >> 4) & 0x07
            payload = bytes([header & 0x0F])
            offset += 1
        else:
            short_code = (header >> 2) & 0x1F
            payload_len = (header & 0x03) + 1
            offset += 1

            if short_code <= 30:
                type_code = short_code + 8
            else:
                if offset >= len(data):
                    raise ValueError("truncated extended TLV type")
                type_code = data[offset] + 39
                offset += 1

            end = offset + payload_len
            if end > len(data):
                raise ValueError("truncated TLV payload")
            payload = data[offset:end]
            offset = end

        entries.append(
            {
                "offset": start,
                "type_code": type_code,
                "name": TYPE_NAMES.get(type_code, f"unknown_{type_code}"),
                "payload_hex": payload.hex().upper(),
                "value_bytes": list(payload),
            }
        )

    return entries


def _entry(entries: list[dict[str, Any]], type_code: int) -> dict[str, Any] | None:
    return next((item for item in entries if item["type_code"] == type_code), None)


def _unsigned_le(entry: dict[str, Any]) -> int:
    return int.from_bytes(bytes(entry["value_bytes"]), "little", signed=False)


def _packed_local_datetime(entry: dict[str, Any]) -> str | None:
    payload = bytes(entry["value_bytes"])
    if len(payload) != 4:
        return None
    raw = struct.unpack("<I", payload)[0]
    second = raw & 0x3F
    minute = (raw >> 6) & 0x3F
    hour = (raw >> 12) & 0x1F
    day = (raw >> 17) & 0x1F
    month = (raw >> 22) & 0x0F
    year = ((raw >> 26) & 0x3F) + 2020
    try:
        # The RF field contains the device's local wall-clock time, not UTC.
        return datetime(year, month, day, hour, minute, second).isoformat()
    except ValueError:
        return None


def decode(frame: str, model: str) -> dict[str, Any]:
    """Decode an HTV145FRF or HCS026FRF status frame."""
    normalized_model = model.strip().upper()
    if normalized_model not in {"HTV145FRF", "HCS026FRF"}:
        raise ValueError(f"unsupported model: {model}")

    entries = parse_tlv(frame)
    result: dict[str, Any] = {
        "model": normalized_model,
        "raw": frame.strip(),
    }

    rssi = _entry(entries, 32)
    if rssi and rssi["value_bytes"]:
        raw_rssi = rssi["value_bytes"][0]
        result["rssi_dbm"] = raw_rssi - 256 if raw_rssi > 127 else raw_rssi

    battery = _entry(entries, 31)
    if battery and battery["value_bytes"]:
        status = battery["value_bytes"][0]
        result["battery_status"] = status
        result["battery_percent"] = BATTERY_PERCENT.get(status)

    report_time = _entry(entries, 54)
    if report_time:
        packed_time = _packed_local_datetime(report_time)
        if packed_time:
            result["report_time_local"] = packed_time

    if normalized_model == "HCS026FRF":
        humidity = _entry(entries, 10)
        if humidity and humidity["value_bytes"]:
            result["soil_moisture_percent"] = humidity["value_bytes"][0]
    else:
        work_state = _entry(entries, 30)
        if work_state and work_state["value_bytes"]:
            raw_mode = work_state["value_bytes"][0] & 0x0F
            result["work_mode"] = raw_mode
            result["valve_state"] = WORK_MODES.get(raw_mode, f"unknown_{raw_mode}")
            result["is_watering"] = raw_mode != 0

        alarm = _entry(entries, 2)
        if alarm and alarm["value_bytes"]:
            result["alarm"] = alarm["value_bytes"][0] & 0x0F

        duration = _entry(entries, 19)
        if duration:
            result["duration_seconds"] = _unsigned_le(duration)

        usage = _entry(entries, 15)
        if usage:
            result["last_usage_liters"] = round(_unsigned_le(usage) / 10.0, 1)

        event_time = _entry(entries, 21)
        if event_time:
            packed_time = _packed_local_datetime(event_time)
            if packed_time:
                result["event_time_local"] = packed_time

    result["tlv"] = entries
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", choices=["HTV145FRF", "HCS026FRF"])
    parser.add_argument("frame", help="RainPoint status payload, for example 10#E1...")
    parser.add_argument("--compact", action="store_true", help="emit compact JSON")
    args = parser.parse_args()

    indent = None if args.compact else 2
    print(json.dumps(decode(args.frame, args.model), indent=indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
