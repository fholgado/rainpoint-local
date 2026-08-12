"""Installation identity boundary for decoded RainPoint RF devices.

Protocol modules should describe frames and telemetry.  This catalog maps the
RF identities found in those frames to stable gateway device identities.  The
legacy profile below preserves the prototype installation while a persistent,
user-managed registry is introduced.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .product_identity import (
    HCS026_MODEL,
    HCS02X_PROTOCOL,
    HTV145_MODEL,
    is_hcs02x_sensor,
)


def _normalize_endpoint(value: str) -> str:
    """Return one normalized four-byte RF endpoint."""
    endpoint = value.lower()
    if len(endpoint) != 8:
        raise ValueError("RF endpoint must contain exactly four bytes")
    try:
        bytes.fromhex(endpoint)
    except ValueError as exc:
        raise ValueError("RF endpoint must be hexadecimal") from exc
    return endpoint


@dataclass(frozen=True)
class SensorDefinition:
    """One soil sensor known to an installation."""

    endpoint: str
    device_id: str
    name: str
    model: str = HCS026_MODEL
    protocol: str = HCS02X_PROTOCOL

    def __post_init__(self) -> None:
        object.__setattr__(self, "endpoint", _normalize_endpoint(self.endpoint))


@dataclass(frozen=True)
class ValveDefinition:
    """One valve link known to an installation."""

    controller_endpoint: str
    valve_endpoint: str
    device_id: str
    name: str
    model: str = HTV145_MODEL

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "controller_endpoint",
            _normalize_endpoint(self.controller_endpoint),
        )
        object.__setattr__(
            self,
            "valve_endpoint",
            _normalize_endpoint(self.valve_endpoint),
        )
        if self.controller_endpoint == self.valve_endpoint:
            raise ValueError("valve link endpoints must be distinct")

    @property
    def link(self) -> frozenset[str]:
        """Return the direction-independent endpoints for this RF link."""
        return frozenset((self.controller_endpoint, self.valve_endpoint))


class DeviceCatalog:
    """Resolve installation devices without coupling them to RF decoding."""

    def __init__(
        self,
        *,
        sensors: tuple[SensorDefinition, ...] = (),
        valves: tuple[ValveDefinition, ...] = (),
        hcs026_pairing_peers: frozenset[str] = frozenset(),
    ) -> None:
        self.sensors = sensors
        self.valves = valves
        self.hcs026_pairing_peers = frozenset(
            _normalize_endpoint(endpoint) for endpoint in hcs026_pairing_peers
        )
        self._sensors_by_endpoint = {
            sensor.endpoint.lower(): sensor for sensor in sensors
        }
        self._valves_by_link = {valve.link: valve for valve in valves}
        if len(self._sensors_by_endpoint) != len(sensors):
            raise ValueError("sensor endpoints must be unique")
        if len(self._valves_by_link) != len(valves):
            raise ValueError("valve endpoint links must be unique")
        device_ids = [device.device_id for device in (*sensors, *valves)]
        if len(set(device_ids)) != len(device_ids):
            raise ValueError("device IDs must be unique")

    @property
    def sensor_endpoints(self) -> frozenset[str]:
        """Return RF endpoints currently established as soil sensors."""
        return frozenset(self._sensors_by_endpoint)

    def sensor(self, endpoint: str) -> SensorDefinition | None:
        """Resolve a soil sensor by its canonical RF endpoint."""
        return self._sensors_by_endpoint.get(endpoint.lower())

    def valve_link(
        self, endpoint_a: str, endpoint_b: str
    ) -> ValveDefinition | None:
        """Resolve a valve by either direction of its RF link."""
        return self._valves_by_link.get(
            frozenset((endpoint_a.lower(), endpoint_b.lower()))
        )

    def with_registry_sensors(
        self, registrations: Iterable[Mapping[str, Any]]
    ) -> DeviceCatalog:
        """Overlay accepted sensor metadata without changing legacy IDs.

        A known compatibility endpoint retains its stable device ID so an
        upgrade cannot fork an existing Home Assistant device. Registry names
        and models take precedence, while new endpoints use their persisted
        registry identity.
        """
        sensors = {sensor.endpoint: sensor for sensor in self.sensors}
        for registration in registrations:
            if not is_hcs02x_sensor(
                model=str(registration.get("model", "")),
                protocol=registration.get("protocol"),
            ):
                continue
            endpoint = _normalize_endpoint(str(registration["endpoint"]))
            existing = sensors.get(endpoint)
            sensors[endpoint] = SensorDefinition(
                endpoint=endpoint,
                device_id=(
                    existing.device_id
                    if existing is not None
                    else str(registration["device_id"])
                ),
                name=str(registration["name"]),
                model=str(registration["model"]),
                protocol=str(
                    registration.get("protocol") or HCS02X_PROTOCOL
                ),
            )
        return DeviceCatalog(
            sensors=tuple(sensors.values()),
            valves=self.valves,
            hcs026_pairing_peers=self.hcs026_pairing_peers,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> DeviceCatalog:
        """Build an installation catalog from a transport-neutral mapping."""
        sensors = tuple(
            SensorDefinition(
                endpoint=str(item["endpoint"]),
                device_id=str(item["device_id"]),
                name=str(item["name"]),
                model=str(item.get("model", HCS026_MODEL)),
                protocol=str(item.get("protocol", HCS02X_PROTOCOL)),
            )
            for item in value.get("sensors", ())
        )
        valves = tuple(
            ValveDefinition(
                controller_endpoint=str(item["controller_endpoint"]),
                valve_endpoint=str(item["valve_endpoint"]),
                device_id=str(item["device_id"]),
                name=str(item["name"]),
                model=str(item.get("model", HTV145_MODEL)),
            )
            for item in value.get("valves", ())
        )
        peers = frozenset(
            str(item) for item in value.get("hcs026_pairing_peers", ())
        )
        return cls(
            sensors=sensors,
            valves=valves,
            hcs026_pairing_peers=peers,
        )


def load_catalog(path: str | Path) -> DeviceCatalog:
    """Load one installation catalog without importing household code."""
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("device catalog must be a JSON object")
    return DeviceCatalog.from_mapping(value)


# This is a compatibility profile, not a protocol truth.  It intentionally
# keeps the existing Home Assistant device IDs stable during generalization.
LEGACY_HOME_CATALOG = DeviceCatalog(
    sensors=(
        SensorDefinition("c4e50024", "soil-left-bed", "Left Bed"),
        SensorDefinition("ce628024", "soil-front-1", "Front Yard Sensor 1"),
        SensorDefinition("d1e28024", "soil-front-2", "Front Yard Sensor 2"),
        SensorDefinition("9ce58024", "soil-right-bed", "Right Bed"),
    ),
    valves=(
        ValveDefinition(
            "b42d008f",
            "b9840280",
            "valve-1",
            "Garden Valve",
        ),
    ),
    hcs026_pairing_peers=frozenset(("b9840280",)),
)
