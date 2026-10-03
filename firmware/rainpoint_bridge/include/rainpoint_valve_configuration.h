#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "rainpoint_protocol.h"

namespace rainpoint::valveConfiguration {

// Request-driven configuration, separate from fresh enrollment and master
// commands. No radio, counter generator, identity defaults or startup actions.
// Not dispatched by production firmware until per-model RF qualification.
enum class Model { Unknown, Htv145, Htv213, Htv405 };

constexpr std::size_t portCount(Model model) {
    switch (model) {
        case Model::Unknown: return 0;
        case Model::Htv145: return 1;
        case Model::Htv213: return 2;
        case Model::Htv405: return 4;
    }
    return 0;
}

struct PortConfiguration {
    // These are stored model-specific settings, NOT duration or battery units.
    std::array<std::uint8_t, 14> settings{};
    bool settingsKnown = false;
    // Unknown plans must never be silently erased by an empty-page reply.
    bool emptyPlanKnown = false;
};

struct Association {
    Model model = Model::Unknown;
    // Exact normalized request routes, including their direction/header bits.
    std::array<std::uint8_t, 4> requestRouteA{};
    std::array<std::uint8_t, 4> requestRouteB{};
    std::array<std::uint8_t, 4> factoryEndpoint{};
    std::uint8_t address = 0; // Persisted device slot, NEVER port count.
    std::uint16_t timingRaw = 0;
    bool timingKnown = false;
    std::uint8_t selector = 0;
    std::uint8_t configurationRevision = 0;
    std::array<PortConfiguration, 4> ports{};
};

struct ReportContext {
    // Caller provides current, qualified wire values only when requested.
    // Never substitute the clock/unit bytes from a historical capture.
    std::array<std::uint8_t, 5> time{};
    std::array<std::uint8_t, 2> units{};
    bool timeKnown = false;
    bool unitsKnown = false;
};

struct Reply {
    std::uint8_t command = 0;
    std::uint8_t phase = 0;
    std::uint8_t port = 0;
    std::uint8_t length = 0;
    // For 81 only: respond on the announcement's qualified selector, while
    // its body retains association.selector for subsequent routine traffic.
    std::uint8_t assignmentReplySelector = 0;
    std::array<std::uint8_t, 20> data{};
};

enum class Result {
    Ready, InvalidAssociation, InvalidFrame, WrongAssociation,
    UnsupportedRequest, InvalidRequest, MissingConfiguration, MissingContext
};

enum class NotificationKind : std::uint8_t { ConfigurationChanged = 0, Startup = 1 };

// Explicit experiment/building primitive, NOT a counter-reset instruction.
// The caller owns allocation/persistence of the independent master phase.
inline bool prepareNotification(std::uint8_t revision, std::uint8_t masterPhase,
                                NotificationKind kind, Reply& reply) {
    reply = {};
    if (revision == 0 || masterPhase > 63 ||
        (kind != NotificationKind::ConfigurationChanged &&
         kind != NotificationKind::Startup)) return false;
    reply.command = 0x20;
    reply.phase = masterPhase;
    reply.length = 2;
    reply.data[0] = revision;
    reply.data[1] = static_cast<std::uint8_t>(kind);
    return true;
}

inline bool nonzero(const std::array<std::uint8_t, 4>& route) {
    return route != std::array<std::uint8_t, 4>{};
}

// Native time serialization from stock 4203B294. Not the one-bit-shifted
// normalized pairing overlays. Weekday is Sunday=0 .. Saturday=6.
inline bool encodeNativeTime(unsigned year, unsigned month, unsigned day,
                             unsigned hour, unsigned minute, unsigned second,
                             unsigned weekday, ReportContext& context) {
    context.timeKnown = false;
    context.time = {};
    constexpr unsigned days[] = {31,28,31,30,31,30,31,31,30,31,30,31};
    if (year < 2020 || year > 2083 || month < 1 || month > 12 ||
        hour > 23 || minute > 59 || second > 59 || weekday > 6) return false;
    const bool leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
    if (day < 1 || day > days[month - 1] + (month == 2 && leap ? 1U : 0U)) return false;
    const std::uint32_t packed = second | (minute << 6U) | (hour << 12U) |
        (day << 17U) | (month << 22U) | ((year - 2020) << 26U);
    for (unsigned i = 0; i < 4; ++i) context.time[i] = (packed >> (8U * i)) & 255U;
    context.time[4] = weekday;
    context.timeKnown = true;
    return true;
}

// Qualified body shape for the captured HTV213 retained announcement only.
// Still not a live radio profile: physical timing/carrier and owner approval
// are external. Other models keep their proven fresh enrollment untouched.
inline Result prepareRetainedAssignment(
    const Association& association,
    const std::array<std::uint8_t, kFrameBytes>& frame,
    const ReportContext& context, Reply& reply
) {
    reply = {};
    if (association.model != Model::Htv213) return Result::UnsupportedRequest;
    if (!nonzero(association.factoryEndpoint) || (association.factoryEndpoint[0] & 128U) ||
        !nonzero(association.requestRouteA) || !nonzero(association.requestRouteB) ||
        association.requestRouteA == association.requestRouteB ||
        association.address == 0 || association.configurationRevision == 0 ||
        association.selector == 0 || association.selector > 15 || !association.timingKnown)
        return Result::InvalidAssociation;
    for (std::size_t i = 0; i < 4; ++i) {
        const auto pairedByte = static_cast<std::uint8_t>(association.factoryEndpoint[i] | (i == 0 ? 128U : 0U));
        if (association.requestRouteB[i] != pairedByte) return Result::InvalidAssociation;
    }
    if (!hasSync(frame) || !hasOrdinaryTrailer(frame)) return Result::InvalidFrame;
    const std::array<std::uint8_t, 4> broadcast{{0x80,0,0,0}};
    for (std::size_t i = 0; i < 4; ++i) {
        if (frame[5+i] != broadcast[i] || frame[9+i] != association.factoryEndpoint[i])
            return Result::WrongAssociation;
    }
    std::array<std::uint8_t, 32> native{};
    for (std::size_t i = 0; i < native.size(); ++i)
        native[i] = static_cast<std::uint8_t>((frame[i+4] << 1U) | (frame[i+5] >> 7U));
    if ((native[9] & 0x40U) || native[10] != 1 || (native[11] & 31U) != 8)
        return Result::UnsupportedRequest;
    const std::array<std::uint8_t, 7> retained{{0xff,0x20,0x05,0x01,0x04,0x3e,0x03}};
    for (std::size_t i = 0; i < retained.size(); ++i)
        if (native[13+i] != retained[i]) return Result::UnsupportedRequest;
    if (native[12] == 0 || native[12] > 15) return Result::UnsupportedRequest;
    if (!context.timeKnown) return Result::MissingContext;
    reply.command = 0x81;
    reply.phase = nativeSequence(frame);
    reply.length = 11;
    reply.assignmentReplySelector = native[12];
    reply.data[0] = 0; // Known-association success, not fresh-admission 0x0a.
    reply.data[1] = association.address;
    reply.data[2] = association.selector;
    reply.data[3] = association.timingRaw & 255U;
    reply.data[4] = association.timingRaw >> 8U;
    for (std::size_t i = 0; i < 5; ++i) reply.data[5+i] = context.time[i];
    reply.data[10] = association.configurationRevision;
    return Result::Ready;
}

// Reply data only: the existing model-specific transport retains ownership of
// timing, carrier, normalized routing, physical tail and bounded TX policy.
// Ready means a reply can be prepared, never that the valve received it.
inline Result prepareReply(
    const Association& association,
    const std::array<std::uint8_t, kFrameBytes>& frame,
    const ReportContext& context,
    Reply& reply
) {
    reply = {};
    if (portCount(association.model) == 0 ||
        !nonzero(association.requestRouteA) ||
        !nonzero(association.requestRouteB) ||
        association.requestRouteA == association.requestRouteB ||
        association.selector == 0 || association.selector > 15 ||
        association.configurationRevision == 0) {
        return Result::InvalidAssociation;
    }
    if (!hasSync(frame) || !hasOrdinaryTrailer(frame)) {
        return Result::InvalidFrame;
    }
    for (std::size_t index = 0; index < 4; ++index) {
        if (frame[5 + index] != association.requestRouteA[index] ||
            frame[9 + index] != association.requestRouteB[index]) {
            return Result::WrongAssociation;
        }
    }
    std::array<std::uint8_t, 32> native{};
    for (std::size_t index = 0; index < native.size(); ++index) {
        native[index] = static_cast<std::uint8_t>(
            (frame[index + 4] << 1U) | (frame[index + 5] >> 7U));
    }
    const auto command = native[10];
    const auto length = static_cast<std::uint8_t>(native[11] & 31U);
    if (native[0] != 0x51 || length > 20) return Result::InvalidFrame;
    if (command != 2 && command != 5 && command != 6) {
        // Factory 01/81 and unsolicited 20/A0 are deliberately not handled.
        return Result::UnsupportedRequest;
    }
    if ((command == 2 && length != 15) ||
        (command == 5 && length != 2) ||
        (command == 6 && length != 3)) return Result::InvalidRequest;
    const auto port = native[command == 2 ? 14 : 13];
    if (native[12] != association.selector ||
        port == 0 || port > portCount(association.model)) {
        return Result::InvalidRequest;
    }
    Reply candidate{};
    candidate.command = static_cast<std::uint8_t>(command | 0x80U);
    candidate.phase = nativeSequence(frame); // Echo ALL six bits, no advance.
    candidate.port = port;
    candidate.length = 1; // Result zero; extra fields are request-dependent.
    const auto& configuration = association.ports[port - 1];
    if (command == 2) {
        const auto flags = native[13];
        if ((flags & 4U) && !context.timeKnown) return Result::MissingContext;
        if ((flags & 128U) && !context.unitsKnown) return Result::MissingContext;
        if (flags & 2U) candidate.data[candidate.length++] = association.configurationRevision;
        if (flags & 4U) {
            for (auto value : context.time) candidate.data[candidate.length++] = value;
        }
        if (flags & 128U) {
            for (auto value : context.units) candidate.data[candidate.length++] = value;
        }
    } else if (command == 5) {
        if (!configuration.settingsKnown) return Result::MissingConfiguration;
        for (auto value : configuration.settings) candidate.data[candidate.length++] = value;
    } else {
        // Only the captured empty page-zero branch is qualified offline.
        if (native[14] != 0) return Result::UnsupportedRequest;
        if (!configuration.emptyPlanKnown) return Result::MissingConfiguration;
    }
    reply = candidate;
    return Result::Ready;
}

} // namespace rainpoint::valveConfiguration
