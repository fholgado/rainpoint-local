#!/usr/bin/env python3
"""Prepare, mark, and finish evidence-complete RainPoint RF trials."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import urlopen

try:
    from valve_trial_analysis import (
        analyze_zone_matrix,
        classify_pairing_exchange,
    )
except ModuleNotFoundError:  # Imported as tools.rf_trial by the test suite.
    from tools.valve_trial_analysis import (
        analyze_zone_matrix,
        classify_pairing_exchange,
    )


FRAME_BYTES = 38
SYNC = bytes.fromhex("79f4882f28")
# Pairing replies use this companion endpoint.  The frame direction is the
# paired sensor identity to this endpoint even though the gateway (stock or
# local) physically transmits it.  Therefore these frames are only attributable
# to the stock gateway when the local transmitter was not authorized.
STOCK_PAIRING_COMPANION_ENDPOINT = bytes.fromhex("39840280")
TRIAL_ID = re.compile(r"[a-z0-9][a-z0-9_-]{2,63}\Z")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_json(
    url: str,
    *,
    timeout: float = 10.0,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    with opener(url, timeout=timeout) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object from {url}")
    return payload


def gateway_snapshot(
    gateway_url: str,
    *,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    base = gateway_url.rstrip("/")
    return {
        name: _get_json(f"{base}/api/v1/{name}", opener=opener)
        for name in ("info", "devices", "nodes", "receivers", "pairing")
    }


def evaluate_preflight(
    snapshot: dict[str, Any],
    *,
    selected_node_id: str | None,
    free_bytes: int,
    minimum_free_bytes: int,
    rtl_433_path: str | None,
) -> dict[str, Any]:
    """Evaluate read-only capture prerequisites without arming a transmitter."""
    info = snapshot.get("info", {})
    nodes = snapshot.get("nodes", {}).get("nodes", [])
    pairing = snapshot.get("pairing", {})
    managed = [node for node in nodes if node.get("managed") is True]
    selected = next(
        (node for node in managed if node.get("node_id") == selected_node_id), None
    )
    checks = {
        "gateway_transport_healthy": info.get("transport_healthy") is True,
        "managed_nodes_present": bool(managed),
        "managed_nodes_connected": bool(managed)
        and all(node.get("connected") is True for node in managed),
        "managed_nodes_authenticated": bool(managed)
        and all(node.get("authenticated") is True for node in managed),
        "transmitters_disarmed": bool(managed)
        and all(node.get("tx_armed") is False for node in managed),
        "pairing_idle": pairing.get("active") is not True,
        "selected_node_ready": selected_node_id is None
        or (
            selected is not None
            and selected.get("connected") is True
            and selected.get("authenticated") is True
            and selected.get("tx_armed") is False
        ),
        "rtl_433_available": rtl_433_path is not None,
        "capture_disk_space": free_bytes >= minimum_free_bytes,
    }
    return {
        "checked_at": _now(),
        "selected_node_id": selected_node_id,
        "managed_node_count": len(managed),
        "rtl_433_path": rtl_433_path,
        "free_bytes": free_bytes,
        "minimum_free_bytes": minimum_free_bytes,
        "checks": checks,
        "passed": all(checks.values()),
        "rf_transmit_authorized": False,
    }


def fetch_events(
    gateway_url: str,
    since: int,
    *,
    opener: Callable[..., Any] = urlopen,
) -> list[dict[str, Any]]:
    """Fetch every cursor page newer than ``since``."""
    base = gateway_url.rstrip("/")
    result: list[dict[str, Any]] = []
    cursor = since
    for _ in range(10_000):
        query = urlencode({"since": cursor})
        payload = _get_json(f"{base}/api/v1/events?{query}", opener=opener)
        page = payload.get("events")
        if not isinstance(page, list):
            raise ValueError("gateway returned an invalid events page")
        result.extend(item for item in page if isinstance(item, dict))
        if not page:
            return result
        next_cursor = payload.get("next_since")
        if not isinstance(next_cursor, int) or next_cursor <= cursor:
            raise ValueError("gateway event cursor did not advance")
        cursor = next_cursor
    raise ValueError("gateway event pagination exceeded 10000 pages")


def latest_event_cursor(
    gateway_url: str,
    *,
    opener: Callable[..., Any] = urlopen,
) -> int:
    events = fetch_events(gateway_url, 0, opener=opener)
    return max((int(item.get("event_id", 0)) for item in events), default=0)


def _event_frame(event: dict[str, Any]) -> bytes | None:
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


def analyze_trial(
    manifest: dict[str, Any],
    events: list[dict[str, Any]],
    actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Summarize captured routes and pairing-specific terminal evidence."""
    routes: Counter[str] = Counter()
    messages: Counter[str] = Counter()
    directed_links: set[tuple[bytes, bytes]] = set()
    factory_count = 0
    paired_count = 0
    terminal_count = 0
    companion_reply_count = 0
    stock_gateway_count = 0
    factory = manifest.get("expected_factory_endpoint")
    paired = manifest.get("expected_paired_endpoint")
    factory_bytes = bytes.fromhex(factory) if factory else None
    paired_bytes = bytes.fromhex(paired) if paired else None
    assigned_channel = manifest.get("assigned_channel")
    echoed_channels: Counter[int] = Counter()
    local_tx_authorized = manifest.get("rf_transmit_authorized") is True

    normalized = 0
    for event in events:
        frame = _event_frame(event)
        if frame is None:
            continue
        normalized += 1
        source = frame[5:9]
        destination = frame[9:13]
        message = frame[13] & 0x7F
        routes[f"{source.hex()}->{destination.hex()}"] += 1
        directed_links.add((source, destination))
        messages[f"0x{message:02x}"] += 1
        if destination == STOCK_PAIRING_COMPANION_ENDPOINT:
            companion_reply_count += 1
            if not local_tx_authorized:
                stock_gateway_count += 1
        if factory_bytes is not None and factory_bytes in (source, destination):
            factory_count += 1
        if paired_bytes is not None and paired_bytes in (source, destination):
            paired_count += 1
            if destination == paired_bytes and message == 1:
                echoed_channels[2 * frame[16] + (1 if frame[17] & 0x80 else 0)] += 1
            if destination == paired_bytes and message == 3:
                terminal_count += 1

    stock_expected_silent = manifest.get("stock_gateway_state") == "off_verified"
    bidirectional_links = sorted(
        f"{source.hex()}<->{destination.hex()}"
        for source, destination in directed_links
        if source < destination and (destination, source) in directed_links
    )
    checks = {"captured_normalized_frames": normalized > 0}
    if manifest.get("kind") == "valve_pairing":
        checks.update(
            {
                "multiple_valve_frames_observed": normalized >= 2,
                "bidirectional_valve_exchange_observed": bool(bidirectional_links),
                "multiple_message_types_observed": len(messages) >= 2,
            }
        )
    else:
        checks.update(
            {
                "factory_identity_observed": (
                    factory_bytes is None or factory_count > 0
                ),
                "paired_identity_observed": paired_bytes is None or paired_count > 0,
                "terminal_message_03_observed": (
                    paired_bytes is None or terminal_count > 0
                ),
                "assigned_channel_echoed": (
                    assigned_channel is None
                    or echoed_channels[int(assigned_channel)] > 0
                ),
            }
        )
    checks["known_stock_gateway_endpoint_silent"] = (
        not stock_expected_silent or stock_gateway_count == 0
    )
    report = {
        "event_count": len(events),
        "normalized_frame_count": normalized,
        "route_counts": dict(routes.most_common()),
        "message_counts": dict(messages.most_common()),
        "bidirectional_links": bidirectional_links,
        "factory_identity_frame_count": factory_count,
        "paired_identity_frame_count": paired_count,
        "terminal_message_03_count": terminal_count,
        "companion_reply_frame_count": companion_reply_count,
        "stock_gateway_frame_count": stock_gateway_count,
        "assigned_channel": assigned_channel,
        "echoed_channel_counts": {
            str(channel): count for channel, count in sorted(echoed_channels.items())
        },
        "checks": checks,
        "passed": all(checks.values()),
    }
    if manifest.get("kind") == "valve_pairing":
        report["pairing_exchange"] = classify_pairing_exchange(events)
        report["zone_matrix"] = analyze_zone_matrix(events, actions or [])
        if report["zone_matrix"]["structured_action_count"]:
            checks["structured_zone_matrix_complete"] = report["zone_matrix"][
                "evidence_complete"
            ]
            report["passed"] = all(checks.values())
    return report


