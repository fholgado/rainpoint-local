#include <array>
#include <cassert>
#include <cstdint>
#include <string>
#include "rainpoint_htv145_pairing.h"

// Redacted frames from htv145_selector2_stock_pairing_control_20260905.json.
// Exercise the real firmware builder and state machine against the complete
// successful stock transcript, including the branch-specific clock markers.
auto fromHex(const std::string& value) {
    std::array<std::uint8_t, rainpoint::kFrameBytes> result{};
    assert(value.size() == result.size() * 2);
    for (std::size_t i = 0; i < result.size(); ++i)
        result[i] = static_cast<std::uint8_t>(std::stoul(value.substr(i * 2, 2), nullptr, 16));
    return result;
}

int main() {
    static_assert(rainpoint::htv145::kTargetFactoryCounter == 0);
    static_assert(rainpoint::htv145::kAssignmentSelector == 2);
    static_assert(rainpoint::htv145::kAssignedChannel == 4);
    static_assert(rainpoint::htv145::kInitialChannelCenterHz == 433'506'719);
    static_assert(rainpoint::htv145::kRoutineChannelCenterHz == 433'396'052);
    static_assert(rainpoint::htv145::kStep4FifoActiveTailDelayUs == 905);
    rainpoint::htv145::PairingProfile profile{};
    assert(rainpoint::htv145::buildProfile(
        {{0x31, 0xc2, 0xd3, 0x8f}}, {{0xa1, 0xb2, 0xc3, 0x80}},
        {{0x21, 0xb2, 0xc3, 0x80}}, profile));
    const rainpoint::PairingLocalDateTime capturedClock{2026, 9, 5, 13, 54, 46};
    std::array<std::uint8_t, rainpoint::kFrameBytes> reply{};
    rainpoint::htv145::PairingSession session(profile);
    session.arm(0, 30'000);
    const auto request0 = fromHex("79f4882f288000000031c2d38f80808402ff8f970080bf0600000000000000000000000057be");
    assert(session.claimReply(request0, 1) == &profile.steps[0]);
    assert(rainpoint::htv145::buildReply(profile, 0, capturedClock, reply));
    assert(reply == fromHex("79f4882f28b1c2d38fa1b2c38080c0858500827000d7eea50d0300800000000000000000fdf8"));
    assert(session.finishReply(true, 2));
    const auto request1 = fromHex("79f4882f28a1b2c380b1c2d38f810107822580804f8000000040800056800000000000005725");
    assert(session.claimReply(request1, 2001) == &profile.steps[1]);
    assert(rainpoint::htv145::buildReply(profile, 1, capturedClock, reply));
    assert(reply == fromHex("79f4882f28b1c2d38fa1b2c3808141010000800000000000000000000000000000000000f67a"));
    assert(session.finishReply(true, 2002));
    assert(rainpoint::htv145::buildConfigurationReply(profile, reply));
    assert(reply == fromHex("79f4882f28b1c2d38fa1b2c3808110010100000000000000000000000000000000000000a902"));
    const auto request2 = fromHex("79f4882f28a1b2c380b1c2d38f8150008000000000000000000000000000000000000000303d");
    assert(session.claimReply(request2, 5'000) == nullptr);
    assert(session.completedSteps() == 3);
    const auto request3 = fromHex("79f4882f28a1b2c380b1c2d38f81828102008000000000000000000000000000000000003c9c");
    assert(session.claimReply(request3, 6001) == &profile.steps[3]);
    assert(rainpoint::htv145::buildReply(profile, 3, capturedClock, reply));
    assert(reply == fromHex("79f4882f28b1c2d38fa1b2c38081c287802c0105000f0000000000000000000000000000d9eb"));
    assert(session.finishReply(true, 6002));
    const auto request4 = fromHex("79f4882f28a1b2c380b1c2d38f820301820080000000000000000000000000000000000018db");
    assert(session.claimReply(request4, 8001) == &profile.steps[4]);
    assert(rainpoint::htv145::buildReply(profile, 4, capturedClock, reply));
    assert(reply == fromHex("79f4882f28b1c2d38fa1b2c3808243008000000000000000000000000000000000000000dac5"));
    assert(session.finishReply(true, 8002));
    const auto request5 = fromHex("79f4882f28a1b2c380b1c2d38f82ac8099000000000000000000000000000000000000000b53");
    assert(session.claimReply(request5, 10001) == &profile.steps[5]);
    assert(rainpoint::htv145::buildReply(profile, 5, capturedClock, reply));
    assert(reply == fromHex("79f4882f28b1c2d38fa1b2c38082ec818019000000000000000000000000000000000000d811"));
    assert(session.finishReply(true, 10002));
    assert(session.stage0Accepted());
    assert(session.completedSteps() == 6);
    assert(session.state() == rainpoint::PairingSessionState::Completed);
    // A missing terminal request must remain incomplete, despite the success LED.
    session.arm(0);
    for (const auto& request : {request0, request1, request2, request3, request4}) {
        if (session.claimReply(request, 10)) assert(session.finishReply(true, 11));
    }
    assert(session.completedSteps() == 5);
    assert(session.state() == rainpoint::PairingSessionState::Armed);
    auto wrongBranch = request1;
    wrongBranch[16] = 0x86;
    rainpoint::writeTrailer(wrongBranch, 0x4f03);
    assert(!rainpoint::htv145::requestMatches(profile, 1, wrongBranch));
    auto corrupt = request5;
    corrupt.back() ^= 1;
    assert(!rainpoint::htv145::requestMatches(profile, 5, corrupt));
    // Live time still changes; do not replay the September 5 timestamp.
    const rainpoint::PairingLocalDateTime anotherClock{2026, 9, 6, 8, 2, 4};
    assert(rainpoint::htv145::buildReply(profile, 0, anotherClock, reply));
    assert(reply[21] == 0xc2 && reply[22] == 0xc0);
    assert(reply[23] == 0xa6 && reply[24] == 0x0d);
    assert(rainpoint::hasOrdinaryTrailer(reply));
}
