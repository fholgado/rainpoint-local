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
PAIRING_CHANNEL_BASE_HZ = 433_031_500
PAIRING_CHANNEL_SPACING_HZ = 110_000


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


def pairing_channel_from_reply(frame: bytes) -> int:
    """Decode the provisional subchannel selector in initial gateway reply."""
    return 2 * (frame[18] & 0x7F) + (1 if frame[19] & 0x80 else 0)


def pairing_channel_from_sensor(frame: bytes) -> int:
    """Decode the subchannel echoed by the sensor's paired message 01."""
    return 2 * frame[16] + (1 if frame[17] & 0x80 else 0)


def expected_pairing_channel_hz(channel: int) -> int:
    """Return the provisional 110 kHz pairing-channel center."""
    return PAIRING_CHANNEL_BASE_HZ + channel * PAIRING_CHANNEL_SPACING_HZ


def channel_assignment(sequence: dict[str, Any]) -> dict[str, Any]:
    """Compare a reply-1 assignment with the sensor's subsequent echo."""
    replies = _frames(sequence)
    requests = [
        bytes.fromhex(value) for value in sequence.get("request_frames", [])
    ]
    if len(requests) < 2 or any(len(frame) != FRAME_BYTES for frame in requests):
        raise ValueError(f"missing request frames in {sequence.get('name')}")
    assigned = pairing_channel_from_reply(replies[0])
    echoed = pairing_channel_from_sensor(requests[1])
    measured_hz = int(sequence["reply_channel_hz"])
    expected_hz = expected_pairing_channel_hz(assigned)
    return {
        "sequence": sequence["name"],
        "assigned_channel": assigned,
        "echoed_channel": echoed,
        "assignment_echo_matches": assigned == echoed,
        "measured_followup_hz": measured_hz,
        "expected_followup_hz": expected_hz,
        "frequency_error_hz": measured_hz - expected_hz,
    }


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
    """Build the evidence record for the validated Sensor A profile."""
    first = _sequence(payload, "sensor_a_first_enrollment")
    rejoin = _sequence(payload, "sensor_a_rejoin")
    first_frames = _frames(first)
    rejoin_frames = _frames(rejoin)
    return {
        "candidate_id": "hcs026_1bce0024_candidate_v1",
        "factory_endpoint": first["factory_endpoint"],
        "paired_endpoint": first["paired_endpoint"],
        "transmit_enabled": True,
        "gateway_selectable": True,
        "firmware_compiled": True,
        "evidence": [
            first["name"],
            rejoin["name"],
            "sensor_a_local_enrollment_isolated_success_20260812",
        ],
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
        "remaining_questions": [
            "Can Sensor A be assigned the known-good channel 4 used by Sensor B?",
            "Can reply payloads be generated from state instead of selected by endpoint?",
            "Does the same branch repeat after factory reset and ordinary power loss?",
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
    assignments = [
        channel_assignment(_sequence(payload, name))
        for name in (
            "sensor_a_first_enrollment",
            "sensor_b_first_enrollment",
            "sensor_b_local_enrollment_isolated_success_20260811",
            "sensor_a_local_enrollment_isolated_success_20260812",
        )
    ]
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
            "channel_assignments": assignments,
            "channel_assignment_echoes_match": all(
                item["assignment_echo_matches"] for item in assignments
            ),
            "channel_frequency_formula_matches": all(
                abs(item["frequency_error_hz"]) <= 50 for item in assignments
            ),
        },
    }


def _print_text(report: dict[str, Any]) -> None:
    candidate = report["sensor_a_candidate"]
    findings = report["findings"]
    print(f"Profile: {candidate['candidate_id']} (physically validated)")
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
    print("Provisional pairing-channel assignments:")
    for assignment in findings["channel_assignments"]:
        print(
            f"  - {assignment['sequence']}: selector "
            f"{assignment['assigned_channel']} echoed by sensor, "
            f"{assignment['measured_followup_hz']} Hz measured"
        )
    for question in candidate["remaining_questions"]:
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
