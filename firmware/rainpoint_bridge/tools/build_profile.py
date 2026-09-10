"""One production firmware with sensor and both valve families enabled."""
from __future__ import annotations

import os
import re
from pathlib import Path

Import("env")  # type: ignore[name-defined]  # PlatformIO/SCons injection.

retired = [name for name in os.environ if name.startswith("RAINPOINT_") and
           (name.endswith("_CANDIDATE") or name in {
               "RAINPOINT_RESEARCH_BENCH", "RAINPOINT_SUPERVISED_HTV405_CONTROL",
               "RAINPOINT_HTV145_ENABLED"})]
if retired:
    raise ValueError("Retired firmware flags: " + ", ".join(sorted(retired)))
version = os.environ.get(
    "RAINPOINT_FIRMWARE_VERSION",
    (Path(env.subst("$PROJECT_DIR")) / "version.txt").read_text().strip(),
)
if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+-]{0,47}", version):
    raise ValueError("RAINPOINT_FIRMWARE_VERSION is invalid")
variant = "unified"
env["RAINPOINT_BUILD_VERSION"] = version
env.Append(CPPDEFINES=[
    ("RAINPOINT_FIRMWARE_VERSION", f'\\"{version}\\"'),
    ("RAINPOINT_FIRMWARE_VARIANT", f'\\"{variant}\\"'),
])
