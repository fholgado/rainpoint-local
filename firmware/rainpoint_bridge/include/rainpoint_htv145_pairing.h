#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "rainpoint_pairing.h"



namespace rainpoint {
namespace htv145 {

// HTV145 enrollment is intentionally a separate module from HTV405. The two
// valve families share the CC1101 transport and frame primitives, but not a
// pairing profile, state machine, calibration, or reply builder.
constexpr const char* kProfileId = "htv145_auto_candidate_v1";
constexpr std::size_t kPairingStepCount = 6;
constexpr std::uint8_t kTargetFactoryCounter = 2;
constexpr std::uint8_t kAssignmentSelector = 6;
constexpr std::uint8_t kAssignedChannel = 12;
// Frozen counter-2/selector-6 recipe from candidate .22. Five rows plus
// operational controls passed on dry hardware. The terminal sixth row has
// not been observed locally. Historical alternatives live in RF fixtures.
constexpr std::int32_t kMaximumPairingFrequencyOffsetHz = 150'000;
constexpr std::int32_t kPairingFrequencyOffsetHz = 122'759;
constexpr std::uint32_t kInitialChannelCenterHz = 433'501'466;
constexpr std::uint32_t kRoutineChannelCenterHz = 434'276'052;
constexpr std::uint8_t kInitialDeviationRegister = 0x45;
constexpr std::uint8_t kOrdinaryDeviationRegister = 0x45;
constexpr std::uint16_t kConfigurationWakeSymbols = 2'400;
constexpr std::uint32_t kConfigurationReplyDeadlineMs = 4'000;
constexpr std::uint32_t kAssignmentReplyStartDelayUs = 49'650;
constexpr std::uint16_t kStage0PostFrameLowHoldAdjustmentUs = 115;
constexpr std::uint16_t kStep1PostFrameLowHoldAdjustmentUs = 115;
constexpr std::uint16_t kStep4PostFrameLowHoldAdjustmentUs = 115;
constexpr std::uint16_t kStep4FifoPostFrameLowHoldAdjustmentUs = 0;
constexpr std::uint16_t kStep4FifoActiveTailDelayUs = 910;
constexpr std::uint32_t kStep1ReplyStartDelayUs = 68'700;
constexpr std::uint16_t kConfigurationPostFrameLowHoldAdjustmentUs = 115;
constexpr std::uint32_t kConfigurationReplyStartDelayUs = 2'848'400;
constexpr std::uint32_t kStep3ReplyStartDelayUs = 53'300;
constexpr std::uint32_t kStep4ReplyStartDelayUs = 52'550;
constexpr std::uint32_t kStep5ReplyStartDelayUs = 47'500;

constexpr std::uint32_t replyStartDelayUs(std::size_t stepIndex) {
    return stepIndex == 0 ? kAssignmentReplyStartDelayUs
        : stepIndex == 1 ? kStep1ReplyStartDelayUs
        : stepIndex == 3 ? kStep3ReplyStartDelayUs
        : stepIndex == 4 ? kStep4ReplyStartDelayUs
        : stepIndex == 5 ? kStep5ReplyStartDelayUs
        : 49'500;
}

struct PairingStep {
    std::array<std::uint8_t, 23> requestBody;
    std::array<std::uint8_t, 23> replyBody;
    bool replyExpected;
    std::uint16_t trailerResidual;
    std::uint32_t channelCenterHz;
    std::uint8_t deviationRegister;
    bool replyToController;
};

struct PairingProfile {
    std::array<std::uint8_t, 4> factoryEndpoint{};
    std::array<std::uint8_t, 4> pairedEndpoint{};
    std::array<std::uint8_t, 4> controllerEndpoint{};
    std::array<std::uint8_t, 4> companionEndpoint{};
    std::array<PairingStep, kPairingStepCount> steps{};
};

// Complete counter-2 / selector-6 transcript from the controlled
// button-first stock enrollment. It is a coherent branch: counters, reply
// residues, and response timing are retained together rather than mixed with
// the counter-0 profile.
constexpr std::array<PairingStep, kPairingStepCount> kCounter2PairingTemplate = {{
    {{{0x82, 0x00, 0x84, 0x02, 0xff, 0x8f, 0x97, 0x00, 0x80, 0xbf, 0x06, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x82, 0x40, 0x85, 0x85, 0x00, 0x86, 0x70, 0x00, 0x98, 0xe1, 0xa1, 0x0d, 0x01, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0x4f03, kInitialChannelCenterHz, kInitialDeviationRegister, true},
    {{{0x82, 0x81, 0x07, 0x86, 0x25, 0x80, 0x80, 0x4f, 0x80, 0x00, 0x00, 0x00, 0x40, 0x80, 0x00, 0x56, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x82, 0xc1, 0x01, 0x00, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0x4f03, kRoutineChannelCenterHz, kOrdinaryDeviationRegister, true},
    {{{0x81, 0x50, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, false, 0x0000, kRoutineChannelCenterHz, kOrdinaryDeviationRegister, false},
    {{{0x83, 0x02, 0x81, 0x06, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x83, 0x42, 0x87, 0x80, 0x2c, 0x01, 0x05, 0x00, 0x0f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0x4f03, kRoutineChannelCenterHz, kOrdinaryDeviationRegister, true},
    {{{0x83, 0x83, 0x01, 0x86, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x83, 0xc3, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0xc713, kRoutineChannelCenterHz, kOrdinaryDeviationRegister, true},
    {{{0x84, 0x2c, 0x80, 0x99, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x84, 0x6c, 0x81, 0x80, 0x19, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0xc713, kRoutineChannelCenterHz, kOrdinaryDeviationRegister, true},
}};

inline bool buildProfile(
    const std::array<std::uint8_t, 4>& factoryEndpoint,
    const std::array<std::uint8_t, 4>& controllerEndpoint,
    const std::array<std::uint8_t, 4>& companionEndpoint,
    PairingProfile& profile
) {
    if (factoryEndpoint[0] & 0x80U || factoryEndpoint[3] != 0x8fU ||
        !validRfControllerIdentity(controllerEndpoint, companionEndpoint)) {
        return false;
    }
    profile = {};
    profile.factoryEndpoint = factoryEndpoint;
    profile.pairedEndpoint = factoryEndpoint;
    profile.pairedEndpoint[0] |= 0x80U;
    profile.controllerEndpoint = controllerEndpoint;
    profile.companionEndpoint = companionEndpoint;
    profile.steps = kCounter2PairingTemplate;
    return true;
}

inline bool requestMatches(
    const PairingProfile& profile,
    std::size_t stepIndex,
    const std::array<std::uint8_t, kFrameBytes>& frame
) {
    if (stepIndex >= profile.steps.size() || !hasSync(frame) ||
        !hasOrdinaryTrailer(frame)) {
        return false;
    }
    const bool endpointsMatch = stepIndex == 0
        ? endpointEquals(frame, 5, {{0x80, 0x00, 0x00, 0x00}}) &&
            endpointEquals(frame, 9, profile.factoryEndpoint)
        : endpointEquals(frame, 5, profile.controllerEndpoint) &&
            endpointEquals(frame, 9, profile.pairedEndpoint);
    if (!endpointsMatch) {
        return false;
    }
    const std::size_t firstComparedBodyByte = stepIndex == 0 ? 2 : 0;
    for (std::size_t index = firstComparedBodyByte; index < 23; ++index) {
        if (frame[13 + index] != profile.steps[stepIndex].requestBody[index]) {
            return false;
        }
    }
    return true;
}

// Discovery supplies identity only. PairingSession retains the frozen counter-2
// transcript, timing and expiry; see the byte-identical response regression.
inline bool initializeAutomaticProfile(
    const std::array<std::uint8_t, 4>& controllerEndpoint,
    const std::array<std::uint8_t, 4>& companionEndpoint,
    PairingProfile& profile
) {
    return buildProfile({{0, 0, 0, 0x8f}}, controllerEndpoint, companionEndpoint, profile);
}

inline bool adoptFactoryAnnouncement(
    const std::array<std::uint8_t, kFrameBytes>& frame,
    PairingProfile& profile
) {
    std::array<std::uint8_t, 4> factory{};
    for (std::size_t index = 0; index < factory.size(); ++index) {
        factory[index] = frame[9 + index];
    }
    PairingProfile candidate{};
    if (!buildProfile(factory, profile.controllerEndpoint, profile.companionEndpoint, candidate) ||
        !requestMatches(candidate, 0, frame)) {
        return false;
    }
    profile = candidate;
    return true;
}

inline bool buildReply(
    const PairingProfile& profile,
    std::size_t stepIndex,
    const PairingLocalDateTime& localClock,
    std::array<std::uint8_t, kFrameBytes>& frame
) {
    if (stepIndex >= profile.steps.size() ||
        !profile.steps[stepIndex].replyExpected) {
        return false;
    }
    frame.fill(0);
    for (std::size_t index = 0; index < kSync.size(); ++index) {
        frame[index] = kSync[index];
    }
    for (std::size_t index = 0; index < 4; ++index) {
        frame[5 + index] = profile.pairedEndpoint[index];
        frame[9 + index] = profile.steps[stepIndex].replyToController
            ? profile.controllerEndpoint[index]
            : profile.companionEndpoint[index];
    }
    for (std::size_t index = 0; index < 23; ++index) {
        frame[13 + index] = profile.steps[stepIndex].replyBody[index];
    }
    if (stepIndex == 0) {
        if (!validPairingLocalDateTime(localClock)) {
            return false;
        }
        const std::uint16_t packedTime = static_cast<std::uint16_t>(
            (static_cast<std::uint16_t>(localClock.hour) << 11) |
            (static_cast<std::uint16_t>(localClock.minute) << 5) |
            (localClock.second / 2)
        );
        const std::uint16_t packedDate = static_cast<std::uint16_t>(
            (static_cast<std::uint16_t>(localClock.year - 2020) << 9) |
            (static_cast<std::uint16_t>(localClock.month) << 5) |
            localClock.day
        );
        // Preserve the accepted counter-2 clock overlays with the live clock.
        const std::uint8_t packedTimeLow = static_cast<std::uint8_t>(
            packedTime
        );
        const std::uint8_t packedTimeHigh = static_cast<std::uint8_t>(
            packedTime >> 8
        );
        frame[21] = packedTimeLow;
        frame[22] = static_cast<std::uint8_t>((packedTimeHigh & 0x7fU) | 0x80U);
        frame[23] = static_cast<std::uint8_t>(packedDate | 0x80U);
        frame[24] = static_cast<std::uint8_t>(packedDate >> 8);
    }
    writeTrailer(frame, profile.steps[stepIndex].trailerResidual);
    return true;
}

inline bool buildConfigurationReply(
    const PairingProfile& profile,
    std::array<std::uint8_t, kFrameBytes>& frame
) {
    frame.fill(0);
    for (std::size_t index = 0; index < kSync.size(); ++index) {
        frame[index] = kSync[index];
    }
    for (std::size_t index = 0; index < 4; ++index) {
        frame[5 + index] = profile.pairedEndpoint[index];
        frame[9 + index] = profile.controllerEndpoint[index];
    }
    frame[13] = 0x81;
    frame[14] = 0x10;
    frame[15] = 0x01;
    frame[16] = 0x01;
    writeTrailer(frame, 0xc713);
    return true;
}

class PairingSession {
public:
    explicit PairingSession(const PairingProfile& profile)
        : profile_(profile) {}

    void arm(std::uint32_t nowMs, std::uint32_t durationMs = 120'000) {
        state_ = PairingSessionState::Armed;
        failureReason_ = PairingFailureReason::None;
        step_ = 0;
        expiresAtMs_ = nowMs + durationMs;
        claimedAtMs_ = 0;
        pending_ = false;
        assignmentLocked_ = false;
        stage0Accepted_ = false;
        stage0Rejected_ = false;
        factorySweepObserved_ = false;
        lastFactorySweepCounter_ = 0;
        acceptedFactoryCounter_ = 0;
    }

    void cancel() {
        state_ = PairingSessionState::Disarmed;
        failureReason_ = PairingFailureReason::None;
        step_ = 0;
        pending_ = false;
        assignmentLocked_ = false;
        stage0Accepted_ = false;
        stage0Rejected_ = false;
        factorySweepObserved_ = false;
        lastFactorySweepCounter_ = 0;
        acceptedFactoryCounter_ = 0;
    }

    const PairingStep* claimReply(
        const std::array<std::uint8_t, kFrameBytes>& frame,
        std::uint32_t nowMs
    ) {
        tick(nowMs);
        if (state_ != PairingSessionState::Armed || pending_) {
            return nullptr;
        }
        if (requestMatches(profile_, 0, frame)) {
            const auto sweepCounter = static_cast<std::uint8_t>(
                frame[13] & 0x7fU
            );
            factorySweepObserved_ = true;
            lastFactorySweepCounter_ = sweepCounter;
            if (assignmentLocked_) {
                if (!stage0Accepted_ && step_ == 1) {
                    stage0Rejected_ = true;
                    fail(PairingFailureReason::Stage0Rejected);
                }
                return nullptr;
            }
            if (sweepCounter != kTargetFactoryCounter) {
                return nullptr;
            }
            assignmentLocked_ = true;
            acceptedFactoryCounter_ = sweepCounter;
            pending_ = true;
            claimedAtMs_ = nowMs;
            return &profile_.steps[0];
        }
        if (!assignmentLocked_ || step_ == 0 ||
            step_ >= profile_.steps.size() ||
            !requestMatches(profile_, step_, frame)) {
            return nullptr;
        }
        if (step_ == 1) {
            stage0Accepted_ = true;
        }
        const auto& step = profile_.steps[step_];
        if (!step.replyExpected) {
            ++step_;
            if (step_ == profile_.steps.size()) {
                state_ = PairingSessionState::Completed;
            }
            return nullptr;
        }
        pending_ = true;
        claimedAtMs_ = nowMs;
        return &step;
    }

    bool finishReply(bool success, std::uint32_t nowMs) {
        if (state_ != PairingSessionState::Armed || !pending_ || !success) {
            fail(PairingFailureReason::ReplyFailed);
            return false;
        }
        const std::uint32_t deadlineMs = step_ == 1
            ? kConfigurationReplyDeadlineMs
            : kPairingReplyDeadlineMs;
        if (nowMs - claimedAtMs_ > deadlineMs) {
            fail(PairingFailureReason::ReplyDeadlineMissed);
            return false;
        }
        pending_ = false;
        ++step_;
        if (step_ == profile_.steps.size()) {
            state_ = PairingSessionState::Completed;
        }
        return true;
    }

    void tick(std::uint32_t nowMs) {
        if (state_ == PairingSessionState::Armed &&
            static_cast<std::int32_t>(nowMs - expiresAtMs_) >= 0) {
            fail(PairingFailureReason::SessionTimeout);
        }
    }

    PairingSessionState state() const { return state_; }
    PairingFailureReason failureReason() const { return failureReason_; }
    std::size_t completedSteps() const { return step_; }
    bool assignmentLocked() const { return assignmentLocked_; }
    bool stage0Accepted() const { return stage0Accepted_; }
    bool stage0Rejected() const { return stage0Rejected_; }
    bool factorySweepObserved() const { return factorySweepObserved_; }
    std::uint8_t lastFactorySweepCounter() const {
        return lastFactorySweepCounter_;
    }
    std::uint8_t acceptedFactoryCounter() const {
        return acceptedFactoryCounter_;
    }

private:
    void fail(PairingFailureReason reason) {
        state_ = PairingSessionState::Failed;
        failureReason_ = reason;
        pending_ = false;
    }

    const PairingProfile& profile_;
    PairingSessionState state_ = PairingSessionState::Disarmed;
    PairingFailureReason failureReason_ = PairingFailureReason::None;
    std::size_t step_ = 0;
    std::uint32_t expiresAtMs_ = 0;
    std::uint32_t claimedAtMs_ = 0;
    bool pending_ = false;
    bool assignmentLocked_ = false;
    bool stage0Accepted_ = false;
    bool stage0Rejected_ = false;
    bool factorySweepObserved_ = false;
    std::uint8_t lastFactorySweepCounter_ = 0;
    std::uint8_t acceptedFactoryCounter_ = 0;
};

}  // namespace htv145
}  // namespace rainpoint
