"""Execute the actual dry-control runtime with a register-level radio fake."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.test_htv213_runtime import function

ROOT = Path(__file__).resolve().parents[1]


class Htv213ControlRuntimeTest(unittest.TestCase):
    def test_receive_handoff_report_ack_and_failure_paths_never_retry_open(self):
        compiler = shutil.which("c++")
        if not compiler:
            self.skipTest("native compiler unavailable")
        source = (ROOT / "firmware/rainpoint_bridge/src/htv213_control_runtime.inc").read_text()
        driver = (ROOT / "firmware/rainpoint_bridge/src/cc1101.cpp").read_text()
        # Reuse the register fake, including the ACTUAL driver's tuning methods.
        support = (ROOT / "firmware/rainpoint_bridge/tests/htv213_runtime_probe.cpp").read_text()
        support = support.split("rainpoint::Cc1101 primaryRadio;", 1)[0]
        support = support.replace('"rainpoint_htv213_pairing.h"', '"rainpoint_htv213_control.h"')
        support = '#include "rainpoint_htv213_owner.h"\n' + support
        support = support.replace("unsigned, unsigned, unsigned = 0) {",
            "unsigned, unsigned, unsigned = 0, unsigned = 0, int tail = -1) {")
        support = support.replace("commands.push_back(htv213::native(frame)[10]);",
            "if (tail != htv213Control::nativeTailSymbol(frame)) std::exit(20);\n"
            "        commands.push_back(htv213::native(frame)[10]);")
        support = support.replace("// ACTUAL_DRIVER_METHODS", "\n".join(
            function(driver, f"bool Cc1101::{name}(") for name in
            ("setChannel", "setReceiveFrequency", "restoreReceiveChannel")))
        support += '''
rainpoint::Cc1101 primaryRadio;
rainpoint::htv213Control::Trial htv213ControlTrial;
rainpoint::htv213::Profile htv213ControlProfile{};
rainpoint::PairingLocalDateTime htv213ControlClock{2026,9,30,10,0,0};
unsigned htv213ControlClockAt=0;
std::int8_t htv213ControlPower=0;
bool htv213ControlListening=false, scanning=false;
unsigned htv213ControlAcks=0, reports=0;
bool htv213OwnerEnabled=false;
std::string htv213OwnerId;
void reportHtv213Owner(const rainpoint::htv213::Frame* =nullptr) {}
struct Wifi { bool allowed=true; bool authenticated() { return allowed; } } wifiTransport;
struct Maintenance { bool allowed=true; bool transmitAllowed() { return allowed; } } rfMaintenance;
void reportHtv213Control(const rainpoint::htv213::Frame* =nullptr) { ++reports; }
void restoreScanningAfterPairing() { scanning=true; }
'''
        support += "\n".join(function(source, signature) for signature in (
            "bool htv213ControlActive(", "void restoreHtv213ControlReceiver(",
            "void transmitHtv213Control(", "void processHtv213Control(", "void pollHtv213Control("))
        fixture = json.loads((ROOT / "research/fixtures/htv213_stock_pairing_controls_20260928.json").read_text())
        trial = next(t for t in fixture["trials"] if t["name"] == "zone1_auto60")
        device = [e["frame"] for e in trial["events"] if e["direction"] == "device"]
        support += '''
rainpoint::htv213::Frame frame(const char* text) {
    rainpoint::htv213::Frame out{};
    const std::string hex(text);
    for (unsigned i=0;i<out.size();++i) out[i]=std::stoul(hex.substr(i*2,2),nullptr,16);
    return out;
}
int main(int argc,char** argv) {
    const std::string mode=argc>1 ? argv[1] : "accepted";
    auto& p=htv213ControlProfile;
    p.factory={{0x11,0x55,0x66,0x77}};
    p.controller={{0xa2,0x44,0x66,0x88}}; p.companion={{0x22,0x44,0x66,0x88}};
    p.address=2; p.selector=11; p.notificationPhase=2; p.timingRaw=480;
    p.initialHz=434397000; p.routineHz=434287000;
    p.replyDelayUs=49000; p.notificationDelayMs=1000;
    rainpoint::htv213::Transmission tx{};
    if (!htv213ControlTrial.start(p,1,60,3,0,tx)) return 1;
    if (mode=="tx-failure") primaryRadio.restoreOk=false;
    transmitHtv213Control(tx);
    if (mode=="tx-failure") {
        if (htv213ControlTrial.state()!=rainpoint::htv213Control::State::Uncertain) return 2;
        primaryRadio.restoreOk=true;
    } else if (primaryRadio.baseHz!=p.routineHz) return 3;
    if (mode=="disconnect") wifiTransport.allowed=false;
    if (mode=="rf-disabled") rfMaintenance.allowed=false;
    if (mode=="timeout" || mode=="tx-failure") fakeNow=1501;
    if (mode=="restore-failure") primaryRadio.restoreOk=false;
    if (mode=="owner") { htv213OwnerEnabled=true; htv213OwnerId="test-owner"; }
    if (mode=="accepted" || mode=="owner" || mode=="restore-failure") {
        fakeNow=313;
        processHtv213Control(frame("ACK_FRAME"),rainpoint::RadioPacket{313000});
    }
    pollHtv213Control();
    if (mode=="disconnect" || mode=="rf-disabled" || mode=="restore-failure") {
        if (htv213ControlActive() || !scanning) return 4;
    } else {
        if (primaryRadio.baseHz!=rainpoint::kReportHz) return 5;
        if (mode=="accepted" || mode=="owner") {
            const char* frames[]={REPORT_FRAMES};
            for (const char* text:frames) {
                fakeNow+=1000;
                processHtv213Control(frame(text),rainpoint::RadioPacket{fakeNow*1000});
            }
            if (htv213ControlTrial.state()!=rainpoint::htv213Control::State::Complete || scanning==(mode=="owner")) return 6;
            if (primaryRadio.commands.back()!=0x84) return 7;
            if (mode=="owner") {
                const auto count=primaryRadio.commands.size();
                processHtv213Control(frame(frames[0]),rainpoint::RadioPacket{fakeNow*1000});
                if (primaryRadio.commands.size()!=count+1 || !htv213OwnerEnabled) return 12;
                wifiTransport.allowed=false; pollHtv213Control();
                if (htv213OwnerEnabled || !scanning) return 13;
            }
        } else {
            if (htv213ControlTrial.state()!=rainpoint::htv213Control::State::Uncertain) return 8;
            fakeNow=120000; pollHtv213Control();
            if (htv213ControlActive() || !scanning) return 9;
        }
    }
    unsigned opens=0;
    for (auto command:primaryRadio.commands) {
        if (command==0x21) ++opens;
        else if (command!=0x82 && command!=0x84) return 10;
    }
    return opens==1 ? 0 : 11;
}
'''.replace("ACK_FRAME", device[0]).replace("REPORT_FRAMES", ",".join(json.dumps(f) for f in device[1:]))
        with tempfile.TemporaryDirectory() as directory:
            exe = str(Path(directory) / "runtime")
            result = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                "-I"+str(ROOT / "firmware/rainpoint_bridge/include"), "-x", "c++", "-", "-o", exe],
                input=support, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for mode in ("accepted", "owner", "timeout", "disconnect", "rf-disabled", "restore-failure", "tx-failure"):
                with self.subTest(mode=mode):
                    result = subprocess.run([exe, mode], text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
