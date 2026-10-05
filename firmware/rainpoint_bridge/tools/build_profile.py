"""Unified sensors and three valve families; research aliases remain opt-in."""
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
experiment = os.environ.get("RAINPOINT_HTV213_PAIRING_EXPERIMENT", "0")
if experiment not in {"0", "1"}:
    raise ValueError("RAINPOINT_HTV213_PAIRING_EXPERIMENT must be 0 or 1")
if experiment == "1":
    if "htv213" not in version or "-" not in version:
        raise ValueError("HTV213 experiment requires an explicit htv213 prerelease version")
    env.Append(CPPDEFINES=["RAINPOINT_HTV213_PAIRING_EXPERIMENT"])
control_experiment = os.environ.get("RAINPOINT_HTV213_CONTROL_EXPERIMENT", "0")
if control_experiment not in {"0", "1"}:
    raise ValueError("RAINPOINT_HTV213_CONTROL_EXPERIMENT must be 0 or 1")
if control_experiment == "1":
    if experiment != "1":
        raise ValueError("HTV213 dry control requires the isolated pairing canary")
    env.Append(CPPDEFINES=["RAINPOINT_HTV213_CONTROL_EXPERIMENT"])
env["RAINPOINT_BUILD_VERSION"] = version
phase_experiment = os.environ.get("RAINPOINT_VALVE_PHASE_EXPERIMENT", "0")
if phase_experiment not in {"0", "1"}:
    raise ValueError("RAINPOINT_VALVE_PHASE_EXPERIMENT must be 0 or 1")
if phase_experiment == "1":
    if ("-phase-trial." not in version or
            os.environ.get("RAINPOINT_HTV213_PAIRING_EXPERIMENT", "0") != "0" or
            os.environ.get("RAINPOINT_HTV213_CONTROL_EXPERIMENT", "0") != "0"):
        raise ValueError("Phase experiment requires its own prerelease and no HTV213 experiment")
    env.Append(CPPDEFINES=["RAINPOINT_VALVE_PHASE_EXPERIMENT"])
env.Append(CPPDEFINES=[
    ("RAINPOINT_FIRMWARE_VERSION", f'\\"{version}\\"'),
    ("RAINPOINT_FIRMWARE_VARIANT", f'\\"{variant}\\"'),
])

# Production trusts release keys only. Explicit test images additionally trust
# development keys so they can receive unattended updates and release handback.
development = os.environ.get("RAINPOINT_DEVELOPMENT_OTA", "0")
if development not in {"0", "1"}:
    raise ValueError("RAINPOINT_DEVELOPMENT_OTA must be 0 or 1")
if development == "1":
    if "RAINPOINT_FIRMWARE_VERSION" not in os.environ or "-" not in version:
        raise ValueError("development OTA requires an explicit prerelease version")
    env.Append(CPPDEFINES=["RAINPOINT_DEVELOPMENT_OTA"])

# Both the gateway package and radio compile pin reviewed public keys.
# An empty set is fail-closed (useful for source checks before provisioning),
# never an implicit unsigned development mode.
package = Path(env.subst("$PROJECT_DIR")).parents[1] / "rainpointd_addon/rainpointd"
key_paths = list((package / "firmware_keys").glob("*.pem"))
if development == "1":
    development_keys = list((package / "firmware_development_keys").glob("*.pem"))
    if not development_keys or any(not p.stem.startswith("rainpoint-development-") for p in development_keys):
        raise ValueError("development OTA requires pinned development public keys")
    key_paths.extend(development_keys)
entries = []
for path in sorted(key_paths):
    if not re.fullmatch(r"[a-z0-9-]{1,32}", path.stem):
        raise ValueError("invalid firmware signing key id")
    pem = path.read_text(encoding="ascii")
    if not pem.startswith("-----BEGIN PUBLIC KEY-----\n") or len(pem) > 512 or ')KEY"' in pem:
        raise ValueError("only bounded public keys may enter firmware")
    entries.append('{"' + path.stem + '", R"KEY(' + pem + ')KEY"}')
if len(entries) > 4:
    raise ValueError("too many firmware signing keys")
build = Path(env.subst("$BUILD_DIR"))
build.mkdir(parents=True, exist_ok=True)
(build / "firmware_trust.h").write_text(
    '#pragma once\n#include "firmware_signature.h"\nnamespace rainpoint {\n'
    'inline const std::array<FirmwareSigningKey, ' + str(len(entries)) + '> kFirmwareSigningKeys = {{\n' +
    ',\n'.join(entries) + '\n}};\n}\n', encoding="ascii")
env.Append(CPPPATH=[str(build)])
