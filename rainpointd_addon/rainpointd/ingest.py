"""Transport-neutral ingestion of normalized RainPoint RF observations."""

from __future__ import annotations

from typing import Any

from .device_catalog import DeviceCatalog
from .gateway import Gateway
from .product_identity import hcs02x_identity
from .protocol import RFObservation, decode_receiver_event, decode_receiver_line


class FrameIngestor:
    """Map normalized RF rows into gateway devices and events."""

    def __init__(
        self,
        gateway: Gateway,
        *,
        catalog: DeviceCatalog | None = None,
        receiver_id: str | None = None,
    ) -> None:
        self.gateway = gateway
        self._catalog_override = catalog
        self.receiver_id = receiver_id
        self._valve_states: dict[str, dict[str, Any]] = {
            valve.device_id: self._empty_valve_state()
            for valve in self.catalog.valves
        }

    @property
    def catalog(self) -> DeviceCatalog:
        """Return the current registry-backed catalog unless explicitly fixed."""
        return self._catalog_override or self.gateway.catalog

    @staticmethod
    def _empty_valve_state() -> dict[str, Any]:
        return {
            "valve_state": None,
            "is_watering": None,
            "duration_seconds": None,
            "last_usage_liters": None,
        }

    def seed(self) -> None:
        """Register catalogued devices before their first periodic packet."""
        for valve in self.catalog.valves:
            self.gateway.register(
                device_id=valve.device_id,
                name=valve.name,
                model=valve.model,
                state=self._valve_states[valve.device_id],
            )
        for sensor in self.catalog.sensors:
            self.gateway.register(
                device_id=sensor.device_id,
                name=sensor.name,
                model=sensor.model,
                state={
                    "rf_endpoint": sensor.endpoint,
                    "soil_moisture_percent": None,
                },
            )

    def consume_line(self, line: str) -> int:
        """Consume one JSON event line from any compatible radio adapter."""
        return self._consume_observations(
            decode_receiver_line(
                line, catalog=self.catalog, receiver_id=self.receiver_id
            )
        )

    def consume_event(self, event: dict[str, Any]) -> int:
        """Consume one normalized receiver event."""
        return self._consume_observations(
            decode_receiver_event(
                event, catalog=self.catalog, receiver_id=self.receiver_id
            )
        )

    def _consume_observations(
        self, observations: list[RFObservation]
    ) -> int:
        """Publish protocol observations into gateway state."""
        published = 0
        for observation in observations:
            decoded = observation.decoded
            observed_at = observation.observed_at
            receiver_metadata = observation.metadata
            moisture = decoded.get("soil_moisture_percent")
            valve = self.catalog.valve_link(
                decoded["endpoint_a"], decoded["endpoint_b"]
            )
            valve_update = {
                key: decoded[key]
                for key in (
                    "valve_state",
                    "is_watering",
                    "duration_seconds",
                    "last_usage_liters",
                )
                if key in decoded
            }
            if valve_update:
                if valve is None:
                    continue
                valve_state = self._valve_states.setdefault(
                    valve.device_id, self._empty_valve_state()
                )
                state = {
                    "model": valve.model,
                    "raw": decoded["frame_hex"],
                    "rf_endpoint_a": decoded["endpoint_a"],
                    "rf_endpoint_b": decoded["endpoint_b"],
                    "rf_trailer_residual": decoded["trailer_residual"],
                    "rf_trailer_valid": decoded["trailer_valid"],
                    "rf_frame_accepted": True,
                    **valve_state,
                    **valve_update,
                }
                state.update(receiver_metadata)
                valve_state.update(valve_update)
                self.gateway.observe_decoded(
                    device_id=valve.device_id,
                    name=valve.name,
                    model=valve.model,
                    frame=decoded["frame_hex"],
                    state=state,
                    observed_at=observed_at,
                )
                published += 1
                continue
            if moisture is None:
                state: dict[str, Any] = {
                    "raw": decoded["frame_hex"],
                    "rf_endpoint_a": decoded["endpoint_a"],
                    "rf_endpoint_b": decoded["endpoint_b"],
                    "rf_message_type": decoded["message_type"],
                    "rf_frame_accepted": decoded["trailer_valid"],
                }
                for key in ("trailer_residual", "trailer_valid"):
                    state[f"rf_{key}"] = decoded[key]
                for key in (
                    "status_soil_moisture_percent",
                    "hub_rssi_db",
                    "battery_endpoint",
                    "battery_status_candidate",
                    "battery_percent_candidate",
                    "hcs026_factory_endpoint",
                    "hcs026_paired_endpoint",
                    "hcs026_pairing_state",
                ):
                    if key in decoded:
                        state[key] = decoded[key]
                if any(
                    key in decoded
                    for key in (
                        "hcs026_factory_endpoint",
                        "hcs026_paired_endpoint",
                    )
                ):
                    state.update(hcs02x_identity(decoded).state_fields())
                state.update(receiver_metadata)
                self.gateway.observe_rf_frame(
                    frame=decoded["frame_hex"],
                    state=state,
                    observed_at=observed_at,
                    device_id=valve.device_id if valve else None,
                )
                published += 1
                continue

            endpoint = decoded.get("canonical_endpoint_b", decoded["endpoint_b"])
            sensor = self.catalog.sensor(endpoint)
            device_id = sensor.device_id if sensor else f"hcs026-{endpoint}"
            name = sensor.name if sensor else f"RainPoint soil sensor {endpoint}"
            identity = hcs02x_identity(
                decoded,
                trusted_model=sensor.model if sensor is not None else None,
            )
            frame_accepted = bool(
                decoded["trailer_valid"] or "product_code" in decoded
            )
            state = {
                "model": identity.model,
                "raw": decoded["frame_hex"],
                "rf_endpoint": endpoint,
                "rf_endpoint_a": decoded["endpoint_a"],
                "rf_endpoint_b": decoded["endpoint_b"],
                "rf_message_type": decoded["message_type"],
                "rf_trailer_residual": decoded["trailer_residual"],
                "rf_trailer_valid": decoded["trailer_valid"],
                "rf_frame_accepted": frame_accepted,
                "soil_moisture_percent": moisture,
                **identity.state_fields(),
            }
            for key, state_key in (
                ("hcs026_factory_endpoint", "rf_factory_endpoint"),
                ("hcs026_paired_endpoint", "rf_paired_endpoint"),
                ("hcs026_pairing_state", "rf_pairing_state"),
                ("battery_low", "battery_low"),
                ("battery_status", "battery_status"),
                ("battery_percent", "battery_percent"),
            ):
                if key in decoded:
                    state[state_key] = decoded[key]
            if "hub_rssi_db" in decoded:
                state["hub_rssi_db"] = decoded["hub_rssi_db"]
            state.update(receiver_metadata)
            if self.gateway.endpoint_suppressed(endpoint):
                self.gateway.observe_rf_frame(
                    frame=decoded["frame_hex"],
                    state=state,
                    observed_at=observed_at,
                )
                published += 1
                continue
            model = identity.model
            if frame_accepted:
                self.gateway.confirm_product_identity(
                    endpoint=endpoint,
                    identity=identity,
                    observed_at=observed_at,
                )
                self.gateway.observe_decoded(
                    device_id=device_id,
                    name=name,
                    model=model,
                    frame=decoded["frame_hex"],
                    state=state,
                    observed_at=observed_at,
                )
            else:
                self.gateway.observe_rf_frame(
                    frame=decoded["frame_hex"],
                    state=state,
                    observed_at=observed_at,
                    device_id=device_id,
                )
            published += 1
        return published
