#!/usr/bin/env python3
"""Classify passive valve enrollment and compare structured multi-zone trials."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Iterable


SYNC = bytes.fromhex("79f4882f28")
FRAME_BYTES = 38
BODY_START = 13
BODY_END = FRAME_BYTES - 2


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _frame(event: dict[str, Any]) -> bytes | None:
    raw = event.get("raw") or event.get("state", {}).get("raw")
    if not isinstance(raw, str):
        return None
    try:
        frame = bytes.fromhex(raw)
    except ValueError:
        return None
    if len(frame) != FRAME_BYTES or not frame.startswith(SYNC):
        return None
    return frame


def _normalized(
    events: Iterable[dict[str, Any]],
) -> list[tuple[dict[str, Any], datetime, bytes]]:
    result = []
    for event in events:
        frame = _frame(event)
        observed_at = _timestamp(event.get("observed_at"))
        if frame is not None and observed_at is not None:
            result.append((event, observed_at, frame))
    result.sort(key=lambda row: (row[1], int(row[0].get("event_id", 0))))
    collapsed = []
    previous: bytes | None = None
    for row in result:
        if row[2] == previous:
            continue
        collapsed.append(row)
        previous = row[2]
    return collapsed


def classify_pairing_exchange(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe exchange phases without assigning unproven protocol semantics."""
    frames = _normalized(events)
    links: dict[tuple[bytes, bytes], list[tuple[dict[str, Any], datetime, bytes]]] = (
        defaultdict(list)
    )
    for row in frames:
        left, right = sorted((row[2][5:9], row[2][9:13]))
        links[(left, right)].append(row)

    exchanges = []
    for (left, right), rows in links.items():
        directions: Counter[str] = Counter()
        messages: dict[str, Counter[str]] = defaultdict(Counter)
        for _, _, frame in rows:
            direction = f"{frame[5:9].hex()}->{frame[9:13].hex()}"
            directions[direction] += 1
            messages[direction][f"0x{frame[13] & 0x7f:02x}"] += 1

        first_direction = (rows[0][2][5:9], rows[0][2][9:13])
        reply_index = next(
            (
                index
                for index, (_, _, frame) in enumerate(rows[1:], start=1)
                if (frame[5:9], frame[9:13])
                == (first_direction[1], first_direction[0])
            ),
            None,
        )
        confirmation_index = None
        if reply_index is not None:
            confirmation_index = next(
                (
                    index
                    for index, (_, _, frame) in enumerate(
                        rows[reply_index + 1 :], start=reply_index + 1
                    )
                    if (frame[5:9], frame[9:13]) == first_direction
                ),
                None,
            )

        def candidate(index: int | None, phase: str) -> dict[str, Any] | None:
            if index is None:
                return None
            event, observed_at, frame = rows[index]
            return {
                "phase": phase,
                "event_id": event.get("event_id"),
                "observed_at": observed_at.isoformat(),
                "route": f"{frame[5:9].hex()}->{frame[9:13].hex()}",
                "message": f"0x{frame[13] & 0x7f:02x}",
                "raw": frame.hex(),
            }

        phase_candidates = [
            candidate(0, "initial_announcement_candidate"),
            candidate(reply_index, "first_reverse_reply_candidate"),
            candidate(confirmation_index, "first_post_reply_confirmation_candidate"),
        ]
        phase_candidates = [item for item in phase_candidates if item is not None]
        exchanges.append(
            {
                "endpoints": [left.hex(), right.hex()],
                "frame_count": len(rows),
                "bidirectional": len(directions) > 1,
                "direction_counts": dict(directions),
                "message_counts_by_direction": {
                    direction: dict(counts)
                    for direction, counts in sorted(messages.items())
                },
                "phase_candidates": phase_candidates,
                "post_exchange_frame_count": max(
                    0,
                    len(rows)
                    - ((confirmation_index + 1) if confirmation_index is not None else 1),
                ),
            }
        )
    exchanges.sort(key=lambda item: (-item["frame_count"], item["endpoints"]))
    return {
        "collapsed_frame_count": len(frames),
        "exchange_count": len(exchanges),
        "bidirectional_exchange_count": sum(
            1 for item in exchanges if item["bidirectional"]
        ),
        "exchanges": exchanges,
        "interpretation_warning": (
            "Phase names are structural candidates, not decoded protocol semantics."
        ),
    }


def _categorical_candidates(
    rows: list[tuple[bytes, dict[str, Any]]], field: str
) -> list[dict[str, Any]]:
    labels = {str(marker[field]) for _, marker in rows if marker.get(field) is not None}
    if len(labels) < 2:
        return []
    candidates = []
    for index in range(BODY_START, BODY_END):
        groups: dict[str, Counter[int]] = defaultdict(Counter)
        for frame, marker in rows:
            if marker.get(field) is not None:
                groups[str(marker[field])][frame[index]] += 1
        if set(groups) != labels:
            continue
        dominant = {label: counts.most_common(1)[0] for label, counts in groups.items()}
        total = sum(sum(counts.values()) for counts in groups.values())
        correct = sum(count for _, count in dominant.values())
        values = {value for value, _ in dominant.values()}
        if len(values) < 2:
            continue
        accuracy = correct / total
        if accuracy < 0.75:
            continue
        candidates.append(
            {
                "byte": index,
                "accuracy": round(accuracy, 6),
                "dominant_values": {
                    label: f"0x{value:02x}"
                    for label, (value, _) in sorted(dominant.items())
                },
                "sample_count": total,
            }
        )
    candidates.sort(key=lambda item: (-item["accuracy"], item["byte"]))
    return candidates[:12]


