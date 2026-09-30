#pragma once

#include "rainpoint_htv145_control.h"
#include "rainpoint_valve_control.h"

namespace rainpoint::commandPhase {

// Builders shared by offline replay and the explicitly enabled phase canary.
// The caller supplies admission, persistence and RF authority.
// Keep the established association-specific body and trailer builders; only
// represent the complete native phase independently of the watering action.
// These are normalized 38-byte windows, NOT complete on-air symbol streams.
using Frame = std::array<std::uint8_t, kFrameBytes>;

inline unsigned fromNormalized(const Frame& frame) {
    // The caller must independently validate the frame and its association.
    return ((frame[13] & 31U) << 1U) | (frame[14] >> 7U);
}

struct ResultEnvelope {
    unsigned phase = 0;
    std::uint8_t result = 0, controlMode = 0, workMode = 0;
    // No port: the stock hub obtains it from its retained request context.
};

inline bool decodeResultEnvelope(const Frame& frame, ResultEnvelope& result) {
    result = {};
    if (!hasSync(frame) || !hasOrdinaryTrailer(frame)) return false;
    const auto native = [&frame](unsigned index) {
        return static_cast<std::uint8_t>((frame[index+4] << 1U) | (frame[index+5] >> 7U));
    };
    if (native(0) != 0x51 || native(10) != 0xa1 || (native(11) & 31U) != 13) return false;
    result.phase = fromNormalized(frame);
    result.result = native(12);
    result.controlMode = native(13) >> 4U;
    result.workMode = native(13) & 15U;
    // Parsing is not acceptance. Caller must check association, reserved full
    // phase, result and model-qualified state, then independent port telemetry.
    return true;
}

inline bool buildHtv145(const Htv145Link& link, unsigned phase, bool open,
                        std::uint32_t seconds, std::uint16_t residue,
                        Frame& frame) {
    frame = {};
    if (phase > 63 || (!open && seconds != 0)) return false;
    const auto sequence = static_cast<std::uint8_t>(0x80U | (phase >> 1U));
    const bool markerInverted = bool(phase & 1U) == open;
    return open
        ? buildHtv145OpenFrame(link, sequence, seconds, residue, frame, markerInverted)
        : buildHtv145CloseFrame(link, sequence, residue, frame, markerInverted);
}

inline bool buildHtv405(const Htv405GatewayControlLink& link, unsigned phase,
                        bool open, std::uint16_t seconds, std::uint8_t zone,
                        std::uint8_t selector, std::uint16_t residue,
                        Frame& frame) {
    frame = {};
    if (phase > 63 || (!open && seconds != 0)) return false;
    const Htv405Phase legacy{static_cast<std::uint8_t>(phase >> 1U), false};
    const bool ready = open
        ? buildHtv405GatewayOpenFrame(link, legacy, zone, selector, seconds, residue, frame)
        : buildHtv405GatewayCloseFrame(link, legacy, zone, selector, residue, frame);
    if (!ready) return false;
    frame[14] = static_cast<std::uint8_t>((frame[14] & 0x7fU) | ((phase & 1U) << 7U));
    writeTrailer(frame, residue);
    return true;
}

} // namespace rainpoint::commandPhase
