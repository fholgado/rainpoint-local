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
from typing import Any, Callable

from .esp32 import ESP32SerialTransport
from .gateway import Gateway


PROTOCOL_VERSION = 2
SUPPORTED_PROTOCOL_VERSIONS = {1, 2}
DEFAULT_NODE_PORT = 8790
MAXIMUM_LINE_BYTES = 8_192
_NODE_ID = re.compile(r"rp-[0-9a-f]{12}\Z")
_HEX_SECRET = re.compile(r"[0-9a-fA-F]{64}\Z")
_PROFILE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_HOST = re.compile(
    r"(?=.{1,253}\Z)[0-9A-Za-z](?:[0-9A-Za-z.-]*[0-9A-Za-z])?\Z"
)


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
        htv145_candidate_observer: (
            Callable[[str, dict[str, Any]], None] | None
        ) = None,
    ) -> None:
        self.gateway = gateway
        self.host = host
        self.port = port
        self.node_tokens = dict(node_tokens or {})
        self.gateway.import_node_credentials(self.node_tokens)
        # Retained for constructor compatibility. Deduplication now belongs to
        # the gateway so SDR, serial, and every network node share one boundary.
        self.deduplication_window_seconds = deduplication_window_seconds
        self.htv145_candidate_observer = htv145_candidate_observer
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
            "firmware_update_start",
            "routine_ack_configure",
            "routine_ack_revoke",
            "htv405_routine_ack_configure",
            "htv405_routine_ack_revoke",
            "valve_control_configure",
            "valve_control_sync",
            "valve_control_open",
            "valve_control_close",
            "valve_control_status",
            "htv145_control_configure",
            "htv145_control_sync",
            "htv145_control_open",
            "htv145_control_close",
            "htv145_control_status",
        }:
            raise ValueError("unsupported radio-node command")
        with self._sessions_lock:
            session = self._sessions.get(node_id)
        if session is None:
            raise ConnectionError(f"radio node is not connected: {node_id}")
        if session["protocol_version"] != 2:
            raise ValueError("radio node protocol does not permit commands")
        command_type = message.get("type")
        if command_type == "identify_start":
            required_capability = "identify"
        elif command_type == "firmware_update_start":
            required_capability = "firmware_update_trial"
        elif command_type in {"routine_ack_configure", "routine_ack_revoke"}:
            required_capability = "routine_sensor_ack_tx"
        elif command_type in {
            "htv405_routine_ack_configure",
            "htv405_routine_ack_revoke",
        }:
            required_capability = "htv405_routine_ack_tx"
        elif command_type.startswith("htv145_control_"):
            required_capability = "htv145_control_tx_candidate"
        elif command_type.startswith("valve_control_"):
            required_capability = "valve_control_tx_candidate"
        elif (
            command_type == "pairing_start"
            and message.get("profile") == "htv405_auto_candidate_v1"
        ):
            required_capability = (
                "htv405_auto_identity_pairing"
                if not message.get("factory_endpoint")
                else "valve_pairing_tx_candidate"
            )
        elif (
            command_type == "pairing_start"
            and message.get("profile") == "htv145_auto_candidate_v1"
        ):
            required_capability = "htv145_pairing_tx_candidate"
        else:
            required_capability = "sensor_pairing_tx"
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
        session: dict[str, Any] | None = None
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
            session = {
                "connection": connection,
                "stream": stream,
                "write_lock": threading.Lock(),
                "protocol_version": protocol_version,
                "capabilities": capabilities,
            }
            with self._sessions_lock:
                previous_session = self._sessions.get(node_id)
                self._active_nodes.add(node_id)
                self._sessions[node_id] = session
                session_reserved = True
            if previous_session is not None:
                previous_connection = previous_session["connection"]
                try:
                    previous_connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                previous_connection.close()
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
                hardware_profile=hello.get("hardware_profile"),
                firmware_variant=hello.get("firmware_variant"),
                firmware_channel=hello.get("firmware_channel"),
                gateway_host=hello.get("gateway_host"),
                remote_address=address[0],
                connected_at=now,
                last_seen=now,
                received_frames=0,
                duplicate_frames=0,
                invalid_messages=0,
            )
            self.gateway.notify_node_update(node_id, "radio_node_connected")
            self.gateway.restore_radio_node_ack_assignments(node_id)
            self.gateway.restore_radio_node_htv405_ack_assignments(node_id)
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
                        pairing_assigned_channel=message.get(
                            "assigned_channel"
                        ),
                        pairing_step_count=message.get("step_count"),
                        pairing_factory_endpoint=message.get(
                            "factory_endpoint"
                        ),
                        pairing_paired_endpoint=message.get(
                            "paired_endpoint"
                        ),
                        pairing_awaiting_terminal_confirmation=(
                            message.get("awaiting_terminal_confirmation") is True
                        ),
                    )
                if message.get("type") == "identify_status":
                    self.gateway.update_node(
                        node_id,
                        identify_active=message.get("active") is True,
                        identify_command_id=message.get("command_id"),
                    )
                if message.get("type") == "firmware_update_status":
                    self.gateway.update_node(
                        node_id,
                        firmware_update_state=message.get("state"),
                        firmware_update_detail=message.get("detail"),
                        firmware_update_command_id=message.get("command_id"),
                        firmware_candidate_version=message.get(
                            "candidate_version"
                        ),
                        firmware_update_received_bytes=message.get(
                            "received_bytes"
                        ),
                        firmware_update_total_bytes=message.get("total_bytes"),
                        firmware_update_boot_attempts=message.get("boot_attempts"),
                        firmware_candidate_pending=(
                            message.get("candidate_pending") is True
                        ),
                    )
                    self.gateway.notify_node_update(
                        node_id, "radio_node_firmware_update"
                    )
                if message.get("type") == "htv145_control_candidate":
                    self.gateway.update_node(
                        node_id,
                        htv145_control_candidate_state=message.get("state"),
                        htv145_control_candidate_configured=(
                            message.get("configured") is True
                        ),
                        htv145_control_candidate_counter_authenticated=(
                            message.get("counter_authenticated") is True
                        ),
                        htv145_control_candidate_pending=(
                            message.get("pending") is True
                        ),
                        htv145_control_candidate_command_id=message.get(
                            "command_id"
                        ),
                        htv145_control_candidate_confirmation=message.get(
                            "confirmation"
                        ),
                    )
                    observer = self.htv145_candidate_observer
                    if observer is not None:
                        observer(node_id, message)
                if message.get("type") == "command_error":
                    current_node = next(
                        (
                            item
                            for item in self.gateway.nodes()
                            if item.get("node_id") == node_id
                        ),
                        {},
                    )
                    if self.gateway.observe_valve_control_error(
                        node_id, message
                    ):
                        self.gateway.update_node(
                            node_id,
                            valve_control_probe_state="failed",
                            valve_control_probe_detail=message.get("error"),
                        )
                    elif message.get("command_id") == current_node.get(
                        "identify_command_id"
                    ):
                        self.gateway.update_node(
                            node_id,
                            identify_active=False,
                            identify_detail=message.get("error"),
                        )
                    elif message.get("command_id") == current_node.get(
                        "routine_ack_command_id"
                    ):
                        self.gateway.update_node(
                            node_id,
                            routine_ack_state="failed",
                            routine_ack_detail=message.get("error"),
                        )
                    elif message.get("command_id") == current_node.get(
                        "htv405_routine_ack_command_id"
                    ):
                        self.gateway.update_node(
                            node_id,
                            htv405_routine_ack_state="failed",
                            htv405_routine_ack_detail=message.get("error"),
                        )
                    else:
                        self.gateway.update_node(
                            node_id,
                            tx_armed=False,
                            pairing_state="failed",
                            pairing_command_id=message.get("command_id"),
                            pairing_detail=message.get("error"),
                        )
                    observer = self.htv145_candidate_observer
                    if observer is not None:
                        observer(node_id, message)
                self._publisher.consume_line(
                    json.dumps(message), authenticated_node_id=node_id
                )
        except (ConnectionError, OSError, socket.timeout, ValueError):
            return
        finally:
            if node_id is not None and session_reserved:
                with self._sessions_lock:
                    owns_active_session = self._sessions.get(node_id) is session
                    if owns_active_session:
                        self._active_nodes.discard(node_id)
                        self._sessions.pop(node_id, None)
                if owns_active_session:
                    self.gateway.update_node(
                        node_id, connected=False, disconnected_at=_timestamp()
                    )
                    self.gateway.notify_node_update(
                        node_id, "radio_node_disconnected"
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
        hardware_profile = hello.get("hardware_profile")
        firmware_variant = hello.get("firmware_variant")
        firmware_channel = hello.get("firmware_channel")
        gateway_host = hello.get("gateway_host")
        if (
            protocol_version not in SUPPORTED_PROTOCOL_VERSIONS
            or not isinstance(node_id, str)
            or not _NODE_ID.fullmatch(node_id)
            or not isinstance(proof, str)
            or not isinstance(capabilities, list)
            or "rx" not in capabilities
            or hello.get("tx_armed", False) is not False
            or (
                hardware_profile is not None
                and (
                    not isinstance(hardware_profile, str)
                    or not _PROFILE.fullmatch(hardware_profile)
                )
            )
            or (
                firmware_variant is not None
                and (
                    not isinstance(firmware_variant, str)
                    or not _PROFILE.fullmatch(firmware_variant)
                )
            )
            or (
                firmware_channel is not None
                and (
                    not isinstance(firmware_channel, str)
                    or not _PROFILE.fullmatch(firmware_channel)
                )
            )
            or (
                gateway_host is not None
                and (
                    not isinstance(gateway_host, str)
                    or not _HOST.fullmatch(gateway_host)
                )
            )
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
                    {
                        "rx",
                        "sensor_pairing_tx",
                        "configurable_rf_controller_identity",
                        "identify",
                        "routine_sensor_ack_tx",
                        "htv405_routine_ack_tx",
                        "valve_pairing_tx_candidate",
                        "htv405_auto_identity_pairing",
                        "htv145_pairing_tx_candidate",
                        "valve_control_tx_candidate",
                        "htv145_control_tx_candidate",
                        "paired_sensor_recovery_tx",
                        "firmware_update_trial",
                    }
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
