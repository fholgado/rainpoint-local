#!/usr/bin/env python3
"""Classify passive valve enrollment and compare structured multi-zone trials."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
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
    # The retained corpus predates normalized timezone handling, so SDR rows
    # may be naive while Wi-Fi-node rows are aware. The gateway event cursor is
    # monotonic across both sources and is therefore the authoritative order.
    result.sort(key=lambda row: (int(row[0].get("event_id", 0)), row[1].timestamp()))
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


def classify_htv405_retained_attempts(
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Separate enrollment, retained rejoin, and inconclusive HTV405 trials.

    This consumes the redacted attempt summaries promoted from retained IQ
    captures.  It deliberately does not equate a white LED with successful new
    enrollment: paired traffic can resume under the valve's stored identity
    without accepting a new assignment.
    """
    rows = []
    counts: Counter[str] = Counter()
    for attempt in attempts:
        flag = str(attempt.get("factory_flag", "")).lower()
        assignment = attempt.get("assignment_observed") is True
        paired = attempt.get("paired_traffic_observed") is True
        paired_before = attempt.get("paired_traffic_before_attempt") is True
        interpretation = str(attempt.get("interpretation", ""))
        if "methodology failure" in interpretation:
            classification = "invalid_methodology"
        elif flag == "7f":
            classification = (
                "cold_boot_rejoin_observed" if paired else "cold_boot_sweep_only"
            )
        elif paired_before and paired:
            classification = "retained_association_rejoin"
        elif paired and not assignment:
            classification = "retained_association_rejoin"
        elif assignment and paired:
            classification = "assignment_followed_by_paired_traffic"
        elif assignment:
            classification = "assignment_only_no_paired_progress"
        else:
            classification = "explicit_sweep_only"
        counts[classification] += 1
        rows.append(
            {
                "capture": attempt.get("capture"),
                "trigger": (
                    "cold_boot" if flag == "7f" else
                    "explicit_long_press" if flag == "ff" else "unknown"
                ),
                "classification": classification,
                "assignment_observed": assignment,
                "paired_traffic_before_attempt": paired_before,
                "paired_traffic_observed": paired,
                "new_assignment_proven": (
                    classification == "assignment_followed_by_paired_traffic"
                    and attempt.get("node_completed_steps") == 1
                    and "assignment accepted" in interpretation
                ),
            }
        )
    return {
        "attempt_count": len(rows),
        "classification_counts": dict(sorted(counts.items())),
        "attempts": rows,
        "findings": {
            "cold_boot_flag": "0x7f",
            "explicit_enrollment_flag": "0xff",
            "white_led_is_assignment_proof": False,
            "stored_identity_can_survive_battery_removal": any(
                item["classification"] == "retained_association_rejoin"
                for item in rows
            ),
        },
    }


def _ordered_frames(
    events: Iterable[dict[str, Any]],
) -> list[tuple[dict[str, Any], datetime, bytes]]:
    rows = []
    for event in events:
        frame = _frame(event)
        observed_at = _timestamp(event.get("observed_at"))
        if frame is not None and observed_at is not None:
            rows.append((event, observed_at, frame))
    rows.sort(key=lambda row: (int(row[0].get("event_id", 0)), row[1].timestamp()))
    return rows


def _htv405_command_zone(frame: bytes) -> tuple[int | None, str | None]:
    local_zone = frame[17] & 0x7F
    if frame[16] == 0x80 and 1 <= local_zone <= 4:
        return local_zone, "selector2_local"
    if (frame[17] & 0x7F) == 1:
        branch_zone = 2 * (frame[16] & 0x7F) + ((frame[17] >> 7) & 1)
        if 1 <= branch_zone <= 4:
            return branch_zone, "selector6_stock"
    return None, None


