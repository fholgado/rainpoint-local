"""Minimal versioned HTTP API for rainpointd."""

from __future__ import annotations

import json
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .gateway import API_VERSION, Gateway


class RainPointHTTPServer(ThreadingHTTPServer):
    """HTTP server carrying the configured gateway instance."""

    gateway: Gateway
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        self._request_slots = threading.BoundedSemaphore(32)
        super().__init__(*args, **kwargs)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(10)
        return request, address

    def process_request(self, request, client_address):
        if not self._request_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()


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
        if parsed.path == f"/api/{API_VERSION}/nodes/rf-capture-readiness":
            query = parse_qs(parsed.query)
            try:
                minimum_remaining_seconds = int(
                    query.get("minimum_remaining_seconds", ["60"])[0]
                )
                readiness = self.server.gateway.radio_node_capture_readiness(
                    minimum_remaining_seconds
                )
            except ValueError as error:
                self._json(400, {"error": str(error)})
                return
            self._json(200, readiness)
            return
        if parsed.path == f"/api/{API_VERSION}/firmware/releases":
            self._json(
                200,
                {"releases": self.server.gateway.firmware_releases()},
            )
            return
        if parsed.path == f"/api/{API_VERSION}/ack-assignments":
            self._json(
                200,
                {"ack_assignments": self.server.gateway.ack_assignments()},
            )
            return
        firmware_prefix = "/firmware/"
        if parsed.path.startswith(firmware_prefix) and parsed.path.endswith(
            ".bin"
        ):
            release_id = parsed.path[
                len(firmware_prefix) : -len(".bin")
            ]
            try:
                body, digest = self.server.gateway.firmware_artifact(release_id)
            except (OSError, ValueError):
                self._json(404, {"error": "firmware artifact not found"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            self.send_header("ETag", f'"sha256:{digest}"')
            self.end_headers()
            self.wfile.write(body)
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
                wait_seconds = float(query.get("wait", ["0"])[0])
                if since < 0 or not math.isfinite(wait_seconds) or not 0 <= wait_seconds <= 30:
                    raise ValueError("invalid event window")
            except ValueError:
                self._json(400, {"error": "since and wait must be numeric"})
                return
            events = self.server.gateway.events(since, wait_seconds)
            self._json(
                200,
                {
                    "events": events,
                    "next_since": events[-1]["event_id"] if events else min(since, self.server.gateway.latest_event_id()),
                },
            )
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        base = f"/api/{API_VERSION}"
        if parsed.path == f"{base}/auth/claim":
            try:
                token = self.server.gateway.claim_registry(
                    str(self._request_json().get("setup_code", ""))
                )
            except PermissionError:
                self._json(401, {"error": "invalid or expired setup code"})
                return
            except ValueError as error:
                self._json(400, {"error": str(error)})
                return
            self._json(200, {"registry_write_token": token})
            return
        if parsed.path == f"{base}/auth/check":
            if self._authorize_registry_write():
                self._json(200, {"authorized": True})
            return
        if parsed.path == f"{base}/auth/rotate":
            if not self._authorize_registry_write():
                return
            self._json(
                200,
                {
                    "registry_write_token": (
                        self.server.gateway.rotate_registry_token()
                    )
                },
            )
            return
        registry_path = parsed.path.startswith(f"{base}/registry/")
        device_path = parsed.path.startswith(f"{base}/devices/")
        device_forget_path = device_path and parsed.path.endswith("/forget")
        valve_control_path = device_path and (
            parsed.path.endswith("/valve/open")
            or parsed.path.endswith("/valve/close")
            or parsed.path.endswith("/valve/synchronize")
            or parsed.path.endswith("/valve/probe-idle-close")
            or parsed.path.endswith("/valve/probe-close-counter")
            or parsed.path.endswith("/valve/probe-open")
            or parsed.path.endswith("/valve/cancel-recovery")
            or parsed.path.endswith("/valve/cancel-transaction")
            or parsed.path.endswith("/valve/node")
            or parsed.path.endswith("/valve/morning-sync")
            or parsed.path.endswith("/valve/sync-now")
            or parsed.path.endswith("/valve/restore-counter")
        )
        htv145_control_prefix = f"{base}/research/htv145-control/"
        htv145_control_path = parsed.path.startswith(htv145_control_prefix)
        htv145_acceptance_prefix = f"{base}/research/htv145-acceptance/"
        htv145_acceptance_path = parsed.path.startswith(
            htv145_acceptance_prefix
        )
        pairing_path = parsed.path.startswith(f"{base}/pairing/")
        node_path = parsed.path.startswith(f"{base}/nodes/")
        if (
            parsed.path == f"{base}/learning"
            or registry_path
            or device_forget_path
            or valve_control_path
            or htv145_control_path
            or htv145_acceptance_path
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
                if parsed.path == f"{base}/nodes/adoptions/start":
                    result = self.server.gateway.start_radio_node_adoption(
                        node_id=str(body.get("node_id", "")),
                        name=str(body.get("name", "")),
                        area=(
                            str(body["area"])
                            if body.get("area") is not None
                            else None
                        ),
                        duration_seconds=int(body.get("duration_seconds", 300)),
                    )
                    self._json(201, result)
                    return
                if parsed.path == f"{base}/nodes/adoptions/status":
                    self._json(
                        200,
                        self.server.gateway.radio_node_adoption(
                            str(body.get("node_id", ""))
                        ),
                    )
                    return
                if parsed.path == f"{base}/nodes/adoptions/cancel":
                    self._json(
                        200,
                        self.server.gateway.cancel_radio_node_adoption(
                            str(body.get("node_id", ""))
                        ),
                    )
                    return
                node_prefix = f"{base}/nodes/"
                node_suffix = parsed.path[len(node_prefix) :] if node_path else ""
                node_id, separator, node_action = node_suffix.rpartition("/")
                if separator and node_action == "identify":
                    result = self.server.gateway.identify_radio_node(
                        node_id,
                        int(body.get("duration_seconds", 15)),
                    )
                    self._json(200, result)
                    return
                if separator and node_action == "rf-mode":
                    result = self.server.gateway.set_radio_node_rf_mode(
                        node_id,
                        str(body.get("mode", "")),
                        (
                            int(body["duration_seconds"])
                            if body.get("duration_seconds") is not None
                            else None
                        ),
                    )
                    self._json(200, result)
                    return
                if separator and node_action == "reboot":
                    result = self.server.gateway.reboot_radio_node(node_id)
                    self._json(202, result)
                    return
                if separator and node_action == "metadata":
                    result = self.server.gateway.update_radio_node_metadata(
                        node_id=node_id,
                        name=str(body.get("name", "")),
                        area=(
                            str(body["area"])
                            if body.get("area") is not None
                            else None
                        ),
                    )
                    self._json(200, {"node": result})
                    return
                if separator and node_action == "ack-assignment":
                    result = self.server.gateway.assign_radio_node_ack(
                        node_id=node_id,
                        paired_endpoint=str(body.get("paired_endpoint", "")),
                        assigned_channel=int(body.get("assigned_channel", 0)),
                        frequency_offset_hz=int(
                            body.get("frequency_offset_hz", 45_000)
                        ),
                        power_dbm=int(body.get("power_dbm", 10)),
                        invert=body.get("invert", False),
                    )
                    self._json(200, {"ack_assignment": result})
                    return
                if separator and node_action == "firmware-update":
                    if body.get("release_id") is not None:
                        result = (
                            self.server.gateway.install_radio_node_firmware_release(
                                node_id,
                                release_id=str(body.get("release_id", "")),
                                public_host=(
                                    str(body["public_host"])
                                    if body.get("public_host") is not None
                                    else None
                                ),
                            )
                        )
                    else:
                        result = (
                            self.server.gateway.start_radio_node_firmware_update(
                                node_id,
                                url=str(body.get("url", "")),
                                version=str(body.get("version", "")),
                                size_bytes=int(body.get("size_bytes", 0)),
                                sha256=str(body.get("sha256", "")),
                            )
                        )
                    self._json(202, result)
                    return
                if separator and node_action == "revoke":
                    self._json(
                        200,
                        self.server.gateway.revoke_radio_node(node_id),
                    )
                    return
                if parsed.path == f"{base}/pairing/start":
                    result = self.server.gateway.start_pairing(
                        int(body.get("duration_seconds", 120)),
                        node_id=(
                            str(body["node_id"])
                            if body.get("node_id") is not None
                            else None
                        ),
                        profile_id=str(
                            body.get("profile_id", "hcs026_auto_v1")
                        ),
                        factory_endpoint=(
                            str(body["factory_endpoint"])
                            if body.get("factory_endpoint") is not None
                            else None
                        ),
                        valve_route=(
                            str(body["valve_route"])
                            if body.get("valve_route") is not None
                            else None
                        ),
                        companion_endpoint=(
                            str(body["companion_endpoint"])
                            if body.get("companion_endpoint") is not None
                            else None
                        ),
                        known_rejoin=body.get("known_rejoin") is True,
                        power_dbm=(
                            int(body["power_dbm"])
                            if body.get("power_dbm") is not None
                            else None
                        ),
                    )
                    self._json(201, result)
                    return
                if parsed.path == f"{base}/pairing/stop":
                    self._json(200, self.server.gateway.stop_pairing(
                        command_id=str(body["command_id"]) if body.get("command_id") is not None else None))
                    return
                if parsed.path == f"{base}/pairing/complete":
                    transmit_performed = bool(
                        self.server.gateway.pairing().get("transmit_performed")
                    )
                    result = self.server.gateway.complete_pairing(
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
                if htv145_control_path:
                    action = parsed.path[len(htv145_control_prefix):]
                    result = self.server.gateway.htv145_control(action, body)
                    self._json(202 if action in {"open", "close", "revoke"} else 200, result)
                    return
                if htv145_acceptance_path:
                    action = parsed.path[len(htv145_acceptance_prefix) :]
                    if action == "prepare":
                        result = self.server.gateway.prepare_htv145_acceptance(
                            node_id=str(body.get("node_id", "")),
                            controller_endpoint=str(
                                body.get("controller_endpoint", "")
                            ),
                            valve_endpoint=str(
                                body.get("valve_endpoint", "")
                            ),
                            center_hz=int(body.get("center_hz", 0)),
                            power_dbm=int(body.get("power_dbm", 0)),
                            invert=body.get("invert", False),
                            trailer_residual=int(
                                body.get("trailer_residual", 0)
                            ),
                            idle_frame=str(body.get("idle_frame", "")),
                            passive_command_frame=str(
                                body.get("passive_command_frame", "")
                            ),
                            idle_observed_at=str(
                                body.get("idle_observed_at", "")
                            ),
                            passive_command_observed_at=str(
                                body.get("passive_command_observed_at", "")
                            ),
                        )
                        self._json(200, result)
                        return
                    if action == "open":
                        result = (
                            self.server.gateway.start_htv145_acceptance_open(
                                duration_seconds=int(
                                    body.get("duration_seconds", 0)
                                )
                            )
                        )
                        self._json(202, result)
                        return
                    if action == "status":
                        self._json(
                            200,
                            self.server.gateway.htv145_acceptance_status(),
                        )
                        return
                    self._json(404, {"error": "not found"})
                    return
                if valve_control_path:
                    device_prefix = f"{base}/devices/"
                    device_suffix = parsed.path[len(device_prefix) :]
                    device_id, separator, action = device_suffix.rpartition(
                        "/valve/"
                    )
                    if not separator or action not in {
                        "open",
                        "close",
                        "synchronize",
                        "probe-idle-close",
                        "probe-close-counter",
                        "probe-open",
                        "cancel-recovery",
                        "cancel-transaction",
                        "node",
                        "morning-sync",
                        "sync-now",
                        "restore-counter",
                    }:
                        self._json(404, {"error": "not found"})
                        return
                    if action == "restore-counter":
                        result = self.server.gateway.restore_htv145_counter(device_id)
                    elif action == "morning-sync":
                        result = self.server.gateway.configure_htv405_morning_sync(
                            device_id=device_id, settings=body,
                        )
                    elif action == "sync-now":
                        result = self.server.gateway.request_htv405_morning_sync(device_id=device_id)
                    elif action == "node":
                        result = self.server.gateway.assign_htv405_control_node(
                            device_id=device_id,
                            node_id=str(body.get("node_id", "")),
                        )
                    elif action == "synchronize":
                        result = (
                            self.server.gateway.synchronize_htv405_control_counter(
                                device_id=device_id,
                                next_sequence=int(
                                    body.get("next_sequence", -1)
                                ),
                                evidence_source=str(
                                    body.get("evidence_source", "")
                                ),
                                guard_duration_seconds=(
                                    int(body["guard_duration_seconds"])
                                    if body.get("guard_duration_seconds")
                                    is not None
                                    else None
                                ),
                            )
                        )
                    elif action == "probe-idle-close":
                        result = (
                            self.server.gateway.request_htv405_idle_close_probe(
                                device_id=device_id
                            )
                        )
                    elif action == "probe-close-counter":
                        result = (
                            self.server.gateway.request_htv405_close_discriminator(
                                device_id=device_id,
                                candidate_sequence=int(
                                    body.get("candidate_sequence", -1)
                                ),
                            )
                        )
                    elif action == "probe-open":
                        result = (
                            self.server.gateway.request_htv405_guarded_open_probe(
                                device_id=device_id,
                                candidate_sequence=(
                                    int(body["candidate_sequence"])
                                    if body.get("candidate_sequence") is not None
                                    else None
                                ),
                            )
                        )
                    elif action == "cancel-recovery":
                        result = (
                            self.server.gateway.cancel_htv405_control_recovery(
                                device_id=device_id
                            )
                        )
                    elif action == "cancel-transaction":
                        result = self.server.gateway.cancel_htv405_watering_transaction(
                            device_id=device_id
                        )
                    elif action in {"open", "close"}:
                        duration = body.get("duration_seconds")
                        zone = body.get("zone", 1)
                        if not isinstance(zone, int) or isinstance(zone, bool):
                            raise ValueError("valve zone must be an integer")
                        if action == "open" and (not isinstance(duration, int) or isinstance(duration, bool)):
                            raise ValueError("valve open requires an integer bounded duration")
                        result = self.server.gateway.request_valve_control(
                            device_id=device_id, action=action, zone=zone,
                            duration_seconds=duration)
                    self._json(202, {"control": result})
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
                if device_forget_path:
                    device_prefix = f"{base}/devices/"
                    device_suffix = parsed.path[len(device_prefix) :]
                    sensor_id, device_separator, device_action = (
                        device_suffix.rpartition("/")
                    )
                else:
                    sensor_id, device_separator, device_action = "", "", ""
                if device_separator and device_action == "forget":
                    result = self.server.gateway.forget_sensor(sensor_id)
                    self._json(
                        200,
                        {
                            "forgotten": result,
                            "rf_unpaired": False,
                            "detail": (
                                "local sensor association removed; "
                                "no RF unpair sent"
                            ),
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
            except PermissionError as error:
                self._json(403, {"error": str(error)})
                return
            except (RuntimeError, TypeError, ValueError) as error:
                self._json(400, {"error": str(error)})
                return
        self._json(
            405,
            {
                "error": "method not allowed",
                "detail": "no mutation is supported at this path",
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
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) > 1:
            raise ValueError("ambiguous request body framing")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("invalid Content-Length") from error
        if not 0 <= length <= 16_384:
            raise ValueError("request body exceeds 16384 bytes")
        try:
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("incomplete request body")
            def reject_constant(value):
                raise ValueError("non-finite JSON number")
            payload = json.loads(raw or b"{}", parse_constant=reject_constant)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("request body must be valid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def log_message(self, format: str, *args: Any) -> None:
        """Keep command-line output concise."""

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
