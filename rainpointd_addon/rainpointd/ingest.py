"""Transport-neutral ingestion of normalized RainPoint RF observations."""

from __future__ import annotations

import json
from typing import Any

from .device_catalog import DeviceCatalog
from .gateway import Gateway
from .rf import normalize_row


def _bridge_metadata(event: dict[str, Any]) -> dict[str, Any]:
    """Return optional receiver metadata supplied by a radio adapter."""
    metadata = event.get("bridge_metadata")
    if not isinstance(metadata, dict):
        return {}
    result = {}
    for source, destination, expected_type in (
        ("radio", "rf_radio", str),
        ("channel", "rf_channel", int),
        ("lqi", "rf_lqi", int),
        ("frequency_offset_hz", "rf_frequency_offset_hz", int),
        ("node_id", "rf_node_id", str),
    ):
        value = metadata.get(source)
        if isinstance(value, expected_type) and not isinstance(value, bool):
            result[destination] = value
    return result


class FrameIngestor:
    """Map normalized RF rows into gateway devices and events."""

    def __init__(
        self, gateway: Gateway, *, catalog: DeviceCatalog | None = None
    ) -> None:
        self.gateway = gateway
        self._catalog_override = catalog
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
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            return 0
        if not isinstance(event, dict):
            return 0
        return self.consume_event(event)

    def consume_event(self, event: dict[str, Any]) -> int:
        """Consume one normalized receiver event."""
        rows = event.get("rows", [])
        if not isinstance(rows, list):
            return 0
        published = 0
        bridge_metadata = _bridge_metadata(event)
        for row in rows:
            try:
                decoded = normalize_row(row, catalog=self.catalog)
            except (KeyError, TypeError, ValueError):
                continue
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
                if "rssi" in event:
                    state["rf_rssi_db"] = event["rssi"]
                state.update(bridge_metadata)
                valve_state.update(valve_update)
                self.gateway.observe_decoded(
                    device_id=valve.device_id,
                    name=valve.name,
                    model=valve.model,
                    frame=decoded["frame_hex"],
                    state=state,
                    observed_at=event.get("time"),
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
                if "rssi" in event:
                    state["rf_rssi_db"] = event["rssi"]
                state.update(bridge_metadata)
                self.gateway.observe_rf_frame(
                    frame=decoded["frame_hex"],
                    state=state,
                    observed_at=event.get("time"),
                    device_id=valve.device_id if valve else None,
                )
                published += 1
                continue

            endpoint = decoded.get("canonical_endpoint_b", decoded["endpoint_b"])
            sensor = self.catalog.sensor(endpoint)
            device_id = sensor.device_id if sensor else f"hcs026-{endpoint}"
            name = sensor.name if sensor else f"RainPoint HCS026 {endpoint}"
            frame_accepted = bool(
                decoded["trailer_valid"] or "product_code" in decoded
            )
            state = {
                "model": sensor.model if sensor else "HCS026FRF",
                "raw": decoded["frame_hex"],
                "rf_endpoint": endpoint,
                "rf_endpoint_a": decoded["endpoint_a"],
                "rf_endpoint_b": decoded["endpoint_b"],
                "rf_message_type": decoded["message_type"],
                "rf_trailer_residual": decoded["trailer_residual"],
                "rf_trailer_valid": decoded["trailer_valid"],
                "rf_frame_accepted": frame_accepted,
                "soil_moisture_percent": moisture,
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
            if "product_code" in decoded:
                state["rf_product_code"] = decoded["product_code"]
            if "hub_rssi_db" in decoded:
                state["hub_rssi_db"] = decoded["hub_rssi_db"]
            if "rssi" in event:
                state["rf_rssi_db"] = event["rssi"]
            state.update(bridge_metadata)
            if self.gateway.endpoint_suppressed(endpoint):
                self.gateway.observe_rf_frame(
                    frame=decoded["frame_hex"],
                    state=state,
                    observed_at=event.get("time"),
                )
                published += 1
                continue
            model = sensor.model if sensor else "HCS026FRF"
            if frame_accepted:
                self.gateway.observe_decoded(
                    device_id=device_id,
                    name=name,
                    model=model,
                    frame=decoded["frame_hex"],
                    state=state,
                    observed_at=event.get("time"),
                )
            else:
                self.gateway.observe_rf_frame(
                    frame=decoded["frame_hex"],
                    state=state,
                    observed_at=event.get("time"),
                    device_id=device_id,
                )
            published += 1
        return published