def _decode_valve_frame(
    frame: bytes,
    *,
    model: str,
    controller: bytes,
    valve: bytes,
    companion: bytes | None,
) -> dict[str, Any] | None:
    source = frame[5:9]
    destination = frame[9:13]
    if model == "HTV145FRF":
        if (
            (source, destination) == (controller, valve)
            and 0x80 <= frame[13] <= 0x9F
            and frame[14] in {0x10, 0x90}
            and frame[15] in {0x81, 0x82}
            and frame[16] == 0x80
            and frame[17] == 0x81
        ):
            watering = frame[14] == 0x10
            duration = None
            if watering:
                duration = ((frame[19] & 0x7F) | (frame[20] << 8)) * 2
            return {
                "role": "command",
                "sequence": frame[13],
                "action": "open" if watering else "close",
                "watering": watering,
                "zone": 1,
                "duration_seconds": duration,
            }
        if (
            (source, destination) == (valve, controller)
            and 0x80 <= frame[13] <= 0x9F
            and frame[14] in {0x50, 0xD0}
            and frame[15] == 0x86
            and frame[16] == 0x80
        ):
            return {
                "role": "response",
                "sequence": frame[13],
                "watering": frame[14] == 0x50,
                "zone": 1,
            }
        if (
            (source, destination) == (valve, controller)
            and frame[15] == 0x07
            and frame[16] == 0x85
            and frame[14] in {0x01, 0x81}
            and (frame[20] & 0x7F) == 0x4F
        ):
            return {
                "role": "state",
                "sequence": frame[13],
                "watering": bool(frame[20] & 0x80),
                "zone": 1,
            }
        return None

    if model != "HTV405FRF" or companion is None:
        raise ValueError("unsupported valve model or missing HTV405 companion")
    if (
        (source, destination) == (valve, companion)
        and frame[14] in {0x10, 0x90}
        and frame[15] in {0x81, 0x82}
    ):
        zone, packing = _htv405_command_zone(frame)
        if zone is None:
            return None
        # HTV405 operation lives at offset 15. Offset 14's high bit is an
        # observed repeat/phase bit and valid opens can carry 0x10 or 0x90.
        watering = frame[15] == 0x82
        duration = None
        if watering:
            duration = ((frame[19] & 0x7F) | (frame[20] << 8)) * 2
        return {
            "role": "command",
            "sequence": frame[13] & 0x1F,
            "action": "open" if watering else "close",
            "watering": watering,
            "zone": zone,
            "zone_packing": packing,
            "duration_seconds": duration,
        }
    if (
        (source, destination) == (controller, valve)
        and frame[14] in {0x50, 0xD0}
        and frame[15] == 0x86
        and (frame[18] & 0x7F) == 0x4F
        and 1 <= (frame[17] >> 4) <= 4
    ):
        return {
            "role": "response",
            "sequence": frame[13] & 0x1F,
            "watering": bool(frame[18] & 0x80),
            "zone": frame[17] >> 4,
        }
    if (
        (source, destination) == (controller, valve)
        and frame[15] == 0x07
        and (frame[20] & 0x7F) == 0x4F
    ):
        zone = (frame[19] & 0x70) >> 4
        watering = bool(frame[20] & 0x80) and 1 <= zone <= 4
        return {
            "role": "state",
            "sequence": frame[13] & 0x1F,
            "watering": watering,
            "zone": zone if watering else None,
        }
    return None


