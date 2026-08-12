#include <array>
#include <cassert>
#include <cstdint>
#include <string>

#include "rainpoint_protocol.h"
#include "rainpoint_pairing.h"

namespace {

std::array<std::uint8_t, rainpoint::kFrameBytes> fromHex(
    const std::string& value
) {
    assert(value.size() == rainpoint::kFrameBytes * 2);
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
    const auto heartbeat = fromHex(
        "79f4882f28c4e500243984028088c181000100000000000000000000000000000000000022e3"
    );
    assert(rainpoint::hasSync(heartbeat));
    assert(rainpoint::trailerResidual(heartbeat) == 0xc713);
    assert(rainpoint::hasOrdinaryTrailer(heartbeat));

    std::array<std::uint8_t, rainpoint::kRadioPayloadBytes> payload{};
    assert(rainpoint::prepareRadioPayload(heartbeat, payload));
    assert(rainpoint::reconstructFrame(payload) == heartbeat);

    auto corrupt = heartbeat;
    corrupt[20] ^= 0x01;
    assert(!rainpoint::hasOrdinaryTrailer(corrupt));
    assert(!rainpoint::prepareRadioPayload(corrupt, payload));

    auto wrongSync = heartbeat;
    wrongSync[0] ^= 0x01;
    assert(!rainpoint::prepareRadioPayload(wrongSync, payload));
    const auto& profile = rainpoint::kValidatedHcs026Profile;
    assert(rainpoint::validPairingProfile(profile));
    assert(profile.steps.size() == 3);
    assert(
        profile.steps[0].channelCenterHz == 433'471'500
    );
    assert(
        profile.steps[1].channelCenterHz == 433'471'500
    );
    assert(rainpoint::kMaxPairingFrequencyOffsetHz == 100'000);
    for (const auto& step : profile.steps) {
        assert(step.wakeSymbols == 320);
        assert(step.replyDeadlineMs == 250);
        assert(rainpoint::hasOrdinaryTrailer(step.frame));
    }

    const auto factoryTrigger = fromHex(
        "79f4882f288000000015a98024010083827fa41e8080848000000000000000000000000022f1"
    );
    const auto pairedMessage1 = fromHex(
        "79f4882f28b984028095a980240181820465c4050000000000000000000000000000000075e9"
    );
    const auto pairedMessage2Data = fromHex(
        "79f4882f28b984028095a980240201820425c405000000000000000000000000000000002905"
    );
    const auto pairedMessage2Short = fromHex(
        "79f4882f28b984028095a9802402828102008000000000000000000000000000000000005881"
    );
    const auto pairedMessage3 = fromHex(
        "79f4882f28b984028095a980240301820205c40580000000000000000000000000000000117f"
    );
    const std::array triggers = {
        factoryTrigger,
        pairedMessage1,
        pairedMessage2Data,
    };
    rainpoint::PairingSession session(profile);
    session.arm(1'000);
    for (std::size_t index = 0; index < triggers.size(); ++index) {
        const auto* reply = session.claimReply(triggers[index], 2'000 + index);
        assert(reply == &profile.steps[index]);
        assert(session.finishReply(true, 2'100 + index));
    }
    assert(session.state() == rainpoint::PairingSessionState::Armed);
    assert(session.completedSteps() == 3);
    assert(session.awaitingTerminalConfirmation());
    assert(session.claimReply(pairedMessage2Short, 5'000) == nullptr);
    assert(session.state() == rainpoint::PairingSessionState::Armed);
    assert(session.claimReply(pairedMessage3, 9'000) == nullptr);
    assert(session.state() == rainpoint::PairingSessionState::Completed);
    assert(!session.awaitingTerminalConfirmation());
    assert(
        session.failureReason() == rainpoint::PairingFailureReason::None
    );

    auto datedReply = profile.steps[0].frame;
    const rainpoint::PairingLocalDateTime capturedAt = {
        2026, 8, 11, 14, 55, 56,
    };
    assert(rainpoint::applyPairingLocalDateTime(datedReply, capturedAt));
    assert(datedReply == profile.steps[0].frame);
    assert(rainpoint::trailerResidual(datedReply) == 0x4f03);
    const rainpoint::PairingLocalDateTime nextMinute = {
        2026, 8, 11, 14, 56, 1,
    };
    assert(rainpoint::applyPairingLocalDateTime(datedReply, nextMinute));
    assert(datedReply[21] == 0x00);
    assert(datedReply[22] == 0x77);
    assert(datedReply[23] == 0x0b);
    assert(datedReply[24] == 0x0d);
    assert(rainpoint::trailerResidual(datedReply) == 0x4f03);
    const rainpoint::PairingLocalDateTime invalidDate = {
        2019, 8, 11, 14, 56, 0,
    };
    assert(!rainpoint::applyPairingLocalDateTime(datedReply, invalidDate));

    rainpoint::PairingLocalDateTime advancing = {
        2026, 8, 11, 15, 13, 42,
    };
    assert(rainpoint::advancePairingLocalDateTime(advancing, 30));
    assert(advancing.year == 2026 && advancing.month == 8 && advancing.day == 11);
    assert(advancing.hour == 15 && advancing.minute == 14 && advancing.second == 12);
    rainpoint::PairingLocalDateTime leapBoundary = {
        2028, 2, 28, 23, 59, 59,
    };
    assert(rainpoint::advancePairingLocalDateTime(leapBoundary, 2));
    assert(
        leapBoundary.year == 2028 && leapBoundary.month == 2 &&
        leapBoundary.day == 29 && leapBoundary.hour == 0 &&
        leapBoundary.minute == 0 && leapBoundary.second == 1
    );

    rainpoint::PairingTrigger trigger;
    assert(rainpoint::pairingTrigger(pairedMessage2Data, profile, trigger));
    assert(trigger == rainpoint::PairingTrigger::PairedMessage2Data);
    assert(rainpoint::rainpointSymbolCount(320) == 624);
    assert(rainpoint::kPairingReplyDelayMs == 60);
    assert(rainpoint::validPairingPowerDbm(0));
    assert(rainpoint::validPairingPowerDbm(5));
    assert(rainpoint::validPairingPowerDbm(7));
    assert(rainpoint::validPairingPowerDbm(10));
    assert(!rainpoint::validPairingPowerDbm(6));
    assert(rainpoint::pairingPaTableValue(0) == 0x60);
    assert(rainpoint::pairingPaTableValue(5) == 0x84);
    assert(rainpoint::pairingPaTableValue(7) == 0xc8);
    assert(rainpoint::pairingPaTableValue(10) == 0xc0);
    assert(rainpoint::rainpointSymbol(
        profile.steps[0].frame, 320, 0
    ) == 0);
    assert(rainpoint::rainpointSymbol(
        profile.steps[0].frame, 320, 1
    ) == 1);
    // The first frame byte is 0x79 (01111001), MSB first after the wake.
    assert(rainpoint::rainpointSymbol(
        profile.steps[0].frame, 320, 320
    ) == 0);
    assert(rainpoint::rainpointSymbol(
        profile.steps[0].frame, 320, 321
    ) == 1);
    for (std::size_t index = 0; index < 320; ++index) {
        assert(rainpoint::rainpointSymbol(
            profile.steps[0].frame, 320, index
        ) == static_cast<std::uint8_t>(index & 1U));
    }
    for (std::size_t byteIndex = 0;
         byteIndex < rainpoint::kFrameBytes;
         ++byteIndex) {
        std::uint8_t reconstructed = 0;
        for (std::size_t bit = 0; bit < 8; ++bit) {
            reconstructed = static_cast<std::uint8_t>(
                (reconstructed << 1) |
                rainpoint::rainpointSymbol(
                    profile.steps[0].frame,
                    320,
                    320 + byteIndex * 8 + bit
                )
            );
        }
        assert(
            reconstructed ==
            profile.steps[0].frame[byteIndex]
        );
    }

    rainpoint::PairingSession outOfOrder(profile);
    outOfOrder.arm(0);
    assert(outOfOrder.claimReply(pairedMessage1, 1) == nullptr);
    assert(outOfOrder.state() == rainpoint::PairingSessionState::Failed);

    rainpoint::PairingSession expired(profile);
    expired.arm(0, 100);
    expired.tick(100);
    assert(expired.state() == rainpoint::PairingSessionState::Failed);
    assert(
        expired.failureReason() ==
        rainpoint::PairingFailureReason::SessionTimeout
    );

    rainpoint::PairingSession incomplete(profile);
    incomplete.arm(0, 10'000);
    for (std::size_t index = 0; index < triggers.size(); ++index) {
        assert(incomplete.claimReply(triggers[index], index * 1'000) != nullptr);
        assert(incomplete.finishReply(true, index * 1'000 + 100));
    }
    assert(incomplete.awaitingTerminalConfirmation());
    incomplete.tick(10'000);
    assert(incomplete.state() == rainpoint::PairingSessionState::Failed);
    assert(
        incomplete.failureReason() ==
        rainpoint::PairingFailureReason::TerminalConfirmationTimeout
    );
    return 0;
}
