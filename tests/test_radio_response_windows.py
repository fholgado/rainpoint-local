"""Actual shared RX resolver resumes short listeners without extending them."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.test_htv213_runtime import function

ROOT = Path(__file__).resolve().parents[1]


class RadioResponseWindowTest(unittest.TestCase):
    def test_other_device_ack_restores_each_active_listener_and_respects_expiry(self):
        compiler = shutil.which('c++')
        if not compiler:
            self.skipTest('native compiler unavailable')
        source = (ROOT/'firmware/rainpoint_bridge/src/main.cpp').read_text()
        methods = '\n'.join(function(source, signature) for signature in (
            'bool rfCommandMayTransmit(', 'std::uint32_t radioResponseCenterHz(',
            'void restoreRadioResponseReceiver(', 'bool radioResponseAllowsCommand('))
        harness = '''
#include <array>
#include <cstdint>
#include <string>
using String=std::string;
unsigned now=0,controlHz=0,pairHz=0,failures=0;
unsigned millis() {return now;}
unsigned htv213ResponseCenterHz() {return controlHz;}
unsigned htv213PairingResponseCenterHz() {return pairHz;}
struct Owner {bool pending=false,listeningOnCommandCarrier=false;unsigned immediateResponseDeadlineMs=0,centerHz=0;};
std::array<Owner,2> htv145Owners{};
struct Probe {bool responseListenActive=false;unsigned responseListenUntilMs=0;} valveControlProbe;
unsigned valveProbeCenterHz() {return 433801500;}
struct Radio {
    unsigned center=433140000;
    bool succeeds=true;
    bool setReceiveFrequency(unsigned hz) {if(!succeeds)return false;center=hz;return true;}
} primaryRadio;
void reportNetworkCommandError(const char*,const char*) {++failures;}
ACTUAL_METHODS
int main() {
    // A different device's serialized ACK has restored the normal RX base.
    controlHz=434287000;
    for(const char* command:{"valve_control_open","htv145_control_open","htv213_control_open",
            "htv213_enrollment_start","firmware_update_start"})
        if(radioResponseAllowsCommand(command)) return 8;
    if(!radioResponseAllowsCommand("routine_ack_authorize")) return 9;
    restoreRadioResponseReceiver();if(primaryRadio.center!=434287000)return 1;
    controlHz=0;pairHz=434397000;primaryRadio.center=433140000;
    restoreRadioResponseReceiver();if(primaryRadio.center!=434397000)return 2;
    pairHz=0;htv145Owners[1]={true,true,100,433691500};now=50;primaryRadio.center=433140000;
    restoreRadioResponseReceiver();if(primaryRadio.center!=433691500)return 3;
    now=100;primaryRadio.center=433140000;
    restoreRadioResponseReceiver();if(primaryRadio.center!=433140000 || radioResponseCenterHz())return 4;
    valveControlProbe={true,200};now=150;
    restoreRadioResponseReceiver();if(primaryRadio.center!=433801500)return 5;
    now=200;primaryRadio.center=433140000;
    restoreRadioResponseReceiver();if(primaryRadio.center!=433140000 || radioResponseCenterHz())return 6;
    if(!radioResponseAllowsCommand("htv213_control_open")) return 10;
    controlHz=434287000;primaryRadio.succeeds=false;
    restoreRadioResponseReceiver();if(failures!=1)return 7;
}
'''.replace('ACTUAL_METHODS', methods)
        with tempfile.TemporaryDirectory() as directory:
            executable = str(Path(directory)/'windows')
            built = subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror',
                '-x','c++','-','-o',executable], input=harness,text=True,capture_output=True)
            self.assertEqual(built.returncode,0,built.stderr)
            result = subprocess.run([executable],text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
