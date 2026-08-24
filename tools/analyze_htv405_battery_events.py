#!/usr/bin/env python3
"""Compare HTV405 RF fields across a known battery-change boundary.

Input is the JSON-lines event export returned by rainpointd's event API. The
tool deliberately reports byte evidence only; it does not promote a field to
battery state without an independently observed full/low transition.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any


FRAME_BYTES = 38


def endpoint(value: str) -> bytes:
    try:
        result = bytes.fromhex(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("endpoint must be hexadecimal") from error
    if len(result) != 4:
        raise argparse.ArgumentTypeError("endpoint must contain exactly four bytes")
    return result


def event_frame(event: dict[str, Any]) -> bytes | None:
    raw = event.get("raw") or (event.get("state") or {}).get("raw")
    if not isinstance(raw, str) or len(raw) != FRAME_BYTES * 2:
        return None
    try:
        return bytes.fromhex(raw)
    except ValueError:
        return None


def family(frame: bytes, controller: bytes, paired: bytes, factory: bytes) -> str:
    if frame[5:9] == bytes.fromhex("80000000") and frame[9:13] == factory:
        return "factory_announcement"
    if frame[5:9] != controller or frame[9:13] != paired:
        return "other_route"
    if frame[15] == 0x07 and frame[16] == 0x82:
        selector = frame[17] & 0x7F
        if selector in {0x05, 0x07}:
            return f"paired_link_selector_{selector:02x}"
        if selector in {0x00, 0x01, 0x02}:
            return "paired_diagnostic"
    if frame[15] in {0x01, 0x81} and frame[16] in {0x02, 0x82}:
        return "paired_startup"
    if frame[15] == 0x80 and frame[16] in {0x99, 0x9A}:
        return "paired_startup_tail"
    if frame[15] == 0x86:
        return "gateway_command_response"
    return "other_paired"


def normalized(frame: bytes) -> bytes:
    result = bytearray(frame)
    # Sequence, repeat, and CRC vary independently of semantic status.
    result[13] = 0
    result[14] &= 0x7F
    result[-2:] = b"\x00\x00"
    return bytes(result)


def value_sets(frames: list[bytes]) -> dict[int, list[int]]:
    result: dict[int, list[int]] = {}
    for index in range(13, FRAME_BYTES - 2):
        if index == 13:
            continue
        values = sorted({frame[index] for frame in frames})
        result[index] = values
    return result


def summarize_group(frames: list[bytes]) -> dict[str, Any]:
    signatures = Counter(normalized(frame).hex() for frame in frames)
    return {
        "count": len(frames),
        "unique_normalized_signatures": len(signatures),
        "top_normalized_bodies": [
            {"count": count, "body": signature[26:-4]}
            for signature, count in signatures.most_common(8)
        ],
        "byte_values": {
            str(index): [f"0x{value:02x}" for value in values]
            for index, values in value_sets(frames).items()
        },
    }


def empty_sides() -> dict[str, list[bytes]]:
    return {"before": [], "after": []}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("events", type=Path)
    parser.add_argument("--boundary-event", type=int, required=True)
    parser.add_argument("--min-event", type=int)
    parser.add_argument("--max-event", type=int)
    parser.add_argument("--controller", type=endpoint, required=True)
    parser.add_argument("--paired", type=endpoint, required=True)
    parser.add_argument("--factory", type=endpoint, required=True)
    args = parser.parse_args()

    controller = args.controller
    paired = args.paired
    factory_endpoint = args.factory
    grouped: dict[str, dict[str, list[bytes]]] = defaultdict(empty_sides)
    first_event: int | None = None
    last_event: int | None = None

    for line in args.events.read_text().splitlines():
        event = json.loads(line)
        event_id = int(event["event_id"])
        if args.min_event is not None and event_id < args.min_event:
            continue
        if args.max_event is not None and event_id > args.max_event:
            continue
        frame = event_frame(event)
        if frame is None:
            continue
        frame_family = family(frame, controller, paired, factory_endpoint)
        if frame_family in {"other_route", "other_paired"}:
            continue
        side = "after" if event_id >= args.boundary_event else "before"
        grouped[frame_family][side].append(frame)
        first_event = event_id if first_event is None else min(first_event, event_id)
        last_event = event_id if last_event is None else max(last_event, event_id)

    families: dict[str, Any] = {}
    for name, sides in sorted(grouped.items()):
        before_values = value_sets(sides["before"])
        after_values = value_sets(sides["after"])
        changed_positions = {
            str(index): {
                "before": [f"0x{value:02x}" for value in before_values[index]],
                "after": [f"0x{value:02x}" for value in after_values[index]],
            }
            for index in sorted(set(before_values) & set(after_values))
            if before_values[index] != after_values[index]
        }
        families[name] = {
            "before": summarize_group(sides["before"]),
            "after": summarize_group(sides["after"]),
            "changed_byte_value_sets": changed_positions,
        }

    print(
        json.dumps(
            {
                "boundary_event": args.boundary_event,
                "event_range": [first_event, last_event],
                "families": families,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