def _load_actions(path: Path) -> list[dict[str, Any]]:
    actions = []
    if not path.is_file():
        return actions
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict):
            raise ValueError(f"invalid action row {line_number}: expected object")
        actions.append(item)
    return actions


def preflight(args: argparse.Namespace) -> int:
    snapshot = gateway_snapshot(args.gateway_url)
    disk_path = args.output.resolve()
    while not disk_path.exists() and disk_path != disk_path.parent:
        disk_path = disk_path.parent
    report = evaluate_preflight(
        snapshot,
        selected_node_id=args.selected_node,
        free_bytes=shutil.disk_usage(disk_path).free,
        minimum_free_bytes=int(args.minimum_free_gib * 1024**3),
        rtl_433_path=shutil.which("rtl_433"),
    )
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(encoded)
    print(encoded, end="")
    return 0 if report["passed"] else 1


def prepare(args: argparse.Namespace) -> int:
    if not TRIAL_ID.fullmatch(args.trial_id):
        raise ValueError("trial ID must use 3-64 lowercase letters, digits, _ or -")
    trial_dir = args.output / args.trial_id
    if trial_dir.exists():
        raise ValueError(f"trial directory already exists: {trial_dir}")
    trial_dir.mkdir(parents=True)
    started_at = _now()
    manifest = {
        "schema_version": 1,
        "trial_id": args.trial_id,
        "kind": args.kind,
        "gateway_url": args.gateway_url.rstrip("/"),
        "started_at": started_at,
        "event_cursor": latest_event_cursor(args.gateway_url),
        "selected_node_id": args.selected_node,
        "stock_gateway_state": args.stock_gateway_state,
        "expected_factory_endpoint": args.factory_endpoint,
        "expected_paired_endpoint": args.paired_endpoint,
        "hardware_notes": args.hardware_notes,
        "antenna_notes": args.antenna_notes,
        "rf_transmit_authorized": False,
    }
    (trial_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    (trial_dir / "gateway-before.json").write_text(
        json.dumps(gateway_snapshot(args.gateway_url), indent=2, sort_keys=True)
        + "\n"
    )
    (trial_dir / "actions.jsonl").write_text(
        json.dumps(
            {
                "timestamp": started_at,
                "action": "trial_prepared",
                "detail": "No RF transmission was authorized by preparation.",
            },
            sort_keys=True,
        )
        + "\n"
    )
    print(trial_dir)
    return 0


def mark(args: argparse.Namespace) -> int:
    action_file = args.trial_directory / "actions.jsonl"
    if not action_file.is_file():
        raise ValueError(f"not a prepared trial: {args.trial_directory}")
    if args.duration_seconds is not None and args.duration_seconds <= 0:
        raise ValueError("duration must be positive")
    with action_file.open("a") as stream:
        row = {"timestamp": _now(), "action": args.action, "detail": args.detail}
        if args.zone is not None:
            row["zone"] = args.zone
        if args.duration_seconds is not None:
            row["duration_seconds"] = args.duration_seconds
        stream.write(json.dumps(row, sort_keys=True) + "\n")
    return 0


def finish(args: argparse.Namespace) -> int:
    trial_dir = args.trial_directory
    manifest_path = trial_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"not a prepared trial: {trial_dir}")
    manifest = json.loads(manifest_path.read_text())
    gateway_url = manifest["gateway_url"]
    events = fetch_events(gateway_url, int(manifest["event_cursor"]))
    finished_at = _now()
    started_local = datetime.fromisoformat(manifest["started_at"]).astimezone()
    finished_local = datetime.fromisoformat(finished_at).astimezone()
    (trial_dir / "gateway-events.json").write_text(
        json.dumps({"events": events}, indent=2, sort_keys=True) + "\n"
    )
    (trial_dir / "gateway-after.json").write_text(
        json.dumps(gateway_snapshot(gateway_url), indent=2, sort_keys=True) + "\n"
    )
    report = analyze_trial(
        manifest,
        events,
        _load_actions(trial_dir / "actions.jsonl"),
    )
    report.update(
        {
            "trial_id": manifest["trial_id"],
            "started_at": manifest["started_at"],
            "finished_at": finished_at,
            "ha_recorder_command": (
                "./tools/correlate_ha_recorder.sh "
                f"--start '{started_local:%Y-%m-%d %H:%M:%S}' "
                f"--end '{finished_local:%Y-%m-%d %H:%M:%S}'"
            ),
        }
    )
    (trial_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    preflight_parser = commands.add_parser("preflight")
    preflight_parser.add_argument("--gateway-url", required=True)
    preflight_parser.add_argument("--selected-node")
    preflight_parser.add_argument("--output", type=Path, default=Path("captures"))
    preflight_parser.add_argument("--minimum-free-gib", type=float, default=2.0)
    preflight_parser.add_argument("--save", type=Path)
    preflight_parser.set_defaults(handler=preflight)

    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("--trial-id", required=True)
    prepare_parser.add_argument(
        "--kind", required=True, choices=("sensor_pairing", "valve_pairing")
    )
    prepare_parser.add_argument("--gateway-url", required=True)
    prepare_parser.add_argument("--selected-node")
    prepare_parser.add_argument(
        "--stock-gateway-state",
        choices=("on", "off_unverified", "off_verified"),
        default="on",
    )
    prepare_parser.add_argument("--factory-endpoint")
    prepare_parser.add_argument("--paired-endpoint")
    prepare_parser.add_argument("--hardware-notes", default="")
    prepare_parser.add_argument("--antenna-notes", default="")
    prepare_parser.add_argument(
        "--output", type=Path, default=Path("captures/trials")
    )
    prepare_parser.set_defaults(handler=prepare)

    mark_parser = commands.add_parser("mark")
    mark_parser.add_argument("trial_directory", type=Path)
    mark_parser.add_argument("action")
    mark_parser.add_argument("--detail", default="")
    mark_parser.add_argument("--zone", type=int, choices=range(1, 5))
    mark_parser.add_argument("--duration-seconds", type=int)
    mark_parser.set_defaults(handler=mark)

    finish_parser = commands.add_parser("finish")
    finish_parser.add_argument("trial_directory", type=Path)
    finish_parser.set_defaults(handler=finish)

    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
