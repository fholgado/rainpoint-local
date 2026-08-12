#!/usr/bin/env python3
"""Run read-only acceptance checks against a RainPoint local radio node."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.request import urlopen


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fetch_snapshot(
    gateway_url: str,
    *,
    timeout: float = 10.0,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    """Fetch the three public API resources used by acceptance checks."""
    base = gateway_url.rstrip("/")
    result: dict[str, Any] = {}
    for name in ("info", "nodes", "receivers"):
        with opener(f"{base}/api/v1/{name}", timeout=timeout) as response:
            result[name] = json.load(response)
    result["captured_at"] = datetime.now(timezone.utc).isoformat()
    return result


def evaluate_node(
    snapshot: dict[str, Any],
    node_id: str,
    *,
    now: datetime | None = None,
    maximum_age_seconds: int = 120,
    minimum_free_heap_bytes: int = 100_000,
) -> dict[str, Any]:
    """Evaluate a node without mutating gateway or radio state."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    info = snapshot.get("info", {})
    nodes = snapshot.get("nodes", {}).get("nodes", [])
    receivers = snapshot.get("receivers", {}).get("receivers", [])
    node = next((item for item in nodes if item.get("node_id") == node_id), None)
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    check(
        "gateway_health",
        info.get("transport_healthy") is True,
        f"transport={info.get('transport')}, error={info.get('transport_error')}",
    )
    if node is None:
        check("node_present", False, f"{node_id} is absent from /nodes")
        return {
            "node_id": node_id,
            "passed": False,
            "checks": checks,
            "node": None,
            "coverage": [],
        }

    check("node_present", True, "managed node is listed")
    check("connected", node.get("connected") is True, str(node.get("connected")))
    check(
        "authenticated",
        node.get("authenticated") is True,
        str(node.get("authenticated")),
    )
    check("managed", node.get("managed") is True, str(node.get("managed")))
    check(
        "protocol_v2",
        int(node.get("protocol_version", 0)) >= 2,
        str(node.get("protocol_version")),
    )
    capabilities = set(node.get("capabilities") or [])
    check("receive_capability", "rx" in capabilities, ", ".join(sorted(capabilities)))
    check(
        "transmitter_disarmed",
        node.get("tx_armed") is False,
        f"tx_armed={node.get('tx_armed')}",
    )

    last_seen = _timestamp(node.get("last_seen"))
    age = (now - last_seen).total_seconds() if last_seen else None
    check(
        "fresh_heartbeat",
        age is not None and 0 <= age <= maximum_age_seconds,
        f"age_seconds={round(age, 1) if age is not None else 'unknown'}",
    )
    free_heap = node.get("free_heap_bytes")
    check(
        "free_heap",
        isinstance(free_heap, int) and free_heap >= minimum_free_heap_bytes,
        f"free_heap_bytes={free_heap}",
    )
    check(
        "wifi_connected",
        isinstance(node.get("ip_address"), str)
        and isinstance(node.get("wifi_rssi_dbm"), (int, float)),
        f"ip={node.get('ip_address')}, rssi_dbm={node.get('wifi_rssi_dbm')}",
    )
    radio_health = node.get("radio_health") or {}
    configured_radios = [
        radio
        for radio in radio_health.values()
        if isinstance(radio, dict) and radio.get("configuration_valid") is True
    ]
    check(
        "radio_configured",
        bool(configured_radios),
        f"valid_radios={len(configured_radios)}",
    )

    coverage = [
        item
        for item in receivers
        if item.get("receiver_id") == node_id and item.get("device_id") is not None
    ]
    accepted = sum(int(item.get("accepted_frame_count", 0)) for item in coverage)
    check(
        "accepted_rf_frames",
        accepted > 0,
        f"devices={len(coverage)}, accepted_frames={accepted}",
    )
    other_pairs = {
        item.get("device_id")
        for item in receivers
        if item.get("receiver_id") != node_id
        and item.get("device_id") is not None
        and int(item.get("accepted_frame_count", 0)) > 0
    }
    overlapping = sorted(
        item["device_id"]
        for item in coverage
        if int(item.get("accepted_frame_count", 0)) > 0
        and item.get("device_id") in other_pairs
    )
    check(
        "overlap_observed",
        bool(overlapping),
        ", ".join(overlapping) if overlapping else "no shared device yet",
    )

    return {
        "node_id": node_id,
        "passed": all(item["passed"] for item in checks),
        "checks": checks,
        "node": node,
        "coverage": coverage,
    }


def _print_text(report: dict[str, Any]) -> None:
    print(f"Radio node {report['node_id']}: {'PASS' if report['passed'] else 'FAIL'}")
    for item in report["checks"]:
        marker = "PASS" if item["passed"] else "FAIL"
        print(f"  [{marker}] {item['name']}: {item['detail']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--gateway-url", help="Gateway root, e.g. http://host:8787")
    source.add_argument("--snapshot", type=Path, help="Previously saved JSON snapshot")
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--maximum-age", type=int, default=120)
    parser.add_argument("--save", type=Path, help="Save the fetched snapshot as JSON")
    parser.add_argument("--json", action="store_true", help="Print machine-readable output")
    args = parser.parse_args()

    if args.snapshot:
        snapshot = json.loads(args.snapshot.read_text())
    else:
        snapshot = fetch_snapshot(args.gateway_url)
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")

    report = evaluate_node(
        snapshot,
        args.node_id,
        maximum_age_seconds=args.maximum_age,
    )
    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        _print_text(report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
