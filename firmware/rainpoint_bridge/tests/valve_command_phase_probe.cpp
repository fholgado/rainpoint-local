// Host-only phase replay. No device, serial, network or radio access.
#include <iomanip>
#include <iostream>
#include <string>
#include "rainpoint_valve_command_phase.h"

int main() {
    using namespace rainpoint;
    std::string model, a, b;
    unsigned phase, open, seconds, port, selector, residue;
    while (std::cin >> model) {
        if (model=="result") {
            std::string raw; std::cin >> raw;
            if (raw.size()!=kFrameBytes*2) return 2;
            commandPhase::Frame frame{};
            for (unsigned i=0;i<frame.size();++i) frame[i]=std::stoul(raw.substr(i*2,2),nullptr,16);
            commandPhase::ResultEnvelope result{};
            const bool ready=commandPhase::decodeResultEnvelope(frame,result);
            std::cout << ready << ' ' << result.phase << ' ' << unsigned(result.result)
                      << ' ' << unsigned(result.controlMode) << ' ' << unsigned(result.workMode) << '\n';
            continue;
        }
        if (!(std::cin >> phase >> open >> seconds >> port >> selector >> residue >> a >> b)) return 2;
        if (a.size() != 8 || b.size() != 8 || open > 1 || seconds > 65535 ||
            port > 255 || selector > 255 || residue > 65535) return 2;
        Htv145Link single{};
        for (unsigned i=0; i<4; ++i) {
            single.controllerEndpoint[i]=std::stoul(a.substr(i*2,2),nullptr,16);
            single.valveEndpoint[i]=std::stoul(b.substr(i*2,2),nullptr,16);
        }
        Htv405GatewayControlLink multi{single.controllerEndpoint, single.valveEndpoint};
        commandPhase::Frame frame{};
        bool ready=false;
        if (model=="145") ready=port==1 && commandPhase::buildHtv145(single,phase,open,seconds,residue,frame);
        else if (model=="405") ready=commandPhase::buildHtv405(multi,phase,open,seconds,port,selector,residue,frame);
        else if (model=="legacy145" || model=="legacy145normal") {
            const bool inverted=model=="legacy145";
            ready=phase<32 && (open
                ? buildHtv145OpenFrame(single,0x80|phase,seconds,residue,frame,inverted)
                : buildHtv145CloseFrame(single,0x80|phase,residue,frame,inverted));
        } else if (model=="legacy405") {
            const Htv405Phase legacy{static_cast<std::uint8_t>(phase),false};
            ready=phase<32 && (open
                ? buildHtv405GatewayOpenFrame(multi,legacy,port,selector,seconds,residue,frame)
                : buildHtv405GatewayCloseFrame(multi,legacy,port,selector,residue,frame));
        } else return 3;
        if (ready && (model=="145" || model=="405") && commandPhase::fromNormalized(frame)!=phase) return 4;
        std::cout << ready << ' ';
        if (ready) for (auto byte:frame) std::cout << std::hex << std::setfill('0') << std::setw(2) << unsigned(byte);
        else std::cout << '-';
        std::cout << std::dec << '\n';
    }
}
