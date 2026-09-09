#include <array>
#include <cassert>
#include <cstdint>
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
int main() {
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

}
