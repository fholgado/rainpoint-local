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

int main() {
    static_assert(
        rainpoint::htv145::kTargetFactoryCounter == 2,
        "compile this regression with the counter-2 research define"
    );
    rainpoint::htv145::PairingProfile profile{};
    assert(rainpoint::htv145::buildProfile(
        {{0x34, 0x2d, 0x00, 0x8f}},
        {{0xb9, 0x84, 0x02, 0x80}},
        {{0x39, 0x84, 0x02, 0x80}},
        profile
    ));
    assert(rainpoint::htv145::replyStartDelayUs(0) == 49'650);
    assert(rainpoint::htv145::replyStartDelayUs(1) == 68'700);
    assert(rainpoint::htv145::replyStartDelayUs(3) == 53'300);
    assert(rainpoint::htv145::replyStartDelayUs(4) == 52'550);
    assert(rainpoint::htv145::replyStartDelayUs(5) == 47'500);
    assert(rainpoint::htv145::kRoutineChannelCenterHz == 434'276'052);
    assert(rainpoint::htv145::kConfigurationWakeSymbols == 2'464);
    assert(
        rainpoint::htv145::kConfigurationReplyStartDelayUs == 2'851'050
    );

    const auto factory0 = fromHex(
        "79f4882f2880000000342d008f80808402ff8f970080bf060000000000000000000000007ccf"
    );
    const auto factory1 = fromHex(
        "79f4882f2880000000342d008f81008402ff8f970080bf060000000000000000000000002b41"
    );
    const auto factory2 = fromHex(
        "79f4882f2880000000342d008f82008402ff8f970080bf060000000000000000000000000c4c"
    );
    const auto request1 = fromHex(
        "79f4882f28b9840280b42d008f828107862580804f8000000040800056800000000000004301"
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
    std::array<std::uint8_t, rainpoint::kFrameBytes> reply{};
    assert(rainpoint::htv145::buildReply(
        profile, 0, capturedClock, reply
    ));
    assert(reply == fromHex(
        "79f4882f28b42d008fb9840280824085850086700098e1a10d01008000000000000000001133"
    ));
    assert(rainpoint::htv145::buildReply(
        profile, 1, capturedClock, reply
    ));
    assert(reply == fromHex(
        "79f4882f28b42d008fb984028082c10100008000000000000000000000000000000000004ca5"
    ));
    assert(rainpoint::htv145::buildReply(
        profile, 3, capturedClock, reply
    ));
    assert(reply == fromHex(
        "79f4882f28b42d008fb9840280834287802c0105000f0000000000000000000000000000063f"
    ));
    assert(rainpoint::htv145::buildReply(
        profile, 4, capturedClock, reply
    ));
    assert(reply == fromHex(
        "79f4882f28b42d008fb984028083c3008000000000000000000000000000000000000000221c"
    ));
    assert(rainpoint::htv145::buildReply(
        profile, 5, capturedClock, reply
    ));
    assert(reply == fromHex(
        "79f4882f28b42d008fb9840280846c8180190000000000000000000000000000000000000bd8"
    ));
}
