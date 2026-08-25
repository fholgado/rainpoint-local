#!/usr/bin/env python3
"""Measure HTV405 factory requests, local assignments, and link acceptance.

The three legs of HTV405 enrollment occupy different RF centers. A generic
"strongest signal" demodulator can therefore recover the routine exchange
while silently missing the timing-critical assignment. This analyzer runs the
same offline demodulator with an explicit decision threshold for each known
leg and correlates them on one capture timeline.
"""

from __future__ import annotations

import argparse
import binascii
import json
from pathlib import Path
from typing import Any, Callable

try:
    from .demod_rainpoint_reply_iq import demodulate
except ImportError:  # Direct script execution.
    from demod_rainpoint_reply_iq import demodulate


FRAME_SYMBOLS = 38 * 8
WAKE_SYMBOLS = 320
DEFAULT_SAMPLE_RATE = 2_000_000
DEFAULT_CAPTURE_CENTER_HZ = 433_700_000
DEFAULT_REQUEST_CENTER_HZ = 433_141_803
DEFAULT_ASSIGNMENT_CENTER_HZ = 433_561_740
DEFAULT_ROUTINE_CENTER_HZ = 433_471_194


def _endpoint(value: str) -> bytes:
    try:
        endpoint = bytes.fromhex(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("endpoint must be hexadecimal") from error
    if len(endpoint) != 4:
        raise argparse.ArgumentTypeError("endpoint must contain exactly four bytes")
    return endpoint


def _frame_matches(
    frame_hex: str,
    *,
    endpoint_a: bytes,
    endpoint_b: bytes,
    body_prefix: bytes | None = None,
) -> bool:
    try:
        frame = bytes.fromhex(frame_hex)
    except ValueError:
        return False
    return (
        len(frame) == 38
        and frame.startswith(bytes.fromhex("79f4882f28"))
        and (
            binascii.crc_hqx(frame[:-2], 0)
            ^ int.from_bytes(frame[-2:], "big")
        )
        in {0xC713, 0x4F03}
        and frame[5:9] == endpoint_a
        and frame[9:13] == endpoint_b
        and (body_prefix is None or frame[13:].startswith(body_prefix))
    )


def _events(
    result: dict[str, Any],
    predicate: Callable[[str], bool],
    *,
    minimum_phase_count: int = 8,
) -> list[dict[str, Any]]:
    symbol_rate = int(result["symbol_rate_sps"])
    events: list[dict[str, Any]] = []
    for match in result["matches"]:
        frame_hex = str(match["frame_hex"])
        phase_count = int(match["phase_count"])
        if phase_count < minimum_phase_count or not predicate(frame_hex):
            continue
        for sync_symbol in match["sync_symbols"]:
            sync_symbol = int(sync_symbol)
            events.append(
                {
                    "frame": frame_hex,
                    "phase_count": phase_count,
                    "sync_symbol": sync_symbol,
                    "burst_start_seconds": (
                        sync_symbol - WAKE_SYMBOLS
                    ) / symbol_rate,
                    "frame_end_seconds": (
                        sync_symbol + FRAME_SYMBOLS
                    ) / symbol_rate,
                }
            )
    ordered = sorted(events, key=lambda item: item["burst_start_seconds"])
    deduplicated: list[dict[str, Any]] = []
    for event in ordered:
        if (
            deduplicated
            and event["frame"] == deduplicated[-1]["frame"]
            and event["burst_start_seconds"]
            - deduplicated[-1]["burst_start_seconds"] < 0.1
        ):
            continue
        deduplicated.append(event)
    return deduplicated


def analyze_pairing_capture(
    path: Path,
    *,
    factory_endpoint: bytes,
    paired_endpoint: bytes,
    companion_endpoint: bytes,
    controller_endpoint: bytes,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    capture_center_hz: int = DEFAULT_CAPTURE_CENTER_HZ,
    request_center_hz: int = DEFAULT_REQUEST_CENTER_HZ,
    assignment_center_hz: int = DEFAULT_ASSIGNMENT_CENTER_HZ,
    routine_center_hz: int = DEFAULT_ROUTINE_CENTER_HZ,
) -> dict[str, Any]:
    """Return correlated enrollment trials from one receive-only IQ file."""
    common = {
        "sample_rate": sample_rate,
        "capture_center_hz": capture_center_hz,
    }
    request_result = demodulate(
        path, channel_center_hz=request_center_hz, **common
    )
    assignment_result = demodulate(
        path, channel_center_hz=assignment_center_hz, **common
    )
    routine_result = demodulate(
        path, channel_center_hz=routine_center_hz, **common
    )

    def request_predicate(frame: str) -> bool:
        return _frame_matches(
            frame,
            endpoint_a=bytes.fromhex("80000000"),
            endpoint_b=factory_endpoint,
            body_prefix=bytes.fromhex("00808402ff"),
        )

    def assignment_predicate(frame: str) -> bool:
        return _frame_matches(
            frame,
            endpoint_a=paired_endpoint,
            endpoint_b=companion_endpoint,
            body_prefix=bytes.fromhex("80c0858503027000"),
        )

    def paired_request_predicate(frame: str) -> bool:
        return _frame_matches(
            frame,
            endpoint_a=controller_endpoint,
            endpoint_b=paired_endpoint,
        )
    requests = _events(request_result, request_predicate)
    assignments = _events(assignment_result, assignment_predicate)
    paired_requests = _events(routine_result, paired_request_predicate)

    trials: list[dict[str, Any]] = []
    unused_assignments = assignments.copy()
    for index, request in enumerate(requests):
        assignment = next(
            (
                candidate
                for candidate in unused_assignments
                if 0 <= candidate["burst_start_seconds"]
                - request["frame_end_seconds"] <= 0.2
            ),
            None,
        )
        if assignment is None:
            continue
        unused_assignments.remove(assignment)
        next_request_start = (
            requests[index + 1]["burst_start_seconds"]
            if index + 1 < len(requests)
            else assignment["burst_start_seconds"] + 15.0
        )
        first_paired_request = next(
            (
                candidate
                for candidate in paired_requests
                if assignment["burst_start_seconds"]
                < candidate["burst_start_seconds"]
                < next_request_start
            ),
            None,
        )
        request_frame = bytes.fromhex(request["frame"])
        trials.append(
            {
                "factory_sweep_counter": request_frame[13] & 0x7F,
                "request_frame": request["frame"],
                "request_start_seconds": round(
                    request["burst_start_seconds"], 6
                ),
                "request_end_seconds": round(
                    request["frame_end_seconds"], 6
                ),
                "request_phase_count": request["phase_count"],
                "assignment_frame": assignment["frame"],
                "assignment_start_seconds": round(
                    assignment["burst_start_seconds"], 6
                ),
                "assignment_phase_count": assignment["phase_count"],
                "request_end_to_assignment_start_ms": round(
                    (
                        assignment["burst_start_seconds"]
                        - request["frame_end_seconds"]
                    )
                    * 1_000,
                    3,
                ),
                "paired_link_observed_before_next_factory_request": (
                    first_paired_request is not None
                ),
                "first_paired_request_seconds": (
                    round(first_paired_request["burst_start_seconds"], 6)
                    if first_paired_request is not None
                    else None
                ),
            }
        )

    return {
        "path": str(path),
        "sample_rate_sps": sample_rate,
        "capture_center_hz": capture_center_hz,
        "decision_centers_hz": {
            "factory_request": request_center_hz,
            "local_assignment": assignment_center_hz,
            "paired_routine": routine_center_hz,
        },
        "factory_request_count": len(requests),
        "assignment_count": len(assignments),
        "paired_request_count": len(paired_requests),
        "trials": trials,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--factory-endpoint", type=_endpoint, required=True)
    parser.add_argument("--paired-endpoint", type=_endpoint, required=True)
    parser.add_argument("--companion-endpoint", type=_endpoint, required=True)
    parser.add_argument("--controller-endpoint", type=_endpoint, required=True)
    parser.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE)
    parser.add_argument(
        "--capture-center", type=int, default=DEFAULT_CAPTURE_CENTER_HZ
    )
    parser.add_argument(
        "--request-center", type=int, default=DEFAULT_REQUEST_CENTER_HZ
    )
    parser.add_argument(
        "--assignment-center", type=int, default=DEFAULT_ASSIGNMENT_CENTER_HZ
    )
    parser.add_argument(
        "--routine-center", type=int, default=DEFAULT_ROUTINE_CENTER_HZ
    )
    args = parser.parse_args()
    result = analyze_pairing_capture(
        args.capture,
        factory_endpoint=args.factory_endpoint,
        paired_endpoint=args.paired_endpoint,
        companion_endpoint=args.companion_endpoint,
        controller_endpoint=args.controller_endpoint,
        sample_rate=args.sample_rate,
        capture_center_hz=args.capture_center,
        request_center_hz=args.request_center,
        assignment_center_hz=args.assignment_center,
        routine_center_hz=args.routine_center,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["trials"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
