// Register-level fake around actual runtime and CC1101 tuning methods.
// Synthetic endpoints; packet bodies/phases from Sep 30 local SDR capture.
#include <iostream>
#include <string>
#include <vector>
#include "rainpoint_htv213_pairing.h"

unsigned fakeNow = 0;
unsigned millis() { return fakeNow; }
namespace rainpoint {
struct RadioPacket { unsigned receivedAtMicros = 0; };
constexpr unsigned kReportHz = 433140000;
constexpr unsigned kChannelNumber = 10, kFlushRx = 58;
class Cc1101 {
public:
    unsigned baseHz = kReportHz;
    unsigned channel_ = 0;
    bool restoreOk = true;
    std::vector<unsigned> commands;
    bool enterIdle() { return true; }
    void strobe(unsigned) {}
    void writeRegister(unsigned, unsigned) {}
    void setFrequency(unsigned hz) { baseHz = hz; }
    bool enterReceive() { return true; }
    bool restoreReceiveConfiguration(unsigned channel) {
        if (!restoreOk) return false;
        baseHz = kReportHz; channel_ = channel; return true;
    }
    bool setChannel(std::uint8_t channel);
    bool setReceiveFrequency(std::uint32_t hz);
    bool restoreReceiveChannel(std::uint8_t channel);
    bool transmitAsync(const htv213::Frame& frame, unsigned, unsigned, bool,
                       unsigned, unsigned, unsigned = 0) {
        commands.push_back(htv213::native(frame)[10]);
        // Real transmitAsync restores the full RX configuration before return.
        return restoreReceiveConfiguration(channel_);
    }
};
// ACTUAL_DRIVER_METHODS
}
rainpoint::Cc1101 primaryRadio;
rainpoint::htv213::Session htv213Session;
rainpoint::PairingLocalDateTime htv213Clock{2026,9,30,10,0,0};
unsigned htv213ClockAt = 0;
std::int8_t htv213Power = 0;
bool htv213ListeningForNotification = false;
struct Wifi { bool authenticated() { return true; } } wifiTransport;
struct Maintenance { bool transmitAllowed() { return true; } } rfMaintenance;
bool htv213Armed() { return htv213Session.state() == rainpoint::htv213::State::Armed; }
void reportHtv213() {}
void restoreScanningAfterPairing() {} // Real helper only re-enables scanning.
// ACTUAL_RUNTIME_FUNCTIONS

rainpoint::htv213::Frame frame(const char* text) {
    rainpoint::htv213::Frame out{};
    const std::string hex(text);
    for (unsigned i=0; i<out.size(); ++i) out[i]=std::stoul(hex.substr(i*2,2),nullptr,16);
    return out;
}
void receive(unsigned now, const char* text) {
    fakeNow=now;
    processHtv213(frame(text),rainpoint::RadioPacket{now*1000});
}
int main(int argc, char** argv) {
    const std::string mode = argc > 1 ? argv[1] : "accepted";
    const bool timeout = mode == "timeout" || mode == "wrong-phase";
    rainpoint::htv213::Profile p{};
    p.factory={{0x11,0x55,0x66,0x77}};
    p.controller={{0xa2,0x44,0x66,0x88}}; p.companion={{0x22,0x44,0x66,0x88}};
    p.address=2; p.selector=11; p.notificationPhase=2; p.timingRaw=480;
    p.initialHz=434397000; p.routineHz=434287000;
    p.replyDelayUs=49000; p.notificationDelayMs=1000;
    p.settings={{0x58,2,10,0,30,0,0,0,0,0,0,0,0,0}};
    if (!htv213Session.arm(p,0,300000)) return 1;
    receive(1,"79f4882f28800000001155667700808405ff900280821f03800000000000000000000000191b");
    receive(71665,"79f4882f28a24466889155667704010785a580804f800000004080005680000000000000ab8c");
    receive(73685,"79f4882f28a244668891556677048107858581004f800000004080005680000000000000719a");
    fakeNow=74685; pollHtv213();
    if (primaryRadio.baseHz!=p.routineHz) return 2;
    if (!timeout) {
        receive(75201,"79f4882f28a24466889155667701500080000000000000000000000000000000000000003742");
        if (!htv213Session.notificationAccepted()) return 3;
    } else {
        fakeNow=75434; pollHtv213();
        if (primaryRadio.baseHz!=p.routineHz) return 6;
        if (mode=="wrong-phase") {
            auto wrong = frame("79f4882f28a24466889155667701500080000000000000000000000000000000000000003742");
            // Full frame remains checksum-valid after changing native phase.
            wrong[13]^=1;
            const auto crc=rainpoint::crcCcittZero(wrong.data(),wrong.size()-2)^0xc713;
            wrong[36]=crc>>8; wrong[37]=crc&255;
            processHtv213(wrong,rainpoint::RadioPacket{});
            if (htv213Session.notificationAccepted()) return 7;
        }
        fakeNow=75435;
    }
    if (mode=="restore-failure") primaryRadio.restoreOk=false;
    pollHtv213();
    if (mode=="restore-failure") {
        if (htv213Armed() || htv213Session.failure()!=rainpoint::htv213::Failure::Receiver)
            return 8;
        return 0;
    }
    if (primaryRadio.baseHz!=rainpoint::kReportHz) {
        std::cerr << "Report carrier not restored after a0: " << primaryRadio.baseHz << '\n';
        return 4;
    }
    receive(111653,"79f4882f28a2446688915566770602810580800000000000000000000000000000000000b0b6");
    if (timeout) {
        if (htv213Session.notificationAccepted() || htv213Session.settingsSent()) return 9;
        // Lost/mismatched a0 must not strand ordinary reports on the other carrier.
        receive(111654,"79f4882f28a244668891556677058107858581004f8000000040800056800000000000001491");
        if (primaryRadio.commands.back()!=0x82) return 10;
    } else if (htv213Session.settingsSent()!=1 || primaryRadio.commands.back()!=0x85) {
        std::cerr << "Port-1 settings request unanswered\n"; return 5;
    }
    for (const auto command : primaryRadio.commands)
        if (command!=0x81 && command!=0x82 && command!=0x20 && command!=0x85) return 11;
}
