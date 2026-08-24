#!/usr/bin/env python3
"""Analyze retained rainpointd events without modifying gateway state."""

from __future__ import annotations

import argparse
import binascii
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import urlopen


SYNC = bytes.fromhex("79f4882f28")
FRAME_BYTES = 38
RESIDUES = (0xC713, 0x4F03)
SENSOR_ENDPOINTS = {
    "9ce58024": "Right Bed",
    "c4e50024": "Left Bed",
    "ce628024": "Front Yard Sensor 1",
    "d1e28024": "Front Yard Sensor 2",
}


def trailer_residual(frame: bytes) -> int:
    """Return the observed CRC-CCITT/XOR trailer residue."""
    return binascii.crc_hqx(frame[:-2], 0) ^ int.from_bytes(frame[-2:], "big")


def load_events(source: Any) -> list[dict[str, Any]]:
    """Load one or more concatenated API pages or a bare event list."""
    content = source.read()
    decoder = json.JSONDecoder()
    offset = 0
    events: list[dict[str, Any]] = []
    while offset < len(content):
        while offset < len(content) and content[offset].isspace():
            offset += 1
        if offset >= len(content):
            break
        payload, offset = decoder.raw_decode(content, offset)
        if isinstance(payload, dict):
            payload = payload.get("events", [])
        if not isinstance(payload, list):
            raise ValueError(
                "expected event lists or objects containing events"
            )
        events.extend(event for event in payload if isinstance(event, dict))
    return events


