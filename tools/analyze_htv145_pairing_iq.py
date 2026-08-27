#!/usr/bin/env python3
"""Correlate HTV145 enrollment branches in bounded CU8 IQ captures.

HTV145 uses the lower request carrier for its factory announcement and paired
requests at stages 1 and 3--5. Only the stage-2 controller-configuration
response moves to the routine response carrier. Keeping those legs separate is
essential: searching for stage 1 on the response carrier makes an accepted
assignment look rejected.
"""

from __future__ import annotations

import argparse
import binascii
from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
from typing import Any, Callable

try:
    from .demod_rainpoint_reply_iq import demodulate
except ImportError:  # Direct script execution.
    from demod_rainpoint_reply_iq import demodulate


FRAME_SYMBOLS = 38 * 8
WAKE_SYMBOLS = 320
DEFAULT_SAMPLE_RATE = 2_000_000
DEFAULT_CAPTURE_CENTER_HZ = 433_700_000
DEFAULT_REQUEST_CENTER_HZ = 433_143_000
DEFAULT_ASSIGNMENT_CENTER_HZ = 433_556_567
DEFAULT_RESPONSE_CENTER_HZ = 433_471_500


def _endpoint(value: str) -> bytes:
    try:
        endpoint = bytes.fromhex(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("endpoint must be hexadecimal") from error
    if len(endpoint) != 4:
        raise argparse.ArgumentTypeError(
            "endpoint must contain exactly four bytes"
        )
    return endpoint


@contextmanager
def _bounded_capture(
    path: Path,
    *,
    sample_rate: int,
    start_seconds: float,
    duration_seconds: float | None,
):
    """Yield a small aligned IQ window and its original timeline origin."""
    if start_seconds < 0:
        raise ValueError("start_seconds must be non-negative")
    if duration_seconds is not None and duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive")
    if start_seconds == 0 and duration_seconds is None:
        yield path, 0.0
        return

    first_sample = round(start_seconds * sample_rate)
    requested_samples = (
        round(duration_seconds * sample_rate)
        if duration_seconds is not None
        else None
    )
    with path.open("rb") as source, tempfile.NamedTemporaryFile(
        suffix=".cu8"
    ) as window:
        source.seek(first_sample * 2)
        remaining_bytes = (
            requested_samples * 2
            if requested_samples is not None
            else None
        )
        while remaining_bytes is None or remaining_bytes > 0:
            requested = (
                1024 * 1024
                if remaining_bytes is None
                else min(1024 * 1024, remaining_bytes)
            )
            chunk = source.read(requested)
            if not chunk:
                break
            window.write(chunk)
            if remaining_bytes is not None:
                remaining_bytes -= len(chunk)
        window.flush()
        if window.tell() < 2:
            raise ValueError("analysis window does not contain IQ samples")
        yield Path(window.name), first_sample / sample_rate


def _matches(
    frame_hex: str,
    *,
    endpoint_a: bytes,
    endpoint_b: bytes,
    body_prefix: bytes,
) -> bool:
    try:
        frame = bytes.fromhex(frame_hex)
    except ValueError:
        return False
    return (
        len(frame) == 38
        and frame.startswith(bytes.fromhex("79f4882f28"))
        and frame[5:9] == endpoint_a
        and frame[9:13] == endpoint_b
        and frame[13:].startswith(body_prefix)
        and (
            binascii.crc_hqx(frame[:-2], 0)
            ^ int.from_bytes(frame[-2:], "big")
        )
        in {0xC713, 0x4F03}
    )


def _factory_matches(frame_hex: str, factory_endpoint: bytes) -> bool:
    """Match the HTV145 factory family while allowing its sweep counter."""
    try:
        frame = bytes.fromhex(frame_hex)
    except ValueError:
        return False
    return (
        len(frame) == 38
        and frame.startswith(bytes.fromhex("79f4882f28"))
        and frame[5:9] == bytes.fromhex("80000000")
        and frame[9:13] == factory_endpoint
        and frame[14:18] == bytes.fromhex("808402ff")
        and (
            binascii.crc_hqx(frame[:-2], 0)
            ^ int.from_bytes(frame[-2:], "big")
        )
        in {0xC713, 0x4F03}
    )


def _events(
    result: dict[str, Any],
    predicate: Callable[[str], bool],
    *,
    origin_seconds: float,
) -> list[dict[str, Any]]:
    symbol_rate = int(result["symbol_rate_sps"])
    events = []
    for match in result["matches"]:
        frame_hex = str(match["frame_hex"])
        if int(match["phase_count"]) < 8 or not predicate(frame_hex):
            continue
        for sync_symbol in match["sync_symbols"]:
            sync_symbol = int(sync_symbol)
            events.append(
                {
                    "frame": frame_hex,
                    "phase_count": int(match["phase_count"]),
                    "start_seconds": origin_seconds
                    + (sync_symbol - WAKE_SYMBOLS) / symbol_rate,
                    "end_seconds": origin_seconds
                    + (sync_symbol + FRAME_SYMBOLS) / symbol_rate,
                }
            )
    events.sort(key=lambda item: item["start_seconds"])
    deduplicated = []
    for event in events:
        if (
            deduplicated
            and event["frame"] == deduplicated[-1]["frame"]
            and event["start_seconds"] - deduplicated[-1]["start_seconds"]
            < 0.1
        ):
            continue
        deduplicated.append(event)
    return deduplicated


def analyze(
    path: Path,
    *,
    factory_endpoint: bytes,
    paired_endpoint: bytes,
    companion_endpoint: bytes,
    controller_endpoint: bytes,
    origin_seconds: float,
    sample_rate: int,
    capture_center_hz: int,
    request_center_hz: int,
    assignment_center_hz: int,
    response_center_hz: int,
) -> dict[str, Any]:
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
    response_result = demodulate(
        path, channel_center_hz=response_center_hz, **common
    )
    requests = _events(
        request_result,
        lambda frame: _factory_matches(frame, factory_endpoint),
        origin_seconds=origin_seconds,
    )
    assignments = _events(
        assignment_result,
        lambda frame: _matches(
            frame,
            endpoint_a=paired_endpoint,
            endpoint_b=companion_endpoint,
            body_prefix=bytes.fromhex("80c0858503057000"),
        ),
        origin_seconds=origin_seconds,
    )
    paired_requests = _events(
        request_result,
        lambda frame: _matches(
            frame,
            endpoint_a=controller_endpoint,
            endpoint_b=paired_endpoint,
            body_prefix=b"",
        ),
        origin_seconds=origin_seconds,
    )
    stage_1_requests = _events(
        request_result,
        lambda frame: _matches(
            frame,
            endpoint_a=controller_endpoint,
            endpoint_b=paired_endpoint,
            body_prefix=bytes.fromhex("8101078225"),
        ),
        origin_seconds=origin_seconds,
    )
    configuration_responses = _events(
        response_result,
        lambda frame: _matches(
            frame,
            endpoint_a=controller_endpoint,
            endpoint_b=paired_endpoint,
            body_prefix=bytes.fromhex("81d00080"),
        ),
        origin_seconds=origin_seconds,
    )

    trials = []
    for request in requests:
        assignment = next(
            (
                candidate
                for candidate in assignments
                if 0
                <= candidate["start_seconds"] - request["end_seconds"]
                <= 0.2
            ),
            None,
        )
        if assignment is None:
            continue
        next_factory_start = next(
            (
                candidate["start_seconds"]
                for candidate in requests
                if candidate["start_seconds"] > request["start_seconds"]
            ),
            assignment["start_seconds"] + 15.0,
        )
        first_paired = next(
            (
                candidate
                for candidate in stage_1_requests
                if assignment["start_seconds"]
                < candidate["start_seconds"]
                < next_factory_start
            ),
            None,
        )
        assignment_frame = bytes.fromhex(assignment["frame"])
        request_frame = bytes.fromhex(request["frame"])
        trials.append(
            {
                "factory_sweep_counter": request_frame[13] & 0x7F,
                "request_frame": request["frame"],
                "request_start_seconds": round(request["start_seconds"], 6),
                "request_end_seconds": round(request["end_seconds"], 6),
                "assignment_frame": assignment["frame"],
                "assignment_selector": assignment_frame[18] & 0x7F,
                "assignment_start_seconds": round(
                    assignment["start_seconds"], 6
                ),
                "request_end_to_assignment_start_ms": round(
                    (assignment["start_seconds"] - request["end_seconds"])
                    * 1_000,
                    3,
                ),
                "stage_1_observed": first_paired is not None,
                "stage_1_start_seconds": (
                    round(first_paired["start_seconds"], 6)
                    if first_paired is not None
                    else None
                ),
            }
        )
    return {
        "path": str(path),
        "origin_seconds": origin_seconds,
        "request_count": len(requests),
        "assignment_count": len(assignments),
        "lower_paired_request_count": len(paired_requests),
        "stage_1_request_count": len(stage_1_requests),
        "configuration_response_count": len(configuration_responses),
        "decision_centers_hz": {
            "lower_request": request_center_hz,
            "assignment": assignment_center_hz,
            "configuration_response": response_center_hz,
        },
        "trials": trials,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--factory-endpoint", type=_endpoint, required=True)
    parser.add_argument("--paired-endpoint", type=_endpoint, required=True)
    parser.add_argument("--companion-endpoint", type=_endpoint, required=True)
    parser.add_argument("--controller-endpoint", type=_endpoint, required=True)
    parser.add_argument("--start-seconds", type=float, default=0.0)
    parser.add_argument("--duration-seconds", type=float)
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
        "--response-center", type=int, default=DEFAULT_RESPONSE_CENTER_HZ
    )
    args = parser.parse_args()
    with _bounded_capture(
        args.capture,
        sample_rate=args.sample_rate,
        start_seconds=args.start_seconds,
        duration_seconds=args.duration_seconds,
    ) as (analysis_path, origin_seconds):
        result = analyze(
            analysis_path,
            factory_endpoint=args.factory_endpoint,
            paired_endpoint=args.paired_endpoint,
            companion_endpoint=args.companion_endpoint,
            controller_endpoint=args.controller_endpoint,
            origin_seconds=origin_seconds,
            sample_rate=args.sample_rate,
            capture_center_hz=args.capture_center,
            request_center_hz=args.request_center,
            assignment_center_hz=args.assignment_center,
            response_center_hz=args.response_center,
        )
    result["path"] = str(args.capture)
    result["analysis_window"] = {
        "start_seconds": args.start_seconds,
        "duration_seconds": args.duration_seconds,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["trials"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
