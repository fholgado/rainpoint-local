"""Regression tests; make the add-on importable without installing HA."""
from pathlib import Path
import sys

ADDON_ROOT = Path(__file__).resolve().parents[1] / "rainpointd_addon"
sys.path.insert(0, str(ADDON_ROOT))
