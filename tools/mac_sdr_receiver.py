#!/usr/bin/env python3
"""Managed, receive-only rtl_433 journal with optional live TLS forwarding.

No IQ recording, RF commands, historical replay, automatic deletion or changes
to HA configuration. A full journal stops capture until the operator archives it.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import plistlib
import re
import selectors
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rainpointd_addon"))
from rainpointd.rf import normalize_row
from rainpointd.rtl433 import rtl_433_command
from rainpointd.secure_transport import client_context

MAX_LINE = 65536


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def receiver_command(config):
    executable = Path(config["rtl433_path"])
    if not executable.is_absolute():
        raise ValueError("rtl433_path must be absolute")
    command = rtl_433_command(config.get("frequency_hz", 433700000), config.get("sample_rate", 2000000))
    command[0] = str(executable)
    device = str(config.get("device", "0"))
    if not re.fullmatch(r"[A-Za-z0-9._-]+", device):
        raise ValueError("invalid SDR device selector")
    command += ["-d", device, "-F", "log"]
    for key in ("frequency_hz", "sample_rate"):
        if key in config and (type(config[key]) is not int or config[key] <= 0):
            raise ValueError(f"{key} must be a positive integer")
    return command


def launch_agent(config_path: Path, python_path: Path):
    """Return a launchd definition; never install or start it implicitly."""
    if not config_path.is_absolute() or not python_path.is_absolute():
        raise ValueError("launchd requires absolute paths")
    return {"Label": "org.rainpoint.local.sdr", "RunAtLoad": True,
            # The runner reconnects itself. Do not restart after storage-full.
            "KeepAlive": False, "ProcessType": "Background",
            "ProgramArguments": [str(python_path), str(Path(__file__).resolve()),
                                 "--config", str(config_path)]}


def normalize_live_line(line: bytes):
    """Preserve source time verbatim alongside explicit UTC receipt time."""
    if len(line) > MAX_LINE:
        return None
    try:
        event = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(event, dict) or not isinstance(event.get("rows"), list):
        return None
    frames = []
    for row in event["rows"]:
        try:
            frames.append(normalize_row(row)["frame_hex"])
        except (ValueError, TypeError, KeyError):
            continue
    return {"schema_version": 1, "received_at": utc_now(),
            "source_time": event.get("time"), "decoder_timezone": "UTC",
            "event": event, "frames": frames}


class LiveForwarder:
    """Receive-only node-protocol adapter; disconnected frames are never replayed."""

    def __init__(self, config):
        self.host = config["host"]
        self.port = int(config.get("port", 8790))
        if not isinstance(self.host, str) or not self.host or not 1 <= self.port <= 65535:
            raise ValueError("invalid gateway address")
        self.node_id = config["node_id"]
        token_path = Path(config["token_file"])
        if (not token_path.is_absolute() or not token_path.is_file() or token_path.is_symlink()
                or token_path.stat().st_mode & 0o077):
            raise ValueError("token_file must be an absolute, private regular file (0600)")
        self.token = token_path.read_text().strip()
        if not re.fullmatch(r"rp-[0-9a-f]{12}", self.node_id) or not re.fullmatch(r"[0-9a-f]{64}", self.token):
            raise ValueError("invalid dedicated receiver identity or credential")
        self.context = client_context(self.token, identity=self.node_id)
        self.connection = None
        self.stream = None
        self.retry_at = 0.0
        self.sent = 0
        self.dropped = 0

    def close(self):
        if self.stream is not None:
            self.stream.close()
        if self.connection is not None:
            self.connection.close()
        self.stream = self.connection = None

    def _send(self, message):
        self.connection.sendall(json.dumps(message).encode() + b"\n")

    def _read(self):
        value = json.loads(self.stream.readline(MAX_LINE + 1))
        if not isinstance(value, dict):
            raise ValueError("invalid receiver handshake")
        return value

    def _connect(self):
        raw = socket.create_connection((self.host, self.port), timeout=1)
        try:
            self.connection = self.context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise
        self.stream = self.connection.makefile("rb")
        challenge = self._read()
        nonce = challenge.get("nonce")
        if challenge.get("type") != "node_challenge" or not isinstance(nonce, str):
            raise ValueError("invalid receiver challenge")
        proof = hmac.new(self.token.encode(),
            f"rainpoint-node-v1\n{nonce}\n{self.node_id}".encode(), hashlib.sha256).hexdigest()
        self._send({"type": "node_hello", "protocol_version": 1,
                    "node_id": self.node_id, "mode": "receive_only", "capabilities": ["rx"],
                    "tx_armed": False, "proof": proof})
        reply = self._read()
        if (reply.get("type") != "node_authenticated" or reply.get("node_id") != self.node_id
                or reply.get("protocol_version") != 1):
            raise ValueError("receiver authentication failed")

    def send_live(self, record=None):
        """Send this observation once or a heartbeat. No stored data is read."""
        frames = record["frames"] if record else []
        if time.monotonic() < self.retry_at:
            self.dropped += len(frames)
            return
        try:
            if self.connection is None:
                self._connect()
            self._send({"type": "node_health", "node_id": self.node_id})
            for frame in frames:
                message = {"type": "rainpoint_rf", "node_id": self.node_id, "radio": "rtl_sdr", "frame": frame}
                rssi = record["event"].get("rssi")
                if type(rssi) in (int, float):
                    message["rssi_dbm"] = rssi
                self._send(message)
                self.sent += 1
        except (OSError, ValueError):
            self.dropped += len(frames)
            self.close()
            self.retry_at = time.monotonic() + 30


def run(config, *, stop=None, command=None):
    """Run one locked, storage-bounded capture; return a reason on clean stop."""
    directory = Path(config["output_directory"])
    if not directory.is_absolute() or directory.is_symlink():
        raise ValueError("output_directory must be an absolute, dedicated directory")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.stat().st_mode & 0o077:
        raise ValueError("output_directory must be private (0700)")
    limit = config.get("max_journal_bytes", 128 * 1024 * 1024)
    if type(limit) is not int or not 1024 <= limit <= 1024 * 1024 * 1024:
        raise ValueError("journal budget must be 1 KiB–1 GiB")
    for name in ("receiver.lock", "events.jsonl", "status.json", "status.tmp"):
        if (directory / name).is_symlink():
            raise ValueError("receiver output must not contain symlinks")
    stopped = stop or (lambda: False)
    forwarder = None
    process = None
    status = {"schema_version": 1, "started_at": utc_now(), "records": 0,
              "decoder_restarts": 0, "invalid_lines": 0, "state": "starting"}

    def save_status(state):
        status.update(state=state, updated_at=utc_now())
        if forwarder:
            status.update(forwarded=forwarder.sent, forward_dropped=forwarder.dropped)
        temporary = directory / "status.tmp"
        temporary.write_text(json.dumps(status, sort_keys=True) + "\n")
        temporary.replace(directory / "status.json")

    with (directory / "receiver.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        journal = directory / "events.jsonl"
        size = journal.stat().st_size if journal.exists() else 0
        try:
            if config.get("forward"):
                forwarder = LiveForwarder(config["forward"])
            with journal.open("ab", buffering=0) as output:
                last_health = 0
                while not stopped():
                    if size >= limit:
                        save_status("storage_full")
                        return "storage_full"
                    process = subprocess.Popen(command or receiver_command(config), stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, env={**os.environ, "TZ": "UTC"})
                    pending = b""
                    discard_line = False
                    save_status("listening")
                    with selectors.DefaultSelector() as selector:
                        selector.register(process.stdout, selectors.EVENT_READ)
                        while not stopped():
                            if time.monotonic() - last_health >= 25:
                                if forwarder:
                                    forwarder.send_live()
                                save_status("listening")
                                last_health = time.monotonic()
                            if not selector.select(timeout=0.5):
                                continue
                            chunk = os.read(process.stdout.fileno(), 4096)
                            if not chunk:
                                break
                            pending += chunk
                            while b"\n" in pending:
                                line, pending = pending.split(b"\n", 1)
                                record = None if discard_line else normalize_live_line(line)
                                discard_line = False
                                if record is None:
                                    status["invalid_lines"] += 1
                                    if line and not line.startswith(b"{"):
                                        status["decoder_message"] = line[:240].decode("utf-8", errors="replace")
                                    continue
                                encoded = (json.dumps(record, sort_keys=True) + "\n").encode()
                                if size + len(encoded) > limit:
                                    save_status("storage_full")
                                    return "storage_full"
                                output.write(encoded)
                                size += len(encoded)
                                status["records"] += 1
                                if forwarder:
                                    forwarder.send_live(record)
                            if len(pending) > MAX_LINE:
                                pending = b""
                                discard_line = True
                    if stopped():
                        break
                    process.stdout.close()
                    status["decoder_exit_code"] = process.wait(timeout=3)
                    status["decoder_restarts"] += 1
                    save_status("decoder_disconnected")
                    # Avoid hot looping on USB disconnect or a decoder error.
                    deadline = time.monotonic() + 10
                    while not stopped() and time.monotonic() < deadline:
                        time.sleep(0.2)
                save_status("stopped")
                return "stopped"
        except Exception:
            save_status("failed")
            raise
        finally:
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                process.stdout.close()
            if forwarder:
                forwarder.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--print-launch-agent", action="store_true")
    args = parser.parse_args()
    if args.print_launch_agent:
        sys.stdout.buffer.write(plistlib.dumps(launch_agent(args.config.resolve(), Path(sys.executable))))
        return 0
    stopping = False
    def stop_handler(signum, frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    try:
        config = json.loads(args.config.read_text())
        receiver_command(config)
        result = run(config, stop=lambda: stopping)
        return 0 if result == "stopped" else 1
    except (OSError, ValueError, KeyError, TypeError):
        # A malformed config may contain credentials: never echo its contents.
        print("Receiver stopped: check private config, output budget, lock and SDR executable.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
