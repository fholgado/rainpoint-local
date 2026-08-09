"""Authenticated receive-only TCP listener for ESP32 radio nodes."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import socket
import threading
import time
from datetime import datetime, timezone
from typing import Any

from .esp32 import ESP32SerialTransport
from .gateway import Gateway


PROTOCOL_VERSION = 1
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
        self.deduplication_window_seconds = deduplication_window_seconds
        self._publisher = ESP32SerialTransport(gateway, device="network")
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._deduplication_lock = threading.Lock()
        self._recent_frames: dict[str, tuple[str, float]] = {}
        self._sessions_lock = threading.Lock()
        self._active_nodes: set[str] = set()

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
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._socket = None
        self._thread = None

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
            node_id = self._authenticate(hello, nonce)
            if node_id is None:
                self._send(stream, {"type": "node_rejected"})
                return
            with self._sessions_lock:
                if node_id in self._active_nodes:
                    self._send(
                        stream,
                        {"type": "node_rejected", "reason": "already_connected"},
                    )
                    return
                self._active_nodes.add(node_id)
                session_reserved = True
            self._send(
                stream,
                {
                    "type": "node_authenticated",
                    "protocol_version": PROTOCOL_VERSION,
                    "node_id": node_id,
                },
            )
            now = _timestamp()
            self.gateway.update_node(
                node_id,
                connected=True,
                authenticated=True,
                mode="receive_only",
                firmware_version=hello.get("firmware_version"),
                remote_address=address[0],
                connected_at=now,
                last_seen=now,
                received_frames=0,
                duplicate_frames=0,
                invalid_messages=0,
            )
            received_frames = 0
            duplicate_frames = 0
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
                    frame = message.get("frame")
                    if isinstance(frame, str) and self._duplicate(frame, node_id):
                        duplicate_frames += 1
                        self.gateway.update_node(
                            node_id, duplicate_frames=duplicate_frames
                        )
                        continue
                    received_frames += 1
                    self.gateway.update_node(
                        node_id, received_frames=received_frames
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
                self.gateway.update_node(
                    node_id, connected=False, disconnected_at=_timestamp()
                )
            try:
                stream.close()
            finally:
                connection.close()

    def _authenticate(
        self, hello: dict[str, Any] | None, nonce: str
    ) -> str | None:
        if hello is None or hello.get("type") != "node_hello":
            return None
        node_id = hello.get("node_id")
        proof = hello.get("proof")
        if (
            hello.get("protocol_version") != PROTOCOL_VERSION
            or hello.get("mode") != "receive_only"
            or not isinstance(node_id, str)
            or not _NODE_ID.fullmatch(node_id)
            or not isinstance(proof, str)
        ):
            return None
        token = self.node_tokens.get(node_id)
        if token is None:
            return None
        payload = f"rainpoint-node-v1\n{nonce}\n{node_id}".encode()
        expected = hmac.new(token.encode(), payload, hashlib.sha256).hexdigest()
        return node_id if hmac.compare_digest(proof, expected) else None

    def _duplicate(self, frame: str, node_id: str) -> bool:
        """Suppress only the same RF frame heard by a different receiver."""
        now = time.monotonic()
        with self._deduplication_lock:
            previous = self._recent_frames.get(frame)
            duplicate = bool(
                previous
                and previous[0] != node_id
                and now - previous[1] <= self.deduplication_window_seconds
            )
            if not duplicate:
                self._recent_frames[frame] = (node_id, now)
            if len(self._recent_frames) > 512:
                cutoff = now - max(self.deduplication_window_seconds, 1)
                self._recent_frames = {
                    key: value
                    for key, value in self._recent_frames.items()
                    if value[1] >= cutoff
                }
            return duplicate

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
