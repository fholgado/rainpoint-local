"""Persistent RF event and endpoint inventory storage."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .product_identity import (
    GENERIC_HCS02X_MODEL,
    HCS02X_PROTOCOL,
    HTV145_MODEL,
    hcs02x_identity,
)

SCHEMA_VERSION = 15
DEFAULT_EVENT_RETENTION_LIMIT = 100_000


def frame_accepted(event: dict[str, Any]) -> bool | None:
    """Return the integrity decision while preserving legacy event meaning."""
    state = event.get("state", {})
    explicit = state.get("rf_frame_accepted")
    if isinstance(explicit, bool):
        return explicit
    trailer_valid = state.get("rf_trailer_valid")
    if trailer_valid is True:
        return True
    # Product-code reports and decoded valve transactions predate the ordinary
    # trailer family. Their strict structural decoders are the current evidence.
    if "rf_product_code" in state:
        return True
    if (
        event.get("event_type") == "device_observation"
        and event.get("model") == HTV145_MODEL
    ):
        return True
    return trailer_valid if isinstance(trailer_valid, bool) else None


class SQLiteEventStore:
    """Persist normalized events and summarize observed RF endpoints."""

    def __init__(
        self,
        path: str | Path,
        *,
        event_retention_limit: int = DEFAULT_EVENT_RETENTION_LIMIT,
    ) -> None:
        if event_retention_limit < 1:
            raise ValueError("event retention limit must be at least 1")
        self.path = Path(path)
        self.event_retention_limit = event_retention_limit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        version = self.schema_version()
        if version > SCHEMA_VERSION:
            self._connection.close()
            raise RuntimeError(
                f"database schema {version} is newer than supported "
                f"version {SCHEMA_VERSION}"
            )
        schema_v1 = (
            """
            BEGIN IMMEDIATE;
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
                last_report_interval_seconds REAL,
                longest_report_gap_seconds REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS device_reception_metrics (
                device_id TEXT PRIMARY KEY,
                valid_frame_count INTEGER NOT NULL DEFAULT 0,
                invalid_frame_count INTEGER NOT NULL DEFAULT 0,
                last_frame_at TEXT NOT NULL,
                last_valid_frame_at TEXT,
                last_invalid_frame_at TEXT,
                last_frame_event_id INTEGER NOT NULL,
                last_valid_frame_event_id INTEGER
            );
            CREATE TABLE IF NOT EXISTS storage_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
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
            CREATE TABLE IF NOT EXISTS device_suppressions (
                endpoint TEXT PRIMARY KEY,
                suppressed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS hcs026_enrollments (
                factory_endpoint TEXT PRIMARY KEY,
                paired_endpoint TEXT NOT NULL UNIQUE,
                enrolled_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS learning_session (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                session_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                baseline_endpoints TEXT NOT NULL
            );
            PRAGMA user_version = 1;
            COMMIT;
            """
        )
        if version == 0:
            self._connection.executescript(schema_v1)
            version = 1
        if version == 1:
            self._migrate_v1_to_v2()
            version = 2
        if version == 2:
            self._migrate_v2_to_v3()
            version = 3
        if version == 3:
            self._migrate_v3_to_v4()
            version = 4
        if version == 4:
            self._migrate_v4_to_v5()
            version = 5
        if version == 5:
            self._migrate_v5_to_v6()
            version = 6
        if version == 6:
            self._migrate_v6_to_v7()
            version = 7
        if version == 7:
            self._migrate_v7_to_v8()
            version = 8
        if version == 8:
            self._migrate_v8_to_v9()
            version = 9
        if version == 9:
            self._migrate_v9_to_v10()
            version = 10
        if version == 10:
            self._migrate_v10_to_v11()
            version = 11
        if version == 11:
            self._migrate_v11_to_v12()
            version = 12
        if version == 12:
            self._migrate_v12_to_v13()
            version = 13
        if version == 13:
            self._migrate_v13_to_v14()
            version = 14
        if version == 14:
            self._migrate_v14_to_v15()
        self._rebuild_endpoint_inventory()
        self._backfill_device_metrics()
        self._backfill_reception_metrics()
        self._prune_events()
        self._connection.commit()

    def close(self) -> None:
        """Close the database connection."""
        self._connection.close()

    def schema_version(self) -> int:
        """Return the explicit SQLite schema version."""
        row = self._connection.execute("PRAGMA user_version").fetchone()
        return int(row[0])

    def metadata_value(self, key: str) -> str | None:
        """Return one internal metadata value without exposing SQL details."""
        row = self._connection.execute(
            "SELECT value FROM storage_metadata WHERE key = ?", (key,)
        ).fetchone()
        return str(row["value"]) if row is not None else None

    def set_metadata_value(self, key: str, value: str) -> None:
        """Persist one internal metadata value atomically."""
        self._connection.execute(
            "INSERT OR REPLACE INTO storage_metadata(key, value) VALUES (?, ?)",
            (key, value),
        )
        self._connection.commit()

    def _migrate_v1_to_v2(self) -> None:
        """Add durable latest-device snapshots and event query indexes."""
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS device_snapshots (
                    device_id TEXT PRIMARY KEY,
                    event_id INTEGER NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_type_id "
                "ON events(event_type, event_id)"
            )
            rows = self._connection.execute(
                "SELECT payload FROM events "
                "WHERE event_type = 'device_observation' ORDER BY event_id"
            ).fetchall()
            for row in rows:
                event = json.loads(row["payload"])
                if frame_accepted(event) is False:
                    continue
                device_id = event.get("device_id")
                if isinstance(device_id, str):
                    self._connection.execute(
                        "INSERT OR REPLACE INTO device_snapshots("
                        "device_id, event_id, payload) VALUES (?, ?, ?)",
                        (device_id, event["event_id"], row["payload"]),
                    )
            self._connection.execute("PRAGMA user_version = 2")

    def _migrate_v2_to_v3(self) -> None:
        """Add persistent per-receiver coverage metrics."""
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS receiver_metrics (
                    receiver_id TEXT NOT NULL,
                    device_id TEXT NOT NULL DEFAULT '',
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    frame_count INTEGER NOT NULL DEFAULT 0,
                    accepted_frame_count INTEGER NOT NULL DEFAULT 0,
                    rejected_frame_count INTEGER NOT NULL DEFAULT 0,
                    duplicate_frame_count INTEGER NOT NULL DEFAULT 0,
                    rssi_total REAL NOT NULL DEFAULT 0,
                    rssi_count INTEGER NOT NULL DEFAULT 0,
                    last_rssi REAL,
                    PRIMARY KEY(receiver_id, device_id)
                )
                """
            )
            rows = self._connection.execute(
                "SELECT payload FROM events ORDER BY event_id"
            ).fetchall()
            for row in rows:
                event = json.loads(row["payload"])
                state = event.setdefault("state", {})
                if not isinstance(state.get("rf_receiver_id"), str):
                    state["rf_receiver_id"] = state.get(
                        "rf_node_id", "legacy-unknown"
                    )
                self._update_receiver_metrics(event)
            self._connection.execute("PRAGMA user_version = 3")

    def _migrate_v3_to_v4(self) -> None:
        """Add the persistent custom local radio-node registry."""
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS radio_nodes (
                    node_id TEXT PRIMARY KEY,
                    token TEXT NOT NULL,
                    name TEXT NOT NULL,
                    area TEXT,
                    registered_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute("PRAGMA user_version = 4")

    def _migrate_v4_to_v5(self) -> None:
        """Persist protocol and model-identification evidence."""
        with self._connection:
            columns = {
                str(row[1])
                for row in self._connection.execute(
                    "PRAGMA table_info(device_registry)"
                )
            }
            for name, sql_type in (
                ("protocol", "TEXT"),
                ("model_source", "TEXT"),
                ("product_code", "INTEGER"),
                ("model_code", "INTEGER"),
            ):
                if name not in columns:
                    self._connection.execute(
                        f"ALTER TABLE device_registry ADD COLUMN {name} {sql_type}"
                    )
            self._connection.execute(
                "UPDATE device_registry SET model = ?, protocol = ?, "
                "model_source = 'legacy_model_unverified' "
                "WHERE model = 'HCS026FRF'",
                (GENERIC_HCS02X_MODEL, HCS02X_PROTOCOL),
            )
            self._connection.execute(
                "UPDATE device_registry SET protocol = 'rainpoint_htv', "
                "model_source = 'legacy_registry' WHERE model = 'HTV145FRF'"
            )
            rows = self._connection.execute(
                "SELECT payload FROM events ORDER BY event_id"
            ).fetchall()
            for row in rows:
                event = json.loads(row["payload"])
                state = event.get("state", {})
                endpoint = state.get("rf_endpoint")
                if not isinstance(endpoint, str):
                    continue
                identity = hcs02x_identity(
                    {
                        "product_code": state.get("rf_product_code"),
                        "model_code": state.get("rf_model_code"),
                    }
                )
                if not identity.source.startswith("rf_"):
                    continue
                self._connection.execute(
                    "UPDATE device_registry SET model = ?, protocol = ?, "
                    "model_source = ?, product_code = ?, model_code = ? "
                    "WHERE endpoint = ?",
                    (
                        identity.model,
                        identity.protocol,
                        identity.source,
                        identity.product_code,
                        identity.model_code,
                        endpoint,
                    ),
                )
            self._connection.execute("PRAGMA user_version = 5")

    def _migrate_v5_to_v6(self) -> None:
        """Persist the most recent distinct report interval for charting."""
        with self._connection:
            columns = {
                str(row[1])
                for row in self._connection.execute(
                    "PRAGMA table_info(device_metrics)"
                )
            }
            if "last_report_interval_seconds" not in columns:
                self._connection.execute(
                    "ALTER TABLE device_metrics ADD COLUMN "
                    "last_report_interval_seconds REAL"
                )
            self._connection.execute(
                "DELETE FROM storage_metadata WHERE key = ?",
                ("device_metrics_version",),
            )
            self._connection.execute("PRAGMA user_version = 6")

    def _migrate_v6_to_v7(self) -> None:
        """Persist the single radio-node owner of each sensor ACK route."""
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS hcs026_ack_assignments (
                    paired_endpoint TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL,
                    assigned_channel INTEGER NOT NULL,
                    frequency_offset_hz INTEGER NOT NULL,
                    power_dbm INTEGER NOT NULL,
                    invert INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_hcs026_ack_node "
                "ON hcs026_ack_assignments(node_id)"
            )
            self._connection.execute("PRAGMA user_version = 7")

    def _migrate_v13_to_v14(self) -> None:
        """Bind every durable sensor ACK route to its RF controller identity."""
        with self._connection:
            columns = {
                str(row[1])
                for row in self._connection.execute(
                    "PRAGMA table_info(hcs026_ack_assignments)"
                )
            }
            for name in ("controller_endpoint", "companion_endpoint"):
                if name not in columns:
                    self._connection.execute(
                        f"ALTER TABLE hcs026_ack_assignments "
                        f"ADD COLUMN {name} TEXT"
                    )
            # Every pre-v14 assignment was created by the retained-association
            # prototype and therefore belongs to the observed stock identity.
            self._connection.execute(
                "UPDATE hcs026_ack_assignments SET "
                "controller_endpoint = COALESCE(controller_endpoint, ?), "
                "companion_endpoint = COALESCE(companion_endpoint, ?)",
                ("b9840280", "39840280"),
            )
            self._connection.execute("PRAGMA user_version = 14")

    def _migrate_v14_to_v15(self) -> None:
        """Retain bounded HTV405 timeout evidence for guarded recovery."""
        with self._connection:
            columns = {
                str(row[1])
                for row in self._connection.execute(
                    "PRAGMA table_info(valve_registry)"
                )
            }
            for name, sql_type in (
                ("control_recovery_sequence", "INTEGER"),
                ("control_recovery_attempt", "INTEGER NOT NULL DEFAULT 0"),
                ("control_recovery_not_before", "TEXT"),
                ("control_recovery_zone", "INTEGER"),
                ("control_recovery_duration_seconds", "INTEGER"),
            ):
                if name not in columns:
                    self._connection.execute(
                        f"ALTER TABLE valve_registry ADD COLUMN {name} {sql_type}"
                    )
            self._connection.execute("PRAGMA user_version = 15")

    def _migrate_v7_to_v8(self) -> None:
        """Persist direction-independent multi-zone valve RF links."""
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS valve_registry (
                    valve_endpoint TEXT PRIMARY KEY,
                    controller_endpoint TEXT NOT NULL,
                    device_id TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    model TEXT NOT NULL,
                    area TEXT,
                    accepted_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(controller_endpoint, valve_endpoint)
                )
                """
            )
            self._connection.execute("PRAGMA user_version = 8")

    def _migrate_v8_to_v9(self) -> None:
        """Persist the last observed HTV405 lower telemetry phase."""
        with self._connection:
            columns = {
                str(row[1])
                for row in self._connection.execute(
                    "PRAGMA table_info(valve_registry)"
                )
            }
            for name, sql_type in (
                ("last_sequence", "INTEGER"),
                ("last_repeat", "INTEGER"),
                ("next_sequence", "INTEGER"),
                ("next_repeat", "INTEGER"),
                ("last_phase_at", "TEXT"),
                ("last_phase_frame", "TEXT"),
            ):
                if name not in columns:
                    self._connection.execute(
                        f"ALTER TABLE valve_registry ADD COLUMN {name} {sql_type}"
                    )
            self._connection.execute("PRAGMA user_version = 9")

    def _migrate_v9_to_v10(self) -> None:
        """Separate durable controller state from lower-channel telemetry."""
        with self._connection:
            columns = {
                str(row[1])
                for row in self._connection.execute(
                    "PRAGMA table_info(valve_registry)"
                )
            }
            for name, sql_type in (
                ("control_node_id", "TEXT"),
                ("control_companion_endpoint", "TEXT"),
                ("control_selector", "INTEGER"),
                ("control_frequency_offset_hz", "INTEGER"),
                ("control_center_hz", "INTEGER"),
                ("control_last_sequence", "INTEGER"),
                ("control_next_sequence", "INTEGER"),
                ("control_confirmed_watering", "INTEGER"),
                ("control_confirmed_at", "TEXT"),
                ("control_response_frame", "TEXT"),
            ):
                if name not in columns:
                    self._connection.execute(
                        f"ALTER TABLE valve_registry ADD COLUMN {name} {sql_type}"
                    )
            self._connection.execute("PRAGMA user_version = 10")

    def _migrate_v10_to_v11(self) -> None:
        """Persist the deadline of an authenticated duration-bounded run."""
        with self._connection:
            columns = {
                str(row[1])
                for row in self._connection.execute(
                    "PRAGMA table_info(valve_registry)"
                )
            }
            for name, sql_type in (
                ("control_active_zone", "INTEGER"),
                ("control_run_started_at", "TEXT"),
                ("control_run_duration_seconds", "INTEGER"),
                ("control_expected_idle_at", "TEXT"),
            ):
                if name not in columns:
                    self._connection.execute(
                        f"ALTER TABLE valve_registry ADD COLUMN {name} {sql_type}"
                    )
            self._connection.execute("PRAGMA user_version = 11")

    def _migrate_v11_to_v12(self) -> None:
        """Persist disabled-by-default HTV145 command coordination state."""
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS htv145_control_state (
                    valve_endpoint TEXT PRIMARY KEY,
                    controller_endpoint TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    center_hz INTEGER NOT NULL,
                    power_dbm INTEGER NOT NULL,
                    invert INTEGER NOT NULL,
                    trailer_residual INTEGER NOT NULL,
                    next_sequence INTEGER,
                    counter_synchronized INTEGER NOT NULL DEFAULT 0,
                    counter_source TEXT,
                    pending_command_id TEXT UNIQUE,
                    pending_action TEXT,
                    pending_sequence INTEGER,
                    pending_duration_seconds INTEGER,
                    pending_started_at TEXT,
                    expected_idle_at TEXT,
                    last_command_started_at TEXT,
                    confirmed_watering INTEGER,
                    confirmed_at TEXT,
                    last_response_frame TEXT,
                    last_result TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute("PRAGMA user_version = 12")

    def _migrate_v12_to_v13(self) -> None:
        """Add durable at-most-once HTV405 command reservations."""
        with self._connection:
            columns = {
                str(row[1])
                for row in self._connection.execute(
                    "PRAGMA table_info(valve_registry)"
                )
            }
            for name, sql_type in (
                ("control_pending_command_id", "TEXT"),
                ("control_pending_action", "TEXT"),
                ("control_pending_sequence", "INTEGER"),
                ("control_pending_zone", "INTEGER"),
                ("control_pending_duration_seconds", "INTEGER"),
                ("control_pending_started_at", "TEXT"),
                ("control_last_result", "TEXT"),
            ):
                if name not in columns:
                    self._connection.execute(
                        f"ALTER TABLE valve_registry ADD COLUMN {name} {sql_type}"
                    )
            self._connection.execute("PRAGMA user_version = 13")

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
        self._update_reception_metrics(event)
        self._update_receiver_metrics(event)
        if (
            event.get("event_type") == "device_observation"
            and isinstance(event.get("device_id"), str)
            and frame_accepted(event) is not False
        ):
            self._connection.execute(
                "INSERT OR REPLACE INTO device_snapshots("
                "device_id, event_id, payload) VALUES (?, ?, ?)",
                (
                    event["device_id"],
                    event["event_id"],
                    json.dumps(event, separators=(",", ":"), sort_keys=True),
                ),
            )
        self._prune_events()
        self._connection.commit()

    def record_receiver_duplicate(self, event: dict[str, Any]) -> None:
        """Retain receiver coverage for a deduplicated air transmission."""
        self._update_receiver_metrics(event, duplicate=True)
        self._connection.commit()

    def _prune_events(self) -> None:
        """Bound the journal without touching durable derived state."""
        self._connection.execute(
            "DELETE FROM events WHERE event_id <= ("
            "SELECT event_id FROM events ORDER BY event_id DESC LIMIT 1 OFFSET ?"
            ")",
            (self.event_retention_limit,),
        )

    def recent_events(self, limit: int) -> list[dict[str, Any]]:
        """Return the newest events in chronological order."""
        rows = self._connection.execute(
            "SELECT payload FROM events ORDER BY event_id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [json.loads(row["payload"]) for row in reversed(rows)]

    def latest_device_events(self) -> list[dict[str, Any]]:
        """Return the newest accepted decoded observation for every device."""
        rows = self._connection.execute(
            "SELECT payload FROM device_snapshots ORDER BY event_id"
        ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

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

    def oldest_event_id(self) -> int:
        """Return the oldest retained event ID, or zero for an empty journal."""
        row = self._connection.execute(
            "SELECT COALESCE(MIN(event_id), 0) AS event_id FROM events"
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

    def reception_metrics(self) -> dict[str, dict[str, Any]]:
        """Return valid/invalid RF reception quality by logical device."""
        rows = self._connection.execute(
            "SELECT * FROM device_reception_metrics ORDER BY device_id"
        ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = dict(row)
            valid = int(item.pop("valid_frame_count"))
            invalid = int(item.pop("invalid_frame_count"))
            total = valid + invalid
            item.update(
                {
                    "valid_rf_frame_count": valid,
                    "invalid_rf_frame_count": invalid,
                    "rf_frame_count": total,
                    "rf_frame_success_percent": (
                        round(valid * 100 / total, 1) if total else None
                    ),
                }
            )
            result[str(item.pop("device_id"))] = item
        return result

    def receiver_metrics(self) -> list[dict[str, Any]]:
        """Return persistent coverage metrics by receiver and logical device."""
        rows = self._connection.execute(
            "SELECT * FROM receiver_metrics ORDER BY receiver_id, device_id"
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            rssi_count = int(item.pop("rssi_count"))
            rssi_total = float(item.pop("rssi_total"))
            item["device_id"] = item["device_id"] or None
            item["average_rssi_db"] = (
                round(rssi_total / rssi_count, 2) if rssi_count else None
            )
            result.append(item)
        return result

    def radio_nodes(self) -> list[dict[str, Any]]:
        """Return managed radio nodes without exposing their credentials."""
        rows = self._connection.execute(
            "SELECT node_id, name, area, registered_at, updated_at "
            "FROM radio_nodes ORDER BY name, node_id"
        ).fetchall()
        return [dict(row) for row in rows]

    def radio_node_credentials(self) -> dict[str, str]:
        """Return private credentials for the authenticated node listener."""
        rows = self._connection.execute(
            "SELECT node_id, token FROM radio_nodes ORDER BY node_id"
        ).fetchall()
        return {str(row["node_id"]): str(row["token"]) for row in rows}

    def upsert_radio_node(
        self,
        *,
        node_id: str,
        token: str,
        name: str,
        area: str | None,
        updated_at: str,
        replace_existing: bool = True,
    ) -> dict[str, Any]:
        """Register one node or migrate its existing option credential."""
        self._connection.execute(
            """
            INSERT INTO radio_nodes(
                node_id, token, name, area, registered_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                token=CASE
                    WHEN ? THEN excluded.token
                    ELSE radio_nodes.token
                END,
                name=CASE
                    WHEN ? THEN excluded.name
                    ELSE radio_nodes.name
                END,
                area=CASE
                    WHEN ? THEN excluded.area
                    ELSE radio_nodes.area
                END,
                updated_at=CASE
                    WHEN ? THEN excluded.updated_at
                    ELSE radio_nodes.updated_at
                END
            """,
            (
                node_id,
                token,
                name,
                area,
                updated_at,
                updated_at,
                replace_existing,
                replace_existing,
                replace_existing,
                replace_existing,
            ),
        )
        self._connection.commit()
        return next(
            item for item in self.radio_nodes() if item["node_id"] == node_id
        )

    def update_radio_node(
        self,
        node_id: str,
        *,
        name: str,
        area: str | None,
        updated_at: str,
    ) -> dict[str, Any]:
        """Update managed radio-node metadata without rotating credentials."""
        cursor = self._connection.execute(
            "UPDATE radio_nodes SET name = ?, area = ?, updated_at = ? "
            "WHERE node_id = ?",
            (name, area, updated_at, node_id),
        )
        if not cursor.rowcount:
            raise KeyError(node_id)
        self._connection.commit()
        return next(
            item for item in self.radio_nodes() if item["node_id"] == node_id
        )

    def delete_radio_node(self, node_id: str) -> bool:
        """Revoke one node credential while retaining RainPoint devices."""
        cursor = self._connection.execute(
            "DELETE FROM radio_nodes WHERE node_id = ?", (node_id,)
        )
        self._connection.commit()
        return bool(cursor.rowcount)

    def registry(self) -> list[dict[str, Any]]:
        """Return accepted local device registrations."""
        rows = self._connection.execute(
            "SELECT * FROM device_registry ORDER BY name, endpoint"
        ).fetchall()
        return [dict(row) for row in rows]

    def valve_registry(self) -> list[dict[str, Any]]:
        """Return persistent valve link registrations."""
        rows = self._connection.execute(
            "SELECT * FROM valve_registry ORDER BY name, valve_endpoint"
        ).fetchall()
        return [dict(row) for row in rows]

    def upsert_valve_link(
        self,
        *,
        controller_endpoint: str,
        valve_endpoint: str,
        device_id: str,
        name: str,
        model: str,
        area: str | None,
        accepted_at: str,
    ) -> dict[str, Any]:
        """Persist a structurally proven controller-to-valve RF link."""
        self._connection.execute(
            """
            INSERT INTO valve_registry(
                controller_endpoint, valve_endpoint, device_id, name, model,
                area, accepted_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(valve_endpoint) DO UPDATE SET
                controller_endpoint=excluded.controller_endpoint,
                name=excluded.name,
                model=excluded.model,
                area=COALESCE(valve_registry.area, excluded.area),
                updated_at=excluded.updated_at
            """,
            (
                controller_endpoint,
                valve_endpoint,
                device_id,
                name,
                model,
                area,
                accepted_at,
                accepted_at,
            ),
        )
        self._connection.commit()
        return next(
            item
            for item in self.valve_registry()
            if item["valve_endpoint"] == valve_endpoint
        )

    def update_valve_phase(
        self,
        *,
        valve_endpoint: str,
        sequence: int,
        repeat: bool,
        next_sequence: int,
        next_repeat: bool,
        observed_at: str,
        frame: str,
    ) -> dict[str, Any]:
        """Persist lower telemetry cadence without inferring TX success."""
        cursor = self._connection.execute(
            """
            UPDATE valve_registry SET
                last_sequence = ?, last_repeat = ?,
                next_sequence = ?, next_repeat = ?,
                last_phase_at = ?, last_phase_frame = ?, updated_at = ?
            WHERE valve_endpoint = ?
            """,
            (
                sequence,
                int(repeat),
                next_sequence,
                int(next_repeat),
                observed_at,
                frame,
                observed_at,
                valve_endpoint,
            ),
        )
        if not cursor.rowcount:
            raise KeyError(valve_endpoint)
        self._connection.commit()
        return next(
            item
            for item in self.valve_registry()
            if item["valve_endpoint"] == valve_endpoint
        )

    def update_valve_control_profile(
        self,
        *,
        valve_endpoint: str,
        node_id: str,
        companion_endpoint: str,
        selector: int,
        frequency_offset_hz: int,
        observed_at: str,
    ) -> dict[str, Any]:
        """Persist association-scoped control routing after local enrollment."""
        cursor = self._connection.execute(
            """
            UPDATE valve_registry SET
                control_node_id = ?, control_companion_endpoint = ?,
                control_selector = ?, control_frequency_offset_hz = ?,
                control_center_hz = NULL, control_last_sequence = NULL,
                control_next_sequence = NULL,
                control_confirmed_watering = NULL,
                control_confirmed_at = NULL, control_response_frame = NULL,
                control_active_zone = NULL, control_run_started_at = NULL,
                control_run_duration_seconds = NULL,
                control_expected_idle_at = NULL,
                control_pending_command_id = NULL,
                control_pending_action = NULL,
                control_pending_sequence = NULL,
                control_pending_zone = NULL,
                control_pending_duration_seconds = NULL,
                control_pending_started_at = NULL,
                control_recovery_sequence = NULL,
                control_recovery_attempt = 0,
                control_recovery_not_before = NULL,
                control_recovery_zone = NULL,
                control_recovery_duration_seconds = NULL,
                control_last_result = 'association_updated_counter_required',
                updated_at = ?
            WHERE valve_endpoint = ?
            """,
            (
                node_id,
                companion_endpoint,
                selector,
                frequency_offset_hz,
                observed_at,
                valve_endpoint,
            ),
        )
        if not cursor.rowcount:
            raise KeyError(valve_endpoint)
        self._connection.commit()
        return next(
            item
            for item in self.valve_registry()
            if item["valve_endpoint"] == valve_endpoint
        )

    def assign_htv405_control_node(
        self,
        *,
        valve_endpoint: str,
        node_id: str,
        observed_at: str,
    ) -> dict[str, Any]:
        """Move RF egress to one node without changing the valve association."""
        cursor = self._connection.execute(
            """
            UPDATE valve_registry SET
                control_node_id = ?, control_last_sequence = NULL,
                control_next_sequence = NULL,
                control_confirmed_watering = 0,
                control_confirmed_at = ?, control_response_frame = NULL,
                control_active_zone = NULL, control_run_started_at = NULL,
                control_run_duration_seconds = NULL,
                control_expected_idle_at = NULL,
                control_recovery_sequence = NULL,
                control_recovery_attempt = 0,
                control_recovery_not_before = NULL,
                control_recovery_zone = NULL,
                control_recovery_duration_seconds = NULL,
                control_last_result = 'control_node_updated_counter_required',
                updated_at = ?
            WHERE valve_endpoint = ?
              AND control_pending_command_id IS NULL
            """,
            (node_id, observed_at, observed_at, valve_endpoint),
        )
        if not cursor.rowcount:
            raise RuntimeError("HTV405 control node update raced")
        self._connection.commit()
        return next(
            item
            for item in self.valve_registry()
            if item["valve_endpoint"] == valve_endpoint
        )

    def reserve_htv405_command(
        self,
        *,
        valve_endpoint: str,
        node_id: str,
        command_id: str,
        action: str,
        zone: int,
        duration_seconds: int | None,
        started_at: str,
        minimum_interval_seconds: float = 15.0,
    ) -> dict[str, Any]:
        """Atomically reserve one authenticated HTV405 command counter."""
        if action not in {"open", "close"}:
            raise ValueError("HTV405 action must be open or close")
        if zone not in range(1, 5):
            raise ValueError("HTV405 zone must be between 1 and 4")
        if action == "open":
            if (
                duration_seconds is None
                or duration_seconds not in range(60, 3_601)
                or duration_seconds % 60
            ):
                raise ValueError(
                    "HTV405 open must be 60-3600 seconds in whole minutes"
                )
        elif duration_seconds is not None:
            raise ValueError("HTV405 close cannot include a duration")
        try:
            started = datetime.fromisoformat(started_at)
        except ValueError as error:
            raise ValueError("invalid HTV405 command timestamp") from error
        row = self._connection.execute(
            "SELECT * FROM valve_registry WHERE valve_endpoint = ?",
            (valve_endpoint,),
        ).fetchone()
        if row is None:
            raise KeyError(valve_endpoint)
        state = dict(row)
        if state["control_node_id"] != node_id:
            raise ValueError("HTV405 node differs from durable association")
        if state["control_pending_command_id"] is not None:
            raise RuntimeError("an HTV405 command is already pending")
        sequence = state["control_next_sequence"]
        if sequence is None:
            raise RuntimeError("HTV405 control counter is not synchronized")
        confirmed_watering = state["control_confirmed_watering"]
        if action == "open" and confirmed_watering is not False and confirmed_watering != 0:
            raise RuntimeError("HTV405 valve is not confirmed idle")
        if action == "close" and (
            confirmed_watering not in {1, True}
            or state["control_active_zone"] != zone
        ):
            raise RuntimeError("HTV405 zone is not confirmed watering")
        last_at = state["control_confirmed_at"]
        if isinstance(last_at, str):
            try:
                previous = datetime.fromisoformat(last_at)
                if previous.tzinfo is None and started.tzinfo is not None:
                    previous = previous.replace(tzinfo=started.tzinfo)
                if started.tzinfo is None and previous.tzinfo is not None:
                    started = started.replace(tzinfo=previous.tzinfo)
                if (started - previous).total_seconds() < minimum_interval_seconds:
                    raise RuntimeError(
                        "minimum HTV405 command interval has not elapsed"
                    )
            except ValueError:
                pass
        cursor = self._connection.execute(
            """
            UPDATE valve_registry SET
                control_pending_command_id = ?,
                control_pending_action = ?,
                control_pending_sequence = ?,
                control_pending_zone = ?,
                control_pending_duration_seconds = ?,
                control_pending_started_at = ?,
                control_last_result = 'pending_authenticated_response',
                updated_at = ?
            WHERE valve_endpoint = ? AND control_node_id = ?
              AND control_pending_command_id IS NULL
              AND control_next_sequence = ?
            """,
            (
                command_id,
                action,
                sequence,
                zone,
                duration_seconds,
                started_at,
                started_at,
                valve_endpoint,
                node_id,
                sequence,
            ),
        )
        if not cursor.rowcount:
            raise RuntimeError("HTV405 command reservation raced")
        self._connection.commit()
        return next(
            item
            for item in self.valve_registry()
            if item["valve_endpoint"] == valve_endpoint
        )

    def synchronize_htv405_control_counter(
        self,
        *,
        valve_endpoint: str,
        node_id: str,
        next_sequence: int,
        source: str,
        observed_at: str,
    ) -> dict[str, Any]:
        """Restore a counter from explicit, externally retained evidence."""
        if next_sequence not in range(0x20):
            raise ValueError("HTV405 counter must be in 0x00..0x1f")
        if source not in {
            "retained_association_capture",
            "authenticated_command_response",
        }:
            raise ValueError("unsupported HTV405 counter evidence source")
        cursor = self._connection.execute(
            """
            UPDATE valve_registry SET
                control_last_sequence = NULL,
                control_next_sequence = ?,
                control_confirmed_watering = 0,
                control_confirmed_at = ?,
                control_response_frame = NULL,
                control_active_zone = NULL,
                control_run_started_at = NULL,
                control_run_duration_seconds = NULL,
                control_expected_idle_at = NULL,
                control_recovery_sequence = NULL,
                control_recovery_attempt = 0,
                control_recovery_not_before = NULL,
                control_recovery_zone = NULL,
                control_recovery_duration_seconds = NULL,
                control_last_result = ?, updated_at = ?
            WHERE valve_endpoint = ? AND control_node_id = ?
              AND control_pending_command_id IS NULL
            """,
            (
                next_sequence,
                observed_at,
                f"counter_synchronized:{source}",
                observed_at,
                valve_endpoint,
                node_id,
            ),
        )
        if not cursor.rowcount:
            raise KeyError((valve_endpoint, node_id))
        self._connection.commit()
        return next(
            item
            for item in self.valve_registry()
            if item["valve_endpoint"] == valve_endpoint
        )

    def fail_htv405_command(
        self,
        *,
        valve_endpoint: str,
        node_id: str,
        command_id: str,
        reason: str,
        observed_at: str,
    ) -> dict[str, Any]:
        """Fail a reservation and invalidate the unconfirmed counter."""
        row = self._connection.execute(
            "SELECT * FROM valve_registry WHERE valve_endpoint = ?",
            (valve_endpoint,),
        ).fetchone()
        if row is None:
            raise KeyError(valve_endpoint)
        state = dict(row)
        recovery_sequence: int | None = None
        recovery_attempt = int(state.get("control_recovery_attempt") or 0)
        recovery_not_before: str | None = None
        recovery_zone: int | None = None
        recovery_duration: int | None = None
        retryable_timeout = (
            reason == "gateway_command_response_timeout_counter_unsynchronized"
            and state.get("control_pending_action") == "open"
            and isinstance(state.get("control_pending_sequence"), int)
            and isinstance(state.get("control_pending_zone"), int)
            and isinstance(state.get("control_pending_duration_seconds"), int)
            and isinstance(state.get("control_pending_started_at"), str)
        )
        if retryable_timeout and recovery_attempt < 2:
            pending_sequence = int(state["control_pending_sequence"])
            recovery_attempt += 1
            recovery_sequence = (
                pending_sequence
                if recovery_attempt == 1
                else (pending_sequence + 1) & 0x1F
            )
            recovery_zone = int(state["control_pending_zone"])
            recovery_duration = int(
                state["control_pending_duration_seconds"]
            )
            try:
                started = datetime.fromisoformat(
                    str(state["control_pending_started_at"])
                )
            except ValueError:
                recovery_sequence = None
                recovery_not_before = None
            else:
                recovery_not_before = (
                    started
                    + timedelta(seconds=recovery_duration + 15)
                ).isoformat()
        cursor = self._connection.execute(
            """
            UPDATE valve_registry SET
                control_next_sequence = NULL,
                control_pending_command_id = NULL,
                control_pending_action = NULL,
                control_pending_sequence = NULL,
                control_pending_zone = NULL,
                control_pending_duration_seconds = NULL,
                control_pending_started_at = NULL,
                control_recovery_sequence = ?,
                control_recovery_attempt = ?,
                control_recovery_not_before = ?,
                control_recovery_zone = ?,
                control_recovery_duration_seconds = ?,
                control_last_result = ?, updated_at = ?
            WHERE valve_endpoint = ? AND control_node_id = ?
              AND control_pending_command_id = ?
            """,
            (
                recovery_sequence,
                recovery_attempt,
                recovery_not_before,
                recovery_zone,
                recovery_duration,
                reason,
                observed_at,
                valve_endpoint,
                node_id,
                command_id,
            ),
        )
        if not cursor.rowcount:
            raise KeyError((valve_endpoint, command_id))
        self._connection.commit()
        return next(
            item
            for item in self.valve_registry()
            if item["valve_endpoint"] == valve_endpoint
        )

    def recover_htv405_timeout_counter(
        self,
        *,
        valve_endpoint: str,
        node_id: str,
        observed_at: str,
    ) -> dict[str, Any] | None:
        """Restore the smallest safe candidate after a bounded open timeout.

        Recovery is unavailable until the entire requested run plus a guard
        interval has elapsed.  This guarantees that even a command whose RF
        acknowledgement and state report were both missed can no longer be
        watering before another counter candidate is attempted.
        """
        row = self._connection.execute(
            "SELECT * FROM valve_registry WHERE valve_endpoint = ?",
            (valve_endpoint,),
        ).fetchone()
        if row is None:
            raise KeyError(valve_endpoint)
        state = dict(row)
        candidate = state.get("control_recovery_sequence")
        not_before = state.get("control_recovery_not_before")
        if (
            state.get("control_node_id") != node_id
            or state.get("control_pending_command_id") is not None
            or state.get("control_next_sequence") is not None
            or not isinstance(candidate, int)
            or isinstance(candidate, bool)
            or candidate not in range(0x20)
            or not isinstance(not_before, str)
            or state.get("control_confirmed_watering") not in {0, False}
        ):
            return None
        try:
            available_at = datetime.fromisoformat(not_before)
            current = datetime.fromisoformat(observed_at)
            if available_at.tzinfo is None and current.tzinfo is not None:
                available_at = available_at.replace(tzinfo=current.tzinfo)
            if current.tzinfo is None and available_at.tzinfo is not None:
                current = current.replace(tzinfo=available_at.tzinfo)
        except ValueError:
            return None
        if current < available_at:
            return None
        cursor = self._connection.execute(
            """
            UPDATE valve_registry SET
                control_next_sequence = ?,
                control_last_result = 'bounded_timeout_counter_recovered',
                updated_at = ?
            WHERE valve_endpoint = ? AND control_node_id = ?
              AND control_pending_command_id IS NULL
              AND control_next_sequence IS NULL
              AND control_recovery_sequence = ?
            """,
            (
                candidate,
                observed_at,
                valve_endpoint,
                node_id,
                candidate,
            ),
        )
        if not cursor.rowcount:
            return None
        self._connection.commit()
        return next(
            item
            for item in self.valve_registry()
            if item["valve_endpoint"] == valve_endpoint
        )

    def observe_htv405_state_report(
        self,
        *,
        valve_endpoint: str,
        watering: bool,
        zone: int | None,
        observed_at: str,
    ) -> dict[str, Any] | None:
        """Apply independent valve state without substituting its counter.

        An idle report can close a previously confirmed bounded run because
        automatic stop does not consume the gateway command counter. An
        otherwise-unexpected watering report makes that counter unsafe: it
        may have been produced by another controller, so local control is
        disabled until new command-counter evidence is supplied.
        """
        if watering and (
            not isinstance(zone, int)
            or isinstance(zone, bool)
            or zone not in range(1, 5)
        ):
            raise ValueError("watering HTV405 report requires a valid zone")
        row = self._connection.execute(
            "SELECT * FROM valve_registry WHERE valve_endpoint = ?",
            (valve_endpoint,),
        ).fetchone()
        if row is None:
            return None
        state = dict(row)
        if state["control_pending_command_id"] is not None:
            return state
        if state["control_next_sequence"] is None and not watering:
            self._connection.execute(
                """
                UPDATE valve_registry SET
                    control_confirmed_watering = 0,
                    control_confirmed_at = ?,
                    control_active_zone = NULL,
                    control_run_started_at = NULL,
                    control_run_duration_seconds = NULL,
                    control_expected_idle_at = NULL,
                    control_last_result =
                        'idle_confirmed_counter_unsynchronized',
                    updated_at = ?
                WHERE valve_endpoint = ?
                  AND control_pending_command_id IS NULL
                  AND control_next_sequence IS NULL
                """,
                (observed_at, observed_at, valve_endpoint),
            )
            self._connection.commit()
            return next(
                item
                for item in self.valve_registry()
                if item["valve_endpoint"] == valve_endpoint
            )
        confirmed_watering = state["control_confirmed_watering"] in {1, True}
        confirmed_zone = state["control_active_zone"]
        if not watering and confirmed_watering:
            self._connection.execute(
                """
                UPDATE valve_registry SET
                    control_confirmed_watering = 0,
                    control_confirmed_at = ?,
                    control_active_zone = NULL,
                    control_run_started_at = NULL,
                    control_run_duration_seconds = NULL,
                    control_expected_idle_at = NULL,
                    control_last_result =
                        'automatic_idle_confirmed_from_telemetry',
                    updated_at = ?
                WHERE valve_endpoint = ? AND control_pending_command_id IS NULL
                """,
                (observed_at, observed_at, valve_endpoint),
            )
            self._connection.commit()
        elif watering and (
            not confirmed_watering or confirmed_zone != zone
        ):
            self._connection.execute(
                """
                UPDATE valve_registry SET
                    control_next_sequence = NULL,
                    control_confirmed_watering = 1,
                    control_confirmed_at = ?,
                    control_active_zone = ?,
                    control_run_started_at = NULL,
                    control_run_duration_seconds = NULL,
                    control_expected_idle_at = NULL,
                    control_recovery_sequence = NULL,
                    control_recovery_not_before = NULL,
                    control_recovery_zone = NULL,
                    control_recovery_duration_seconds = NULL,
                    control_last_result =
                        'unexpected_watering_counter_unsynchronized',
                    updated_at = ?
                WHERE valve_endpoint = ? AND control_pending_command_id IS NULL
                """,
                (observed_at, zone, observed_at, valve_endpoint),
            )
            self._connection.commit()
        return next(
            item
            for item in self.valve_registry()
            if item["valve_endpoint"] == valve_endpoint
        )

    def confirm_valve_control_response(
        self,
        *,
        valve_endpoint: str,
        node_id: str,
        sequence: int,
        next_sequence: int,
        zone: int,
        watering: bool,
        center_hz: int,
        observed_at: str,
        frame: str,
        run_started_at: str | None = None,
        run_duration_seconds: int | None = None,
        expected_idle_at: str | None = None,
    ) -> dict[str, Any]:
        """Advance control state only after a node-authenticated response."""
        if watering and (
            zone not in range(1, 5)
            or run_started_at is None
            or run_duration_seconds is None
            or expected_idle_at is None
        ):
            raise ValueError("watering confirmation requires a bounded run")
        registration = next(
            (
                item
                for item in self.valve_registry()
                if item["valve_endpoint"] == valve_endpoint
            ),
            None,
        )
        if registration is None:
            raise KeyError(valve_endpoint)
        pending_id = registration.get("control_pending_command_id")
        if pending_id is not None and any(
            (
                registration.get("control_pending_sequence") != sequence,
                registration.get("control_pending_zone") != zone,
                registration.get("control_pending_action")
                != ("open" if watering else "close"),
            )
        ):
            raise ValueError("HTV405 response does not match reservation")
        cursor = self._connection.execute(
            """
            UPDATE valve_registry SET
                control_last_sequence = ?, control_next_sequence = ?,
                control_confirmed_watering = ?,
                control_confirmed_at = ?, control_response_frame = ?,
                control_center_hz = ?, control_active_zone = ?,
                control_run_started_at = ?,
                control_run_duration_seconds = ?,
                control_expected_idle_at = ?,
                control_pending_command_id = NULL,
                control_pending_action = NULL,
                control_pending_sequence = NULL,
                control_pending_zone = NULL,
                control_pending_duration_seconds = NULL,
                control_pending_started_at = NULL,
                control_recovery_sequence = NULL,
                control_recovery_attempt = 0,
                control_recovery_not_before = NULL,
                control_recovery_zone = NULL,
                control_recovery_duration_seconds = NULL,
                control_last_result = 'authenticated_response_confirmed',
                updated_at = ?
            WHERE valve_endpoint = ? AND control_node_id = ?
            """,
            (
                sequence,
                next_sequence,
                int(watering),
                observed_at,
                frame,
                center_hz,
                zone if watering else None,
                run_started_at if watering else None,
                run_duration_seconds if watering else None,
                expected_idle_at if watering else None,
                observed_at,
                valve_endpoint,
                node_id,
            ),
        )
        if not cursor.rowcount:
            raise KeyError((valve_endpoint, node_id))
        self._connection.commit()
        result = next(
            item
            for item in self.valve_registry()
            if item["valve_endpoint"] == valve_endpoint
        )
        return result

    def htv145_control_states(
        self, valve_endpoint: str | None = None
    ) -> list[dict[str, Any]]:
        """Return private HTV145 coordinator state; never an actuator API."""
        if valve_endpoint is None:
            rows = self._connection.execute(
                "SELECT * FROM htv145_control_state ORDER BY valve_endpoint"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM htv145_control_state WHERE valve_endpoint = ?",
                (valve_endpoint,),
            ).fetchall()
        result = [dict(row) for row in rows]
        for item in result:
            item["invert"] = bool(item["invert"])
            item["counter_synchronized"] = bool(
                item["counter_synchronized"]
            )
            if item["confirmed_watering"] is not None:
                item["confirmed_watering"] = bool(
                    item["confirmed_watering"]
                )
        return result

    def configure_htv145_control(
        self,
        *,
        valve_endpoint: str,
        controller_endpoint: str,
        node_id: str,
        center_hz: int,
        power_dbm: int,
        invert: bool,
        trailer_residual: int,
        updated_at: str,
    ) -> dict[str, Any]:
        """Persist an association-specific profile with control unsynchronized."""
        cursor = self._connection.execute(
            """
            INSERT INTO htv145_control_state(
                valve_endpoint, controller_endpoint, node_id, center_hz,
                power_dbm, invert, trailer_residual, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(valve_endpoint) DO UPDATE SET
                controller_endpoint=excluded.controller_endpoint,
                node_id=excluded.node_id,
                center_hz=excluded.center_hz,
                power_dbm=excluded.power_dbm,
                invert=excluded.invert,
                trailer_residual=excluded.trailer_residual,
                next_sequence=NULL,
                counter_synchronized=0,
                counter_source=NULL,
                pending_command_id=NULL,
                pending_action=NULL,
                pending_sequence=NULL,
                pending_duration_seconds=NULL,
                pending_started_at=NULL,
                expected_idle_at=NULL,
                confirmed_watering=NULL,
                confirmed_at=NULL,
                last_response_frame=NULL,
                last_result='profile_configured_counter_required',
                updated_at=excluded.updated_at
            WHERE htv145_control_state.pending_command_id IS NULL
            """,
            (
                valve_endpoint,
                controller_endpoint,
                node_id,
                center_hz,
                power_dbm,
                int(invert),
                trailer_residual,
                updated_at,
            ),
        )
        if not cursor.rowcount:
            raise RuntimeError("cannot reconfigure HTV145 while command pending")
        self._connection.commit()
        return self.htv145_control_states(valve_endpoint)[0]

    def synchronize_htv145_control_counter(
        self,
        *,
        valve_endpoint: str,
        next_sequence: int,
        source: str,
        observed_at: str,
    ) -> dict[str, Any]:
        """Set an outbound counter only from explicit, evidenced state."""
        if next_sequence not in range(0x80, 0xA0):
            raise ValueError("HTV145 sequence must be in 0x80..0x9f")
        if source not in {
            "passive_stock_command",
            "matching_immediate_response",
            "matching_independent_state_report",
        }:
            raise ValueError("unsupported HTV145 counter source")
        cursor = self._connection.execute(
            """
            UPDATE htv145_control_state SET
                next_sequence = ?, counter_synchronized = 1,
                counter_source = ?, last_result = 'counter_synchronized',
                updated_at = ?
            WHERE valve_endpoint = ? AND pending_command_id IS NULL
            """,
            (next_sequence, source, observed_at, valve_endpoint),
        )
        if not cursor.rowcount:
            raise RuntimeError("HTV145 profile missing or command pending")
        self._connection.commit()
        return self.htv145_control_states(valve_endpoint)[0]

    def observe_htv145_control_state(
        self,
        *,
        valve_endpoint: str,
        watering: bool,
        observed_at: str,
        frame: str,
    ) -> dict[str, Any]:
        """Persist state without changing the independent command counter."""
        cursor = self._connection.execute(
            """
            UPDATE htv145_control_state SET
                confirmed_watering = ?, confirmed_at = ?,
                expected_idle_at = CASE WHEN ? THEN expected_idle_at ELSE NULL END,
                last_response_frame = ?, updated_at = ?
            WHERE valve_endpoint = ?
            """,
            (
                int(watering),
                observed_at,
                int(watering),
                frame,
                observed_at,
                valve_endpoint,
            ),
        )
        if not cursor.rowcount:
            raise KeyError(valve_endpoint)
        self._connection.commit()
        return self.htv145_control_states(valve_endpoint)[0]

    def reserve_htv145_command(
        self,
        *,
        valve_endpoint: str,
        command_id: str,
        action: str,
        duration_seconds: int | None,
        started_at: str,
        expected_idle_at: str | None,
    ) -> dict[str, Any]:
        """Atomically reserve one logical command before any node write."""
        if action not in {"open", "close"}:
            raise ValueError("HTV145 action must be open or close")
        if action == "open" and (
            duration_seconds is None
            or duration_seconds <= 0
            or duration_seconds % 60
            or expected_idle_at is None
        ):
            raise ValueError("HTV145 open requires a bounded whole-minute run")
        if action == "close" and (
            duration_seconds is not None or expected_idle_at is not None
        ):
            raise ValueError("HTV145 close cannot carry a run duration")
        with self._connection:
            row = self._connection.execute(
                "SELECT * FROM htv145_control_state WHERE valve_endpoint = ?",
                (valve_endpoint,),
            ).fetchone()
            if row is None:
                raise KeyError(valve_endpoint)
            if row["pending_command_id"] is not None:
                raise RuntimeError("an HTV145 command is already pending")
            if not row["counter_synchronized"] or row["next_sequence"] is None:
                raise RuntimeError("the HTV145 command counter is unsynchronized")
            if action == "open" and row["confirmed_watering"] != 0:
                raise RuntimeError("HTV145 open requires confirmed idle state")
            previous_started_at = row["last_command_started_at"]
            if previous_started_at is not None:
                elapsed = (
                    datetime.fromisoformat(started_at)
                    - datetime.fromisoformat(previous_started_at)
                ).total_seconds()
                if elapsed < 15:
                    raise RuntimeError(
                        "HTV145 commands require a 15-second hardware interval"
                    )
            cursor = self._connection.execute(
                """
                UPDATE htv145_control_state SET
                    pending_command_id = ?, pending_action = ?,
                    pending_sequence = ?, pending_duration_seconds = ?,
                    pending_started_at = ?, expected_idle_at = ?,
                    last_command_started_at = ?,
                    last_result = 'reserved_not_confirmed', updated_at = ?
                WHERE valve_endpoint = ?
                  AND pending_command_id IS NULL
                  AND counter_synchronized = 1
                  AND next_sequence = ?
                  AND last_command_started_at IS ?
                  AND (? = 'close' OR confirmed_watering = 0)
                """,
                (
                    command_id,
                    action,
                    row["next_sequence"],
                    duration_seconds,
                    started_at,
                    expected_idle_at,
                    started_at,
                    started_at,
                    valve_endpoint,
                    row["next_sequence"],
                    previous_started_at,
                    action,
                ),
            )
            if not cursor.rowcount:
                raise RuntimeError(
                    "HTV145 reservation state changed before dispatch"
                )
        return self.htv145_control_states(valve_endpoint)[0]

    def confirm_htv145_command(
        self,
        *,
        valve_endpoint: str,
        command_id: str,
        sequence: int,
        watering: bool,
        confirmation: str,
        observed_at: str,
        frame: str,
    ) -> dict[str, Any]:
        """Advance a reserved counter only from matching valve evidence."""
        if confirmation not in {
            "matching_immediate_response",
            "matching_independent_state_report",
        }:
            raise ValueError("unsupported HTV145 confirmation")
        row = self._connection.execute(
            "SELECT * FROM htv145_control_state WHERE valve_endpoint = ?",
            (valve_endpoint,),
        ).fetchone()
        if row is None:
            raise KeyError(valve_endpoint)
        expected_watering = row["pending_action"] == "open"
        if (
            row["pending_command_id"] != command_id
            or row["pending_sequence"] != sequence
            or bool(watering) != expected_watering
        ):
            raise ValueError("HTV145 confirmation does not match reservation")
        next_sequence = 0x80 | ((sequence + 1) & 0x1F)
        cursor = self._connection.execute(
            """
            UPDATE htv145_control_state SET
                next_sequence = ?, counter_synchronized = 1,
                counter_source = ?, pending_command_id = NULL,
                pending_action = NULL, pending_sequence = NULL,
                pending_duration_seconds = NULL, pending_started_at = NULL,
                expected_idle_at = CASE WHEN ? THEN expected_idle_at ELSE NULL END,
                confirmed_watering = ?,
                confirmed_at = ?, last_response_frame = ?,
                last_result = 'confirmed', updated_at = ?
            WHERE valve_endpoint = ? AND pending_command_id = ?
              AND pending_sequence = ? AND pending_action = ?
            """,
            (
                next_sequence,
                confirmation,
                int(watering),
                int(watering),
                observed_at,
                frame,
                observed_at,
                valve_endpoint,
                command_id,
                sequence,
                row["pending_action"],
            ),
        )
        if not cursor.rowcount:
            raise ValueError("HTV145 reservation changed before confirmation")
        self._connection.commit()
        return self.htv145_control_states(valve_endpoint)[0]

    def fail_htv145_command(
        self,
        *,
        valve_endpoint: str,
        command_id: str,
        reason: str,
        observed_at: str,
    ) -> dict[str, Any]:
        """Clear a failed reservation and make the counter unusable."""
        cursor = self._connection.execute(
            """
            UPDATE htv145_control_state SET
                counter_synchronized = 0, counter_source = NULL,
                pending_command_id = NULL, pending_action = NULL,
                pending_sequence = NULL, pending_duration_seconds = NULL,
                pending_started_at = NULL,
                expected_idle_at = CASE
                    WHEN pending_action = 'open' THEN expected_idle_at
                    ELSE NULL
                END,
                last_result = ?, updated_at = ?
            WHERE valve_endpoint = ? AND pending_command_id = ?
            """,
            (reason, observed_at, valve_endpoint, command_id),
        )
        if not cursor.rowcount:
            raise ValueError("HTV145 failure does not match reservation")
        self._connection.commit()
        return self.htv145_control_states(valve_endpoint)[0]

    def accept_endpoint(
        self,
        *,
        endpoint: str,
        device_id: str,
        name: str,
        model: str,
        area: str | None,
        accepted_at: str,
        protocol: str | None = None,
        model_source: str | None = None,
        product_code: int | None = None,
        model_code: int | None = None,
    ) -> dict[str, Any]:
        """Accept or update one observed endpoint in the local registry."""
        self._connection.execute(
            """
            INSERT INTO device_registry(
                endpoint, device_id, name, model, area,
                accepted_at, updated_at, protocol, model_source, product_code,
                model_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET
                name=excluded.name,
                model=excluded.model,
                area=excluded.area,
                protocol=excluded.protocol,
                model_source=excluded.model_source,
                product_code=excluded.product_code,
                model_code=excluded.model_code,
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
                protocol,
                model_source,
                product_code,
                model_code,
            ),
        )
        self._connection.execute(
            "DELETE FROM device_suppressions WHERE endpoint = ?", (endpoint,)
        )
        self._connection.commit()
        return self.registry_device(device_id)

    def update_registry_product_identity(
        self,
        endpoint: str,
        *,
        model: str,
        protocol: str,
        model_source: str,
        product_code: int | None,
        model_code: int | None,
        updated_at: str,
    ) -> dict[str, Any]:
        """Persist a stronger packet-derived product identification."""
        cursor = self._connection.execute(
            "UPDATE device_registry SET model = ?, protocol = ?, "
            "model_source = ?, product_code = ?, model_code = ?, updated_at = ? "
            "WHERE endpoint = ?",
            (
                model,
                protocol,
                model_source,
                product_code,
                model_code,
                updated_at,
                endpoint,
            ),
        )
        if not cursor.rowcount:
            raise KeyError(endpoint)
        self._connection.commit()
        return self.registry_endpoint(endpoint)

    def registry_device(self, device_id: str) -> dict[str, Any]:
        """Return one accepted device or raise KeyError."""
        row = self._connection.execute(
            "SELECT * FROM device_registry WHERE device_id = ?", (device_id,)
        ).fetchone()
        if row is None:
            raise KeyError(device_id)
        return dict(row)

    def registry_endpoint(self, endpoint: str) -> dict[str, Any]:
        """Return one accepted endpoint or raise KeyError."""
        row = self._connection.execute(
            "SELECT * FROM device_registry WHERE endpoint = ?", (endpoint,)
        ).fetchone()
        if row is None:
            raise KeyError(endpoint)
        return dict(row)

    def migrate_registry_device_id(
        self, endpoint: str, device_id: str
    ) -> dict[str, Any]:
        """Align a legacy registration with an established stable identity."""
        cursor = self._connection.execute(
            "UPDATE device_registry SET device_id = ? WHERE endpoint = ?",
            (device_id, endpoint),
        )
        if not cursor.rowcount:
            raise KeyError(endpoint)
        self._connection.commit()
        return self.registry_endpoint(endpoint)

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

    def forget_registry_device(
        self,
        device_id: str,
        *,
        suppressed_at: str,
        enrollment_factory_endpoint: str | None = None,
    ) -> dict[str, Any]:
        """Remove local metadata and suppress automatic RF rediscovery."""
        device = self.registry_device(device_id)
        self._connection.execute(
            "DELETE FROM device_registry WHERE device_id = ?", (device_id,)
        )
        self._connection.execute(
            "INSERT OR REPLACE INTO device_suppressions(endpoint, suppressed_at) "
            "VALUES (?, ?)",
            (device["endpoint"], suppressed_at),
        )
        if enrollment_factory_endpoint is not None:
            self._connection.execute(
                "DELETE FROM hcs026_enrollments WHERE factory_endpoint = ?",
                (enrollment_factory_endpoint,),
            )
        self._connection.commit()
        return device

    def forget_sensor_endpoint(
        self,
        endpoint: str,
        *,
        suppressed_at: str,
        enrollment_factory_endpoint: str,
    ) -> dict[str, Any] | None:
        """Forget any observed HCS026 endpoint in one transaction.

        Automatically discovered paired sensors may not yet have a registry
        row. They still need the same suppression and enrollment cleanup as a
        named sensor so Home Assistant can offer one consistent operation.
        """
        row = self._connection.execute(
            "SELECT * FROM device_registry WHERE endpoint = ?", (endpoint,)
        ).fetchone()
        with self._connection:
            self._connection.execute(
                "DELETE FROM device_registry WHERE endpoint = ?", (endpoint,)
            )
            self._connection.execute(
                "INSERT OR REPLACE INTO device_suppressions(endpoint, suppressed_at) "
                "VALUES (?, ?)",
                (endpoint, suppressed_at),
            )
            self._connection.execute(
                "DELETE FROM hcs026_enrollments WHERE factory_endpoint = ?",
                (enrollment_factory_endpoint,),
            )
        return dict(row) if row is not None else None

    def suppressed_endpoints(self) -> frozenset[str]:
        """Return endpoints explicitly removed from local device exposure."""
        rows = self._connection.execute(
            "SELECT endpoint FROM device_suppressions ORDER BY endpoint"
        ).fetchall()
        return frozenset(str(row["endpoint"]) for row in rows)

    def enrollment_records(self) -> list[dict[str, Any]]:
        """Return persisted HCS026 physical enrollment mappings."""
        rows = self._connection.execute(
            "SELECT * FROM hcs026_enrollments ORDER BY factory_endpoint"
        ).fetchall()
        return [dict(row) for row in rows]

    def ack_assignments(self, node_id: str | None = None) -> list[dict[str, Any]]:
        """Return persistent single-owner sensor acknowledgement routes."""
        if node_id is None:
            rows = self._connection.execute(
                "SELECT * FROM hcs026_ack_assignments "
                "ORDER BY paired_endpoint"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM hcs026_ack_assignments WHERE node_id = ? "
                "ORDER BY paired_endpoint",
                (node_id,),
            ).fetchall()
        assignments = [dict(row) for row in rows]
        for assignment in assignments:
            assignment["invert"] = bool(assignment["invert"])
        return assignments

    def upsert_ack_assignment(self, assignment: dict[str, Any]) -> None:
        """Atomically assign one paired endpoint to exactly one radio node."""
        self._connection.execute(
            """
            INSERT INTO hcs026_ack_assignments(
                paired_endpoint, node_id, assigned_channel,
                frequency_offset_hz, power_dbm, invert, updated_at,
                controller_endpoint, companion_endpoint
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(paired_endpoint) DO UPDATE SET
                node_id=excluded.node_id,
                assigned_channel=excluded.assigned_channel,
                frequency_offset_hz=excluded.frequency_offset_hz,
                power_dbm=excluded.power_dbm,
                invert=excluded.invert,
                updated_at=excluded.updated_at,
                controller_endpoint=excluded.controller_endpoint,
                companion_endpoint=excluded.companion_endpoint
            """,
            (
                assignment["paired_endpoint"],
                assignment["node_id"],
                assignment["assigned_channel"],
                assignment["frequency_offset_hz"],
                assignment["power_dbm"],
                int(bool(assignment["invert"])),
                assignment["updated_at"],
                assignment["controller_endpoint"],
                assignment["companion_endpoint"],
            ),
        )
        self._connection.commit()

    def delete_ack_assignment(self, paired_endpoint: str) -> dict[str, Any] | None:
        """Delete and return one sensor acknowledgement route."""
        row = self._connection.execute(
            "SELECT * FROM hcs026_ack_assignments WHERE paired_endpoint = ?",
            (paired_endpoint,),
        ).fetchone()
        if row is None:
            return None
        self._connection.execute(
            "DELETE FROM hcs026_ack_assignments WHERE paired_endpoint = ?",
            (paired_endpoint,),
        )
        self._connection.commit()
        return dict(row)

    def upsert_enrollment_record(self, record: dict[str, Any]) -> None:
        """Persist one enrollment observation."""
        self._connection.execute(
            """
            INSERT INTO hcs026_enrollments(
                factory_endpoint, paired_endpoint, enrolled_at, last_seen_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(factory_endpoint) DO UPDATE SET
                paired_endpoint=excluded.paired_endpoint,
                enrolled_at=excluded.enrolled_at,
                last_seen_at=excluded.last_seen_at
            """,
            (
                record["factory_endpoint"],
                record["paired_endpoint"],
                record["enrolled_at"],
                record["last_seen_at"],
            ),
        )
        self._connection.commit()

    def delete_enrollment_record(self, factory_endpoint: str) -> bool:
        """Delete one physical enrollment mapping."""
        cursor = self._connection.execute(
            "DELETE FROM hcs026_enrollments WHERE factory_endpoint = ?",
            (factory_endpoint,),
        )
        self._connection.commit()
        return bool(cursor.rowcount)

    def import_enrollment_records(
        self, records: list[dict[str, Any]]
    ) -> None:
        """Import validated legacy mappings in one transaction."""
        with self._connection:
            self._connection.executemany(
                """
                INSERT INTO hcs026_enrollments(
                    factory_endpoint, paired_endpoint, enrolled_at, last_seen_at
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        record["factory_endpoint"],
                        record["paired_endpoint"],
                        record["enrolled_at"],
                        record["last_seen_at"],
                    )
                    for record in records
                ],
            )

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
        if frame_accepted(event) is False:
            return
        roles: dict[str, set[str]] = {}
        for key, role in (
            ("rf_endpoint_a", "a"),
            ("rf_endpoint_b", "b"),
            ("rf_endpoint", "sensor"),
        ):
            endpoint = state.get(key)
            if (
                key == "rf_endpoint_b"
                and "rf_product_code" in state
                and endpoint != state.get("rf_endpoint")
            ):
                # Product-code reports encode a variant in the address byte;
                # discovery uses the separately retained canonical endpoint.
                continue
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

    def _update_reception_metrics(self, event: dict[str, Any]) -> None:
        """Track integrity separately from decoded device-state cadence."""
        device_id = event.get("device_id")
        valid = frame_accepted(event)
        if not isinstance(device_id, str) or not isinstance(valid, bool):
            return
        observed_at = event.get("observed_at")
        event_id = event.get("event_id")
        if not isinstance(observed_at, str) or not isinstance(event_id, int):
            return
        self._connection.execute(
            """
            INSERT INTO device_reception_metrics(
                device_id, valid_frame_count, invalid_frame_count,
                last_frame_at, last_valid_frame_at, last_invalid_frame_at,
                last_frame_event_id, last_valid_frame_event_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                valid_frame_count=(
                    device_reception_metrics.valid_frame_count +
                    excluded.valid_frame_count
                ),
                invalid_frame_count=(
                    device_reception_metrics.invalid_frame_count +
                    excluded.invalid_frame_count
                ),
                last_frame_at=excluded.last_frame_at,
                last_valid_frame_at=COALESCE(
                    excluded.last_valid_frame_at,
                    device_reception_metrics.last_valid_frame_at
                ),
                last_invalid_frame_at=COALESCE(
                    excluded.last_invalid_frame_at,
                    device_reception_metrics.last_invalid_frame_at
                ),
                last_frame_event_id=excluded.last_frame_event_id,
                last_valid_frame_event_id=COALESCE(
                    excluded.last_valid_frame_event_id,
                    device_reception_metrics.last_valid_frame_event_id
                )
            """,
            (
                device_id,
                int(valid),
                int(not valid),
                observed_at,
                observed_at if valid else None,
                observed_at if not valid else None,
                event_id,
                event_id if valid else None,
            ),
        )

    def _update_receiver_metrics(
        self, event: dict[str, Any], *, duplicate: bool = False
    ) -> None:
        """Track physical reception independently from logical event cadence."""
        state = event.get("state", {})
        receiver_id = state.get("rf_receiver_id")
        observed_at = event.get("observed_at")
        if not isinstance(receiver_id, str) or not isinstance(observed_at, str):
            return
        device_id = event.get("device_id")
        if not isinstance(device_id, str):
            device_id = ""
        accepted = frame_accepted(event)
        rssi = state.get("rf_rssi_db")
        has_rssi = isinstance(rssi, (int, float)) and not isinstance(rssi, bool)
        self._connection.execute(
            """
            INSERT INTO receiver_metrics(
                receiver_id, device_id, first_seen, last_seen, frame_count,
                accepted_frame_count, rejected_frame_count,
                duplicate_frame_count, rssi_total, rssi_count, last_rssi
            ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(receiver_id, device_id) DO UPDATE SET
                last_seen=excluded.last_seen,
                frame_count=receiver_metrics.frame_count + 1,
                accepted_frame_count=(
                    receiver_metrics.accepted_frame_count +
                    excluded.accepted_frame_count
                ),
                rejected_frame_count=(
                    receiver_metrics.rejected_frame_count +
                    excluded.rejected_frame_count
                ),
                duplicate_frame_count=(
                    receiver_metrics.duplicate_frame_count +
                    excluded.duplicate_frame_count
                ),
                rssi_total=receiver_metrics.rssi_total + excluded.rssi_total,
                rssi_count=receiver_metrics.rssi_count + excluded.rssi_count,
                last_rssi=COALESCE(excluded.last_rssi, receiver_metrics.last_rssi)
            """,
            (
                receiver_id,
                device_id,
                observed_at,
                observed_at,
                int(accepted is True),
                int(accepted is False),
                int(duplicate),
                float(rssi) if has_rssi else 0.0,
                int(has_rssi),
                float(rssi) if has_rssi else None,
            ),
        )

    def _update_device_metrics(self, event: dict[str, Any]) -> None:
        """Update one device's cadence counters for a decoded observation."""
        if (
            event.get("event_type") != "device_observation"
            or frame_accepted(event) is False
        ):
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
                last_report_interval_seconds, longest_report_gap_seconds
            ) VALUES (?, ?, ?, 1, 0, 0, NULL, 0)
            ON CONFLICT(device_id) DO UPDATE SET
                last_observed_at=excluded.last_observed_at,
                report_count=device_metrics.report_count + 1,
                interval_count=device_metrics.interval_count + ?,
                total_interval_seconds=(
                    device_metrics.total_interval_seconds + ?
                ),
                last_report_interval_seconds=(
                    CASE WHEN ? = 1 THEN ?
                    ELSE device_metrics.last_report_interval_seconds END
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
                interval_increment,
                gap,
                gap,
            ),
        )

    def _backfill_device_metrics(self) -> None:
        """Rebuild cadence once without trailer-rejected observations."""
        count_row = self._connection.execute(
            "SELECT COUNT(*) AS count FROM device_metrics"
        ).fetchone()
        version_row = self._connection.execute(
            "SELECT value FROM storage_metadata WHERE key = ?",
            ("device_metrics_version",),
        ).fetchone()
        if int(count_row["count"]) and (
            version_row is not None and version_row["value"] == "3"
        ):
            return
        self._connection.execute("DELETE FROM device_metrics")
        rows = self._connection.execute(
            "SELECT payload FROM events WHERE event_type = 'device_observation' "
            "ORDER BY event_id"
        ).fetchall()
        for event_row in rows:
            self._update_device_metrics(json.loads(event_row["payload"]))
        self._connection.execute(
            "INSERT OR REPLACE INTO storage_metadata(key, value) VALUES (?, ?)",
            ("device_metrics_version", "3"),
        )

    def _backfill_reception_metrics(self) -> None:
        """Build RF integrity metrics once from retained device events."""
        row = self._connection.execute(
            "SELECT COUNT(*) AS count FROM device_reception_metrics"
        ).fetchone()
        if int(row["count"]):
            return
        rows = self._connection.execute(
            "SELECT payload FROM events ORDER BY event_id"
        ).fetchall()
        for event_row in rows:
            self._update_reception_metrics(json.loads(event_row["payload"]))

    def _rebuild_endpoint_inventory(self) -> None:
        """One-time rebuild that removes trailer-invalid phantom endpoints."""
        row = self._connection.execute(
            "SELECT value FROM storage_metadata WHERE key = ?",
            ("endpoint_inventory_version",),
        ).fetchone()
        if row is not None and row["value"] == "2":
            return
        self._connection.execute("DELETE FROM endpoints")
        rows = self._connection.execute(
            "SELECT payload FROM events ORDER BY event_id"
        ).fetchall()
        for event_row in rows:
            self._update_endpoints(json.loads(event_row["payload"]))
        self._connection.execute(
            "INSERT OR REPLACE INTO storage_metadata(key, value) VALUES (?, ?)",
            ("endpoint_inventory_version", "2"),
        )


def _parse_timestamp(value: str) -> datetime | None:
    """Parse ISO timestamps used by rtl_433 and the replay transport."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