def _duration_candidates(
    rows: list[tuple[bytes, dict[str, Any]]]
) -> list[dict[str, Any]]:
    durations = {
        int(marker["duration_seconds"])
        for _, marker in rows
        if isinstance(marker.get("duration_seconds"), int)
    }
    if len(durations) < 2:
        return []
    result = []
    scales = (0.5, 1, 2, 60)
    for index in range(BODY_START, BODY_END - 1):
        for byte_order in ("little", "big"):
            for scale in scales:
                considered = 0
                matches = 0
                for frame, marker in rows:
                    duration = marker.get("duration_seconds")
                    if not isinstance(duration, int):
                        continue
                    considered += 1
                    raw = int.from_bytes(frame[index : index + 2], byte_order)
                    if raw * scale == duration:
                        matches += 1
                accuracy = matches / considered if considered else 0
                if accuracy >= 0.75:
                    result.append(
                        {
                            "offset": index,
                            "width": 2,
                            "byte_order": byte_order,
                            "scale_to_seconds": scale,
                            "accuracy": round(accuracy, 6),
                            "sample_count": considered,
                        }
                    )
    result.sort(
        key=lambda item: (-item["accuracy"], item["offset"], item["byte_order"])
    )
    return result[:12]


def analyze_zone_matrix(
    events: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    *,
    window_seconds: float = 10.0,
) -> dict[str, Any]:
    """Associate frames with structured action markers and rank changing fields."""
    markers = []
    for action in actions:
        timestamp = _timestamp(action.get("timestamp"))
        if timestamp is not None and (
            action.get("zone") is not None or action.get("duration_seconds") is not None
        ):
            markers.append((timestamp, action))
    markers.sort(key=lambda row: row[0])
    open_pairs = {
        (int(action["zone"]), int(action["duration_seconds"]))
        for _, action in markers
        if action.get("action") == "zone_open"
        and isinstance(action.get("zone"), int)
        and isinstance(action.get("duration_seconds"), int)
    }
    close_zones = {
        int(action["zone"])
        for _, action in markers
        if action.get("action") == "zone_close"
        and isinstance(action.get("zone"), int)
    }
    required_open_pairs = {
        (zone, duration)
        for zone in range(1, 5)
        for duration in (60, 120)
    }
    matrix_complete = required_open_pairs <= open_pairs and set(range(1, 5)) <= close_zones
    frames = _normalized(events)
    annotated: list[tuple[bytes, dict[str, Any]]] = []
    action_rows = []
    for position, (started_at, marker) in enumerate(markers):
        natural_end = started_at.timestamp() + window_seconds
        if position + 1 < len(markers):
            natural_end = min(natural_end, markers[position + 1][0].timestamp())
        selected = [
            frame
            for _, observed_at, frame in frames
            if started_at.timestamp() <= observed_at.timestamp() < natural_end
        ]
        annotated.extend((frame, marker) for frame in selected)
        action_rows.append(
            {
                "timestamp": started_at.isoformat(),
                "action": marker.get("action"),
                "zone": marker.get("zone"),
                "duration_seconds": marker.get("duration_seconds"),
                "frame_count": len(selected),
                "route_counts": dict(
                    Counter(
                        f"{frame[5:9].hex()}->{frame[9:13].hex()}"
                        for frame in selected
                    )
                ),
            }
        )

    by_route: dict[str, list[tuple[bytes, dict[str, Any]]]] = defaultdict(list)
    for frame, marker in annotated:
        by_route[f"{frame[5:9].hex()}->{frame[9:13].hex()}"].append((frame, marker))
    route_reports = []
    for route, rows in by_route.items():
        changed = []
        for index in range(BODY_START, BODY_END):
            counts = Counter(frame[index] for frame, _ in rows)
            if len(counts) > 1:
                changed.append(
                    {
                        "byte": index,
                        "values": {
                            f"0x{value:02x}": count
                            for value, count in counts.most_common()
                        },
                    }
                )
        route_reports.append(
            {
                "route": route,
                "frame_count": len(rows),
                "changed_body_bytes": changed,
                "zone_candidates": _categorical_candidates(rows, "zone"),
                "action_candidates": _categorical_candidates(rows, "action"),
                "duration_candidates": _duration_candidates(rows),
            }
        )
    route_reports.sort(key=lambda item: (-item["frame_count"], item["route"]))
    return {
        "window_seconds": window_seconds,
        "structured_action_count": len(markers),
        "associated_frame_count": len(annotated),
        "coverage": {
            "observed_open_pairs": [list(item) for item in sorted(open_pairs)],
            "missing_open_pairs": [
                list(item) for item in sorted(required_open_pairs - open_pairs)
            ],
            "observed_close_zones": sorted(close_zones),
            "missing_close_zones": sorted(set(range(1, 5)) - close_zones),
            "matrix_complete": matrix_complete,
        },
        "actions": action_rows,
        "routes": route_reports,
        "evidence_complete": bool(markers)
        and matrix_complete
        and all(item["frame_count"] > 0 for item in action_rows),
    }
