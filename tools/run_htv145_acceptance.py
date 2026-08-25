#!/usr/bin/env python3
"""Preflight and run one auditable HTV145 dry-valve acceptance trial."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "rainpointd_addon"))
sys.path.insert(0, str(TOOLS))

from analyze_rainpoint_events import event_frame, fetch_events  # noqa: E402
from rainpointd.valve_protocol import (  # noqa: E402
    ValveLink,
    decode_htv145_command_response,
    decode_htv145_gateway_command,
    decode_htv145_state_report,
    decode_htv145_terminal_idle_report,
)


# Preserve the exact CC1101 register-derived base before rounding the selected
# channel. Rounding the base first puts channel 11 one hertz low.
RAINPOINT_BASE_CENTER_HZ = 0x10A8C3 * 26_000_000 / 65_536
RAINPOINT_CHANNEL_SPACING_HZ = 99_975.5859375
SUPPORTED_CHANNELS = {0, 11}
MAXIMUM_EXPLICIT_CENTER_ERROR_HZ = 25_000


def _observed_utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if observed.tzinfo is None:
        observed = observed.astimezone()
    return observed.astimezone(timezone.utc)


def _post_json(
    base_url: str,
    path: str,
    payload: dict[str, Any],
    *,
    token: str,
) -> dict[str, Any]:
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise ValueError("gateway returned a non-object response")
    return result


def _preflight(
    events: list[dict[str, Any]],
    *,
    link: ValveLink,
    isolation_seconds: int,
    maximum_command_age_seconds: int,
    maximum_idle_age_seconds: int,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    commands: list[tuple[dict[str, Any], bytes, dict[str, Any]]] = []
    latest_idle: tuple[dict[str, Any], bytes, dict[str, Any]] | None = None
    latest_battery: tuple[dict[str, Any], bool] | None = None
    latest_controller_frame_at: datetime | None = None
    decoded_events: list[tuple[dict[str, Any], bytes, datetime]] = []
    for event in events:
        frame = event_frame(event)
        if frame is None:
            continue
        observed = _observed_utc(event.get("observed_at"))
        if observed is None:
            continue
        decoded_events.append((event, frame, observed))
        if (
            frame[5:9] == link.controller_endpoint
            and frame[9:13] == link.valve_endpoint
            and (
                latest_controller_frame_at is None
                or observed > latest_controller_frame_at
            )
        ):
            latest_controller_frame_at = observed
        command = decode_htv145_gateway_command(frame, link)
        if command is not None:
            commands.append((event, frame, command))
        report = decode_htv145_state_report(frame, link)
        if report is None:
            report = decode_htv145_terminal_idle_report(frame, link)
        if report is not None and report["watering"] is False:
            latest_idle = (event, frame, report)
        battery_low = (event.get("state") or {}).get("battery_low")
        if (
            frame[5:9] == link.valve_endpoint
            and frame[9:13] == link.controller_endpoint
            and isinstance(battery_low, bool)
        ):
            latest_battery = (event, battery_low)

    latest_command: tuple[dict[str, Any], bytes, dict[str, Any]] | None = None
    for candidate in reversed(commands):
        candidate_at = _observed_utc(candidate[0].get("observed_at"))
        if candidate_at is None:
            continue
        expected_watering = bool(candidate[2]["watering"])
        sequence = int(candidate[2]["sequence"])
        for _event, frame, observed in decoded_events:
            latency = (observed - candidate_at).total_seconds()
            if latency < 0:
                continue
            if latency > 15:
                break
            response = decode_htv145_command_response(frame, link)
            if response is not None and (
                int(response["sequence"]) == sequence
                and bool(response["watering"]) == expected_watering
            ):
                latest_command = candidate
                break
            report = decode_htv145_state_report(frame, link)
            if report is not None and bool(report["watering"]) == expected_watering:
                latest_command = candidate
                break
        if latest_command is not None:
            break
    if latest_command is None:
        raise RuntimeError(
            "no positively confirmed passive HTV145 command establishes the counter"
        )
    if latest_idle is None:
        raise RuntimeError("no retained valve-originated HTV145 idle evidence")
    if latest_battery is None:
        raise RuntimeError("no confirmed HTV145 battery state is available")
    if latest_battery[1]:
        raise RuntimeError(
            "HTV145 battery is confirmed low; replace it before control acceptance"
        )
    command_at = _observed_utc(latest_command[0].get("observed_at"))
    idle_at = _observed_utc(latest_idle[0].get("observed_at"))
    if command_at is None or idle_at is None:
        raise RuntimeError("retained HTV145 evidence has invalid timestamps")
    command_age = (now - command_at).total_seconds()
    idle_age = (now - idle_at).total_seconds()
    controller_silence = (
        (now - latest_controller_frame_at).total_seconds()
        if latest_controller_frame_at is not None
        else float("inf")
    )
    if not 0 <= command_age <= maximum_command_age_seconds:
        raise RuntimeError("passive HTV145 command evidence is too old")
    if not 0 <= idle_age <= maximum_idle_age_seconds:
        raise RuntimeError("HTV145 valve is not freshly confirmed idle")
    if controller_silence < isolation_seconds:
        raise RuntimeError("stock-controller RF was observed inside the isolation window")
    command_state = latest_command[0].get("state") or {}
    channel = command_state.get("rf_channel")
    if not isinstance(channel, int) or channel not in SUPPORTED_CHANNELS:
        raise RuntimeError("confirmed HTV145 command lacks supported RF channel evidence")
    command_center_hz = round(
        RAINPOINT_BASE_CENTER_HZ + channel * RAINPOINT_CHANNEL_SPACING_HZ
    )
    return {
        "checked_at": now.isoformat(),
        "event_cursor": max(
            (int(event.get("event_id", 0)) for event in events), default=0
        ),
        "latest_passive_command_event_id": latest_command[0].get("event_id"),
        "latest_passive_command_observed_at": command_at.isoformat(),
        "latest_passive_command_sequence": latest_command[2]["sequence"],
        "next_command_sequence": latest_command[2]["next_sequence"],
        "command_rf_channel": channel,
        "command_center_hz": command_center_hz,
        "battery_low": latest_battery[1],
        "battery_observed_at": latest_battery[0].get("observed_at"),
        "latest_idle_event_id": latest_idle[0].get("event_id"),
        "latest_idle_observed_at": idle_at.isoformat(),
        "stock_controller_silence_seconds": round(controller_silence, 3),
        "passive_command_frame": latest_command[1].hex(),
        "idle_frame": latest_idle[1].hex(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway-url", required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--controller-endpoint", required=True)
    parser.add_argument("--valve-endpoint", required=True)
    parser.add_argument("--center-hz", type=int)
    parser.add_argument("--power-dbm", type=int, default=10)
    parser.add_argument("--invert", action="store_true")
    parser.add_argument(
        "--trailer-residual", type=lambda value: int(value, 0), default=0xC713
    )
    parser.add_argument("--duration-seconds", type=int, default=60)
    parser.add_argument("--isolation-seconds", type=int, default=600)
    parser.add_argument("--maximum-command-age-seconds", type=int, default=86_400)
    parser.add_argument("--maximum-idle-age-seconds", type=int, default=1_800)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-grace-seconds", type=int, default=90)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="perform the one bounded open after preflight; omitted is read-only",
    )
    args = parser.parse_args()
    if args.duration_seconds < 60 or args.duration_seconds > 3_600:
        parser.error("duration must be between 60 and 3600 seconds")
    if args.duration_seconds % 60:
        parser.error("duration must use whole minutes")

    token = os.environ.get("RAINPOINT_REGISTRY_TOKEN")
    if args.execute and not token:
        parser.error("RAINPOINT_REGISTRY_TOKEN is required with --execute")
    link = ValveLink(
        bytes.fromhex(args.controller_endpoint),
        bytes.fromhex(args.valve_endpoint),
    )
    events_url = f"{args.gateway_url.rstrip('/')}/api/v1/events"
    events = fetch_events(events_url)
    preflight = _preflight(
        events,
        link=link,
        isolation_seconds=args.isolation_seconds,
        maximum_command_age_seconds=args.maximum_command_age_seconds,
        maximum_idle_age_seconds=args.maximum_idle_age_seconds,
    )
    center_hz = int(preflight["command_center_hz"])
    if args.center_hz is not None:
        if abs(args.center_hz - center_hz) > MAXIMUM_EXPLICIT_CENTER_ERROR_HZ:
            raise RuntimeError(
                "explicit HTV145 center does not match retained RF channel evidence"
            )
        center_hz = args.center_hz
    result: dict[str, Any] = {
        "schema_version": 1,
        "trial": "htv145_dry_valve_automatic_stop",
        "preflight": preflight,
        "executed": args.execute,
    }
    if args.execute:
        assert token is not None
        prepare = _post_json(
            args.gateway_url,
            "/api/v1/research/htv145-acceptance/prepare",
            {
                "node_id": args.node_id,
                "controller_endpoint": args.controller_endpoint,
                "valve_endpoint": args.valve_endpoint,
                "center_hz": center_hz,
                "power_dbm": args.power_dbm,
                "invert": args.invert,
                "trailer_residual": args.trailer_residual,
                "idle_frame": preflight["idle_frame"],
                "passive_command_frame": preflight["passive_command_frame"],
                "idle_observed_at": preflight["latest_idle_observed_at"],
                "passive_command_observed_at": (
                    preflight["latest_passive_command_observed_at"]
                ),
            },
            token=token,
        )
        opened = _post_json(
            args.gateway_url,
            "/api/v1/research/htv145-acceptance/open",
            {"duration_seconds": args.duration_seconds},
            token=token,
        )
        deadline = time.monotonic() + args.duration_seconds + args.timeout_grace_seconds
        status: dict[str, Any] = {}
        while time.monotonic() < deadline:
            status = _post_json(
                args.gateway_url,
                "/api/v1/research/htv145-acceptance/status",
                {},
                token=token,
            )
            if status.get("passed") is True:
                break
            coordinator = status.get("coordinator") or {}
            last_result = str(coordinator.get("last_result", ""))
            if (
                coordinator.get("counter_synchronized") is False
                and last_result not in {
                    "profile_configured_counter_required",
                    "counter_synchronized",
                    "reserved_not_confirmed",
                }
            ):
                break
            time.sleep(max(0.2, args.poll_seconds))
        result.update({"prepare": prepare, "open": opened, "final": status})
    content = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(content, encoding="utf-8")
    print(content, end="")
    return 0 if not args.execute or result.get("final", {}).get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
