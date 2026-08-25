"""Persistent identity for one custom local RainPoint RF gateway."""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


IDENTITY_METADATA_KEY = "local_rf_controller_identity_v1"
IDENTITY_VERSION = 1
LEGACY_STOCK_COMPANION_ENDPOINT = "39840280"
LEGACY_STOCK_CONTROLLER_ENDPOINT = "b9840280"


class IdentityStore(Protocol):
    """Small persistence boundary used by identity provisioning."""

    def metadata_value(self, key: str) -> str | None: ...

    def set_metadata_value(self, key: str, value: str) -> None: ...


def _endpoint(value: str) -> bytes:
    normalized = value.strip().lower()
    if len(normalized) != 8:
        raise ValueError("RF controller endpoint must contain four bytes")
    try:
        endpoint = bytes.fromhex(normalized)
    except ValueError as error:
        raise ValueError("RF controller endpoint must be hexadecimal") from error
    if endpoint == bytes(4):
        raise ValueError("RF controller endpoint cannot be zero")
    return endpoint


def controller_endpoint_for(companion_endpoint: str) -> str:
    """Return the observed active-controller form of a companion endpoint."""
    companion = bytearray(_endpoint(companion_endpoint))
    if companion[0] & 0x80:
        raise ValueError("companion endpoint must have a clear association bit")
    companion[0] |= 0x80
    return companion.hex()


@dataclass(frozen=True)
class LocalRFControllerIdentity:
    """One durable gateway-wide RF identity shared by all radio nodes."""

    version: int
    companion_endpoint: str
    controller_endpoint: str
    created_at: str

    @classmethod
    def from_json(cls, value: str) -> LocalRFControllerIdentity:
        try:
            payload = json.loads(value)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("stored RF controller identity is invalid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("stored RF controller identity must be an object")
        identity = cls(
            version=int(payload.get("version", 0)),
            companion_endpoint=str(payload.get("companion_endpoint", "")).lower(),
            controller_endpoint=str(payload.get("controller_endpoint", "")).lower(),
            created_at=str(payload.get("created_at", "")),
        )
        identity.validate()
        return identity

    def validate(self) -> None:
        if self.version != IDENTITY_VERSION:
            raise ValueError("unsupported RF controller identity version")
        companion = _endpoint(self.companion_endpoint)
        if companion[0] & 0x80:
            raise ValueError("companion endpoint must have a clear association bit")
        # All captured RainPoint controller identities use the 0x80 family
        # suffix. Preserve that observed constraint until broader hardware
        # validation proves a larger address space safe.
        if companion[-1] != 0x80:
            raise ValueError("companion endpoint must use the observed 0x80 suffix")
        if self.controller_endpoint != controller_endpoint_for(
            self.companion_endpoint
        ):
            raise ValueError("controller endpoint does not match companion endpoint")
        if self.companion_endpoint == LEGACY_STOCK_COMPANION_ENDPOINT:
            raise ValueError("custom RF identity cannot reuse the stock endpoint")
        try:
            parsed = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("RF controller identity creation time is invalid") from error
        if parsed.tzinfo is None:
            raise ValueError("RF controller identity creation time must be timezone-aware")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), separators=(",", ":"), sort_keys=True)


def generate_local_rf_identity(
    *,
    random_bytes: Callable[[int], bytes] = secrets.token_bytes,
    now: datetime | None = None,
) -> LocalRFControllerIdentity:
    """Generate a compatible identity without using installation data."""
    for _ in range(32):
        random_part = bytearray(random_bytes(3))
        if len(random_part) != 3:
            raise ValueError("RF identity entropy source returned the wrong size")
        random_part[0] &= 0x7F
        if random_part[0] == 0:
            continue
        companion = bytes((*random_part, 0x80)).hex()
        if companion == LEGACY_STOCK_COMPANION_ENDPOINT:
            continue
        timestamp = (now or datetime.now(timezone.utc)).astimezone(
            timezone.utc
        ).isoformat()
        identity = LocalRFControllerIdentity(
            version=IDENTITY_VERSION,
            companion_endpoint=companion,
            controller_endpoint=controller_endpoint_for(companion),
            created_at=timestamp,
        )
        identity.validate()
        return identity
    raise RuntimeError("unable to generate a non-reserved RF controller identity")


def load_or_create_local_rf_identity(
    store: IdentityStore,
    *,
    random_bytes: Callable[[int], bytes] = secrets.token_bytes,
    now: datetime | None = None,
) -> LocalRFControllerIdentity:
    """Return the durable identity, creating it exactly once when absent."""
    stored = store.metadata_value(IDENTITY_METADATA_KEY)
    if stored is not None:
        return LocalRFControllerIdentity.from_json(stored)
    identity = generate_local_rf_identity(random_bytes=random_bytes, now=now)
    store.set_metadata_value(IDENTITY_METADATA_KEY, identity.to_json())
    return identity
