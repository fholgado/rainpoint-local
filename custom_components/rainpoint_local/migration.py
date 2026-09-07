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
    if type(version) is not int or not 1 <= version <= 3:
        raise ValueError("unsupported config-entry version")
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

    if version < 3:
        host = migrated_data.get(CONF_HOST)
        port = migrated_data.get(CONF_PORT, DEFAULT_PORT)
        if not isinstance(host, str) or not host.strip() or type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("invalid gateway address")
        migrated_data[CONF_HOST] = host.strip()
        migrated_data[CONF_PORT] = port
        legacy_token = migrated_options.pop(CONF_TOKEN, None)
        if not migrated_data.get(CONF_TOKEN) and legacy_token:
            migrated_data[CONF_TOKEN] = str(legacy_token)
        version = 3
    return version, migrated_data, migrated_options
