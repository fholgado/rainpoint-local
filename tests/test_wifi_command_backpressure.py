"""Reconnect configuration bursts must wait in TCP, not be discarded."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.test_htv213_runtime import function

ROOT = Path(__file__).resolve().parents[1]


class CommandBackpressureTest(unittest.TestCase):
    def test_more_than_one_queue_of_commands_is_delivered_in_order(self):
        compiler=shutil.which('c++')
        if not compiler:self.skipTest('native compiler unavailable')
        source=(ROOT/'firmware/rainpoint_bridge/src/wifi_transport.cpp').read_text()
        poll=function(source,'void WifiTransport::poll(')
        loop=poll[poll.index('    while (client_.available()'):].rsplit('}',1)[0]
        take=function(source,'bool WifiTransport::takeCommand(')
        harness='''
#include <array>
#include <string>
#include <iostream>
using String=std::string;
struct Client {
    String bytes;unsigned position=0;
    bool available() {return position<bytes.size();}
    char read() {return bytes[position++];}
};
class WifiTransport {
public:
    static constexpr unsigned kMaximumLineBytes=3072;
    Client client_;
    String inputLine_;
    unsigned networkBytesReceived_=0,pendingCommandHead_=0,pendingCommandCount_=0,errors=0;
    std::array<String,8> pendingCommands_{};
    void reportNetworkState(const char*,const char*) {++errors;}
    void clearConnection() {}
    void handleGatewayLine(const String& line) {
        if(pendingCommandCount_==pendingCommands_.size()) {++errors;return;}
        pendingCommands_[(pendingCommandHead_+pendingCommandCount_)%pendingCommands_.size()]=line;
        ++pendingCommandCount_;
    }
    void poll() {
ACTUAL_LOOP
    }
    bool takeCommand(String&);
};
ACTUAL_TAKE
int main() {
    WifiTransport transport;
    for(unsigned i=0;i<24;++i)transport.client_.bytes+="owner"+std::to_string(i)+"\\n";
    for(unsigned i=0;i<24;++i) {
        transport.poll();String command;
        if(transport.errors || !transport.takeCommand(command) || command!="owner"+std::to_string(i))return 1;
    }
    String empty;if(transport.takeCommand(empty) || transport.client_.available())return 2;
}
'''.replace('ACTUAL_LOOP',loop).replace('ACTUAL_TAKE',take)
        with tempfile.TemporaryDirectory() as directory:
            executable=str(Path(directory)/'queue')
            built=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror','-x','c++','-',
                '-o',executable],input=harness,text=True,capture_output=True)
            self.assertEqual(built.returncode,0,built.stderr)
            result=subprocess.run([executable],text=True,capture_output=True)
            self.assertEqual(result.returncode,0,'Reconnect burst was discarded instead of applying backpressure')
