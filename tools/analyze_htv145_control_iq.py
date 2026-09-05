#!/usr/bin/env python3
"""Check HTV145 command bytes and wake lengths in a bounded existing IQ capture.

This is receive-only analysis. A decoded request proves command intent; only
valve-originated frames are reported as responses. No RF device is contacted.
"""

from __future__ import annotations

import argparse
import binascii
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rainpointd_addon"))
from rainpointd.valve_protocol import (  # noqa: E402
    ValveLink,
    decode_htv145_command_error,
    decode_htv145_command_response,
    decode_htv145_gateway_command,
)
try:
    from .analyze_htv145_pairing_iq import _bounded_capture, _endpoint
    from .demod_rainpoint_reply_iq import demodulate_many
except ImportError:
    from analyze_htv145_pairing_iq import _bounded_capture, _endpoint
    from demod_rainpoint_reply_iq import demodulate_many


def summarize_matches(matches: list[dict], link: ValveLink) -> dict:
    """Separate validated commands/responses without inferring acceptance."""
    commands, responses, errors = [], [], []
    for match in matches:
        frame = bytes.fromhex(match["frame_hex"])
        command = decode_htv145_gateway_command(frame, link)
        response = decode_htv145_command_response(frame, link)
        error = decode_htv145_command_error(frame, link)
        if command is None and response is None and error is None:
            continue
        item = {
            "frame": frame.hex(),
            "decoded": command or response or error,
            "trailer_residue": f"{binascii.crc_hqx(frame[:-2], 0) ^ int.from_bytes(frame[-2:], 'big'):04x}",
            "phase_count": match["phase_count"],
            "wake_symbol_histogram": match["alternating_wake_symbol_histogram"],
            "observed_wake_symbols": match["alternating_wake_symbols"],
        }
        target = commands if command is not None else responses if response is not None else errors
        target.append(item)
    return {"commands": commands, "responses": responses, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--controller-endpoint", type=_endpoint, required=True)
    parser.add_argument("--valve-endpoint", type=_endpoint, required=True)
    parser.add_argument("--decision-center", type=int, required=True)
    parser.add_argument("--start-seconds", type=float, default=0)
    parser.add_argument("--duration-seconds", type=float, required=True)
    parser.add_argument("--sample-rate", type=int, default=2_000_000)
    parser.add_argument("--capture-center", type=int, default=433_700_000)
    args = parser.parse_args()
    link = ValveLink(args.controller_endpoint, args.valve_endpoint)
    with _bounded_capture(args.capture, sample_rate=args.sample_rate,
                          start_seconds=args.start_seconds,
                          duration_seconds=args.duration_seconds) as (path, _origin):
        result = demodulate_many(path, channel_centers_hz=[args.decision_center],
                                sample_rate=args.sample_rate,
                                capture_center_hz=args.capture_center)[args.decision_center]
    summary = summarize_matches(result["matches"], link)
    summary.update({"capture": str(args.capture), "start_seconds": args.start_seconds,
                    "duration_seconds": args.duration_seconds,
                    "decision_center_hz": args.decision_center,
                    "scope": "decoded RF evidence; request reception is not valve acceptance"})
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["commands"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
