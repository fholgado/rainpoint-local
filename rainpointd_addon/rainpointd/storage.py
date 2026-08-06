"""Persistent RF event and endpoint inventory storage."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class SQLiteEventStore:
    """Persist normalized events and summarize observed RF endpoints."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY,
                observed_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS endpoints (
                endpoint TEXT PRIMARY KEY,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                frame_count INTEGER NOT NULL DEFAULT 0,
                as_a_count INTEGER NOT NULL DEFAULT 0,
                as_b_count INTEGER NOT NULL DEFAULT 0,
                as_sensor_count INTEGER NOT NULL DEFAULT 0,
                last_message_type INTEGER,
                last_frame TEXT NOT NULL,
                last_rssi REAL
            );
            """
        )
        self._connection.commit()

    def close(self) -> None:
        """Close the database connection."""
        self._connection.close()

    def append(self, event: dict[str, Any]) -> None:
        """Store one event and update endpoint inventory atomically."""
        self._connection.execute(
            "INSERT INTO events(event_id, observed_at, event_type, payload) "
            "VALUES (?, ?, ?, ?)",
            (
                event["event_id"],
                event["observed_at"],
                event["event_type"],
                json.dumps(event, separators=(",", ":"), sort_keys=True),
            ),
        )
        self._update_endpoints(event)
        self._connection.commit()

    def recent_events(self, limit: int) -> list[dict[str, Any]]:
        """Return the newest events in chronological order."""
        rows = self._connection.execute(
            "SELECT payload FROM events ORDER BY event_id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [json.loads(row["payload"]) for row in reversed(rows)]

    def events(self, since: int = 0, limit: int = 1_000) -> list[dict[str, Any]]:
        """Return one chronological page newer than an event ID."""
        rows = self._connection.execute(
            "SELECT payload FROM events WHERE event_id > ? "
            "ORDER BY event_id LIMIT ?",
            (since, limit),
        ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def latest_event_id(self) -> int:
        """Return the newest persistent event ID."""
        row = self._connection.execute(
            "SELECT COALESCE(MAX(event_id), 0) AS event_id FROM events"
        ).fetchone()
        return int(row["event_id"])

    def event_count(self) -> int:
        """Return the number of stored events."""
        row = self._connection.execute(
            "SELECT COUNT(*) AS event_count FROM events"
        ).fetchone()
        return int(row["event_count"])

    def endpoints(self) -> list[dict[str, Any]]:
        """Return stable endpoint discovery summaries."""
        rows = self._connection.execute(
            "SELECT * FROM endpoints ORDER BY endpoint"
        ).fetchall()
        return [dict(row) for row in rows]

    def _update_endpoints(self, event: dict[str, Any]) -> None:
        state = event.get("state", {})
        roles: dict[str, set[str]] = {}
        for key, role in (
            ("rf_endpoint_a", "a"),
            ("rf_endpoint_b", "b"),
            ("rf_endpoint", "sensor"),
        ):
            endpoint = state.get(key)
            if endpoint:
                roles.setdefault(str(endpoint), set()).add(role)

        for endpoint, endpoint_roles in roles.items():
            self._connection.execute(
                """
                INSERT INTO endpoints(
                    endpoint, first_seen, last_seen, frame_count,
                    as_a_count, as_b_count, as_sensor_count,
                    last_message_type, last_frame, last_rssi
                ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(endpoint) DO UPDATE SET
                    last_seen=excluded.last_seen,
                    frame_count=endpoints.frame_count + 1,
                    as_a_count=endpoints.as_a_count + excluded.as_a_count,
                    as_b_count=endpoints.as_b_count + excluded.as_b_count,
                    as_sensor_count=(
                        endpoints.as_sensor_count + excluded.as_sensor_count
                    ),
                    last_message_type=COALESCE(
                        excluded.last_message_type,
                        endpoints.last_message_type
                    ),
                    last_frame=excluded.last_frame,
                    last_rssi=excluded.last_rssi
                """,
                (
                    endpoint,
                    event["observed_at"],
                    event["observed_at"],
                    int("a" in endpoint_roles),
                    int("b" in endpoint_roles),
                    int("sensor" in endpoint_roles),
                    state.get("rf_message_type"),
                    event["raw"],
                    state.get("rf_rssi_db"),
                ),
            )
