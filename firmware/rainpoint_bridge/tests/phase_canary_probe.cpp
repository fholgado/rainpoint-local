#ifdef RAINPOINT_TEST_ARDUINO_WORD_MACRO
// Arduino.h is included before protocol headers on the ESP32. Reproduce its
// public function-like macro: a plain desktop build otherwise misses collisions.
#include <cstdint>
inline std::uint16_t makeWord(std::uint16_t value) { return value; }
inline std::uint16_t makeWord(std::uint8_t high, std::uint8_t low) {
    return (std::uint16_t(high) << 8U) | low;
}
#define word(...) makeWord(__VA_ARGS__)
#endif
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
            unsigned phase,ordinal,selector,now,commit,port=1; std::string id,route;
            input>>phase>>ordinal>>selector>>now>>commit>>id>>route;
            input>>port;
            std::array<std::uint8_t,8> bytes{};
            for (unsigned i=0;i<8;++i) bytes[i]=std::stoul(route.substr(i*2,2),nullptr,16);
            ok=guard.begin(auth,id.c_str(),phase,ordinal,selector,bytes,now,[&](const auto& record) {
                if (!commit) return false;
                saved=record; return true;
            },port);
        } else if (operation=="frame") {
            unsigned now; std::string raw; input>>now>>raw;
            rainpoint::commandPhase::Frame frame{};
            for (unsigned i=0;i<38;++i) frame[i]=std::stoul(raw.substr(i*2,2),nullptr,16);
            ok=guard.observe(frame,now); saved=guard.record;
        } else if (operation=="tick") {
            unsigned now; input>>now; ok=guard.tick(now); saved=guard.record;
        } else if (operation=="restart") {
            guard={}; guard.restore(saved); ok=true;
        } else if (operation=="legacy_restart") {
            saved.magic=0x50484331; saved.port=255;
            guard={}; guard.restore(saved); ok=guard.record.port==1;
        } else if (operation=="corrupt_port") {
            saved.port=5; guard={}; guard.restore(saved); ok=true;
        } else if (operation=="recover") {
            std::string id,attempt,ack,active,idle;
            unsigned ackAge,activeAge,idleAge,commit;
            input>>id>>attempt>>ackAge>>activeAge>>idleAge>>commit>>ack>>active>>idle;
            const auto parse=[](const std::string& hex) {
                rainpoint::commandPhase::Frame frame{};
                for(unsigned i=0;i<38;++i) frame[i]=std::stoul(hex.substr(2*i,2),nullptr,16);
                return frame;
            };
            ok=guard.recover(auth,id.c_str(),attempt.c_str(),parse(ack),parse(active),parse(idle),
                ackAge,activeAge,idleAge,[&](const auto& record) { if(!commit) return false; saved=record;return true; });
        } else if (operation=="release") {
            ok=guard.release(auth,[&](const auto& record) { saved=record; return true; });
        }
        std::cout<<ok<<" "<<unsigned(guard.record.stage)<<" "<<unsigned(guard.record.count)
                 <<" "<<unsigned(guard.record.phase)<<" "<<guard.locked()<<"\n";
    }
}
