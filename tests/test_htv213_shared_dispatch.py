"""The actual radio dispatch must not swallow another device's report."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from research.pairing_native_transcripts import decode
from tests.test_valve_configuration import alter

ROOT = Path(__file__).resolve().parents[1]


class SharedDispatchTest(unittest.TestCase):
    def test_owned_two_zone_report_and_unrelated_report_take_different_paths(self):
        compiler = shutil.which("c++")
        if not compiler:
            self.skipTest("native compiler unavailable")
        main = (ROOT / "firmware/rainpoint_bridge/src/main.cpp").read_text()
        # Compile the actual interception branch of pollRadio, with the rest
        # represented by a downstream callback. The routing predicate uses
        # the same protocol implementation as the firmware.
        prefix = main.split("void pollRadio(", 1)[1].split("    bool htv405PairingReplyRestoredReceive", 1)[0]
        prefix = prefix.rsplit("#endif", 1)[1]
        fixture = json.loads((ROOT / "research/fixtures/htv213_stock_pairing_controls_20260928.json").read_text())
        own = next(e["frame"] for e in fixture['trials'][0]['events']
                   if e['direction'] == 'device' and decode(e['frame']).command == 2)
        foreign = bytearray.fromhex(own); foreign[9:13] = bytes.fromhex('9155668f')
        foreign = alter(foreign.hex())
        harness = '''
#include <string>
#include "rainpoint_htv213_control.h"
using Frame=rainpoint::htv213::Frame;
struct Radio { } primaryRadio;
struct Packet {};
rainpoint::htv213::Profile profile;
bool htv213OwnerEnabled=true;
unsigned ownCalls=0,pairCalls=0,downstream=0;
bool htv213ControlActive() {return false;}
bool htv213Armed() {return false;}
bool htv213OwnsFrame(const Frame& f) {return rainpoint::htv213Control::frameForProfile(profile,f);}
bool htv213PairingOwnsFrame(const Frame&) {return false;}
void processHtv213Control(const Frame&,const Packet&) {++ownCalls;}
bool dispatchHtv213Frame(const Frame& f,const Packet& p) {
    if(!htv213OwnsFrame(f))return false;
    processHtv213Control(f,p);return true;
}
void processHtv213(const Frame&,const Packet&) {++pairCalls;}
void printPacket(const char*,const Frame&,const Packet&,Radio&) {}
void restoreRadioResponseReceiver() {}
void dispatch(const Frame& frame) {
    auto& radio=primaryRadio; const char* name="primary"; Packet packet;
ACTUAL_BRANCH
    ++downstream;
}
Frame frame(const char* text) {
    Frame f{};const std::string value(text);
    for(unsigned i=0;i<f.size();++i) f[i]=std::stoul(value.substr(i*2,2),nullptr,16);
    return f;
}
int main() {
    profile.factory={{0x11,0x55,0x66,0x77}};
    profile.controller={{0xa2,0x44,0x66,0x88}};profile.companion={{0x22,0x44,0x66,0x88}};
    profile.address=2;profile.selector=11;profile.notificationPhase=2;profile.timingRaw=480;
    profile.initialHz=434397000;profile.routineHz=434287000;
    profile.replyDelayUs=49000;profile.notificationDelayMs=1000;
    dispatch(frame("OWN"));
    dispatch(frame("FOREIGN"));
    return ownCalls==1 && pairCalls==0 && downstream==1 ? 0 : 1;
}
'''.replace('ACTUAL_BRANCH', prefix).replace('OWN', own).replace('FOREIGN', foreign)
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory) / 'dispatch')
            built = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                '-I'+str(ROOT/'firmware/rainpoint_bridge/include'), '-x', 'c++', '-', '-o', executable],
                input=harness, text=True, capture_output=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            result = subprocess.run([executable], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, 'Unrelated report was intercepted by the two-zone owner')
