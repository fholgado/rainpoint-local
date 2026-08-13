#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "rainpoint_pairing.h"
#include "rainpoint_protocol.h"

namespace rainpoint {

// Stock captures place the acknowledgement sync about 177--188 ms after the
// report sync. poll() returns after the 15.2 ms frame, and the reply contributes
// a 16 ms wake, so a 150 ms post-receive delay reproduces that envelope.
constexpr std::uint16_t kRoutineAckDelayMs = 150;
constexpr std::uint16_t kRoutineAckWakeSymbols = 320;
constexpr std::uint16_t kRoutineAckDeadlineMs = 250;

constexpr std::array<std::uint8_t, 4> kHcs026SensorRoute = {
    0xb9, 0x84, 0x02, 0x80,
};
constexpr std::array<std::uint8_t, 4> kHcs026CompanionEndpoint = {
    0x39, 0x84, 0x02, 0x80,
};

struct RoutineAckAuthorization {
    std::array<std::uint8_t, 4> pairedEndpoint{};
    std::uint8_t pairingChannel = 0;
    std::int32_t frequencyOffsetHz = 0;
    std::int8_t powerDbm = 0;
    bool invert = false;
    bool active = false;
};

inline bool isAuthorizedRoutineHcs026Report(
    const std::array<std::uint8_t, kFrameBytes>& frame,
    const RoutineAckAuthorization& authorization
);

constexpr std::size_t kMaximumRoutineAckAuthorizations = 8;

class RoutineAckAuthorizations {
public:
    bool authorize(const RoutineAckAuthorization& authorization) {
        if (!authorization.active ||
            (authorization.pairingChannel != 4 &&
             authorization.pairingChannel != 5) ||
            !validPairingPowerDbm(authorization.powerDbm) ||
            authorization.frequencyOffsetHz < -kMaxPairingFrequencyOffsetHz ||
            authorization.frequencyOffsetHz > kMaxPairingFrequencyOffsetHz) {
            return false;
        }
        RoutineAckAuthorization* available = nullptr;
        for (auto& existing : authorizations_) {
            if (existing.active &&
                existing.pairedEndpoint == authorization.pairedEndpoint) {
                existing = authorization;
                return true;
            }
            if (!existing.active && available == nullptr) {
                available = &existing;
            }
        }
        if (available == nullptr) {
            return false;
        }
        *available = authorization;
        return true;
    }

    const RoutineAckAuthorization* match(
        const std::array<std::uint8_t, kFrameBytes>& frame
    ) const {
        for (const auto& authorization : authorizations_) {
            if (isAuthorizedRoutineHcs026Report(frame, authorization)) {
                return &authorization;
            }
        }
        return nullptr;
    }

    std::size_t activeCount() const {
        std::size_t count = 0;
        for (const auto& authorization : authorizations_) {
            count += authorization.active ? 1U : 0U;
        }
        return count;
    }

private:
    std::array<RoutineAckAuthorization, kMaximumRoutineAckAuthorizations>
        authorizations_{};
};

inline bool isAuthorizedRoutineHcs026Report(
    const std::array<std::uint8_t, kFrameBytes>& frame,
    const RoutineAckAuthorization& authorization
) {
    if (!authorization.active || !hasSync(frame) ||
        !hasOrdinaryTrailer(frame) ||
        !endpointEquals(frame, 5, kHcs026SensorRoute) ||
        !endpointEquals(frame, 9, authorization.pairedEndpoint)) {
        return false;
    }
    const std::uint8_t message = frame[13] & 0x7fU;
    // Messages 01--03 are enrollment/rejoin control traffic. Routine reports
    // use 00 after counter wrap or 04--7f and the captured HCS026 data shape.
    return message != 1 && message != 2 && message != 3 &&
        (frame[14] & 0x7fU) == 0x01 && frame[15] == 0x82;
}

inline bool buildRoutineHcs026Acknowledgement(
    const std::array<std::uint8_t, kFrameBytes>& report,
    const RoutineAckAuthorization& authorization,
    std::array<std::uint8_t, kFrameBytes>& acknowledgement
) {
    if (!isAuthorizedRoutineHcs026Report(report, authorization)) {
        return false;
    }
    acknowledgement.fill(0);
    for (std::size_t index = 0; index < kSync.size(); ++index) {
        acknowledgement[index] = kSync[index];
    }
    for (std::size_t index = 0; index < authorization.pairedEndpoint.size();
         ++index) {
        acknowledgement[5 + index] = authorization.pairedEndpoint[index];
        acknowledgement[9 + index] = kHcs026CompanionEndpoint[index];
    }
    acknowledgement[13] = report[13] | 0x80U;
    acknowledgement[14] = report[14] | 0x40U;
    acknowledgement[15] = 0x81;
    acknowledgement[16] = 0x00;
    acknowledgement[17] = 0x01;
    // Every directly paired report/reply pair retained the report's CRC
    // residual selector, so preserve it rather than guessing globally.
    writeTrailer(acknowledgement, trailerResidual(report));
    return true;
}

inline std::uint32_t routineAckCenterHz(
    const RoutineAckAuthorization& authorization
) {
    return pairingChannelCenterHz(authorization.pairingChannel) +
        authorization.frequencyOffsetHz;
}

}  // namespace rainpoint
