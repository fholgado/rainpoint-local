"""Compile the real radio guard and replay captured matching ACKs offline."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rainpointd_addon"))
from rainpointd.valve_command_phase import build_command, decode_envelope
from rainpointd.valve_protocol import ValveLink
from tests.valve_native_helpers import alter


@unittest.skipUnless(shutil.which("c++"), "native C++ compiler unavailable")
class NativeRadioReceiptTests(unittest.TestCase):
    def test_durable_exact_packet_duplicate_restart_and_failed_write(self):
        single = json.loads((ROOT / "research/fixtures/htv145_active_counter_recovery_20260906.json").read_text())["command_transactions"][0]
        four = json.loads((ROOT / "research/fixtures/htv405_local_port2_baseline_20261001.json").read_text())["events"][0]["frame"]
        raw = bytes.fromhex(four)
        state = bytearray(decode_envelope(single["independent_state_frame"]).data)
        state[3] = 0
        state[10:12] = state[13:15] = bytes(2)
        single_idle = alter(single["independent_state_frame"], data=state)
        four_idle = json.loads((ROOT / "research/fixtures/htv405_local_port2_baseline_20261001.json").read_text())["events"][2]["frame"]
        request = build_command(model="HTV405FRF", link=ValveLink(raw[9:13], bytes((raw[5]&127,))+raw[6:9]),
            phase=1, action="open", port=2, duration_seconds=60, residue=0x4f03, selector=5).hex()
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / "receipt")
            compile_result = subprocess.run(["c++", "-std=c++17", "-I"+str(ROOT / "firmware/rainpoint_bridge/include"),
                str(ROOT / "firmware/rainpoint_bridge/tests/native_receipt_probe.cpp"), "-o", executable],
                capture_output=True, text=True)
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            for model, command, ack, idle in (("single", single["command_frame"], single["response_frame"], single_idle), ("four", request, four, four_idle)):
                with self.subTest(model=model):
                    result = subprocess.run([executable, model, command, ack, idle], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
