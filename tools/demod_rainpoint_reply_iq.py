#!/usr/bin/env python3
"""Recover short RainPoint 2-FSK reply candidates from CU8 captures.

The normal rtl_433 decoder expects the longer sensor wake prefix. Enrollment
captures also contain roughly 31 ms bursts that use the same symbol rate and
deviation but are not emitted as ordinary rows. This offline tool performs
clock-phase search and looks for the established RainPoint sync word.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

try:
    from .characterize_rainpoint_iq import characterize
except ImportError:  # Direct script execution.
    from characterize_rainpoint_iq import characterize


SYNC_BITS = "".join(f"{byte:08b}" for byte in bytes.fromhex("79f4882f28"))


def demodulate(
    path: Path,
    *,
    sample_rate: int = 2_000_000,
    capture_center_hz: int = 433_700_000,
    symbol_rate: int = 20_000,
) -> dict[str, Any]:
    """Return the best exact-sync clock phase and recovered frame bits."""
    if sample_rate % symbol_rate:
        raise ValueError("sample rate must be divisible by symbol rate")
    raw = path.read_bytes()
    samples = [
        complex(raw[index] - 127.5, raw[index + 1] - 127.5)
        for index in range(0, len(raw) - 1, 2)
    ]
    frequency: list[float] = [0.0]
    for previous, current in zip(samples, samples[1:]):
        delta = current * previous.conjugate()
        frequency.append(
            math.atan2(delta.imag, delta.real) * sample_rate / (2 * math.pi)
        )
    cumulative = [0.0]
    for value in frequency:
        cumulative.append(cumulative[-1] + value)

    profile = characterize(
        path,
        sample_rate=sample_rate,
        center_frequency=capture_center_hz,
    )
    threshold = profile["channel_center_hz"] - capture_center_hz
    samples_per_symbol = sample_rate // symbol_rate
    raw_matches: list[dict[str, Any]] = []
    for phase in range(samples_per_symbol):
        bits = []
        offsets = range(phase, len(samples) - samples_per_symbol, samples_per_symbol)
        for offset in offsets:
            mean = (
                cumulative[offset + samples_per_symbol] - cumulative[offset]
            ) / samples_per_symbol
            bits.append("1" if mean > threshold else "0")
        bit_string = "".join(bits)
        for inverted in (False, True):
            candidate = (
                "".join("1" if bit == "0" else "0" for bit in bit_string)
                if inverted
                else bit_string
            )
            start = candidate.find(SYNC_BITS)
            while start >= 0:
                frame = candidate[start : start + 304]
                raw_matches.append(
                    {
                        "phase_samples": phase,
                        "inverted": inverted,
                        "sync_symbol": start,
                        "frame_bits": len(frame),
                        "frame_hex": (
                            int(frame, 2).to_bytes(len(frame) // 8, "big").hex()
                            if len(frame) % 8 == 0
                            else None
                        ),
                    }
                )
                start = candidate.find(SYNC_BITS, start + 1)
    grouped: dict[str, dict[str, Any]] = {}
    for match in raw_matches:
        frame_hex = str(match["frame_hex"])
        item = grouped.setdefault(
            frame_hex,
            {
                "frame_hex": frame_hex,
                "inverted": match["inverted"],
                "phase_samples": [],
                "sync_symbols": [],
            },
        )
        item["phase_samples"].append(match["phase_samples"])
        item["sync_symbols"].append(match["sync_symbol"])
    matches = sorted(
        (
            {
                "frame_hex": item["frame_hex"],
                "inverted": item["inverted"],
                "phase_count": len(item["phase_samples"]),
                "phase_min": min(item["phase_samples"]),
                "phase_max": max(item["phase_samples"]),
                "sync_symbols": sorted(set(item["sync_symbols"])),
            }
            for item in grouped.values()
        ),
        key=lambda item: (-item["phase_count"], item["frame_hex"]),
    )
    return {
        "path": str(path),
        "sample_rate_sps": sample_rate,
        "symbol_rate_sps": symbol_rate,
        "channel_center_hz": profile["channel_center_hz"],
        "matches": matches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", nargs="+", type=Path)
    parser.add_argument("--sample-rate", type=int, default=2_000_000)
    parser.add_argument("--frequency", type=int, default=433_700_000)
    args = parser.parse_args()
    found = False
    for capture in args.captures:
        result = demodulate(
            capture,
            sample_rate=args.sample_rate,
            capture_center_hz=args.frequency,
        )
        print(json.dumps(result, sort_keys=True))
        found = found or bool(result["matches"])
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())