def analyze_valve_transactions(
    events: list[dict[str, Any]],
    *,
    model: str,
    controller_endpoint: str,
    valve_endpoint: str,
    companion_endpoint: str | None = None,
    retry_window_seconds: float = 2.1,
) -> dict[str, Any]:
    """Correlate logical commands, RF attempts, responses, and state reports."""
    controller = bytes.fromhex(controller_endpoint)
    valve = bytes.fromhex(valve_endpoint)
    companion = bytes.fromhex(companion_endpoint) if companion_endpoint else None
    decoded_rows = []
    for event, observed_at, frame in _ordered_frames(events):
        decoded = _decode_valve_frame(
            frame,
            model=model,
            controller=controller,
            valve=valve,
            companion=companion,
        )
        if decoded is not None:
            decoded_rows.append((event, observed_at, frame, decoded))

    transactions: list[dict[str, Any]] = []
    for event, observed_at, frame, decoded in decoded_rows:
        if decoded["role"] != "command":
            continue
        if transactions:
            previous = transactions[-1]
            elapsed = (observed_at - previous["_first_at"]).total_seconds()
            if frame.hex() == previous["command_frame"] and elapsed <= retry_window_seconds:
                previous["attempt_event_ids"].append(event.get("event_id"))
                previous["attempt_offsets_ms"].append(round(elapsed * 1_000, 3))
                previous["attempt_count"] += 1
                previous["_last_at"] = observed_at
                continue
        transactions.append(
            {
                "model": model,
                "action": decoded["action"],
                "zone": decoded["zone"],
                "zone_packing": decoded.get("zone_packing"),
                "duration_seconds": decoded.get("duration_seconds"),
                "command_sequence": decoded["sequence"],
                "command_frame": frame.hex(),
                "attempt_count": 1,
                "attempt_event_ids": [event.get("event_id")],
                "attempt_offsets_ms": [0.0],
                "response_event_id": None,
                "response_latency_ms": None,
                "state_event_id": None,
                "state_watering": None,
                "state_sequence": None,
                "_first_at": observed_at,
                "_last_at": observed_at,
            }
        )

    unassigned_states = 0
    for event, observed_at, _frame_bytes, decoded in decoded_rows:
        if decoded["role"] == "command":
            continue
        candidate = next(
            (
                row for row in reversed(transactions)
                if row["_last_at"] <= observed_at
                and (observed_at - row["_last_at"]).total_seconds() <= 30
                and (
                    row["zone"] == decoded.get("zone")
                    or (
                        decoded["role"] == "state"
                        and decoded["watering"] is False
                        and row["action"] == "close"
                    )
                )
                and row["action"] == ("open" if decoded["watering"] else "close")
            ),
            None,
        )
        if candidate is None:
            if decoded["role"] == "state":
                unassigned_states += 1
            continue
        if decoded["role"] == "response" and candidate["response_event_id"] is None:
            if decoded["sequence"] == candidate["command_sequence"]:
                candidate["response_event_id"] = event.get("event_id")
                candidate["response_latency_ms"] = round(
                    (observed_at - candidate["_last_at"]).total_seconds() * 1_000,
                    3,
                )
        elif decoded["role"] == "state" and candidate["state_event_id"] is None:
            candidate["state_event_id"] = event.get("event_id")
            candidate["state_watering"] = decoded["watering"]
            candidate["state_sequence"] = decoded["sequence"]

    transitions: Counter[int] = Counter()
    for previous, current in zip(transactions, transactions[1:]):
        transitions[(current["command_sequence"] - previous["command_sequence"]) & 0x1F] += 1
    for row in transactions:
        row.pop("_first_at")
        row.pop("_last_at")
        row["positive_evidence"] = (
            row["response_event_id"] is not None or row["state_event_id"] is not None
        )
    return {
        "model": model,
        "logical_command_count": len(transactions),
        "rf_attempt_count": sum(row["attempt_count"] for row in transactions),
        "confirmed_logical_command_count": sum(
            row["positive_evidence"] for row in transactions
        ),
        "unassigned_state_report_count": unassigned_states,
        "command_sequence_delta_counts": {
            str(delta): count for delta, count in sorted(transitions.items())
        },
        "transactions": transactions,
        "counter_warning": (
            "Only command sequences advance the outbound command stream; "
            "state-report sequences are independent telemetry."
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


def _effective_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply append-only operator corrections and return protocol actions only."""
    effective: list[dict[str, Any]] = []
    for original in actions:
        action = dict(original)
        if action.get("action") == "marker_correction":
            corrected_zone = action.get("zone")
            corrected_duration = action.get("duration_seconds")
            if not isinstance(corrected_zone, int):
                continue
            open_index = next(
                (
                    index
                    for index in range(len(effective) - 1, -1, -1)
                    if effective[index].get("action") == "zone_open"
                    and (
                        corrected_duration is None
                        or effective[index].get("duration_seconds")
                        == corrected_duration
                    )
                ),
                None,
            )
            if open_index is None:
                continue
            previous_zone = effective[open_index].get("zone")
            effective[open_index]["zone"] = corrected_zone
            effective[open_index]["corrected_by"] = action.get("timestamp")
            for candidate in effective[open_index + 1 :]:
                if (
                    candidate.get("action") == "zone_close"
                    and candidate.get("zone") == previous_zone
                ):
                    candidate["zone"] = corrected_zone
                    candidate["corrected_by"] = action.get("timestamp")
            continue
        if action.get("action") in {"zone_open", "zone_close"}:
            effective.append(action)
    return effective


def analyze_zone_matrix(
    events: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    *,
    window_seconds: float = 30.0,
) -> dict[str, Any]:
    """Associate frames with structured action markers and rank changing fields."""
    markers = []
    for action in _effective_actions(actions):
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
        if not selected:
            previous_end = started_at.timestamp() - window_seconds
            if position > 0:
                previous_end = max(
                    previous_end, markers[position - 1][0].timestamp()
                )
            selected = [
                frame
                for _, observed_at, frame in frames
                if previous_end < observed_at.timestamp() < started_at.timestamp()
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


def _load_json_events(path: Path) -> list[dict[str, Any]]:
    content = path.read_text(encoding="utf-8")
    decoder = json.JSONDecoder()
    offset = 0
    events: list[dict[str, Any]] = []
    while offset < len(content):
        while offset < len(content) and content[offset].isspace():
            offset += 1
        if offset >= len(content):
            break
        payload, offset = decoder.raw_decode(content, offset)
        if isinstance(payload, dict) and isinstance(payload.get("events"), list):
            payload = payload["events"]
        if isinstance(payload, dict):
            events.append(payload)
        elif isinstance(payload, list):
            events.extend(item for item in payload if isinstance(item, dict))
        else:
            raise ValueError("expected event objects, event lists, or API pages")
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    transactions = commands.add_parser("transactions")
    transactions.add_argument("events", type=Path)
    transactions.add_argument("--model", required=True, choices=("HTV145FRF", "HTV405FRF"))
    transactions.add_argument("--controller-endpoint", required=True)
    transactions.add_argument("--valve-endpoint", required=True)
    transactions.add_argument("--companion-endpoint")

    lifecycle = commands.add_parser("htv405-lifecycle")
    lifecycle.add_argument("summary", type=Path)

    args = parser.parse_args()
    if args.command == "transactions":
        report = analyze_valve_transactions(
            _load_json_events(args.events),
            model=args.model,
            controller_endpoint=args.controller_endpoint,
            valve_endpoint=args.valve_endpoint,
            companion_endpoint=args.companion_endpoint,
        )
    else:
        payload = json.loads(args.summary.read_text(encoding="utf-8"))
        attempts = payload.get("attempts")
        if not isinstance(attempts, list):
            raise ValueError("HTV405 lifecycle summary has no attempts list")
        report = classify_htv405_retained_attempts(attempts)
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
