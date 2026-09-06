#!/usr/bin/env python3
"""Compare recorded HTV145 command phases; no device access or transmission.

The six-bit interpretation is a research hypothesis. Recorded stock commands
support monotonic progression locally; alternating control and anchor rollover
are qualified, while arbitrary action ordering remains unqualified. Analysis
never authenticates a runtime counter.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'rainpointd_addon'))
from rainpointd.valve_protocol import ValveLink, decode_htv145_gateway_command, decode_htv145_command_response


def command_phase(frame: bytes, link: ValveLink) -> int:
    if decode_htv145_gateway_command(frame, link) is None:
        raise ValueError('not a valid command on this association')
    return ((frame[13] & 0x1f) << 1) | int(bool(frame[14] & 0x80))


def analyze_transactions(rows: list[dict], link: ValveLink) -> dict:
    commands = []
    for row in rows:
        command = bytes.fromhex(row['command_frame'])
        response = bytes.fromhex(row['response_frame'])
        decoded = decode_htv145_gateway_command(command, link)
        reply = decode_htv145_command_response(response, link)
        if decoded is None or reply is None or any(decoded[k] != reply[k] for k in ('sequence', 'watering', 'command_marker_inverted')):
            raise ValueError('transaction lacks a matching positive response')
        phase = command_phase(command, link)
        commands.append({'phase': phase, 'counter': command[13], 'marker': command[14],
                         'watering': decoded['watering'], 'response_marker': response[14]})
    adjacent = [right['phase'] == (left['phase'] + 1) % 64 for left, right in zip(commands, commands[1:])]
    return {'scope': 'offline phase-progression hypothesis; no counter authenticated',
            'commands': commands, 'adjacent_progression': adjacent,
            'all_adjacent_increment': bool(adjacent) and all(adjacent)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture', type=Path)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text())
    rows = fixture['command_transactions']
    first = bytes.fromhex(rows[0]['command_frame'])
    print(json.dumps(analyze_transactions(rows, ValveLink(first[5:9], first[9:13])), indent=2))


if __name__ == '__main__':
    main()
