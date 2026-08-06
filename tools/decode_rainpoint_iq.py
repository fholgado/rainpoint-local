#!/usr/bin/env python3
"""Decode and normalize RainPoint FSK packets saved by rtl_433."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "rainpointd_addon"))

from rainpointd.rf import FLEX_DECODER, normalize_row  # noqa: E402


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
