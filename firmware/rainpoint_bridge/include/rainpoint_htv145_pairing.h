#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "rainpoint_pairing.h"

#ifndef RAINPOINT_HTV145_FACTORY_COUNTER_CANDIDATE
#define RAINPOINT_HTV145_FACTORY_COUNTER_CANDIDATE 0
#endif

namespace rainpoint {
namespace htv145 {

// HTV145 enrollment is intentionally a separate module from HTV405. The two
// valve families share the CC1101 transport and frame primitives, but not a
// pairing profile, state machine, calibration, or reply builder.
constexpr const char* kProfileId = "htv145_auto_candidate_v1";
constexpr std::size_t kPairingStepCount = 6;
constexpr std::uint8_t kTargetFactoryCounter =
    RAINPOINT_HTV145_FACTORY_COUNTER_CANDIDATE;
static_assert(
    kTargetFactoryCounter == 0 || kTargetFactoryCounter == 2,
    "HTV145 research pairing supports only captured counter-0 or counter-2 branches"
);
// The generic pairing bound remains intentionally narrower for validated
// sensors and HTV405. HTV145 uses a separately gated research image and its
// capture-derived node calibration legitimately exceeds that shared bound.
constexpr std::int32_t kMaximumPairingFrequencyOffsetHz = 150'000;
// Balanced-wake analysis of unclipped probe .22 and accepted stock IQ showed
// that the local assignment was 35.370 kHz low relative to the valve's own
// factory request oscillator. Probe .23 adds only that normalized correction
// and the independently measured stock initial-deviation profile.
constexpr std::int32_t kPairingFrequencyOffsetHz = 122'759;
static_assert(
    kPairingFrequencyOffsetHz <= kMaximumPairingFrequencyOffsetHz,
    "HTV145 pairing calibration must remain inside its research-only bound"
);
constexpr std::uint32_t kInitialChannelCenterHz = 433'501'466;
// Counter-2 stage 0 is now physically proven and keeps the original initial
// carrier. Direct balanced-wake measurement of the first two accepted local
// assignments showed that the following stage-1 response landed 30.326 kHz
// above the accepted stock response. Correct only the counter-2 routine leg;
// the independent counter-0 research profile remains unchanged.
constexpr std::uint32_t kRoutineChannelCenterHz =
    kTargetFactoryCounter == 2 ? 434'276'052 : 434'306'378;
constexpr std::uint8_t kInitialDeviationRegister = 0x45;
constexpr std::uint8_t kOrdinaryDeviationRegister = 0x45;
// Retained only for the gated SDR calibration command. The live counter-0
// selector-6 profile does not transmit this older selector-5 prelude.
constexpr std::uint16_t kCounter0AssignmentPreludeSymbols = 256;
constexpr std::uint8_t kCounter0AssignmentPreludeDeviationRegister = 0x42;
// Stock emits a 2,400-symbol alternating wake. The candidate-.3 ESP32/CC1101
// burst was 3.242 ms (about 64 symbols) shorter on-air, and only 2,368 of the
// expected 2,399 wake transitions were recoverable. Add only that expendable
// lead compensation on the isolated counter-2 research branch so the on-air
// wake remains the stock 2,400 symbols. Counter 0 and every production path
// retain their original 2,400-symbol request.
constexpr std::uint16_t kConfigurationWakeSymbols =
    kTargetFactoryCounter == 2 ? 2'464 : 2'400;
constexpr std::uint32_t kConfigurationReplyDeadlineMs = 4'000;
constexpr std::uint32_t kAssignmentReplyStartDelayUs =
    kTargetFactoryCounter == 2 ? 49'650 : 52'150;
// Three independent accepted stock frames retain a low FSK tone until about
// 160 us after the normalized frame. The existing CC1101 path naturally stays
// on air for about 45 us after driving GDO0 low, so the isolated candidate adds
// only the measured 115 us difference. This constant is inert unless the
// separate research build flag is enabled.
constexpr std::uint16_t kStage0PostFrameLowHoldAdjustmentUs = 115;
constexpr std::uint32_t kStep1ReplyStartDelayUs =
    kTargetFactoryCounter == 2 ? 68'700 : 70'700;
// Stock evidence measures the delayed configuration from the normalized
// 320-symbol reply boundary, while this transmission carries a 2,400-symbol
// wake. The first accepted local counter-2 exchange proved that scheduling the
// waveform at 2,952,550 us made the decoded configuration boundary 101,500 us
// late. Compensate only the counter-2 research branch; its now-proven stage-0
// assignment remains byte-for-byte unchanged.
constexpr std::uint32_t kConfigurationReplyStartDelayUs =
    kTargetFactoryCounter == 2 ? 2'851'050 : 3'054'850;
constexpr std::uint32_t kStep3ReplyStartDelayUs =
    kTargetFactoryCounter == 2 ? 53'300 : 35'750;
constexpr std::uint32_t kStep4ReplyStartDelayUs =
    kTargetFactoryCounter == 2 ? 52'550 : 52'000;
constexpr std::uint32_t kStep5ReplyStartDelayUs =
    kTargetFactoryCounter == 2 ? 47'500 : 47'200;

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

// One coherent counter-0 / selector-6 transcript from the controlled
// 2026-09-01 stock-gateway capture. Do not synthesize rows from HTV405 or from
// the older selector-5/later-sweep experiments.
constexpr std::array<PairingStep, kPairingStepCount> kCounter0PairingTemplate = {{
    {{{0x80, 0x80, 0x84, 0x02, 0xff, 0x8f, 0x97, 0x00, 0x80, 0xbf, 0x06, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x80, 0xc0, 0x85, 0x85, 0x00, 0x86, 0x70, 0x00, 0xf8, 0x65, 0x21, 0x0d, 0x01, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0xc713, kInitialChannelCenterHz, kInitialDeviationRegister, true},
    {{{0x81, 0x01, 0x07, 0x86, 0x25, 0x80, 0x80, 0x4f, 0x80, 0x00, 0x00, 0x00, 0x40, 0x80, 0x00, 0x56, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x81, 0x41, 0x01, 0x00, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0x4f03, kRoutineChannelCenterHz, kOrdinaryDeviationRegister, true},
    {{{0x81, 0x50, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, false, 0x0000, kRoutineChannelCenterHz, kOrdinaryDeviationRegister, false},
    {{{0x81, 0x82, 0x81, 0x06, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x81, 0xc2, 0x87, 0x80, 0x2c, 0x01, 0x05, 0x00, 0x0f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0x4f03, kRoutineChannelCenterHz, kOrdinaryDeviationRegister, true},
    {{{0x82, 0x03, 0x01, 0x86, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x82, 0x43, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0x4f03, kRoutineChannelCenterHz, kOrdinaryDeviationRegister, true},
    {{{0x82, 0xac, 0x80, 0x99, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x82, 0xec, 0x81, 0x80, 0x19, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0x4f03, kRoutineChannelCenterHz, kOrdinaryDeviationRegister, true},
}};

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
    profile.steps = kTargetFactoryCounter == 2
        ? kCounter2PairingTemplate
        : kCounter0PairingTemplate;
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
        // Counter 0 carries its branch marker in time-low bit 7; counter 2
        // moves that marker to time-high bit 7. Preserve the other byte as
        // ordinary FAT/DOS time so the live hour and minute remain intact.
        const std::uint8_t packedTimeLow = static_cast<std::uint8_t>(
            packedTime
        );
        const std::uint8_t packedTimeHigh = static_cast<std::uint8_t>(
            packedTime >> 8
        );
        if (kTargetFactoryCounter == 2) {
            frame[21] = packedTimeLow;
            frame[22] = static_cast<std::uint8_t>(
                (packedTimeHigh & 0x7fU) | 0x80U
            );
        } else {
            frame[21] = static_cast<std::uint8_t>(
                (packedTimeLow & 0x7fU) | 0x80U
            );
            frame[22] = packedTimeHigh;
        }
        frame[23] = static_cast<std::uint8_t>(
            packedDate | (kTargetFactoryCounter == 2 ? 0x80U : 0x00U)
        );
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
