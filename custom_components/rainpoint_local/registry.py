"""Entry-scoped device lookup across the supported HA versions."""
from typing import Any


def device_for_entry(registry: Any, entry_id: str, identifier: tuple[str, str]) -> Any:
    """Never return another gateway entry's device with the same identifier."""
    if (lookup := getattr(registry, "async_get_device_by_identifier", None)) is not None:
        return lookup(identifier, entry_id)
    # HA 2026.7 predates scoped lookups. Only its compatibility path uses these
    # APIs; 2026.8+ must not call deprecated methods/properties.
    device = registry.async_get_device(identifiers={identifier})
    return device if device is not None and entry_id in device.config_entries else None
