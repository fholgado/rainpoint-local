"""Typed, validated models at the rainpointd API boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class APIModelError(ValueError):
    """A gateway payload does not satisfy the advertised API contract."""


PAIRING_DEVICE_CATEGORIES = frozenset({"sensor", "valve"})


def multi_zone_numbers(device: dict[str, Any]) -> tuple[int, ...]:
    """Only the identified four-outlet model has separate zone entities."""
    return (1, 2, 3, 4) if device.get("model") == "HTV405FRF" else ()


def unsupported_device_entity_ids(device_id: str, device: dict[str, Any]) -> set[str]:
    """Exact obsolete IDs, preserving the single valve's overall watering entity."""
    if device.get("model") == "HTV405FRF":
        return {f"{device_id}_last_usage"}
    if device.get("model") == "HTV145FRF":
        return {
            f"{device_id}_zone_{zone}_{suffix}"
            for zone in range(1, 5)
            for suffix in ("watering", "duration", "control")
        }
    return set()


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
    if pairing_is_finalizing(payload):
        return "finalize_pairing"
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


def pairing_is_finalizing(payload: dict[str, Any]) -> bool:
    """Keep accepted enrollment separate from readiness of its selected radio."""
    if pairing_completed_endpoint(payload) is None:
        return False
    selected = payload.get("selected_node_id")
    if not selected:  # Compatibility with gateways preceding node selection.
        return False
    nodes = payload.get("pairing_nodes", [])
    if not isinstance(selected, str) or not isinstance(nodes, list):
        raise APIModelError("invalid selected pairing radio")
    node = next((node for node in nodes
                 if isinstance(node, dict) and node.get("node_id") == selected), None)
    return (node is None or node.get("tx_armed") is not False
            or node.get("node_reboot_pending") is True)


def validate_event_page(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Validate a durable event page before advancing the consumer cursor."""
    events = payload.get("events")
    cursor = payload.get("next_since")
    if not isinstance(events, list) or type(cursor) is not int or cursor < 0:
        raise APIModelError("invalid events response")
    previous = -1
    for event in events:
        if not isinstance(event, dict):
            raise APIModelError("invalid event")
        event_id = event.get("event_id")
        if type(event_id) is not int or event_id <= previous or event_id > cursor:
            raise APIModelError("invalid event ordering")
        previous = event_id
    return events, cursor


def events_require_refresh(events: list[dict[str, Any]]) -> bool:
    """Reconcile unknown/state events promptly; batch raw RF metrics on fallback."""
    return any(event.get("event_type") not in {"rf_frame", "receiver_duplicate"}
               for event in events)


def apply_sensor_event_page(devices: dict[str, dict], events: list[dict]) -> dict[str, dict] | None:
    """Apply known sensor observations; require snapshots for control/topology changes."""
    result = dict(devices)
    changed = False
    for event in events:
        if event.get("event_type") in {"rf_frame", "receiver_duplicate"}:
            continue
        device_id = event.get("device_id")
        previous = result.get(device_id)
        state = event.get("state")
        if (event.get("event_type") != "device_observation" or previous is None
                or previous.get("model") not in {"HCS026FRF", "HCS02x-compatible soil sensor"}
                or event.get("model") != previous.get("model")
                or not isinstance(state, dict) or not isinstance(event.get("observed_at"), str)):
            return None
        if int(event["event_id"]) <= int(previous.get("last_event_id") or 0):
            continue
        result[device_id] = {**previous, "state": {**previous.get("state", {}), **state},
                            "observed_at": event["observed_at"], "last_event_id": event["event_id"],
                            "available": True, "reporting": True, "report_age_seconds": 0}
        changed = True
    return result if changed else devices
