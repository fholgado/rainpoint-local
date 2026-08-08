#!/usr/bin/env python3
"""Compare a candidate RainPoint CU8 waveform with an RF reference offline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from .characterize_rainpoint_iq import characterize
except ImportError:  # Direct script execution.
    from characterize_rainpoint_iq import characterize


def compare_waveforms(
    reference: Path,
    candidate: Path,
    *,
    sample_rate: int = 2_000_000,
    capture_center_hz: int = 433_700_000,
    center_tolerance_hz: int = 5_000,
    separation_tolerance_hz: int = 5_000,
    occupied_width_tolerance_hz: int = 30_000,
) -> dict[str, Any]:
    """Compare alignment-independent spectral properties of two waveforms."""
    baseline = characterize(
        reference,
        sample_rate=sample_rate,
        center_frequency=capture_center_hz,
    )
    measured = characterize(
        candidate,
        sample_rate=sample_rate,
        center_frequency=capture_center_hz,
    )
    comparisons = {
        "channel_center_hz": _comparison(
            baseline,
            measured,
            "channel_center_hz",
            center_tolerance_hz,
        ),
        "tone_separation_hz": _comparison(
            baseline,
            measured,
            "tone_separation_hz",
            separation_tolerance_hz,
        ),
        "occupied_95_width_hz": _comparison(
            baseline,
            measured,
            "occupied_95_width_hz",
            occupied_width_tolerance_hz,
        ),
    }
    return {
        "reference": baseline,
        "candidate": measured,
        "comparisons": comparisons,
        "spectral_match": all(item["within_tolerance"] for item in comparisons.values()),
        "scope": (
            "offline spectral comparison only; symbol content and RF power "
            "must be validated separately"
        ),
    }


def _comparison(
    reference: dict[str, Any],
    candidate: dict[str, Any],
    key: str,
    tolerance_hz: int,
) -> dict[str, Any]:
    delta = int(candidate[key]) - int(reference[key])
    return {
        "reference_hz": reference[key],
        "candidate_hz": candidate[key],
        "delta_hz": delta,
        "tolerance_hz": tolerance_hz,
        "within_tolerance": abs(delta) <= tolerance_hz,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--sample-rate", type=int, default=2_000_000)
    parser.add_argument("--frequency", type=int, default=433_700_000)
    parser.add_argument("--center-tolerance", type=int, default=5_000)
    parser.add_argument("--separation-tolerance", type=int, default=5_000)
    parser.add_argument("--width-tolerance", type=int, default=30_000)
    args = parser.parse_args()
    try:
        result = compare_waveforms(
            args.reference,
            args.candidate,
            sample_rate=args.sample_rate,
            capture_center_hz=args.frequency,
            center_tolerance_hz=args.center_tolerance,
            separation_tolerance_hz=args.separation_tolerance,
            occupied_width_tolerance_hz=args.width_tolerance,
        )
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["spectral_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
