#!/usr/bin/env python3
"""Decode and normalize RainPoint FSK packets saved by rtl_433."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable


SYNC = bytes.fromhex("79f4882f28")
FRAME_BYTES = 38
FLEX_DECODER = (
    "n=RainPoint,m=FSK_PCM,s=48,l=48,r=49152,"
    "bits>=620,match={40}79f4882f28"
)


def _row_bits(row: dict[str, Any]) -> str:
    """Return exactly the valid bits from an rtl_433 bit row."""
    bit_count = int(row["len"])
    bits = "".join(f"{int(nibble, 16):04b}" for nibble in row["data"])
    if len(bits) < bit_count:
        raise ValueError("rtl_433 row contains fewer bits than advertised")
    return bits[:bit_count]


def _soil_moisture(frame: bytes) -> int | None:
    """Decode the field position seen in a correlated HCS026FRF report."""
    # HCS026FRF marker observed immediately before its three-nibble moisture
    # field. More captures are needed before treating this as model-agnostic.
    if len(frame) != FRAME_BYTES or frame[20] & 0x7F != 0x44:
        return None
    percent = frame[21] * 2 + (1 if frame[22] & 0x80 else 0)
    return percent if 0 <= percent <= 100 else None


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Locate sync and normalize either observed preamble length."""
    bits = _row_bits(row)
    sync_bits = "".join(f"{byte:08b}" for byte in SYNC)
    sync_offset = bits.find(sync_bits)
    inverted = False

    if sync_offset < 0:
        inverted_bits = bits.translate(str.maketrans("01", "10"))
        sync_offset = inverted_bits.find(sync_bits)
        if sync_offset < 0:
            raise ValueError("RainPoint sync word not found")
        bits = inverted_bits
        inverted = True

    framed_bits = bits[sync_offset:]
    full_bytes = bytes(
        int(framed_bits[index : index + 8], 2)
        for index in range(0, len(framed_bits) - 7, 8)
    )
    if len(full_bytes) < FRAME_BYTES:
        raise ValueError(
            f"truncated RainPoint frame: {len(full_bytes)} of {FRAME_BYTES} bytes"
        )

    frame = full_bytes[:FRAME_BYTES]
    result = {
        "bit_count": len(bits),
        "preamble_bits": sync_offset,
        "inverted": inverted,
        "frame_bits": len(framed_bits),
        "trailing_bits": len(framed_bits) - FRAME_BYTES * 8,
        "frame_hex": frame.hex(),
        "sync": frame[:5].hex(),
        # Direction is not assigned until endpoint roles are independently proven.
        "endpoint_a": frame[5:9].hex(),
        "endpoint_b": frame[9:13].hex(),
        "message_type": frame[13],
        "message_body": frame[13:-2].hex(),
        "trailer": frame[-2:].hex(),
    }
    moisture = _soil_moisture(frame)
    if moisture is not None:
        result["soil_moisture_percent"] = moisture
    return result


def decode_iq_file(
    path: Path,
    *,
    sample_rate: int = 1_024_000,
    frequency: int = 433_920_000,
) -> Iterable[dict[str, Any]]:
    """Run the proven rtl_433 flex decoder and yield normalized frames."""
    command = [
        "rtl_433",
        "-r",
        str(path),
        "-s",
        str(sample_rate),
        "-f",
        str(frequency),
        "-R",
        "0",
        "-X",
        FLEX_DECODER,
        "-M",
        "bits",
        "-F",
        "json",
    ]
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    for line in completed.stdout.splitlines():
        if not line.startswith("{"):
            continue
        event = json.loads(line)
        for row in event.get("rows", []):
            try:
                decoded = normalize_row(row)
            except ValueError:
                continue
            yield {
                "path": str(path),
                "capture_time": event.get("time"),
                **decoded,
            }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize RainPoint frames from rtl_433 CU8 captures"
    )
    parser.add_argument("captures", nargs="+", type=Path)
    parser.add_argument("--sample-rate", type=int, default=1_024_000)
    parser.add_argument("--frequency", type=int, default=433_920_000)
    args = parser.parse_args()

    found = 0
    for path in args.captures:
        for decoded in decode_iq_file(
            path,
            sample_rate=args.sample_rate,
            frequency=args.frequency,
        ):
            print(json.dumps(decoded, sort_keys=True))
            found += 1
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())
