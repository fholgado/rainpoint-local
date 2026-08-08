"""Persistent RF event and endpoint inventory storage."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
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
            CREATE TABLE IF NOT EXISTS device_metrics (
                device_id TEXT PRIMARY KEY,
                first_observed_at TEXT NOT NULL,
                last_observed_at TEXT NOT NULL,
                report_count INTEGER NOT NULL DEFAULT 0,
                interval_count INTEGER NOT NULL DEFAULT 0,
                total_interval_seconds REAL NOT NULL DEFAULT 0,
                longest_report_gap_seconds REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS device_registry (
                endpoint TEXT PRIMARY KEY,
                device_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                model TEXT NOT NULL,
                area TEXT,
                accepted_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS learning_session (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                session_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                baseline_endpoints TEXT NOT NULL
            );
            """
        )
        self._backfill_device_metrics()
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
        self._update_device_metrics(event)
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

    def device_metrics(self) -> dict[str, dict[str, Any]]:
        """Return persistent report-cadence metrics by device ID."""
        rows = self._connection.execute(
            "SELECT * FROM device_metrics ORDER BY device_id"
        ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = dict(row)
            interval_count = int(item.pop("interval_count"))
            total = float(item.pop("total_interval_seconds"))
            item["average_report_interval_seconds"] = (
                round(total / interval_count, 3) if interval_count else None
            )
            result[str(item.pop("device_id"))] = item
        return result

    def registry(self) -> list[dict[str, Any]]:
        """Return accepted local device registrations."""
        rows = self._connection.execute(
            "SELECT * FROM device_registry ORDER BY name, endpoint"
        ).fetchall()
        return [dict(row) for row in rows]

    def accept_endpoint(
        self,
        *,
        endpoint: str,
        device_id: str,
        name: str,
        model: str,
        area: str | None,
        accepted_at: str,
    ) -> dict[str, Any]:
        """Accept or update one observed endpoint in the local registry."""
        self._connection.execute(
            """
            INSERT INTO device_registry(
                endpoint, device_id, name, model, area,
                accepted_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET
                name=excluded.name,
                model=excluded.model,
                area=excluded.area,
                updated_at=excluded.updated_at
            """,
            (
                endpoint,
                device_id,
                name,
                model,
                area,
                accepted_at,
                accepted_at,
            ),
        )
        self._connection.commit()
        return self.registry_device(device_id)

    def registry_device(self, device_id: str) -> dict[str, Any]:
        """Return one accepted device or raise KeyError."""
        row = self._connection.execute(
            "SELECT * FROM device_registry WHERE device_id = ?", (device_id,)
        ).fetchone()
        if row is None:
            raise KeyError(device_id)
        return dict(row)

    def update_registry_device(
        self,
        device_id: str,
        *,
        name: str,
        area: str | None,
        updated_at: str,
    ) -> dict[str, Any]:
        """Rename or reassign one local registration."""
        cursor = self._connection.execute(
            "UPDATE device_registry SET name = ?, area = ?, updated_at = ? "
            "WHERE device_id = ?",
            (name, area, updated_at, device_id),
        )
        if not cursor.rowcount:
            raise KeyError(device_id)
        self._connection.commit()
        return self.registry_device(device_id)

    def forget_registry_device(self, device_id: str) -> dict[str, Any]:
        """Delete local metadata without sending an RF unpair command."""
        device = self.registry_device(device_id)
        self._connection.execute(
            "DELETE FROM device_registry WHERE device_id = ?", (device_id,)
        )
        self._connection.commit()
        return device

    def save_learning_session(self, session: dict[str, Any]) -> None:
        """Persist the current discovery window across gateway restarts."""
        self._connection.execute(
            """
            INSERT OR REPLACE INTO learning_session(
                singleton, session_id, started_at, expires_at,
                baseline_endpoints
            ) VALUES (1, ?, ?, ?, ?)
            """,
            (
                session["session_id"],
                session["started_at"],
                session["expires_at"],
                json.dumps(session["baseline_endpoints"]),
            ),
        )
        self._connection.commit()

    def learning_session(self) -> dict[str, Any] | None:
        """Return the most recent discovery window."""
        row = self._connection.execute(
            "SELECT * FROM learning_session WHERE singleton = 1"
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result.pop("singleton")
        result["baseline_endpoints"] = json.loads(result["baseline_endpoints"])
        return result

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

    def _update_device_metrics(self, event: dict[str, Any]) -> None:
        """Update one device's cadence counters for a decoded observation."""
        if event.get("event_type") != "device_observation":
            return
        device_id = event.get("device_id")
        observed_at = event.get("observed_at")
        if not device_id or not isinstance(observed_at, str):
            return

        existing = self._connection.execute(
            "SELECT last_observed_at FROM device_metrics WHERE device_id = ?",
            (device_id,),
        ).fetchone()
        gap = 0.0
        interval_increment = 0
        if existing:
            previous = _parse_timestamp(existing["last_observed_at"])
            current = _parse_timestamp(observed_at)
            if previous is not None and current is not None:
                try:
                    gap = max(0.0, (current - previous).total_seconds())
                    interval_increment = 1
                except TypeError:
                    # Ignore a mixed aware/naive timestamp during migration.
                    pass

        self._connection.execute(
            """
            INSERT INTO device_metrics(
                device_id, first_observed_at, last_observed_at, report_count,
                interval_count, total_interval_seconds,
                longest_report_gap_seconds
            ) VALUES (?, ?, ?, 1, 0, 0, 0)
            ON CONFLICT(device_id) DO UPDATE SET
                last_observed_at=excluded.last_observed_at,
                report_count=device_metrics.report_count + 1,
                interval_count=device_metrics.interval_count + ?,
                total_interval_seconds=(
                    device_metrics.total_interval_seconds + ?
                ),
                longest_report_gap_seconds=MAX(
                    device_metrics.longest_report_gap_seconds, ?
                )
            """,
            (
                device_id,
                observed_at,
                observed_at,
                interval_increment,
                gap,
                gap,
            ),
        )

    def _backfill_device_metrics(self) -> None:
        """Build cadence metrics once when upgrading an existing database."""
        row = self._connection.execute(
            "SELECT COUNT(*) AS count FROM device_metrics"
        ).fetchone()
        if int(row["count"]):
            return
        rows = self._connection.execute(
            "SELECT payload FROM events WHERE event_type = 'device_observation' "
            "ORDER BY event_id"
        ).fetchall()
        for event_row in rows:
            self._update_device_metrics(json.loads(event_row["payload"]))


def _parse_timestamp(value: str) -> datetime | None:
    """Parse ISO timestamps used by rtl_433 and the replay transport."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
