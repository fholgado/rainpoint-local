"""Minimal versioned HTTP API for rainpointd."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .gateway import API_VERSION, Gateway


class RainPointHTTPServer(ThreadingHTTPServer):
    """HTTP server carrying the configured gateway instance."""

    gateway: Gateway


class RequestHandler(BaseHTTPRequestHandler):
    """Serve read-only gateway endpoints."""

    server: RainPointHTTPServer

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json(200, {"status": "ok"})
            return
        if parsed.path == f"/api/{API_VERSION}/info":
            self._json(200, self.server.gateway.info())
            return
        if parsed.path == f"/api/{API_VERSION}/devices":
            self._json(200, {"devices": self.server.gateway.devices()})
            return
        if parsed.path == f"/api/{API_VERSION}/events":
            query = parse_qs(parsed.query)
            try:
                since = int(query.get("since", ["0"])[0])
            except ValueError:
                self._json(400, {"error": "since must be an integer"})
                return
            self._json(
                200,
                {
                    "events": self.server.gateway.events(since),
                    "next_since": self._latest_event_id(),
                },
            )
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._json(
            405,
            {
                "error": "gateway is read-only",
                "detail": "control is intentionally unavailable in this milestone",
            },
        )

    def log_message(self, format: str, *args: Any) -> None:
        """Keep command-line output concise."""

    def _latest_event_id(self) -> int:
        events = self.server.gateway.events()
        return events[-1]["event_id"] if events else 0

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def create_server(
    gateway: Gateway, host: str = "127.0.0.1", port: int = 8787
) -> RainPointHTTPServer:
    """Create, but do not start, an HTTP server."""
    server = RainPointHTTPServer((host, port), RequestHandler)
    server.gateway = gateway
    return server
