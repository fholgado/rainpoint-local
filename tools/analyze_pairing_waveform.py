#!/usr/bin/env python3
"""Inventory RF bursts and measure balanced RainPoint wake symbols in CU8 IQ.

Frame decoders are intentionally not used here. Exact-sync demodulation proves
packet content, but it can miss an unframed transmission and an unconstrained
FFT can select a data-dependent sideband instead of the two physical FSK tones.
This tool provides two independent checks:

* ``inventory`` finds every energy burst in a bounded capture window; and
* ``waveform`` measures the alternating wake one symbol at a time, giving each
  FSK tone equal weight regardless of the frame payload.

NumPy is optional for the repository as a whole but required to process IQ.
The pure comparison helpers remain importable by the normal test suite.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Iterable

try:
    import numpy as np
except (ImportError, ModuleNotFoundError):  # Research-only acceleration.
    np = None


DEFAULT_SAMPLE_RATE = 2_000_000
DEFAULT_CAPTURE_CENTER_HZ = 433_700_000
DEFAULT_SYMBOL_RATE = 20_000
DEFAULT_WAKE_SYMBOLS = 320
DEFAULT_ACTIVE_THRESHOLD = 5.0


def cc1101_deviation_hz(register: int, *, crystal_hz: int = 26_000_000) -> float:
    """Return the CC1101 deviation represented by one DEVIATN register."""
    if not 0 <= register <= 0x77:
        raise ValueError("deviation register is outside the CC1101 field range")
    exponent = (register >> 4) & 0x07
    mantissa = register & 0x07
    return crystal_hz / (1 << 17) * (8 + mantissa) * (1 << exponent)


def closest_deviation_register(
    measured_hz: float,
    *,
    candidates: Iterable[int] = (0x43, 0x45),
) -> dict[str, Any]:
    """Identify the closest allowed CC1101 deviation profile."""
    values = [(int(register), cc1101_deviation_hz(int(register))) for register in candidates]
    if not values:
        raise ValueError("at least one candidate register is required")
    register, expected = min(values, key=lambda item: abs(item[1] - measured_hz))
    return {
        "register": register,
        "register_hex": f"0x{register:02x}",
        "expected_hz": round(expected, 3),
        "measured_hz": round(float(measured_hz), 3),
        "error_hz": round(float(measured_hz) - expected, 3),
    }


def normalized_phy_comparison(
    *,
    reference_request_center_hz: float,
    reference_reply_center_hz: float,
    candidate_request_center_hz: float,
    candidate_reply_center_hz: float,
) -> dict[str, float]:
    """Compare replies relative to the same device's request oscillator.

    SDR and transmitter crystal error make absolute centers from separate
    sessions unsafe to compare directly. The valve request in each session is
    the common oscillator reference seen by the valve receiver.
    """
    reference_offset = reference_reply_center_hz - reference_request_center_hz
    candidate_offset = candidate_reply_center_hz - candidate_request_center_hz
    return {
        "reference_reply_minus_request_hz": round(reference_offset, 3),
        "candidate_reply_minus_request_hz": round(candidate_offset, 3),
        "candidate_minus_reference_hz": round(candidate_offset - reference_offset, 3),
    }


def group_active_indexes(
    indexes: Iterable[int],
    *,
    maximum_gap_samples: int,
    minimum_active_samples: int,
) -> list[dict[str, int]]:
    """Group threshold crossings while tolerating short fades."""
    if maximum_gap_samples < 0 or minimum_active_samples <= 0:
        raise ValueError("gap must be non-negative and minimum must be positive")
    groups: list[dict[str, int]] = []
    start: int | None = None
    previous: int | None = None
    count = 0
    for value in indexes:
        current = int(value)
        if previous is not None and current <= previous:
            raise ValueError("active indexes must be strictly increasing")
        if previous is None or current - previous <= maximum_gap_samples + 1:
            if start is None:
                start = current
            count += 1
        else:
            if start is not None and count >= minimum_active_samples:
                groups.append(
                    {
                        "start_index": start,
                        "end_index": previous,
                        "active_samples": count,
                    }
                )
            start = current
            count = 1
        previous = current
    if start is not None and previous is not None and count >= minimum_active_samples:
        groups.append(
            {
                "start_index": start,
                "end_index": previous,
                "active_samples": count,
            }
        )
    return groups


def _require_numpy() -> None:
    if np is None:
        raise RuntimeError(
            "NumPy is required for IQ analysis; use the bundled workspace "
            "Python runtime or install the research dependency"
        )


def _read_window(
    path: Path,
    *,
    sample_rate: int,
    start_seconds: float,
    duration_seconds: float,
):
    _require_numpy()
    assert np is not None
    if start_seconds < 0 or duration_seconds <= 0:
        raise ValueError("start must be non-negative and duration must be positive")
    first_sample = round(start_seconds * sample_rate)
    sample_count = round(duration_seconds * sample_rate)
    raw = np.memmap(path, dtype=np.uint8, mode="r")
    first_byte = first_sample * 2
    last_byte = min(raw.size, first_byte + sample_count * 2)
    if last_byte - first_byte < 4:
        raise ValueError("analysis window does not contain IQ samples")
    bounded = raw[first_byte:last_byte].astype(np.float32)
    return (bounded[0::2] - 127.5) + 1j * (bounded[1::2] - 127.5)


def inventory_bursts(
    path: Path,
    *,
    sample_rate: int,
    capture_center_hz: int,
    start_seconds: float,
    duration_seconds: float,
    active_threshold: float = DEFAULT_ACTIVE_THRESHOLD,
    maximum_gap_ms: float = 2.0,
    minimum_duration_ms: float = 0.5,
) -> dict[str, Any]:
    """Return every decoder-independent energy burst in one bounded window."""
    _require_numpy()
    assert np is not None
    samples = _read_window(
        path,
        sample_rate=sample_rate,
        start_seconds=start_seconds,
        duration_seconds=duration_seconds,
    )
    magnitude = np.abs(samples)
    active = np.flatnonzero(magnitude > active_threshold)
    grouped = group_active_indexes(
        active.tolist(),
        maximum_gap_samples=round(maximum_gap_ms * sample_rate / 1_000),
        minimum_active_samples=round(minimum_duration_ms * sample_rate / 1_000),
    )
    bursts = []
    for item in grouped:
        left = item["start_index"]
        right = item["end_index"] + 1
        segment = samples[left:right]
        segment_magnitude = magnitude[left:right]
        valid = (segment_magnitude[1:] > active_threshold) & (
            segment_magnitude[:-1] > active_threshold
        )
        frequency = (
            np.angle(segment[1:] * np.conj(segment[:-1]))
            * sample_rate
            / (2 * math.pi)
        )[valid]
        raw_segment = np.column_stack((segment.real + 127.5, segment.imag + 127.5))
        rails = (raw_segment <= 0.5) | (raw_segment >= 254.5)
        bursts.append(
            {
                "start_seconds": round(start_seconds + left / sample_rate, 6),
                "end_seconds": round(start_seconds + (right - 1) / sample_rate, 6),
                "duration_ms": round((right - left) * 1_000 / sample_rate, 3),
                "active_samples": item["active_samples"],
                "active_fraction": round(item["active_samples"] / (right - left), 6),
                "magnitude_median": round(float(np.median(segment_magnitude)), 3),
                "adc_rail_fraction": round(float(np.mean(rails)), 6),
                "instantaneous_frequency_hz": {
                    "p10": round(capture_center_hz + float(np.percentile(frequency, 10))),
                    "median": round(capture_center_hz + float(np.median(frequency))),
                    "p90": round(capture_center_hz + float(np.percentile(frequency, 90))),
                },
            }
        )
    return {
        "path": str(path),
        "analysis_window": {
            "start_seconds": start_seconds,
            "duration_seconds": duration_seconds,
        },
        "active_threshold": active_threshold,
        "burst_count": len(bursts),
        "bursts": bursts,
        "scope": "energy inventory only; no frame decoder or sync-word filter",
    }


def _cluster_transitions(candidates, *, minimum_spacing_samples: int):
    assert np is not None
    groups: list[list[int]] = []
    for candidate in candidates:
        value = int(candidate)
        if not groups or value - groups[-1][-1] >= minimum_spacing_samples:
            groups.append([value])
        else:
            groups[-1].append(value)
    return np.asarray([round(float(np.median(group))) for group in groups], dtype=int)


def analyze_balanced_wake(
    path: Path,
    *,
    sample_rate: int,
    capture_center_hz: int,
    decision_center_hz: int,
    start_seconds: float,
    duration_seconds: float,
    active_threshold: float = DEFAULT_ACTIVE_THRESHOLD,
    symbol_rate: int = DEFAULT_SYMBOL_RATE,
    wake_symbols: int = DEFAULT_WAKE_SYMBOLS,
) -> dict[str, Any]:
    """Measure an alternating wake without payload-weighted spectral bias."""
    _require_numpy()
    assert np is not None
    samples = _read_window(
        path,
        sample_rate=sample_rate,
        start_seconds=start_seconds,
        duration_seconds=duration_seconds,
    )
    magnitude = np.abs(samples)
    active = np.flatnonzero(magnitude > active_threshold)
    if active.size < wake_symbols:
        raise ValueError("no complete active waveform found in analysis window")
    left = int(active[0])
    right = int(active[-1]) + 1
    waveform = samples[left:right]
    waveform_magnitude = magnitude[left:right]
    frequency = (
        np.angle(waveform[1:] * np.conj(waveform[:-1]))
        * sample_rate
        / (2 * math.pi)
    )
    smoothing = max(3, round(sample_rate / symbol_rate / 5))
    smoothed = np.convolve(frequency, np.ones(smoothing) / smoothing, mode="same")
    threshold = decision_center_hz - capture_center_hz
    binary = smoothed > threshold
    transitions = np.flatnonzero(binary[1:] != binary[:-1]) + 1
    samples_per_symbol = sample_rate / symbol_rate
    transitions = transitions[
        (transitions > samples_per_symbol * 0.3)
        & (transitions < samples_per_symbol * (wake_symbols + 1))
    ]
    transitions = _cluster_transitions(
        transitions,
        minimum_spacing_samples=max(1, round(samples_per_symbol / 2)),
    )[: wake_symbols - 1]
    if transitions.size < wake_symbols * 0.8:
        raise ValueError("alternating wake transitions could not be recovered")
    x = np.arange(transitions.size)
    slope, intercept = np.polyfit(x, transitions, 1)
    residual = transitions - (slope * x + intercept)
    symbol_frequencies = []
    for interval_left, interval_right in zip(transitions[:-1], transitions[1:]):
        margin = max(5, (interval_right - interval_left) // 4)
        interior = frequency[
            interval_left + margin : interval_right - margin
        ]
        if interior.size:
            symbol_frequencies.append(float(np.median(interior)))
    symbol_frequencies_array = np.asarray(symbol_frequencies)
    low = symbol_frequencies_array[symbol_frequencies_array < threshold]
    high = symbol_frequencies_array[symbol_frequencies_array > threshold]
    if low.size < 10 or high.size < 10:
        raise ValueError("both alternating FSK tones were not recovered")
    low_tone = capture_center_hz + float(np.median(low))
    high_tone = capture_center_hz + float(np.median(high))
    raw_waveform = np.column_stack((waveform.real + 127.5, waveform.imag + 127.5))
    rails = (raw_waveform <= 0.5) | (raw_waveform >= 254.5)
    return {
        "path": str(path),
        "analysis_window": {
            "start_seconds": start_seconds,
            "duration_seconds": duration_seconds,
        },
        "burst": {
            "start_seconds": round(start_seconds + left / sample_rate, 9),
            "end_seconds": round(start_seconds + (right - 1) / sample_rate, 9),
            "duration_ms": round((right - left) * 1_000 / sample_rate, 6),
            "magnitude_median": round(float(np.median(waveform_magnitude)), 3),
            "adc_rail_fraction": round(float(np.mean(rails)), 6),
        },
        "wake": {
            "requested_symbols": wake_symbols,
            "recovered_transitions": int(transitions.size),
            "symbol_rate_sps": round(sample_rate / slope, 3),
            "symbol_duration_us": round(slope * 1_000_000 / sample_rate, 6),
            "transition_fit_rms_samples": round(
                float(np.sqrt(np.mean(residual**2))), 6
            ),
        },
        "fsk": {
            "low_tone_hz": round(low_tone),
            "high_tone_hz": round(high_tone),
            "channel_center_hz": round((low_tone + high_tone) / 2),
            "deviation_hz": round((high_tone - low_tone) / 2),
            "closest_deviation_register": closest_deviation_register(
                (high_tone - low_tone) / 2
            ),
        },
        "method": (
            "median instantaneous frequency from the interior half of each "
            "recovered alternating wake symbol"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser("inventory")
    inventory.add_argument("capture", type=Path)
    inventory.add_argument("--start-seconds", type=float, required=True)
    inventory.add_argument("--duration-seconds", type=float, required=True)
    inventory.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE)
    inventory.add_argument("--capture-center", type=int, default=DEFAULT_CAPTURE_CENTER_HZ)
    inventory.add_argument("--threshold", type=float, default=DEFAULT_ACTIVE_THRESHOLD)
    inventory.add_argument("--maximum-gap-ms", type=float, default=2.0)
    inventory.add_argument("--minimum-duration-ms", type=float, default=0.5)

    waveform = subparsers.add_parser("waveform")
    waveform.add_argument("capture", type=Path)
    waveform.add_argument("--start-seconds", type=float, required=True)
    waveform.add_argument("--duration-seconds", type=float, required=True)
    waveform.add_argument("--decision-center", type=int, required=True)
    waveform.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE)
    waveform.add_argument("--capture-center", type=int, default=DEFAULT_CAPTURE_CENTER_HZ)
    waveform.add_argument("--symbol-rate", type=int, default=DEFAULT_SYMBOL_RATE)
    waveform.add_argument("--wake-symbols", type=int, default=DEFAULT_WAKE_SYMBOLS)
    waveform.add_argument("--threshold", type=float, default=DEFAULT_ACTIVE_THRESHOLD)

    args = parser.parse_args()
    try:
        if args.command == "inventory":
            result = inventory_bursts(
                args.capture,
                sample_rate=args.sample_rate,
                capture_center_hz=args.capture_center,
                start_seconds=args.start_seconds,
                duration_seconds=args.duration_seconds,
                active_threshold=args.threshold,
                maximum_gap_ms=args.maximum_gap_ms,
                minimum_duration_ms=args.minimum_duration_ms,
            )
        else:
            result = analyze_balanced_wake(
                args.capture,
                sample_rate=args.sample_rate,
                capture_center_hz=args.capture_center,
                decision_center_hz=args.decision_center,
                start_seconds=args.start_seconds,
                duration_seconds=args.duration_seconds,
                active_threshold=args.threshold,
                symbol_rate=args.symbol_rate,
                wake_symbols=args.wake_symbols,
            )
    except (RuntimeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
