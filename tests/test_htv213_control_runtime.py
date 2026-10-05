"""Execute the actual dry-control runtime with a register-level radio fake."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tests.test_htv213_runtime import function
from research.pairing_native_transcripts import decode
from tests.test_htv213_pairing import REPEAT_FACTORY
from tests.test_valve_configuration import alter

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
bool htv213RetainedRejoinEnabled=false;
rainpoint::valveConfiguration::Association htv213RetainedConfiguration{};
std::string htv213OwnerId;
void reportHtv213Owner(const rainpoint::htv213::Frame* =nullptr) {}
struct Wifi { bool allowed=true; bool authenticated() { return allowed; } } wifiTransport;
struct Maintenance { bool allowed=true; bool transmitAllowed() { return allowed; } } rfMaintenance;
void reportHtv213Control(const rainpoint::htv213::Frame* =nullptr) { ++reports; }
void restoreScanningAfterPairing() { scanning=true; }
using String=std::string;
String htv213ControlCommandId, htv213ControlOpenId, lastCommandError;
bool radiosHealthy=true, scanChannels=false;
bool htv213Armed() { return false; }
rainpoint::PairingSessionState currentPairingState() { return rainpoint::PairingSessionState::Disarmed; }
struct Authorizations { unsigned activeCount() { return 0; } } routineAckAuthorizations, htv405RoutineAckAuthorizations;
bool htv145OwnsReports() { return false; }
bool htv145Pending() { return false; }
struct Probe { bool commandPendingConfirmation=false, openQueued=false, closeQueued=false; } valveControlProbe;
String jsonStringField(const String& command,const char* key) {
    const String k=key;
    if(k=="recovery_command_id") return command=="malformed" ? "bad" :
        command=="resume" ? String(32,'a') : "";
    if(k=="factory_endpoint") return "11556677";
    if(k=="controller_endpoint") return "a2446688";
    if(k=="companion_endpoint") return "22446688";
    if(k=="port_1_settings" || k=="port_2_settings") return String("58020a001e00")+String(16,'0');
    return "20261004100000";
}
bool jsonLongField(const String&,const char* key,long& value) {
    const String k=key;
    if(k=="port" || k=="recovery_port") value=1;
    else if(k=="seconds" || k=="recovery_seconds") value=60;
    else if(k=="recovery_phase") value=3;
    else if(k=="assigned_selector") value=11;
    else if(k=="initial_center_hz") value=434397000;
    else if(k=="routine_center_hz") value=434287000;
    else if(k=="reply_delay_us") value=49000;
    else if(k=="power_dbm") value=0;
    else if(k=="device_address" || k=="notification_phase" || k=="configuration_revision") value=2;
    else if(k=="timing_raw") value=480;
    else if(k=="notification_delay_ms") value=1000;
    else return false;
    return true;
}
bool jsonBoolField(const String&,const char*,bool& value) { value=true; return true; }
bool parseRawHexEndpoint(const String& text,std::array<std::uint8_t,4>& out) {
    for(unsigned i=0;i<4;++i) out[i]=std::stoul(text.substr(i*2,2),nullptr,16);
    return true;
}
bool parsePairingLocalDateTime(const String&,rainpoint::PairingLocalDateTime& out) {
    out={2026,10,4,10,0,0}; return true;
}
void reportNetworkCommandError(const String&,const char* error) { lastCommandError=error; }
'''
        support += function((ROOT / "firmware/rainpoint_bridge/src/main.cpp").read_text(),
                            "bool validCommandId(")
        support = support.replace("bool enterIdle() {", "bool prepareTransmit() { return true; }\n"
            "    bool cacheTransmitFrequency(unsigned) { return true; }\n    bool enterIdle() {")
        support += "\n".join(function(source, signature) for signature in (
            "bool parseHtv213Settings(",
            "bool htv213ControlActive(", "void restoreHtv213ControlReceiver(",
            "void transmitHtv213Control(", "bool handleHtv213ControlCommand(",
            "void processHtv213Control(", "void pollHtv213Control("))
        fixture = json.loads((ROOT / "research/fixtures/htv213_stock_pairing_controls_20260928.json").read_text())
        trial = next(t for t in fixture["trials"] if t["name"] == "zone1_auto60")
        device = [e["frame"] for e in trial["events"] if e["direction"] == "device"]
        idle1 = next(f for f in device if decode(f).command == 2 and decode(f).data[3] == 0)
        data = bytearray(decode(idle1).data); data[2] = 2
        idle2 = alter(idle1, data=data)
        lifecycle = json.loads((ROOT / "research/fixtures/htv213_stock_lifecycle_20260928.json").read_text())
        battery = next(t for t in lifecycle["trials"] if t["name"] == "battery_rejoin")
        announcement = next(e["frame"] for e in battery["events"] if e["direction"] == "device" and
                            decode(e["frame"]).command == 1)
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
    if (mode=="resume-reconnect" || mode=="resume-reboot" || mode=="resume-invalid") {
        // Actual owner dispatcher must restore observation without an open.
        if(mode=="resume-reconnect") {
            htv213ControlTrial.start(p,1,60,3,0,tx);
            transmitHtv213Control(tx);
            htv213OwnerEnabled=true; htv213OwnerId="test-owner";
            fakeNow=130000; pollHtv213Control();
            wifiTransport.allowed=false; pollHtv213Control();
            wifiTransport.allowed=true;
        }
        const auto before=primaryRadio.commands.size();
        handleHtv213ControlCommand("htv213_owner_set",mode=="resume-invalid" ? "malformed" : "resume","test-owner");
        if(mode=="resume-invalid") return lastCommandError=="invalid_htv213_idle_recovery" &&
            primaryRadio.commands.size()==before && !htv213OwnerEnabled ? 0 : 30;
        if(!lastCommandError.empty() || primaryRadio.commands.size()!=before ||
           htv213ControlTrial.state()!=rainpoint::htv213Control::State::Overdue ||
           htv213ControlCommandId!=String(32,'a') || htv213ControlTrial.phase()!=3) return 31;
        processHtv213Control(frame("IDLE1"),rainpoint::RadioPacket{fakeNow*1000});
        if(htv213ControlTrial.state()==rainpoint::htv213Control::State::RecoveredIdle) return 32;
        ++fakeNow;
        processHtv213Control(frame("IDLE2"),rainpoint::RadioPacket{fakeNow*1000});
        if(htv213ControlTrial.state()!=rainpoint::htv213Control::State::RecoveredIdle ||
           htv213ControlTrial.openAcknowledged() || htv213ControlTrial.summaryReceived() ||
           htv213ControlActive() || scanChannels || !htv213OwnerEnabled ||
           primaryRadio.commands.size()!=before+2) return 33;
        for(unsigned i=before;i<primaryRadio.commands.size();++i)
            if(primaryRadio.commands[i]!=0x82) return 34;
        return 0;
    }
    if (mode=="ota-idle-owner" || mode=="ota-no-owner") {
        htv213OwnerEnabled=mode=="ota-idle-owner";
        htv213OwnerId="test-owner";
        // The real dispatcher must reach signed OTA validation without clearing
        // a persistent, idle RF owner. No parser fake is reached by this path.
        if (handleHtv213ControlCommand("firmware_update_start","{}","ota-test")) {
            std::cerr << "Idle OTA intercepted: " << lastCommandError << '\\n'; return 21;
        }
        if (htv213OwnerEnabled!=(mode=="ota-idle-owner") || htv213OwnerId!="test-owner" ||
            !primaryRadio.commands.empty() || htv213ControlTrial.phase()!=0) return 22;
        return 0;
    }
    if (!htv213ControlTrial.start(p,1,60,3,0,tx)) return 1;
    if (mode=="ota-active-owner" || mode=="ota-active-no-owner") {
        htv213OwnerEnabled=mode=="ota-active-owner";
        if (!handleHtv213ControlCommand("firmware_update_start","{}","ota-test") ||
            lastCommandError!="htv213_control_experiment_busy" || !htv213ControlActive() ||
            htv213ControlTrial.phase()!=3 || !primaryRadio.commands.empty()) return 23;
        return 0;
    }
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
    const bool rejoin=mode=="rejoin" || mode=="rejoin-boot07";
    const bool recovery=mode=="idle-recovery" || mode=="overdue-idle-recovery";
    const bool owner=mode=="owner" || rejoin || recovery;
    if (recovery) fakeNow=mode=="idle-recovery" ? 1501 : 130000;
    if (owner) {
        htv213OwnerEnabled=true; htv213OwnerId="test-owner";
        auto& a=htv213RetainedConfiguration;
        a.model=rainpoint::valveConfiguration::Model::Htv213;
        a.factoryEndpoint=p.factory; a.requestRouteA=p.controller;
        a.requestRouteB=p.factory; a.requestRouteB[0]|=128;
        a.address=p.address; a.selector=p.selector; a.timingKnown=true; a.timingRaw=p.timingRaw;
        a.configurationRevision=2;
        for (unsigned i=0;i<2;++i) {
            a.ports[i].settingsKnown=true; a.ports[i].emptyPlanKnown=true;
            a.ports[i].settings={{0x58,2,10,0,30,0,0,0,0,0,0,0,0,0}};
        }
    }
    if (mode=="accepted" || (owner && !recovery) || mode=="restore-failure") {
        fakeNow=313;
        processHtv213Control(frame("ACK_FRAME"),rainpoint::RadioPacket{313000});
    }
    pollHtv213Control();
    if (recovery) {
        processHtv213Control(frame("IDLE1"),rainpoint::RadioPacket{fakeNow*1000});
        if (htv213ControlTrial.state()==rainpoint::htv213Control::State::RecoveredIdle) return 24;
        ++fakeNow;
        processHtv213Control(frame("IDLE2"),rainpoint::RadioPacket{fakeNow*1000});
        if (htv213ControlTrial.state()!=rainpoint::htv213Control::State::RecoveredIdle ||
            htv213ControlActive() || scanning || !htv213OwnerEnabled ||
            primaryRadio.baseHz!=rainpoint::kReportHz ||
            primaryRadio.commands!=std::vector<unsigned>({0x21,0x82,0x82})) return 25;
        if (handleHtv213ControlCommand("firmware_update_start","{}","ota-test")) return 26;
        return 0; // No automatic retry, close, phase allocation or owner loss.
    }
    if (mode=="disconnect" || mode=="rf-disabled" || mode=="restore-failure") {
        if (htv213ControlActive() || !scanning) return 4;
    } else {
        if (primaryRadio.baseHz!=rainpoint::kReportHz) return 5;
        if (mode=="accepted" || owner) {
            const char* frames[]={REPORT_FRAMES};
            for (const char* text:frames) {
                fakeNow+=1000;
                processHtv213Control(frame(text),rainpoint::RadioPacket{fakeNow*1000});
            }
            if (htv213ControlTrial.state()!=rainpoint::htv213Control::State::Complete || scanning==owner) return 6;
            if (primaryRadio.commands.back()!=0x84) return 7;
            if (owner) {
                const auto count=primaryRadio.commands.size();
                processHtv213Control(frame(frames[0]),rainpoint::RadioPacket{fakeNow*1000});
                if (primaryRadio.commands.size()!=count+1 || !htv213OwnerEnabled) return 12;
                if (rejoin) {
                    const auto before=primaryRadio.commands.size();
                    const auto announcement=frame(mode=="rejoin-boot07" ? "BOOT07" : "ANNOUNCEMENT");
                    processHtv213Control(announcement,rainpoint::RadioPacket{fakeNow*1000});
                    if (primaryRadio.commands.size()!=before) return 14; // Disabled by default.
                    htv213RetainedRejoinEnabled=true;
                    processHtv213Control(announcement,rainpoint::RadioPacket{fakeNow*1000});
                    processHtv213Control(announcement,rainpoint::RadioPacket{fakeNow*1000});
                    if (primaryRadio.commands.size()!=before+2 || primaryRadio.commands.back()!=0x81 ||
                        primaryRadio.baseHz!=rainpoint::kReportHz ||
                        htv213ControlTrial.phase()!=3) return 15;
                }
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
        else if (command!=0x82 && command!=0x84 && (!rejoin || command!=0x81)) return 10;
    }
    return opens==1 ? 0 : 11;
}
'''.replace("ACK_FRAME", device[0]).replace("REPORT_FRAMES", ",".join(json.dumps(f) for f in device[1:])).replace("ANNOUNCEMENT", announcement).replace("BOOT07", REPEAT_FACTORY).replace("IDLE1", idle1).replace("IDLE2", idle2)
        with tempfile.TemporaryDirectory() as directory:
            exe = str(Path(directory) / "runtime")
            result = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                "-I"+str(ROOT / "firmware/rainpoint_bridge/include"), "-x", "c++", "-", "-o", exe],
                input=support, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for mode in ("ota-idle-owner", "ota-no-owner", "ota-active-owner", "ota-active-no-owner",
                         "resume-reconnect", "resume-reboot", "resume-invalid",
                         "idle-recovery", "overdue-idle-recovery",
                         "accepted", "owner", "rejoin", "rejoin-boot07", "timeout", "disconnect", "rf-disabled", "restore-failure", "tx-failure"):
                with self.subTest(mode=mode):
                    result = subprocess.run([exe, mode], text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
