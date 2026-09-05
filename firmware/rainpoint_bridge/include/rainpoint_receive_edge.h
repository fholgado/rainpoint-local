#pragma once

#include <cstddef>
#include <cstdint>

#include "rainpoint_protocol.h"

namespace rainpoint {

struct ReceiveEndObservation {
    bool valid = false;
    std::uint32_t endedAtMicros = 0;
    std::uint32_t highObservedMicros = 0;
    std::uint32_t pollLagMicros = 0;
};

// One packet-end edge may anchor only the next complete, unambiguous FIFO
// packet. A flush, short GPIO pulse, timeout, or stale edge invalidates it.
class ReceiveEndCapture {
public:
    static constexpr std::uint32_t kMinimumHighMicros = 200;
    static constexpr std::uint32_t kMaximumHighMicros = 16'000;
    static constexpr std::uint32_t kMaximumPollLagMicros = 2'000;

    void clear() { observation_ = {}; }

    void observe(std::uint32_t endedAtMicros, std::uint32_t highMicros) {
        observation_ = {
            highMicros >= kMinimumHighMicros &&
                highMicros <= kMaximumHighMicros,
            endedAtMicros,
            highMicros,
            0,
        };
    }

    ReceiveEndObservation take(std::uint32_t polledAtMicros,
                               std::size_t fifoBytes) {
        auto result = observation_;
        clear();
        result.pollLagMicros = polledAtMicros - result.endedAtMicros;
        result.valid = result.valid &&
            result.pollLagMicros <= kMaximumPollLagMicros &&
            fifoBytes == kRadioPayloadBytes + 2;
        return result;
    }

private:
    ReceiveEndObservation observation_{};
};

}  // namespace rainpoint
