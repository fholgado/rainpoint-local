#!/usr/bin/env python3
"""Verify that production firmware excludes local RF transmit bench commands."""

from __future__ import annotations

import sys
from pathlib import Path


BENCH_COMMANDS = (
    b"pairing_arm_b",
    b"pairing_probe_b",
    b"pairing_offset_hz",
    b"pairing_power_dbm",
    b"pairing_clock_local",
    b"pairing_invert",
)

CANDIDATE_MARKERS = (
    b"routine_sensor_ack_tx",
    b"authorized_until_reboot",
)

OTA_CANDIDATE_MARKERS = (
    b"firmware_update_start",
    b"firmware_update_trial",
    b"verified_sha256",
)


def main() -> int:
    if len(sys.argv) not in (3, 4, 5):
        print(
            "usage: check_firmware_boundaries.py "
            "PRODUCTION_BIN BENCH_BIN [ROUTINE_ACK_CANDIDATE_BIN] "
            "[OTA_CANDIDATE_BIN]"
        )
        return 2
    production = Path(sys.argv[1]).read_bytes()
    bench = Path(sys.argv[2]).read_bytes()
    leaked = [
        value.decode()
        for value in (*BENCH_COMMANDS, *CANDIDATE_MARKERS, *OTA_CANDIDATE_MARKERS)
        if value in production
    ]
    missing = [value.decode() for value in BENCH_COMMANDS if value not in bench]
    if len(sys.argv) >= 4:
        candidate = Path(sys.argv[3]).read_bytes()
        missing.extend(
            value.decode()
            for value in CANDIDATE_MARKERS
            if value not in candidate
        )
    if len(sys.argv) == 5:
        ota_candidate = Path(sys.argv[4]).read_bytes()
        missing.extend(
            value.decode()
            for value in OTA_CANDIDATE_MARKERS
            if value not in ota_candidate
        )
    if leaked:
        print(f"production firmware contains bench commands: {', '.join(leaked)}")
    if missing:
        print(f"research firmware is missing bench commands: {', '.join(missing)}")
    return 1 if leaked or missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
