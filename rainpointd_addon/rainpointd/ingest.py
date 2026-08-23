"""Transport-neutral ingestion of normalized RainPoint RF observations."""

from __future__ import annotations

from typing import Any

from .device_catalog import DeviceCatalog
from .gateway import Gateway
from .product_identity import hcs02x_identity
from .protocol import RFObservation, decode_receiver_event, decode_receiver_line
from .valve_protocol import (
    decode_htv405_control_frame,
    decode_htv405_gateway_command_response,
    htv405_phase_state,
    is_htv405_link_frame,
)


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
        state: dict[str, Any] = {
            "valve_state": None,
            "is_watering": None,
            "duration_seconds": None,
            "last_usage_liters": None,
        }
        for zone in range(1, 5):
            state[f"zone_{zone}_is_watering"] = None
            state[f"zone_{zone}_remaining_seconds"] = None
            state[f"zone_{zone}_duration_seconds"] = None
        return state

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
            valve_phase: dict[str, int | bool] = {}
            try:
                raw_frame = bytes.fromhex(decoded["frame_hex"])
            except ValueError:
                raw_frame = b""
            control_response = (
                decode_htv405_gateway_command_response(raw_frame) or {}
            )
            if is_htv405_link_frame(raw_frame):
                valve_phase = htv405_phase_state(raw_frame)
                self.gateway.register_observed_htv405_link(
                    controller_endpoint=decoded["endpoint_a"],
                    valve_endpoint=decoded["endpoint_b"],
                    frame=decoded["frame_hex"],
                    observed_at=observed_at,
                )
            if valve is None:
                if is_htv405_link_frame(raw_frame):
                    valve = self.catalog.valve_link(
                        decoded["endpoint_a"], decoded["endpoint_b"]
                    )
                    if valve is not None:
                        # The first structurally valid report established the
                        # link after normalization, so decode its fields now.
                        decoded.update(
                            decode_htv405_control_frame(raw_frame) or {}
                        )
                        decoded["valve_state"] = (
                            "watering"
                            if decoded.get("is_watering")
                            else "idle"
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
                zone = decoded.get("zone")
                if isinstance(zone, int) and 1 <= zone <= 4:
                    watering = bool(decoded.get("is_watering"))
                    valve_update[f"zone_{zone}_is_watering"] = watering
                    valve_update[f"zone_{zone}_remaining_seconds"] = (
                        decoded.get("remaining_seconds") if watering else None
                    )
                    if "duration_seconds" in decoded:
                        valve_update[f"zone_{zone}_duration_seconds"] = decoded[
                            "duration_seconds"
                        ]
                    if watering:
                        # The HTV405 chassis physically permits one active
                        # outlet. A newly observed open therefore closes every
                        # other logical zone even if its final idle report was
                        # missed by this receiver.
                        for other_zone in range(1, 5):
                            if other_zone == zone:
                                continue
                            valve_update[
                                f"zone_{other_zone}_is_watering"
                            ] = False
                            valve_update[
                                f"zone_{other_zone}_remaining_seconds"
                            ] = None
                    zone_states = {
                        candidate: valve_update.get(
                            f"zone_{candidate}_is_watering",
                            valve_state.get(
                                f"zone_{candidate}_is_watering"
                            ),
                        )
                        for candidate in range(1, 5)
                    }
                    active_zone = next(
                        (
                            candidate
                            for candidate, active in zone_states.items()
                            if active is True
                        ),
                        None,
                    )
                    valve_update["active_zone"] = active_zone
                    valve_update["is_watering"] = active_zone is not None
                    valve_update["valve_state"] = (
                        "watering" if active_zone is not None else "idle"
                    )
                state = {
                    "model": valve.model,
                    "raw": decoded["frame_hex"],
                    "rf_endpoint_a": decoded["endpoint_a"],
                    "rf_endpoint_b": decoded["endpoint_b"],
                    "rf_trailer_residual": decoded["trailer_residual"],
                    "rf_trailer_valid": decoded["trailer_valid"],
                    "rf_frame_accepted": True,
                    **valve_phase,
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
                    **valve_phase,
                    **control_response,
                }
                for key in ("trailer_residual", "trailer_valid"):
                    state[f"rf_{key}"] = decoded[key]
                for key in (
                    "status_soil_moisture_percent",
                    "hub_rssi_db",
                    "routine_ack_endpoint",
                    "routine_ack_message",
                    "routine_ack_body_code",
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
