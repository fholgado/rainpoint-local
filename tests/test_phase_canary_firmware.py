"""Compile the radio's durable phase guard; no RF or live database access."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from tests.valve_native_helpers import alter

ROOT=Path(__file__).resolve().parents[1]


class PhaseCanaryFirmwareTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler=shutil.which("c++")
        if not compiler: raise unittest.SkipTest("native compiler unavailable")
        temporary=tempfile.TemporaryDirectory(); cls.addClassCleanup(temporary.cleanup)
        cls.probe=str(Path(temporary.name)/"phase-canary")
        subprocess.run([compiler,"-std=c++17","-Wall","-Wextra","-Werror",
            "-I"+str(ROOT/"firmware/rainpoint_bridge/include"),
            str(ROOT/"firmware/rainpoint_bridge/tests/phase_canary_probe.cpp"),"-o",cls.probe],check=True)
        fixture=json.loads((ROOT/"research/fixtures/htv145_active_counter_recovery_20260906.json").read_text())
        cls.ack=fixture["command_transactions"][0]["response_frame"]
        cls.active=fixture["command_transactions"][0]["independent_state_frame"]
        cls.idle=fixture["command_transactions"][1]["independent_state_frame"]

    def run_guard(self, lines):
        result=subprocess.run([self.probe],input="\n".join(lines)+"\n",text=True,capture_output=True,check=True)
        return [tuple(map(int,line.split())) for line in result.stdout.splitlines()]

    def begin(self, phase=6, ordinal=1, now=1000, commit=1):
        return f"begin {phase} {ordinal} 12 {now} {commit} {str(ordinal)*32} a1b2c380b1c2d38f"

    def cycle(self, phase, start=1000):
        return [f"frame {start+500} {alter(self.ack,phase=phase)}",
                f"frame {start+3000} {self.active}",f"frame {start+61000} {self.idle}"]

    def test_two_adjacent_runs_and_explicit_release(self):
        result=self.run_guard([self.begin(),*self.cycle(6),self.begin(7,2,70000),
            *self.cycle(7,70000),self.begin(8,3,140000),"release",self.begin()])
        self.assertEqual(result[0],(1,2,1,6,1))
        self.assertEqual(result[3],(1,3,1,6,1))
        self.assertEqual(result[7],(1,4,2,7,1))
        self.assertEqual(result[8][0],0)
        self.assertEqual(result[9],(1,6,2,7,0))
        self.assertEqual(result[10][0],0)  # Cannot reuse the grant after release.

    def test_restart_and_failed_commit_prevent_transmission(self):
        self.assertEqual(self.run_guard([self.begin(commit=0)])[0],(0,0,0,0,0))
        result=self.run_guard([self.begin(),"restart",self.begin(),self.begin(7,2),"release"])
        self.assertEqual(result[1][1],5)
        self.assertEqual([r[0] for r in result[2:]],[0,0,0])

    def test_missing_reply_negative_reply_and_wrong_phase(self):
        negative=alter(self.ack,phase=6,data=bytes.fromhex("06219f00000000813c00ad3c00"))
        result=self.run_guard([self.begin(),f"frame 2000 {alter(self.ack,phase=7)}",f"frame 3000 {negative}",self.begin(7,2)])
        self.assertEqual(result[1][0],0)
        self.assertEqual(result[2][1],5)
        self.assertEqual(result[3][0],0)
        self.assertEqual(self.run_guard([self.begin(),"tick 17000"])[-1][1],5)

    def test_phase_jump_early_idle_and_unapproved_boundary_rejected(self):
        result=self.run_guard([self.begin(),f"frame 1200 {self.idle}",*self.cycle(6),self.begin(8,2,70000)])
        self.assertEqual(result[1][0],0)
        self.assertEqual(result[-1][0],0)
        for phase in (0,62,63,64):
            self.assertEqual(self.run_guard([self.begin(phase)])[0][0],0)
