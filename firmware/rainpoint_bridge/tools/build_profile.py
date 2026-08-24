"""Select production-safe or explicitly requested research build flags."""

from __future__ import annotations

import os
import re

Import("env")  # type: ignore[name-defined]  # PlatformIO/SCons injection.


research_value = os.environ.get("RAINPOINT_RESEARCH_BENCH", "0")
if research_value not in {"0", "1"}:
    raise ValueError("RAINPOINT_RESEARCH_BENCH must be 0 or 1")

research_enabled = research_value == "1"
default_version = (
    "0.14.0-valve-control-probe.39" if research_enabled else "0.14.0"
)
firmware_version = os.environ.get(
    "RAINPOINT_FIRMWARE_VERSION", default_version
)
if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+-]{0,47}", firmware_version):
    raise ValueError("RAINPOINT_FIRMWARE_VERSION is invalid")

env.Append(
    CPPDEFINES=[
        ("RAINPOINT_RESEARCH_BENCH", int(research_enabled)),
        ("RAINPOINT_FIRMWARE_VERSION", f'\\"{firmware_version}\\"'),
    ]
)
