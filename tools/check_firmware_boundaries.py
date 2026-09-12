#!/usr/bin/env python3
"""Verify a unified radio-node image has the intended command boundary."""

from __future__ import annotations

import sys
from pathlib import Path


FORBIDDEN_BENCH_COMMANDS = (
    b"hcs026_15a98024_v1", b"hcs026_1bce0024_candidate_v1",
    b"htv145_dry_open_probe", b"htv145_dry_close_probe",
    b"htv145_post_frame_tail_candidate",
    b"htv145_profile_calibration",
    b"htv145_fifo_step4_calibration",
    b"htv145_receive_edge_calibration",
    b"htv145_receive_edge_observation",
    b"pairing_arm_b",
    b"pairing_probe_b",
    b"pairing_offset_hz",
    b"pairing_power_dbm",
    b"pairing_clock_local",
    b"pairing_invert",
)

REQUIRED_CAPABILITIES = (
    b"configurable_rf_controller_identity",
    b"routine_sensor_ack_tx",
    b"valve_pairing_tx_candidate",
    b"htv405_auto_identity_pairing",
    b"firmware_update_start",
    b"firmware_update_trial",
    b"firmware_signed_ota",
    b"publisher_signature_invalid",
    b"verified_publisher_and_sha256",
)

FORBIDDEN_VALVE_CONTROL_COMMANDS = (
    b"valve_open",
    b"valve_close",
    b"valve_start",
    b"watering_start",
)

VALVE_CONTROL_COMMANDS = (
    b"valve_control_open",
    b"valve_control_close",
    b"valve_control_tx_candidate",
    b"valve_control_cancel_wait",
    b"htv405_bounded_sync_wait",
)

HTV145_PAIRING_CAPABILITIES = (b"htv145_pairing_tx_candidate",)
HTV145_CONTROL_COMMANDS = (
    b"htv145_control_open", b"htv145_control_close",
    b"htv145_control_revoke", b"htv145_report_ack_tx",
)


def main() -> int:
    arguments = sys.argv[1:]
    if len(arguments) != 1:
        print("usage: check_firmware_boundaries.py FIRMWARE_BIN")
        return 2
    firmware = Path(arguments[0]).read_bytes()
    leaked = [value.decode() for value in FORBIDDEN_BENCH_COMMANDS if value in firmware]
    leaked.extend(
        value.decode()
        for value in FORBIDDEN_VALVE_CONTROL_COMMANDS
        if value in firmware
    )
    missing = [
        value.decode() for value in (
            REQUIRED_CAPABILITIES + VALVE_CONTROL_COMMANDS
            + HTV145_PAIRING_CAPABILITIES + HTV145_CONTROL_COMMANDS
        ) if value not in firmware
    ]
    if leaked:
        print(f"firmware contains forbidden commands: {', '.join(leaked)}")
    if missing:
        print(f"firmware is missing capabilities: {', '.join(missing)}")
    return 1 if leaked or missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
