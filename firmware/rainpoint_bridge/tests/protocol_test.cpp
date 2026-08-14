#include <array>
#include <cassert>
#include <cstdint>
#include <string>

#include "rainpoint_protocol.h"
#include "rainpoint_pairing.h"
#include "rainpoint_ack.h"
#include "rainpoint_ota.h"

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
    rainpoint::OtaBootState otaState{};
    rainpoint::beginOtaCandidate(otaState);
    rainpoint::recordCandidateBoot(otaState);
    rainpoint::recordCandidateBoot(otaState);
    assert(!rainpoint::shouldRollback(otaState));
    rainpoint::recordCandidateBoot(otaState);
    assert(rainpoint::shouldRollback(otaState));
    rainpoint::confirmCandidate(otaState);
    assert(!rainpoint::shouldRollback(otaState));

    const auto heartbeat = fromHex(
        "79f4882f28c4e500243984028088c181000100000000000000000000000000000000000022e3"
    );
    assert(rainpoint::hasSync(heartbeat));
    assert(rainpoint::trailerResidual(heartbeat) == 0xc713);
    assert(rainpoint::hasOrdinaryTrailer(heartbeat));

    std::array<std::uint8_t, rainpoint::kRadioPayloadBytes> payload{};
    assert(rainpoint::prepareRadioPayload(heartbeat, payload));
    assert(rainpoint::reconstructFrame(payload) == heartbeat);

    const auto routineReport = fromHex(
        "79f4882f28b9840280ce6280241701820305c41a800000000000000000000000000000007833"
    );
    const auto capturedRoutineAck = fromHex(
        "79f4882f28ce6280243984028097418100010000000000000000000000000000000000005242"
    );
    rainpoint::RoutineAckAuthorization routineAuthorization{
        {{0xce, 0x62, 0x80, 0x24}}, 8, 45'000, 10, false, true,
    };
    std::array<std::uint8_t, rainpoint::kFrameBytes> generatedRoutineAck{};
    assert(rainpoint::isAuthorizedRoutineHcs026Report(
        routineReport, routineAuthorization
    ));
    assert(rainpoint::buildRoutineHcs026Acknowledgement(
        routineReport, routineAuthorization, generatedRoutineAck
    ));
    assert(generatedRoutineAck == capturedRoutineAck);
    assert(
        rainpoint::trailerResidual(generatedRoutineAck) ==
        rainpoint::trailerResidual(routineReport)
    );
    assert(rainpoint::routineAckCenterHz(routineAuthorization) == 433'956'500);
    assert(rainpoint::kRoutineAckDelayMs == 150);
    assert(rainpoint::kRoutineAckWakeSymbols == 320);
    assert(rainpoint::kRoutineAckDeadlineMs == 250);
    rainpoint::RoutineAckAuthorizations routineAuthorizations;
    auto locallyAssignedAuthorization = routineAuthorization;
    locallyAssignedAuthorization.pairingChannel = 4;
    assert(routineAuthorizations.activeCount() == 0);
    assert(routineAuthorizations.authorize(locallyAssignedAuthorization));
    assert(routineAuthorizations.activeCount() == 1);
    assert(routineAuthorizations.match(routineReport) != nullptr);
    assert(routineAuthorizations.revoke(
        locallyAssignedAuthorization.pairedEndpoint
    ));
    assert(routineAuthorizations.activeCount() == 0);
    assert(routineAuthorizations.match(routineReport) == nullptr);
    assert(!routineAuthorizations.revoke(
        locallyAssignedAuthorization.pairedEndpoint
    ));
    assert(routineAuthorizations.authorize(locallyAssignedAuthorization));

    auto wrongRoutineEndpoint = routineReport;
    wrongRoutineEndpoint[9] ^= 0x01;
    rainpoint::writeTrailer(
        wrongRoutineEndpoint, rainpoint::trailerResidual(routineReport)
    );
    assert(!rainpoint::isAuthorizedRoutineHcs026Report(
        wrongRoutineEndpoint, routineAuthorization
    ));
    auto pairingControlMessage = routineReport;
    pairingControlMessage[13] = 0x03;
    rainpoint::writeTrailer(
        pairingControlMessage, rainpoint::trailerResidual(routineReport)
    );
    assert(!rainpoint::isAuthorizedRoutineHcs026Report(
        pairingControlMessage, routineAuthorization
    ));
    routineAuthorization.active = false;
    assert(!rainpoint::buildRoutineHcs026Acknowledgement(
        routineReport, routineAuthorization, generatedRoutineAck
    ));
    assert(!routineAuthorizations.authorize(routineAuthorization));

    auto corrupt = heartbeat;
    corrupt[20] ^= 0x01;
    assert(!rainpoint::hasOrdinaryTrailer(corrupt));
    assert(!rainpoint::prepareRadioPayload(corrupt, payload));

    auto wrongSync = heartbeat;
    wrongSync[0] ^= 0x01;
    assert(!rainpoint::prepareRadioPayload(wrongSync, payload));
    const auto& profile = rainpoint::kValidatedHcs026Profile;
    assert(rainpoint::validPairingProfile(profile));
    assert(profile.stepCount == 3);
    assert(
        profile.steps[0].channelCenterHz == 433'471'500
    );
    assert(
        profile.steps[1].channelCenterHz == 433'471'500
    );
    assert(rainpoint::kMaxPairingFrequencyOffsetHz == 100'000);
    for (std::size_t index = 0; index < profile.stepCount; ++index) {
        const auto& step = profile.steps[index];
        assert(step.wakeSymbols == 320);
        assert(step.replyDeadlineMs == 250);
        assert(rainpoint::hasOrdinaryTrailer(step.frame));
    }

    const auto& sensorA = rainpoint::kSensorAHcs026CandidateProfile;
    assert(rainpoint::validPairingProfile(sensorA));
    assert(sensorA.stepCount == 4);
    assert(sensorA.replyDelayMs == 10);
    assert(sensorA.steps[0].channelCenterHz == 433'471'484);
    assert(sensorA.steps[1].channelCenterHz == 434'021'457);
    assert(sensorA.steps[2].channelCenterHz == 434'021'457);
    assert(sensorA.steps[3].trigger == rainpoint::PairingTrigger::PairedMessage2Short);
    assert(!sensorA.completeAfterFinalReply);
    assert(sensorA.factoryEndpoint[0] == 0x1b);
    assert(sensorA.pairedEndpoint[0] == 0x9b);

    auto generalizedSensorA = sensorA;
    assert(rainpoint::assignPairingChannel(generalizedSensorA, 5));
    assert(rainpoint::pairingChannelFromReply(
        generalizedSensorA.steps[0].frame
    ) == 5);
    assert(generalizedSensorA.steps[0].frame[18] == 0x02);
    assert(generalizedSensorA.steps[0].frame[19] == 0xf0);
    assert(rainpoint::hasOrdinaryTrailer(generalizedSensorA.steps[0].frame));
    assert(
        generalizedSensorA.steps[0].channelCenterHz == 433'471'500
    );
    for (std::size_t index = 1; index < generalizedSensorA.stepCount; ++index) {
        assert(
            generalizedSensorA.steps[index].channelCenterHz == 433'581'500
        );
    }
    assert(!rainpoint::assignPairingChannel(generalizedSensorA, 3));
    assert(!rainpoint::assignPairingChannel(generalizedSensorA, 8));
    assert(!rainpoint::assignPairingChannel(generalizedSensorA, 12));

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

    const auto sensorAFactoryTrigger = fromHex(
        "79f4882f28800000001bce0024010083827fa41e8080b20000000000000000000000000073e3"
    );
    std::array<std::uint8_t, 4> detectedFactory{};
    assert(rainpoint::hcs026FactoryAnnouncement(
        factoryTrigger, detectedFactory
    ));
    assert(detectedFactory == profile.factoryEndpoint);
    assert(rainpoint::hcs026FactoryAnnouncement(
        sensorAFactoryTrigger, detectedFactory
    ));
    assert(detectedFactory == sensorA.factoryEndpoint);
    assert(!rainpoint::hcs026FactoryAnnouncement(heartbeat, detectedFactory));
    auto wrongFactorySignature = factoryTrigger;
    wrongFactorySignature[18] ^= 0x01;
    rainpoint::writeTrailer(
        wrongFactorySignature, rainpoint::kCurrentPairingTrailerResidual
    );
    assert(!rainpoint::hcs026FactoryAnnouncement(
        wrongFactorySignature, detectedFactory
    ));

    auto unknownFactoryTrigger = factoryTrigger;
    unknownFactoryTrigger[9] = 0x12;
    unknownFactoryTrigger[10] = 0x34;
    unknownFactoryTrigger[11] = 0x00;
    rainpoint::writeTrailer(
        unknownFactoryTrigger, rainpoint::kCurrentPairingTrailerResidual
    );
    assert(rainpoint::hcs026FactoryAnnouncement(
        unknownFactoryTrigger, detectedFactory
    ));
    assert((detectedFactory == std::array<std::uint8_t, 4>{{
        0x12, 0x34, 0x00, 0x24,
    }}));
    rainpoint::PairingProfile automatic{};
    assert(!rainpoint::buildAutomaticHcs026Profile(
        {{0x92, 0x34, 0x00, 0x24}}, 4, automatic
    ));
    assert(rainpoint::buildAutomaticHcs026Profile(
        detectedFactory, 4, automatic
    ));
    assert(std::string(automatic.id) == "hcs026_auto_v1");
    assert(automatic.factoryEndpoint == detectedFactory);
    assert((automatic.pairedEndpoint == std::array<std::uint8_t, 4>{{
        0x92, 0x34, 0x00, 0x24,
    }}));
    assert(automatic.stepCount == 4);
    assert(automatic.replyDelayMs == 10);
    for (std::size_t index = 0; index < automatic.stepCount; ++index) {
        assert(rainpoint::hasOrdinaryTrailer(automatic.steps[index].frame));
        assert(automatic.steps[index].channelCenterHz == 433'471'500);
        for (std::size_t endpointIndex = 0; endpointIndex < 4; ++endpointIndex) {
            assert(
                automatic.steps[index].frame[5 + endpointIndex] ==
                automatic.pairedEndpoint[endpointIndex]
            );
        }
    }
    assert(
        automatic.steps[3].trigger ==
        rainpoint::PairingTrigger::PairedMessage2Short
    );
    rainpoint::PairingProfile automaticSensorB{};
    assert(rainpoint::buildAutomaticHcs026Profile(
        profile.factoryEndpoint, 4, automaticSensorB
    ));
    rainpoint::PairingSession automaticSensorBSession(automaticSensorB);
    automaticSensorBSession.arm(20'000);
    const std::array automaticSensorBTriggers = {
        factoryTrigger,
        pairedMessage1,
        pairedMessage2Data,
        pairedMessage2Short,
    };
    for (std::size_t index = 0; index < automaticSensorBTriggers.size(); ++index) {
        const auto* reply = automaticSensorBSession.claimReply(
            automaticSensorBTriggers[index], 21'000 + index
        );
        assert(reply == &automaticSensorB.steps[index]);
        assert(automaticSensorBSession.finishReply(true, 21'100 + index));
    }
    assert(automaticSensorBSession.awaitingTerminalConfirmation());
    assert(
        automaticSensorBSession.claimReply(pairedMessage3, 22'000) == nullptr
    );
    assert(
        automaticSensorBSession.state() ==
        rainpoint::PairingSessionState::Completed
    );
    const auto sensorAPairedMessage1 = fromHex(
        "79f4882f28b98402809bce002401818204e5c4008000000000000000000000000000000008d6"
    );
    const auto sensorAPairedMessage2Data = fromHex(
        "79f4882f28b98402809bce002402018204e5c400800000000000000000000000000000001d5e"
    );
    const auto sensorAPairedMessage2Short = fromHex(
        "79f4882f28b98402809bce002402818204e5c400800000000000000000000000000000002fdb"
    );
    const auto sensorAPairedMessage3 = fromHex(
        "79f4882f28b98402809bce00240301820485c40080000000000000000000000000000000518b"
    );
    const std::array sensorATriggers = {
        sensorAFactoryTrigger,
        sensorAPairedMessage1,
        sensorAPairedMessage2Data,
        sensorAPairedMessage2Short,
    };
    rainpoint::PairingSession sensorASession(sensorA);
    sensorASession.arm(10'000);
    for (std::size_t index = 0; index < sensorATriggers.size(); ++index) {
        const auto* reply = sensorASession.claimReply(
            sensorATriggers[index], 11'000 + index
        );
        assert(reply == &sensorA.steps[index]);
        assert(sensorASession.finishReply(true, 11'100 + index));
        if (index + 1 < sensorATriggers.size()) {
            assert(sensorASession.state() == rainpoint::PairingSessionState::Armed);
        }
    }
    assert(sensorASession.state() == rainpoint::PairingSessionState::Armed);
    assert(sensorASession.completedSteps() == 4);
    assert(sensorASession.awaitingTerminalConfirmation());
    assert(sensorASession.claimReply(sensorAPairedMessage3, 12'000) == nullptr);
    assert(sensorASession.state() == rainpoint::PairingSessionState::Completed);

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
