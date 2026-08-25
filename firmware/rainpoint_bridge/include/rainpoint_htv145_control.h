#pragma once

#include <array>
#include <cstdint>

#include "rainpoint_protocol.h"

namespace rainpoint {

// Stock HTV145 opens use a 1,200-symbol command wake. One retained logical
// open contained three byte-identical attempts at these offsets. The attempts
// are one bounded RF burst; a controller must never create a second logical
// open merely because its acknowledgement was missed.
constexpr std::uint16_t kHtv145CommandWakeSymbols = 1'200;
constexpr std::array<std::uint32_t, 3> kHtv145CommandAttemptOffsetsMs = {
    0,
    730,
    1'670,
};
constexpr std::uint32_t kHtv145ImmediateResponseWindowMs = 3'000;
constexpr std::uint32_t kHtv145StateConfirmationWindowMs = 15'000;

struct Htv145Link {
    std::array<std::uint8_t, 4> controllerEndpoint{};
    std::array<std::uint8_t, 4> valveEndpoint{};
};

struct Htv145CommandResponse {
    std::uint8_t sequence = 0;
    bool watering = false;
};

inline bool validHtv145Link(const Htv145Link& link) {
    return link.controllerEndpoint != std::array<std::uint8_t, 4>{} &&
        link.valveEndpoint != std::array<std::uint8_t, 4>{} &&
        link.controllerEndpoint != link.valveEndpoint;
}

inline bool htv145RouteMatches(
    const std::array<std::uint8_t, kFrameBytes>& frame,
    const std::array<std::uint8_t, 4>& endpointA,
    const std::array<std::uint8_t, 4>& endpointB
) {
    for (std::size_t index = 0; index < 4; ++index) {
        if (frame[5 + index] != endpointA[index] ||
            frame[9 + index] != endpointB[index]) {
            return false;
        }
    }
    return true;
}

inline bool validHtv145Sequence(std::uint8_t sequence) {
    return sequence >= 0x80 && sequence <= 0x9f;
}

inline std::uint8_t nextHtv145CommandSequence(std::uint8_t sequence) {
    return static_cast<std::uint8_t>(0x80U | ((sequence + 1U) & 0x1fU));
}

inline bool encodeHtv145Duration(
    std::uint32_t durationSeconds,
    std::array<std::uint8_t, 2>& encoded
) {
    if (durationSeconds < 60 || durationSeconds > 24U * 60U * 60U ||
        durationSeconds % 60U != 0) {
        return false;
    }
    const std::uint32_t units = durationSeconds / 2U;
    if (units > 0xffffU) {
        return false;
    }
    encoded[0] = static_cast<std::uint8_t>(units & 0xffU) | 0x80U;
    encoded[1] = static_cast<std::uint8_t>(units >> 8U);
    return true;
}

inline bool buildHtv145OpenFrame(
    const Htv145Link& link,
    std::uint8_t sequence,
    std::uint32_t durationSeconds,
    std::uint16_t trailerResidual,
    std::array<std::uint8_t, kFrameBytes>& frame
) {
    std::array<std::uint8_t, 2> duration{};
    if (!validHtv145Link(link) || !validHtv145Sequence(sequence) ||
        !encodeHtv145Duration(durationSeconds, duration) ||
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
    frame[13] = sequence;
    frame[14] = 0x10;
    frame[15] = 0x82;
    frame[16] = 0x80;
    frame[17] = 0x81;
    frame[19] = duration[0];
    frame[20] = duration[1];
    writeTrailer(frame, trailerResidual);
    return true;
}

inline bool buildHtv145CloseFrame(
    const Htv145Link& link,
    std::uint8_t sequence,
    std::uint16_t trailerResidual,
    std::array<std::uint8_t, kFrameBytes>& frame
) {
    if (!validHtv145Link(link) || !validHtv145Sequence(sequence) ||
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
    frame[13] = sequence;
    frame[14] = 0x90;
    frame[15] = 0x81;
    frame[16] = 0x80;
    frame[17] = 0x81;
    writeTrailer(frame, trailerResidual);
    return true;
}

inline bool decodeHtv145CommandResponse(
    const std::array<std::uint8_t, kFrameBytes>& frame,
    const Htv145Link& link,
    Htv145CommandResponse& response
) {
    if (!hasSync(frame) || !hasOrdinaryTrailer(frame) ||
        !htv145RouteMatches(
            frame, link.valveEndpoint, link.controllerEndpoint
        ) ||
        !validHtv145Sequence(frame[13]) ||
        (frame[14] != 0x50 && frame[14] != 0xd0) ||
        frame[15] != 0x86 || frame[16] != 0x80 ||
        (frame[17] & 0x0fU) != 0 ||
        (frame[18] & 0x7fU) != 0x4f ||
        ((frame[14] ^ frame[18]) & 0x80U) == 0 ||
        frame[23] != 0x40 || frame[26] != 0x56) {
        return false;
    }
    response.sequence = frame[13];
    response.watering = frame[14] == 0x50;
    return true;
}

inline bool decodeHtv145StateReport(
    const std::array<std::uint8_t, kFrameBytes>& frame,
    const Htv145Link& link,
    bool& watering
) {
    if (!hasSync(frame) || !hasOrdinaryTrailer(frame) ||
        !htv145RouteMatches(
            frame, link.valveEndpoint, link.controllerEndpoint
        ) ||
        frame[15] != 0x07 || frame[16] != 0x85 ||
        (frame[14] != 0x01 && frame[14] != 0x81) ||
        (frame[20] & 0x7fU) != 0x4f) {
        return false;
    }
    watering = (frame[20] & 0x80U) != 0;
    return true;
}

}  // namespace rainpoint
