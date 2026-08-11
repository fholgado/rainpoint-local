"""Persistent HCS026 enrollment state machine.

Controlled captures show the sensor emitting both its factory identity and the
deterministically related paired identity. This module records only transitions
observed on air; command dispatch remains a separate authenticated boundary.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


STATE_VERSION = 1


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.astimezone()
    return value.astimezone(timezone.utc).isoformat()


def _aware(value: datetime) -> datetime:
    """Interpret naive rtl_433 timestamps in the gateway's local timezone."""
    return value.astimezone() if value.tzinfo is None else value


def _validate_endpoint(endpoint: str) -> bytes:
    if len(endpoint) != 8:
        raise ValueError("HCS026 endpoint must contain exactly four bytes")
    try:
        value = bytes.fromhex(endpoint)
    except ValueError as error:
        raise ValueError("HCS026 endpoint must be hexadecimal") from error
    if value[-1] != 0x24:
        raise ValueError("HCS026 endpoint must use the observed 0x24 suffix")
    return value


def paired_endpoint(factory_endpoint: str) -> str:
    """Derive the paired identity observed for an HCS026 factory identity."""
    value = _validate_endpoint(factory_endpoint)
    if value[0] & 0x80:
        raise ValueError("factory endpoint already has the paired identity bit set")
    return (bytes([value[0] | 0x80]) + value[1:]).hex()


def factory_endpoint(paired: str) -> str:
    """Recover the factory identity from an observed paired identity."""
    value = _validate_endpoint(paired)
    if not value[0] & 0x80:
        raise ValueError("paired endpoint does not have the identity bit set")
    return (bytes([value[0] & 0x7F]) + value[1:]).hex()


@dataclass(frozen=True)
class EnrollmentRecord:
    factory_endpoint: str
    paired_endpoint: str
    enrolled_at: str
    last_seen_at: str


class HCS026EnrollmentManager:
    """Track explicit receive-only enrollment windows and persistent mappings."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._records: dict[str, EnrollmentRecord] = {}
        self._candidates: dict[str, str] = {}
        self._session_enrolled: list[str] = []
        self._window_expires_at: datetime | None = None
        self._load()

    def start(
        self, timeout_seconds: int = 120, *, now: datetime | None = None
    ) -> dict[str, Any]:
        if timeout_seconds < 1 or timeout_seconds > 900:
            raise ValueError("pairing timeout must be between 1 and 900 seconds")
        current = _aware(now or _utc_now())
        self._candidates.clear()
        self._session_enrolled.clear()
        self._window_expires_at = current + timedelta(seconds=timeout_seconds)
        return self.status(now=current)

    def stop(self) -> dict[str, Any]:
        self._window_expires_at = None
        self._candidates.clear()
        return self.status()

    def status(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = _aware(now or _utc_now())
        self._expire(current)
        return {
            "active": self._window_expires_at is not None,
            "expires_at": (
                _timestamp(self._window_expires_at)
                if self._window_expires_at is not None
                else None
            ),
            "candidates": sorted(self._candidates),
            "new_records": [
                asdict(self._records[factory])
                for factory in self._session_enrolled
                if factory in self._records
            ],
            "records": [asdict(record) for record in self.records()],
        }

    def observe(
        self, state: dict[str, Any], *, now: datetime | None = None
    ) -> dict[str, Any]:
        """Consume normalized decoder fields and return an idempotent action."""
        current = _aware(now or _utc_now())
        self._expire(current)
        pairing_state = state.get("hcs026_pairing_state")
        factory = state.get("hcs026_factory_endpoint")
        if pairing_state not in {"factory", "paired"} or not isinstance(factory, str):
            return {"action": "ignored", "reason": "not_hcs026_enrollment"}

        expected_paired = paired_endpoint(factory)
        known = self._records.get(factory)
        if pairing_state == "factory":
            if known is not None:
                self._touch(factory, current)
                return {
                    "action": "known_factory",
                    "record": asdict(self._records[factory]),
                }
            if self._window_expires_at is None:
                return {"action": "ignored", "reason": "pairing_window_closed"}
            self._candidates[factory] = _timestamp(current)
            return {
                "action": "candidate_observed",
                "factory_endpoint": factory,
                "expected_paired_endpoint": expected_paired,
            }

        observed_paired = state.get("hcs026_paired_endpoint")
        if observed_paired != expected_paired:
            return {"action": "ignored", "reason": "identity_mismatch"}
        if known is not None:
            self._touch(factory, current)
            return {
                "action": "known_paired",
                "record": asdict(self._records[factory]),
            }
        if self._window_expires_at is None:
            return {"action": "ignored", "reason": "pairing_window_closed"}
        if factory not in self._candidates:
            return {"action": "ignored", "reason": "factory_announcement_missing"}

        message_type = state.get("message_type", state.get("rf_message_type"))
        if message_type != 3:
            return {
                "action": "paired_progress",
                "factory_endpoint": factory,
                "paired_endpoint": observed_paired,
                "message_type": message_type,
                "terminal_message_required": 3,
            }

        observed_at = _timestamp(current)
        record = EnrollmentRecord(
            factory_endpoint=factory,
            paired_endpoint=observed_paired,
            enrolled_at=observed_at,
            last_seen_at=observed_at,
        )
        self._records[factory] = record
        self._session_enrolled.append(factory)
        self._candidates.pop(factory, None)
        self._save()
        return {"action": "enrolled", "record": asdict(record)}

    def forget(self, endpoint: str) -> bool:
        """Forget local association state without transmitting an RF reset."""
        value = _validate_endpoint(endpoint)
        factory = factory_endpoint(endpoint) if value[0] & 0x80 else endpoint
        removed = self._records.pop(factory, None) is not None
        self._candidates.pop(factory, None)
        if removed:
            self._save()
        return removed

    def records(self) -> list[EnrollmentRecord]:
        return [self._records[key] for key in sorted(self._records)]

    def _expire(self, now: datetime) -> None:
        if self._window_expires_at is not None and now >= self._window_expires_at:
            self._window_expires_at = None
            self._candidates.clear()

    def _touch(self, factory: str, now: datetime) -> None:
        record = self._records[factory]
        self._records[factory] = EnrollmentRecord(
            factory_endpoint=record.factory_endpoint,
            paired_endpoint=record.paired_endpoint,
            enrolled_at=record.enrolled_at,
            last_seen_at=_timestamp(now),
        )
        self._save()

    def _load(self) -> None:
        if not self.path.exists():
            return
        payload = json.loads(self.path.read_text())
        if payload.get("version") != STATE_VERSION:
            raise ValueError("unsupported HCS026 enrollment state version")
        for item in payload.get("records", []):
            record = EnrollmentRecord(**item)
            if paired_endpoint(record.factory_endpoint) != record.paired_endpoint:
                raise ValueError("stored HCS026 identity mapping is invalid")
            self._records[record.factory_endpoint] = record

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "version": STATE_VERSION,
                    "records": [asdict(item) for item in self.records()],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        temporary.replace(self.path)
