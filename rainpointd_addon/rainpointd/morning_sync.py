"""Local-calendar policy for bounded HTV405 maintenance; no RF transport."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_CONFIG = {
    "enabled": False,
    "start_time": "05:30",
    "timezone": "UTC",
    "window_minutes": 30,
}


def configuration(previous: dict, changes: dict) -> dict:
    """Validate a partial operator update without resetting other settings."""
    if set(changes) - set(DEFAULT_CONFIG):
        raise ValueError("unknown morning sync setting")
    result = {**DEFAULT_CONFIG, **previous, **changes}
    if not isinstance(result["enabled"], bool):
        raise ValueError("morning sync enabled must be boolean")
    if not isinstance(result["start_time"], str) or not re.fullmatch(
        r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", result["start_time"]
    ):
        raise ValueError("morning sync start_time must be HH:MM")
    minutes = result["window_minutes"]
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 15 <= minutes <= 120:
        raise ValueError("morning sync window must be 15-120 minutes")
    hour, minute = map(int, result["start_time"].split(":"))
    if hour * 60 + minute + minutes > 24 * 60:
        raise ValueError("morning sync window must end on the same local day")
    try:
        ZoneInfo(result["timezone"])
    except (ZoneInfoNotFoundError, TypeError, ValueError) as error:
        raise ValueError("morning sync requires an IANA timezone") from error
    return result


def service_window(config: dict, now: datetime) -> tuple[str, str, int]:
    """Return local date, window phase, and remaining real seconds.

    A service-date claim prevents the repeated DST hour from running twice.
    Nonexistent wall times are skipped unless a later real instant is still
    inside the configured window. No missed-window catch-up is authorized.
    """
    if now.tzinfo is None:
        raise ValueError("morning sync requires an aware clock")
    local = now.astimezone(ZoneInfo(config["timezone"]))
    hour, minute = map(int, config["start_time"].split(":"))
    start_minute = hour * 60 + minute
    end_minute = start_minute + config["window_minutes"]
    wall_seconds = local.hour * 3600 + local.minute * 60 + local.second
    phase = (
        "before" if wall_seconds < start_minute * 60
        else "inside" if wall_seconds < end_minute * 60
        else "after"
    )
    # Use actual instants across a DST change and cap the node-side wait
    # at two hours.
    remaining = 0
    if phase == "inside":
        end = local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=end_minute)
        remaining = max(0, min(7200, int(end.timestamp() - now.timestamp())))
    return local.date().isoformat(), phase, remaining


def association_key(registration: dict) -> str:
    """Bind readiness to the actual association, owner and RF profile."""
    fields = (
        "valve_endpoint", "controller_endpoint", "accepted_at",
        "control_node_id", "control_companion_endpoint", "control_selector",
        "control_frequency_offset_hz",
    )
    value = json.dumps([registration.get(key) for key in fields], separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()
