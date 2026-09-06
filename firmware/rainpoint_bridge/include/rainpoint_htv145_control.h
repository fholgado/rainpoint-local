#pragma once

#include <algorithm>
#include <array>
#include <cstdint>

#include "rainpoint_protocol.h"

namespace rainpoint {

// Stock selector-6 opens and closes use a 2,400-symbol command wake, measured
// directly from the retained CU8 (2,399 alternating transitions before sync).
// The earlier 1,200-symbol assumption truncated that wake by 60 ms. One logical
// open contained three byte-identical attempts at these offsets. The attempts
// are one bounded RF burst; a controller must never create a second logical
// open merely because its acknowledgement was missed.
constexpr std::uint16_t kHtv145CommandWakeSymbols = 2'400;
constexpr std::array<std::uint32_t, 3> kHtv145CommandAttemptOffsetsMs = {
    0,
    730,
    1'670,
};
constexpr std::uint32_t kHtv145ImmediateResponseWindowMs = 3'000;
constexpr std::uint32_t kHtv145StateConfirmationWindowMs = 15'000;
constexpr std::uint32_t kHtv145MinimumCommandIntervalMs = 15'000;

inline bool htv145CommandIntervalElapsed(std::uint32_t last, std::uint32_t now) {
    return now - last >= kHtv145MinimumCommandIntervalMs;
}

struct Htv145Link {
    std::array<std::uint8_t, 4> controllerEndpoint{};
    std::array<std::uint8_t, 4> valveEndpoint{};
};

struct Htv145CommandResponse {
    std::uint8_t sequence = 0;
    bool watering = false;
    bool commandMarkerInverted = false;
};

struct Htv145CommandError {
    std::uint8_t sequence = 0;
    std::uint8_t resultCode = 0;
};

inline bool validHtv145Link(const Htv145Link& link) {
    return link.controllerEndpoint != std::array<std::uint8_t, 4>{} &&
        link.valveEndpoint != std::array<std::uint8_t, 4>{} &&
        link.controllerEndpoint != link.valveEndpoint;
}

inline bool canRevokeHtv145Owner(
    bool configured, bool pending, const Htv145Link& current, const Htv145Link& requested
) {
    return !pending && validHtv145Link(requested) && (!configured ||
        (current.controllerEndpoint == requested.controllerEndpoint &&
         current.valveEndpoint == requested.valveEndpoint));
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

inline std::uint8_t nextHtv145CommandSequence(
    std::uint8_t sequence, bool watering
) {
    // Stock selector-6 trace: open 81, close 82, open 82, close 83.
    return watering
        ? static_cast<std::uint8_t>(0x80U | ((sequence + 1U) & 0x1fU))
        : sequence;
}

inline bool encodeHtv145Duration(
    std::uint32_t durationSeconds,
    std::array<std::uint8_t, 2>& encoded
) {
    PackedDuration packed{};
    if (!encodePackedWholeMinuteDuration(
            durationSeconds, 24U * 60U * 60U, packed
        )) {
        return false;
    }
    encoded = packed.field;
    return true;
}

inline bool buildHtv145OpenFrame(
    const Htv145Link& link,
    std::uint8_t sequence,
    std::uint32_t durationSeconds,
    std::uint16_t trailerResidual,
    std::array<std::uint8_t, kFrameBytes>& frame,
    bool commandMarkerInverted = false
) {
    PackedDuration duration{};
    if (!validHtv145Link(link) || !validHtv145Sequence(sequence) ||
        !encodePackedWholeMinuteDuration(
            durationSeconds, 24U * 60U * 60U, duration
        ) ||
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
    frame[14] = commandMarkerInverted ? 0x90 : 0x10;
    frame[15] = 0x82;
    frame[16] = 0x80;
    frame[17] = 0x81;
    frame[19] = duration.field[0];
    frame[20] = duration.field[1];
    frame[21] = duration.extension;
    writeTrailer(frame, trailerResidual);
    return true;
}

inline bool buildHtv145CloseFrame(
    const Htv145Link& link,
    std::uint8_t sequence,
    std::uint16_t trailerResidual,
    std::array<std::uint8_t, kFrameBytes>& frame,
    bool commandMarkerInverted = false
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
    frame[14] = commandMarkerInverted ? 0x10 : 0x90;
    frame[15] = 0x81;
    frame[16] = 0x80;
    frame[17] = 0x81;
    writeTrailer(frame, trailerResidual);
    return true;
}

struct Htv145ControlProfile {
    Htv145Link link{};
    std::uint16_t trailerResidual = 0;
    bool commandMarkerInverted = false;
    // Stock recordings differ by association; the locally accepted recipe
    // uses 4f03 for both actions. Persist both residues explicitly.
    std::uint16_t closeTrailerResidual = 0x4f03;
};

inline bool buildHtv145ControlFrame(
    const Htv145ControlProfile& profile,
    std::uint8_t sequence,
    bool watering,
    std::uint32_t durationSeconds,
    std::array<std::uint8_t, kFrameBytes>& frame
) {
    return watering
        ? buildHtv145OpenFrame(
            profile.link, sequence, durationSeconds, profile.trailerResidual,
            frame, profile.commandMarkerInverted
        )
        : buildHtv145CloseFrame(
            profile.link, sequence, profile.closeTrailerResidual, frame,
            profile.commandMarkerInverted
        );
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
        frame[23] != 0x40 || (frame[26] & 0x7fU) != 0x56) {
        return false;
    }
    response.sequence = frame[13];
    // Offset 14's high marker flips between the selector-5 and selector-6
    // associations. Offset 18 remains cf=watering and 4f=idle in both.
    response.watering = (frame[18] & 0x80U) != 0;
    response.commandMarkerInverted =
        ((frame[14] & 0x80U) != 0) == response.watering;
    return true;
}

inline bool decodeHtv145CommandError(
    const std::array<std::uint8_t, kFrameBytes>& frame,
    const Htv145Link& link,
    Htv145CommandError& error
) {
    // Non-success family captured with both 50 and d0 command markers. Its
    // idle-looking fields do not prove a physical close or counter acceptance.
    constexpr std::array<std::uint8_t, 22> body = {
        0x50, 0x86, 0x83, 0x00, 0x4f, 0x80, 0x00, 0x00,
        0x00, 0x40, 0x80, 0x00, 0x56, 0x80, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    };
    if (!hasSync(frame) || !hasOrdinaryTrailer(frame) ||
        !htv145RouteMatches(frame, link.valveEndpoint, link.controllerEndpoint) ||
        !validHtv145Sequence(frame[13])) {
        return false;
    }
    for (std::size_t index = 0; index < body.size(); ++index) {
        if (index == 0 && (frame[14] == 0x50 || frame[14] == 0xd0)) {
            continue;
        }
        if (index == 3 && (frame[17] == 0 || frame[17] == 0x10)) {
            continue;
        }
        if (frame[14 + index] != body[index]) {
            return false;
        }
    }
    error.sequence = frame[13];
    error.resultCode = 3;
    return true;
}

// Only meaningful inside an explicitly reserved, fresh-idle zero anchor.
// Result 3 remains an error for every ordinary actuator command.
inline bool isHtv145IdleAnchorResponse(
    const std::array<std::uint8_t, kFrameBytes>& frame,
    const Htv145Link& link
) {
    Htv145CommandResponse response{};
    Htv145CommandError error{};
    if (frame[13] != 0x80 || frame[14] != 0x50) return false;
    return (decodeHtv145CommandResponse(frame, link, response) && !response.watering)
        || (decodeHtv145CommandError(frame, link, error) && frame[17] == 0x10);
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
        !validHtv145Sequence(frame[13]) || frame[15] != 0x07 ||
        (frame[16] != 0x82 && frame[16] != 0x85 && frame[16] != 0x86) ||
        (frame[14] != 0x01 && frame[14] != 0x81) ||
        (frame[20] & 0x7fU) != 0x4f || frame[25] != 0x40 ||
        frame[28] != 0x56) {
        return false;
    }
    watering = (frame[20] & 0x80U) != 0;
    return true;
}

// Timing candidate from the ten stock report/ACK exchanges: 67--84 ms
// sync-to-sync, including the 15.2 ms report and 16 ms ACK wake.
constexpr std::uint16_t kHtv145ReportAckWakeSymbols = 320;
constexpr std::uint32_t kHtv145ReportAckDelayUs = 40'000;

inline bool buildHtv145ReportAck(
    const std::array<std::uint8_t, kFrameBytes>& report,
    const Htv145Link& link,
    std::uint16_t residue,
    std::array<std::uint8_t, kFrameBytes>& reply
) {
    bool watering = false;
    const bool state = decodeHtv145StateReport(report, link, watering);
    bool summary = hasSync(report) && hasOrdinaryTrailer(report) &&
        htv145RouteMatches(report, link.valveEndpoint, link.controllerEndpoint) &&
        validHtv145Sequence(report[13]) &&
        (report[14] == 0x02 || report[14] == 0x82) && report[15] == 0x07 &&
        (report[16] == 0x82 || report[16] == 0x85 || report[16] == 0x86) &&
        (report[17] == 0 || report[17] == 0x80) && report[18] == 0x80 &&
        (report[23] == 0x08 || report[23] == 0x10) &&
        !(report[26] & 0x7fU) && report[27] == 0;
    const std::uint16_t elapsed = static_cast<std::uint16_t>(report[28]) |
        (static_cast<std::uint16_t>(report[29]) << 8U);
    const std::uint32_t elapsedSeconds = (elapsed & 0x7fffU) * 2U + ((elapsed & 0x8000U) != 0);
    summary = summary && elapsedSeconds > 0 && elapsedSeconds <= 86'400;
    for (std::size_t i = 30; i < 36; ++i) {
        summary = summary && report[i] == 0;
    }
    if ((!state && !summary) || (residue != 0x4f03 && residue != 0xc713)) {
        return false;
    }
    reply.fill(0);
    std::copy(kSync.begin(), kSync.end(), reply.begin());
    std::copy(link.controllerEndpoint.begin(), link.controllerEndpoint.end(), reply.begin() + 5);
    std::copy(link.valveEndpoint.begin(), link.valveEndpoint.end(), reply.begin() + 9);
    reply[13] = report[13];
    reply[14] = report[14] | 0x40;
    reply[15] = state ? 1 : 0;
    reply[16] = state ? 0 : 0x80;
    reply[17] = state ? 1 : 0;
    writeTrailer(reply, residue);
    return true;
}

}  // namespace rainpoint
