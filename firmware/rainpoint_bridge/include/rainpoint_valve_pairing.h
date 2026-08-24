#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "rainpoint_pairing.h"

namespace rainpoint {

constexpr const char* kAutomaticHtv405ProfileId =
    "htv405_auto_candidate_v1";
constexpr std::size_t kHtv405PairingStepCount = 18;
// A continuous 2.0 Msps capture measured 50.656 ms of silence between the end
// of the 31.23 ms factory announcement and the stock assignment reply. The
// A local continuous-IQ trial measured the 50 ms software candidate about
// 1.3 ms later than stock start-to-start timing. The cached hop and transmit
// setup occur after this delay, so 49 ms is the closest millisecond target.
// The accepted stock assignment began 50.656 ms after the factory request
// finished. Fixed pre-transmit delays produced 80.1--84.4 ms request-start to
// RF-start timing because allocation and synthesizer preparation happened
// afterward. The node now prepares first and schedules the RF burst from the
// RX FIFO-complete timestamp. This target allows for the sub-millisecond FIFO
// polling delay while keeping the first assignment in the proven window.
constexpr std::uint32_t kHtv405AssignmentReplyStartDelayUs = 49'500;
constexpr std::uint32_t kHtv405OrdinaryReplyStartDelayUs = 49'500;
// The selector-2 transcript contains two timing-sensitive transitions before
// the short-form controller initialization begins. Stock replies to the
// repeated 01/81 request with 81/C1 about 36 ms after receive completion. A
// previous local profile incorrectly suppressed that reply; the next local
// request retained state 05/81 instead of advancing to stock's 05/82 and the
// valve never entered the 03/82 short-form exchange.
constexpr std::size_t kHtv405Selector2PhaseReplyStepIndex = 2;
constexpr std::uint32_t kHtv405Selector2PhaseReplyStartDelayUs = 35'650;
// Selector 2 then acknowledges paired message 2 twice: first with its ordinary
// 82/41 reply, then with a long-wake 82/10 controller command about one second
// after that same request finishes.
constexpr std::size_t kHtv405Selector2ConfigurationStepIndex = 3;
constexpr std::size_t kHtv405Selector2InitialOrdinaryStepIndex = 5;
constexpr std::size_t kHtv405Selector2ShortFormStepIndex = 6;
// Unlike the other ordinary acknowledgements, the 82/41 reply immediately
// before the controller transition starts 38.2 ms after the request ends in
// the accepted stock capture. A 38.0 ms scheduler target reproduces that
// on-air interval after the measured ~0.2 ms FIFO-completion overhead.
constexpr std::uint32_t kHtv405Selector2ImmediateReplyStartDelayUs = 38'000;
// In the accepted selector-2 stock transcript, the gateway's 84/C2 response
// to the repeated 04/82 short-form request started 39.1 ms after that request
// ended. The generic 49.5 ms reply slot is late enough that a locally paired
// valve can remain in the same initialization state while advancing only its
// transaction counter. Apply this measured slot only to retries observed after
// the already validated first ten logical steps.
constexpr std::uint32_t kHtv405Selector2ShortRepeatReplyStartDelayUs = 39'000;
// The accepted continuous selector-2 enrollment shows that the last three
// extended replies use dedicated slots rather than the ordinary 49.5 ms
// turnaround: request-end to reply-start gaps were 39.0, 41.1, and 38.9 ms.
// Probe.14 reached logical step 16 but kept the valve in its 99-family retry
// loop while transmitting step 15 in the ordinary slot. Preserve the frozen
// prefix and apply these measured timings only to extended steps 15--17.
constexpr std::uint32_t kHtv405Selector2ExtendedStep15ReplyStartDelayUs =
    39'000;
constexpr std::uint32_t kHtv405Selector2ExtendedStep16ReplyStartDelayUs =
    41'000;
constexpr std::uint32_t kHtv405Selector2ExtendedStep17ReplyStartDelayUs =
    39'000;
constexpr std::uint32_t kHtv405Selector2ConfigurationReplyStartDelayUs =
    997'500;
constexpr std::uint16_t kHtv405Selector2ConfigurationWakeSymbols = 2'400;
constexpr std::uint16_t kHtv405Selector2ConfigurationReplyDeadlineMs = 1'500;
constexpr std::uint8_t kOrdinaryDeviationRegister = 0x45;
// Freeze the initial assignment at the setting that has repeatedly produced a
// physical white-flash transition and, most recently, advanced this valve to
// paired step 6. Later controller-initialization experiments must not change
// this accepted step-0 carrier, deviation, payload, wake, or reply timing.
// A single failed retry is not calibration evidence: controlled trials have
// already shown success and failure without any firmware change.
constexpr std::uint8_t kHtv405InitialDeviationRegister = 0x43;
constexpr std::uint32_t kHtv405InitialChannelCenterHz = 433'511'445;
// Paired replies measured 5.035 kHz high relative to the stock gateway after
// normalizing both captures against the valve carrier. Apply that correction
// to every selector-2 initialization reply, including the long transition.
constexpr std::uint32_t kHtv405RoutineChannelCenterHz = 433'421'373;

constexpr std::uint32_t htv405PairingReplyStartDelayUs(
    std::size_t stepIndex
) {
    return stepIndex == 0
        ? kHtv405AssignmentReplyStartDelayUs
        : stepIndex == kHtv405Selector2PhaseReplyStepIndex
        ? kHtv405Selector2PhaseReplyStartDelayUs
        : stepIndex == kHtv405Selector2ConfigurationStepIndex
        ? kHtv405Selector2ImmediateReplyStartDelayUs
        : stepIndex == 15
        ? kHtv405Selector2ExtendedStep15ReplyStartDelayUs
        : stepIndex == 16
        ? kHtv405Selector2ExtendedStep16ReplyStartDelayUs
        : stepIndex == 17
        ? kHtv405Selector2ExtendedStep17ReplyStartDelayUs
        : kHtv405OrdinaryReplyStartDelayUs;
}

struct Htv405PairingStep {
    std::array<std::uint8_t, 23> requestBody;
    std::array<std::uint8_t, 23> replyBody;
    bool replyExpected;
    std::uint16_t trailerResidual;
    std::uint32_t channelCenterHz;
    std::uint8_t deviationRegister;
};

struct Htv405PairingProfile {
    std::array<std::uint8_t, 4> factoryEndpoint{};
    std::array<std::uint8_t, 4> pairedEndpoint{};
    std::array<std::uint8_t, 4> valveRoute{};
    std::array<std::uint8_t, 4> companionEndpoint{};
    std::array<Htv405PairingStep, kHtv405PairingStepCount> steps{};
};

constexpr std::array<Htv405PairingStep, kHtv405PairingStepCount>
    kHtv405PairingTemplate = {{
    {{{0x00, 0x80, 0x84, 0x02, 0xff, 0x93, 0x13, 0x00, 0x00, 0xbd, 0x84, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x80, 0xc0, 0x85, 0x85, 0x03, 0x02, 0x70, 0x00, 0x9d, 0x97, 0x91, 0x0d, 0x01, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0x4f03, kHtv405InitialChannelCenterHz, kHtv405InitialDeviationRegister},
    {{{0x01, 0x01, 0x07, 0x82, 0x25, 0x80, 0x80, 0x4f, 0x80, 0x00, 0x00, 0x00, 0x40, 0x80, 0x00, 0x56, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x81, 0x41, 0x01, 0x00, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0x4f03, 433426408, 0x45},
    {{{0x01, 0x81, 0x07, 0x82, 0x05, 0x81, 0x00, 0x4f, 0x80, 0x00, 0x00, 0x00, 0x40, 0x80, 0x00, 0x56, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x81, 0xc1, 0x01, 0x00, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0xc713, 433426408, 0x45},
    {{{0x02, 0x01, 0x07, 0x82, 0x05, 0x81, 0x80, 0x4f, 0x80, 0x00, 0x00, 0x00, 0x40, 0x80, 0x00, 0x56, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x82, 0x41, 0x01, 0x00, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0xc713, 433426408, 0x45},
    {{{0x02, 0x81, 0x07, 0x82, 0x05, 0x82, 0x00, 0x4f, 0x80, 0x00, 0x00, 0x00, 0x40, 0x80, 0x00, 0x56, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, false, 0x0000, 433426408, 0x45},
    {{{0x03, 0x01, 0x07, 0x82, 0x05, 0x82, 0x00, 0x4f, 0x80, 0x00, 0x00, 0x00, 0x40, 0x80, 0x00, 0x56, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x83, 0x41, 0x01, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0xc713, 433426408, 0x45},
    {{{0x03, 0x82, 0x81, 0x06, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x83, 0xc2, 0x87, 0x80, 0x2c, 0x01, 0x05, 0x00, 0x0f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0xc713, 434306001, 0x45},
    {{{0x04, 0x02, 0x81, 0x06, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x84, 0x42, 0x87, 0x80, 0x2c, 0x01, 0x05, 0x00, 0x0f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0x4f03, 434306001, 0x45},
    {{{0x04, 0x82, 0x81, 0x06, 0x01, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x84, 0xc2, 0x87, 0x80, 0x2c, 0x01, 0x05, 0x00, 0x0f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0xc713, 434306001, 0x45},
    {{{0x05, 0x02, 0x81, 0x06, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x85, 0x42, 0x87, 0x80, 0x2c, 0x01, 0x05, 0x00, 0x0f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0x4f03, 434306001, 0x45},
    {{{0x05, 0x83, 0x01, 0x86, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x85, 0xc3, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0xc713, 434306001, 0x45},
    {{{0x06, 0x03, 0x01, 0x86, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x86, 0x43, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0xc713, 434306001, 0x45},
    {{{0x06, 0x83, 0x01, 0x86, 0x01, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x86, 0xc3, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0x4f03, 434306001, 0x45},
    {{{0x07, 0x03, 0x01, 0x86, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x87, 0x43, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0xc713, 434306001, 0x45},
    {{{0x07, 0xac, 0x80, 0x99, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x87, 0xec, 0x87, 0x80, 0x19, 0x06, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0xc713, 434306001, 0x45},
    {{{0x08, 0x2c, 0x80, 0x99, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x88, 0x6c, 0x87, 0x80, 0x19, 0x86, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0xc713, 434306001, 0x45},
    {{{0x08, 0xac, 0x80, 0x9a, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x88, 0xec, 0x87, 0x80, 0x1a, 0x06, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0xc713, 434306001, 0x45},
    {{{0x09, 0x2c, 0x80, 0x9a, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}, {{0x89, 0x6c, 0x87, 0x80, 0x1a, 0x86, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x32, 0x00, 0x00, 0x00, 0x00, 0x00}}, true, 0xc713, 434306001, 0x45},
}};

inline bool htv405FactoryAnnouncement(
    const std::array<std::uint8_t, kFrameBytes>& frame,
    std::array<std::uint8_t, 4>& factoryEndpoint
) {
    if (!hasSync(frame) || !hasOrdinaryTrailer(frame) ||
        !endpointEquals(frame, 5, {{0x80, 0x00, 0x00, 0x00}}) ||
        frame[9] & 0x80U || frame[12] != 0x13) {
        return false;
    }
    for (std::size_t index = 0; index < 23; ++index) {
        if (frame[13 + index] != kHtv405PairingTemplate[0].requestBody[index]) {
            return false;
        }
    }
    for (std::size_t index = 0; index < 4; ++index) {
        factoryEndpoint[index] = frame[9 + index];
    }
    return true;
}

inline bool buildAutomaticHtv405Profile(
    const std::array<std::uint8_t, 4>& factoryEndpoint,
    const std::array<std::uint8_t, 4>& valveRoute,
    const std::array<std::uint8_t, 4>& companionEndpoint,
    Htv405PairingProfile& profile
) {
    if (factoryEndpoint[0] & 0x80U || factoryEndpoint[3] != 0x13 ||
        valveRoute == std::array<std::uint8_t, 4>{} ||
        companionEndpoint == std::array<std::uint8_t, 4>{}) {
        return false;
    }
    profile.factoryEndpoint = factoryEndpoint;
    profile.pairedEndpoint = factoryEndpoint;
    profile.pairedEndpoint[0] |= 0x80U;
    profile.valveRoute = valveRoute;
    profile.companionEndpoint = companionEndpoint;
    profile.steps = kHtv405PairingTemplate;
    // The two latest accepted stock enrollments assigned selector 2. Its
    // request marker and routine channel form one coherent branch; keep the
    // later request rows synchronized even where the retained fixture table
    // originated from the independently valid selector-6 transcript.
    for (std::size_t index = 1; index < profile.steps.size(); ++index) {
        profile.steps[index].channelCenterHz =
            kHtv405RoutineChannelCenterHz;
    }
    for (std::size_t index = 6; index <= 9; ++index) {
        profile.steps[index].requestBody[3] = 0x02;
    }
    for (std::size_t index = 10; index <= 13; ++index) {
        profile.steps[index].requestBody[3] = 0x82;
    }
    // Keep the template's 81/C1 response to 01/81. The isolated selector-2
    // stock capture contains that gateway transmission at 433.471408 MHz,
    // starting 35.95 ms after the request ended. Suppressing it was the
    // reproducible cause of the local 6/18 initialization stall.
    return true;
}

constexpr std::uint8_t htv405ShiftedCounter(
    std::uint8_t value,
    std::uint8_t offset
) {
    return static_cast<std::uint8_t>(
        (value & 0x80U) | ((value + offset) & 0x7fU)
    );
}

inline bool htv405RequestMatches(
    const Htv405PairingProfile& profile,
    std::size_t stepIndex,
    const std::array<std::uint8_t, kFrameBytes>& frame,
    std::uint8_t counterOffset = 0,
    bool ignoreCounter = false
) {
    if (stepIndex >= profile.steps.size() || !hasSync(frame) ||
        !hasOrdinaryTrailer(frame)) {
        return false;
    }
    const bool endpointsMatch = stepIndex == 0
        ? endpointEquals(frame, 5, {{0x80, 0x00, 0x00, 0x00}}) &&
            endpointEquals(frame, 9, profile.factoryEndpoint)
        : endpointEquals(frame, 5, profile.valveRoute) &&
            endpointEquals(frame, 9, profile.pairedEndpoint);
    if (!endpointsMatch) {
        return false;
    }
    // During an explicit enrollment sweep the valve advances the first two
    // body bytes as it retries across its RF channels. Those bytes are not a
    // different product or request; byte 4 (0xff) distinguishes the explicit
    // long-press request from the 0x7f cold-boot announcement. Keep accepting
    // later explicit requests so a marginal or colliding assignment can be
    // retried within the same user-initiated window.
    const std::size_t firstComparedBodyByte = stepIndex == 0 ? 2 : 0;
    for (std::size_t index = firstComparedBodyByte; index < 23; ++index) {
        if (stepIndex > 0 && index == 0) {
            if (ignoreCounter) {
                continue;
            }
            if (frame[13] != htv405ShiftedCounter(
                    profile.steps[stepIndex].requestBody[0], counterOffset
                )) {
                return false;
            }
            continue;
        }
        // A selector-2 assignment accepted on a later factory-sweep counter
        // can resume within the initial 01..03 exchange rather than at 01/01.
        // Captures show bytes 4..6 reflecting the missed acknowledgement
        // state while the counter, marker, and remaining request body stay
        // stable. The first successful post-configuration continuation showed
        // the same bounded lag in the 02/82 short-form phase at steps 7..9.
        // Ignore only that state triplet in those two proven ranges; every
        // route, message family, counter, and remaining body byte stays exact.
        const bool resynchronizingInitialPhase =
            stepIndex >= 1 && stepIndex <= 5;
        const bool resynchronizingShortPhase =
            stepIndex >= 7 && stepIndex <= 9;
        // Probe.10 advanced through the recovered short-form transition, then
        // observed the exact selector-2 03/83 message families with the same
        // bounded lag in bytes 4..6. Keep this tolerance confined to the four
        // controller-transition rows immediately after the frozen prefix.
        const bool resynchronizingControllerPhase =
            stepIndex >= 10 && stepIndex <= 13;
        // Probe.12 reached the final 99/9A extended phase. Its first 2C
        // request retained the preceding state bit (00 instead of 80), while
        // the counter, message family, phase marker, and remaining body stayed
        // exact. Tolerate only that one state byte in the four extended rows.
        const bool resynchronizingExtendedPhase =
            stepIndex >= 14 && stepIndex <= 17;
        if ((resynchronizingInitialPhase || resynchronizingShortPhase ||
                resynchronizingControllerPhase) &&
            index >= 4 && index <= 6) {
            continue;
        }
        if (resynchronizingExtendedPhase && index == 4) {
            continue;
        }
        if (frame[13 + index] != profile.steps[stepIndex].requestBody[index]) {
            return false;
        }
    }
    return true;
}

inline bool htv405RetainedRejoinRequestMatches(
    const Htv405PairingProfile& profile,
    const std::array<std::uint8_t, kFrameBytes>& frame
) {
    if (!hasSync(frame) || !hasOrdinaryTrailer(frame) ||
        !endpointEquals(frame, 5, {{0x80, 0x00, 0x00, 0x00}}) ||
        !endpointEquals(frame, 9, profile.factoryEndpoint)) {
        return false;
    }
    // A battery boot preserves the association but changes the explicit
    // enrollment flag from 0xff to 0x7f. The first two body bytes advance as
    // the valve sweeps channels, exactly like the long-press request. Keep
    // every other product and payload byte pinned to the captured profile.
    for (std::size_t index = 2; index < 23; ++index) {
        if (index == 4) {
            if (frame[13 + index] != 0x7fU) {
                return false;
            }
            continue;
        }
        if (frame[13 + index] != profile.steps[0].requestBody[index]) {
            return false;
        }
    }
    return true;
}

inline bool buildHtv405PairingReply(
    const Htv405PairingProfile& profile,
    std::size_t stepIndex,
    const PairingLocalDateTime& localClock,
    std::array<std::uint8_t, kFrameBytes>& frame,
    std::uint8_t counterOffset = 0
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
        frame[9 + index] = profile.companionEndpoint[index];
    }
    for (std::size_t index = 0; index < 23; ++index) {
        frame[13 + index] = profile.steps[stepIndex].replyBody[index];
    }
    if (stepIndex > 0) {
        frame[13] = htv405ShiftedCounter(frame[13], counterOffset);
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
        frame[21] = static_cast<std::uint8_t>((packedTime & 0x7fU) | 0x80U);
        frame[22] = static_cast<std::uint8_t>((packedTime >> 8) | 0x80U);
        frame[23] = static_cast<std::uint8_t>((packedDate & 0x7fU) | 0x80U);
        frame[24] = static_cast<std::uint8_t>(packedDate >> 8);
    }
    writeTrailer(frame, profile.steps[stepIndex].trailerResidual);
    return true;
}

inline bool buildHtv405Selector2ConfigurationReply(
    const Htv405PairingProfile& profile,
    std::array<std::uint8_t, kFrameBytes>& frame,
    std::uint8_t counterOffset = 0
) {
    frame.fill(0);
    for (std::size_t index = 0; index < kSync.size(); ++index) {
        frame[index] = kSync[index];
    }
    for (std::size_t index = 0; index < 4; ++index) {
        frame[5 + index] = profile.pairedEndpoint[index];
        frame[9 + index] = profile.companionEndpoint[index];
    }
    // This command shares the valve transaction counter even though it is a
    // second gateway transmission for the same request. Stock uses 82/10 for
    // request 02/01; a later-sweep enrollment that reaches request 03/01 must
    // therefore receive 83/10, just as its immediate acknowledgement is
    // shifted from 82/41 to 83/41.
    frame[13] = htv405ShiftedCounter(0x82, counterOffset);
    frame[14] = 0x10;
    frame[15] = 0x01;
    frame[16] = 0x01;
    writeTrailer(frame, 0x4f03);
    return true;
}

class Htv405PairingSession {
public:
    explicit Htv405PairingSession(const Htv405PairingProfile& profile)
        : profile_(profile) {}

    void arm(
        std::uint32_t nowMs,
        std::uint32_t durationMs = 120'000,
        bool acceptColdBootStart = false
    ) {
        state_ = PairingSessionState::Armed;
        step_ = 0;
        acceptColdBootStart_ = acceptColdBootStart;
        pending_ = false;
        pendingAdvances_ = false;
        counterOffset_ = 0;
        replyCounterOffset_ = 0;
        counterOffsetKnown_ = false;
        replyStartDelayOverrideUs_ = 0;
        expiresAtMs_ = nowMs + durationMs;
        failureReason_ = PairingFailureReason::None;
    }

    void cancel() {
        state_ = PairingSessionState::Disarmed;
        step_ = 0;
        acceptColdBootStart_ = false;
        pending_ = false;
        pendingAdvances_ = false;
        counterOffset_ = 0;
        replyCounterOffset_ = 0;
        counterOffsetKnown_ = false;
        replyStartDelayOverrideUs_ = 0;
        failureReason_ = PairingFailureReason::None;
    }

    const Htv405PairingStep* claimReply(
        const std::array<std::uint8_t, kFrameBytes>& frame,
        std::uint32_t nowMs
    ) {
        tick(nowMs);
        if (state_ != PairingSessionState::Armed || pending_) {
            return nullptr;
        }
        replyStartDelayOverrideUs_ = 0;
        // Step zero may be retransmitted with a later sweep counter. Once an
        // assignment has been sent, retry it until paired traffic proves that
        // the valve advanced; do not strand the session at step one.
        const bool assignmentRequest = !acceptColdBootStart_ &&
            htv405RequestMatches(profile_, 0, frame);
        const bool coldBootRequest = acceptColdBootStart_ &&
            htv405RetainedRejoinRequestMatches(profile_, frame);
        if (step_ <= 1 && (assignmentRequest || coldBootRequest)) {
            pending_ = true;
            pendingAdvances_ = step_ == 0;
            replyCounterOffset_ = 0;
            claimedAtMs_ = nowMs;
            return &profile_.steps[0];
        }
        if (acceptColdBootStart_ && step_ == 0) {
            return nullptr;
        }
        // A later-sweep assignment can enter controller initialization with
        // its transaction counter already advanced. The 2026-08-23 capture
        // proved that the valve then repeats the established long-form
        // x1/01 -> x1/41 and x1/81 -> x1/C1 phase pair after acknowledging
        // the long x1/10 configuration command. Keep step 6 as a bounded
        // synchronization point: answer only those two proven long forms,
        // without moving the transcript, until the exact short-form request
        // arrives. This continuation is deliberately isolated after the
        // physically validated assignment and configuration exchange.
        if (step_ == kHtv405Selector2ShortFormStepIndex) {
            const auto claimRepeatedPhase = [
                this, &frame, nowMs
            ](std::size_t replyStep) -> const Htv405PairingStep* {
                if (!htv405RequestMatches(
                        profile_, replyStep, frame, 0, true
                    )) {
                    return nullptr;
                }
                const std::uint8_t expected = static_cast<std::uint8_t>(
                    profile_.steps[replyStep].requestBody[0] & 0x7fU
                );
                const std::uint8_t observed = static_cast<std::uint8_t>(
                    frame[13] & 0x7fU
                );
                if (observed < expected || observed - expected > 15) {
                    return nullptr;
                }
                pending_ = true;
                pendingAdvances_ = false;
                replyCounterOffset_ = static_cast<std::uint8_t>(
                    observed - expected
                );
                claimedAtMs_ = nowMs;
                return &profile_.steps[replyStep];
            };
            if (const auto* repeatedPhase = claimRepeatedPhase(
                    kHtv405Selector2PhaseReplyStepIndex
                ); repeatedPhase != nullptr) {
                return repeatedPhase;
            }
            if (const auto* repeatedOrdinary = claimRepeatedPhase(
                    kHtv405Selector2InitialOrdinaryStepIndex
                ); repeatedOrdinary != nullptr) {
                return repeatedOrdinary;
            }
            // Re-anchor the remaining exact transcript when the valve finally
            // emits its selector-2 short form. Only the counter may differ.
            if (htv405RequestMatches(
                    profile_, kHtv405Selector2ShortFormStepIndex,
                    frame, 0, true
                )) {
                const std::uint8_t expected = static_cast<std::uint8_t>(
                    profile_.steps[
                        kHtv405Selector2ShortFormStepIndex
                    ].requestBody[0] & 0x7fU
                );
                const std::uint8_t observed = static_cast<std::uint8_t>(
                    frame[13] & 0x7fU
                );
                if (observed >= expected && observed - expected <= 15) {
                    counterOffset_ = static_cast<std::uint8_t>(
                        observed - expected
                    );
                    counterOffsetKnown_ = true;
                }
            }
        }
        // A successful local association reached logical step 10, then the
        // valve repeated the selector-2 short-form 02/82 phase while advancing
        // its transaction counter. The stock transcript shows that 04/82 must
        // receive 84/C2 in an earlier reply slot than generic acknowledgements.
        // Recover only after the frozen ten-step prefix: map xx/02 and xx/82
        // retries back to their exact captured reply bodies, re-anchor the
        // counter, and leave the logical step unchanged until the valve emits
        // the expected xx/83 transition.
        if (step_ >= 10) {
            std::size_t retryStep = profile_.steps.size();
            if (htv405RequestMatches(profile_, 8, frame, 0, true)) {
                retryStep = 8;
                replyStartDelayOverrideUs_ =
                    kHtv405Selector2ShortRepeatReplyStartDelayUs;
            } else if (htv405RequestMatches(
                    profile_, 7, frame, 0, true
                )) {
                // State 2 is the final ordinary short-form request; state 0/1
                // is a retry of the preceding phase. Their reply payloads are
                // identical apart from the transaction counter.
                retryStep = frame[17] >= 0x02 ? 9 : 7;
            }
            if (retryStep < profile_.steps.size()) {
                const std::uint8_t expected = static_cast<std::uint8_t>(
                    profile_.steps[retryStep].requestBody[0] & 0x7fU
                );
                const std::uint8_t observed = static_cast<std::uint8_t>(
                    frame[13] & 0x7fU
                );
                if (observed >= expected && observed - expected <= 15) {
                    counterOffset_ = static_cast<std::uint8_t>(
                        observed - expected
                    );
                    counterOffsetKnown_ = true;
                    pending_ = true;
                    pendingAdvances_ = false;
                    replyCounterOffset_ = counterOffset_;
                    claimedAtMs_ = nowMs;
                    return &profile_.steps[retryStep];
                }
            }
            replyStartDelayOverrideUs_ = 0;
        }
        // Probe.11 completed the frozen controller-transition prefix through
        // logical step 14. The valve then repeated the proven 03/83
        // authorization pair while advancing its transaction counter, just
        // as it had done for the earlier 02/82 short-form pair. Re-anchor and
        // answer only these exact controller-family retries after step 14;
        // keep the logical transcript parked until the valve advances to the
        // captured AC extended request.
        if (step_ >= 14) {
            std::size_t retryStep = profile_.steps.size();
            if (htv405RequestMatches(profile_, 12, frame, 0, true)) {
                retryStep = 12;
            } else if (htv405RequestMatches(
                    profile_, 11, frame, 0, true
                )) {
                // State 2 is the final ordinary authorization request; state
                // 0/1 retries the preceding phase. Their message family is
                // otherwise identical.
                retryStep = frame[17] >= 0x02 ? 13 : 11;
            }
            if (retryStep < profile_.steps.size()) {
                const std::uint8_t expected = static_cast<std::uint8_t>(
                    profile_.steps[retryStep].requestBody[0] & 0x7fU
                );
                const std::uint8_t observed = static_cast<std::uint8_t>(
                    frame[13] & 0x7fU
                );
                if (observed >= expected && observed - expected <= 15) {
                    counterOffset_ = static_cast<std::uint8_t>(
                        observed - expected
                    );
                    counterOffsetKnown_ = true;
                    pending_ = true;
                    pendingAdvances_ = false;
                    replyCounterOffset_ = counterOffset_;
                    claimedAtMs_ = nowMs;
                    return &profile_.steps[retryStep];
                }
            }
        }
        // Once the final extended phase begins, a missed acknowledgement can
        // make the valve repeat any already-completed 99/9A request with a
        // newer counter. Answer only earlier rows from this exact four-row
        // family, re-anchor the counter, and keep the logical step unchanged.
        // The current row still falls through to the normal transcript matcher
        // so it advances exactly once.
        if (step_ >= 15) {
            const std::size_t extendedEnd = step_ < profile_.steps.size()
                ? step_
                : profile_.steps.size();
            for (std::size_t retryStep = 14;
                 retryStep < extendedEnd;
                 ++retryStep) {
                if (!htv405RequestMatches(
                        profile_, retryStep, frame, 0, true
                    )) {
                    continue;
                }
                const std::uint8_t expected = static_cast<std::uint8_t>(
                    profile_.steps[retryStep].requestBody[0] & 0x7fU
                );
                const std::uint8_t observed = static_cast<std::uint8_t>(
                    frame[13] & 0x7fU
                );
                if (observed < expected || observed - expected > 15) {
                    continue;
                }
                counterOffset_ = static_cast<std::uint8_t>(
                    observed - expected
                );
                counterOffsetKnown_ = true;
                pending_ = true;
                pendingAdvances_ = false;
                replyCounterOffset_ = counterOffset_;
                claimedAtMs_ = nowMs;
                return &profile_.steps[retryStep];
            }
        }
        // Assignment on a later factory-sweep pass does not skip logical
        // initialization stages. Instead, the valve starts the same sequence
        // with its transaction counter shifted. Infer that bounded offset
        // from the first paired request while retaining the request phase and
        // payload checks, then apply it consistently to the entire exchange.
        std::size_t matchedStep = profile_.steps.size();
        if (step_ == 1 && !counterOffsetKnown_) {
            for (std::size_t candidate = 1; candidate <= 5; ++candidate) {
                if (!htv405RequestMatches(
                        profile_, candidate, frame, 0, true
                    )) {
                    continue;
                }
                const std::uint8_t expected = static_cast<std::uint8_t>(
                    profile_.steps[candidate].requestBody[0] & 0x7fU
                );
                const std::uint8_t observed = static_cast<std::uint8_t>(
                    frame[13] & 0x7fU
                );
                if (observed < expected || observed - expected > 15) {
                    continue;
                }
                counterOffset_ = static_cast<std::uint8_t>(observed - expected);
                counterOffsetKnown_ = true;
                matchedStep = candidate;
                break;
            }
        }
        if (matchedStep == profile_.steps.size()) {
            for (std::size_t candidate = step_;
                 candidate < profile_.steps.size();
                 ++candidate) {
                if (htv405RequestMatches(
                        profile_, candidate, frame, counterOffset_
                    )) {
                    matchedStep = candidate;
                    break;
                }
            }
        }
        if (matchedStep < profile_.steps.size()) {
            step_ = matchedStep;
            const auto& step = profile_.steps[step_];
            if (!step.replyExpected) {
                ++step_;
                if (step_ == profile_.steps.size()) {
                    state_ = PairingSessionState::Completed;
                }
                return nullptr;
            }
            pending_ = true;
            pendingAdvances_ = true;
            replyCounterOffset_ = counterOffset_;
            claimedAtMs_ = nowMs;
            return &step;
        }
        for (std::size_t index = 0; index < step_; ++index) {
            if (htv405RequestMatches(profile_, index, frame)) {
                return nullptr;
            }
        }
        return nullptr;
    }

    bool finishReply(bool success, std::uint32_t nowMs) {
        if (state_ != PairingSessionState::Armed || !pending_ || !success) {
            fail(PairingFailureReason::ReplyFailed);
            return false;
        }
        const std::uint32_t replyDeadlineMs =
            step_ == kHtv405Selector2ConfigurationStepIndex
            ? kHtv405Selector2ConfigurationReplyDeadlineMs
            : kPairingReplyDeadlineMs;
        if (nowMs - claimedAtMs_ > replyDeadlineMs) {
            fail(PairingFailureReason::ReplyDeadlineMissed);
            return false;
        }
        pending_ = false;
        if (pendingAdvances_) {
            ++step_;
        }
        pendingAdvances_ = false;
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
    std::size_t completedSteps() const { return step_; }
    bool pending() const { return pending_; }
    PairingFailureReason failureReason() const { return failureReason_; }
    std::uint8_t counterOffset() const { return counterOffset_; }
    std::uint8_t replyCounterOffset() const { return replyCounterOffset_; }
    bool counterOffsetKnown() const { return counterOffsetKnown_; }
    std::uint32_t replyStartDelayOverrideUs() const {
        return replyStartDelayOverrideUs_;
    }

private:
    void fail(PairingFailureReason reason) {
        state_ = PairingSessionState::Failed;
        pending_ = false;
        pendingAdvances_ = false;
        counterOffset_ = 0;
        replyCounterOffset_ = 0;
        counterOffsetKnown_ = false;
        replyStartDelayOverrideUs_ = 0;
        failureReason_ = reason;
    }

    const Htv405PairingProfile& profile_;
    PairingSessionState state_ = PairingSessionState::Disarmed;
    PairingFailureReason failureReason_ = PairingFailureReason::None;
    std::size_t step_ = 0;
    std::uint32_t expiresAtMs_ = 0;
    std::uint32_t claimedAtMs_ = 0;
    bool pending_ = false;
    bool pendingAdvances_ = false;
    std::uint8_t counterOffset_ = 0;
    std::uint8_t replyCounterOffset_ = 0;
    bool counterOffsetKnown_ = false;
    std::uint32_t replyStartDelayOverrideUs_ = 0;
    bool acceptColdBootStart_ = false;
};

}  // namespace rainpoint
