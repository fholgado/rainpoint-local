"""Receive-only rtl_433 transport for live RainPoint RF observations."""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable, Sequence

from .gateway import Gateway
from .rf import FLEX_DECODER, normalize_row


KNOWN_HCS026 = {
    "c4e50024": ("soil-left-bed", "Left Bed"),
    "ce628024": ("soil-front-1", "Front Yard Sensor 1"),
    "d1e28024": ("soil-front-2", "Front Yard Sensor 2"),
    "9ce58024": ("soil-right-bed", "Right Bed"),
}


def _bridge_metadata(event: dict[str, Any]) -> dict[str, Any]:
    """Return optional receiver metadata supplied by an embedded bridge."""
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


def rtl_433_command(
    frequency: int,
    sample_rate: int,
    *,
    signal_capture_seconds: int = 0,
) -> list[str]:
    """Build the receive-only rtl_433 command without any transmit capability."""
    command = [
        "rtl_433",
        "-f",
        str(frequency),
        "-s",
        str(sample_rate),
        "-R",
        "0",
        "-X",
        FLEX_DECODER,
        "-M",
        "time:iso:usec",
        "-M",
        "bits",
        "-M",
        "level",
        "-F",
        "json",
    ]
    if signal_capture_seconds > 0:
        command.extend(
            ["-A", "-S", "all", "-T", str(signal_capture_seconds)]
        )
    return command


class RTL433Transport:
    """Stream matching rtl_433 JSON events into a Gateway."""

    def __init__(
        self,
        gateway: Gateway,
        *,
        frequency: int = 433_700_000,
        sample_rate: int = 2_000_000,
        signal_capture_seconds: int = 0,
        signal_directory: str | None = None,
        command: Sequence[str] | None = None,
        process_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
    ) -> None:
        self.gateway = gateway
        self.command = list(command or rtl_433_command(frequency, sample_rate))
        self._capture_command = (
            rtl_433_command(
                frequency,
                sample_rate,
                signal_capture_seconds=signal_capture_seconds,
            )
            if command is None and signal_capture_seconds > 0
            else None
        )
        self._signal_directory = signal_directory
        if self._capture_command and not self._signal_directory:
            raise ValueError("signal_directory is required for raw capture")
        if self._signal_directory:
            Path(self._signal_directory).mkdir(parents=True, exist_ok=True)
        self._capture_pending = self._capture_command is not None
        self.process_factory = process_factory
        self._process: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._valve_state: dict[str, Any] = {
            "valve_state": None,
            "is_watering": None,
            "duration_seconds": None,
            "last_usage_liters": None,
        }

    def seed(self) -> None:
        """Register known sensors before their first periodic packet arrives."""
        self.gateway.register(
            device_id="valve-1",
            name="Garden Valve",
            model="HTV145FRF",
            state=self._valve_state,
        )
        for endpoint, (device_id, name) in KNOWN_HCS026.items():
            self.gateway.register(
                device_id=device_id,
                name=name,
                model="HCS026FRF",
                state={"rf_endpoint": endpoint, "soil_moisture_percent": None},
            )

    def start(self) -> None:
        """Start rtl_433 and consume its JSON output in a background thread."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._process = self._start_process(
            self._capture_command or self.command,
            cwd=self._signal_directory if self._capture_pending else None,
        )
        self.gateway.set_transport_status(True)
        self._thread = threading.Thread(
            target=self._run,
            name="rainpoint-rtl433",
            daemon=True,
        )
        self._thread.start()

    def _start_process(
        self, command: Sequence[str], *, cwd: str | None = None
    ) -> subprocess.Popen[str]:
        """Start one receive-only rtl_433 phase."""
        process = self.process_factory(
            command,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            bufsize=1,
            cwd=cwd,
        )
        if process.stdout is None:
            raise RuntimeError("rtl_433 stdout pipe was not created")
        return process

    def stop(self) -> None:
        """Stop the receive process and reader thread."""
        self._stop.set()
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=3)
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._process = None
        self._thread = None

    def consume_line(self, line: str) -> int:
        """Consume one rtl_433 JSON line and return published observation count."""
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            return 0

        published = 0
        bridge_metadata = _bridge_metadata(event)
        for row in event.get("rows", []):
            try:
                decoded = normalize_row(row)
            except (KeyError, TypeError, ValueError):
                continue
            moisture = decoded.get("soil_moisture_percent")
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
                self._valve_state.update(valve_update)
                state = {
                    "model": "HTV145FRF",
                    "raw": decoded["frame_hex"],
                    "rf_endpoint_a": decoded["endpoint_a"],
                    "rf_endpoint_b": decoded["endpoint_b"],
                    "rf_trailer_residual": decoded["trailer_residual"],
                    "rf_trailer_valid": decoded["trailer_valid"],
                    **self._valve_state,
                }
                if "rssi" in event:
                    state["rf_rssi_db"] = event["rssi"]
                state.update(bridge_metadata)
                self.gateway.observe_decoded(
                    device_id="valve-1",
                    name="Garden Valve",
                    model="HTV145FRF",
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
                }
                for key in ("trailer_residual", "trailer_valid"):
                    state[f"rf_{key}"] = decoded[key]
                for key in (
                    "status_soil_moisture_percent",
                    "hub_rssi_db",
                    "battery_endpoint",
                    "battery_status_candidate",
                    "battery_percent_candidate",
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
                )
                published += 1
                continue

            endpoint = decoded.get("canonical_endpoint_b", decoded["endpoint_b"])
            device_id, name = KNOWN_HCS026.get(
                endpoint,
                (f"hcs026-{endpoint}", f"RainPoint HCS026 {endpoint}"),
            )
            state: dict[str, Any] = {
                "model": "HCS026FRF",
                "raw": decoded["frame_hex"],
                "rf_endpoint": endpoint,
                "rf_endpoint_a": decoded["endpoint_a"],
                "rf_endpoint_b": decoded["endpoint_b"],
                "rf_trailer_residual": decoded["trailer_residual"],
                "rf_trailer_valid": decoded["trailer_valid"],
                "soil_moisture_percent": moisture,
            }
            if "product_code" in decoded:
                state["rf_product_code"] = decoded["product_code"]
            if "hub_rssi_db" in decoded:
                state["hub_rssi_db"] = decoded["hub_rssi_db"]
            if "rssi" in event:
                state["rf_rssi_db"] = event["rssi"]
            state.update(bridge_metadata)
            self.gateway.observe_decoded(
                device_id=device_id,
                name=name,
                model="HCS026FRF",
                frame=decoded["frame_hex"],
                state=state,
                observed_at=event.get("time"),
            )
            published += 1
        return published

    def _run(self) -> None:
        while not self._stop.is_set():
            process = self._process
            if process is None or process.stdout is None:
                return
            try:
                for line in process.stdout:
                    if self._stop.is_set():
                        return
                    self.consume_line(line)
            except Exception as exc:  # Keep health visible if reader fails.
                if not self._stop.is_set():
                    self.gateway.set_transport_status(False, str(exc))
                return

            returncode = process.wait()
            if self._stop.is_set():
                return
            if self._capture_pending:
                self._capture_pending = False
                try:
                    self._process = self._start_process(self.command)
                except Exception as exc:
                    self.gateway.set_transport_status(False, str(exc))
                    return
                self.gateway.set_transport_status(True)
                continue
            self.gateway.set_transport_status(
                False, f"rtl_433 exited unexpectedly ({returncode})"
            )
            return
