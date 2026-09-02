#!/usr/bin/env python3
"""Validate an accepted stock HTV145 stage-zero exchange for exact replay."""

from __future__ import annotations

import argparse
import binascii
import json
from pathlib import Path
from typing import Any


FRAME_BYTES = 38
SYNC = bytes.fromhex("79f4882f28")
FACTORY_DESTINATION = bytes.fromhex("80000000")
TRAILER_RESIDUES = frozenset((0xC713, 0x4F03))


def _frame(value: Any, field: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a hexadecimal string")
    try:
        frame = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"{field} is not valid hexadecimal") from exc
    if len(frame) != FRAME_BYTES or not frame.startswith(SYNC):
        raise ValueError(f"{field} is not a normalized RainPoint frame")
    return frame


def _trailer_residual(frame: bytes) -> int:
    return binascii.crc_hqx(frame[:-2], 0) ^ int.from_bytes(frame[-2:], "big")


def _exchange(payload: dict[str, Any], stage: int) -> dict[str, Any]:
    matches = [
        item
        for item in payload.get("exchanges", [])
        if item.get("stage") == stage
    ]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one stock stage-{stage} exchange")
    return matches[0]


def _cpp_initializer(frame: bytes) -> str:
    return "{{" + ", ".join(f"0x{value:02x}" for value in frame) + "}}"


def prepare_exact_replay(
    payload: dict[str, Any],
    *,
    source_path: Path | None = None,
) -> dict[str, Any]:
    """Return a strict manifest only for an accepted fresh counter-0 exchange."""
    if payload.get("model") != "HTV145FRF":
        raise ValueError("source fixture is not HTV145FRF")
    lifecycle = payload.get("lifecycle", {})
    if "successful" not in str(lifecycle.get("visible_result", "")).lower():
        raise ValueError("source fixture lacks a successful physical result")
    if "reset" not in lifecycle or "batteries" not in lifecycle:
        raise ValueError("source fixture lacks a controlled reset lifecycle")

    association = payload.get("association", {})
    factory_endpoint = bytes.fromhex(str(association.get("factory_endpoint", "")))
    paired_endpoint = bytes.fromhex(str(association.get("paired_endpoint", "")))
    controller_endpoint = bytes.fromhex(
        str(association.get("controller_endpoint", ""))
    )
    companion_endpoint = bytes.fromhex(
        str(association.get("companion_endpoint", ""))
    )
    if any(
        len(endpoint) != 4
        for endpoint in (
            factory_endpoint,
            paired_endpoint,
            controller_endpoint,
            companion_endpoint,
        )
    ):
        raise ValueError("source fixture has an invalid association endpoint")
    if paired_endpoint != bytes((factory_endpoint[0] | 0x80,)) + factory_endpoint[1:]:
        raise ValueError("paired endpoint is not derived from the factory endpoint")

    stage_0 = _exchange(payload, 0)
    stage_1 = _exchange(payload, 1)
    request = _frame(stage_0.get("request_frame"), "stage-0 request")
    assignment = _frame(stage_0.get("reply_frame"), "stage-0 assignment")
    acceptance = _frame(stage_1.get("request_frame"), "stage-1 request")

    request_counter = request[13] & 0x7F
    assignment_counter = assignment[13] & 0x7F
    selector = assignment[18] & 0x7F
    assigned_response_channel = 2 * selector + (1 if assignment[19] & 0x80 else 0)
    if request_counter != 0 or assignment_counter != request_counter:
        raise ValueError("exact replay source must be an echoed counter-0 assignment")
    if request[5:9] != FACTORY_DESTINATION or request[9:13] != factory_endpoint:
        raise ValueError("stage-0 request route does not match the association")
    if assignment[5:9] != paired_endpoint or assignment[9:13] != controller_endpoint:
        raise ValueError("stage-0 assignment route does not match the association")
    if acceptance[5:9] != controller_endpoint or acceptance[9:13] != paired_endpoint:
        raise ValueError("stage-1 acceptance route does not match the association")
    if selector != int(association.get("assignment_selector", -1)):
        raise ValueError("assignment selector conflicts with fixture metadata")
    if assigned_response_channel != int(
        association.get("assigned_response_channel", -1)
    ):
        raise ValueError("assigned response channel conflicts with fixture metadata")

    request_residual = _trailer_residual(request)
    assignment_residual = _trailer_residual(assignment)
    acceptance_residual = _trailer_residual(acceptance)
    if any(
        residual not in TRAILER_RESIDUES
        for residual in (request_residual, assignment_residual, acceptance_residual)
    ):
        raise ValueError("source exchange contains an unsupported trailer residual")

    return {
        "model": "HTV145FRF",
        "source_fixture": source_path.name if source_path is not None else None,
        "source_capture_sha256": payload.get("capture_sha256"),
        "lifecycle": "documented_factory_reset_stock_accepted",
        "factory_endpoint": factory_endpoint.hex(),
        "paired_endpoint": paired_endpoint.hex(),
        "controller_endpoint": controller_endpoint.hex(),
        "companion_endpoint": companion_endpoint.hex(),
        "factory_sweep_counter": request_counter,
        "assignment_selector": selector,
        "assigned_response_channel": assigned_response_channel,
        "request_end_to_assignment_start_us": round(
            float(stage_0["request_end_to_reply_start_ms"]) * 1_000
        ),
        "assignment_center_hz": int(stage_0["reply_center_hz"]),
        "assigned_response_center_hz": int(
            association["assigned_response_center_hz"]
        ),
        "exact_request_frame": request.hex(),
        "exact_assignment_frame": assignment.hex(),
        "acceptance_frame": acceptance.hex(),
        "request_trailer_residual": f"{request_residual:04x}",
        "assignment_trailer_residual": f"{assignment_residual:04x}",
        "acceptance_trailer_residual": f"{acceptance_residual:04x}",
        "cpp_initializer": _cpp_initializer(assignment),
        "success_signal": "addressed stage-1 request matching acceptance_frame",
        "replay_rule": "transmit these 38 assignment bytes unchanged exactly once",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.fixture.read_text())
    print(
        json.dumps(
            prepare_exact_replay(payload, source_path=args.fixture),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
