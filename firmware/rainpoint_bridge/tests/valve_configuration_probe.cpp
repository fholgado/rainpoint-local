// Offline fixture adapter. No radio, socket, serial, or production dispatcher.
#include <iostream>
#include <iomanip>
#include <string>
#include "rainpoint_valve_configuration.h"

template<std::size_t N>
std::array<std::uint8_t, N> hex(const std::string& text) {
    if (text.size() != N * 2) throw std::invalid_argument("hex length");
    std::array<std::uint8_t, N> result{};
    for (std::size_t i = 0; i < N; ++i) {
        const auto part = text.substr(i * 2, 2);
        if (part.find_first_not_of("0123456789abcdefABCDEF") != std::string::npos)
            throw std::invalid_argument("hex character");
        result[i] = static_cast<std::uint8_t>(std::stoul(part, nullptr, 16));
    }
    return result;
}

int main(int argc, char** argv) {
    using namespace rainpoint::valveConfiguration;
    // model selector revision routeA routeB settings|- empty-plan frame
    // optional current encoded time and units (or - for unknown).
    if (argc != 11) return 2;
    try {
        Association association{};
        const std::string model = argv[1];
        if (model == "145") association.model = Model::Htv145;
        else if (model == "213") association.model = Model::Htv213;
        else if (model == "405") association.model = Model::Htv405;
        else return 2;
        const auto selector = std::stoul(argv[2]);
        const auto revision = std::stoul(argv[3]);
        if (selector > 255 || revision > 255) return 2;
        association.selector = selector;
        association.configurationRevision = revision;
        association.requestRouteA = hex<4>(argv[4]);
        association.requestRouteB = hex<4>(argv[5]);
        for (auto& port : association.ports) {
            if (std::string(argv[6]) != "-") {
                port.settings = hex<14>(argv[6]);
                port.settingsKnown = true;
            }
            port.emptyPlanKnown = std::string(argv[7]) == "1";
        }
        ReportContext context{};
        if (std::string(argv[9]) != "-") {
            context.time = hex<5>(argv[9]);
            context.timeKnown = true;
        }
        if (std::string(argv[10]) != "-") {
            context.units = hex<2>(argv[10]);
            context.unitsKnown = true;
        }
        Reply reply{};
        const auto result = prepareReply(association, hex<38>(argv[8]), context, reply);
        std::cout << static_cast<int>(result) << ' ' << static_cast<int>(reply.command)
                  << ' ' << static_cast<int>(reply.phase) << ' ' << static_cast<int>(reply.port) << ' ';
        for (std::size_t i = 0; i < reply.length; ++i)
            std::cout << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(reply.data[i]);
        std::cout << '\n';
    } catch (const std::exception&) { return 2; }
}
