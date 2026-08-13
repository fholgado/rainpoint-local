"""Pure config-entry migrations for RainPoint Local."""

from __future__ import annotations

from typing import Any

from .const import CONF_HOST, CONF_PORT, CONF_TOKEN, DEFAULT_PORT


def migrate_entry_payload(
    version: int,
    data: dict[str, Any],
    options: dict[str, Any],
) -> tuple[int, dict[str, Any], dict[str, Any]]:
    """Return the current config-entry representation without HA side effects."""
    migrated_data = dict(data)
    migrated_options = dict(options)

    if version < 2:
        migrated_data[CONF_HOST] = str(migrated_data[CONF_HOST]).strip()
        migrated_data[CONF_PORT] = int(
            migrated_data.get(CONF_PORT, DEFAULT_PORT)
        )
        legacy_token = migrated_options.pop(CONF_TOKEN, None)
        if CONF_TOKEN not in migrated_data and legacy_token:
            migrated_data[CONF_TOKEN] = str(legacy_token)
        version = 2

    return version, migrated_data, migrated_options
