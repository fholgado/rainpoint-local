"""Receive-only serial transport for the RainPoint ESP32 radio bridge."""

from __future__ import annotations

import json
import ipaddress
import threading
from typing import Any, Callable

from .gateway import Gateway
from .rf import FRAME_BYTES, SYNC
from .ingest import FrameIngestor
from .valve_protocol import decode_htv405_routine_ack


class ESP32SerialTransport:
    """Stream normalized frame JSON from an ESP32 into a Gateway."""

    def __init__(
        self,
        gateway: Gateway,
        *,
        device: str,
        baud: int = 115_200,
        serial_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.gateway = gateway
        self.device = device
        self.baud = baud
        self.serial_factory = serial_factory
        self._publisher = FrameIngestor(
            gateway, receiver_id="local-esp32-serial"
        )
        self._serial: Any | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.radio_health: dict[str, dict[str, Any]] = {}

    def seed(self) -> None:
        """Register the same known receive-only devices as the SDR backend."""
        self._publisher.seed()

    def start(self) -> None:
        """Open the serial port and consume bridge messages in the background."""
        if self._thread is not None:
            return
        factory = self.serial_factory
        if factory is None:
            import serial

            factory = serial.Serial
        self._stop.clear()
        self._serial = factory(self.device, baudrate=self.baud, timeout=1)
        self.gateway.set_transport_status(True)
        self._thread = threading.Thread(
            target=self._run,
            name="rainpoint-esp32",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the reader and close the serial port."""
        self._stop.set()
        serial_port = self._serial
        if serial_port is not None:
            serial_port.close()
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._serial = None
        self._thread = None

    def consume_line(
        self, line: str | bytes, *, authenticated_node_id: str | None = None
    ) -> int:
        """Validate one bridge line and publish it through the RF decoder."""
        if isinstance(line, bytes):
            try:
                line = line.decode("utf-8")
            except UnicodeDecodeError:
                return 0
        try:
            message = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            return 0
        if not isinstance(message, dict):
            return 0
        reported_node_id = message.get("node_id")
        if authenticated_node_id is not None:
            if reported_node_id not in (None, authenticated_node_id):
                return 0
            message["node_id"] = authenticated_node_id
        message_type = message.get("type")
        if message_type in {"fatal", "radio_error"}:
            detail = str(message.get("error", "bridge reported a radio error"))
            radio = message.get("radio")
            if isinstance(radio, str):
                detail = f"{radio}: {detail}"
            self.gateway.set_transport_status(False, detail)
            return 0
        if message_type == "radio_ready":
            self.gateway.set_transport_status(True)
            return 0
        if message_type == "radio_health":
            radio = message.get("radio")
            if not isinstance(radio, str):
                return 0
            health_key = (
                f"{authenticated_node_id}:{radio}"
                if authenticated_node_id
                else radio
            )
            self.radio_health[health_key] = {
                key: message[key]
                for key in (
                    "channel",
                    "configuration_valid",
                    "packets",
                    "overflows",
                    "recoveries",
                )
                if key in message
            }
            if message.get("configuration_valid") is False:
                self.gateway.set_transport_status(
                    False, f"{radio}: cc1101_configuration_mismatch"
                )
            if authenticated_node_id:
                node_health = {
                    key.removeprefix(f"{authenticated_node_id}:"): value
                    for key, value in self.radio_health.items()
                    if key.startswith(f"{authenticated_node_id}:")
                }
                self.gateway.update_node(
                    authenticated_node_id,
                    radio_health=node_health,
                )
            return 0
        if message_type == "node_health":
            if authenticated_node_id is None:
                return 0
            diagnostics: dict[str, Any] = {}
            for key in (
                "uptime_seconds",
                "free_heap_bytes",
                "minimum_free_heap_bytes",
                "largest_free_block_bytes",
                "cpu_frequency_mhz",
                "maximum_loop_gap_ms",
                "reset_reason_code",
                "network_bytes_sent",
                "network_bytes_received",
                "wifi_reconnects",
                "gateway_connect_attempts",
                "gateway_authentications",
                "routine_ack_authorized_sensors",
                "routine_ack_receive_channel",
                "routine_ack_transmissions",
                "routine_ack_failures",
                "htv405_routine_ack_authorized_valves",
                "htv405_routine_ack_transmissions",
                "htv405_routine_ack_failures",
                "sensor_recovery_transmissions",
                "sensor_recovery_failures",
                "sensor_recovery_completions",
                "rf_mode_remaining_seconds",
                "rf_mode_changed_uptime_ms",
                "rf_blocked_transmit_count",
                "rf_rejected_command_count",
            ):
                value = message.get(key)
                if (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                ):
                    diagnostics[key] = value
            rf_mode = message.get("rf_mode")
            if rf_mode in {"normal", "receive_only"}:
                diagnostics["rf_mode"] = rf_mode
            reboot_pending = message.get("node_reboot_pending")
            if isinstance(reboot_pending, bool):
                diagnostics["node_reboot_pending"] = reboot_pending
            temperature = message.get("device_temperature_c")
            if (
                isinstance(temperature, (int, float))
                and not isinstance(temperature, bool)
                and -50 <= temperature <= 150
            ):
                diagnostics["device_temperature_c"] = float(temperature)
            wifi_rssi = message.get("wifi_rssi_dbm")
            if (
                isinstance(wifi_rssi, int)
                and not isinstance(wifi_rssi, bool)
                and -150 <= wifi_rssi <= 0
            ):
                diagnostics["wifi_rssi_dbm"] = wifi_rssi
            ip_address = message.get("ip_address")
            if isinstance(ip_address, str):
                try:
                    diagnostics["ip_address"] = str(
                        ipaddress.ip_address(ip_address)
                    )
                except ValueError:
                    pass
            self.gateway.observe_node_health(
                authenticated_node_id, **diagnostics
            )
            return 0
        if message_type == "sensor_recovery_status":
            if authenticated_node_id is None:
                return 0
            endpoint = message.get("paired_endpoint")
            state = message.get("state")
            phase = message.get("phase")
            if (
                not isinstance(endpoint, str)
                or len(endpoint) != 8
                or not all(
                    character in "0123456789abcdef" for character in endpoint
                )
                or not isinstance(state, str)
                or not isinstance(phase, str)
            ):
                return 0
            diagnostics: dict[str, Any] = {
                "rf_recovery_state": state,
                "rf_recovery_phase": phase,
            }
            for source, target in (
                ("transmissions", "rf_recovery_transmissions"),
                ("failures", "rf_recovery_failures"),
                ("completions", "rf_recovery_completions"),
            ):
                value = message.get(source)
                if (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                ):
                    diagnostics[target] = value
            self.gateway.update_node(
                authenticated_node_id,
                sensor_recovery_endpoint=endpoint,
                **diagnostics,
            )
            self.gateway.observe_sensor_link_status(
                authenticated_node_id, endpoint, **diagnostics
            )
            return 0
        if message_type == "routine_ack_status":
            if authenticated_node_id is None:
                return 0
            endpoint = message.get("paired_endpoint")
            state = message.get("state")
            if (
                not isinstance(endpoint, str)
                or len(endpoint) != 8
                or not all(
                    character in "0123456789abcdef" for character in endpoint
                )
                or not isinstance(state, str)
            ):
                return 0
            diagnostics = {
                "routine_ack_state": state,
                "routine_ack_endpoint": endpoint,
            }
            for source, target in (
                ("authorized_sensor_count", "routine_ack_authorized_sensors"),
                ("transmissions", "routine_ack_transmissions"),
                ("failures", "routine_ack_failures"),
                ("assigned_channel", "routine_ack_assigned_channel"),
                ("channel_center_hz", "routine_ack_channel_center_hz"),
            ):
                value = message.get(source)
                if (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                ):
                    diagnostics[target] = value
            self.gateway.update_node(authenticated_node_id, **diagnostics)
            self.gateway.observe_sensor_link_status(
                authenticated_node_id,
                endpoint,
                rf_ack_state=state,
                rf_ack_confirmation=(
                    "pending_observation" if state == "transmitted" else None
                ),
                rf_ack_transmissions=diagnostics.get(
                    "routine_ack_transmissions"
                ),
                rf_ack_failures=diagnostics.get("routine_ack_failures"),
                rf_ack_assigned_channel=diagnostics.get(
                    "routine_ack_assigned_channel"
                ),
            )
            return 0
        if message_type == "htv405_routine_ack_status":
            if authenticated_node_id is None:
                return 0
            endpoint = message.get("valve_endpoint")
            state = message.get("state")
            if (
                not isinstance(endpoint, str)
                or len(endpoint) != 8
                or not all(
                    character in "0123456789abcdef" for character in endpoint
                )
                or not isinstance(state, str)
            ):
                return 0
            diagnostics: dict[str, Any] = {
                "htv405_routine_ack_state": state,
                "htv405_routine_ack_endpoint": endpoint,
            }
            for source, target in (
                (
                    "authorized_valve_count",
                    "htv405_routine_ack_authorized_valves",
                ),
                ("transmissions", "htv405_routine_ack_transmissions"),
                ("failures", "htv405_routine_ack_failures"),
                ("channel_center_hz", "htv405_routine_ack_channel_center_hz"),
            ):
                value = message.get(source)
                if (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                ):
                    diagnostics[target] = value
            self.gateway.update_node(authenticated_node_id, **diagnostics)
            event_fields: dict[str, Any] = {
                "ack_state": state,
            }
            for source in (
                "authorized_valve_count",
                "transmissions",
                "failures",
                "channel_center_hz",
            ):
                value = message.get(source)
                if (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                ):
                    event_fields[source] = value
            frame = message.get("frame")
            if (
                isinstance(frame, str)
                and len(frame) == FRAME_BYTES * 2
                and all(
                    character in "0123456789abcdef" for character in frame
                )
            ):
                decoded = decode_htv405_routine_ack(bytes.fromhex(frame))
                event_fields["frame"] = frame
                if decoded is not None:
                    event_fields["telemetry_sequence"] = int(
                        decoded["htv405_routine_ack_sequence"]
                    )
                    event_fields["telemetry_repeat"] = bool(
                        decoded["htv405_routine_ack_repeat"]
                    )
                    event_fields["companion_endpoint"] = str(
                        decoded["htv405_routine_ack_companion_endpoint"]
                    )
                    event_fields["controller_endpoint"] = str(
                        decoded["htv405_routine_ack_controller_endpoint"]
                    )
            self.gateway.observe_htv405_routine_ack_status(
                authenticated_node_id,
                endpoint,
                **event_fields,
            )
            return 0
        if message_type == "valve_control_probe":
            # Research-only status is never an actuator request. Accept
            # durable controller state only from an authenticated network
            # node; the gateway performs an independent frame/profile check.
            if authenticated_node_id is None:
                return 0
            status = message.get("state")
            if isinstance(status, str):
                self.gateway.update_node(
                    authenticated_node_id,
                    valve_control_probe_state=status,
                    valve_control_probe_configured=(
                        message.get("configured") is True
                    ),
                    valve_control_probe_counter_authenticated=(
                        message.get("command_counter_valid") is True
                        and message.get("command_phase_source")
                        == "authenticated_valve_response"
                    ),
                )
            self.gateway.observe_valve_control_probe(
                authenticated_node_id, message
            )
            return 0
        if message_type != "rainpoint_rf":
            return 0
        frame_hex = message.get("frame")
        if not isinstance(frame_hex, str) or len(frame_hex) != FRAME_BYTES * 2:
            return 0
        try:
            frame = bytes.fromhex(frame_hex)
        except ValueError:
            return 0
        if frame[: len(SYNC)] != SYNC:
            return 0

        event: dict[str, Any] = {
            "rows": [{"len": FRAME_BYTES * 8, "data": frame.hex()}],
            "bridge_metadata": {
                key: message[key]
                for key in (
                    "node_id",
                    "radio",
                    "channel",
                    "lqi",
                    "frequency_offset_hz",
                )
                if key in message
            },
        }
        rssi = message.get("rssi_dbm")
        if isinstance(rssi, (int, float)) and not isinstance(rssi, bool):
            event["rssi"] = rssi
        return self._publisher.consume_event(event)

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                serial_port = self._serial
                if serial_port is None:
                    return
                line = serial_port.readline()
                if line:
                    self.consume_line(line)
        except Exception as exc:
            if not self._stop.is_set():
                self.gateway.set_transport_status(False, str(exc))
