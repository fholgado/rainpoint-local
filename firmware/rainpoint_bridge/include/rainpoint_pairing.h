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

struct PairingReplyStep {
    PairingTrigger trigger;
    std::uint32_t channelCenterHz;
    std::uint16_t wakeSymbols;
    std::uint16_t replyDeadlineMs;
    std::array<std::uint8_t, kFrameBytes> frame;
};

constexpr std::uint32_t kPairingSymbolRate = 20'000;
constexpr std::uint16_t kPairingWakeSymbols = 320;
constexpr std::uint16_t kPairingReplyDeadlineMs = 250;
constexpr std::int32_t kMaxPairingFrequencyOffsetHz = 100'000;

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
        value = 1U ^ static_cast<std::uint8_t>(index & 1U);
    } else {
        const std::size_t frameIndex = index - wakeSymbols;
        value = (frame[frameIndex / 8] >> (7 - frameIndex % 8)) & 1U;
    }
    return invert ? value ^ 1U : value;
}

constexpr std::array<PairingReplyStep, 5> kSensorBPairingProfile = {{
    {
        PairingTrigger::FactoryAnnouncement,
        433'471'500,
        kPairingWakeSymbols,
        kPairingReplyDeadlineMs,
        {{0x79, 0xf4, 0x88, 0x2f, 0x28, 0x95, 0xa9, 0x80, 0x24, 0x39,
          0x84, 0x02, 0x80, 0x81, 0x40, 0x88, 0x05, 0x03, 0x84, 0x70,
          0x00, 0xf4, 0x73, 0x0a, 0x0d, 0x00, 0x80, 0x80, 0x00, 0x00,
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x60, 0xa8}},
    },
    {
        PairingTrigger::PairedMessage1,
        433'911'500,
        kPairingWakeSymbols,
        kPairingReplyDeadlineMs,
        {{0x79, 0xf4, 0x88, 0x2f, 0x28, 0x95, 0xa9, 0x80, 0x24, 0x39,
          0x84, 0x02, 0x80, 0x81, 0xc1, 0x82, 0x00, 0x00, 0x9f, 0x80,
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x77, 0xdc}},
    },
    {
        PairingTrigger::PairedMessage2Data,
        433'911'500,
        kPairingWakeSymbols,
        kPairingReplyDeadlineMs,
        {{0x79, 0xf4, 0x88, 0x2f, 0x28, 0x95, 0xa9, 0x80, 0x24, 0x39,
          0x84, 0x02, 0x80, 0x82, 0x41, 0x81, 0x00, 0x01, 0x00, 0x00,
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x36, 0x22}},
    },
    {
        PairingTrigger::PairedMessage2Short,
        433'911'500,
        kPairingWakeSymbols,
        kPairingReplyDeadlineMs,
        {{0x79, 0xf4, 0x88, 0x2f, 0x28, 0x95, 0xa9, 0x80, 0x24, 0x39,
          0x84, 0x02, 0x80, 0x82, 0xc2, 0x81, 0x00, 0x00, 0x80, 0x00,
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x03, 0xdf}},
    },
    {
        PairingTrigger::PairedMessage3,
        433'911'500,
        kPairingWakeSymbols,
        kPairingReplyDeadlineMs,
        {{0x79, 0xf4, 0x88, 0x2f, 0x28, 0x95, 0xa9, 0x80, 0x24, 0x39,
          0x84, 0x02, 0x80, 0x83, 0x41, 0x81, 0x00, 0x01, 0x00, 0x00,
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
          0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x53, 0x29}},
    },
}};

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

