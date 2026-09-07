"""Captured-fixture replay transport."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .gateway import Gateway


DEFAULT_FIXTURES = Path(__file__).resolve().parents[2] / "examples" / "captured-replay" / "fixtures.json"



def load_fixtures(path: Path = DEFAULT_FIXTURES) -> list[dict[str, Any]]:
    """Load and validate replay fixtures."""
    fixtures = json.loads(path.read_text())
    if not isinstance(fixtures, list) or not fixtures:
        raise ValueError("fixture file must contain a non-empty JSON list")
    for fixture in fixtures:
        missing = {"name", "model", "frame", "device_id", "device_name"} - fixture.keys()
        if missing:
            raise ValueError(f"fixture is missing fields: {sorted(missing)}")
        if any(not isinstance(fixture[field], str) or not fixture[field].strip()
               for field in ("name", "model", "frame", "device_id", "device_name")):
            raise ValueError("fixture identity and frame fields must be non-empty strings")
    return fixtures


class ReplayTransport:
    """Cycle known captured frames through a Gateway."""

    def __init__(
        self,
        gateway: Gateway,
        *,
        fixtures: list[dict[str, Any]] | None = None,
        interval: float = 5.0,
    ) -> None:
        self.gateway = gateway
        self.fixtures = fixtures or load_fixtures()
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def seed(self) -> None:
        """Load one observation for every fixture into the gateway immediately."""
        for fixture in self.fixtures:
            self._publish(fixture)

    def start(self) -> None:
        """Start fixture replay in a background thread."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="rainpoint-replay", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop replay."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval + 0.5))
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            for fixture in self.fixtures:
                if self._stop.is_set():
                    return
                self._publish(fixture)
                if self._stop.wait(self.interval):
                    return

    def _publish(self, fixture: dict[str, Any]) -> None:
        self.gateway.observe(
            device_id=fixture["device_id"],
            name=fixture["device_name"],
            model=fixture["model"],
            frame=fixture["frame"],
        )
