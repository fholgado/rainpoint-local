#pragma once

#include <array>
#include <cstdint>

#include "rainpoint_protocol.h"

namespace rainpoint {

struct Htv405ValveLink {
    std::array<std::uint8_t, 4> controllerEndpoint{};
    std::array<std::uint8_t, 4> valveEndpoint{};
};

struct Htv405GatewayControlLink {
    std::array<std::uint8_t, 4> pairedEndpoint{};
    std::array<std::uint8_t, 4> companionEndpoint{};
};

struct Htv405Phase {
    std::uint8_t sequence;
    bool repeat;
};

struct Htv405GatewayCommandResponse {
    std::uint8_t sequence;
    std::uint8_t zone;
    bool watering;
};

struct Htv405GatewayCommandRejection {
    std::uint8_t sequence;
};

struct Htv405StateReport {
    std::uint8_t zone;
    bool watering;
};

inline bool validHtv405ValveLink(const Htv405ValveLink& link) {
    return link.controllerEndpoint != std::array<std::uint8_t, 4>{} &&
        link.valveEndpoint != std::array<std::uint8_t, 4>{} &&
        link.controllerEndpoint != link.valveEndpoint;
}

inline bool validHtv405GatewayControlLink(
    const Htv405GatewayControlLink& link
) {
    return link.pairedEndpoint != std::array<std::uint8_t, 4>{} &&
        link.companionEndpoint != std::array<std::uint8_t, 4>{} &&
        link.pairedEndpoint != link.companionEndpoint;
}

inline bool buildHtv405GatewayOpenFrame(
    const Htv405GatewayControlLink& link,
    Htv405Phase phase,
    std::uint8_t zone,
    std::uint8_t associationSelector,
    std::uint16_t durationSeconds,
    std::uint16_t trailerResidual,
    std::array<std::uint8_t, kFrameBytes>& frame
) {
    // This builder is compiled only into supervised prototype firmware.
    // Bounded opens use whole-minute durations; one- and two-minute physical
    // runs have authenticated response, matching state-report, and
    // automatic-idle evidence, while longer encodings are protocol-tested.
    if (!validHtv405GatewayControlLink(link) || phase.sequence > 0x1f ||
        zone < 1 || zone > 4 ||
        (associationSelector != 0x05 && associationSelector != 0x85) ||
        durationSeconds < 60 || durationSeconds > 3'600 ||
        (durationSeconds % 2U) != 0 ||
        trailerResidual != 0x4f03) {
        return false;
    }

    frame.fill(0);
    for (std::size_t index = 0; index < kSync.size(); ++index) {
        frame[index] = kSync[index];
    }
    for (std::size_t index = 0; index < 4; ++index) {
        frame[5 + index] = link.pairedEndpoint[index];
        frame[9 + index] = link.companionEndpoint[index];
    }

    // HTV405 stores the duration as a two-byte, two-second counter biased by
    // 0x80. This must be addition, not a bitwise OR: a 900-second request has
    // units 0x01c2 and must encode as 0x0242. The former OR encoding produced
    // 0x01c2, which the valve physically bounded to 644 seconds.
    const std::uint16_t encodedDuration = static_cast<std::uint16_t>(
        durationSeconds / 2U + 0x80U
    );
    frame[13] = static_cast<std::uint8_t>(0x80U | phase.sequence);
    // Gateway control byte 14 is the operation marker, not the
    // primary/repeat bit used by lower-channel valve reports.
    frame[14] = 0x90;
    frame[15] = 0x82;
    frame[16] = 0x80;
    // Both physically accepted stock commands use the selector-2 gateway
    // command marker 0x81 even when the resulting valve state is reported on
    // the selector-6 association branch. Do not substitute the state-report
    // selector here; the command marker belongs to the gateway envelope.
    frame[17] = static_cast<std::uint8_t>(0x80U | zone);
    frame[19] = static_cast<std::uint8_t>(encodedDuration & 0xffU);
    frame[20] = static_cast<std::uint8_t>(encodedDuration >> 8U);
    writeTrailer(frame, trailerResidual);
    return true;
}

inline bool buildHtv405GatewayCloseFrame(
    const Htv405GatewayControlLink& link,
    Htv405Phase phase,
    std::uint8_t zone,
    std::uint8_t associationSelector,
    std::uint16_t trailerResidual,
    std::array<std::uint8_t, kFrameBytes>& frame
) {
    if (!validHtv405GatewayControlLink(link) || phase.sequence > 0x1f ||
        zone < 1 || zone > 4 ||
        (associationSelector != 0x05 && associationSelector != 0x85) ||
        trailerResidual != 0x4f03) {
        return false;
    }

    frame.fill(0);
    for (std::size_t index = 0; index < kSync.size(); ++index) {
        frame[index] = kSync[index];
    }
    for (std::size_t index = 0; index < 4; ++index) {
        frame[5 + index] = link.pairedEndpoint[index];
        frame[9 + index] = link.companionEndpoint[index];
    }

    frame[13] = static_cast<std::uint8_t>(0x80U | phase.sequence);
    frame[14] = 0x10;
    frame[15] = 0x81;
    frame[16] = 0x80;
    frame[17] = static_cast<std::uint8_t>(0x80U | zone);
    writeTrailer(frame, trailerResidual);
    return true;
}

inline bool buildHtv405GatewayLinkAckFrame(
    const Htv405GatewayControlLink& link,
    Htv405Phase phase,
    std::uint16_t trailerResidual,
    std::array<std::uint8_t, kFrameBytes>& frame
) {
    if (!validHtv405GatewayControlLink(link) || phase.sequence > 0x1f ||
        trailerResidual != 0xc713) {
        return false;
    }

    frame.fill(0);
    for (std::size_t index = 0; index < kSync.size(); ++index) {
        frame[index] = kSync[index];
    }
    for (std::size_t index = 0; index < 4; ++index) {
        frame[5 + index] = link.pairedEndpoint[index];
        frame[9 + index] = link.companionEndpoint[index];
    }
    frame[13] = static_cast<std::uint8_t>(0x80U | phase.sequence);
    frame[14] = phase.repeat ? 0xc1 : 0x41;
    frame[15] = 0x01;
    frame[17] = 0x01;
    writeTrailer(frame, trailerResidual);
    return true;
}

inline bool isHtv405LinkFrame(
    const std::array<std::uint8_t, kFrameBytes>& frame
) {
    return hasSync(frame) && hasOrdinaryTrailer(frame) &&
        frame[15] == 0x07 && frame[16] == 0x82 &&
        ((frame[17] & 0x7fU) == 0x05 ||
         (frame[17] & 0x7fU) == 0x07) &&
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

inline bool decodeHtv405StateReport(
    const std::array<std::uint8_t, kFrameBytes>& frame,
    Htv405StateReport& report
) {
    if (!isHtv405LinkFrame(frame) || (frame[17] & 0x7fU) != 0x05) {
        return false;
    }
    const bool watering = (frame[20] & 0x80U) != 0;
    const auto localZone = static_cast<std::uint8_t>(
        (frame[19] & 0x70U) >> 4U
    );
    const bool directLocalLayout = frame[17] == 0x05 &&
        (frame[19] & 0x0fU) == 0 &&
        (watering || (frame[18] == 0x80 && frame[19] == 0x80));
    const auto zone = static_cast<std::uint8_t>(
        directLocalLayout
            ? localZone
            : (frame[18] & 0x7fU) * 2U +
                ((frame[19] & 0x80U) != 0 ? 1U : 0U)
    );
    if ((zone < 1 || zone > 4) && !(zone == 0 && !watering)) {
        return false;
    }
    report.zone = zone;
    report.watering = watering;
    return true;
}

inline bool decodeHtv405GatewayCommandResponse(
    const std::array<std::uint8_t, kFrameBytes>& frame,
    Htv405GatewayCommandResponse& response
) {
    // The valve answers accepted gateway commands on the command carrier.
    // Open and close responses share the 50/86 envelope; byte 17 contains a
    // one-hot-looking zone nibble (0x10..0x40), while the high bit of both
    // byte 14 and byte 18 reports the resulting watering state. Byte 16 has
    // varied across accepted captures, so it is deliberately excluded.
    if (!hasSync(frame) || !hasOrdinaryTrailer(frame) ||
        (frame[14] & 0x7fU) != 0x50 || frame[15] != 0x86 ||
        (frame[17] & 0x0fU) != 0 ||
        (frame[17] >> 4U) < 1 || (frame[17] >> 4U) > 4 ||
        (frame[18] & 0x7fU) != 0x4f ||
        frame[23] != 0x40 || frame[26] != 0x56 ||
        ((frame[14] ^ frame[18]) & 0x80U) != 0) {
        return false;
    }
    response.sequence = static_cast<std::uint8_t>(frame[13] & 0x1fU);
    response.zone = static_cast<std::uint8_t>(frame[17] >> 4U);
    response.watering = (frame[18] & 0x80U) != 0;
    return true;
}

inline bool decodeHtv405GatewayCommandRejection(
    const std::array<std::uint8_t, kFrameBytes>& frame,
    Htv405GatewayCommandRejection& rejection
) {
    // A syntactically valid command that the valve does not accept receives
    // this sequence-scoped d0/86/83/00 reply. Captures with both a stale
    // counter and an unsupported duration share this envelope, so it proves
    // only rejection (and therefore that watering did not begin), not why the
    // command was rejected.
    if (!hasSync(frame) || !hasOrdinaryTrailer(frame) ||
        frame[14] != 0xd0 || frame[15] != 0x86 || frame[16] != 0x83 ||
        frame[17] != 0x00 || frame[18] != 0x4f ||
        frame[23] != 0x40 || frame[26] != 0x56) {
        return false;
    }
    rejection.sequence = static_cast<std::uint8_t>(frame[13] & 0x1fU);
    return true;
}

inline std::uint8_t nextHtv405GatewayCommandSequence(
    std::uint8_t acceptedSequence,
    bool watering
) {
    // Stock early-stop captures show that the first accepted open advances
    // the watering-session counter, while a confirmed close leaves that next
    // session counter unchanged. Lower telemetry uses a separate counter.
    return watering
        ? static_cast<std::uint8_t>((acceptedSequence + 1U) & 0x1fU)
        : acceptedSequence;
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

inline bool buildHtv405OpenFrame(
    const Htv405ValveLink& link,
    Htv405Phase phase,
    std::uint8_t zone,
    std::uint8_t selector,
    std::uint16_t requestedDurationSeconds,
    std::uint16_t remainingDurationSeconds,
    std::uint16_t trailerResidual,
    std::array<std::uint8_t, kFrameBytes>& frame
) {
    if (!validHtv405ValveLink(link) || phase.sequence > 0x1f ||
        zone < 1 || zone > 4 ||
        (selector != 0x05 && selector != 0x85) ||
        requestedDurationSeconds == 0 ||
        requestedDurationSeconds > 254 ||
        remainingDurationSeconds > requestedDurationSeconds ||
        remainingDurationSeconds > 254 ||
        (requestedDurationSeconds % 2U) != 0 ||
        (remainingDurationSeconds % 2U) != 0 ||
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
    frame[19] = static_cast<std::uint8_t>(
        0x10U | (zone % 2U ? 0x80U : 0x00U)
    );
    frame[20] = 0xcf;
    frame[21] = 0x80;
    frame[25] = 0x40;
    frame[26] = static_cast<std::uint8_t>(
        0x80U | (remainingDurationSeconds / 2U)
    );
    frame[27] = 0x80;
    frame[28] = 0x56;
    frame[29] = static_cast<std::uint8_t>(
        0x80U | (requestedDurationSeconds / 2U)
    );
    writeTrailer(frame, trailerResidual);
    return true;
}

}  // namespace rainpoint