def fetch_events(
    url: str,
    *,
    timeout: float = 10.0,
    max_pages: int = 10_000,
    opener: Callable[..., Any] = urlopen,
) -> list[dict[str, Any]]:
    """Read every cursor page from a read-only rainpointd events endpoint."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("events URL must use http or https")

    base_query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    try:
        since = int(base_query.pop("since", "0"))
    except ValueError as exc:
        raise ValueError("events URL since value must be an integer") from exc

    events: list[dict[str, Any]] = []
    for _ in range(max_pages):
        page_query = dict(base_query)
        page_query["since"] = str(since)
        page_url = urlunparse(parsed._replace(query=urlencode(page_query)))
        with opener(page_url, timeout=timeout) as response:
            payload = json.load(response)
        if not isinstance(payload, dict) or not isinstance(
            payload.get("events"), list
        ):
            raise ValueError("events endpoint returned an invalid page")
        page = [event for event in payload["events"] if isinstance(event, dict)]
        events.extend(page)
        next_since = payload.get("next_since")
        if not page:
            return events
        if not isinstance(next_since, int) or next_since <= since:
            raise ValueError("events endpoint cursor did not advance")
        since = next_since
    raise ValueError(f"events endpoint exceeded {max_pages} pages")


def event_frame(event: dict[str, Any]) -> bytes | None:
    """Return a structurally valid normalized frame from an event."""
    raw = event.get("raw") or event.get("state", {}).get("raw")
    if not isinstance(raw, str) or len(raw) != FRAME_BYTES * 2:
        return None
    try:
        frame = bytes.fromhex(raw)
    except ValueError:
        return None
    return frame if frame.startswith(SYNC) else None


def _feature_accuracy(
    frames: Iterable[tuple[bytes, int]], byte_index: int, bit: int
) -> tuple[float, dict[int, Counter[int]]]:
    groups: dict[int, Counter[int]] = defaultdict(Counter)
    count = 0
    correct = 0
    for frame, label in frames:
        groups[(frame[byte_index] >> bit) & 1][label] += 1
        count += 1
    for labels in groups.values():
        correct += max(labels.values())
    return (correct / count if count else 0.0), groups


def _timestamp(event: dict[str, Any]) -> datetime | None:
    value = event.get("observed_at")
    if not isinstance(value, str):
        return None
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # Historical rtl_433 rows use a naive gateway-local timestamp, while
    # Wi-Fi radio nodes emit explicit UTC offsets. Interpret only the former
    # in the machine's local timezone so mixed receiver corpora remain
    # comparable without rewriting retained evidence.
    return observed.astimezone() if observed.tzinfo is None else observed


def _top_xor_features(
    frames: list[tuple[bytes, int]], limit: int = 12
) -> list[dict[str, Any]]:
    """Find the best one- or two-bit XOR predictors for the residue selector."""
    if not frames:
        return []
    feature_masks = []
    for byte_index in range(FRAME_BYTES - 2):
        for bit in range(8):
            mask = 0
            for row, (frame, _) in enumerate(frames):
                if (frame[byte_index] >> bit) & 1:
                    mask |= 1 << row
            feature_masks.append((byte_index, bit, mask))
    label_mask = 0
    for row, (_, label) in enumerate(frames):
        if label:
            label_mask |= 1 << row

    candidates = []
    row_count = len(frames)
    for left in range(len(feature_masks)):
        left_byte, left_bit, left_mask = feature_masks[left]
        for right in range(left + 1, len(feature_masks)):
            right_byte, right_bit, right_mask = feature_masks[right]
            errors = bin((left_mask ^ right_mask) ^ label_mask).count("1")
            correct = max(errors, row_count - errors)
            candidates.append(
                (
                    correct,
                    left_byte,
                    left_bit,
                    right_byte,
                    right_bit,
                    errors > row_count - errors,
                )
            )
    candidates.sort(reverse=True)
    return [
        {
            "left_byte": left_byte,
            "left_bit": left_bit,
            "right_byte": right_byte,
            "right_bit": right_bit,
            "inverted": inverted,
            "accuracy": round(correct / row_count, 6),
        }
        for (
            correct,
            left_byte,
            left_bit,
            right_byte,
            right_bit,
            inverted,
        ) in candidates[:limit]
    ]


def _transition_counts(residues: Iterable[int]) -> dict[str, int]:
    previous = None
    result = Counter()
    for residual in residues:
        if previous is not None:
            result["same" if residual == previous else "different"] += 1
        previous = residual
    return dict(result)


def _hamming_distance(left: int, right: int) -> int:
    return bin(left ^ right).count("1")


def _latency_summary(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"count": 0}
    ordered = sorted(values)

    def percentile(fraction: float) -> float:
        index = round((len(ordered) - 1) * fraction)
        return round(ordered[index], 6)

    return {
        "count": len(ordered),
        "minimum_seconds": round(ordered[0], 6),
        "median_seconds": percentile(0.5),
        "p95_seconds": percentile(0.95),
        "maximum_seconds": round(ordered[-1], 6),
    }


def _htv145_links(
    events: list[tuple[dict[str, Any], bytes, int]],
) -> set[tuple[bytes, bytes]]:
    """Infer HTV145 controller/valve links from decoded observations.

    A link is deliberately learned from model-qualified retained evidence, not
    from installation-specific endpoint constants. Commands run controller to
    valve; every decoded status/usage report runs valve to controller.
    """
    links: set[tuple[bytes, bytes]] = set()
    for event, frame, _ in events:
        state = event.get("state", {})
        if state.get("model") != "HTV145FRF":
            continue
        if frame[14] in (0x10, 0x90):
            links.add((frame[5:9], frame[9:13]))
        else:
            links.add((frame[9:13], frame[5:9]))
    return links


def _deduplicate_receiver_observations(
    events: list[tuple[dict[str, Any], bytes, int]],
    *,
    window_seconds: float = 0.15,
) -> list[tuple[dict[str, Any], bytes, int]]:
    """Collapse one air transmission heard by multiple receivers.

    Exact frames farther apart than the short receiver fan-in window remain
    separate. That preserves true on-air retransmissions while avoiding a
    false retransmission count caused by SDR and ESP32 diversity reception.
    """
    ordered = sorted(
        events,
        key=lambda item: _timestamp(item[0]) or datetime.min,
    )
    result: list[tuple[dict[str, Any], bytes, int]] = []
    last_by_raw: dict[bytes, datetime] = {}
    for item in ordered:
        observed_at = _timestamp(item[0])
        if observed_at is None:
            continue
        previous = last_by_raw.get(item[1])
        if previous is not None:
            delta = (observed_at - previous).total_seconds()
            if 0 <= delta <= window_seconds:
                continue
        result.append(item)
        last_by_raw[item[1]] = observed_at
    return result


def _htv145_transaction_summary(
    clean_events: list[tuple[dict[str, Any], bytes, int]],
    *,
    response_window_seconds: float = 3.0,
    state_confirmation_window_seconds: float = 15.0,
) -> dict[str, Any]:
    """Separate HTV145 command, response, and telemetry counter evidence."""
    links = _htv145_links(clean_events)
    if not links:
        return {
            "links": [],
            "command_count": 0,
            "commands": [],
            "telemetry_counter_transitions": {},
            "telemetry_acknowledgements": {"count": 0},
        }

    route_events = [
        item
        for item in clean_events
        if any(
            (item[1][5:9], item[1][9:13])
            in ((controller, valve), (valve, controller))
            for controller, valve in links
        )
    ]
    transmissions = _deduplicate_receiver_observations(route_events)
    transmissions.sort(key=lambda item: _timestamp(item[0]) or datetime.min)

    command_groups: list[list[tuple[int, dict[str, Any], bytes, int]]] = []
    for position, (event, frame, residual) in enumerate(transmissions):
        if (
            (frame[5:9], frame[9:13]) not in links
            or frame[14] not in (0x10, 0x90)
        ):
            continue
        observed_at = _timestamp(event)
        if observed_at is None:
            continue
        if command_groups:
            previous = command_groups[-1][-1]
            previous_at = _timestamp(previous[1])
            if (
                previous[2] == frame
                and previous_at is not None
                and 0 <= (observed_at - previous_at).total_seconds() <= 5.0
            ):
                command_groups[-1].append((position, event, frame, residual))
                continue
        command_groups.append([(position, event, frame, residual)])

    commands: list[dict[str, Any]] = []
    for attempts in command_groups:
        position, event, frame, residual = attempts[0]
        observed_at = _timestamp(event)
        last_attempt_at = _timestamp(attempts[-1][1])
        if observed_at is None or last_attempt_at is None:
            continue
        mode = "open" if frame[14] == 0x10 else "close"
        expected_watering = mode == "open"
        response = None
        state_confirmation = None
        for candidate_event, candidate_frame, candidate_residual in transmissions[
            position + 1 :
        ]:
            candidate_at = _timestamp(candidate_event)
            if candidate_at is None:
                continue
            delta = (candidate_at - observed_at).total_seconds()
            if delta < 0:
                continue
            if delta > state_confirmation_window_seconds:
                break
            reverse_link = (
                candidate_frame[5:9] == frame[9:13]
                and candidate_frame[9:13] == frame[5:9]
            )
            if not reverse_link:
                continue
            if (
                response is None
                and delta <= response_window_seconds
                and candidate_frame[13] == frame[13]
                and candidate_frame[14]
                == (0x50 if mode == "open" else 0xD0)
            ):
                response = {
                    "event_id": candidate_event.get("event_id"),
                    "latency_from_first_attempt_seconds": round(delta, 6),
                    "latency_from_last_attempt_seconds": round(
                        (candidate_at - last_attempt_at).total_seconds(), 6
                    ),
                    "residual": f"{candidate_residual:04x}",
                }
            state = candidate_event.get("state", {})
            if (
                state_confirmation is None
                and state.get("model") == "HTV145FRF"
                and state.get("is_watering") is expected_watering
            ):
                state_confirmation = {
                    "event_id": candidate_event.get("event_id"),
                    "latency_from_first_attempt_seconds": round(delta, 6),
                    "latency_from_last_attempt_seconds": round(
                        (candidate_at - last_attempt_at).total_seconds(), 6
                    ),
                    "telemetry_sequence": f"{candidate_frame[13]:02x}",
                }
        duration = None
        if mode == "open":
            raw_duration = int.from_bytes(frame[19:21], "little")
            duration_candidates = {
                raw_duration * 2,
                (raw_duration & ~0x80) * 2,
            }
            confirmed = [
                value
                for value in duration_candidates
                if 0 < value <= 24 * 60 * 60 and value % 60 == 0
            ]
            duration = confirmed[0] if len(confirmed) == 1 else None
        commands.append(
            {
                "event_id": event.get("event_id"),
                "observed_at": event.get("observed_at"),
                "controller_endpoint": frame[5:9].hex(),
                "valve_endpoint": frame[9:13].hex(),
                "mode": mode,
                "command_sequence": f"{frame[13]:02x}",
                "attempt_count": len(attempts),
                "attempt_intervals_seconds": [
                    round(
                        (
                            _timestamp(right[1]) - _timestamp(left[1])
                        ).total_seconds(),
                        6,
                    )
                    for left, right in zip(attempts, attempts[1:])
                    if _timestamp(left[1]) is not None
                    and _timestamp(right[1]) is not None
                ],
                "duration_seconds": duration,
                "residual": f"{residual:04x}",
                "immediate_response": response,
                "state_confirmation": state_confirmation,
            }
        )

    command_transitions: Counter[int] = Counter()
    for previous, current in zip(commands, commands[1:]):
        if (
            previous["controller_endpoint"] == current["controller_endpoint"]
            and previous["valve_endpoint"] == current["valve_endpoint"]
        ):
            left = int(previous["command_sequence"], 16) & 0x1F
            right = int(current["command_sequence"], 16) & 0x1F
            command_transitions[(right - left) & 0x1F] += 1

    telemetry_sequences: dict[str, list[int]] = defaultdict(list)
    ack_latencies: list[float] = []
    ack_pairs = 0
    for position, (event, frame, _) in enumerate(transmissions):
        for controller, valve in links:
            if frame[5:9] != valve or frame[9:13] != controller:
                continue
            if frame[14] in (0x50, 0xD0):
                continue
            route = f"{controller.hex()}->{valve.hex()}"
            sequence = frame[13] & 0x1F
            if (
                not telemetry_sequences[route]
                or telemetry_sequences[route][-1] != sequence
            ):
                telemetry_sequences[route].append(sequence)
            observed_at = _timestamp(event)
            if observed_at is None:
                continue
            for candidate_event, candidate_frame, _ in transmissions[position + 1 :]:
                candidate_at = _timestamp(candidate_event)
                if candidate_at is None:
                    continue
                delta = (candidate_at - observed_at).total_seconds()
                if delta < 0:
                    continue
                if delta > response_window_seconds:
                    break
                if (
                    candidate_frame[5:9] == controller
                    and candidate_frame[9:13] == valve
                    and candidate_frame[13] == frame[13]
                    and candidate_frame[14] not in (0x10, 0x90)
                ):
                    ack_pairs += 1
                    ack_latencies.append(delta)
                    break

    telemetry_transitions: dict[str, dict[str, int]] = {}
    for route, sequences in telemetry_sequences.items():
        counts = Counter(
            (right - left) & 0x1F
            for left, right in zip(sequences, sequences[1:])
        )
        telemetry_transitions[route] = {
            str(delta): count for delta, count in sorted(counts.items())
        }

    return {
        "links": [
            {
                "controller_endpoint": controller.hex(),
                "valve_endpoint": valve.hex(),
            }
            for controller, valve in sorted(links)
        ],
        "command_count": len(commands),
        "command_counter_transitions": {
            str(delta): count
            for delta, count in sorted(command_transitions.items())
        },
        "commands": commands,
        "telemetry_counter_transitions": telemetry_transitions,
        "telemetry_acknowledgements": {
            "count": ack_pairs,
            "latency": _latency_summary(ack_latencies),
        },
    }


def _valve_transaction_summary(
    bursts: list[tuple[dict[str, Any], bytes, int]],
    response_window_seconds: float = 3.0,
) -> dict[str, Any]:
    """Correlate captured hub commands with the next valve-to-hub frame."""
    commands = []
    latencies: dict[str, list[float]] = defaultdict(list)
    duration_counts: Counter[int] = Counter()
    link_counts: Counter[str] = Counter()
    acknowledged = Counter()
    for position, (event, frame, residual) in enumerate(bursts):
        if frame[14] not in (0x10, 0x90):
            continue
        observed_at = _timestamp(event)
        if observed_at is None:
            continue
        # The operation selector is frame[15] low bits: 0x02 opens and 0x01
        # closes. HTV405 uses frame[14] bit 7 as a repeat/phase bit, so treating
        # that bit as the operation reverses valid commands whenever the phase
        # flips. Retain the old frame[14] fallback only for incomplete research
        # frames that predate the full command-body capture.
        operation_selector = frame[15] & 0x7F
        if operation_selector == 0x02:
            mode = "open"
        elif operation_selector == 0x01:
            mode = "close"
        else:
            mode = "close" if frame[14] & 0x80 else "open"
        controller_endpoint = frame[5:9]
        valve_endpoint = frame[9:13]
        link = f"{controller_endpoint.hex()}->{valve_endpoint.hex()}"
        link_counts[link] += 1
        duration = 0
        if mode == "open":
            raw_duration = int.from_bytes(frame[19:21], "little")
            candidates = {raw_duration * 2, (raw_duration & ~0x80) * 2}
            confirmed = [
                value
                for value in candidates
                if 0 < value <= 24 * 60 * 60 and value % 60 == 0
            ]
            duration = confirmed[0] if len(confirmed) == 1 else raw_duration * 2
        duration_counts[duration] += 1
        response_event_id = None
        latency = None
        for candidate_event, candidate_frame, _ in bursts[position + 1 :]:
            candidate_at = _timestamp(candidate_event)
            if candidate_at is None:
                continue
            delta = (candidate_at - observed_at).total_seconds()
            if delta < 0:
                continue
            if delta > response_window_seconds:
                break
            if (
                candidate_frame[5:9] == valve_endpoint
                and candidate_frame[9:13] == controller_endpoint
                and candidate_frame[13] == frame[13]
                and candidate_frame[14]
                == (0xD0 if mode == "close" else 0x50)
            ):
                latency = delta
                response_event_id = candidate_event.get("event_id")
                latencies[mode].append(delta)
                acknowledged[mode] += 1
                break
        commands.append(
            {
                "event_id": event.get("event_id"),
                "observed_at": event.get("observed_at"),
                "mode": mode,
                "controller_endpoint": controller_endpoint.hex(),
                "valve_endpoint": valve_endpoint.hex(),
                "sequence": f"{frame[13]:02x}",
                "duration_bytes": frame[19:21].hex(),
                "duration_seconds": duration,
                "residual": f"{residual:04x}",
                "response_event_id": response_event_id,
                "response_latency_seconds": (
                    round(latency, 6) if latency is not None else None
                ),
            }
        )

    mode_counts = Counter(command["mode"] for command in commands)
    return {
        "response_window_seconds": response_window_seconds,
        "command_count": len(commands),
        "link_counts": dict(link_counts.most_common()),
        "mode_counts": dict(mode_counts),
        "acknowledged_counts": dict(acknowledged),
        "acknowledgement_rates": {
            mode: round(acknowledged[mode] / count, 6)
            for mode, count in mode_counts.items()
        },
        "response_latency": {
            mode: _latency_summary(values)
            for mode, values in sorted(latencies.items())
        },
        "open_duration_counts": {
            str(duration): count
            for duration, count in sorted(duration_counts.items())
            if duration
        },
        "commands": commands,
    }


def analyze(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Return integrity, selector-feature, and compact-routing evidence."""
    normalized: list[tuple[dict[str, Any], bytes, int]] = []
    invalid_residues: Counter[str] = Counter()
    invalid_residue_distances: Counter[int] = Counter()
    for event in events:
        frame = event_frame(event)
        if frame is None:
            continue
        residual = trailer_residual(frame)
        normalized.append((event, frame, residual))
        if residual not in RESIDUES:
            invalid_residues[f"{residual:04x}"] += 1
            invalid_residue_distances[
                min(_hamming_distance(residual, known) for known in RESIDUES)
            ] += 1

    unique_by_raw: dict[bytes, tuple[dict[str, Any], int]] = {}
    for event, frame, residual in normalized:
        unique_by_raw.setdefault(frame, (event, residual))
    clean_unique = [
        (frame, residual)
        for frame, (_, residual) in unique_by_raw.items()
        if residual in RESIDUES
    ]

    payload_residues: dict[bytes, set[int]] = defaultdict(set)
    for frame, residual in clean_unique:
        payload_residues[frame[:-2]].add(residual)
    conflicting_payloads = sum(
        1 for residues in payload_residues.values() if len(residues) > 1
    )

    bit_features = []
    labels = {RESIDUES[0]: 0, RESIDUES[1]: 1}
    labeled = [(frame, labels[residual]) for frame, residual in clean_unique]
    for byte_index in range(FRAME_BYTES - 2):
        for bit in range(8):
            accuracy, groups = _feature_accuracy(labeled, byte_index, bit)
            bit_features.append(
                {
                    "byte": byte_index,
                    "bit": bit,
                    "accuracy": round(accuracy, 6),
                    "zero": dict(groups[0]),
                    "one": dict(groups[1]),
                }
            )
    bit_features.sort(key=lambda item: item["accuracy"], reverse=True)

    clean_events = [
        (event, frame, residual)
        for event, frame, residual in normalized
        if residual in RESIDUES
    ]
    clean_events.sort(key=lambda item: item[0].get("event_id", 0))
    bursts = []
    previous_frame = None
    for event, frame, residual in clean_events:
        if frame == previous_frame:
            continue
        bursts.append((event, frame, residual))
        previous_frame = frame

    route_transitions: dict[str, list[int]] = defaultdict(list)
    for _, frame, residual in bursts:
        route = f"{frame[5:9].hex()}->{frame[9:13].hex()}"
        route_transitions[route].append(residual)

    route_residues: dict[str, Counter[str]] = defaultdict(Counter)
    message_residues: dict[str, Counter[str]] = defaultdict(Counter)
    route_labeled: dict[str, list[tuple[bytes, int]]] = defaultdict(list)
    for frame, residual in clean_unique:
        residue = f"{residual:04x}"
        route = f"{frame[5:9].hex()}->{frame[9:13].hex()}"
        route_residues[route][residue] += 1
        message_residues[f"{frame[13]:02x}"][residue] += 1
        route_labeled[route].append((frame, labels[residual]))

    route_selector_bits = {}
    for route, frames in route_labeled.items():
        if len(frames) < 10:
            continue
        candidates = []
        for byte_index in range(FRAME_BYTES - 2):
            for bit in range(8):
                accuracy, groups = _feature_accuracy(frames, byte_index, bit)
                candidates.append((accuracy, byte_index, bit, groups))
        accuracy, byte_index, bit, groups = max(candidates)
        message_bit_accuracy, message_groups = _feature_accuracy(frames, 13, 0)
        route_selector_bits[route] = {
            "frame_count": len(frames),
            "best_byte": byte_index,
            "best_bit": bit,
            "best_accuracy": round(accuracy, 6),
            "best_zero": dict(groups[0]),
            "best_one": dict(groups[1]),
            "message_lsb_accuracy": round(message_bit_accuracy, 6),
            "message_lsb_zero": dict(message_groups[0]),
            "message_lsb_one": dict(message_groups[1]),
        }

    known_observations = []
    compact_frames = []
    for event, frame, residual in normalized:
        observed_at = _timestamp(event)
        if observed_at is None:
            continue
        state = event.get("state", {})
        endpoint = state.get("rf_endpoint")
        moisture = state.get("soil_moisture_percent")
        if endpoint in SENSOR_ENDPOINTS and isinstance(moisture, int):
            known_observations.append((observed_at, endpoint, moisture))

        status_moisture = state.get("status_soil_moisture_percent")
        if status_moisture is None:
            body = frame[13:-2]
            for marker in range(len(body) - 1):
                if body[marker] != 0x88:
                    continue
                has_field_code = marker > 0 and body[marker - 1] == 0x0A
                has_rssi = marker + 3 < len(body) and body[marker + 2] == 0xE0
                if not has_field_code and not has_rssi:
                    continue
                candidate = body[marker + 1]
                if candidate <= 100:
                    status_moisture = candidate
                    break
        if isinstance(status_moisture, int):
            compact_frames.append((event, frame, observed_at, status_moisture))

    compact_associations = []
    for event, frame, observed_at, moisture in compact_frames:
        residual = trailer_residual(frame)
        nearest_by_endpoint: dict[str, dict[str, Any]] = {}
        for known_at, endpoint, known_moisture in known_observations:
            delta = (observed_at - known_at).total_seconds()
            candidate = {
                "endpoint": endpoint,
                "name": SENSOR_ENDPOINTS[endpoint],
                "moisture": known_moisture,
                "delta_seconds": round(delta, 6),
                "value_matches": known_moisture == moisture,
            }
            previous = nearest_by_endpoint.get(endpoint)
            if previous is None or abs(delta) < abs(previous["delta_seconds"]):
                nearest_by_endpoint[endpoint] = candidate
        candidates = list(nearest_by_endpoint.values())
        candidates.sort(key=lambda item: abs(item["delta_seconds"]))
        compact_associations.append(
            {
                "event_id": event.get("event_id"),
                "observed_at": event.get("observed_at"),
                "route": f"{frame[5:9].hex()}->{frame[9:13].hex()}",
                "moisture": moisture,
                "residual": f"{residual:04x}",
                "trailer_valid": residual in RESIDUES,
                "candidates": candidates,
            }
        )

    return {
        "event_count": len(events),
        "normalized_event_count": len(normalized),
        "unique_frame_count": len(unique_by_raw),
        "clean_unique_count": len(clean_unique),
        "clean_unique_residues": dict(
            Counter(f"{residual:04x}" for _, residual in clean_unique)
        ),
        "invalid_residue_event_count": sum(invalid_residues.values()),
        "common_invalid_residues": invalid_residues.most_common(10),
        "invalid_residue_min_hamming_distance": {
            str(distance): count
            for distance, count in sorted(invalid_residue_distances.items())
        },
        "same_payload_conflicting_residue_count": conflicting_payloads,
        "top_selector_bits": bit_features[:12],
        "top_two_bit_xor_selectors": _top_xor_features(labeled),
        "event_residue_transitions": _transition_counts(
            residual for _, _, residual in clean_events
        ),
        "burst_count": len(bursts),
        "burst_residue_transitions": _transition_counts(
            residual for _, _, residual in bursts
        ),
        "route_burst_transitions": {
            route: _transition_counts(residues)
            for route, residues in sorted(
                route_transitions.items(), key=lambda item: -len(item[1])
            )
            if len(residues) >= 10
        },
        "route_residues": {
            route: dict(counts)
            for route, counts in sorted(
                route_residues.items(), key=lambda item: -sum(item[1].values())
            )
        },
        "route_selector_bits": {
            route: details
            for route, details in sorted(
                route_selector_bits.items(),
                key=lambda item: -item[1]["frame_count"],
            )
        },
        "message_residues": {
            message: dict(counts)
            for message, counts in sorted(
                message_residues.items(), key=lambda item: -sum(item[1].values())
            )
        },
        "valve_transactions": _valve_transaction_summary(bursts),
        "htv145_transactions": _htv145_transaction_summary(clean_events),
        "compact_associations": compact_associations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "events",
        nargs="?",
        type=Path,
        help="rainpointd events JSON; omit to read stdin",
    )
    parser.add_argument(
        "--url",
        help="read all cursor pages from a rainpointd /api/v1/events URL",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="per-page HTTP timeout in seconds (default: 10)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="omit per-command valve transaction rows",
    )
    parser.add_argument(
        "--section",
        choices=(
            "valve_transactions",
            "htv145_transactions",
            "compact_associations",
        ),
        help="emit only one detailed analysis section",
    )
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    if args.url and args.events:
        parser.error("events file and --url are mutually exclusive")
    if args.url:
        events = fetch_events(args.url, timeout=args.timeout)
    elif args.events:
        with args.events.open(encoding="utf-8") as source:
            events = load_events(source)
    else:
        events = load_events(sys.stdin)
    result = analyze(events)
    if args.summary:
        result["valve_transactions"].pop("commands", None)
        result["htv145_transactions"].pop("commands", None)
    if args.section:
        result = {args.section: result[args.section]}
    json.dump(result, sys.stdout, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
