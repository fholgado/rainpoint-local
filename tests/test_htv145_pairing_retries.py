"""Run the actual native pairing session, including frozen captured replies."""
from pathlib import Path
import json
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class Htv145PairingRetriesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        cls.executable = str(Path(directory.name) / "htv145-pairing")
        compiled = subprocess.run([
            "c++", "-std=c++17", "-I" + str(ROOT / "firmware/rainpoint_bridge/include"),
            str(ROOT / "firmware/rainpoint_bridge/tests/htv145_counter2_protocol_test.cpp"),
            "-o", cls.executable,
        ], capture_output=True, text=True, timeout=60)
        if compiled.returncode:
            raise AssertionError(compiled.stderr)

    def test_native_frozen_prefix_and_bounded_retries(self):
        result = subprocess.run(
            [self.executable], capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def _replay_recorded_requests(self, filename):
        fixture = json.loads((ROOT / "research/fixtures" / filename).read_text())
        self.assertFalse(fixture["verdict"]["terminal_request_observed"])
        self.assertFalse(fixture["verdict"]["enrollment_complete"])
        requests = fixture["requests"]
        self.assertEqual(7, len(requests))
        origin = requests[0]["end_seconds"] - 1
        rows = []
        # Replay measured receive-end offsets, not waveform simulation. The
        # native driver supplies a clearly synthetic assignment prerequisite;
        # no absent terminal packet is invented. First accepted replies are
        # compared directly with the captured bytes, including their CRCs.
        for index, request in enumerate(requests):
            step = 1 if index == 0 else 3 if index == 1 else 4
            expected = fixture["replies"][(0, 2, 3)[index]]["frame"] if index < 3 else "-"
            rows.append((
                round((request["end_seconds"] - origin) * 1000),
                step, request["frame"], expected,
            ))
        configuration = fixture["configuration_response"]
        configuration_end = configuration.get("end_seconds", configuration["start_seconds"])
        rows.append((
            round((configuration_end - origin) * 1000),
            -1, configuration["frame"], "-",
        ))
        rows.sort()
        transcript = "".join(f"{when} {step} {frame} {reply}\n" for when, step, frame, reply in rows)
        result = subprocess.run(
            [self.executable, "--replay"], input=transcript,
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            "recorded_rows=8 plan_retries=4 completed_steps=5 expired=1\n",
            result.stdout,
        )

    def test_low_gain_capture_replays_without_fabricating_completion(self):
        self._replay_recorded_requests("htv145_low_gain_terminal_retry_20260905.json")

    def test_calibrated_tail_capture_replays_without_fabricating_completion(self):
        self._replay_recorded_requests("htv145_calibrated_tail_terminal_retry_20260905.json")

    def test_receive_edge_capture_replays_without_fabricating_completion(self):
        self._replay_recorded_requests("htv145_receive_edge_terminal_retry_20260905.json")