inline bool validSensorBPairingProfile() {
    constexpr std::array<std::uint8_t, 4> paired = {0x95, 0xa9, 0x80, 0x24};
    constexpr std::array<std::uint8_t, 4> companion = {0x39, 0x84, 0x02, 0x80};
    for (const auto& step : kSensorBPairingProfile) {
        if (!hasSync(step.frame) || !hasOrdinaryTrailer(step.frame) ||
            step.wakeSymbols != kPairingWakeSymbols ||
            step.replyDeadlineMs != kPairingReplyDeadlineMs) {
            return false;
        }
        for (std::size_t index = 0; index < paired.size(); ++index) {
            if (step.frame[index + 5] != paired[index] ||
                step.frame[index + 9] != companion[index]) {
                return false;
            }
        }
    }
    return true;
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

inline bool sensorBTrigger(
    const std::array<std::uint8_t, kFrameBytes>& frame,
    PairingTrigger& trigger
) {
    constexpr std::array<std::uint8_t, 4> factoryRoute = {
        0x80, 0x00, 0x00, 0x00,
    };
    constexpr std::array<std::uint8_t, 4> factory = {
        0x15, 0xa9, 0x80, 0x24,
    };
    constexpr std::array<std::uint8_t, 4> gateway = {
        0xb9, 0x84, 0x02, 0x80,
    };
    constexpr std::array<std::uint8_t, 4> paired = {
        0x95, 0xa9, 0x80, 0x24,
    };
    if (!hasSync(frame) || !hasOrdinaryTrailer(frame)) {
        return false;
    }
    const std::uint8_t message = frame[13] & 0x7f;
    if (endpointEquals(frame, 5, factoryRoute) &&
        endpointEquals(frame, 9, factory) && message == 1) {
        trigger = PairingTrigger::FactoryAnnouncement;
        return true;
    }
    if (!endpointEquals(frame, 5, gateway) ||
        !endpointEquals(frame, 9, paired)) {
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
    if (message == 2 && frame[14] == 0x82) {
        trigger = PairingTrigger::PairedMessage2Short;
        return true;
    }
    if (message == 3) {
        trigger = PairingTrigger::PairedMessage3;
        return true;
    }
    return false;
}

class SensorBPairingSession {
public:
    void arm(std::uint32_t nowMs, std::uint32_t durationMs = 120'000) {
        state_ = PairingSessionState::Armed;
        step_ = 0;
        expiresAtMs_ = nowMs + durationMs;
        pending_ = false;
    }

    void cancel() {
        state_ = PairingSessionState::Disarmed;
        step_ = 0;
        pending_ = false;
    }

    void tick(std::uint32_t nowMs) {
        if (state_ == PairingSessionState::Armed &&
            static_cast<std::int32_t>(nowMs - expiresAtMs_) >= 0) {
            fail();
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
        if (!sensorBTrigger(frame, observed)) {
            return nullptr;
        }
        const PairingTrigger expected = kSensorBPairingProfile[step_].trigger;
        if (observed == expected) {
            pending_ = true;
            claimedAtMs_ = nowMs;
            return &kSensorBPairingProfile[step_];
        }
        for (std::size_t index = 0; index < step_; ++index) {
            if (kSensorBPairingProfile[index].trigger == observed) {
                return nullptr;
            }
        }
        fail();
        return nullptr;
    }

    bool finishReply(bool success, std::uint32_t nowMs) {
        if (state_ != PairingSessionState::Armed || !pending_ || !success ||
            nowMs - claimedAtMs_ >
                kSensorBPairingProfile[step_].replyDeadlineMs) {
            fail();
            return false;
        }
        pending_ = false;
        ++step_;
        if (step_ == kSensorBPairingProfile.size()) {
            state_ = PairingSessionState::Completed;
        }
        return true;
    }

    PairingSessionState state() const { return state_; }
    std::size_t completedSteps() const { return step_; }
    bool pending() const { return pending_; }
    std::uint32_t expiresAtMs() const { return expiresAtMs_; }

private:
    void fail() {
        state_ = PairingSessionState::Failed;
        pending_ = false;
    }

    PairingSessionState state_ = PairingSessionState::Disarmed;
    std::size_t step_ = 0;
    std::uint32_t expiresAtMs_ = 0;
    std::uint32_t claimedAtMs_ = 0;
    bool pending_ = false;
};

}  // namespace rainpoint
