"""Typed, validated models at the rainpointd API boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class APIModelError(ValueError):
    """A gateway payload does not satisfy the advertised API contract."""


@dataclass(frozen=True)
class GatewayMetadata:
    """Stable gateway identity, compatibility, and optional capabilities."""

    api_version: str
    gateway_id: str
    capabilities: frozenset[str]
    latest_event_id: int

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> GatewayMetadata:
        api_version = payload.get("api_version")
        gateway_id = payload.get("gateway_id")
        capabilities = payload.get("capabilities", [])
        latest_event_id = payload.get("latest_event_id", 0)
        if not isinstance(api_version, str) or not api_version:
            raise APIModelError("gateway api_version is missing")
        if not isinstance(gateway_id, str) or not gateway_id:
            raise APIModelError("gateway_id is missing")
        if not isinstance(capabilities, list) or not all(
            isinstance(item, str) for item in capabilities
        ):
            raise APIModelError("gateway capabilities must be strings")
        if not isinstance(latest_event_id, int) or latest_event_id < 0:
            raise APIModelError("latest_event_id must be a non-negative integer")
        return cls(
            api_version=api_version,
            gateway_id=gateway_id,
            capabilities=frozenset(capabilities),
            latest_event_id=latest_event_id,
        )


def validate_object_list(
    payload: dict[str, Any], key: str, identity_key: str
) -> list[dict[str, Any]]:
    """Validate an API collection and its stable identity field."""
    values = payload.get(key)
    if not isinstance(values, list):
        raise APIModelError(f"{key} response is not a list")
    if not all(
        isinstance(item, dict)
        and isinstance(item.get(identity_key), str)
        and bool(item[identity_key])
        for item in values
    ):
        raise APIModelError(f"{key} contains an invalid {identity_key}")
    return values


def pairing_completed_endpoint(payload: dict[str, Any]) -> str | None:
    """Return a validated endpoint for new enrollment or sensor recovery."""
    endpoint = payload.get("completed_endpoint")
    if endpoint is None:
        records = payload.get("new_records")
        if isinstance(records, list) and records and isinstance(records[0], dict):
            endpoint = records[0].get("paired_endpoint")
    if endpoint is None:
        return None
    if not isinstance(endpoint, str):
        raise APIModelError("pairing completion endpoint is not a string")
    normalized = endpoint.strip().lower()
    if len(normalized) != 8 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise APIModelError("pairing completion endpoint is invalid")
    return normalized


def pairing_progress_action(payload: dict[str, Any]) -> str:
    """Map gateway pairing stages to concise Home Assistant progress text."""
    stage = payload.get("stage")
    if stage in {
        "factory_detected_transmitter_required",
        "pairing_exchange_in_progress",
    }:
        return "exchange_with_sensor"
    if stage in {
        "waiting_for_terminal_confirmation",
        "terminal_confirmation_processing",
        "paired_identity_observed",
    }:
        return "confirm_sensor"
    return "wait_for_sensor"
