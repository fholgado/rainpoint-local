"""Select production-safe or explicitly requested research build flags."""

from __future__ import annotations

import os
import re

Import("env")  # type: ignore[name-defined]  # PlatformIO/SCons injection.


research_value = os.environ.get("RAINPOINT_RESEARCH_BENCH", "0")
if research_value not in {"0", "1"}:
    raise ValueError("RAINPOINT_RESEARCH_BENCH must be 0 or 1")

supervised_value = os.environ.get(
    "RAINPOINT_SUPERVISED_HTV405_CONTROL", "0"
)
if supervised_value not in {"0", "1"}:
    raise ValueError("RAINPOINT_SUPERVISED_HTV405_CONTROL must be 0 or 1")

htv145_value = os.environ.get("RAINPOINT_HTV145_TX_CANDIDATE", "0")
if htv145_value not in {"0", "1"}:
    raise ValueError("RAINPOINT_HTV145_TX_CANDIDATE must be 0 or 1")

research_enabled = research_value == "1"
supervised_enabled = supervised_value == "1"
htv145_enabled = htv145_value == "1"
htv145_pairing_value = os.environ.get(
    "RAINPOINT_HTV145_PAIRING_CANDIDATE", "0"
)
if htv145_pairing_value not in {"0", "1"}:
    raise ValueError("RAINPOINT_HTV145_PAIRING_CANDIDATE must be 0 or 1")
htv145_pairing_enabled = htv145_pairing_value == "1"
if htv145_enabled and not research_enabled:
    raise ValueError(
        "RAINPOINT_HTV145_TX_CANDIDATE requires RAINPOINT_RESEARCH_BENCH=1"
    )
if htv145_pairing_enabled and not research_enabled:
    raise ValueError(
        "RAINPOINT_HTV145_PAIRING_CANDIDATE requires "
        "RAINPOINT_RESEARCH_BENCH=1"
    )
standard_version = "0.15.1"
supervised_version = "0.15.0-supervised-beta.7"
htv145_candidate_version = "0.15.0-htv145-control-candidate.1"
htv145_pairing_candidate_version = "0.15.1-htv145-pairing-probe.5"
if htv145_pairing_enabled:
    default_version = htv145_pairing_candidate_version
    firmware_variant = "htv145-pairing-probe"
elif htv145_enabled:
    default_version = htv145_candidate_version
    firmware_variant = "htv145-control-candidate"
elif supervised_enabled:
    default_version = supervised_version
    firmware_variant = "unified"
elif research_enabled:
    default_version = "0.15.0-research-bench.1"
    firmware_variant = "research-bench"
else:
    default_version = standard_version
    firmware_variant = "unified"
firmware_version = os.environ.get(
    "RAINPOINT_FIRMWARE_VERSION", default_version
)
if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+-]{0,47}", firmware_version):
    raise ValueError("RAINPOINT_FIRMWARE_VERSION is invalid")

env.Append(
    CPPDEFINES=[
        ("RAINPOINT_RESEARCH_BENCH", int(research_enabled)),
        (
            "RAINPOINT_SUPERVISED_HTV405_CONTROL",
            int(supervised_enabled),
        ),
        ("RAINPOINT_HTV145_TX_CANDIDATE", int(htv145_enabled)),
        (
            "RAINPOINT_HTV145_PAIRING_CANDIDATE",
            int(htv145_pairing_enabled),
        ),
        ("RAINPOINT_FIRMWARE_VERSION", f'\\"{firmware_version}\\"'),
        ("RAINPOINT_FIRMWARE_VARIANT", f'\\"{firmware_variant}\\"'),
    ]
)
