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
    """Serve telemetry plus token-protected local registry metadata."""

    server: RainPointHTTPServer

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            health = self.server.gateway.health()
            self._json(200 if health["status"] == "ok" else 503, health)
            return
        if parsed.path == f"/api/{API_VERSION}/info":
            self._json(200, self.server.gateway.info())
            return
        if parsed.path == f"/api/{API_VERSION}/devices":
            self._json(200, {"devices": self.server.gateway.devices()})
            return
        if parsed.path == f"/api/{API_VERSION}/nodes":
            self._json(200, {"nodes": self.server.gateway.nodes()})
            return
        if parsed.path == f"/api/{API_VERSION}/receivers":
            self._json(200, {"receivers": self.server.gateway.receivers()})
            return
        if parsed.path == f"/api/{API_VERSION}/endpoints":
            self._json(200, {"endpoints": self.server.gateway.endpoints()})
            return
        if parsed.path == f"/api/{API_VERSION}/registry":
            self._json(
                200,
                {
                    "devices": self.server.gateway.registry(),
                    "rf_pairing": False,
                },
            )
            return
        if parsed.path == f"/api/{API_VERSION}/learning":
            self._json(200, self.server.gateway.learning())
            return
        if parsed.path == f"/api/{API_VERSION}/pairing":
            self._json(200, self.server.gateway.pairing())
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
                    "next_since": self._page_cursor(since),
                },
            )
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        base = f"/api/{API_VERSION}"
        if parsed.path == f"{base}/auth/check":
            if self._authorize_registry_write():
                self._json(200, {"authorized": True})
            return
        registry_path = parsed.path.startswith(f"{base}/registry/")
        pairing_path = parsed.path.startswith(f"{base}/pairing/")
        node_path = parsed.path.startswith(f"{base}/nodes/")
        if (
            parsed.path == f"{base}/learning"
            or registry_path
            or pairing_path
            or node_path
        ):
            if not self._authorize_registry_write():
                return
            try:
                body = self._request_json()
                if parsed.path == f"{base}/learning":
                    result = self.server.gateway.start_learning(
                        int(body.get("duration_seconds", 300))
                    )
                    self._json(201, result)
                    return
                if parsed.path == f"{base}/nodes/register":
                    result = self.server.gateway.register_radio_node(
                        node_id=str(body.get("node_id", "")),
                        token=str(body.get("token", "")),
                        name=str(body.get("name", "")),
                        area=(
                            str(body["area"])
                            if body.get("area") is not None
                            else None
                        ),
                    )
                    self._json(201, {"node": result})
                    return
                node_prefix = f"{base}/nodes/"
                node_suffix = parsed.path[len(node_prefix) :]
                node_id, separator, node_action = node_suffix.rpartition("/")
                if separator and node_action == "identify":
                    result = self.server.gateway.identify_radio_node(
                        node_id,
                        int(body.get("duration_seconds", 15)),
                    )
                    self._json(200, result)
                    return
                if parsed.path == f"{base}/pairing/start":
                    result = self.server.gateway.start_pairing(
                        int(body.get("duration_seconds", 120)),
                        node_id=(
                            str(body["node_id"])
                            if body.get("node_id") is not None
                            else None
                        ),
                    )
                    self._json(201, result)
                    return
                if parsed.path == f"{base}/pairing/stop":
                    self._json(200, self.server.gateway.stop_pairing())
                    return
                if parsed.path == f"{base}/pairing/complete":
                    transmit_performed = bool(
                        self.server.gateway.pairing().get("transmit_performed")
                    )
                    result = self.server.gateway.complete_hcs026_pairing(
                        endpoint=str(body.get("endpoint", "")),
                        name=str(body.get("name", "")),
                        area=body.get("area"),
                    )
                    self._json(
                        201,
                        {
                            "device": result,
                            "rf_paired": True,
                            "transmit_performed": transmit_performed,
                        },
                    )
                    return
                if parsed.path == f"{base}/registry/accept":
                    result = self.server.gateway.accept_endpoint(
                        endpoint=str(body.get("endpoint", "")),
                        name=str(body.get("name", "")),
                        model=str(body.get("model", "")),
                        area=body.get("area"),
                    )
                    self._json(
                        201,
                        {
                            "device": result,
                            "rf_paired": False,
                            "detail": "local metadata accepted; no RF pairing sent",
                        },
                    )
                    return
                prefix = f"{base}/registry/"
                suffix = parsed.path[len(prefix) :]
                device_id, separator, action = suffix.rpartition("/")
                if separator and action == "rename":
                    kwargs: dict[str, Any] = {}
                    if "name" in body:
                        kwargs["name"] = body["name"]
                    if "area" in body:
                        kwargs["area"] = body["area"]
                    result = self.server.gateway.update_registry_device(
                        device_id, **kwargs
                    )
                    self._json(200, {"device": result, "rf_paired": False})
                    return
                if separator and action == "forget":
                    result = self.server.gateway.forget_registry_device(device_id)
                    self._json(
                        200,
                        {
                            "forgotten": result,
                            "rf_unpaired": False,
                            "detail": (
                                "local metadata and enrollment removed; "
                                "no RF unpair sent"
                            ),
                        },
                    )
                    return
                self._json(404, {"error": "not found"})
                return
            except KeyError as error:
                self._json(404, {"error": f"not found: {error.args[0]}"})
                return
            except (RuntimeError, TypeError, ValueError) as error:
                self._json(400, {"error": str(error)})
                return
        self._json(
            405,
            {
                "error": "gateway is read-only",
                "detail": "control is intentionally unavailable in this milestone",
            },
        )

    def _authorize_registry_write(self) -> bool:
        """Require a configured bearer token for local metadata changes."""
        authorization = self.headers.get("Authorization", "")
        token = (
            authorization.removeprefix("Bearer ")
            if authorization.startswith("Bearer ")
            else None
        )
        info = self.server.gateway.info()
        if not info["registry_writes_enabled"]:
            self._json(403, {"error": "registry writes are disabled"})
            return False
        if not self.server.gateway.registry_authorized(token):
            self._json(401, {"error": "invalid registry token"})
            return False
        return True

    def _request_json(self) -> dict[str, Any]:
        """Read one small JSON object from a metadata request."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("invalid Content-Length") from error
        if not 0 <= length <= 16_384:
            raise ValueError("request body exceeds 16384 bytes")
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("request body must be valid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def log_message(self, format: str, *args: Any) -> None:
        """Keep command-line output concise."""

    def _page_cursor(self, since: int) -> int:
        events = self.server.gateway.events(since)
        return events[-1]["event_id"] if events else since

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
