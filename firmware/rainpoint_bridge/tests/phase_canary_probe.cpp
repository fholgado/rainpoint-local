#include "rainpoint_phase_canary.h"
#include <iostream>
#include <sstream>
#include <string>

int main() {
    rainpoint::phaseCanary::Guard guard;
    rainpoint::phaseCanary::Record saved{};
    const char* auth="abababababababababababababababab";
    std::string line;
    while (std::getline(std::cin,line)) {
        std::istringstream input(line); std::string operation; input>>operation;
        bool ok=false;
        if (operation=="begin") {
            unsigned phase,ordinal,selector,now,commit; std::string id,route;
            input>>phase>>ordinal>>selector>>now>>commit>>id>>route;
            std::array<std::uint8_t,8> bytes{};
            for (unsigned i=0;i<8;++i) bytes[i]=std::stoul(route.substr(i*2,2),nullptr,16);
            ok=guard.begin(auth,id.c_str(),phase,ordinal,selector,bytes,now,[&](const auto& record) {
                if (!commit) return false;
                saved=record; return true;
            });
        } else if (operation=="frame") {
            unsigned now; std::string raw; input>>now>>raw;
            rainpoint::commandPhase::Frame frame{};
            for (unsigned i=0;i<38;++i) frame[i]=std::stoul(raw.substr(i*2,2),nullptr,16);
            ok=guard.observe(frame,now); saved=guard.record;
        } else if (operation=="tick") {
            unsigned now; input>>now; ok=guard.tick(now); saved=guard.record;
        } else if (operation=="restart") {
            guard={}; guard.restore(saved); ok=true;
        } else if (operation=="release") {
            ok=guard.release(auth,[&](const auto& record) { saved=record; return true; });
        }
        std::cout<<ok<<" "<<unsigned(guard.record.stage)<<" "<<unsigned(guard.record.count)
                 <<" "<<unsigned(guard.record.phase)<<" "<<guard.locked()<<"\n";
    }
}
