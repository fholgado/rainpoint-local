#!/usr/bin/env python3
"""Persist read-only RainPoint snapshots/events independently of agent sessions.

Run collect periodically from a host scheduler. The first run fixes the observation
window; later runs cannot extend it. The SQLite output is installation-private.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import ssl
from typing import Callable
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, HTTPSHandler


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def gateway_getter(base: str, token: str) -> Callable[[str], dict]:
    """Read-only TLS-PSK client; no plaintext fallback or redirected requests.

    Kept standalone for HA shell_command deployment. Its TLS settings are
    contract-tested against rainpointd.secure_transport.client_context.
    """
    parsed = urlsplit(base)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/")):
        raise ValueError("an HTTPS gateway origin is required")
    key = token.encode()
    if not 32 <= len(key) <= 256:
        raise ValueError("invalid management credential")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # Peer authenticated by PSK, not X.509.
    context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_2
    context.set_ciphers("ECDHE-PSK-CHACHA20-POLY1305:PSK-AES128-GCM-SHA256")
    context.set_psk_client_callback(lambda hint: ("management", key))
    opener = build_opener(HTTPSHandler(context=context), NoRedirect())

    def fetch(resource: str) -> dict:
        # Only collector resources; this helper cannot issue management writes.
        if resource not in {"devices", "nodes", "receivers"} and not (
                resource.startswith("events?since=") and resource[13:].isdigit()):
            raise ValueError("unsupported collection resource")
        with opener.open(f"{base.rstrip('/')}/api/v1/{resource}", timeout=5) as response:
            return json.load(response)
    return fetch


def ha_credentials(config: Path, entry_id: str | None) -> tuple[str, str]:
    """Reuse one existing HA entry privately; never modify its credential."""
    entries = json.loads((config / ".storage/core.config_entries").read_text())
    matches = [entry for entry in entries["data"]["entries"]
               if entry["domain"] == "rainpoint_local"
               and (entry_id is None or entry["entry_id"] == entry_id)]
    if len(matches) != 1:
        raise ValueError("select exactly one RainPoint entry with --entry-id")
    data = matches[0]["data"]
    host = data["host"]
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"https://{host}:{data['port']}", data["registry_write_token"]


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=1)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS snapshots (at TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events (event_id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS observations (at TEXT, kind TEXT, detail TEXT);
    """)
    return db


def collect(
    db: sqlite3.Connection, getter: Callable[[str], dict], *,
    now: datetime, hours: float = 72, max_pages: int = 8,
) -> dict:
    """Collect a bounded batch atomically; failures retain the old cursor."""
    if not 0 < hours <= 168 or not 1 <= max_pages <= 8:
        raise ValueError("hours must be in (0,168]; max_pages must be in [1,8]")
    at = now.isoformat()
    # Serialize scheduler invocations; never reset a previously fixed window.
    db.execute("BEGIN IMMEDIATE")
    try:
        meta = dict(db.execute("SELECT key,value FROM metadata"))
        if not meta:
            meta = {"started_at": at, "ends_at": (now + timedelta(hours=hours)).isoformat(),
                    "cursor": "0", "state": "collecting"}
            db.executemany("INSERT INTO metadata VALUES (?,?)", meta.items())
            db.commit()
            db.execute("BEGIN IMMEDIATE")
        if meta["state"] == "completed":
            db.commit()
            return summary(db)
        snapshot = {resource: getter(resource) for resource in ("devices", "nodes", "receivers")}
        cursor = int(meta["cursor"])
        if cursor == 0:
            # Start at current inventory, not at the beginning of unrelated history.
            cursor = max((int(d.get("last_event_id") or 0)
                          for d in snapshot["devices"].get("devices", [])), default=0)
        for _ in range(max_pages):
            batch = getter(f"events?since={cursor}").get("events", [])
            if not batch:
                break
            ids = [int(e["event_id"]) for e in batch]
            if ids != sorted(set(ids)) or ids[0] <= cursor:
                raise ValueError("event page does not advance monotonically")
            expected = cursor + 1
            for event in batch:
                event_id = int(event["event_id"])
                if event_id != expected:
                    db.execute("INSERT INTO observations VALUES (?,?,?)",
                               (at, "event_gap", json.dumps({"expected": expected, "received": event_id})))
                db.execute("INSERT OR IGNORE INTO events VALUES (?,?)",
                           (event_id, json.dumps(event, separators=(',', ':'))))
                expected = event_id + 1
            cursor = ids[-1]
            if len(batch) < 1000:
                break
        db.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?)",
                   (at, json.dumps(snapshot, separators=(',', ':'))))
        db.execute("UPDATE metadata SET value=? WHERE key='cursor'", (str(cursor),))
        if now >= datetime.fromisoformat(meta["ends_at"]):
            db.execute("UPDATE metadata SET value='completed' WHERE key='state'")
        db.commit()
    except Exception as exc:
        db.rollback()
        # Record type only: URLs, credentials, and response bodies are not error logs.
        db.execute("INSERT INTO observations VALUES (?,?,?)", (at, "collection_error", type(exc).__name__))
        db.commit()
        raise
    return summary(db)


def summary(db: sqlite3.Connection) -> dict:
    meta = dict(db.execute("SELECT key,value FROM metadata"))
    count, first, last = db.execute("SELECT COUNT(*),MIN(at),MAX(at) FROM snapshots").fetchone()
    anomalies = dict(db.execute("SELECT kind,COUNT(*) FROM observations GROUP BY kind"))
    return {**meta, "snapshots": count, "first_snapshot": first, "last_snapshot": last,
            "events": db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            "observations": anomalies,
            "qualification": "evidence_only_not_automatic_pass"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("collect", "status"))
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--gateway-url")
    parser.add_argument("--token-file", type=Path)
    parser.add_argument("--ha-config", type=Path)
    parser.add_argument("--entry-id")
    parser.add_argument("--hours", type=float, default=72)
    parser.add_argument("--status-output", type=Path)
    args = parser.parse_args()
    getter = None
    if args.command == "collect":
        if args.ha_config and not (args.gateway_url or args.token_file):
            base, token = ha_credentials(args.ha_config, args.entry_id)
        elif args.gateway_url and args.token_file and not args.ha_config:
            base, token = args.gateway_url, args.token_file.read_text().strip()
        else:
            parser.error("collect requires --ha-config or --gateway-url with --token-file")
        getter = gateway_getter(base, token)
    db = connect(args.database)
    try:
        result = (collect(db, getter,
                          now=utcnow(), hours=args.hours)
                  if args.command == "collect" else summary(db))
        encoded = json.dumps(result, sort_keys=True)
        if args.status_output:
            temporary = args.status_output.with_suffix(".tmp")
            temporary.write_text(encoded + "\n")
            temporary.replace(args.status_output)
        print(encoded)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
