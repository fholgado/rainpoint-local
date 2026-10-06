"""Actual multi-association command dispatcher and RF packet router."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from research.pairing_native_transcripts import decode
from tests.test_htv213_runtime import function

ROOT=Path(__file__).resolve().parents[1]


class MultiRuntimeTest(unittest.TestCase):
    def test_owner_capacity_command_binding_reports_and_revocation_are_isolated(self):
        compiler=shutil.which('c++')
        if not compiler:self.skipTest('native compiler unavailable')
        runtime=(ROOT/'firmware/rainpoint_bridge/src/htv213_control_runtime.inc').read_text()
        runtime=runtime.replace(function(runtime,'void reportHtv213Owner('),
            'void reportHtv213Owner(const rainpoint::htv213::Frame* =nullptr) { ownerStatuses.emplace_back(htv213OwnerId,htv213OwnerEnabled); }')
        runtime=runtime.replace(function(runtime,'void reportHtv213Control('),
            'void reportHtv213Control(const rainpoint::htv213::Frame* =nullptr) {}')
        driver=(ROOT/'firmware/rainpoint_bridge/src/cc1101.cpp').read_text()
        support=(ROOT/'firmware/rainpoint_bridge/tests/htv213_runtime_probe.cpp').read_text().split('rainpoint::Cc1101 primaryRadio;',1)[0]
        support=support.replace('"rainpoint_htv213_pairing.h"','"rainpoint_htv213_owner.h"')
        support=support.replace('std::vector<unsigned> commands;',
            'std::vector<unsigned> commands; std::vector<htv213::Frame> transmissions;')
        support=support.replace('unsigned, unsigned, unsigned = 0) {',
            'unsigned, unsigned, unsigned = 0, unsigned = 0, int tail=-1) {')
        support=support.replace('commands.push_back(htv213::native(frame)[10]);',
            'if(tail!=htv213Control::nativeTailSymbol(frame))std::exit(90);\n'
            '        transmissions.push_back(frame);commands.push_back(htv213::native(frame)[10]);')
        support=support.replace('bool enterIdle() {',
            'bool prepareTransmit() {return true;}\n    bool cacheTransmitFrequency(unsigned) {return true;}\n    bool enterIdle() {')
        support=support.replace('// ACTUAL_DRIVER_METHODS','\n'.join(function(driver,f'bool Cc1101::{name}(')
            for name in ('setChannel','setReceiveFrequency','restoreReceiveChannel')))
        support+='''
#include <cstdio>
using String=std::string;
rainpoint::Cc1101 primaryRadio;
bool radiosHealthy=true,scanChannels=false;
String lastError;
std::vector<std::pair<String,bool>> ownerStatuses;
struct Wifi {bool authenticated(){return true;}} wifiTransport;
struct Maintenance {bool transmitAllowed(){return true;}} rfMaintenance;
bool htv213Armed(){return false;}
bool htv145Pending(){return false;}
rainpoint::PairingSessionState currentPairingState(){return rainpoint::PairingSessionState::Disarmed;}
struct Probe {bool commandPendingConfirmation=false,openQueued=false,closeQueued=false;} valveControlProbe;
void restoreScanningAfterPairing(){scanChannels=true;}
unsigned number(const String& value){return value.back()-'0';}
String endpoint(unsigned value){char result[9];std::snprintf(result,sizeof(result),"%08x",value);return result;}
String jsonStringField(const String& command,const char* key){
    const String k=key;
    if(k=="factory_endpoint")return endpoint(0x11556677+number(command));
    if(k=="controller_endpoint")return "a2446688";
    if(k=="companion_endpoint")return "22446688";
    if(k=="recovery_command_id")return "";
    if(k=="owner_id")return "owner"+std::to_string(number(command));
    if(k=="open_command_id")return "open"+std::to_string(number(command));
    if(k=="port_1_settings" || k=="port_2_settings")return String("58020a001e00")+String(16,'0');
    return "20261005120000";
}
bool jsonLongField(const String& command,const char* key,long& value){
    const String k=key;
    if(k=="phase")value=command.find("close")==0 ? 4 : 3;
    else if(k=="port")value=1;
    else if(k=="seconds")value=60;
    else if(k=="assigned_selector")value=11;
    else if(k=="initial_center_hz")value=434397000;
    else if(k=="routine_center_hz")value=434287000;
    else if(k=="reply_delay_us")value=49000;
    else if(k=="notification_delay_ms")value=1000;
    else if(k=="notification_phase" || k=="configuration_revision")value=2;
    else if(k=="device_address")value=number(command)+2;
    else if(k=="timing_raw")value=480;
    else if(k=="power_dbm")value=0;
    else return false;
    return true;
}
bool jsonBoolField(const String&,const char*,bool& value){value=true;return true;}
bool parseRawHexEndpoint(const String& text,rainpoint::htv213::Endpoint& out){
    for(unsigned i=0;i<4;++i)out[i]=std::stoul(text.substr(i*2,2),nullptr,16);return true;
}
bool parsePairingLocalDateTime(const String&,rainpoint::PairingLocalDateTime& out){out={2026,10,5,12,0,0};return true;}
bool validCommandId(const String& value){return !value.empty();}
void reportNetworkCommandError(const String&,const char* error){lastError=error;}
'''+runtime
        events=json.loads((ROOT/'research/fixtures/htv213_stock_pairing_controls_20260928.json').read_text())['trials']
        events=next(t for t in events if t['name']=='zone1_auto60')['events']
        ack=next(e['frame'] for e in events if e['direction']=='device' and decode(e['frame']).command==0xa1)
        report=next(e['frame'] for e in events if e['direction']=='device' and decode(e['frame']).command==2)
        support+='''
rainpoint::htv213::Frame frame(const char* text,unsigned owner){
    rainpoint::htv213::Frame f{};const String value(text);
    for(unsigned i=0;i<f.size();++i)f[i]=std::stoul(value.substr(i*2,2),nullptr,16);
    auto paired=endpoint((0x11556677+owner)|0x80000000);
    for(unsigned i=0;i<4;++i)f[9+i]=std::stoul(paired.substr(i*2,2),nullptr,16);
    rainpoint::writeTrailer(f,0xc713);return f;
}
bool target(unsigned owner){
    const auto& f=primaryRadio.transmissions.back();const auto expected=endpoint((0x11556677+owner)|0x80000000);
    for(unsigned i=0;i<4;++i)if(f[5+i]!=std::stoul(expected.substr(i*2,2),nullptr,16))return false;
    return true;
}
int main(){
    for(unsigned i=0;i<8;++i){
        const auto id="owner"+std::to_string(i);
        if(!dispatchHtv213ControlCommand("htv213_owner_set",std::to_string(i),id) || !lastError.empty())return 1;
    }
    if(ownerStatuses.size()!=8 || !primaryRadio.commands.empty())return 2;
    dispatchHtv213ControlCommand("htv213_owner_set","8","owner8");
    if(lastError!="htv213_owner_missing_or_capacity")return 3;
    lastError.clear();
    if(dispatchHtv213ControlCommand("routine_ack_authorize","0","sensor"))return 4;
    if(!dispatchHtv213ControlCommand("htv213_control_open","3","open3") || !lastError.empty() || !target(3))return 5;
    const auto count=primaryRadio.commands.size();
    dispatchHtv213ControlCommand("htv213_control_open","1","too-early");
    if(lastError!="radio_busy_with_other_valve" || primaryRadio.commands.size()!=count)return 6;
    lastError.clear();fakeNow=313;
    if(!dispatchHtv213Frame(frame("ACK",3),rainpoint::RadioPacket{313000}) || htv213ResponseCenterHz())return 7;
    if(!dispatchHtv213Frame(frame("REPORT",1),rainpoint::RadioPacket{314000}) || !target(1))return 8;
    if(!dispatchHtv213ControlCommand("htv213_control_open","1","open1") || !lastError.empty() || !target(1))return 9;
    fakeNow=626;dispatchHtv213Frame(frame("ACK",1),rainpoint::RadioPacket{626000});
    if(!dispatchHtv213ControlCommand("htv213_control_close","close1","close1") || !lastError.empty() || !target(1))return 10;
    dispatchHtv213ControlCommand("htv213_owner_clear","2","clear2");
    if(!lastError.empty() || ownerStatuses.back()!=std::make_pair(String("owner2"),false))return 11;
    if(dispatchHtv213Frame(frame("REPORT",2),rainpoint::RadioPacket{627000}))return 12;
    return 0;
}
'''.replace('ACK',ack).replace('REPORT',report)
        with tempfile.TemporaryDirectory() as directory:
            executable=str(Path(directory)/'owners')
            built=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror',
                '-I'+str(ROOT/'firmware/rainpoint_bridge/include'),'-x','c++','-','-o',executable],
                input=support,text=True,capture_output=True)
            self.assertEqual(built.returncode,0,built.stderr)
            result=subprocess.run([executable],text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr+f' mode={result.returncode}')
