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
        cls.arduino_probe=str(Path(temporary.name)/"phase-canary-arduino")
        for probe, flags in ((cls.probe, []),
                (cls.arduino_probe, ["-DRAINPOINT_TEST_ARDUINO_WORD_MACRO"])):
            subprocess.run([compiler,"-std=c++17","-Wall","-Wextra","-Werror",*flags,
                "-I"+str(ROOT/"firmware/rainpoint_bridge/include"),
                str(ROOT/"firmware/rainpoint_bridge/tests/phase_canary_probe.cpp"),"-o",probe],check=True)
        fixture=json.loads((ROOT/"research/fixtures/htv145_active_counter_recovery_20260906.json").read_text())
        cls.ack=fixture["command_transactions"][0]["response_frame"]
        cls.active=fixture["command_transactions"][0]["independent_state_frame"]
        cls.idle=fixture["command_transactions"][1]["independent_state_frame"]

    def run_guard(self, lines, probe=None):
        outputs=[]
        for executable in ([probe] if probe else [self.probe,self.arduino_probe]):
            result=subprocess.run([executable],input="\n".join(lines)+"\n",
                text=True,capture_output=True,check=True)
            outputs.append([tuple(map(int,line.split())) for line in result.stdout.splitlines()])
        if len(outputs)==2:
            self.assertEqual(outputs[0],outputs[1],"host and Arduino guard decisions must agree")
        return outputs[0]

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

    def test_arduino_macro_environment_accepts_same_received_exchange(self):
        # Actual ESP32 Arduino.h defines word(...) as makeWord(...). Compile
        # the guard in that environment, not just its macro-free host variant.
        lines=[self.begin(phase=2),*self.cycle(2),"tick 63000"]
        rows=self.run_guard(lines,self.arduino_probe)
        self.assertEqual(rows[1][0],1,"positive phase-2 ACK must be recognized on Arduino")
        self.assertEqual(rows[-1][1],3,"confirmed automatic stop must complete run one")

    def test_installed_phase2_capture_in_both_compilation_environments(self):
        capture=json.loads((ROOT/"research/fixtures/htv145_phase2_trial_20260930.json").read_text())
        self.assertGreaterEqual(len(capture["events"]),3)
        lines=[self.begin(phase=capture["phase"])]
        lines += [f"frame {1000+e['elapsed_ms']} {e['frame']}" for e in capture["events"]]
        lines.append("tick 71000")
        for probe in (self.probe,self.arduino_probe):
            with self.subTest(probe=Path(probe).name):
                rows=self.run_guard(lines,probe)
                self.assertEqual(rows[1][0],1)
                self.assertEqual(rows[-1][1],3)

    def test_no_watering_recovery_requires_saved_attempt_and_complete_evidence(self):
        capture=json.loads((ROOT/"research/fixtures/htv145_phase2_trial_20260930.json").read_text())
        ack,active,idle=capture["events"][:3]
        def command(commit=1,attempt="1"*32,ack_frame=None,idle_age=None):
            return (f"recover {'a'*32} {attempt} {ack['elapsed_ms']} {active['elapsed_ms']} "
                f"{idle_age or idle['elapsed_ms']} {commit} {ack_frame or ack['frame']} {active['frame']} {idle['frame']}")
        failed=[self.begin(phase=2),"tick 17000"]
        for invalid in (command(commit=0),command(attempt="2"*32),command(idle_age=54000),
                        command(ack_frame=alter(ack["frame"],phase=3))):
            rows=self.run_guard([*failed,invalid,self.begin(phase=3,ordinal=2)])
            self.assertEqual(rows[-2],(0,5,1,2,1))
            self.assertEqual(rows[-1][0],0)
        rows=self.run_guard([*failed,"restart",command(),"restart",command(),self.begin(phase=3,ordinal=2)])
        self.assertEqual(rows[3],(1,7,1,2,0))
        self.assertEqual(rows[4],(1,7,1,2,0))
        self.assertEqual(rows[5][0],0) # Runtime handles duplicate ACK without touching counters.
        self.assertEqual(rows[6][0],0)

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
