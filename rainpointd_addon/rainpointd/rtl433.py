"""Receive-only rtl_433 transport for live RainPoint RF observations."""

from __future__ import annotations

import json
import subprocess
import threading
from typing import Any, Callable, Sequence, TextIO

from .gateway import Gateway
from .rf import FLEX_DECODER, normalize_row


KNOWN_HCS026 = {
    "9ce58024": ("soil-right-bed", "Right Bed"),
}


def rtl_433_command(frequency: int, sample_rate: int) -> list[str]:
    """Build the receive-only rtl_433 command without any transmit capability."""
    return [
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


class RTL433Transport:
    """Stream matching rtl_433 JSON events into a Gateway."""

    def __init__(
        self,
        gateway: Gateway,
        *,
        frequency: int = 434_000_000,
        sample_rate: int = 1_024_000,
        command: Sequence[str] | None = None,
        process_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
    ) -> None:
        self.gateway = gateway
        self.command = list(command or rtl_433_command(frequency, sample_rate))
        self.process_factory = process_factory
        self._process: subprocess.Popen[str] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def seed(self) -> None:
        """Register known sensors before their first periodic packet arrives."""
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
        self._process = self.process_factory(
            self.command,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            bufsize=1,
        )
        self.gateway.set_transport_status(True)
        if self._process.stdout is None:
            raise RuntimeError("rtl_433 stdout pipe was not created")
        self._thread = threading.Thread(
            target=self._run,
            args=(self._process.stdout,),
            name="rainpoint-rtl433",
            daemon=True,
        )
        self._thread.start()

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
        for row in event.get("rows", []):
            try:
                decoded = normalize_row(row)
            except (KeyError, TypeError, ValueError):
                continue
            moisture = decoded.get("soil_moisture_percent")
            if moisture is None:
                state: dict[str, Any] = {
                    "raw": decoded["frame_hex"],
                    "rf_endpoint_a": decoded["endpoint_a"],
                    "rf_endpoint_b": decoded["endpoint_b"],
                    "rf_message_type": decoded["message_type"],
                }
                if "rssi" in event:
                    state["rf_rssi_db"] = event["rssi"]
                self.gateway.observe_rf_frame(
                    frame=decoded["frame_hex"],
                    state=state,
                    observed_at=event.get("time"),
                )
                published += 1
                continue

            endpoint = decoded["endpoint_b"]
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
                "soil_moisture_percent": moisture,
            }
            if "rssi" in event:
                state["rf_rssi_db"] = event["rssi"]
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

    def _run(self, stream: TextIO) -> None:
        try:
            for line in stream:
                if self._stop.is_set():
                    return
                self.consume_line(line)
        except Exception as exc:  # Keep health visible if the reader fails.
            if not self._stop.is_set():
                self.gateway.set_transport_status(False, str(exc))
            return
        if not self._stop.is_set():
            returncode = self._process.wait() if self._process else None
            self.gateway.set_transport_status(
                False, f"rtl_433 exited unexpectedly ({returncode})"
            )
