#!/usr/bin/env python3
"""Estimate RainPoint 2-FSK parameters from rtl_433 CU8 captures.

This intentionally uses only the Python standard library so it can run on the
same lightweight development hosts as the decoder. Absolute frequencies still
include the RTL-SDR's oscillator error; compare several packets and round only
after identifying a stable channel plan.
"""

from __future__ import annotations

import argparse
import cmath
import json
import math
from pathlib import Path
from typing import Any


FFT_SAMPLES = 65_536


def _iq_samples(data: bytes) -> list[complex]:
    return [
        complex(data[index] - 127.5, data[index + 1] - 127.5)
        for index in range(0, len(data) - 1, 2)
    ]


def _strongest_window(samples: list[complex], length: int) -> list[complex]:
    """Select a signal-rich FFT window without requiring burst timestamps."""
    if len(samples) <= length:
        return samples + [0j] * (length - len(samples))
    stride = length // 2
    candidates = range(0, len(samples) - length + 1, stride)
    start = max(
        candidates,
        key=lambda offset: sum(abs(value) ** 2 for value in samples[offset : offset + length]),
    )
    return samples[start : start + length]


def _fft(values: list[complex]) -> None:
    """In-place radix-2 FFT, avoiding a NumPy dependency for one-off captures."""
    length = len(values)
    target = 0
    for index in range(1, length):
        bit = length >> 1
        while target & bit:
            target ^= bit
            bit >>= 1
        target ^= bit
        if index < target:
            values[index], values[target] = values[target], values[index]

    block = 2
    while block <= length:
        step = cmath.exp(-2j * math.pi / block)
        half = block // 2
        for start in range(0, length, block):
            twiddle = 1 + 0j
            for index in range(start, start + half):
                first = values[index]
                second = values[index + half] * twiddle
                values[index] = first + second
                values[index + half] = first - second
                twiddle *= step
        block *= 2


def _symmetric_occupied_width(
    spectrum: list[tuple[float, float]], center: float, fraction: float
) -> int:
    ordered = sorted((abs(frequency - center), power) for frequency, power in spectrum)
    target = sum(power for _, power in ordered) * fraction
    accumulated = 0.0
    for distance, power in ordered:
        accumulated += power
        if accumulated >= target:
            return round(distance * 2)
    return 0


def characterize(
    path: Path,
    *,
    sample_rate: int,
    center_frequency: int,
) -> dict[str, Any]:
    """Estimate stable FSK tones and occupied bandwidth in one CU8 file."""
    samples = _strongest_window(_iq_samples(path.read_bytes()), FFT_SAMPLES)
    for index, sample in enumerate(samples):
        window = 0.5 - 0.5 * math.cos(2 * math.pi * index / (FFT_SAMPLES - 1))
        samples[index] = sample * window
    _fft(samples)

    spectrum: list[tuple[float, float]] = []
    for index, value in enumerate(samples):
        signed_bin = index if index < FFT_SAMPLES // 2 else index - FFT_SAMPLES
        offset = signed_bin * sample_rate / FFT_SAMPLES
        if abs(offset) < 100_000:  # Exclude the RTL-SDR center/DC artifact.
            continue
        spectrum.append((center_frequency + offset, abs(value) ** 2))

    strongest = sorted(spectrum, key=lambda item: item[1], reverse=True)[:500]
    pairs = [
        (first_power + second_power, first_frequency, second_frequency)
        for first_frequency, first_power in strongest
        for second_frequency, second_power in strongest
        if 70_000 <= abs(first_frequency - second_frequency) <= 90_000
    ]
    if not pairs:
        raise ValueError(f"two RainPoint FSK tones not found in {path}")
    _, first, second = max(pairs)
    low, high = sorted((first, second))
    channel_center = (low + high) / 2

    # Limit occupied-bandwidth calculations to the identified channel. Raw CU8
    # clipping can inflate the 99% result, so retain both 95% and 99% figures.
    channel_spectrum = [
        item for item in spectrum if abs(item[0] - channel_center) <= 200_000
    ]
    return {
        "path": str(path),
        "sample_rate_sps": sample_rate,
        "capture_center_hz": center_frequency,
        "low_tone_hz": round(low),
        "high_tone_hz": round(high),
        "channel_center_hz": round(channel_center),
        "tone_separation_hz": round(high - low),
        "deviation_hz": round((high - low) / 2),
        "occupied_95_width_hz": _symmetric_occupied_width(
            channel_spectrum, channel_center, 0.95
        ),
        "occupied_99_width_hz": _symmetric_occupied_width(
            channel_spectrum, channel_center, 0.99
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", nargs="+", type=Path)
    parser.add_argument("--sample-rate", type=int, default=2_000_000)
    parser.add_argument("--frequency", type=int, default=433_700_000)
    args = parser.parse_args()

    found = 0
    for path in args.captures:
        try:
            result = characterize(
                path,
                sample_rate=args.sample_rate,
                center_frequency=args.frequency,
            )
        except ValueError as error:
            print(json.dumps({"path": str(path), "error": str(error)}))
            continue
        print(json.dumps(result, sort_keys=True))
        found += 1
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())
