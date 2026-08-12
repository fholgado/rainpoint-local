"""Receive-only rtl_433 transport for live RainPoint RF observations."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Callable, Sequence

from .device_catalog import DeviceCatalog
from .gateway import Gateway
from .ingest import FrameIngestor
from .rf import FLEX_DECODER


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
        catalog: DeviceCatalog | None = None,
    ) -> None:
        self.gateway = gateway
        self._catalog_override = catalog
        self._ingestor = FrameIngestor(
            gateway,
            catalog=catalog,
            receiver_id="local-sdr",
        )
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

    @property
    def catalog(self) -> DeviceCatalog:
        """Return the current registry-backed device catalog."""
        return self._catalog_override or self.gateway.catalog

    def seed(self) -> None:
        """Register known sensors before their first periodic packet arrives."""
        self._ingestor.seed()

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
        return self._ingestor.consume_line(line)

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
