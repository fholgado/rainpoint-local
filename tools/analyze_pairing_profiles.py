#!/usr/bin/env python3
"""Compare captured HCS026 gateway replies without enabling a transmitter."""

from __future__ import annotations

import argparse
import binascii
import json
from pathlib import Path
from typing import Any


FRAME_BYTES = 38
IDENTITY_BYTES = frozenset(range(5, 9))
TRAILER_BYTES = frozenset((36, 37))
CLOCK_BYTES = frozenset(range(21, 25))


def residual(frame: bytes) -> int:
    return binascii.crc_hqx(frame[:-2], 0) ^ int.from_bytes(frame[-2:], "big")


def _sequence(payload: dict[str, Any], name: str) -> dict[str, Any]:
    try:
        return next(item for item in payload["sequences"] if item["name"] == name)
    except StopIteration:
        raise ValueError(f"missing pairing sequence: {name}") from None


def _frames(sequence: dict[str, Any]) -> list[bytes]:
    result = [bytes.fromhex(value) for value in sequence.get("frames", [])]
    if not result or any(len(frame) != FRAME_BYTES for frame in result):
        raise ValueError(f"invalid frames in {sequence.get('name')}")
    return result


def compare_sequences(
    payload: dict[str, Any],
    left_name: str,
    right_name: str,
) -> dict[str, Any]:
    """Return byte-level differences between two aligned stock sequences."""
    left = _sequence(payload, left_name)
    right = _sequence(payload, right_name)
    left_frames = _frames(left)
    right_frames = _frames(right)
    aligned_steps = min(len(left_frames), len(right_frames))
    comparisons = []
    for index in range(aligned_steps):
        differences = [
            {
                "offset": offset,
                "left": f"{left_frames[index][offset]:02x}",
                "right": f"{right_frames[index][offset]:02x}",
            }
            for offset in range(FRAME_BYTES)
            if left_frames[index][offset] != right_frames[index][offset]
        ]
        semantic = [
            item
            for item in differences
            if item["offset"] not in IDENTITY_BYTES | TRAILER_BYTES | CLOCK_BYTES
        ]
        comparisons.append(
            {
                "step": index + 1,
                "differences": differences,
                "semantic_differences": semantic,
            }
        )
    return {
        "left": left_name,
        "right": right_name,
        "left_frame_count": len(left_frames),
        "right_frame_count": len(right_frames),
        "aligned_steps": aligned_steps,
        "steps": comparisons,
    }


def sensor_a_candidate(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a non-runnable evidence record for tomorrow's Sensor A test."""
    first = _sequence(payload, "sensor_a_first_enrollment")
    rejoin = _sequence(payload, "sensor_a_rejoin")
    first_frames = _frames(first)
    rejoin_frames = _frames(rejoin)
    return {
        "candidate_id": "research_hcs026_1bce0024_v0",
        "factory_endpoint": first["factory_endpoint"],
        "paired_endpoint": first["paired_endpoint"],
        "transmit_enabled": False,
        "gateway_selectable": False,
        "firmware_compiled": False,
        "evidence": [first["name"], rejoin["name"]],
        "first_enrollment_reply_count": len(first_frames),
        "rejoin_reply_count": len(rejoin_frames),
        "initial_channel_hz": first["initial_reply_channel_hz"],
        "followup_channel_hz": first["reply_channel_hz"],
        "rejoin_followup_channel_hz": rejoin["reply_channel_hz"],
        "channel_evidence_consistent": (
            first["initial_reply_channel_hz"] == rejoin["initial_reply_channel_hz"]
            and first["reply_channel_hz"] == rejoin["reply_channel_hz"]
        ),
        "ordinary_trailer_residuals": sorted(
            {f"0x{residual(frame):04x}" for frame in first_frames + rejoin_frames}
        ),
        "captured_frames": [frame.hex() for frame in first_frames],
        "blocking_questions": [
            "Does a first enrollment require all five replies or only the first three?",
            "Must follow-up replies switch from 433.4715 MHz to 434.021457 MHz?",
            "Will the sensor emit terminal message 03 and routine telemetry while the stock RainPoint gateway is isolated?",
        ],
    }


def analyze(payload: dict[str, Any]) -> dict[str, Any]:
    first_comparison = compare_sequences(
        payload,
        "sensor_a_first_enrollment",
        "sensor_b_first_enrollment",
    )
    semantic_offsets = sorted(
        {
            item["offset"]
            for step in first_comparison["steps"]
            for item in step["semantic_differences"]
        }
    )
    return {
        "comparison": first_comparison,
        "sensor_a_candidate": sensor_a_candidate(payload),
        "findings": {
            "semantic_difference_offsets": semantic_offsets,
            "identity_substitution_alone_is_safe": not semantic_offsets,
            "later_steps_match_after_identity_and_trailer": all(
                not step["semantic_differences"]
                for step in first_comparison["steps"][1:]
            ),
        },
    }


def _print_text(report: dict[str, Any]) -> None:
    candidate = report["sensor_a_candidate"]
    findings = report["findings"]
    print(f"Candidate: {candidate['candidate_id']} (TX disabled)")
    print(
        "Channels: "
        f"{candidate['initial_channel_hz']} Hz initial -> "
        f"{candidate['followup_channel_hz']} Hz follow-up"
    )
    print(
        "Stock reply counts: "
        f"{candidate['first_enrollment_reply_count']} first enrollment, "
        f"{candidate['rejoin_reply_count']} rejoin"
    )
    print(
        "Non-identity/clock/trailer differences from Sensor B: "
        + ", ".join(str(item) for item in findings["semantic_difference_offsets"])
    )
    print(
        "Identity substitution alone: "
        + ("safe" if findings["identity_substitution_alone_is_safe"] else "unsafe")
    )
    for question in candidate["blocking_questions"]:
        print(f"  - {question}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "fixture",
        type=Path,
        nargs="?",
        default=Path("research/fixtures/hcs026_gateway_pairing_replies.json"),
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = analyze(json.loads(args.fixture.read_text()))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_text(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
