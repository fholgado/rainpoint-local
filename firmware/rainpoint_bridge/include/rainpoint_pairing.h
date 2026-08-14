#pragma once

#include <array>
#include <cstdint>

#include "rainpoint_protocol.h"

namespace rainpoint {

enum class PairingTrigger : std::uint8_t {
    FactoryAnnouncement,
    PairedMessage1,
    PairedMessage2Data,
    PairedMessage2Short,
    PairedMessage3,
};

enum class PairingSessionState : std::uint8_t {
    Disarmed,
    Armed,
    Completed,
    Failed,
};

enum class PairingFailureReason : std::uint8_t {
    None,
    SessionTimeout,
    TerminalConfirmationTimeout,
    UnexpectedTrigger,
    ReplyFailed,
    ReplyDeadlineMissed,
};

struct PairingLocalDateTime {
    std::uint16_t year;
    std::uint8_t month;
    std::uint8_t day;
    std::uint8_t hour;
    std::uint8_t minute;
    std::uint8_t second;
};

struct PairingReplyStep {
    PairingTrigger trigger;
    std::uint32_t channelCenterHz;
    std::uint16_t wakeSymbols;
    std::uint16_t replyDeadlineMs;
    std::array<std::uint8_t, kFrameBytes> frame;
};

struct PairingProfile {
    const char* id;
    const char* model;
    const char* evidence;
    std::array<std::uint8_t, 4> factoryEndpoint;
    std::array<std::uint8_t, 4> pairedEndpoint;
    std::array<std::uint8_t, 4> sensorRoute;
    std::array<std::uint8_t, 4> companionEndpoint;
    std::uint16_t replyDelayMs;
    std::array<PairingReplyStep, 5> steps;
    std::uint8_t stepCount;
    PairingTrigger completionTrigger;
    bool completeAfterFinalReply;
};

constexpr std::uint32_t kPairingSymbolRate = 20'000;
constexpr std::uint16_t kPairingWakeSymbols = 320;
constexpr std::uint16_t kPairingReplyDelayMs = 60;
constexpr std::uint16_t kPairingReplyDeadlineMs = 250;
constexpr std::int32_t kMaxPairingFrequencyOffsetHz = 100'000;
constexpr std::uint16_t kCurrentPairingTrailerResidual = 0x4f03;
constexpr std::uint32_t kPairingChannelBaseHz = 433'031'500;
constexpr std::uint32_t kPairingChannelSpacingHz = 110'000;
constexpr std::uint8_t kInitialPairingChannel = 4;
constexpr const char* kAutomaticHcs026ProfileId = "hcs026_auto_v1";
constexpr bool validPairingLocalDateTime(const PairingLocalDateTime& value) {
    return value.year >= 2020 && value.year <= 2147 &&
        value.month >= 1 && value.month <= 12 &&
        value.day >= 1 && value.day <= 31 && value.hour <= 23 &&
        value.minute <= 59 && value.second <= 59;
}

constexpr bool pairingLeapYear(std::uint16_t year) {
    return year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
}

constexpr std::uint8_t pairingDaysInMonth(
    std::uint16_t year,
    std::uint8_t month
) {
    return month == 2 ? static_cast<std::uint8_t>(pairingLeapYear(year) ? 29 : 28)
        : month == 4 || month == 6 || month == 9 || month == 11 ? 30
        : 31;
}

inline bool advancePairingLocalDateTime(
    PairingLocalDateTime& value,
    std::uint32_t elapsedSeconds
) {
    if (!validPairingLocalDateTime(value) ||
        value.day > pairingDaysInMonth(value.year, value.month)) {
        return false;
    }
    std::uint32_t secondsOfDay =
        static_cast<std::uint32_t>(value.hour) * 3'600 +
        static_cast<std::uint32_t>(value.minute) * 60 + value.second +
        elapsedSeconds;
    std::uint32_t elapsedDays = secondsOfDay / 86'400;
    secondsOfDay %= 86'400;
    value.hour = static_cast<std::uint8_t>(secondsOfDay / 3'600);
    value.minute = static_cast<std::uint8_t>((secondsOfDay % 3'600) / 60);
    value.second = static_cast<std::uint8_t>(secondsOfDay % 60);
    while (elapsedDays-- > 0) {
        if (value.day < pairingDaysInMonth(value.year, value.month)) {
            ++value.day;
            continue;
        }
        value.day = 1;
        if (value.month < 12) {
            ++value.month;
            continue;
        }
        value.month = 1;
        if (value.year == 2147) {
            return false;
        }
        ++value.year;
    }
    return true;
}

inline bool applyPairingLocalDateTime(
    std::array<std::uint8_t, kFrameBytes>& frame,
    const PairingLocalDateTime& value
) {
    if (!validPairingLocalDateTime(value)) {
        return false;
    }
    // The initial gateway reply uses the FAT/DOS clock layout, except its
    // seven-bit year is relative to 2020 rather than 1980. Seconds have
    // two-second resolution. Bytes 21..24 were confirmed across successful
    // Sensor B enrollments on consecutive days.
    const std::uint16_t packedTime = static_cast<std::uint16_t>(
        (static_cast<std::uint16_t>(value.hour) << 11) |
        (static_cast<std::uint16_t>(value.minute) << 5) |
        (value.second / 2)
    );
    const std::uint16_t packedDate = static_cast<std::uint16_t>(
        (static_cast<std::uint16_t>(value.year - 2020) << 9) |
        (static_cast<std::uint16_t>(value.month) << 5) |
        value.day
    );
    frame[21] = static_cast<std::uint8_t>(packedTime & 0xff);
    frame[22] = static_cast<std::uint8_t>(packedTime >> 8);
    frame[23] = static_cast<std::uint8_t>(packedDate & 0xff);
    frame[24] = static_cast<std::uint8_t>(packedDate >> 8);
    writeTrailer(frame, kCurrentPairingTrailerResidual);
    return true;
}

constexpr bool validPairingPowerDbm(std::int8_t powerDbm) {
    return powerDbm == 0 || powerDbm == 5 || powerDbm == 7 || powerDbm == 10;
}

constexpr std::uint8_t pairingPaTableValue(std::int8_t powerDbm) {
    // TI CC1101 datasheet table for 433 MHz with multi-layer inductors.
    return powerDbm == 10 ? 0xc0
        : powerDbm == 7 ? 0xc8
        : powerDbm == 5 ? 0x84
        : 0x60;
}

constexpr std::size_t rainpointSymbolCount(std::uint16_t wakeSymbols) {
    return wakeSymbols + kFrameBytes * 8;
}

inline std::uint8_t rainpointSymbol(
    const std::array<std::uint8_t, kFrameBytes>& frame,
    std::uint16_t wakeSymbols,
    std::size_t index,
    bool invert = false
) {
    std::uint8_t value;
    if (index < wakeSymbols) {
        // Stock gateway captures start the alternating wake low. The frame
        // that follows retains its ordinary, non-inverted bit polarity.
        value = static_cast<std::uint8_t>(index & 1U);
    } else {
        const std::size_t frameIndex = index - wakeSymbols;
        value = (frame[frameIndex / 8] >> (7 - frameIndex % 8)) & 1U;
    }
    return invert ? value ^ 1U : value;
}

constexpr PairingProfile kValidatedHcs026Profile = {
    "hcs026_15a98024_v1",
    "HCS026FRF",
    "isolated local enrollment confirmed 2026-08-11",
    {{0x15, 0xa9, 0x80, 0x24}},
    {{0x95, 0xa9, 0x80, 0x24}},
    {{0xb9, 0x84, 0x02, 0x80}},
    {{0x39, 0x84, 0x02, 0x80}},
    kPairingReplyDelayMs,
    {{
    {
        PairingTrigger::FactoryAnnouncement,
        433'471'500,
        kPairingWakeSymbols,
        kPairingReplyDeadlineMs,
        {{0x79, 0xf4, 0x88, 0x2f, 0x28, 0x95, 0xa9, 0x80, 0x24, 0x39,
          0x84, 0x02, 0x80, 0x81, 0x40, 0x88, 0x05, 0x03, 0x82, 0x70,
          0x00, 0xfc, 0x76, 0x0b, 0x0d, 0x01, 0x00, 0x80, 0x00, 0x00,
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x30, 0xc3}},
    },
    {
        PairingTrigger::PairedMessage1,
        433'471'500,
        kPairingWakeSymbols,
        kPairingReplyDeadlineMs,
        {{0x79, 0xf4, 0x88, 0x2f, 0x28, 0x95, 0xa9, 0x80, 0x24, 0x39,
          0x84, 0x02, 0x80, 0x81, 0xc1, 0x82, 0x00, 0x00, 0x9f, 0x80,
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x77, 0xdc}},
    },
    {
        PairingTrigger::PairedMessage2Data,
        433'471'500,
        kPairingWakeSymbols,
        kPairingReplyDeadlineMs,
        {{0x79, 0xf4, 0x88, 0x2f, 0x28, 0x95, 0xa9, 0x80, 0x24, 0x39,
          0x84, 0x02, 0x80, 0x82, 0x41, 0x81, 0x00, 0x01, 0x00, 0x00,
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x36, 0x22}},
    },
    }},
    3,
    PairingTrigger::PairedMessage3,
    false,
};

// Identity-specific Sensor A mixed-state profile. Every transmitted byte and
// channel below comes from controlled stock enrollment captures. The profile
// emits the
// first-enrollment request sequence through the data message, followed by the
// rejoin short-message form. Replies 1..3 therefore come from the captured
// first enrollment and reply 4 from the captured rejoin. Terminal message 03
// is required afterward; no uncaptured response is synthesized.
constexpr PairingProfile kSensorAHcs026CandidateProfile = {
    "hcs026_1bce0024_candidate_v1",
    "HCS026FRF",
    "controlled successful local enrollment captured 2026-08-12",
    {{0x1b, 0xce, 0x00, 0x24}},
    {{0x9b, 0xce, 0x00, 0x24}},
    {{0xb9, 0x84, 0x02, 0x80}},
    {{0x39, 0x84, 0x02, 0x80}},
    10,
    {{
    {
        PairingTrigger::FactoryAnnouncement,
        433'471'484,
        kPairingWakeSymbols,
        kPairingReplyDeadlineMs,
        {{0x79, 0xf4, 0x88, 0x2f, 0x28, 0x9b, 0xce, 0x00, 0x24, 0x39,
          0x84, 0x02, 0x80, 0x81, 0x40, 0x88, 0x05, 0x03, 0x04, 0xf0,
          0x00, 0xad, 0xf1, 0x8a, 0x0d, 0x00, 0x80, 0x80, 0x00, 0x00,
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x4c, 0x41}},
    },
    {
        PairingTrigger::PairedMessage1,
        434'021'457,
        kPairingWakeSymbols,
        kPairingReplyDeadlineMs,
        {{0x79, 0xf4, 0x88, 0x2f, 0x28, 0x9b, 0xce, 0x00, 0x24, 0x39,
          0x84, 0x02, 0x80, 0x81, 0xc1, 0x82, 0x00, 0x00, 0x9f, 0x80,
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x3d, 0x14}},
    },
    {
        PairingTrigger::PairedMessage2Data,
        434'021'457,
        kPairingWakeSymbols,
        kPairingReplyDeadlineMs,
        {{0x79, 0xf4, 0x88, 0x2f, 0x28, 0x9b, 0xce, 0x00, 0x24, 0x39,
          0x84, 0x02, 0x80, 0x82, 0x41, 0x81, 0x00, 0x01, 0x00, 0x00,
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x7c, 0xea}},
    },
    {
        PairingTrigger::PairedMessage2Short,
        434'021'457,
        kPairingWakeSymbols,
        kPairingReplyDeadlineMs,
        {{0x79, 0xf4, 0x88, 0x2f, 0x28, 0x9b, 0xce, 0x00, 0x24, 0x39,
          0x84, 0x02, 0x80, 0x82, 0xc1, 0x81, 0x00, 0x01, 0x00, 0x00,
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x4e, 0x6f}},
    },
    }},
    4,
    PairingTrigger::PairedMessage3,
    false,
};

inline const char* pairingTriggerName(PairingTrigger trigger) {
    switch (trigger) {
        case PairingTrigger::FactoryAnnouncement:
            return "factory_announcement";
        case PairingTrigger::PairedMessage1:
            return "paired_message_1";
        case PairingTrigger::PairedMessage2Data:
            return "paired_message_2_data";
        case PairingTrigger::PairedMessage2Short:
            return "paired_message_2_short";
        case PairingTrigger::PairedMessage3:
            return "paired_message_3";
    }
    return "unknown";
}

inline bool validPairingProfile(const PairingProfile& profile) {
    if (profile.stepCount == 0 || profile.stepCount > profile.steps.size()) {
        return false;
    }
    if (profile.replyDelayMs > profile.steps[0].replyDeadlineMs) {
        return false;
    }
    for (std::size_t stepIndex = 0;
         stepIndex < profile.stepCount;
         ++stepIndex) {
        const auto& step = profile.steps[stepIndex];
        if (!hasSync(step.frame) || !hasOrdinaryTrailer(step.frame) ||
            step.wakeSymbols != kPairingWakeSymbols ||
            step.replyDeadlineMs != kPairingReplyDeadlineMs) {
            return false;
        }
        for (std::size_t index = 0; index < profile.pairedEndpoint.size(); ++index) {
            if (step.frame[index + 5] != profile.pairedEndpoint[index] ||
                step.frame[index + 9] != profile.companionEndpoint[index]) {
                return false;
            }
        }
    }
    return true;
}

constexpr std::uint32_t pairingChannelCenterHz(std::uint8_t channel) {
    return kPairingChannelBaseHz +
        static_cast<std::uint32_t>(channel) * kPairingChannelSpacingHz;
}

constexpr std::uint8_t pairingChannelFromReply(
    const std::array<std::uint8_t, kFrameBytes>& frame
) {
    return static_cast<std::uint8_t>(
        2 * (frame[18] & 0x7fU) + ((frame[19] & 0x80U) ? 1 : 0)
    );
}

constexpr std::uint8_t pairingChannelFromSensor(
    const std::array<std::uint8_t, kFrameBytes>& frame
) {
    return static_cast<std::uint8_t>(
        2 * frame[16] + ((frame[17] & 0x80U) ? 1 : 0)
    );
}

inline bool assignPairingChannel(
    PairingProfile& profile,
    std::uint8_t channel
) {
    // Four controlled exchanges show reply 1 assigning this selector and the
    // sensor echoing it in its following message 01. This experimental writer
    // is intentionally restricted to selectors physically validated for local
    // reassignment; the full selector domain and reuse rules are still unknown.
    if ((channel != 4 && channel != 5) || profile.stepCount == 0) {
        return false;
    }
    auto& initial = profile.steps[0];
    initial.channelCenterHz = pairingChannelCenterHz(kInitialPairingChannel);
    initial.frame[18] = static_cast<std::uint8_t>(
        channel / 2U | ((channel & 1U) == 0 ? 0x80U : 0x00U)
    );
    initial.frame[19] = static_cast<std::uint8_t>(
        0x70U | ((channel & 1U) != 0 ? 0x80U : 0x00U)
    );
    writeTrailer(initial.frame, kCurrentPairingTrailerResidual);
    for (std::size_t index = 1; index < profile.stepCount; ++index) {
        profile.steps[index].channelCenterHz = pairingChannelCenterHz(channel);
    }
    return validPairingProfile(profile);
}

inline bool hcs026FactoryAnnouncement(
    const std::array<std::uint8_t, kFrameBytes>& frame,
    std::array<std::uint8_t, 4>& factoryEndpoint
) {
    constexpr std::array<std::uint8_t, 4> factoryRoute = {
        0x80, 0x00, 0x00, 0x00,
    };
    // Both independently captured HCS026 identities share this factory
    // announcement signature. Keep the automatic adopter model-bounded so a
    // different RainPoint product cannot be enrolled merely because it uses
    // the same factory route and message number.
    constexpr std::array<std::uint8_t, 7> hcs026SignatureTail = {
        0x00, 0x83, 0x82, 0x7f, 0xa4, 0x1e, 0x80,
    };
    if (!hasSync(frame) || !hasOrdinaryTrailer(frame)) {
        return false;
    }
    for (std::size_t index = 0; index < factoryRoute.size(); ++index) {
        if (frame[5 + index] != factoryRoute[index]) {
            return false;
        }
    }
    // A long press repeats the same factory announcement with message counters
    // 1, 2, and 4. Automatic rejoin can only arm after the first copy has
    // reached the gateway, so accept the otherwise byte-identical retries.
    const std::uint8_t message = frame[13] & 0x7fU;
    if (message != 1 && message != 2 && message != 4) {
        return false;
    }
    for (std::size_t index = 0; index < hcs026SignatureTail.size(); ++index) {
        if (frame[14 + index] != hcs026SignatureTail[index]) {
            return false;
        }
    }
    // Captured unpaired HCS026 endpoints have a clear association bit and the
    // product suffix 0x24. These checks are deliberately narrower than the
    // ordinary receive decoder because this path authorizes transmission.
    if ((frame[9] & 0x80U) != 0 || frame[12] != 0x24) {
        return false;
    }
    for (std::size_t index = 0; index < factoryEndpoint.size(); ++index) {
        factoryEndpoint[index] = frame[9 + index];
    }
    return true;
}

inline bool buildAutomaticHcs026Profile(
    const std::array<std::uint8_t, 4>& factoryEndpoint,
    std::uint8_t channel,
    PairingProfile& profile
) {
    if ((factoryEndpoint[0] & 0x80U) != 0 || factoryEndpoint[3] != 0x24) {
        return false;
    }
    // The common first-enrollment branch is byte-identical across the two
    // stock captures after identity, clock, selector, and trailer substitution.
    // Start with the physically validated Sensor A profile and replace its
    // rejoin-only fourth reply with the common first-enrollment short reply.
    profile = kSensorAHcs026CandidateProfile;
    profile.id = kAutomaticHcs026ProfileId;
    profile.evidence =
        "two-identity common HCS026 first-enrollment template; physical auto-adoption pending";
    profile.replyDelayMs = 10;
    profile.factoryEndpoint = factoryEndpoint;
    profile.pairedEndpoint = factoryEndpoint;
    profile.pairedEndpoint[0] |= 0x80U;
    profile.steps[3].frame = {{
        0x79, 0xf4, 0x88, 0x2f, 0x28, 0x9b, 0xce, 0x00, 0x24, 0x39,
        0x84, 0x02, 0x80, 0x82, 0xc2, 0x81, 0x00, 0x00, 0x80, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x49, 0x17,
    }};
    for (std::size_t stepIndex = 0; stepIndex < profile.stepCount; ++stepIndex) {
        auto& frame = profile.steps[stepIndex].frame;
        for (std::size_t index = 0; index < profile.pairedEndpoint.size(); ++index) {
            frame[5 + index] = profile.pairedEndpoint[index];
        }
        writeTrailer(frame, kCurrentPairingTrailerResidual);
    }
    return assignPairingChannel(profile, channel);
}

inline bool endpointEquals(
    const std::array<std::uint8_t, kFrameBytes>& frame,
    std::size_t offset,
    const std::array<std::uint8_t, 4>& endpoint
) {
    for (std::size_t index = 0; index < endpoint.size(); ++index) {
        if (frame[offset + index] != endpoint[index]) {
            return false;
        }
    }
    return true;
}

inline bool pairingTrigger(
    const std::array<std::uint8_t, kFrameBytes>& frame,
    const PairingProfile& profile,
    PairingTrigger& trigger
) {
    if (!hasSync(frame) || !hasOrdinaryTrailer(frame)) {
        return false;
    }
    const std::uint8_t message = frame[13] & 0x7f;
    std::array<std::uint8_t, 4> announcedFactory{};
    if (hcs026FactoryAnnouncement(frame, announcedFactory) &&
        announcedFactory == profile.factoryEndpoint) {
        trigger = PairingTrigger::FactoryAnnouncement;
        return true;
    }
    if (!endpointEquals(frame, 5, profile.sensorRoute) ||
        !endpointEquals(frame, 9, profile.pairedEndpoint)) {
        return false;
    }
    if (message == 1) {
        trigger = PairingTrigger::PairedMessage1;
        return true;
    }
    if (message == 2 && frame[14] == 0x01) {
        trigger = PairingTrigger::PairedMessage2Data;
        return true;
    }
    // Controlled captures show two HCS026 short-message encodings here:
    // Sensor A uses 0x81 while Sensor B uses 0x82. Both occur after the data
    // form (0x01) and represent the same pairing trigger.
    if (message == 2 && (frame[14] == 0x81 || frame[14] == 0x82)) {
        trigger = PairingTrigger::PairedMessage2Short;
        return true;
    }
    if (message == 3) {
        trigger = PairingTrigger::PairedMessage3;
        return true;
    }
    return false;
}

class PairingSession {
public:
    explicit PairingSession(const PairingProfile& profile) : profile_(profile) {}

    void arm(std::uint32_t nowMs, std::uint32_t durationMs = 120'000) {
        state_ = PairingSessionState::Armed;
        step_ = 0;
        expiresAtMs_ = nowMs + durationMs;
        pending_ = false;
        failureReason_ = PairingFailureReason::None;
    }

    void cancel() {
        state_ = PairingSessionState::Disarmed;
        step_ = 0;
        pending_ = false;
        failureReason_ = PairingFailureReason::None;
    }

    void tick(std::uint32_t nowMs) {
        if (state_ == PairingSessionState::Armed &&
            static_cast<std::int32_t>(nowMs - expiresAtMs_) >= 0) {
            fail(
                step_ == profile_.stepCount
                    ? PairingFailureReason::TerminalConfirmationTimeout
                    : PairingFailureReason::SessionTimeout
            );
        }
    }

    const PairingReplyStep* claimReply(
        const std::array<std::uint8_t, kFrameBytes>& frame,
        std::uint32_t nowMs
    ) {
        tick(nowMs);
        if (state_ != PairingSessionState::Armed || pending_) {
            return nullptr;
        }
        PairingTrigger observed;
        if (!pairingTrigger(frame, profile_, observed)) {
            return nullptr;
        }
        if (step_ == profile_.stepCount) {
            if (observed == profile_.completionTrigger) {
                state_ = PairingSessionState::Completed;
                return nullptr;
            }
            // Stock enrollment emits this short message between the final
            // gateway reply and terminal message 03. It requires no reply.
            if (observed == PairingTrigger::PairedMessage2Short) {
                return nullptr;
            }
            for (std::size_t index = 0;
                 index < profile_.stepCount;
                 ++index) {
                const auto& step = profile_.steps[index];
                if (step.trigger == observed) {
                    return nullptr;
                }
            }
            fail(PairingFailureReason::UnexpectedTrigger);
            return nullptr;
        }
        const PairingTrigger expected = profile_.steps[step_].trigger;
        if (observed == expected) {
            pending_ = true;
            claimedAtMs_ = nowMs;
            return &profile_.steps[step_];
        }
        for (std::size_t index = 0; index < step_; ++index) {
            if (profile_.steps[index].trigger == observed) {
                return nullptr;
            }
        }
        fail(PairingFailureReason::UnexpectedTrigger);
        return nullptr;
    }

    bool finishReply(bool success, std::uint32_t nowMs) {
        if (state_ != PairingSessionState::Armed || !pending_ || !success) {
            fail(PairingFailureReason::ReplyFailed);
            return false;
        }
        if (nowMs - claimedAtMs_ >
            profile_.steps[step_].replyDeadlineMs) {
            fail(PairingFailureReason::ReplyDeadlineMissed);
            return false;
        }
        pending_ = false;
        ++step_;
        if (step_ == profile_.stepCount &&
            profile_.completeAfterFinalReply) {
            state_ = PairingSessionState::Completed;
        }
        return true;
    }

    PairingSessionState state() const { return state_; }
    std::size_t completedSteps() const { return step_; }
    bool pending() const { return pending_; }
    bool awaitingTerminalConfirmation() const {
        return state_ == PairingSessionState::Armed &&
            step_ == profile_.stepCount &&
            !profile_.completeAfterFinalReply;
    }
    PairingFailureReason failureReason() const { return failureReason_; }
    std::uint32_t expiresAtMs() const { return expiresAtMs_; }

private:
    void fail(PairingFailureReason reason) {
        state_ = PairingSessionState::Failed;
        pending_ = false;
        failureReason_ = reason;
    }

    PairingSessionState state_ = PairingSessionState::Disarmed;
    std::size_t step_ = 0;
    std::uint32_t expiresAtMs_ = 0;
    std::uint32_t claimedAtMs_ = 0;
    bool pending_ = false;
    PairingFailureReason failureReason_ = PairingFailureReason::None;
    const PairingProfile& profile_;
};

}  // namespace rainpoint
