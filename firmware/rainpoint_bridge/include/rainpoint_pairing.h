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

}  // namespace rainpoint
