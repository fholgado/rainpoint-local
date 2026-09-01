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
    import numpy as np
except (ImportError, ModuleNotFoundError):  # Optional research acceleration.
    np = None

try:
    from .characterize_rainpoint_iq import characterize
except ImportError:  # Direct script execution.
    from characterize_rainpoint_iq import characterize


SYNC_BITS = "".join(f"{byte:08b}" for byte in bytes.fromhex("79f4882f28"))
SYNC_BYTES = bytes.fromhex("79f4882f28")
INVERTED_SYNC_BYTES = bytes(byte ^ 0xFF for byte in SYNC_BYTES)


def _group_matches(raw_matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse successful clock phases into the established result shape."""
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
                "alternating_wake_symbols": [],
            },
        )
        item["phase_samples"].append(match["phase_samples"])
        item["sync_symbols"].append(match["sync_symbol"])
        item["alternating_wake_symbols"].append(
            match["alternating_wake_symbols"]
        )
    return sorted(
        (
            {
                "frame_hex": item["frame_hex"],
                "inverted": item["inverted"],
                "phase_count": len(item["phase_samples"]),
                "phase_min": min(item["phase_samples"]),
                "phase_max": max(item["phase_samples"]),
                "sync_symbols": sorted(set(item["sync_symbols"])),
                "alternating_wake_symbols": sorted(
                    set(item["alternating_wake_symbols"])
                ),
            }
            for item in grouped.values()
        ),
        key=lambda item: (-item["phase_count"], item["frame_hex"]),
    )


def _numpy_frequency_cumulative(path: Path, sample_rate: int):
    """Build one frequency discriminator shared by every RF decision center."""
    assert np is not None
    raw = np.memmap(path, dtype=np.uint8, mode="r")
    sample_count = int(raw.size // 2)
    if sample_count < 2:
        raise ValueError("capture does not contain enough IQ samples")
    frequency = np.empty(sample_count, dtype=np.float32)
    frequency[0] = 0.0
    scale = sample_rate / (2 * math.pi)
    chunk_samples = 2_000_000
    for start in range(1, sample_count, chunk_samples):
        end = min(sample_count, start + chunk_samples)
        source_start = start - 1
        chunk = raw[source_start * 2 : end * 2]
        in_phase = chunk[0::2].astype(np.float32)
        quadrature = chunk[1::2].astype(np.float32)
        in_phase -= 127.5
        quadrature -= 127.5
        real = (
            in_phase[1:] * in_phase[:-1]
            + quadrature[1:] * quadrature[:-1]
        )
        imaginary = (
            quadrature[1:] * in_phase[:-1]
            - in_phase[1:] * quadrature[:-1]
        )
        frequency[start:end] = np.arctan2(imaginary, real) * scale
    cumulative = np.empty(sample_count + 1, dtype=np.float64)
    cumulative[0] = 0.0
    np.cumsum(frequency, dtype=np.float64, out=cumulative[1:])
    del frequency
    del raw
    return cumulative


def _numpy_sync_offsets(bits) -> list[tuple[int, bool]]:
    """Find exact normal and inverted sync words at every bit alignment."""
    assert np is not None
    packed = np.packbits(bits, bitorder="big")
    offsets: list[tuple[int, bool]] = []
    for bit_offset in range(8):
        if bit_offset == 0:
            aligned = packed
        elif packed.size < 2:
            continue
        else:
            aligned = np.bitwise_or(
                np.left_shift(packed[:-1], bit_offset),
                np.right_shift(packed[1:], 8 - bit_offset),
            )
        encoded = aligned.tobytes()
        for inverted, target in (
            (False, SYNC_BYTES),
            (True, INVERTED_SYNC_BYTES),
        ):
            position = encoded.find(target)
            while position >= 0:
                start = bit_offset + position * 8
                if start + len(SYNC_BITS) <= bits.size:
                    offsets.append((start, inverted))
                position = encoded.find(target, position + 1)
    return sorted(set(offsets))


def _numpy_raw_matches(bits, phase: int) -> list[dict[str, Any]]:
    """Decode every exact-sync frame recovered for one sample phase."""
    assert np is not None
    matches: list[dict[str, Any]] = []
    for start, inverted in _numpy_sync_offsets(bits):
        frame = bits[start : start + 304]
        if inverted:
            frame = np.logical_not(frame)
        frame_hex = None
        if frame.size % 8 == 0:
            frame_hex = np.packbits(frame, bitorder="big").tobytes().hex()
        wake_symbols = 0
        cursor = start - 1
        next_bit = bool(bits[start]) ^ inverted
        while cursor >= 0:
            candidate = bool(bits[cursor]) ^ inverted
            if candidate == next_bit:
                break
            wake_symbols += 1
            next_bit = candidate
            cursor -= 1
        matches.append(
            {
                "phase_samples": phase,
                "inverted": inverted,
                "sync_symbol": start,
                "alternating_wake_symbols": wake_symbols,
                "frame_bits": int(frame.size),
                "frame_hex": frame_hex,
            }
        )
    return matches


def demodulate_many(
    path: Path,
    *,
    channel_centers_hz: list[int] | tuple[int, ...],
    sample_rate: int = 2_000_000,
    capture_center_hz: int = 433_700_000,
    symbol_rate: int = 20_000,
) -> dict[int, dict[str, Any]]:
    """Demodulate several RF legs while sharing one IQ discriminator pass."""
    centers = tuple(dict.fromkeys(int(center) for center in channel_centers_hz))
    if not centers:
        raise ValueError("at least one channel center is required")
    if np is None:
        return {
            center: demodulate(
                path,
                sample_rate=sample_rate,
                capture_center_hz=capture_center_hz,
                symbol_rate=symbol_rate,
                channel_center_hz=center,
            )
            for center in centers
        }
    if sample_rate % symbol_rate:
        raise ValueError("sample rate must be divisible by symbol rate")
    cumulative = _numpy_frequency_cumulative(path, sample_rate)
    sample_count = cumulative.size - 1
    samples_per_symbol = sample_rate // symbol_rate
    raw_matches = {center: [] for center in centers}
    thresholds = {
        center: center - capture_center_hz for center in centers
    }
    for phase in range(samples_per_symbol):
        left = cumulative[
            phase : sample_count - samples_per_symbol : samples_per_symbol
        ]
        right = cumulative[
            phase + samples_per_symbol : sample_count : samples_per_symbol
        ]
        count = min(left.size, right.size)
        if count == 0:
            continue
        means = (right[:count] - left[:count]) / samples_per_symbol
        for center in centers:
            bits = means > thresholds[center]
            raw_matches[center].extend(_numpy_raw_matches(bits, phase))
    del cumulative
    return {
        center: {
            "path": str(path),
            "sample_rate_sps": sample_rate,
            "symbol_rate_sps": symbol_rate,
            "channel_center_hz": center,
            "engine": "numpy_shared_discriminator",
            "matches": _group_matches(raw_matches[center]),
        }
        for center in centers
    }


def demodulate(
    path: Path,
    *,
    sample_rate: int = 2_000_000,
    capture_center_hz: int = 433_700_000,
    symbol_rate: int = 20_000,
    channel_center_hz: int | None = None,
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

    if channel_center_hz is None:
        profile = characterize(
            path,
            sample_rate=sample_rate,
            center_frequency=capture_center_hz,
        )
        channel_center_hz = int(profile["channel_center_hz"])
    threshold = channel_center_hz - capture_center_hz
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
                wake_symbols = 0
                cursor = start - 1
                next_bit = candidate[start]
                while cursor >= 0 and candidate[cursor] != next_bit:
                    wake_symbols += 1
                    next_bit = candidate[cursor]
                    cursor -= 1
                frame = candidate[start : start + 304]
                raw_matches.append(
                    {
                        "phase_samples": phase,
                        "inverted": inverted,
                        "sync_symbol": start,
                        "alternating_wake_symbols": wake_symbols,
                        "frame_bits": len(frame),
                        "frame_hex": (
                            int(frame, 2).to_bytes(len(frame) // 8, "big").hex()
                            if len(frame) % 8 == 0
                            else None
                        ),
                    }
                )
                start = candidate.find(SYNC_BITS, start + 1)
    matches = _group_matches(raw_matches)
    return {
        "path": str(path),
        "sample_rate_sps": sample_rate,
        "symbol_rate_sps": symbol_rate,
        "channel_center_hz": channel_center_hz,
        "matches": matches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", nargs="+", type=Path)
    parser.add_argument("--sample-rate", type=int, default=2_000_000)
    parser.add_argument("--frequency", type=int, default=433_700_000)
    parser.add_argument(
        "--channel-center",
        type=int,
        help=(
            "use this known RF channel center as the FSK decision threshold "
            "instead of characterizing the strongest signal in the file"
        ),
    )
    args = parser.parse_args()
    found = False
    for capture in args.captures:
        result = demodulate(
            capture,
            sample_rate=args.sample_rate,
            capture_center_hz=args.frequency,
            channel_center_hz=args.channel_center,
        )
        print(json.dumps(result, sort_keys=True))
        found = found or bool(result["matches"])
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())
