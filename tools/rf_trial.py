#!/usr/bin/env python3
"""Prepare, mark, and finish evidence-complete RainPoint RF trials."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import urlopen


FRAME_BYTES = 38
SYNC = bytes.fromhex("79f4882f28")
STOCK_GATEWAY_ENDPOINT = bytes.fromhex("b42d008f")
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
    manifest: dict[str, Any], events: list[dict[str, Any]]
) -> dict[str, Any]:
    """Summarize captured routes and pairing-specific terminal evidence."""
    routes: Counter[str] = Counter()
    messages: Counter[str] = Counter()
    factory_count = 0
    paired_count = 0
    terminal_count = 0
    stock_gateway_count = 0
    factory = manifest.get("expected_factory_endpoint")
    paired = manifest.get("expected_paired_endpoint")
    factory_bytes = bytes.fromhex(factory) if factory else None
    paired_bytes = bytes.fromhex(paired) if paired else None

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
        messages[f"0x{message:02x}"] += 1
        if STOCK_GATEWAY_ENDPOINT in (source, destination):
            stock_gateway_count += 1
        if factory_bytes is not None and factory_bytes in (source, destination):
            factory_count += 1
        if paired_bytes is not None and paired_bytes in (source, destination):
            paired_count += 1
            if destination == paired_bytes and message == 3:
                terminal_count += 1

    stock_expected_silent = manifest.get("stock_gateway_state") == "off_verified"
    checks = {
        "captured_normalized_frames": normalized > 0,
        "factory_identity_observed": factory_bytes is None or factory_count > 0,
        "paired_identity_observed": paired_bytes is None or paired_count > 0,
        "terminal_message_03_observed": paired_bytes is None or terminal_count > 0,
        "known_stock_gateway_endpoint_silent": (
            not stock_expected_silent or stock_gateway_count == 0
        ),
    }
    return {
        "event_count": len(events),
        "normalized_frame_count": normalized,
        "route_counts": dict(routes.most_common()),
        "message_counts": dict(messages.most_common()),
        "factory_identity_frame_count": factory_count,
        "paired_identity_frame_count": paired_count,
        "terminal_message_03_count": terminal_count,
        "stock_gateway_frame_count": stock_gateway_count,
        "checks": checks,
        "passed": all(checks.values()),
    }


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
    with action_file.open("a") as stream:
        stream.write(
            json.dumps(
                {"timestamp": _now(), "action": args.action, "detail": args.detail},
                sort_keys=True,
            )
            + "\n"
        )
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
    report = analyze_trial(manifest, events)
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
    mark_parser.set_defaults(handler=mark)

    finish_parser = commands.add_parser("finish")
    finish_parser.add_argument("trial_directory", type=Path)
    finish_parser.set_defaults(handler=finish)

    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
