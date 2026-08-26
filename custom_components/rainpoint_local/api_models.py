"""Typed, validated models at the rainpointd API boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class APIModelError(ValueError):
    """A gateway payload does not satisfy the advertised API contract."""


PAIRING_DEVICE_CATEGORIES = frozenset({"sensor", "valve"})


@dataclass(frozen=True)
class PairingProfileMetadata:
    """One gateway-advertised pairing profile suitable for HA presentation."""

    profile_id: str
    model: str
    device_category: str
    display_name: str
    required_node_capability: str
    automatic_discovery: bool
    user_pairing_supported: bool

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> PairingProfileMetadata:
        values = {
            key: payload.get(key)
            for key in (
                "profile_id",
                "model",
                "device_category",
                "display_name",
                "required_node_capability",
            )
        }
        if not all(isinstance(value, str) and value for value in values.values()):
            raise APIModelError("pairing profile identity metadata is incomplete")
        category = str(values["device_category"])
        if category not in PAIRING_DEVICE_CATEGORIES:
            raise APIModelError("pairing profile device category is unsupported")
        automatic = payload.get("automatic_discovery")
        supported = payload.get("user_pairing_supported")
        if not isinstance(automatic, bool) or not isinstance(supported, bool):
            raise APIModelError("pairing profile support flags must be booleans")
        return cls(
            profile_id=str(values["profile_id"]),
            model=str(values["model"]),
            device_category=category,
            display_name=str(values["display_name"]),
            required_node_capability=str(values["required_node_capability"]),
            automatic_discovery=automatic,
            user_pairing_supported=supported,
        )


def pairing_profiles(payload: dict[str, Any]) -> tuple[PairingProfileMetadata, ...]:
    """Validate the gateway's advertised model/category pairing catalog."""
    values = payload.get("supported_profiles")
    if not isinstance(values, list):
        raise APIModelError("supported_profiles response is not a list")
    profiles = tuple(
        PairingProfileMetadata.from_payload(item)
        for item in values
        if isinstance(item, dict)
    )
    if len(profiles) != len(values):
        raise APIModelError("supported_profiles contains a non-object")
    if len({profile.profile_id for profile in profiles}) != len(profiles):
        raise APIModelError("supported_profiles contains duplicate profile IDs")
    return profiles


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
        return "exchange_with_device"
    if stage in {
        "waiting_for_terminal_confirmation",
        "terminal_confirmation_processing",
        "paired_identity_observed",
    }:
        return "confirm_device"
    return "wait_for_device"
