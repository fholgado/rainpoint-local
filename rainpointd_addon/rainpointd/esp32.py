"""Receive-only serial transport for the RainPoint ESP32 radio bridge."""

from __future__ import annotations

import json
import threading
from typing import Any, Callable

from .gateway import Gateway
from .rf import FRAME_BYTES, SYNC
from .rtl433 import RTL433Transport


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
        # Reuse the established decoded-event publisher so RTL-SDR and ESP32
        # input produce identical device state and endpoint inventory.
        self._publisher = RTL433Transport(gateway, command=["unused"])
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
        return self._publisher.consume_line(json.dumps(event))

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
