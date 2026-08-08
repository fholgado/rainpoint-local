#!/usr/bin/env python3
"""Generate a receive-tool-compatible RainPoint command waveform offline.

The output is unsigned 8-bit interleaved complex IQ (CU8). This tool has no
radio, serial, socket, or Home Assistant code path: it can only write a file.
It exists to validate symbol timing, tone placement, wake-prefix handling, and
future CC1101 modulation against the independent RTL-SDR toolchain.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable


SYNC = bytes.fromhex("79f4882f28")
FRAME_BYTES = 38
DEFAULT_SAMPLE_RATE = 2_000_000
DEFAULT_CAPTURE_CENTER = 433_700_000
DEFAULT_CHANNEL_CENTER = 434_240_000
DEFAULT_SYMBOL_RATE = 20_000
DEFAULT_DEVIATION = 40_000
DEFAULT_WAKE_SYMBOLS = 1_200


def frame_bits(frame: bytes) -> list[int]:
    """Return a normalized RainPoint frame MSB first."""
    if len(frame) != FRAME_BYTES:
        raise ValueError(f"frame must be exactly {FRAME_BYTES} bytes")
    if not frame.startswith(SYNC):
        raise ValueError(f"frame must begin with sync {SYNC.hex()}")
    return [
        (byte >> shift) & 1
        for byte in frame
        for shift in range(7, -1, -1)
    ]


def command_symbols(
    frame: bytes,
    *,
    wake_symbols: int = DEFAULT_WAKE_SYMBOLS,
    wake_first_bit: int = 1,
) -> list[int]:
    """Build the measured alternating command wake prefix plus one frame."""
    if wake_symbols < 0:
        raise ValueError("wake_symbols cannot be negative")
    if wake_first_bit not in (0, 1):
        raise ValueError("wake_first_bit must be 0 or 1")
    wake = [wake_first_bit ^ (index & 1) for index in range(wake_symbols)]
    return wake + frame_bits(frame)


def generate_cu8(
    symbols: Iterable[int],
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    capture_center_hz: int = DEFAULT_CAPTURE_CENTER,
    channel_center_hz: int = DEFAULT_CHANNEL_CENTER,
    symbol_rate: int = DEFAULT_SYMBOL_RATE,
    deviation_hz: int = DEFAULT_DEVIATION,
    leading_silence_ms: float = 5.0,
    trailing_silence_ms: float = 5.0,
    amplitude: float = 80.0,
) -> bytes:
    """Modulate binary symbols as continuous-phase 2-FSK CU8 samples."""
    if sample_rate % symbol_rate:
        raise ValueError("sample_rate must be an integer multiple of symbol_rate")
    if not 0 < amplitude <= 127:
        raise ValueError("amplitude must be in the range (0, 127]")
    samples_per_symbol = sample_rate // symbol_rate
    leading = round(sample_rate * leading_silence_ms / 1_000)
    trailing = round(sample_rate * trailing_silence_ms / 1_000)
    data = bytearray((128, 128) * leading)
    phase = 0.0
    for symbol in symbols:
        if symbol not in (0, 1):
            raise ValueError("symbols must contain only 0 and 1")
        rf_frequency = channel_center_hz + (deviation_hz if symbol else -deviation_hz)
        step = 2 * math.pi * (rf_frequency - capture_center_hz) / sample_rate
        for _ in range(samples_per_symbol):
            phase = (phase + step) % (2 * math.pi)
            data.extend(
                (
                    round(127.5 + amplitude * math.cos(phase)),
                    round(127.5 + amplitude * math.sin(phase)),
                )
            )
    data.extend((128, 128) * trailing)
    return bytes(data)


def generate_command(
    frame: bytes,
    **settings: Any,
) -> tuple[bytes, dict[str, Any]]:
    """Generate one offline command waveform and its reproducibility metadata."""
    wake_symbols = int(settings.pop("wake_symbols", DEFAULT_WAKE_SYMBOLS))
    wake_first_bit = int(settings.pop("wake_first_bit", 1))
    symbols = command_symbols(
        frame,
        wake_symbols=wake_symbols,
        wake_first_bit=wake_first_bit,
    )
    data = generate_cu8(symbols, **settings)
    sample_rate = int(settings.get("sample_rate", DEFAULT_SAMPLE_RATE))
    symbol_rate = int(settings.get("symbol_rate", DEFAULT_SYMBOL_RATE))
    leading_ms = float(settings.get("leading_silence_ms", 5.0))
    trailing_ms = float(settings.get("trailing_silence_ms", 5.0))
    metadata = {
        "format": "CU8",
        "frame_hex": frame.hex(),
        "frame_bytes": len(frame),
        "frame_symbols": len(frame) * 8,
        "wake_symbols": wake_symbols,
        "wake_first_bit": wake_first_bit,
        "total_symbols": len(symbols),
        "symbol_rate_sps": symbol_rate,
        "sample_rate_sps": sample_rate,
        "samples_per_symbol": sample_rate // symbol_rate,
        "capture_center_hz": int(
            settings.get("capture_center_hz", DEFAULT_CAPTURE_CENTER)
        ),
        "channel_center_hz": int(
            settings.get("channel_center_hz", DEFAULT_CHANNEL_CENTER)
        ),
        "deviation_hz": int(settings.get("deviation_hz", DEFAULT_DEVIATION)),
        "wake_duration_ms": wake_symbols * 1_000 / symbol_rate,
        "frame_duration_ms": len(frame) * 8 * 1_000 / symbol_rate,
        "leading_silence_ms": leading_ms,
        "trailing_silence_ms": trailing_ms,
        "waveform_duration_ms": len(data) / 2 * 1_000 / sample_rate,
        "sha256": hashlib.sha256(data).hexdigest(),
        "safety": "offline file only; no transmit path",
    }
    return data, metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--frame", required=True, help="38-byte normalized hex frame")
    parser.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE)
    parser.add_argument("--capture-center", type=int, default=DEFAULT_CAPTURE_CENTER)
    parser.add_argument("--channel-center", type=int, default=DEFAULT_CHANNEL_CENTER)
    parser.add_argument("--symbol-rate", type=int, default=DEFAULT_SYMBOL_RATE)
    parser.add_argument("--deviation", type=int, default=DEFAULT_DEVIATION)
    parser.add_argument("--wake-symbols", type=int, default=DEFAULT_WAKE_SYMBOLS)
    parser.add_argument("--wake-first-bit", type=int, choices=(0, 1), default=1)
    parser.add_argument("--silence-ms", type=float, default=5.0)
    args = parser.parse_args()

    try:
        frame = bytes.fromhex(args.frame)
        data, metadata = generate_command(
            frame,
            sample_rate=args.sample_rate,
            capture_center_hz=args.capture_center,
            channel_center_hz=args.channel_center,
            symbol_rate=args.symbol_rate,
            deviation_hz=args.deviation,
            wake_symbols=args.wake_symbols,
            wake_first_bit=args.wake_first_bit,
            leading_silence_ms=args.silence_ms,
            trailing_silence_ms=args.silence_ms,
        )
    except ValueError as error:
        parser.error(str(error))
    args.output.write_bytes(data)
    metadata["path"] = str(args.output)
    print(json.dumps(metadata, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
