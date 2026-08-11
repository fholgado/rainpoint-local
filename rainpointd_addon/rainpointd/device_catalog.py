"""Installation identity boundary for decoded RainPoint RF devices.

Protocol modules should describe frames and telemetry.  This catalog maps the
RF identities found in those frames to stable gateway device identities.  The
legacy profile below preserves the prototype installation while a persistent,
user-managed registry is introduced.
"""

from __future__ import annotations

from dataclasses import dataclass


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
    model: str = "HCS026FRF"

    def __post_init__(self) -> None:
        object.__setattr__(self, "endpoint", _normalize_endpoint(self.endpoint))


@dataclass(frozen=True)
class ValveDefinition:
    """One valve link known to an installation."""

    controller_endpoint: str
    valve_endpoint: str
    device_id: str
    name: str
    model: str = "HTV145FRF"

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
