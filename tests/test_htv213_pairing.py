"""Execute the isolated pairing candidate against redacted stock exchanges."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from research.pairing_native_transcripts import decode
from tests.test_valve_configuration import alter

ROOT = Path(__file__).resolve().parents[1]
# Successful stock phase-4 assignment: synthetic routes and zeroed wall clock.
# Original preserved under two-zone-stock-20260928/analysis-htv213/first-pairing.jsonl.
FACTORY = "79f4882f288000000011556677020084067f900280821f0280000000000000000000000068f7"
ASSIGNMENT = "79f4882f289155667722446688824085850105f0008000000000008000000000000000003626"
# Sep 29 explicit pairing attempt, phase 1; only factory identity is redacted.
# Private IQ: htv213-local-pairing-20260929/20260929-210852, t=58.546901s.
REPEAT_FACTORY = "79f4882f28800000001155667700808405ff900280821f03800000000000000000000000191b"


class Htv213PairingTest(unittest.TestCase):
    def test_actual_runtime_prepares_both_assignment_carriers_with_two_cache_slots(self):
        source = (ROOT / "firmware/rainpoint_bridge/src/htv213_pairing_runtime.inc").read_text()
        preparation = source.split("    if (!rainpoint::htv213::valid(p)", 1)[1].split("    htv213CommandId=id", 1)[0]
        preparation = "    if (!rainpoint::htv213::valid(p)" + preparation
        preparation = preparation.replace('reportNetworkCommandError(id,"htv213_prepare_failed"); return true;', 'return false;')
        harness = '''#include <set>
#include "rainpoint_htv213_pairing.h"
struct Radio {
    std::set<unsigned> cache;
    bool prepareTransmit() { return true; }
    bool cacheTransmitFrequency(unsigned hz) {
        if (cache.count(hz)) return true;
        if (cache.size()==2) return false;
        cache.insert(hz); return true;
    }
};
unsigned millis() { return 0; }
bool prepare(unsigned routine) {
    rainpoint::htv213::Profile p{};
    p.factory={{0x11,0x55,0x66,0x77}};
    p.controller={{0xa2,0x44,0x66,0x88}}; p.companion={{0x22,0x44,0x66,0x88}};
    p.address=2; p.selector=11; p.notificationPhase=2; p.timingRaw=480;
    p.initialHz=434391500; p.routineHz=routine;
    p.replyDelayUs=49000; p.notificationDelayMs=1000;
    Radio primaryRadio; rainpoint::htv213::Session htv213Session;
    unsigned duration=300;
''' + preparation + '''
    return primaryRadio.cache == std::set<unsigned>{434391500,434281500}
        && htv213Session.state()==rainpoint::htv213::State::Armed;
}
int main() { return prepare(434281500) && prepare(433801500) ? 0 : 1; }
'''
        exe = str(Path(self.temp.name) / "frequency-cache")
        subprocess.run([shutil.which("c++"), "-std=c++17", "-I"+str(ROOT/"firmware/rainpoint_bridge/include"),
                        "-x", "c++", "-", "-o", exe], input=harness, text=True, capture_output=True, check=True)
        subprocess.run([exe], check=True)

    def test_actual_firmware_ingress_gate_admits_only_authenticated_canary_commands(self):
        source=(ROOT/"firmware/rainpoint_bridge/src/wifi_transport.cpp").read_text()
        gate=source.split("    if (authenticated_ &&\n",1)[1].split(")) {",1)[0]
        harness='''#include <string>
#include "rainpoint_valve_control.h"
using rainpoint::isHtv405NetworkCommand;
bool allowed(bool authenticated_, const std::string& type) {
    if (authenticated_ &&
'''+gate+''')) return true;
    return false;
}
int main() {
#ifdef RAINPOINT_HTV213_PAIRING_EXPERIMENT
    constexpr bool expected=true;
#else
    constexpr bool expected=false;
#endif
#ifdef RAINPOINT_HTV213_CONTROL_EXPERIMENT
    constexpr bool controlExpected=true;
#else
    constexpr bool controlExpected=false;
#endif
    for (const auto* command : {"htv213_pairing_start", "htv213_pairing_cancel"}) {
        if (allowed(true,command)!=expected) return 1;
        if (allowed(false,command)) return 2;
    }
    if (!allowed(true,"pairing_start")) return 3;
    if (allowed(true,"unknown_command")) return 4;
    for (const auto* command : {"htv213_control_probe_open", "htv213_control_probe_close"}) {
        if (allowed(true,command)!=controlExpected) return 5;
        if (allowed(false,command)) return 6;
    }
}
'''
        path=Path(self.temp.name)/"ingress.cpp"
        path.write_text(harness)
        for experimental, control in ((False,False),(True,False),(True,True)):
            exe=str(Path(self.temp.name)/f"ingress-{experimental}-{control}")
            command=[shutil.which("c++"),"-std=c++17","-I"+str(ROOT/"firmware/rainpoint_bridge/include")]
            if experimental:command+=["-DRAINPOINT_HTV213_PAIRING_EXPERIMENT"]
            if control:command+=["-DRAINPOINT_HTV213_CONTROL_EXPERIMENT"]
            subprocess.run(command+[str(path),"-o",exe],check=True,capture_output=True,text=True)
            result=subprocess.run([exe])
            self.assertEqual(result.returncode,0,f"actual ingress gate, experimental={experimental}")

    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("c++")
        if not compiler:
            raise unittest.SkipTest("native compiler unavailable")
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.exe = str(Path(cls.temp.name) / "pairing")
        subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                        "-I"+str(ROOT/"firmware/rainpoint_bridge/include"),
                        str(ROOT/"firmware/rainpoint_bridge/tests/htv213_pairing_probe.cpp"),
                        "-o",cls.exe], check=True,capture_output=True,text=True)
        cls.events = json.loads((ROOT/"research/fixtures/htv213_stock_pairing_controls_20260928.json").read_text())["trials"][0]["events"]

    def run_ops(self, ops):
        result=subprocess.run([self.exe],input="\n".join(ops)+"\n",text=True,capture_output=True,check=True)
        return [list(map(int, parts[:9]))+[parts[9]] for parts in (row.split() for row in result.stdout.splitlines())]

    def prefix(self):
        return ["arm 0",f"frame 1 {FACTORY}","finish 2 1"]

    def enrollment(self):
        ops=self.prefix(); now=100; replies=[]
        for event in self.events:
            packet=decode(event["frame"])
            if event["direction"]=="device":
                ops += [f"frame {now} {event['frame']}"]
                if packet.command!=0xa0:
                    replies.append(len(ops)-1)
                    ops += [f"finish {now+1} 1"]
                now+=2000
            elif packet.command==0x20:
                ops += [f"notification {now}",f"finish {now+1} 1"]
                now+=2000
        return ops,replies

    def test_assignment_and_configuration_match_capture(self):
        ops,indices=self.enrollment(); rows=self.run_ops(ops)
        self.assertEqual(rows[1][-1],ASSIGNMENT)
        expected=[e["frame"] for e in self.events if e["direction"]=="gateway" and decode(e["frame"]).command!=0x20]
        for index,frame in zip(indices,expected,strict=True):
            self.assertEqual(rows[index][0],1)
            self.assertEqual(rows[index][-1],frame)
        self.assertEqual(rows[-1][1],1, "last transmitted plan reply is not completion")
        self.assertEqual(rows[-1][3:7],[3,3,3,1])
        report=self.events[0]["frame"]
        self.assertEqual(self.run_ops(ops+[f"frame 25000 {report}","finish 25001 1"])[-1][1],2)

    def test_local_pairing5_capture_preserves_both_port_configuration_and_retries(self):
        fixture = json.loads((ROOT / "research/fixtures/htv213_local_pairing_20260930.json").read_text())
        ops = ["arm 0"]
        expected = []
        reply_index = None
        for event in fixture["events"]:
            packet = decode(event["frame"])
            now = round(event["seconds"] * 1000)
            if event["direction"] == "device":
                # Runtime listens only to lower announcements/reports and the
                # routine-carrier notification response, not other sweep legs.
                if event["center_hz"] != 433140000 and packet.command != 0xa0:
                    continue
                ops.append(f"frame {now} {event['frame']}")
                reply_index = len(ops) - 1
            elif packet.command == 0x20:
                ops.append(f"notification {now}")
                expected.append((len(ops) - 1, event["frame"]))
                ops.append(f"finish {now + 1} 1")
            else:
                self.assertIsNotNone(reply_index)
                expected.append((reply_index, event["frame"]))
                ops.append(f"finish {now + 1} 1")
        rows = self.run_ops(ops)
        self.assertEqual(len(expected), 13)
        for index, captured in expected:
            self.assertEqual(rows[index][0], 1)
            actual, captured = decode(rows[index][-1]), decode(captured)
            self.assertEqual((actual.command, actual.phase, actual.data),
                             (captured.command, captured.phase, captured.data))
        self.assertEqual(rows[-1][3:8], [3, 3, 3, 1, 13])
        self.assertEqual(rows[-1][1], 1, "No post-plan report was captured in this exchange")

    def test_full_phase_echo_not_fixed_sweep_counter(self):
        for phase in range(64):
            rows=self.run_ops(["arm 0",f"frame 1 {alter(FACTORY,phase=phase)}"])
            self.assertEqual(decode(rows[-1][-1]).phase,phase)

    def test_captured_repeat_announcement_uses_unchanged_assignment_and_continuation(self):
        self.assertEqual(decode(REPEAT_FACTORY).data, bytes.fromhex("0bff200501043e07"))
        for phase in range(64):
            with self.subTest(phase=phase):
                frame = alter(REPEAT_FACTORY, phase=phase)
                rows = self.run_ops(["arm 0", f"frame 1 {frame}"])
                self.assertEqual(rows[-1][0], 1, "captured explicit-pairing request rejected")
                # Compare actual native-CRC encoding to the existing path;
                # alter() reconstructs a legacy CRC, not the native CRC tail.
                original = self.run_ops(["arm 0", f"frame 1 {alter(FACTORY, phase=phase)}"])
                self.assertEqual(rows[-1][-1], original[-1][-1])
                self.assertEqual(decode(rows[-1][-1]).phase, phase)
                self.assertEqual(decode(rows[-1][-1]).data, decode(ASSIGNMENT).data)
        ops, _ = self.enrollment()
        baseline = self.run_ops(ops)
        ops[1] = f"frame 1 {alter(REPEAT_FACTORY, phase=4)}"
        repeat = self.run_ops(ops)
        self.assertEqual(repeat[1][-1], baseline[1][-1], "assignment bytes must stay unchanged")
        self.assertEqual(repeat[2:], baseline[2:], "later stages must stay unchanged")

    def test_factory_reply_carrier_follows_request_not_assigned_selector(self):
        for assigned in (1, 11, 15):
            for frame, expected in ((FACTORY, 434351500), (REPEAT_FACTORY, 434241500)):
                with self.subTest(assigned=assigned, request=decode(frame).data[0]):
                    rows = self.run_ops([f"profile 0 434351500 433801500 {assigned}",
                                         "arm 0", f"frame 1 {frame}"])
                    self.assertEqual(rows[-1][0], 1)
                    self.assertEqual(rows[-1][8], expected)
                    self.assertEqual(decode(rows[-1][-1]).data[2], assigned)

    def test_calibrated_reference_carries_through_factory_and_routine(self):
        # Synthetic per-node correction; never a baked-in runtime default.
        initial, routine = 434391500, 434281500
        for frame, expected in ((FACTORY, initial), (REPEAT_FACTORY, initial - 110000)):
            rows = self.run_ops([f"profile 0 {initial} {routine} 11", "arm 0", f"frame 1 {frame}"])
            self.assertEqual(rows[-1][8], expected)
        ops, _ = self.enrollment()
        ops[1] = f"frame 1 {alter(REPEAT_FACTORY, phase=4)}"
        rows = self.run_ops([f"profile 0 {initial} {routine} 11"] + ops)
        self.assertEqual(rows[2][8], initial - 110000)
        for row in rows[3:]:
            if row[0] and row[-1] != "-":
                self.assertEqual(row[8], routine)

    def test_derived_factory_frequency_is_bounded_before_arming(self):
        for initial in (433000000, 433109999, 435000001):
            rows = self.run_ops([f"profile 0 {initial} 434241500 11", "arm 0"])
            self.assertEqual(rows[-1][0], 0)
        rows = self.run_ops(["profile 0 433110000 434241500 11", "arm 0",
                             f"frame 1 {REPEAT_FACTORY}"])
        self.assertEqual(rows[-1][8], 433000000)

    def test_repeat_announcement_does_not_broaden_model_routes_or_rejoin(self):
        body = decode(REPEAT_FACTORY).data
        rejected = []
        # Exact observed variants only; no invented cross-product or flag mask.
        for index in range(len(body)):
            mutation = bytearray(body)
            mutation[index] ^= 1
            rejected.append(alter(REPEAT_FACTORY, data=mutation))
        for data in ("0bff200501043e03", "0cff200501043e03",
                     "0bff200501043e05", "0cff200501043e07"):
            rejected.append(alter(REPEAT_FACTORY, data=bytes.fromhex(data)))
        for start in (5, 9):
            other = bytearray.fromhex(REPEAT_FACTORY)
            other[start + 3] ^= 1
            rejected.append(alter(other.hex()))
        rejected.extend((alter(REPEAT_FACTORY, command=0x21),
                         alter(REPEAT_FACTORY, data=body[:-1]),
                         alter(REPEAT_FACTORY, data=body + b"\x00")))
        for frame in rejected:
            with self.subTest(frame=frame):
                self.assertEqual(self.run_ops(["arm 0", f"frame 1 {frame}"])[-1][0], 0)

    def test_retained_announcement_and_other_routes_rejected(self):
        body=bytearray(decode(FACTORY).data);body[-1]=3
        other=bytearray.fromhex(FACTORY);other[12]^=1
        for frame in (alter(FACTORY,data=body),alter(other.hex()),alter(FACTORY,command=0x21)):
            self.assertEqual(self.run_ops(["arm 0",f"frame 1 {frame}"])[-1][0],0)

    def test_tx_failure_timeout_cancel_disconnect_and_no_rearm(self):
        for op,reason in (("finish 2 0",2),("tick 300000",1),("cancel 2",4),("disconnect 2",3)):
            rows=self.run_ops(["arm 0",f"frame 1 {FACTORY}",op,f"frame 300001 {FACTORY}"])
            self.assertEqual(rows[-1][1:3],[3,reason]);self.assertEqual(rows[-1][0],0)
        self.assertEqual(self.run_ops(["arm 0","arm 1"])[-1][0],0)

    def test_notification_requires_both_ports_and_is_once_only(self):
        report=self.events[0]["frame"]
        rows=self.run_ops(self.prefix()+[f"frame 100 {report}","finish 101 1","notification 5000"])
        self.assertEqual(rows[-1][0],0)
        ops,_=self.enrollment()
        self.assertEqual(self.run_ops(ops+["notification 30000"])[-1][0],0)

    def test_addressed_traffic_before_assignment_does_not_pair(self):
        rows=self.run_ops(["arm 0",f"frame 1 {self.events[0]['frame']}"])
        self.assertEqual(rows[-1][0],0);self.assertEqual(rows[-1][3],0)

    def test_notification_reply_window_is_bounded_and_ends_on_matching_ack(self):
        ops,_=self.enrollment()
        index=next(i for i,op in enumerate(ops) if op.startswith("notification"))
        now=int(ops[index+1].split()[1])
        prefix=ops[:index+2]
        self.assertEqual(self.run_ops(prefix+[f"listening {now+749}"])[-1][0],1)
        self.assertEqual(self.run_ops(prefix+[f"listening {now+750}"])[-1][0],0)
        ack=next(e["frame"] for e in self.events if decode(e["frame"]).command==0xa0)
        rows=self.run_ops(prefix+[f"frame {now+100} {ack}",f"listening {now+101}"])
        self.assertEqual(rows[-1][0],0)
        self.assertEqual(rows[-1][6],1)

    def test_wrong_notification_phase_cannot_unlock_settings(self):
        ops,_=self.enrollment()
        for i,op in enumerate(ops):
            if op.startswith("frame") and decode(op.split()[2]).command==0xa0:
                ops[i]=op.rsplit(" ",1)[0]+" "+alter(op.split()[2],phase=3)
        self.assertEqual(self.run_ops(ops)[-1][4:7],[0,0,0])
