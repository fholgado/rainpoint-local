#!/usr/bin/env python3
"""Prepare and finish a persistent RainPoint sensor-fleet soak test."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.request import urlopen


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fetch_snapshot(
    gateway_url: str,
    *,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    base = gateway_url.rstrip("/")
    snapshot: dict[str, Any] = {"captured_at": _now().isoformat()}
    for resource in ("devices", "nodes", "receivers"):
        with opener(f"{base}/api/v1/{resource}", timeout=10) as response:
            snapshot[resource] = json.load(response)
    return snapshot


def _soil_sensors(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    devices = snapshot.get("devices", {}).get("devices", [])
    return {
        str(device["device_id"]): device
        for device in devices
        if device.get("state", {}).get("device_kind") == "soil_sensor"
    }


def evaluate(
    baseline: dict[str, Any],
    current: dict[str, Any],
    *,
    minimum_hours: float = 72,
    maximum_effective_interval_seconds: int = 1_800,
) -> dict[str, Any]:
    """Require every starting sensor to remain fresh and advance its cadence."""
    elapsed = (
        _timestamp(str(current["captured_at"]))
        - _timestamp(str(baseline["captured_at"]))
    ).total_seconds()
    starting = _soil_sensors(baseline)
    ending = _soil_sensors(current)
    minimum_reports = max(
        1, math.floor(max(0, elapsed) / maximum_effective_interval_seconds)
    )
    sensor_results = []
    for device_id, before in sorted(starting.items()):
        after = ending.get(device_id)
        before_count = int(before.get("report_count") or 0)
        after_count = int(after.get("report_count") or 0) if after else before_count
        delta = after_count - before_count
        checks = {
            "still_registered": after is not None,
            "reporting_now": after is not None and after.get("reporting") is True,
            "reports_advanced": delta >= minimum_reports,
        }
        sensor_results.append(
            {
                "device_id": device_id,
                "name": before.get("name"),
                "report_delta": delta,
                "minimum_report_delta": minimum_reports,
                "last_report_age_seconds": (
                    after.get("report_age_seconds") if after else None
                ),
                "checks": checks,
                "passed": all(checks.values()),
            }
        )

    nodes = current.get("nodes", {}).get("nodes", [])
    managed_nodes = [node for node in nodes if node.get("managed") is True]
    node_checks = {
        "all_managed_nodes_connected": bool(managed_nodes)
        and all(node.get("connected") is True for node in managed_nodes),
        "all_managed_nodes_authenticated": bool(managed_nodes)
        and all(node.get("authenticated") is True for node in managed_nodes),
        "ack_capacity_covers_starting_sensors": sum(
            int(node.get("routine_ack_assigned_sensors") or 0)
            for node in managed_nodes
        )
        >= len(starting),
    }
    duration_passed = elapsed >= minimum_hours * 3600
    return {
        "elapsed_hours": round(elapsed / 3600, 3),
        "minimum_hours": minimum_hours,
        "starting_sensor_count": len(starting),
        "duration_passed": duration_passed,
        "node_checks": node_checks,
        "sensors": sensor_results,
        "passed": (
            bool(starting)
            and duration_passed
            and all(node_checks.values())
            and all(sensor["passed"] for sensor in sensor_results)
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--gateway-url", required=True)
    prepare.add_argument("--output", type=Path, required=True)
    finish = commands.add_parser("finish")
    finish.add_argument("baseline", type=Path)
    finish.add_argument("--gateway-url", required=True)
    finish.add_argument("--minimum-hours", type=float, default=72)
    finish.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.command == "prepare":
        snapshot = fetch_snapshot(args.gateway_url)
        args.output.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
        print(args.output)
        return 0

    baseline = json.loads(args.baseline.read_text())
    report = evaluate(
        baseline,
        fetch_snapshot(args.gateway_url),
        minimum_hours=args.minimum_hours,
    )
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded)
    print(encoded, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
