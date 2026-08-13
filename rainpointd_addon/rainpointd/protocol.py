"""Transport-neutral RainPoint RF protocol boundary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .device_catalog import DeviceCatalog
from .rf import normalize_row


@dataclass(frozen=True)
class RFObservation:
    """One decoded RF frame plus transport-independent receiver evidence."""

    decoded: dict[str, Any]
    observed_at: str | None
    metadata: dict[str, Any]


def _receiver_metadata(
    event: dict[str, Any], receiver_id: str | None
) -> dict[str, Any]:
    metadata = event.get("bridge_metadata")
    source = metadata if isinstance(metadata, dict) else {}
    result: dict[str, Any] = {}
    for source_key, state_key, expected_type in (
        ("radio", "rf_radio", str),
        ("channel", "rf_channel", int),
        ("lqi", "rf_lqi", int),
        ("frequency_offset_hz", "rf_frequency_offset_hz", int),
        ("node_id", "rf_node_id", str),
    ):
        value = source.get(source_key)
        if isinstance(value, expected_type) and not isinstance(value, bool):
            result[state_key] = value
    source_node_id = source.get("node_id")
    if isinstance(source_node_id, str):
        result["rf_receiver_id"] = source_node_id
    if receiver_id is not None:
        result.setdefault("rf_receiver_id", receiver_id)
    rssi = event.get("rssi")
    if isinstance(rssi, (int, float)) and not isinstance(rssi, bool):
        result["rf_rssi_db"] = rssi
    return result


def decode_receiver_event(
    event: dict[str, Any],
    *,
    catalog: DeviceCatalog,
    receiver_id: str | None = None,
) -> list[RFObservation]:
    """Decode the common event envelope emitted by every radio transport."""
    rows = event.get("rows")
    if not isinstance(rows, list):
        return []
    observed_at = event.get("time")
    if not isinstance(observed_at, str):
        observed_at = None
    metadata = _receiver_metadata(event, receiver_id)
    observations: list[RFObservation] = []
    for row in rows:
        try:
            decoded = normalize_row(row, catalog=catalog)
        except (KeyError, TypeError, ValueError):
            continue
        observations.append(
            RFObservation(decoded, observed_at, dict(metadata))
        )
    return observations


def decode_receiver_line(
    line: str,
    *,
    catalog: DeviceCatalog,
    receiver_id: str | None = None,
) -> list[RFObservation]:
    """Decode one JSON-line receiver envelope without gateway dependencies."""
    try:
        event = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(event, dict):
        return []
    return decode_receiver_event(
        event, catalog=catalog, receiver_id=receiver_id
    )
