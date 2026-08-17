#!/usr/bin/env python3
"""Verify the standard radio-node image has the intended command boundary."""

from __future__ import annotations

import sys
from pathlib import Path


FORBIDDEN_BENCH_COMMANDS = (
    b"pairing_arm_b",
    b"pairing_probe_b",
    b"pairing_offset_hz",
    b"pairing_power_dbm",
    b"pairing_clock_local",
    b"pairing_invert",
)

REQUIRED_CAPABILITIES = (
    b"routine_sensor_ack_tx",
    b"valve_pairing_tx_candidate",
    b"firmware_update_start",
    b"firmware_update_trial",
    b"verified_sha256",
)

FORBIDDEN_VALVE_CONTROL_COMMANDS = (
    b"valve_open",
    b"valve_close",
    b"valve_start",
    b"watering_start",
)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_firmware_boundaries.py FIRMWARE_BIN")
        return 2
    firmware = Path(sys.argv[1]).read_bytes()
    leaked = [
        value.decode() for value in FORBIDDEN_BENCH_COMMANDS if value in firmware
    ]
    leaked.extend(
        value.decode()
        for value in FORBIDDEN_VALVE_CONTROL_COMMANDS
        if value in firmware
    )
    missing = [
        value.decode() for value in REQUIRED_CAPABILITIES if value not in firmware
    ]
    if leaked:
        print(f"standard firmware contains bench commands: {', '.join(leaked)}")
    if missing:
        print(f"standard firmware is missing capabilities: {', '.join(missing)}")
    return 1 if leaked or missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
