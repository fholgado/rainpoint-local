"""Authenticated TCP listener for ESP32 radio-node telemetry and status."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import socket
import threading
from datetime import datetime, timezone
from typing import Any

from .esp32 import ESP32SerialTransport
from .gateway import Gateway


PROTOCOL_VERSION = 2
SUPPORTED_PROTOCOL_VERSIONS = {1, 2}
DEFAULT_NODE_PORT = 8790
MAXIMUM_LINE_BYTES = 8_192
_NODE_ID = re.compile(r"rp-[0-9a-f]{12}\Z")
_HEX_SECRET = re.compile(r"[0-9a-fA-F]{64}\Z")


def load_node_tokens(raw: str | None) -> dict[str, str]:
    """Parse the node-id to enrollment-token map from add-on configuration."""
    if raw is None or not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("node_tokens must be a JSON object") from error
    if not isinstance(value, dict):
        raise ValueError("node_tokens must be a JSON object")
    result: dict[str, str] = {}
    for node_id, token in value.items():
        if not isinstance(node_id, str) or not _NODE_ID.fullmatch(node_id):
            raise ValueError(f"invalid node id: {node_id!r}")
        if not isinstance(token, str) or not _HEX_SECRET.fullmatch(token):
            raise ValueError(f"invalid token for node {node_id}")
        result[node_id] = token.lower()
    return result


class ESP32NetworkServer:
    """Accept authenticated telemetry from multiple Wi-Fi radio nodes."""

    def __init__(
        self,
        gateway: Gateway,
        *,
        host: str = "0.0.0.0",
        port: int = DEFAULT_NODE_PORT,
        node_tokens: dict[str, str] | None = None,
        deduplication_window_seconds: float = 0.25,
    ) -> None:
        self.gateway = gateway
        self.host = host
        self.port = port
        self.node_tokens = dict(node_tokens or {})
        self.gateway.import_node_credentials(self.node_tokens)
        # Retained for constructor compatibility. Deduplication now belongs to
        # the gateway so SDR, serial, and every network node share one boundary.
        self.deduplication_window_seconds = deduplication_window_seconds
        self._publisher = ESP32SerialTransport(gateway, device="network")
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._sessions_lock = threading.Lock()
        self._active_nodes: set[str] = set()
        self._sessions: dict[str, dict[str, Any]] = {}

    @property
    def server_port(self) -> int:
        """Return the bound port, including when an ephemeral port was used."""
        listener = self._socket
        return listener.getsockname()[1] if listener is not None else self.port

    def start(self) -> None:
        """Bind the listener and start accepting nodes in the background."""
        if self._thread is not None:
            return
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((self.host, self.port))
        except Exception:
            listener.close()
            raise
        listener.listen(8)
        listener.settimeout(1)
        self._socket = listener
        self._publisher.seed()
        self.gateway.set_node_command_sender(self.send_command)
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._accept,
            name="rainpoint-node-listener",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop accepting new nodes and close the listener."""
        self._stop.set()
        listener = self._socket
        if listener is not None:
            listener.close()
        with self._sessions_lock:
            active_connections = [
                session["connection"] for session in self._sessions.values()
            ]
        for connection in active_connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._socket = None
        self._thread = None
        self.gateway.set_node_command_sender(None)

    def send_command(self, node_id: str, message: dict[str, Any]) -> None:
        """Send one bounded command to an authenticated protocol-v2 node."""
        if message.get("type") not in {
            "pairing_start",
            "pairing_cancel",
            "identify_start",
        }:
            raise ValueError("unsupported radio-node command")
        with self._sessions_lock:
            session = self._sessions.get(node_id)
        if session is None:
            raise ConnectionError(f"radio node is not connected: {node_id}")
        if session["protocol_version"] != 2:
            raise ValueError("radio node protocol does not permit commands")
        required_capability = (
            "identify"
            if message.get("type") == "identify_start"
            else "sensor_pairing_tx"
        )
        if required_capability not in session["capabilities"]:
            raise ValueError(
                f"radio node lacks {required_capability} capability"
            )
        with session["write_lock"]:
            self._send(session["stream"], message)

    def _accept(self) -> None:
        while not self._stop.is_set():
            listener = self._socket
            if listener is None:
                return
            try:
                connection, address = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            threading.Thread(
                target=self._handle_connection,
                args=(connection, address),
                name="rainpoint-node-session",
                daemon=True,
            ).start()

    def _handle_connection(
        self, connection: socket.socket, address: tuple[str, int]
    ) -> None:
        node_id: str | None = None
        session_reserved = False
        connection.settimeout(75)
        stream = connection.makefile("rwb", buffering=0)
        try:
            nonce = secrets.token_hex(32)
            self._send(
                stream,
                {
                    "type": "node_challenge",
                    "protocol_version": PROTOCOL_VERSION,
                    "nonce": nonce,
                },
            )
            hello = self._receive(stream)
            authenticated = self._authenticate(hello, nonce)
            if authenticated is None:
                self._send(stream, {"type": "node_rejected"})
                return
            node_id, protocol_version = authenticated
            capabilities = list(hello.get("capabilities", ["rx"]))
            with self._sessions_lock:
                if node_id in self._active_nodes:
                    self._send(
                        stream,
                        {"type": "node_rejected", "reason": "already_connected"},
                    )
                    return
                self._active_nodes.add(node_id)
                self._sessions[node_id] = {
                    "connection": connection,
                    "stream": stream,
                    "write_lock": threading.Lock(),
                    "protocol_version": protocol_version,
                    "capabilities": capabilities,
                }
                session_reserved = True
            authenticated_message = {
                "type": "node_authenticated",
                "protocol_version": protocol_version,
                "node_id": node_id,
            }
            if protocol_version == 2:
                token = self._credential(node_id)
                if token is None:
                    return
                server_payload = (
                    f"rainpoint-gateway-v2\n{nonce}\n{node_id}".encode()
                )
                authenticated_message["server_proof"] = hmac.new(
                    token.encode(), server_payload, hashlib.sha256
                ).hexdigest()
            self._send(stream, authenticated_message)
            self.gateway.complete_radio_node_adoption(node_id)
            now = _timestamp()
            self.gateway.update_node(
                node_id,
                connected=True,
                authenticated=True,
                protocol_version=protocol_version,
                mode=hello.get("mode"),
                capabilities=capabilities,
                tx_armed=False,
                firmware_version=hello.get("firmware_version"),
                remote_address=address[0],
                connected_at=now,
                last_seen=now,
                received_frames=0,
                duplicate_frames=0,
                invalid_messages=0,
            )
            received_frames = 0
            invalid_messages = 0
            while not self._stop.is_set():
                message = self._receive(stream)
                if message is None:
                    return
                now = _timestamp()
                self.gateway.update_node(node_id, last_seen=now)
                if message.get("node_id") not in (None, node_id):
                    invalid_messages += 1
                    self.gateway.update_node(
                        node_id, invalid_messages=invalid_messages
                    )
                    continue
                if message.get("type") == "rainpoint_rf":
                    received_frames += 1
                    self.gateway.update_node(
                        node_id, received_frames=received_frames
                    )
                if message.get("type") == "pairing_tx_status":
                    self.gateway.update_node(
                        node_id,
                        tx_armed=message.get("tx_armed") is True,
                        pairing_state=message.get("state"),
                        pairing_completed_steps=message.get("completed_steps"),
                        pairing_detail=message.get("detail"),
                        pairing_command_id=message.get("command_id"),
                        pairing_failure_reason=message.get("failure_reason"),
                    )
                if message.get("type") == "identify_status":
                    self.gateway.update_node(
                        node_id,
                        identify_active=message.get("active") is True,
                        identify_command_id=message.get("command_id"),
                    )
                if message.get("type") == "command_error":
                    current_node = next(
                        (
                            item
                            for item in self.gateway.nodes()
                            if item.get("node_id") == node_id
                        ),
                        {},
                    )
                    if message.get("command_id") == current_node.get(
                        "identify_command_id"
                    ):
                        self.gateway.update_node(
                            node_id,
                            identify_active=False,
                            identify_detail=message.get("error"),
                        )
                    else:
                        self.gateway.update_node(
                            node_id,
                            tx_armed=False,
                            pairing_state="failed",
                            pairing_command_id=message.get("command_id"),
                            pairing_detail=message.get("error"),
                        )
                self._publisher.consume_line(
                    json.dumps(message), authenticated_node_id=node_id
                )
        except (ConnectionError, OSError, socket.timeout, ValueError):
            return
        finally:
            if node_id is not None and session_reserved:
                with self._sessions_lock:
                    self._active_nodes.discard(node_id)
                    self._sessions.pop(node_id, None)
                self.gateway.update_node(
                    node_id, connected=False, disconnected_at=_timestamp()
                )
            try:
                stream.close()
            finally:
                connection.close()

    def _authenticate(
        self, hello: dict[str, Any] | None, nonce: str
    ) -> tuple[str, int] | None:
        if hello is None or hello.get("type") != "node_hello":
            return None
        node_id = hello.get("node_id")
        proof = hello.get("proof")
        capabilities = hello.get("capabilities", ["rx"])
        protocol_version = hello.get("protocol_version")
        if (
            protocol_version not in SUPPORTED_PROTOCOL_VERSIONS
            or not isinstance(node_id, str)
            or not _NODE_ID.fullmatch(node_id)
            or not isinstance(proof, str)
            or not isinstance(capabilities, list)
            or "rx" not in capabilities
            or hello.get("tx_armed", False) is not False
        ):
            return None
        if protocol_version == 1:
            if hello.get("mode") != "receive_only" or any(
                capability not in {"rx", "pairing_plan", "pairing_tx_bench"}
                for capability in capabilities
            ):
                return None
        else:
            capability_set = set(capabilities)
            if (
                hello.get("mode") != "local_radio_node"
                or not {"rx", "sensor_pairing_tx"}.issubset(capability_set)
                or not capability_set.issubset(
                    {"rx", "sensor_pairing_tx", "identify"}
                )
            ):
                return None
        token = self._credential(node_id)
        if token is None:
            return None
        payload = (
            f"rainpoint-node-v{protocol_version}\n{nonce}\n{node_id}".encode()
        )
        expected = hmac.new(token.encode(), payload, hashlib.sha256).hexdigest()
        return (
            (node_id, protocol_version)
            if hmac.compare_digest(proof, expected)
            else None
        )

    def _credential(self, node_id: str) -> str | None:
        """Resolve a managed credential with an ephemeral-test fallback."""
        return (
            self.gateway.radio_node_credential(node_id)
            or self.gateway.pending_radio_node_credential(node_id)
            or self.node_tokens.get(node_id)
        )

    @staticmethod
    def _send(stream: Any, message: dict[str, Any]) -> None:
        stream.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")

    @staticmethod
    def _receive(stream: Any) -> dict[str, Any] | None:
        line = stream.readline(MAXIMUM_LINE_BYTES + 1)
        if not line:
            return None
        if len(line) > MAXIMUM_LINE_BYTES or not line.endswith(b"\n"):
            raise ValueError("node message exceeds maximum line length")
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("node message is not valid JSON") from error
        if not isinstance(value, dict):
            raise ValueError("node message must be a JSON object")
        return value


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
