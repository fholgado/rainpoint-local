#!/usr/bin/env python3
"""Correlate HTV145 enrollment branches in bounded CU8 IQ captures.

HTV145 alternates its factory sweep across lower and upper request carriers.
Paired requests at stages 1 and 3--5 return to the lower carrier, while gateway
continuations and the stage-2 controller-configuration response move to the
subchannel selected by the accepted assignment. Keeping those legs separate is
essential: forcing every accepted branch onto one carrier makes a successful
enrollment look rejected.
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
    from .demod_rainpoint_reply_iq import demodulate_many
except ImportError:  # Direct script execution.
    from demod_rainpoint_reply_iq import demodulate_many


FRAME_SYMBOLS = 38 * 8
WAKE_SYMBOLS = 320
DEFAULT_SAMPLE_RATE = 2_000_000
DEFAULT_CAPTURE_CENTER_HZ = 433_700_000
DEFAULT_REQUEST_CENTER_HZ = 433_143_000
DEFAULT_UPPER_SWEEP_CENTER_HZ = 434_306_001
DEFAULT_ASSIGNMENT_CENTER_HZ = 433_556_567
DEFAULT_RESPONSE_CENTER_HZ = 433_471_500
PAIRING_CHANNEL_BASE_HZ = 433_031_500
PAIRING_CHANNEL_SPACING_HZ = 110_000
RESPONSE_CENTER_TOLERANCE_HZ = 10_000


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
        and frame[14] & 0x7F == 0
        and frame[15:18] == bytes.fromhex("8402ff")
        and (
            binascii.crc_hqx(frame[:-2], 0)
            ^ int.from_bytes(frame[-2:], "big")
        )
        in {0xC713, 0x4F03}
    )


def _assignment_matches(
    frame_hex: str,
    *,
    paired_endpoint: bytes,
    companion_endpoint: bytes,
    controller_endpoint: bytes,
) -> bool:
    """Match either complete stock HTV145 assignment branch.

    Counter-0 selector-5 enrollment addresses the companion endpoint. The
    accepted counter-2 selector-6 branch addresses the controller route
    directly. Requiring the counter, selector, and endpoint from only the
    first capture made the second accepted exchange invisible.
    """
    try:
        frame = bytes.fromhex(frame_hex)
    except ValueError:
        return False
    return (
        len(frame) == 38
        and frame.startswith(bytes.fromhex("79f4882f28"))
        and frame[5:9] == paired_endpoint
        and frame[9:13] in {companion_endpoint, controller_endpoint}
        and frame[13] & 0x80
        and frame[14] & 0x7F == 0x40
        and frame[15:17] == bytes.fromhex("8585")
        and frame[18] & 0x7F in {0x05, 0x06}
        and frame[19] & 0x70 == 0x70
        and frame[20] == 0x00
        and (
            binascii.crc_hqx(frame[:-2], 0)
            ^ int.from_bytes(frame[-2:], "big")
        )
        in {0xC713, 0x4F03}
    )


def _stage_1_matches(
    frame_hex: str,
    *,
    controller_endpoint: bytes,
    paired_endpoint: bytes,
) -> bool:
    try:
        frame = bytes.fromhex(frame_hex)
    except ValueError:
        return False
    body = frame[13:36]
    expected_tail = bytes.fromhex(
        "80804f800000004080005680000000000000"
    )
    return (
        len(frame) == 38
        and frame.startswith(bytes.fromhex("79f4882f28"))
        and frame[5:9] == controller_endpoint
        and frame[9:13] == paired_endpoint
        and body[0] & 0x80
        and body[1] & 0x7F == 0x01
        and body[2] == 0x07
        and body[3] & 0x7F in {0x02, 0x06}
        and body[4] & 0x7F == 0x25
        and body[5:] == expected_tail
        and (
            binascii.crc_hqx(frame[:-2], 0)
            ^ int.from_bytes(frame[-2:], "big")
        )
        in {0xC713, 0x4F03}
    )


def _assigned_response_channel(
    frame_hex: str,
    *,
    controller_endpoint: bytes,
) -> tuple[int, int] | None:
    """Decode the selector-6 continuation subchannel from an assignment."""
    try:
        frame = bytes.fromhex(frame_hex)
    except ValueError:
        return None
    if (
        len(frame) != 38
        or frame[9:13] != controller_endpoint
        or frame[18] & 0x7F != 0x06
    ):
        return None
    channel = 2 * (frame[18] & 0x7F) + bool(frame[19] & 0x80)
    return (
        channel,
        PAIRING_CHANNEL_BASE_HZ + channel * PAIRING_CHANNEL_SPACING_HZ,
    )


def _configuration_response_matches(
    frame_hex: str,
    *,
    controller_endpoint: bytes,
    paired_endpoint: bytes,
) -> bool:
    try:
        frame = bytes.fromhex(frame_hex)
    except ValueError:
        return False
    body = frame[13:36]
    return (
        len(frame) == 38
        and frame.startswith(bytes.fromhex("79f4882f28"))
        and frame[5:9] == controller_endpoint
        and frame[9:13] == paired_endpoint
        and body[0] & 0x7F == 0x01
        and body[1] & 0x7F == 0x50
        and body[2:] == bytes.fromhex("0080" + "00" * 19)
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
                    "center_hz": int(result["channel_center_hz"]),
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


def _merged_events(groups: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Merge carrier-specific events without duplicating nearby decodes."""
    ordered = sorted(
        (event for group in groups for event in group),
        key=lambda item: item["start_seconds"],
    )
    merged = []
    for event in ordered:
        if any(
            candidate["frame"] == event["frame"]
            and abs(candidate["start_seconds"] - event["start_seconds"])
            < 0.1
            for candidate in merged[-3:]
        ):
            continue
        merged.append(event)
    return merged


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
    upper_sweep_center_hz: int = DEFAULT_UPPER_SWEEP_CENTER_HZ,
) -> dict[str, Any]:
    common = {
        "sample_rate": sample_rate,
        "capture_center_hz": capture_center_hz,
    }
    channels = demodulate_many(
        path,
        channel_centers_hz=(
            request_center_hz,
            upper_sweep_center_hz,
            assignment_center_hz,
            response_center_hz,
        ),
        **common,
    )
    request_result = channels[request_center_hz]
    upper_sweep_result = channels[upper_sweep_center_hz]
    assignment_result = channels[assignment_center_hz]
    response_results = {response_center_hz: channels[response_center_hz]}
    requests = _merged_events(
        [
            _events(
                result,
                lambda frame: _factory_matches(frame, factory_endpoint),
                origin_seconds=origin_seconds,
            )
            for result in (request_result, upper_sweep_result)
        ]
    )
    assignments = _events(
        assignment_result,
        lambda frame: _assignment_matches(
            frame,
            paired_endpoint=paired_endpoint,
            companion_endpoint=companion_endpoint,
            controller_endpoint=controller_endpoint,
        ),
        origin_seconds=origin_seconds,
    )
    assigned_channels = [
        assigned
        for assignment in assignments
        if (
            assigned := _assigned_response_channel(
                assignment["frame"],
                controller_endpoint=controller_endpoint,
            )
        )
        is not None
    ]
    additional_centers = sorted(
        {
            center
            for _, center in assigned_channels
            if all(
                abs(center - existing) > RESPONSE_CENTER_TOLERANCE_HZ
                for existing in response_results
            )
        }
    )
    if additional_centers:
        response_results.update(
            demodulate_many(
                path,
                channel_centers_hz=additional_centers,
                **common,
            )
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
        lambda frame: _stage_1_matches(
            frame,
            controller_endpoint=controller_endpoint,
            paired_endpoint=paired_endpoint,
        ),
        origin_seconds=origin_seconds,
    )
    paired_responses = _merged_events(
        [
            _events(
                result,
                lambda frame: _matches(
                    frame,
                    endpoint_a=paired_endpoint,
                    endpoint_b=controller_endpoint,
                    body_prefix=b"",
                ),
                origin_seconds=origin_seconds,
            )
            for result in response_results.values()
        ]
    )
    configuration_responses = _merged_events(
        [
            _events(
                result,
                lambda frame: _configuration_response_matches(
                    frame,
                    controller_endpoint=controller_endpoint,
                    paired_endpoint=paired_endpoint,
                ),
                origin_seconds=origin_seconds,
            )
            for result in response_results.values()
        ]
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
        assigned_response = _assigned_response_channel(
            assignment["frame"],
            controller_endpoint=controller_endpoint,
        )
        trials.append(
            {
                "factory_sweep_counter": request_frame[13] & 0x7F,
                "request_frame": request["frame"],
                "request_start_seconds": round(request["start_seconds"], 6),
                "request_end_seconds": round(request["end_seconds"], 6),
                "assignment_frame": assignment["frame"],
                "assignment_selector": assignment_frame[18] & 0x7F,
                "assignment_counter": assignment_frame[13] & 0x7F,
                "assignment_destination": assignment_frame[9:13].hex(),
                "assignment_to_controller_route": (
                    assignment_frame[9:13] == controller_endpoint
                ),
                "assigned_response_channel": (
                    assigned_response[0]
                    if assigned_response is not None
                    else None
                ),
                "assigned_response_center_hz": (
                    assigned_response[1]
                    if assigned_response is not None
                    else response_center_hz
                ),
                "counter_echoed": (
                    assignment_frame[13] & 0x7F
                    == request_frame[13] & 0x7F
                ),
                "assignment_start_seconds": round(
                    assignment["start_seconds"], 6
                ),
                "request_end_to_assignment_start_ms": round(
                    (assignment["start_seconds"] - request["end_seconds"])
                    * 1_000,
                    3,
                ),
                "stage_1_observed": first_paired is not None,
                "stage_0_verdict": (
                    "accepted"
                    if first_paired is not None
                    else "rejected_assignment_without_stage_1"
                ),
                "stage_1_start_seconds": (
                    round(first_paired["start_seconds"], 6)
                    if first_paired is not None
                    else None
                ),
            }
        )
    stage_0_failures = [
        trial
        for trial in trials
        if trial["stage_0_verdict"] != "accepted"
    ]
    stage_0_verdict = (
        "no_assignment_trial"
        if not trials
        else "rejected_assignment_without_stage_1"
        if stage_0_failures
        else "accepted"
    )
    return {
        "path": str(path),
        "origin_seconds": origin_seconds,
        "request_count": len(requests),
        "assignment_count": len(assignments),
        "lower_paired_request_count": len(paired_requests),
        "stage_1_request_count": len(stage_1_requests),
        "paired_response_count": len(paired_responses),
        "configuration_response_count": len(configuration_responses),
        "stage_0_verdict": stage_0_verdict,
        "stage_0_failure_count": len(stage_0_failures),
        "factory_requests": requests,
        "assignments": assignments,
        "paired_requests": paired_requests,
        "stage_1_requests": stage_1_requests,
        "paired_responses": paired_responses,
        "configuration_responses": configuration_responses,
        "assigned_response_centers_hz": sorted(
            {center for _, center in assigned_channels}
        ),
        "decision_centers_hz": {
            "lower_request": request_center_hz,
            "upper_sweep": upper_sweep_center_hz,
            "assignment": assignment_center_hz,
            "configuration_response": sorted(response_results),
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
        "--upper-sweep-center",
        type=int,
        default=DEFAULT_UPPER_SWEEP_CENTER_HZ,
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
            upper_sweep_center_hz=args.upper_sweep_center,
        )
    result["path"] = str(args.capture)
    result["analysis_window"] = {
        "start_seconds": args.start_seconds,
        "duration_seconds": args.duration_seconds,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["stage_0_verdict"] == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
