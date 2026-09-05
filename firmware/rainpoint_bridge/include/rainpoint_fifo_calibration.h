#pragma once

#include <array>
#include <cstdint>
#include <vector>

#include "rainpoint_protocol.h"

namespace rainpoint {

constexpr std::uint16_t kMaxFifoActiveTailDelayUs = 1'200;

// An optional zero byte keeps the modulator supplied while the research
// caller measures the FIFO-empty edge and stops TX. It is outside the frame.
inline bool buildFifoCalibrationStream(
    const std::array<std::uint8_t, kFrameBytes>& frame,
    std::uint16_t wakeSymbols,
    std::uint16_t activeTailDelayUs,
    std::vector<std::uint8_t>& stream
) {
    if ((wakeSymbols != 320 && wakeSymbols != 2'400) ||
        activeTailDelayUs > kMaxFifoActiveTailDelayUs) return false;
    stream.assign(wakeSymbols / 8, 0x55);
    stream.insert(stream.end(), frame.begin(), frame.end());
    if (activeTailDelayUs != 0) stream.push_back(0x00);
    return true;
}

}  // namespace rainpoint
