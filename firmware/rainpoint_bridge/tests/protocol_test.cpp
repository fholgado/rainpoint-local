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
    assert(rainpoint::validSensorBPairingProfile());
    assert(rainpoint::kSensorBPairingProfile.size() == 5);
    assert(
        rainpoint::kSensorBPairingProfile[0].channelCenterHz == 433'471'500
    );
    assert(
        rainpoint::kSensorBPairingProfile[1].channelCenterHz == 433'911'500
    );
    assert(rainpoint::kMaxPairingFrequencyOffsetHz == 100'000);
    for (const auto& step : rainpoint::kSensorBPairingProfile) {
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
        "79f4882f28b984028095a9802402828104008000000000000000000000000000000000006d3b"
    );
    const auto pairedMessage3 = fromHex(
        "79f4882f28b984028095a980240301820405c405000000000000000000000000000000002cb4"
    );
    const std::array triggers = {
        factoryTrigger,
        pairedMessage1,
        pairedMessage2Data,
        pairedMessage2Short,
        pairedMessage3,
    };
    rainpoint::SensorBPairingSession session;
    session.arm(1'000);
    for (std::size_t index = 0; index < triggers.size(); ++index) {
        const auto* reply = session.claimReply(triggers[index], 2'000 + index);
        assert(reply == &rainpoint::kSensorBPairingProfile[index]);
        assert(session.finishReply(true, 2'100 + index));
    }
    assert(session.state() == rainpoint::PairingSessionState::Completed);
    assert(session.completedSteps() == 5);

    rainpoint::PairingTrigger trigger;
    assert(rainpoint::sensorBTrigger(pairedMessage2Data, trigger));
    assert(trigger == rainpoint::PairingTrigger::PairedMessage2Data);
    assert(rainpoint::rainpointSymbolCount(320) == 624);
    assert(rainpoint::rainpointSymbol(
        rainpoint::kSensorBPairingProfile[0].frame, 320, 0
    ) == 1);
    assert(rainpoint::rainpointSymbol(
        rainpoint::kSensorBPairingProfile[0].frame, 320, 1
    ) == 0);
    // The first frame byte is 0x79 (01111001), MSB first after the wake.
    assert(rainpoint::rainpointSymbol(
        rainpoint::kSensorBPairingProfile[0].frame, 320, 320
    ) == 0);
    assert(rainpoint::rainpointSymbol(
        rainpoint::kSensorBPairingProfile[0].frame, 320, 321
    ) == 1);
    for (std::size_t index = 0; index < 320; ++index) {
        assert(rainpoint::rainpointSymbol(
            rainpoint::kSensorBPairingProfile[0].frame, 320, index
        ) == (1U ^ static_cast<std::uint8_t>(index & 1U)));
    }
    for (std::size_t byteIndex = 0;
         byteIndex < rainpoint::kFrameBytes;
         ++byteIndex) {
        std::uint8_t reconstructed = 0;
        for (std::size_t bit = 0; bit < 8; ++bit) {
            reconstructed = static_cast<std::uint8_t>(
                (reconstructed << 1) |
                rainpoint::rainpointSymbol(
                    rainpoint::kSensorBPairingProfile[0].frame,
                    320,
                    320 + byteIndex * 8 + bit
                )
            );
        }
        assert(
            reconstructed ==
            rainpoint::kSensorBPairingProfile[0].frame[byteIndex]
        );
    }

    rainpoint::SensorBPairingSession outOfOrder;
    outOfOrder.arm(0);
    assert(outOfOrder.claimReply(pairedMessage1, 1) == nullptr);
    assert(outOfOrder.state() == rainpoint::PairingSessionState::Failed);

    rainpoint::SensorBPairingSession expired;
    expired.arm(0, 100);
    expired.tick(100);
    assert(expired.state() == rainpoint::PairingSessionState::Failed);
    return 0;
}
