"""Compile the radio's durable phase guard; no RF or live database access."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from tests.valve_native_helpers import alter, decode

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

    def test_dry_ports_require_matching_active_idle_and_cannot_switch_mid_trial(self):
        for port in (2,3,4):
            with self.subTest(port=port):
                def routed(frame):
                    data=bytearray(decode(frame).data);data[2]=port
                    return alter(frame,data=data)
                lines=[self.begin()+f" {port}",
                    f"frame 1500 {alter(self.ack,phase=6)}",
                    f"frame 4000 {self.active}", # Wrong outlet cannot advance.
                    f"frame 5000 {routed(self.active)}",
                    f"frame 62000 {self.idle}",
                    f"frame 63000 {routed(self.idle)}",
                    self.begin(7,2,70000)+" 1",
                    self.begin(7,2,70000)+f" {port}"]
                rows=self.run_guard(lines)
                self.assertEqual(rows[2][0],0)
                self.assertEqual(rows[4][0],0)
                self.assertEqual(rows[5][1],3)
                self.assertEqual(rows[6][0],0)
                self.assertEqual(rows[7][0],1)
        for port in (0,5,255):
            self.assertEqual(self.run_guard([self.begin()+f" {port}"])[0][0],0)

    def test_legacy_record_padding_migrates_to_port_one_and_new_bad_port_locks(self):
        rows=self.run_guard([self.begin(),*self.cycle(6),self.begin(7,2,70000),
            *self.cycle(7,70000),"release","legacy_restart"])
        self.assertEqual(rows[-1],(1,6,2,7,0))
        rows=self.run_guard([self.begin()+" 2","restart"])
        self.assertEqual(rows[-1][1],5) # Active restored record remains locked.
        rows=self.run_guard([self.begin(),"corrupt_port"])
        self.assertEqual(rows[-1][1],5)

    def test_captured_four_zone_outlet_shapes_with_synthetic_ack_and_timing(self):
        matrix=json.loads((ROOT/"research/fixtures/htv405_stock_cloud_control_matrix_20260824.json").read_text())
        for trial in matrix["trials"]:
            port=trial["zone"];active=trial["active_report_frame"];idle=trial["idle_report_frame"]
            shape=decode(active);route=b''.join(shape.route).hex()
            raw=bytearray.fromhex(self.ack);raw[5:13]=bytes.fromhex(route)
            ack=alter(raw.hex(),phase=6)
            # Recorded idle follows an explicit close. Retiming it here checks
            # parsing only; this is not evidence of a live automatic stop.
            begin=f"begin 6 1 {shape.data[0]} 1000 1 {'1'*32} {route} {port}"
            with self.subTest(port=port):
                rows=self.run_guard([begin,f"frame 1500 {ack}",f"frame 4000 {active}",f"frame 62000 {idle}"])
                self.assertEqual(rows[-1],(1,3,1,6,1))

    def test_actual_generated_four_zone_port2_exchange(self):
        capture=json.loads((ROOT/'research/fixtures/htv405_local_port2_baseline_20261001.json').read_text())
        rows=self.run_guard([f"begin 1 1 4 1000 1 {'1'*32} b1c2d38fa1b2c380 2 1",
            *[f"frame {1000+e['elapsed_ms']} {e['frame']}" for e in capture['events']]])
        self.assertEqual(rows[1][0],1,'actual local Zone 2 positive ACK must be recognized')
        self.assertEqual(rows[-1],(1,3,1,1,1),'actual active/automatic-idle must finish the run')

    def test_local_four_zone_requires_selected_outlet_and_model(self):
        capture=json.loads((ROOT/'research/fixtures/htv405_local_port2_baseline_20261001.json').read_text())
        ack,active,idle=[e['frame'] for e in capture['events']]
        begin=f"begin 1 1 4 1000 1 {'1'*32} b1c2d38fa1b2c380 2"
        self.assertEqual(self.run_guard([begin,f'frame 1800 {ack}'])[1][0],0)
        wrong_ack=bytearray(decode(ack).data);wrong_ack[1]=0x61
        wrong_active=bytearray(decode(active).data);wrong_active[3]=0x61
        rows=self.run_guard([begin+' 1',f'frame 1700 {alter(ack,data=wrong_ack)}',
            f'frame 1800 {ack}',f'frame 2500 {alter(active,data=wrong_active)}',
            f'frame 63000 {idle}',f'frame 64000 {active}',f'frame 65000 {idle}',
            f"begin 2 2 4 70000 1 {'2'*32} b1c2d38fa1b2c380 2 0"])
        self.assertEqual(rows[1][0],0)
        self.assertEqual(rows[3][0],0)
        self.assertEqual(rows[4][0],0) # Global idle needs a matching active first.
        self.assertEqual(rows[6][1],3)
        self.assertEqual(rows[7][0],0) # Model cannot change mid-authorization.

    def test_port_record_migration_ignores_old_model_padding_and_new_bad_model_locks(self):
        rows=self.run_guard([self.begin(),*self.cycle(6),self.begin(7,2,70000),
            *self.cycle(7,70000),'release','port_restart'])
        self.assertEqual(rows[-1],(1,6,2,7,0))
        rows=self.run_guard([self.begin(),'corrupt_model'])
        self.assertEqual(rows[-1][1],5)
