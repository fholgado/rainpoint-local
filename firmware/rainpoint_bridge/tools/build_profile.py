"""One supported firmware environment and one isolated HTV145 qualification gate.

Production includes sensor pairing/ACKs, HTV405 control and OTA. The HTV145
option selects the frozen counter-2/selector-6 recipe plus bounded controls;
it does not restore serial probes or select individual timing experiments.
"""
from __future__ import annotations

import os
import re

Import("env")  # type: ignore[name-defined]  # PlatformIO/SCons injection.

value = os.environ.get("RAINPOINT_HTV145_ENABLED", "0")
if value not in {"0", "1"}:
    raise ValueError("RAINPOINT_HTV145_ENABLED must be 0 or 1")
retired = [name for name in os.environ if name.startswith("RAINPOINT_") and
           (name.endswith("_CANDIDATE") or name in {
               "RAINPOINT_RESEARCH_BENCH", "RAINPOINT_SUPERVISED_HTV405_CONTROL"})]
if retired:
    raise ValueError("Retired firmware flags: " + ", ".join(sorted(retired)))
enabled = value == "1"
version = os.environ.get("RAINPOINT_FIRMWARE_VERSION",
                         "0.15.17-htv145-control.1" if enabled else "0.15.14")
if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+-]{0,47}", version):
    raise ValueError("RAINPOINT_FIRMWARE_VERSION is invalid")
variant = "htv145-control-candidate" if enabled else "unified"
env.Append(CPPDEFINES=[
    ("RAINPOINT_HTV145_ENABLED", int(enabled)),
    ("RAINPOINT_FIRMWARE_VERSION", f'\\"{version}\\"'),
    ("RAINPOINT_FIRMWARE_VARIANT", f'\\"{variant}\\"'),
])
