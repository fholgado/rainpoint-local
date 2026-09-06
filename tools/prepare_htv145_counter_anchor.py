#!/usr/bin/env python3
"""Prepare explicit dry-counter experiment packets; never transmit or seed counters."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'rainpointd_addon'))
from rainpointd.htv145_control import Htv145ControlProfile
from rainpointd.valve_protocol import (
    build_close_frame, build_open_frame, decode_htv145_command_response,
    next_htv145_command_sequence,
)


def prepare(profile: Htv145ControlProfile, readiness: dict) -> dict:
    """Freeze baseline evidence and a deliberately different zero-counter probe."""
    state = readiness['state']
    if not readiness.get('ready') or not readiness.get('counter_synchronized'):
        raise ValueError('fresh idle, known counter and available owner are required')
    for key in ('node_id', 'controller_endpoint', 'valve_endpoint'):
        if state.get(key) != getattr(profile, key):
            raise ValueError('readiness belongs to a different association')
    baseline = readiness['next_sequence']
    if type(baseline) is not int or baseline not in range(0x80, 0xa0):
        raise ValueError('invalid baseline counter')
    if not profile.command_marker_inverted or profile.close_trailer_residual != 0x4f03:
        raise ValueError('experiment requires the evidenced selector-6 profile')
    probe = 0x80 if baseline != 0x80 else 0x9f
    after_open = next_htv145_command_sequence(probe, watering=True)
    def close(counter):
        return build_close_frame(profile.link, counter, profile.close_trailer_residual,
                                 command_marker_inverted=True).hex()
    return {
        'experiment': 'htv145-idle-counter-anchor', 'preparation_only': True,
        'baseline_counter': baseline, 'probe_counter': probe,
        'baseline_idle_at': state['confirmed_at'],
        'maximum_open_seconds': 60, 'maximum_logical_opens': 1,
        'minimum_command_interval_seconds': 15, 'report_wait_seconds': 1800,
        'steps': [
            {'id': 'baseline_close', 'counter': baseline, 'frame': close(baseline),
             'gate': 'fresh idle report; matching immediate idle reply required'},
            {'id': 'different_counter_close', 'counter': probe, 'frame': close(probe),
             'gate': 'baseline passed; next idle report; invalidate live counter certainty before TX'},
            {'id': 'verify_open', 'counter': probe,
             'frame': build_open_frame(profile.link, probe, 60, profile.trailer_residual,
                                       command_marker_inverted=True).hex(),
             'gate': 'positive immediate idle reply at probe counter; no silence-based progression'},
            {'id': 'early_close', 'counter': after_open, 'frame': close(after_open),
             'gate': 'matching open acceptance; at least 15 seconds after open; independent idle required'},
        ],
        'stop_on': ['baseline failure', 'negative response', 'unanswered probe',
                    'unexpected watering', 'owner reconnect', 'capture loss', 'foreign controller command'],
        'runtime_requirement': 'isolated probe reservation and report-triggered firmware path; not implemented',
    }


def anchor_reply_matches(profile: Htv145ControlProfile, counter: int, frame: bytes,
                         *, response_age_seconds: float) -> bool:
    """An idle report or radio transmit log cannot establish the probe counter."""
    reply = decode_htv145_command_response(frame, profile.link)
    return bool(reply is not None and 0 <= response_age_seconds <= 3
                and reply['sequence'] == counter and reply['watering'] is False
                and reply['command_marker_inverted'] == profile.command_marker_inverted)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--readiness', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text())
    result = prepare(Htv145ControlProfile(**profile.get('profile', profile)),
                     json.loads(args.readiness.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(f'Prepared {args.output}; no RF transmitted')


if __name__ == '__main__':
    main()
