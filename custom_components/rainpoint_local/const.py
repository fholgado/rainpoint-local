"""Constants for RainPoint Local."""

from datetime import timedelta

DOMAIN = "rainpoint_local"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_TOKEN = "registry_write_token"
DEFAULT_PORT = 8787
DEFAULT_SCAN_INTERVAL = timedelta(seconds=5)
API_VERSION = "v1"
PLATFORMS = ["sensor", "binary_sensor", "button"]
