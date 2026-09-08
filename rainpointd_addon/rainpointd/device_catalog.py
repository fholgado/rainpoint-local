"""Installation identity boundary for decoded RainPoint RF devices.

Protocol modules should describe frames and telemetry.  This catalog maps the
RF identities found in those frames to stable gateway device identities. Persisted
observations preserve established IDs across upgrades; new installations start
without a household catalog.
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

    def with_registries(
        self,
        sensor_registrations: Iterable[Mapping[str, Any]],
        valve_registrations: Iterable[Mapping[str, Any]],
    ) -> DeviceCatalog:
        """Overlay persistent sensor identities and valve RF links."""
        catalog = self.with_registry_sensors(sensor_registrations)
        valves = {valve.link: valve for valve in catalog.valves}
        for registration in valve_registrations:
            valve = ValveDefinition(
                controller_endpoint=str(registration["controller_endpoint"]),
                valve_endpoint=str(registration["valve_endpoint"]),
                device_id=str(registration["device_id"]),
                name=str(registration["name"]),
                model=str(registration.get("model") or "HTV405FRF"),
            )
            existing = valves.get(valve.link)
            if valve.model == HTV145_MODEL:
                # Registry fields use pairing roles. A new link has no prior
                # receive observation to preserve, so establish the reverse
                # command-link order explicitly. Retire superseded routes for
                # the same device instead of letting old traffic overwrite it.
                valves = {link: item for link, item in valves.items()
                          if item.device_id != valve.device_id or link == valve.link}
                if existing is None:
                    valve = ValveDefinition(
                        controller_endpoint=valve.valve_endpoint,
                        valve_endpoint=valve.controller_endpoint,
                        device_id=valve.device_id, name=valve.name, model=valve.model)
            if existing is not None:
                # HTV145 pairing roles and control-link order differ. Keep
                # the receive direction established by accepted telemetry.
                receive_link = existing if existing.model == HTV145_MODEL else valve
                valve = ValveDefinition(
                    controller_endpoint=receive_link.controller_endpoint,
                    valve_endpoint=receive_link.valve_endpoint,
                    device_id=existing.device_id,
                    name=valve.name,
                    model=valve.model,
                )
            valves[valve.link] = valve
        return DeviceCatalog(
            sensors=catalog.sensors,
            valves=tuple(valves.values()),
            hcs026_pairing_peers=catalog.hcs026_pairing_peers,
        )

    def with_observed_identities(self, events: Iterable[Mapping[str, Any]],
                                 suppressed: frozenset[str] = frozenset()) -> DeviceCatalog:
        """Recover stable identities from accepted persisted device snapshots.

        Explicit catalog entries win. Never infer a transmit profile or counter
        from these receive-side identities; those remain in the association store.
        """
        sensors = {sensor.endpoint: sensor for sensor in self.sensors}
        valves = {valve.link: valve for valve in self.valves}
        peers = set(self.hcs026_pairing_peers)
        device_ids = {device.device_id for device in (*self.sensors, *self.valves)}
        for event in events:
            state = event.get("state") or {}
            if (event.get("event_type") != "device_observation"
                    or state.get("rf_frame_accepted") is False
                    or (state.get("rf_trailer_valid") is False
                        and state.get("rf_frame_accepted") is not True)):
                continue
            device_id, name = event.get("device_id"), event.get("name")
            if not isinstance(device_id, str) or not isinstance(name, str):
                continue
            if device_id in device_ids:
                continue
            try:
                if is_hcs02x_sensor(model=event.get("model"), protocol=state.get("rf_protocol_family")):
                    if (state.get("rf_frame_accepted") is not True
                            and state.get("rf_trailer_valid") is not True
                            and state.get("rf_pairing_state") != "paired"):
                        continue
                    endpoint = _normalize_endpoint(str(state.get("rf_endpoint", "")))
                    if endpoint in suppressed:
                        continue
                    if endpoint in sensors:
                        continue
                    sensors.setdefault(endpoint, SensorDefinition(endpoint, device_id, name,
                        str(event["model"]), str(state.get("rf_protocol_family") or HCS02X_PROTOCOL)))
                    device_ids.add(device_id)
                    controller = str(state.get("rf_endpoint_a", ""))
                    if controller != endpoint and controller != "80000000":
                        peers.add(_normalize_endpoint(controller))
                elif event.get("model") in {"HTV145FRF", "HTV405FRF"}:
                    if state.get("rf_trailer_valid") is not True:
                        continue
                    endpoint_a = str(state.get("rf_endpoint_a", ""))
                    endpoint_b = str(state.get("rf_endpoint_b", ""))
                    # HTV145 accepted telemetry uses the reverse of its command
                    # link order. HTV405 reports retain the catalog link order.
                    controller, endpoint = ((endpoint_b, endpoint_a)
                        if event["model"] == HTV145_MODEL else (endpoint_a, endpoint_b))
                    valve = ValveDefinition(controller, endpoint, device_id, name, str(event["model"]))
                    if not valve.link.intersection(suppressed):
                        if valve.link not in valves:
                            valves[valve.link] = valve
                            device_ids.add(device_id)
            except (ValueError, KeyError):
                continue
        return DeviceCatalog(sensors=tuple(sensors.values()), valves=tuple(valves.values()),
                             hcs026_pairing_peers=frozenset(peers))

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


EMPTY_CATALOG = DeviceCatalog()
