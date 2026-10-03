#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>

#include "rainpoint_htv145_pairing.h"

namespace {

std::array<std::uint8_t, rainpoint::kFrameBytes> fromHex(
    const std::string& value
) {
    if (value.size() != rainpoint::kFrameBytes * 2) {
        throw std::invalid_argument("unexpected frame length");
    }
    std::array<std::uint8_t, rainpoint::kFrameBytes> result{};
    for (std::size_t index = 0; index < result.size(); ++index) {
        result[index] = static_cast<std::uint8_t>(
            std::stoul(value.substr(index * 2, 2), nullptr, 16)
        );
    }
    return result;
}

}  // namespace

// Synthetic endpoints; captured bodies and original CRC residues preserved.
int main(int argc, char** argv) {
    static_assert(
        rainpoint::htv145::kTargetFactoryCounter == 2,
        "compile this regression with the counter-2 research define"
    );
    rainpoint::htv145::PairingProfile profile{};
    assert(rainpoint::htv145::buildProfile(
        {{0x31, 0xc2, 0xd3, 0x8f}},
        {{0xa1, 0xb2, 0xc3, 0x80}},
        {{0x21, 0xb2, 0xc3, 0x80}},
        profile
    ));
    if (argc == 2 && std::string(argv[1]) == "--replay") {
        // Offline fixture driver. These partial IQ transcripts start after
        // assignment; supply only that synthetic prerequisite, then consume
        // every recorded request at its relative millisecond observation time.
        rainpoint::htv145::PairingSession replay(profile);
        replay.arm(0);
        const auto assignment = fromHex(
            "79f4882f288000000031c2d38f82008402ff8f970080bf06000000000000000000000000273d");
        assert(replay.claimReply(assignment, 1) == &profile.steps[0]);
        assert(replay.finishReply(true, 2));
        const rainpoint::PairingLocalDateTime clock{2026, 9, 1, 12, 12, 48};
        std::uint32_t observedAtMs;
        int expectedStep;
        std::string requestHex, expectedReplyHex;
        std::size_t rows = 0;
        while (std::cin >> observedAtMs >> expectedStep >> requestHex >> expectedReplyHex) {
            const auto request = fromHex(requestHex);
            const auto* claimed = replay.claimReply(request, observedAtMs);
            if (expectedStep < 0) {
                assert(claimed == nullptr); // recorded configuration ACK
                assert(replay.completedSteps() == 3);
            } else {
                assert(claimed == &profile.steps[expectedStep]);
                std::array<std::uint8_t, rainpoint::kFrameBytes> actual{};
                assert(replay.buildClaimedReply(clock, actual));
                assert(rainpoint::nativeSequence(actual) == rainpoint::nativeSequence(request));
                assert(rainpoint::hasOrdinaryTrailer(actual));
                if (expectedReplyHex != "-") {
                    assert(actual == fromHex(expectedReplyHex));
                }
                assert(replay.finishReply(true, observedAtMs + 1));
            }
            ++rows;
        }
        assert(std::cin.eof());
        assert(rows == 8);
        assert(replay.planReplyRetries() == 4);
        assert(replay.completedSteps() == 5);
        replay.tick(119'999);
        assert(replay.state() == rainpoint::PairingSessionState::Armed);
        replay.tick(120'000);
        assert(replay.state() == rainpoint::PairingSessionState::Failed);
        assert(replay.failureReason() == rainpoint::PairingFailureReason::SessionTimeout);
        assert(replay.completedSteps() == 5); // no fabricated terminal completion
        std::cout << "recorded_rows=8 plan_retries=4 completed_steps=5 expired=1\n";
        return 0;
    }
    assert(argc == 1);
    assert(rainpoint::htv145::replyStartDelayUs(0) == 49'650);
    assert(rainpoint::htv145::replyStartDelayUs(1) == 68'700);
    assert(rainpoint::htv145::replyStartDelayUs(3) == 53'300);
    assert(rainpoint::htv145::replyStartDelayUs(4) == 52'550);
    assert(rainpoint::htv145::replyStartDelayUs(5) == 47'500);
    assert(rainpoint::htv145::kRoutineChannelCenterHz == 434'276'052);
    assert(rainpoint::htv145::kConfigurationWakeSymbols == 2'400);
    assert(
        rainpoint::htv145::kStep1PostFrameLowHoldAdjustmentUs == 115
    );
    assert(
        rainpoint::htv145::kConfigurationPostFrameLowHoldAdjustmentUs == 115
    );
    assert(
        rainpoint::htv145::kStep4PostFrameLowHoldAdjustmentUs == 115
    );
    assert(
        rainpoint::htv145::kConfigurationReplyStartDelayUs == 2'848'400
    );

    const auto factory0 = fromHex(
        "79f4882f288000000031c2d38f80808402ff8f970080bf0600000000000000000000000057be"
    );
    const auto factory1 = fromHex(
        "79f4882f288000000031c2d38f81008402ff8f970080bf060000000000000000000000000030"
    );
    const auto factory2 = fromHex(
        "79f4882f288000000031c2d38f82008402ff8f970080bf06000000000000000000000000273d"
    );
    const auto request1 = fromHex(
        "79f4882f28a1b2c380b1c2d38f828107862580804f8000000040800056800000000000001c71"
    );

    rainpoint::htv145::PairingSession session(profile);
    session.arm(0);
    assert(session.claimReply(factory0, 1) == nullptr);
    assert(session.claimReply(factory1, 1'500) == nullptr);
    assert(!session.assignmentLocked());
    assert(session.claimReply(factory2, 5'500) == &profile.steps[0]);
    assert(session.finishReply(true, 5'501));
    assert(session.assignmentLocked());
    assert(session.acceptedFactoryCounter() == 2);
    assert(session.claimReply(request1, 7'000) == &profile.steps[1]);
    assert(session.stage0Accepted());

    const rainpoint::PairingLocalDateTime capturedClock{
        2026, 9, 1, 12, 12, 48,
    };
    // Automatic discovery must produce byte-identical replies to explicitly
    // supplying the identity; it must not alter the proven RF transcript.
    rainpoint::htv145::PairingProfile discovered{};
    assert(rainpoint::htv145::initializeAutomaticProfile(
        profile.controllerEndpoint, profile.companionEndpoint, discovered));
    auto malformed = factory2;
    malformed[17] ^= 1;
    assert(!rainpoint::htv145::adoptFactoryAnnouncement(malformed, discovered));
    rainpoint::writeTrailer(malformed, rainpoint::trailerResidual(factory2));
    assert(!rainpoint::htv145::adoptFactoryAnnouncement(malformed, discovered));
    auto pairedAnnouncement = factory2;
    pairedAnnouncement[9] |= 0x80;
    rainpoint::writeTrailer(pairedAnnouncement, rainpoint::trailerResidual(factory2));
    assert(!rainpoint::htv145::adoptFactoryAnnouncement(pairedAnnouncement, discovered));
    assert(discovered.factoryEndpoint[0] == 0);
    assert(!rainpoint::htv145::adoptFactoryAnnouncement(request1, discovered));
    assert(rainpoint::htv145::adoptFactoryAnnouncement(factory0, discovered));
    assert(discovered.factoryEndpoint == profile.factoryEndpoint);
    rainpoint::htv145::PairingSession discoveredSession(discovered);
    discoveredSession.arm(0);
    assert(discoveredSession.claimReply(factory0, 1) == nullptr);
    assert(discoveredSession.claimReply(factory1, 1'500) == nullptr);
    assert(discoveredSession.claimReply(factory2, 5'500) == &discovered.steps[0]);
    for (std::size_t index = 0; index < profile.steps.size(); ++index) {
        std::array<std::uint8_t, rainpoint::kFrameBytes> expected{}, actual{};
        const bool built = rainpoint::htv145::buildReply(profile, index, capturedClock, expected);
        assert(built == rainpoint::htv145::buildReply(discovered, index, capturedClock, actual));
        assert(actual == expected);
    }
    std::array<std::uint8_t, rainpoint::kFrameBytes> reply{};
    assert(rainpoint::htv145::buildReply(
        profile, 0, capturedClock, reply
    ));
    assert(reply == fromHex(
        "79f4882f28b1c2d38fa1b2c380824085850086700098e1a10d0100800000000000000000be64"
    ));
    assert(rainpoint::htv145::buildReply(
        profile, 1, capturedClock, reply
    ));
    assert(reply == fromHex(
        "79f4882f28b1c2d38fa1b2c38082c1010000800000000000000000000000000000000000e3f2"
    ));
    assert(rainpoint::htv145::buildReply(
        profile, 3, capturedClock, reply
    ));
    assert(reply == fromHex(
        "79f4882f28b1c2d38fa1b2c380834287802c0105000f0000000000000000000000000000a968"
    ));
    assert(rainpoint::htv145::buildReply(
        profile, 4, capturedClock, reply
    ));
    assert(reply == fromHex(
        "79f4882f28b1c2d38fa1b2c38083c30080000000000000000000000000000000000000008d4b"
    ));
    assert(rainpoint::htv145::buildReply(
        profile, 5, capturedClock, reply
    ));
    assert(reply == fromHex(
        "79f4882f28b1c2d38fa1b2c380846c818019000000000000000000000000000000000000a48f"
    ));
    assert(session.finishReply(true, 7'001));
    const auto configurationResponse = fromHex("79f4882f28a1b2c380b1c2d38f8150008000000000000000000000000000000000000000303d");
    const auto request3 = fromHex("79f4882f28a1b2c380b1c2d38f830281060080000000000000000000000000000000000012c3");
    const auto request4 = fromHex("79f4882f28a1b2c380b1c2d38f83830186008000000000000000000000000000000000001189");
    const auto request5 = fromHex("79f4882f28a1b2c380b1c2d38f842c80990000000000000000000000000000000000000077cd");
    assert(session.claimReply(request4, 8'000) == nullptr);  // out of order
    assert(session.claimReply(configurationResponse, 9'000) == nullptr); // no reply
    assert(session.completedSteps() == 3);
    assert(session.claimReply(request3, 10'000) == &profile.steps[3]);
    assert(session.finishReply(true, 10'001));
    assert(session.claimReply(request4, 11'000) == &profile.steps[4]);
    assert(session.finishReply(true, 11'001));
    assert(session.completedSteps() == 5);
    assert(session.state() == rainpoint::PairingSessionState::Armed);
    // Captured missed-reply recovery: native 06 repeats at phases 8..11.
    // Answer the last stage without advancing logical progress or reopening
    // assignment. This must not change any first-response bytes above.
    auto retry = request4;
    retry[13] = 0x84;
    retry[14] = 0x03;
    rainpoint::writeTrailer(retry, 0x4f03);
    assert(session.claimReply(retry, 11'900) == &profile.steps[4]);
    assert(session.finishReply(true, 11'901));
    assert(session.completedSteps() == 5);
    // Existing no-retry completion remains covered with a separate session.
    session.arm(0);
    assert(session.claimReply(factory2, 1) == &profile.steps[0]);
    assert(session.finishReply(true, 2));
    assert(session.claimReply(request1, 3) == &profile.steps[1]);
    assert(session.finishReply(true, 4));
    assert(session.claimReply(configurationResponse, 5) == nullptr);
    assert(session.claimReply(request3, 6) == &profile.steps[3]);
    assert(session.finishReply(true, 7));
    assert(session.claimReply(request4, 8) == &profile.steps[4]);
    assert(session.finishReply(true, 9));
    auto corrupt = request5; corrupt[37] ^= 1;
    assert(session.claimReply(corrupt, 12'000) == nullptr);
    assert(session.claimReply(request5, 12'100) == &profile.steps[5]);
    assert(session.finishReply(true, 12'101));
    assert(session.state() == rainpoint::PairingSessionState::Completed);
    rainpoint::htv145::PairingSession rejected(profile);
    rejected.arm(0);
    assert(rejected.claimReply(factory2, 1) == &profile.steps[0]);
    assert(rejected.finishReply(true, 2));
    assert(rejected.claimReply(factory0, 3) == nullptr);
    assert(rejected.stage0Rejected());
    assert(rejected.state() == rainpoint::PairingSessionState::Failed);

    const auto prepare = [&](rainpoint::htv145::PairingSession& trial,
                             std::uint32_t startMs = 0) {
        trial.arm(startMs);
        const std::array<std::array<std::uint8_t, rainpoint::kFrameBytes>, 5> requests{
            factory2, request1, configurationResponse, request3, request4};
        for (std::size_t i = 0; i < requests.size(); ++i) {
            const auto* claimed = trial.claimReply(requests[i], startMs + 100 + i * 1'000);
            if (i == 2) { assert(claimed == nullptr); continue; }
            assert(claimed == &profile.steps[i]);
            std::array<std::uint8_t, rainpoint::kFrameBytes> frozen{}, actual{};
            assert(rainpoint::htv145::buildReply(profile, i, capturedClock, frozen));
            assert(trial.buildClaimedReply(capturedClock, actual));
            assert(frozen == actual); // byte-identical first responses, all stages
            assert(trial.finishReply(true, startMs + 101 + i * 1'000));
        }
        assert(trial.completedSteps() == 5);
        assert(trial.requiresReceiveEndCapture());
    };
    const auto withPhase = [](auto frame, std::uint8_t phase) {
        frame[13] = static_cast<std::uint8_t>((frame[13] & 0xe0U) | (phase >> 1U));
        frame[14] = static_cast<std::uint8_t>((frame[14] & 0x7fU) | ((phase & 1U) << 7U));
        rainpoint::writeTrailer(frame, 0x4f03);
        return frame;
    };
    rainpoint::htv145::PairingSession retrySession(profile);
    prepare(retrySession);
    auto bad = withPhase(request4, 8);
    bad[37] ^= 1;
    assert(retrySession.claimReply(bad, 5'000) == nullptr);
    for (const std::size_t offset : {5U, 9U, 13U, 14U, 15U, 16U, 17U, 18U, 35U}) {
        bad = withPhase(request4, 8);
        // At byte 13 mutate a non-phase header bit; the rest are exact gates.
        bad[offset] ^= offset == 13 ? 0x20 : 1;
        rainpoint::writeTrailer(bad, 0x4f03);
        assert(retrySession.claimReply(bad, 5'000) == nullptr);
    }
    assert(retrySession.claimReply(withPhase(request4, 6), 5'000) == nullptr);
    assert(retrySession.claimReply(withPhase(request4, 12), 5'000) == nullptr);
    assert(retrySession.claimReply(request1, 5'000) == nullptr); // no prefix rewind
    for (std::uint8_t phase = 8; phase <= 11; ++phase) {
        auto request = withPhase(request4, phase);
        assert(retrySession.claimReply(request, 5'000 + phase * 100) == &profile.steps[4]);
        assert(retrySession.claimReply(request, 5'001 + phase * 100) == nullptr); // in flight
        assert(retrySession.buildClaimedReply(capturedClock, reply));
        assert(rainpoint::nativeSequence(reply) == phase);
        assert(rainpoint::hasOrdinaryTrailer(reply));
        auto frozen = reply;
        assert(rainpoint::htv145::buildReply(profile, 4, capturedClock, frozen));
        for (std::size_t i = 0; i < 36; ++i) {
            if (i != 13 && i != 14) assert(reply[i] == frozen[i]);
        }
        assert(retrySession.finishReply(true, 5'010 + phase * 100));
        assert(retrySession.completedSteps() == 5);
        assert(retrySession.planReplyRetries() == phase - 7);
    }
    assert(retrySession.claimReply(withPhase(request4, 11), 7'000) == nullptr); // retry cap
    assert(retrySession.claimReply(request5, 7'000) == nullptr); // stale terminal phase
    const auto advancedTerminal = withPhase(request5, 12);
    assert(retrySession.claimReply(advancedTerminal, 7'000) == &profile.steps[5]);
    assert(retrySession.buildClaimedReply(capturedClock, reply));
    assert(rainpoint::nativeSequence(reply) == 12);
    assert(retrySession.finishReply(true, 7'010));
    assert(retrySession.state() == rainpoint::PairingSessionState::Completed);
    assert(!retrySession.requiresReceiveEndCapture());
    assert(retrySession.claimReply(advancedTerminal, 7'020) == nullptr);

    prepare(retrySession);
    assert(retrySession.claimReply(request4, 5'000) == &profile.steps[4]); // exact repeat
    assert(retrySession.buildClaimedReply(capturedClock, reply));
    assert(rainpoint::nativeSequence(reply) == 7);
    assert(retrySession.finishReply(true, 5'001));
    assert(retrySession.completedSteps() == 5);
    assert(retrySession.claimReply(withPhase(request4, 8), 14'102) == nullptr); // window elapsed
    assert(retrySession.claimReply(request5, 14'103) == &profile.steps[5]); // bounded retries do not block tail
    assert(!retrySession.finishReply(true, 120'000)); // session deadline still wins
    assert(retrySession.failureReason() == rainpoint::PairingFailureReason::SessionTimeout);
    retrySession.cancel();
    assert(!retrySession.requiresReceiveEndCapture());
    assert(!retrySession.buildClaimedReply(capturedClock, reply));
    assert(retrySession.claimReply(request4, 120'001) == nullptr);
    prepare(retrySession);
    assert(retrySession.planReplyRetries() == 0);
    assert(retrySession.claimReply(withPhase(request4, 8), 5'000) == &profile.steps[4]);
    assert(!retrySession.finishReply(true, 6'000)); // reply deadline, not just session deadline
    assert(retrySession.failureReason() == rainpoint::PairingFailureReason::ReplyDeadlineMissed);

    // Missing continuation never upgrades partial enrollment to completion.
    prepare(retrySession);
    retrySession.tick(119'999);
    assert(retrySession.state() == rainpoint::PairingSessionState::Armed);
    assert(retrySession.completedSteps() == 5);
    retrySession.tick(120'000);
    assert(retrySession.state() == rainpoint::PairingSessionState::Failed);
    assert(retrySession.failureReason() == rainpoint::PairingFailureReason::SessionTimeout);
    assert(retrySession.claimReply(request5, 120'001) == nullptr);

    // A delayed terminal request still completes before the session deadline,
    // even after the retry window closed. Exactly 250 ms is permitted.
    prepare(retrySession);
    assert(retrySession.claimReply(withPhase(request4, 8), 5'000) == &profile.steps[4]);
    assert(retrySession.finishReply(true, 5'001));
    assert(retrySession.claimReply(withPhase(request4, 9), 14'102) == nullptr);
    assert(retrySession.claimReply(withPhase(request5, 9), 119'749) == &profile.steps[5]);
    assert(retrySession.finishReply(true, 119'999));
    assert(retrySession.state() == rainpoint::PairingSessionState::Completed);

    // Window is inclusive at 10 seconds and is measured from the first reply,
    // not extended by subsequent retries. Rejecting a late packet is inert.
    prepare(retrySession);
    assert(retrySession.claimReply(withPhase(request4, 8), 14'101) == &profile.steps[4]);
    assert(retrySession.finishReply(true, 14'102));
    assert(retrySession.claimReply(withPhase(request4, 9), 14'103) == nullptr);
    assert(retrySession.planReplyRetries() == 1);
    assert(retrySession.claimReply(withPhase(request5, 9), 14'104) == &profile.steps[5]);
    assert(retrySession.finishReply(true, 14'105));

    // Four exact repeats consume the same bounded retry budget as advancing
    // phases. They preserve full reply bytes and do not advance enrollment.
    prepare(retrySession);
    for (std::uint8_t attempt = 1; attempt <= 4; ++attempt) {
        assert(retrySession.claimReply(request4, 5'000 + attempt * 100) == &profile.steps[4]);
        assert(retrySession.buildClaimedReply(capturedClock, reply));
        std::array<std::uint8_t, rainpoint::kFrameBytes> frozen{};
        assert(rainpoint::htv145::buildReply(profile, 4, capturedClock, frozen));
        assert(reply == frozen);
        assert(retrySession.finishReply(true, 5'001 + attempt * 100));
        assert(retrySession.completedSteps() == 5);
        assert(retrySession.planReplyRetries() == attempt);
    }
    assert(retrySession.claimReply(request4, 6'000) == nullptr);
    assert(retrySession.claimReply(request5, 6'001) == &profile.steps[5]);
    assert(retrySession.finishReply(true, 6'002));

    // Retried terminal matching preserves every non-phase gate. Corrupted
    // identity, reserved bits, command, native length, data and padding cannot
    // consume the valid next terminal request or mutate progress/retry budget.
    prepare(retrySession);
    assert(retrySession.claimReply(withPhase(request4, 8), 5'000) == &profile.steps[4]);
    assert(retrySession.finishReply(true, 5'001));
    const auto terminal9 = withPhase(request5, 9);
    for (std::size_t offset = 5; offset < 36; ++offset) {
        bad = terminal9;
        bad[offset] ^= offset == 13 ? 0x20 : 1;
        rainpoint::writeTrailer(bad, rainpoint::trailerResidual(terminal9));
        assert(retrySession.claimReply(bad, 5'100) == nullptr);
        assert(retrySession.completedSteps() == 5);
        assert(retrySession.planReplyRetries() == 1);
        assert(retrySession.state() == rainpoint::PairingSessionState::Armed);
    }
    for (std::uint8_t phase : {7, 8, 10, 63, 0}) {
        assert(retrySession.claimReply(withPhase(request5, phase), 5'100) == nullptr);
    }
    assert(retrySession.claimReply(terminal9, 5'101) == &profile.steps[5]);
    assert(retrySession.buildClaimedReply(capturedClock, reply));
    assert(rainpoint::nativeSequence(reply) == 9);
    assert(retrySession.finishReply(true, 5'102));

    // The frozen prefix begins plan phase 7; the source-only retry policy permits +4;
    // phase wrap is intentionally unreachable. Do not broaden the profile to
    // manufacture a successful 63->0 pairing that has never been observed.
    prepare(retrySession);
    for (std::uint8_t phase : {63, 0, 1, 2}) {
        assert(retrySession.claimReply(withPhase(request4, phase), 5'000) == nullptr);
    }
    assert(retrySession.planReplyRetries() == 0);
    assert(retrySession.claimReply(request5, 5'001) == &profile.steps[5]);
    assert(retrySession.finishReply(true, 5'002));

    // Clock rollover is a different kind of wrap and is valid: retry-window
    // arithmetic and whole-session expiry must survive uint32_t millis wrap.
    constexpr std::uint32_t nearWrap = 0xfffff000U;
    prepare(retrySession, nearWrap);
    assert(retrySession.claimReply(withPhase(request4, 8), nearWrap + 5'000U) == &profile.steps[4]);
    assert(retrySession.finishReply(true, nearWrap + 5'001U));
    assert(retrySession.claimReply(withPhase(request5, 9), nearWrap + 6'000U) == &profile.steps[5]);
    assert(retrySession.finishReply(true, nearWrap + 6'001U));
    assert(retrySession.state() == rainpoint::PairingSessionState::Completed);
    prepare(retrySession, nearWrap);
    retrySession.tick(nearWrap + 119'999U);
    assert(retrySession.state() == rainpoint::PairingSessionState::Armed);
    retrySession.tick(nearWrap + 120'000U);
    assert(retrySession.failureReason() == rainpoint::PairingFailureReason::SessionTimeout);

}
