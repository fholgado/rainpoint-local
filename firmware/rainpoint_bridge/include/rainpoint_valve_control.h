#pragma once

#include <array>
#include <cstdint>

#include "rainpoint_protocol.h"

namespace rainpoint {

struct Htv405ValveLink {
    std::array<std::uint8_t, 4> controllerEndpoint{};
    std::array<std::uint8_t, 4> valveEndpoint{};
};

struct Htv405Phase {
    std::uint8_t sequence;
    bool repeat;
};

inline bool validHtv405ValveLink(const Htv405ValveLink& link) {
    return link.controllerEndpoint != std::array<std::uint8_t, 4>{} &&
        link.valveEndpoint != std::array<std::uint8_t, 4>{} &&
        link.controllerEndpoint != link.valveEndpoint;
}

inline bool isHtv405LinkFrame(
    const std::array<std::uint8_t, kFrameBytes>& frame
) {
    return hasSync(frame) && hasOrdinaryTrailer(frame) &&
        frame[15] == 0x07 && frame[16] == 0x82 &&
        (frame[17] & 0x7fU) == 0x07 &&
        (frame[20] & 0x7fU) == 0x4f &&
        frame[25] == 0x40 && frame[28] == 0x56;
}

inline bool nextHtv405Phase(
    const std::array<std::uint8_t, kFrameBytes>& report,
    Htv405Phase& phase
) {
    if (!isHtv405LinkFrame(report)) {
        return false;
    }
    const auto sequence = static_cast<std::uint8_t>(report[13] & 0x1fU);
    const bool repeated = (report[14] & 0x80U) != 0;
    phase.sequence = repeated
        ? static_cast<std::uint8_t>((sequence + 1U) & 0x1fU)
        : sequence;
    phase.repeat = !repeated;
    return true;
}

inline bool buildHtv405CloseFrame(
    const Htv405ValveLink& link,
    Htv405Phase phase,
    std::uint8_t zone,
    std::uint8_t selector,
    std::uint16_t trailerResidual,
    std::array<std::uint8_t, kFrameBytes>& frame
) {
    if (!validHtv405ValveLink(link) || phase.sequence > 0x1f ||
        zone < 1 || zone > 4 ||
        (selector != 0x05 && selector != 0x85) ||
        (trailerResidual != 0xc713 && trailerResidual != 0x4f03)) {
        return false;
    }

    frame.fill(0);
    for (std::size_t index = 0; index < kSync.size(); ++index) {
        frame[index] = kSync[index];
    }
    for (std::size_t index = 0; index < 4; ++index) {
        frame[5 + index] = link.controllerEndpoint[index];
        frame[9 + index] = link.valveEndpoint[index];
    }

    frame[13] = phase.sequence;
    frame[14] = phase.repeat ? 0x81 : 0x01;
    frame[15] = 0x07;
    frame[16] = 0x82;
    frame[17] = selector;
    frame[18] = static_cast<std::uint8_t>(0x80U | (zone / 2U));
    frame[19] = zone % 2U ? 0x80 : 0x00;
    frame[20] = 0x4f;
    frame[21] = 0x80;
    frame[25] = 0x40;
    frame[26] = 0x80;
    frame[28] = 0x56;
    frame[29] = 0x80;
    writeTrailer(frame, trailerResidual);
    return true;
}

}  // namespace rainpoint
