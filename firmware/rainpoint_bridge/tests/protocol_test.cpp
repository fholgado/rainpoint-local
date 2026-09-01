#include <array>
#include <cassert>
#include <cstdint>
#include <string>

#include "rainpoint_protocol.h"
#include "rainpoint_pairing.h"
#include "rainpoint_htv145_pairing.h"
#include "rainpoint_valve_pairing.h"
#include "rainpoint_valve_control.h"
#include "rainpoint_htv145_control.h"
#include "rainpoint_ack.h"
#include "rainpoint_ota.h"
#include "rainpoint_rf_maintenance.h"

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

std::array<std::uint8_t, rainpoint::kFrameBytes> htv405Request(
    const rainpoint::Htv405PairingProfile& profile,
    std::size_t stepIndex,
    std::uint8_t counterOffset = 0
) {
    assert(stepIndex < profile.steps.size());
    std::array<std::uint8_t, rainpoint::kFrameBytes> request{};
    for (std::size_t index = 0; index < rainpoint::kSync.size(); ++index) {
        request[index] = rainpoint::kSync[index];
    }
    const auto& endpointA = stepIndex == 0
        ? std::array<std::uint8_t, 4>{{0x80, 0x00, 0x00, 0x00}}
        : profile.valveRoute;
    const auto& endpointB = stepIndex == 0
        ? profile.factoryEndpoint
        : profile.pairedEndpoint;
    for (std::size_t index = 0; index < 4; ++index) {
        request[5 + index] = endpointA[index];
        request[9 + index] = endpointB[index];
    }
    for (std::size_t index = 0; index < 23; ++index) {
        request[13 + index] = profile.steps[stepIndex].requestBody[index];
    }
    if (stepIndex > 0) {
        request[13] = rainpoint::htv405ShiftedCounter(
            request[13], counterOffset
        );
    }
    rainpoint::writeTrailer(request, 0xc713);
    return request;
}
}  // namespace

int main() {
    rainpoint::RfMaintenanceState rfMaintenance;
    assert(rfMaintenance.transmitAllowed());
    assert(!rfMaintenance.enterReceiveOnly(100, 59));
    assert(rfMaintenance.enterReceiveOnly(100, 900));
    assert(!rfMaintenance.transmitAllowed());
    assert(rfMaintenance.remainingSeconds(100) == 900);
    assert(rfMaintenance.remainingSeconds(100'100) == 800);
    assert(!rfMaintenance.tick(900'099));
    assert(rfMaintenance.tick(900'100));
    assert(rfMaintenance.transmitAllowed());
    assert(rfMaintenance.remainingSeconds(900'100) == 0);
    assert(rfMaintenance.enterReceiveOnly(0xfffffff0U, 60));
    assert(!rfMaintenance.tick(0x0000'0010U));
    rfMaintenance.resumeNormal(0x0000'0010U);
    assert(rfMaintenance.transmitAllowed());

    const rainpoint::Htv405RoutineAckAuthorization htv405AckAuthorization{
        {{0xb9, 0x84, 0x02, 0x80}},
        {{0x94, 0xa9, 0x80, 0x13}},
        {{0x39, 0x84, 0x02, 0x80}},
        45'000,
        10,
        false,
        true,
    };
    rainpoint::Htv405RoutineAckAuthorizations htv405AckAuthorizations;
    assert(htv405AckAuthorizations.authorize(htv405AckAuthorization));
    assert(htv405AckAuthorizations.activeCount() == 1);
    const auto htv405ActiveReport = fromHex(
        "79f4882f28b984028094a9801304010786858190cf80000000409b00569e0000000000000db6"
    );
    const auto htv405IdleRepeatReport = fromHex(
        "79f4882f28b984028094a98013048107868581804f80000000408000568000000000000043a2"
    );
    std::array<std::uint8_t, rainpoint::kFrameBytes> htv405RoutineAck{};
    assert(
        htv405AckAuthorizations.match(htv405ActiveReport) != nullptr
    );
    assert(rainpoint::buildRoutineHtv405Acknowledgement(
        htv405ActiveReport,
        htv405AckAuthorization,
        0xc713,
        htv405RoutineAck
    ));
    assert(htv405RoutineAck == fromHex(
        "79f4882f2894a980133984028084410100010000000000000000000000000000000000000c06"
    ));
    assert(rainpoint::buildRoutineHtv405Acknowledgement(
        htv405IdleRepeatReport,
        htv405AckAuthorization,
        0x4f03,
        htv405RoutineAck
    ));
    assert(htv405RoutineAck == fromHex(
        "79f4882f2894a980133984028084c10100010000000000000000000000000000000000003e83"
    ));
    auto foreignHtv405Report = htv405ActiveReport;
    foreignHtv405Report[5] ^= 0x01;
    rainpoint::writeTrailer(foreignHtv405Report, 0xc713);
    assert(htv405AckAuthorizations.match(foreignHtv405Report) == nullptr);
    assert(!rainpoint::buildRoutineHtv405Acknowledgement(
        foreignHtv405Report,
        htv405AckAuthorization,
        0xc713,
        htv405RoutineAck
    ));
    assert(
        rainpoint::routineHtv405AckCenterHz(htv405AckAuthorization) ==
        rainpoint::kHtv405RoutineChannelCenterHz + 45'000
    );

    const rainpoint::Htv405ValveLink testValveLink{
        {{0xaa, 0x11, 0x02, 0x80}},
        {{0xa1, 0xb2, 0xc3, 0x13}},
    };
    std::array<std::uint8_t, rainpoint::kFrameBytes> closeFrame{};
    assert(rainpoint::buildHtv405CloseFrame(
        testValveLink,
        {0x0a, true},
        1,
        0x05,
        0xc713,
        closeFrame
    ));
    assert(closeFrame == fromHex(
        "79f4882f28aa110280a1b2c3130a8107820580804f8000000040"
        "800056800000000000002077"
    ));
    for (std::uint8_t zone = 1; zone <= 4; ++zone) {
        assert(rainpoint::buildHtv405CloseFrame(
            testValveLink,
            {0x0a, false},
            zone,
            0x05,
            0x4f03,
            closeFrame
        ));
        assert(closeFrame[18] == static_cast<std::uint8_t>(0x80 | zone / 2));
        assert(closeFrame[19] == (zone % 2 ? 0x80 : 0x00));
        assert(rainpoint::hasOrdinaryTrailer(closeFrame));
    }
    assert(!rainpoint::buildHtv405CloseFrame(
        testValveLink, {0x0a, false}, 5, 0x05, 0x4f03, closeFrame
    ));

    const rainpoint::Htv405ValveLink capturedValveLink{
        {{0xb9, 0x84, 0x02, 0x80}},
        {{0x94, 0xa9, 0x80, 0x13}},
    };
    const rainpoint::Htv405GatewayControlLink capturedGatewayControlLink{
        {{0x94, 0xa9, 0x80, 0x13}},
        {{0x39, 0x84, 0x02, 0x80}},
    };
    std::array<std::uint8_t, rainpoint::kFrameBytes> gatewayCommand{};
    assert(rainpoint::buildHtv405GatewayOpenFrame(
        capturedGatewayControlLink,
        {0x01, true},
        1,
        0x85,
        120,
        0x4f03,
        gatewayCommand
    ));
    assert(gatewayCommand == fromHex(
        "79f4882f2894a9801339840280819082808100bc0000000000"
        "00000000000000000000006c37"
    ));
    assert(rainpoint::buildHtv405GatewayOpenFrame(
        capturedGatewayControlLink,
        {0x01, false},
        1,
        0x85,
        120,
        0x4f03,
        gatewayCommand
    ));
    assert(gatewayCommand == fromHex(
        "79f4882f2894a9801339840280819082808100bc0000000000"
        "00000000000000000000006c37"
    ));
    assert(rainpoint::buildHtv405GatewayCloseFrame(
        capturedGatewayControlLink,
        {0x02, false},
        1,
        0x85,
        0x4f03,
        gatewayCommand
    ));
    assert(gatewayCommand == fromHex(
        "79f4882f2894a9801339840280821081808100000000000000"
        "00000000000000000000000117"
    ));
    assert(rainpoint::buildHtv405GatewayCloseFrame(
        capturedGatewayControlLink,
        {0x02, true},
        1,
        0x85,
        0x4f03,
        gatewayCommand
    ));
    assert(gatewayCommand == fromHex(
        "79f4882f2894a9801339840280821081808100000000000000"
        "00000000000000000000000117"
    ));
    assert(rainpoint::buildHtv405GatewayLinkAckFrame(
        capturedGatewayControlLink,
        {0x0a, false},
        0xc713,
        gatewayCommand
    ));
    assert(gatewayCommand == fromHex(
        "79f4882f2894a98013398402808a4101000100000000000000"
        "00000000000000000000005a26"
    ));
    // The dry-bench multi-zone trial varies only this command selector. The
    // live research firmware still requires a per-command authenticated
    // response; production builds do not compile this transmit path.
    for (std::uint8_t zone = 1; zone <= 4; ++zone) {
        assert(rainpoint::buildHtv405GatewayOpenFrame(
            capturedGatewayControlLink,
            {0x01, true},
            zone,
            0x85,
            120,
            0x4f03,
            gatewayCommand
        ));
        assert(gatewayCommand[17] ==
            static_cast<std::uint8_t>(0x80U | zone));
        assert(rainpoint::buildHtv405GatewayCloseFrame(
            capturedGatewayControlLink,
            {0x02, false},
            zone,
            0x85,
            0x4f03,
            gatewayCommand
        ));
        assert(gatewayCommand[17] ==
            static_cast<std::uint8_t>(0x80U | zone));
    }
    assert(rainpoint::buildHtv405GatewayOpenFrame(
        capturedGatewayControlLink,
        {0x01, true},
        1,
        0x05,
        120,
        0x4f03,
        gatewayCommand
    ));
    assert(gatewayCommand[17] == 0x81);
    assert(rainpoint::buildHtv405GatewayOpenFrame(
        capturedGatewayControlLink,
        {0x01, false},
        1,
        0x05,
        1'200,
        0x4f03,
        gatewayCommand
    ));
    assert(gatewayCommand[19] == 0xd8);
    assert(gatewayCommand[20] == 0x02);
    assert(rainpoint::trailerResidual(gatewayCommand) == 0x4f03);
    assert(rainpoint::buildHtv405GatewayOpenFrame(
        capturedGatewayControlLink,
        {0x02, false},
        1,
        0x05,
        900,
        0x4f03,
        gatewayCommand
    ));
    assert(gatewayCommand[19] == 0x42);
    assert(gatewayCommand[20] == 0x02);
    assert(rainpoint::trailerResidual(gatewayCommand) == 0x4f03);
    std::array<std::uint8_t, rainpoint::kFrameBytes> openFrame{};
    assert(rainpoint::buildHtv405OpenFrame(
        capturedValveLink,
        {0x0b, false},
        1,
        0x85,
        60,
        54,
        0x4f03,
        openFrame
    ));
    assert(openFrame == fromHex(
        "79f4882f28b984028094a980130b010782858090cf8000000040"
        "9b80569e0000000000002fc2"
    ));
    assert(rainpoint::buildHtv405OpenFrame(
        capturedValveLink,
        {0x0b, false},
        1,
        0x05,
        60,
        54,
        0x4f03,
        openFrame
    ));
    assert(openFrame == fromHex(
        "79f4882f28b984028094a980130b010782058090cf8000000040"
        "9b80569e000000000000bd0b"
    ));
    rainpoint::Htv405GatewayCommandResponse commandResponse{};
    const auto capturedLocalOpenResponse = fromHex(
        "79f4882f28b984028094a9801303d0868010cf8000000040bc"
        "0056bc000000000000000038bf"
    );
    assert(rainpoint::decodeHtv405GatewayCommandResponse(
        capturedLocalOpenResponse, commandResponse
    ));
    assert(commandResponse.sequence == 0x03);
    assert(commandResponse.zone == 1);
    assert(commandResponse.watering);
    assert(
        rainpoint::nextHtv405GatewayCommandSequence(
            commandResponse.sequence, commandResponse.watering
        ) ==
        0x04
    );
    rainpoint::Htv405GatewayCommandRejection commandRejection{};
    const auto capturedRejectedCommand = fromHex(
        "79f4882f28ee86de8094a9801303d08683004f800000004080"
        "0056800000000000000000738e"
    );
    assert(rainpoint::decodeHtv405GatewayCommandRejection(
        capturedRejectedCommand, commandRejection
    ));
    assert(commandRejection.sequence == 0x03);
    auto corruptRejectedCommand = capturedRejectedCommand;
    corruptRejectedCommand[16] = 0x80;
    assert(!rainpoint::decodeHtv405GatewayCommandRejection(
        corruptRejectedCommand, commandRejection
    ));
    const auto capturedLocalCloseResponse = fromHex(
        "79f4882f28b984028094a9801304508683104f800000004080"
        "00568000000000000000001e6e"
    );
    assert(rainpoint::decodeHtv405GatewayCommandResponse(
        capturedLocalCloseResponse, commandResponse
    ));
    assert(commandResponse.sequence == 0x04);
    assert(commandResponse.zone == 1);
    assert(!commandResponse.watering);
    assert(
        rainpoint::nextHtv405GatewayCommandSequence(
            commandResponse.sequence, commandResponse.watering
        ) ==
        0x04
    );
    const std::array<std::string, 3> multiZoneResponses{{
        "79f4882f28b984028094a980130bd0868020cf80000000409e"
        "00569e000000000000000079b2",
        "79f4882f28b984028094a980130cd0868030cf80000000409e"
        "00569e000000000000000062ff",
        "79f4882f28b984028094a980130dd0868040cf80000000409e"
        "00569e00000000000000001e77",
    }};
    for (std::uint8_t zone = 2; zone <= 4; ++zone) {
        assert(rainpoint::decodeHtv405GatewayCommandResponse(
            fromHex(multiZoneResponses[zone - 2]), commandResponse
        ));
        assert(commandResponse.sequence ==
            static_cast<std::uint8_t>(zone + 9));
        assert(commandResponse.zone == zone);
        assert(commandResponse.watering);
    }
    rainpoint::Htv405StateReport stateReport{};
    const auto localZoneTwoReport = fromHex(
        "79f4882f28b984028094a980131a8107820580a0cf80000000409e"
        "00569e0000000000000d22"
    );
    assert(rainpoint::decodeHtv405StateReport(
        localZoneTwoReport, stateReport
    ));
    assert(stateReport.zone == 2);
    assert(stateReport.watering);
    const auto localIdleReport = fromHex(
        "79f4882f28b984028094a980131d0107820580804f800000004080"
        "0056800000000000000045"
    );
    assert(rainpoint::decodeHtv405StateReport(
        localIdleReport, stateReport
    ));
    assert(stateReport.zone == 0);
    assert(!stateReport.watering);
    const auto selectorSevenPhaseReport = fromHex(
        "79f4882f28b984028094a980131c8107820700a0cf800000004088"
        "00569e0000000000006700"
    );
    assert(!rainpoint::decodeHtv405StateReport(
        selectorSevenPhaseReport, stateReport
    ));
    auto corruptCommandResponse = capturedLocalOpenResponse;
    corruptCommandResponse[18] ^= 0x80;
    rainpoint::writeTrailer(corruptCommandResponse, 0x4f03);
    assert(!rainpoint::decodeHtv405GatewayCommandResponse(
        corruptCommandResponse, commandResponse
    ));
    assert(!rainpoint::buildHtv405OpenFrame(
        capturedValveLink,
        {0x0b, false},
        1,
        0x05,
        60,
        55,
        0x4f03,
        openFrame
    ));

    auto localValveReport = fromHex(
        "79f4882f28aa110280a1b2c313080107820701004f8000000040"
        "80005680000000000000a102"
    );
    rainpoint::writeTrailer(localValveReport, 0xc713);
    rainpoint::Htv405Phase nextValvePhase{};
    assert(rainpoint::nextHtv405Phase(localValveReport, nextValvePhase));
    assert(nextValvePhase.sequence == 0x08);
    assert(nextValvePhase.repeat);
    localValveReport[14] |= 0x80;
    rainpoint::writeTrailer(localValveReport, 0x4f03);
    assert(rainpoint::nextHtv405Phase(localValveReport, nextValvePhase));
    assert(nextValvePhase.sequence == 0x09);
    assert(!nextValvePhase.repeat);
    // Active-state reports from the same locally enrolled HTV405 use the
    // association selector (0x05) instead of the idle-link selector (0x07).
    // Both shapes retain the same phase and control-slot markers.
    localValveReport[17] = 0x05;
    rainpoint::writeTrailer(localValveReport, 0x4f03);
    assert(rainpoint::nextHtv405Phase(localValveReport, nextValvePhase));
    assert(nextValvePhase.sequence == 0x09);
    assert(!nextValvePhase.repeat);

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
    const std::array<std::uint8_t, 4> stockController{{
        0xb9, 0x84, 0x02, 0x80,
    }};
    const std::array<std::uint8_t, 4> stockCompanion{{
        0x39, 0x84, 0x02, 0x80,
    }};
    rainpoint::RoutineAckAuthorization routineAuthorization{
        {{0xce, 0x62, 0x80, 0x24}}, stockController, stockCompanion,
        8, 45'000, 10, false, true,
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

    const std::array<std::uint8_t, 4> localController{{
        0xc1, 0x23, 0x45, 0x80,
    }};
    const std::array<std::uint8_t, 4> localCompanion{{
        0x41, 0x23, 0x45, 0x80,
    }};
    assert(rainpoint::validRfControllerIdentity(
        localController, localCompanion
    ));
    auto localRoutineReport = routineReport;
    for (std::size_t index = 0; index < localController.size(); ++index) {
        localRoutineReport[5 + index] = localController[index];
    }
    rainpoint::writeTrailer(
        localRoutineReport, rainpoint::trailerResidual(routineReport)
    );
    auto localAuthorization = routineAuthorization;
    localAuthorization.controllerEndpoint = localController;
    localAuthorization.companionEndpoint = localCompanion;
    std::array<std::uint8_t, rainpoint::kFrameBytes> localRoutineAck{};
    assert(rainpoint::buildRoutineHcs026Acknowledgement(
        localRoutineReport, localAuthorization, localRoutineAck
    ));
    assert(rainpoint::endpointEquals(localRoutineAck, 9, localCompanion));

    rainpoint::RoutineAckAuthorization sensorARecoveryAuthorization{
        {{0x9b, 0xce, 0x00, 0x24}}, stockController, stockCompanion,
        4, 0, 10, false, true,
    };
    assert(routineAuthorizations.authorize(sensorARecoveryAuthorization));
    const auto sensorARecoveryMessage1 = fromHex(
        "79f4882f28b98402809bce002401018202054419800000000000000000000000000000005202"
    );
    rainpoint::PairingTrigger recoveryTrigger{};
    const auto* recoveryAuthorization =
        rainpoint::authorizedHcs026ControlFrame(
            sensorARecoveryMessage1,
            routineAuthorizations,
            recoveryTrigger
        );
    assert(recoveryAuthorization != nullptr);
    assert(recoveryTrigger == rainpoint::PairingTrigger::PairedMessage1);
    std::array<std::uint8_t, rainpoint::kFrameBytes> recoveryReply{};
    assert(rainpoint::buildKnownHcs026RecoveryReply(
        recoveryTrigger, *recoveryAuthorization, recoveryReply
    ));
    assert(recoveryReply == fromHex(
        "79f4882f289bce00243984028081c18200011f80000000000000000000000000000000000414"
    ));
    const auto sensorARecoveryMessage2Data = fromHex(
        "79f4882f28b98402809bce002402018204e5c400800000000000000000000000000000001d5e"
    );
    recoveryAuthorization = rainpoint::authorizedHcs026ControlFrame(
        sensorARecoveryMessage2Data, routineAuthorizations, recoveryTrigger
    );
    assert(recoveryAuthorization != nullptr);
    assert(recoveryTrigger == rainpoint::PairingTrigger::PairedMessage2Data);
    assert(rainpoint::buildKnownHcs026RecoveryReply(
        recoveryTrigger, *recoveryAuthorization, recoveryReply
    ));
    assert(recoveryReply == fromHex(
        "79f4882f289bce00243984028082428100008000000000000000000000000000000000007b92"
    ));
    const auto sensorARecoveryMessage2Short = fromHex(
        "79f4882f28b98402809bce002402818204e5c400800000000000000000000000000000002fdb"
    );
    recoveryAuthorization = rainpoint::authorizedHcs026ControlFrame(
        sensorARecoveryMessage2Short, routineAuthorizations, recoveryTrigger
    );
    assert(recoveryAuthorization != nullptr);
    assert(recoveryTrigger == rainpoint::PairingTrigger::PairedMessage2Short);
    assert(rainpoint::buildKnownHcs026RecoveryReply(
        recoveryTrigger, *recoveryAuthorization, recoveryReply
    ));
    assert(recoveryReply == fromHex(
        "79f4882f289bce00243984028082c18100010000000000000000000000000000000000004e6f"
    ));
    const auto sensorARecoveryMessage3 = fromHex(
        "79f4882f28b98402809bce002403028104808000000000000000000000000000000000001c91"
    );
    recoveryAuthorization = rainpoint::authorizedHcs026ControlFrame(
        sensorARecoveryMessage3, routineAuthorizations, recoveryTrigger
    );
    assert(recoveryAuthorization != nullptr);
    assert(recoveryTrigger == rainpoint::PairingTrigger::PairedMessage3);
    assert(!rainpoint::buildKnownHcs026RecoveryReply(
        recoveryTrigger, *recoveryAuthorization, recoveryReply
    ));
    auto unknownRecovery = sensorARecoveryMessage1;
    unknownRecovery[9] = 0xaa;
    rainpoint::writeTrailer(
        unknownRecovery, rainpoint::kCurrentPairingTrailerResidual
    );
    assert(rainpoint::authorizedHcs026ControlFrame(
        unknownRecovery, routineAuthorizations, recoveryTrigger
    ) == nullptr);
    auto ordinaryMessage1Shape = sensorARecoveryMessage1;
    ordinaryMessage1Shape[15] = 0x81;
    rainpoint::writeTrailer(
        ordinaryMessage1Shape, rainpoint::kCurrentPairingTrailerResidual
    );
    assert(rainpoint::authorizedHcs026ControlFrame(
        ordinaryMessage1Shape, routineAuthorizations, recoveryTrigger
    ) == nullptr);
    assert(routineAuthorizations.revoke(
        sensorARecoveryAuthorization.pairedEndpoint
    ));
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
    const auto sensorAFactoryRetry4 = fromHex(
        "79f4882f28800000001bce0024040083827fa41e8080b2000000000000000000000000001af5"
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
    assert(rainpoint::hcs026FactoryAnnouncement(
        sensorAFactoryRetry4, detectedFactory
    ));
    assert(detectedFactory == sensorA.factoryEndpoint);
    rainpoint::PairingSession sensorARetrySession(sensorA);
    sensorARetrySession.arm(10'000);
    assert(
        sensorARetrySession.claimReply(sensorAFactoryRetry4, 10'100) ==
        &sensorA.steps[0]
    );
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
        {{0x92, 0x34, 0x00, 0x24}}, stockController, stockCompanion,
        4, automatic
    ));
    assert(rainpoint::buildAutomaticHcs026Profile(
        detectedFactory, stockController, stockCompanion, 4, automatic
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
    rainpoint::PairingProfile localIdentityAutomatic{};
    assert(rainpoint::buildAutomaticHcs026Profile(
        detectedFactory, localController, localCompanion,
        4, localIdentityAutomatic
    ));
    assert(localIdentityAutomatic.sensorRoute == localController);
    assert(localIdentityAutomatic.companionEndpoint == localCompanion);
    for (std::size_t index = 0;
         index < localIdentityAutomatic.stepCount; ++index) {
        assert(rainpoint::endpointEquals(
            localIdentityAutomatic.steps[index].frame, 9, localCompanion
        ));
    }
    // Automatic discovery rebuilds the active profile in place after the
    // factory announcement. Exercise that exact aliasing shape so a custom
    // identity cannot silently fall back to the retained stock endpoints.
    rainpoint::PairingProfile inPlaceIdentityAutomatic{};
    assert(rainpoint::buildAutomaticHcs026Profile(
        detectedFactory, localController, localCompanion,
        4, inPlaceIdentityAutomatic
    ));
    assert(rainpoint::buildAutomaticHcs026Profile(
        profile.factoryEndpoint,
        inPlaceIdentityAutomatic.sensorRoute,
        inPlaceIdentityAutomatic.companionEndpoint,
        4,
        inPlaceIdentityAutomatic
    ));
    assert(inPlaceIdentityAutomatic.sensorRoute == localController);
    assert(inPlaceIdentityAutomatic.companionEndpoint == localCompanion);
    for (std::size_t index = 0;
         index < inPlaceIdentityAutomatic.stepCount; ++index) {
        assert(rainpoint::endpointEquals(
            inPlaceIdentityAutomatic.steps[index].frame, 9, localCompanion
        ));
    }
    rainpoint::PairingProfile automaticRejoin{};
    assert(rainpoint::buildAutomaticHcs026RejoinProfile(
        detectedFactory, stockController, stockCompanion, 4, automaticRejoin
    ));
    assert(automaticRejoin.stepCount == 1);
    assert(automaticRejoin.completeAfterFinalReply);
    rainpoint::PairingSession automaticRejoinSession(automaticRejoin);
    automaticRejoinSession.arm(10'000);
    const auto* automaticRejoinReply = automaticRejoinSession.claimReply(
        unknownFactoryTrigger, 10'100
    );
    assert(automaticRejoinReply == &automaticRejoin.steps[0]);
    assert(automaticRejoinSession.finishReply(true, 10'200));
    assert(
        automaticRejoinSession.state() ==
        rainpoint::PairingSessionState::Completed
    );
    rainpoint::PairingProfile automaticSensorB{};
    assert(rainpoint::buildAutomaticHcs026Profile(
        profile.factoryEndpoint, stockController, stockCompanion,
        4, automaticSensorB
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

    const auto htv405Factory = fromHex(
        "79f4882f288000000014a9801300808402ff93130000bd848000000000000000000000004795"
    );
    const auto htv405Request1 = fromHex(
        "79f4882f28b984028094a98013010107822580804f800000004080005680000000000000ccbf"
    );
    const auto htv405RequestNoReply = fromHex(
        "79f4882f28b984028094a98013028107820582004f800000004080005680000000000000b9c6"
    );
    std::array<std::uint8_t, 4> htv405FactoryEndpoint{};
    assert(rainpoint::htv405FactoryAnnouncement(
        htv405Factory, htv405FactoryEndpoint
    ));
    rainpoint::Htv405PairingProfile discoveredHtv405Profile{};
    assert(rainpoint::initializeAutomaticHtv405Profile(
        {{0xb9, 0x84, 0x02, 0x80}},
        {{0x39, 0x84, 0x02, 0x80}},
        discoveredHtv405Profile
    ));
    assert(discoveredHtv405Profile.factoryEndpoint ==
        (std::array<std::uint8_t, 4>{{0x00, 0x00, 0x00, 0x00}}));
    assert(discoveredHtv405Profile.pairedEndpoint ==
        (std::array<std::uint8_t, 4>{{0x00, 0x00, 0x00, 0x00}}));
    assert(discoveredHtv405Profile.stepCount ==
        rainpoint::kHtv405PairingStepCount);
    assert(rainpoint::adoptAutomaticHtv405FactoryEndpoint(
        htv405FactoryEndpoint, discoveredHtv405Profile
    ));
    assert(discoveredHtv405Profile.factoryEndpoint == htv405FactoryEndpoint);
    assert(discoveredHtv405Profile.pairedEndpoint ==
        (std::array<std::uint8_t, 4>{{0x94, 0xa9, 0x80, 0x13}}));
    assert(rainpoint::htv405RequestMatches(
        discoveredHtv405Profile, 0, htv405Factory
    ));
    rainpoint::Htv405PairingProfile htv405Profile{};
    assert(rainpoint::buildAutomaticHtv405Profile(
        htv405FactoryEndpoint,
        {{0xb9, 0x84, 0x02, 0x80}},
        {{0x39, 0x84, 0x02, 0x80}},
        htv405Profile
    ));
    const auto htv145FactorySweep0 = fromHex(
        "79f4882f2880000000342d008f80808402ff8f970080bf060000000000000000000000007ccf"
    );
    const auto htv145FactorySweep3 = fromHex(
        "79f4882f2880000000342d008f83808402ff8f970080bf060000000000000000000000005bc2"
    );
    rainpoint::htv145::PairingProfile htv145PairingProbe{};
    assert(rainpoint::htv145::buildProfile(
        {{0x34, 0x2d, 0x00, 0x8f}},
        {{0xb9, 0x84, 0x02, 0x80}},
        {{0x39, 0x84, 0x02, 0x80}},
        htv145PairingProbe
    ));
    assert(htv145PairingProbe.pairedEndpoint ==
        (std::array<std::uint8_t, 4>{{0xb4, 0x2d, 0x00, 0x8f}}));
    assert(rainpoint::htv145::requestMatches(
        htv145PairingProbe, 0, htv145FactorySweep0
    ));
    assert(rainpoint::htv145::requestMatches(
        htv145PairingProbe, 0, htv145FactorySweep3
    ));
    assert(
        htv145PairingProbe.steps[0].requestBody !=
        htv405Profile.steps[0].requestBody
    );
    assert((htv145PairingProbe.steps[0].replyBody[5] & 0x7fU) == 0x06);
    assert(htv405Profile.steps[0].replyBody[5] == 0x02);
    assert(htv405Profile.stepCount == rainpoint::kHtv405PairingStepCount);
    assert(htv145PairingProbe.steps.size() ==
        rainpoint::htv145::kPairingStepCount);
    assert(rainpoint::htv145::kPairingFrequencyOffsetHz == 122'759);
    assert(rainpoint::htv145::kInitialDeviationRegister == 0x45);
    assert(
        rainpoint::htv145::kInitialChannelCenterHz ==
        433'501'466
    );
    assert(
        htv145PairingProbe.steps[0].channelCenterHz ==
        rainpoint::htv145::kInitialChannelCenterHz
    );
    assert(
        htv145PairingProbe.steps[0].channelCenterHz !=
        htv405Profile.steps[0].channelCenterHz
    );
    assert(rainpoint::htv145::replyStartDelayUs(0) == 52'150);
    assert(rainpoint::htv145::replyStartDelayUs(1) == 70'700);
    assert(rainpoint::htv145::replyStartDelayUs(3) == 35'750);
    assert(rainpoint::htv145::replyStartDelayUs(4) == 52'000);
    assert(rainpoint::htv145::replyStartDelayUs(5) == 47'200);
    assert(htv145PairingProbe.steps[0].replyToController);
    assert(htv145PairingProbe.steps[1].replyToController);
    assert(htv145PairingProbe.steps[3].replyToController);
    const rainpoint::PairingLocalDateTime htv145StockClock{
        2026, 9, 1, 12, 43, 48,
    };
    std::array<std::uint8_t, rainpoint::kFrameBytes> htv145Reply{};
    assert(rainpoint::htv145::buildReply(
        htv145PairingProbe, 0, htv145StockClock, htv145Reply
    ));
    assert(htv145Reply == fromHex(
        "79f4882f28b42d008fb984028080c0858500867000f865210d010080000000000000000041c6"
    ));
    assert(rainpoint::htv145::buildConfigurationReply(
        htv145PairingProbe, htv145Reply
    ));
    assert(htv145Reply == fromHex(
        "79f4882f28b42d008fb984028081100101000000000000000000000000000000000000000655"
    ));
    const auto htv145Request1 = fromHex(
        "79f4882f28b9840280b42d008f810107862580804f8000000040800056800000000000005689"
    );
    const auto htv145ConfigurationResponse = fromHex(
        "79f4882f28b9840280b42d008f81500080000000000000000000000000000000000000006f4d"
    );
    const auto htv145ShortRequest = fromHex(
        "79f4882f28b9840280b42d008f81828106008000000000000000000000000000000000003d30"
    );
    const auto htv145ControllerRequest = fromHex(
        "79f4882f28b9840280b42d008f82030186008000000000000000000000000000000000001977"
    );
    const auto htv145ExtendedRequest = fromHex(
        "79f4882f28b9840280b42d008f82ac8099000000000000000000000000000000000000005423"
    );
    rainpoint::htv145::PairingSession htv145Session(htv145PairingProbe);
    htv145Session.arm(0);
    assert(htv145Session.claimReply(htv145FactorySweep0, 1) ==
        &htv145PairingProbe.steps[0]);
    assert(htv145Session.finishReply(true, 2));
    assert(htv145Session.assignmentLocked());
    assert(!htv145Session.stage0Accepted());
    assert(htv145Session.claimReply(htv145Request1, 1'000) ==
        &htv145PairingProbe.steps[1]);
    assert(htv145Session.stage0Accepted());
    assert(htv145Session.finishReply(true, 3'900));
    assert(htv145Session.claimReply(
        htv145ConfigurationResponse, 4'200
    ) == nullptr);
    assert(htv145Session.completedSteps() == 3);
    assert(htv145Session.claimReply(htv145ShortRequest, 5'000) ==
        &htv145PairingProbe.steps[3]);
    assert(htv145Session.finishReply(true, 5'001));
    assert(htv145Session.claimReply(htv145ControllerRequest, 6'000) ==
        &htv145PairingProbe.steps[4]);
    assert(htv145Session.finishReply(true, 6'001));
    assert(htv145Session.claimReply(htv145ExtendedRequest, 7'000) ==
        &htv145PairingProbe.steps[5]);
    assert(htv145Session.finishReply(true, 7'001));
    assert(htv145Session.state() ==
        rainpoint::PairingSessionState::Completed);
    // Once the single assignment has been transmitted, the next factory
    // fallback is explicit stage-0 rejection. It must never cause a second
    // assignment in the same arm window.
    rainpoint::htv145::PairingSession htv145Rejected(htv145PairingProbe);
    htv145Rejected.arm(0);
    assert(htv145Rejected.claimReply(htv145FactorySweep0, 1) ==
        &htv145PairingProbe.steps[0]);
    assert(htv145Rejected.finishReply(true, 2));
    assert(htv145Rejected.claimReply(htv145FactorySweep3, 3'000) == nullptr);
    assert(htv145Rejected.state() == rainpoint::PairingSessionState::Failed);
    assert(htv145Rejected.failureReason() ==
        rainpoint::PairingFailureReason::Stage0Rejected);
    assert(htv145Rejected.stage0Rejected());
    assert(!htv145Rejected.stage0Accepted());
    // Custom gateway identity changes only the association endpoints. Freeze
    // every timing, channel, and request/reply body from the physically
    // accepted stock-identity profile so identity rollout cannot silently
    // perturb the pairing mechanism that succeeded on hardware.
    rainpoint::Htv405PairingProfile htv405CustomIdentityProfile{};
    const std::array<std::uint8_t, 4> customController = {
        {0xe1, 0x23, 0x45, 0x80},
    };
    const std::array<std::uint8_t, 4> customCompanion = {
        {0x61, 0x23, 0x45, 0x80},
    };
    assert(rainpoint::validRfControllerIdentity(
        customController, customCompanion
    ));
    assert(rainpoint::buildAutomaticHtv405Profile(
        htv405FactoryEndpoint,
        customController,
        customCompanion,
        htv405CustomIdentityProfile
    ));
    assert(
        htv405CustomIdentityProfile.factoryEndpoint ==
        htv405Profile.factoryEndpoint
    );
    assert(
        htv405CustomIdentityProfile.pairedEndpoint ==
        htv405Profile.pairedEndpoint
    );
    assert(htv405CustomIdentityProfile.valveRoute == customController);
    assert(htv405CustomIdentityProfile.companionEndpoint == customCompanion);
    for (std::size_t index = 0;
         index < rainpoint::kHtv405PairingStepCount;
         ++index) {
        const auto& retained = htv405Profile.steps[index];
        const auto& generated = htv405CustomIdentityProfile.steps[index];
        assert(generated.requestBody == retained.requestBody);
        assert(generated.replyBody == retained.replyBody);
        assert(generated.replyExpected == retained.replyExpected);
        assert(generated.trailerResidual == retained.trailerResidual);
        assert(generated.channelCenterHz == retained.channelCenterHz);
        assert(generated.deviationRegister == retained.deviationRegister);
    }
    assert(htv405Profile.pairedEndpoint[0] == 0x94);
    assert(rainpoint::htv405RequestMatches(
        htv405Profile, 0, htv405Factory
    ));
    assert(rainpoint::htv405RequestMatches(
        htv405Profile, 1, htv405Request1
    ));
    assert(rainpoint::htv405RequestMatches(
        htv405Profile, 4, htv405RequestNoReply
    ));
    assert(!htv405Profile.steps[4].replyExpected);
    assert(htv405Profile.steps[
        rainpoint::kHtv405Selector2PhaseReplyStepIndex
    ].replyExpected);
    assert(
        htv405Profile.steps[0].deviationRegister ==
        rainpoint::kHtv405InitialDeviationRegister
    );
    // Freeze the physically accepted initial exchange. Later HTV405
    // controller-handshake experiments must not silently recalibrate it.
    assert(rainpoint::kHtv405InitialDeviationRegister == 0x43);
    assert(
        htv405Profile.steps[0].channelCenterHz ==
        rainpoint::kHtv405InitialChannelCenterHz
    );
    assert(rainpoint::kHtv405InitialChannelCenterHz == 433'511'445);
    assert(rainpoint::kPairingWakeSymbols == 320);
    assert(
        htv405Profile.steps[1].deviationRegister ==
        rainpoint::kOrdinaryDeviationRegister
    );
    assert(
        htv405Profile.steps[1].channelCenterHz ==
        rainpoint::kHtv405RoutineChannelCenterHz
    );
    assert(rainpoint::kHtv405AssignmentReplyStartDelayUs == 49'500);
    assert(rainpoint::kHtv405OrdinaryReplyStartDelayUs == 49'500);
    assert(
        rainpoint::kHtv405Selector2PhaseReplyStartDelayUs == 35'650
    );
    assert(
        rainpoint::kHtv405Selector2ImmediateReplyStartDelayUs == 38'000
    );
    assert(
        rainpoint::kHtv405Selector2ShortRepeatReplyStartDelayUs == 39'000
    );
    assert(
        rainpoint::kHtv405Selector2ConfigurationReplyStartDelayUs ==
        997'500
    );
    assert(rainpoint::kHtv405Selector2ConfigurationWakeSymbols == 2'400);
    std::array<std::uint8_t, rainpoint::kFrameBytes> htv405Reply{};
    const rainpoint::PairingLocalDateTime htv405Clock = {
        2026, 8, 17, 18, 56, 58,
    };
    assert(rainpoint::buildHtv405PairingReply(
        htv405Profile, 0, htv405Clock, htv405Reply
    ));
    assert(htv405Reply == fromHex(
        "79f4882f2894a980133984028080c08585030270009d97910d01008000000000000000007447"
    ));
    std::array<std::uint8_t, rainpoint::kFrameBytes>
        htv405CustomIdentityReply{};
    assert(rainpoint::buildHtv405PairingReply(
        htv405CustomIdentityProfile,
        0,
        htv405Clock,
        htv405CustomIdentityReply
    ));
    for (std::size_t index = 0; index < 4; ++index) {
        assert(
            htv405CustomIdentityReply[5 + index] ==
            htv405Profile.pairedEndpoint[index]
        );
        assert(
            htv405CustomIdentityReply[9 + index] == customCompanion[index]
        );
    }
    for (std::size_t index = 13; index < 36; ++index) {
        assert(htv405CustomIdentityReply[index] == htv405Reply[index]);
    }
    assert(rainpoint::hasOrdinaryTrailer(htv405CustomIdentityReply));
    assert(
        rainpoint::trailerResidual(htv405CustomIdentityReply) ==
        rainpoint::kCurrentPairingTrailerResidual
    );
    assert(!rainpoint::buildHtv405PairingReply(
        htv405Profile, 4, htv405Clock, htv405Reply
    ));
    assert(rainpoint::buildHtv405PairingReply(
        htv405Profile,
        rainpoint::kHtv405Selector2ConfigurationStepIndex,
        htv405Clock,
        htv405Reply
    ));
    assert(htv405Reply == fromHex(
        "79f4882f2894a980133984028082410100008000000000000000000000000000000000007b1d"
    ));
    assert(rainpoint::buildHtv405PairingReply(
        htv405Profile,
        rainpoint::kHtv405Selector2PhaseReplyStepIndex,
        htv405Clock,
        htv405Reply
    ));
    assert(htv405Reply == fromHex(
        "79f4882f2894a980133984028081c10100008000000000000000000000000000000000006e95"
    ));
    assert(rainpoint::buildHtv405Selector2ConfigurationReply(
        htv405Profile,
        htv405Reply
    ));
    assert(htv405Reply == fromHex(
        "79f4882f2894a980133984028082100101000000000000000000000000000000000000002465"
    ));
    // The immediate acknowledgement follows the ordinary counter offset.
    assert(rainpoint::buildHtv405PairingReply(
        htv405Profile,
        rainpoint::kHtv405Selector2ConfigurationStepIndex,
        htv405Clock,
        htv405Reply,
        3
    ));
    assert(htv405Reply[13] == 0x85);
    // The subsequent controller transition shares the same transaction
    // counter while retaining its distinct 10/01/01 command body.
    assert(rainpoint::buildHtv405Selector2ConfigurationReply(
        htv405Profile,
        htv405Reply,
        3
    ));
    assert(htv405Reply == fromHex(
        "79f4882f2894a980133984028085100101000000000000000000000000000000000000000f75"
    ));
    // A later-sweep assignment can first expose the repeated 02/81 request.
    // The session re-anchors it as shifted step 2, then answers 03/01 as
    // shifted step 3. The immediate 83/41 acknowledgement and long-wake
    // 83/10 configuration must share sequence 3. Preserve it as association
    // diagnostics; it is not sufficient evidence to initialize the distinct
    // watering-command counter.
    rainpoint::Htv405PairingSession shiftedConfigurationSession(
        htv405Profile
    );
    shiftedConfigurationSession.arm(17'000);
    assert(shiftedConfigurationSession.claimReply(
        htv405Factory, 17'050
    ) == &htv405Profile.steps[0]);
    assert(shiftedConfigurationSession.finishReply(true, 17'060));
    auto shiftedInitialRepeat = htv405Request(htv405Profile, 2, 1);
    assert(shiftedConfigurationSession.claimReply(
        shiftedInitialRepeat, 17'100
    ) == &htv405Profile.steps[2]);
    assert(!shiftedConfigurationSession.isSelector2ConfigurationStep(2));
    assert(shiftedConfigurationSession.finishReply(true, 17'110));
    auto shiftedConfigurationTrigger = htv405Request(htv405Profile, 3, 1);
    assert(shiftedConfigurationSession.claimReply(
        shiftedConfigurationTrigger, 17'200
    ) == &htv405Profile.steps[3]);
    assert(shiftedConfigurationSession.replyCounterOffset() == 1);
    assert(shiftedConfigurationSession.isSelector2ConfigurationStep(3));
    assert(rainpoint::buildHtv405PairingReply(
        htv405Profile,
        3,
        htv405Clock,
        htv405Reply,
        shiftedConfigurationSession.replyCounterOffset()
    ));
    assert(htv405Reply[13] == 0x83);
    const std::uint8_t shiftedConfigurationOffset =
        static_cast<std::uint8_t>(
            ((htv405Reply[13] & 0x7fU) - 0x02U) & 0x7fU
        );
    assert(rainpoint::buildHtv405Selector2ConfigurationReply(
        htv405Profile,
        htv405Reply,
        shiftedConfigurationOffset
    ));
    assert(htv405Reply[13] == 0x83);
    shiftedConfigurationSession.markSelector2ConfigurationTransmitted(
        htv405Reply[13]
    );
    assert(
        shiftedConfigurationSession.selector2ConfigurationTransmitted()
    );
    assert(
        shiftedConfigurationSession.selector2ConfigurationSequence() == 3
    );
    // Marking diagnostics must not suppress retransmission handling.
    assert(shiftedConfigurationSession.isSelector2ConfigurationStep(3));
    assert(shiftedConfigurationSession.finishReply(true, 17'210));
    auto laterHtv405Factory = htv405Factory;
    laterHtv405Factory[13] = 0x02;
    laterHtv405Factory[14] = 0x00;
    rainpoint::writeTrailer(laterHtv405Factory, 0xc713);
    assert(rainpoint::htv405RequestMatches(
        htv405Profile, 0, laterHtv405Factory
    ));
    auto coldBootHtv405Factory = laterHtv405Factory;
    coldBootHtv405Factory[17] = 0x7f;
    rainpoint::writeTrailer(coldBootHtv405Factory, 0xc713);
    assert(!rainpoint::htv405RequestMatches(
        htv405Profile, 0, coldBootHtv405Factory
    ));
    assert(rainpoint::htv405RetainedRejoinRequestMatches(
        htv405Profile, coldBootHtv405Factory
    ));
    auto wrongProductColdBoot = coldBootHtv405Factory;
    wrongProductColdBoot[16] ^= 0x01;
    rainpoint::writeTrailer(wrongProductColdBoot, 0xc713);
    assert(!rainpoint::htv405RetainedRejoinRequestMatches(
        htv405Profile, wrongProductColdBoot
    ));
    rainpoint::Htv405PairingSession isolatedNewPairingSession(htv405Profile);
    isolatedNewPairingSession.arm(18'000);
    assert(isolatedNewPairingSession.claimReply(
        coldBootHtv405Factory, 18'100
    ) == nullptr);
    assert(isolatedNewPairingSession.completedSteps() == 0);
    assert(
        isolatedNewPairingSession.state() ==
        rainpoint::PairingSessionState::Armed
    );
    rainpoint::Htv405PairingSession htv405RejoinSession(htv405Profile);
    htv405RejoinSession.arm(19'000, 120'000, true);
    assert(htv405RejoinSession.claimReply(
        htv405Factory, 19'050
    ) == nullptr);
    assert(htv405RejoinSession.completedSteps() == 0);
    assert(htv405RejoinSession.claimReply(
        coldBootHtv405Factory, 19'100
    ) == &htv405Profile.steps[0]);
    assert(htv405RejoinSession.finishReply(true, 19'110));
    assert(htv405RejoinSession.completedSteps() == 1);
    assert(
        htv405RejoinSession.state() ==
        rainpoint::PairingSessionState::Armed
    );
    const auto htv405RejoinFirstPairedRequest = htv405Request(
        htv405Profile, 1
    );
    assert(htv405RejoinSession.claimReply(
        htv405RejoinFirstPairedRequest, 19'200
    ) == &htv405Profile.steps[1]);
    assert(htv405RejoinSession.finishReply(true, 19'210));
    assert(htv405RejoinSession.completedSteps() == 2);
    rainpoint::Htv405PairingSession htv405RetrySession(htv405Profile);
    htv405RetrySession.arm(20'000);
    assert(htv405RetrySession.claimReply(htv405Factory, 20'100) ==
        &htv405Profile.steps[0]);
    assert(htv405RetrySession.finishReply(true, 20'110));
    assert(htv405RetrySession.completedSteps() == 1);
    assert(htv405RetrySession.claimReply(laterHtv405Factory, 20'200) ==
        &htv405Profile.steps[0]);
    assert(htv405RetrySession.finishReply(true, 20'210));
    assert(htv405RetrySession.completedSteps() == 1);
    // The deadline-scheduled local assignment was accepted on factory sweep
    // counter 3. The valve then began the ordinary logical 01/01 sequence at
    // transaction counter 4, proving that the whole transcript is shifted
    // rather than skipped forward.
    const auto htv405ShiftedInitialRequest = fromHex(
        "79f4882f28b984028094a98013040107822580804f8000000040800056800000000000002db9"
    );
    const auto htv405ShiftedInitialRepeat = fromHex(
        "79f4882f28b984028094a98013048107822580804f8000000040800056800000000000001f3c"
    );
    assert(rainpoint::htv405RequestMatches(
        htv405Profile, 1, htv405ShiftedInitialRequest, 3
    ));
    assert(rainpoint::htv405RequestMatches(
        htv405Profile, 2, htv405ShiftedInitialRepeat, 3
    ));
    rainpoint::Htv405PairingSession htv405ResyncSession(htv405Profile);
    htv405ResyncSession.arm(25'000);
    assert(htv405ResyncSession.claimReply(htv405Factory, 25'100) ==
        &htv405Profile.steps[0]);
    assert(htv405ResyncSession.finishReply(true, 25'110));
    assert(htv405ResyncSession.completedSteps() == 1);
    assert(htv405ResyncSession.claimReply(
        htv405ShiftedInitialRequest, 25'200
    ) == &htv405Profile.steps[1]);
    assert(htv405ResyncSession.counterOffsetKnown());
    assert(htv405ResyncSession.counterOffset() == 3);
    assert(rainpoint::buildHtv405PairingReply(
        htv405Profile,
        1,
        htv405Clock,
        htv405Reply,
        htv405ResyncSession.counterOffset()
    ));
    assert(htv405Reply[13] == 0x84);
    assert(rainpoint::hasOrdinaryTrailer(htv405Reply));
    assert(htv405ResyncSession.finishReply(true, 25'210));
    assert(htv405ResyncSession.completedSteps() == 2);
    assert(htv405ResyncSession.claimReply(
        htv405ShiftedInitialRepeat, 25'300
    ) == &htv405Profile.steps[2]);
    assert(rainpoint::buildHtv405PairingReply(
        htv405Profile,
        2,
        htv405Clock,
        htv405Reply,
        htv405ResyncSession.counterOffset()
    ));
    assert(htv405Reply[13] == 0x84);
    assert(htv405Reply[14] == 0xc1);
    assert(htv405ResyncSession.finishReply(true, 25'310));
    assert(htv405ResyncSession.completedSteps() == 3);
    for (std::size_t index = 3;
         index < rainpoint::kHtv405PairingStepCount;
         ++index) {
        std::array<std::uint8_t, rainpoint::kFrameBytes> request{};
        for (std::size_t syncIndex = 0;
             syncIndex < rainpoint::kSync.size();
             ++syncIndex) {
            request[syncIndex] = rainpoint::kSync[syncIndex];
        }
        for (std::size_t endpointIndex = 0; endpointIndex < 4; ++endpointIndex) {
            request[5 + endpointIndex] = htv405Profile.valveRoute[endpointIndex];
            request[9 + endpointIndex] =
                htv405Profile.pairedEndpoint[endpointIndex];
        }
        for (std::size_t bodyIndex = 0; bodyIndex < 23; ++bodyIndex) {
            request[13 + bodyIndex] =
                htv405Profile.steps[index].requestBody[bodyIndex];
        }
        request[13] = rainpoint::htv405ShiftedCounter(request[13], 3);
        rainpoint::writeTrailer(request, 0xc713);
        const auto* step = htv405ResyncSession.claimReply(
            request, 25'400 + static_cast<std::uint32_t>(index) * 100
        );
        if (htv405Profile.steps[index].replyExpected) {
            assert(step == &htv405Profile.steps[index]);
            assert(rainpoint::buildHtv405PairingReply(
                htv405Profile, index, htv405Clock, htv405Reply, 3
            ));
            assert(htv405Reply[13] == rainpoint::htv405ShiftedCounter(
                htv405Profile.steps[index].replyBody[0], 3
            ));
            assert(htv405ResyncSession.finishReply(
                true, 25'410 + static_cast<std::uint32_t>(index) * 100
            ));
        } else {
            assert(step == nullptr);
            assert(htv405ResyncSession.completedSteps() == index + 1);
        }
    }
    assert(
        htv405ResyncSession.state() ==
        rainpoint::PairingSessionState::Completed
    );
    assert(
        htv405ResyncSession.completedSteps() ==
        rainpoint::kHtv405PairingStepCount
    );
    // A successful later-sweep assignment observed on 2026-08-23 entered at
    // 02/81, confirmed the shifted 83/10 controller command, then repeated
    // the long 04/01 and 04/81 phase pair before short-form initialization.
    // Preserve the accepted initial exchange while allowing only that proven
    // post-configuration continuation at step 6.
    const auto htv405ObservedStartRepeat = fromHex(
        "79f4882f28b984028094a98013028107822580804f8000000040800056800000000000005127"
    );
    const auto htv405ObservedConfigurationRequest = fromHex(
        "79f4882f28b984028094a98013030107822580804f80000000408000568000000000000006a9"
    );
    const auto htv405ObservedPostConfiguration = fromHex(
        "79f4882f28b984028094a98013040107820581004f8000000040800056800000000000004d3a"
    );
    const auto htv405ObservedPostConfigurationRepeat = fromHex(
        "79f4882f28b984028094a98013048107820581004f8000000040800056800000000000007fbf"
    );
    const auto htv405ObservedNextOrdinary = fromHex(
        "79f4882f28b984028094a98013050107820581004f8000000040800056800000000000002831"
    );
    rainpoint::Htv405PairingSession htv405PostConfigurationSession(
        htv405Profile
    );
    htv405PostConfigurationSession.arm(27'000);
    assert(htv405PostConfigurationSession.claimReply(
        htv405Factory, 27'100
    ) == &htv405Profile.steps[0]);
    assert(htv405PostConfigurationSession.finishReply(true, 27'110));
    assert(htv405PostConfigurationSession.claimReply(
        htv405ObservedStartRepeat, 27'200
    ) == &htv405Profile.steps[2]);
    assert(htv405PostConfigurationSession.replyCounterOffset() == 1);
    assert(htv405PostConfigurationSession.finishReply(true, 27'210));
    assert(htv405PostConfigurationSession.claimReply(
        htv405ObservedConfigurationRequest, 27'300
    ) == &htv405Profile.steps[3]);
    assert(htv405PostConfigurationSession.replyCounterOffset() == 1);
    assert(htv405PostConfigurationSession.finishReply(true, 27'310));
    assert(htv405PostConfigurationSession.claimReply(
        htv405ObservedPostConfiguration, 27'400
    ) == &htv405Profile.steps[5]);
    assert(htv405PostConfigurationSession.replyCounterOffset() == 1);
    assert(htv405PostConfigurationSession.finishReply(true, 27'410));
    assert(htv405PostConfigurationSession.completedSteps() == 6);
    assert(htv405PostConfigurationSession.claimReply(
        htv405ObservedPostConfigurationRepeat, 27'500
    ) == &htv405Profile.steps[2]);
    assert(htv405PostConfigurationSession.replyCounterOffset() == 3);
    assert(rainpoint::buildHtv405PairingReply(
        htv405Profile,
        rainpoint::kHtv405Selector2PhaseReplyStepIndex,
        htv405Clock,
        htv405Reply,
        htv405PostConfigurationSession.replyCounterOffset()
    ));
    assert(htv405Reply == fromHex(
        "79f4882f2894a980133984028084c10100008000000000000000000000000000000000008f93"
    ));
    assert(htv405PostConfigurationSession.finishReply(true, 27'510));
    assert(htv405PostConfigurationSession.completedSteps() == 6);
    assert(htv405PostConfigurationSession.claimReply(
        htv405ObservedNextOrdinary, 27'600
    ) == &htv405Profile.steps[5]);
    assert(htv405PostConfigurationSession.replyCounterOffset() == 2);
    assert(rainpoint::buildHtv405PairingReply(
        htv405Profile,
        rainpoint::kHtv405Selector2InitialOrdinaryStepIndex,
        htv405Clock,
        htv405Reply,
        htv405PostConfigurationSession.replyCounterOffset()
    ));
    assert(htv405Reply[13] == 0x85);
    assert(htv405Reply[14] == 0x41);
    assert(htv405PostConfigurationSession.finishReply(true, 27'610));
    assert(htv405PostConfigurationSession.completedSteps() == 6);
    auto htv405ShiftedShortRequest = fromHex(
        "79f4882f28b984028094a9801303828102008000000000000000000000000000000000000000"
    );
    htv405ShiftedShortRequest[13] = 0x05;
    rainpoint::writeTrailer(htv405ShiftedShortRequest, 0xc713);
    assert(htv405PostConfigurationSession.claimReply(
        htv405ShiftedShortRequest, 27'700
    ) == &htv405Profile.steps[6]);
    assert(htv405PostConfigurationSession.counterOffset() == 2);
    assert(htv405PostConfigurationSession.replyCounterOffset() == 2);
    assert(htv405PostConfigurationSession.finishReply(true, 27'710));
    assert(htv405PostConfigurationSession.completedSteps() == 7);
    const auto htv405ObservedShortOrdinary = fromHex(
        "79f4882f28b984028094a98013090281020080000000000000000000000000000000000005a8"
    );
    const auto htv405ObservedShortRepeat = fromHex(
        "79f4882f28b984028094a980130982810200800000000000000000000000000000000000372d"
    );
    const auto htv405ObservedNextShortOrdinary = fromHex(
        "79f4882f28b984028094a980130a0281020080000000000000000000000000000000000022a5"
    );
    assert(rainpoint::htv405RequestMatches(
        htv405Profile, 7, htv405ObservedShortOrdinary, 5
    ));
    assert(rainpoint::htv405RequestMatches(
        htv405Profile, 8, htv405ObservedShortRepeat, 5
    ));
    assert(rainpoint::htv405RequestMatches(
        htv405Profile, 9, htv405ObservedNextShortOrdinary, 5
    ));
    assert(rainpoint::buildHtv405PairingReply(
        htv405Profile, 7, htv405Clock, htv405Reply, 5
    ));
    assert(htv405Reply[13] == 0x89);
    assert(htv405Reply[14] == 0x42);
    assert(rainpoint::hasOrdinaryTrailer(htv405Reply));
    assert(rainpoint::buildHtv405PairingReply(
        htv405Profile, 8, htv405Clock, htv405Reply, 5
    ));
    assert(htv405Reply[13] == 0x89);
    assert(htv405Reply[14] == 0xc2);
    assert(rainpoint::hasOrdinaryTrailer(htv405Reply));
    assert(rainpoint::buildHtv405PairingReply(
        htv405Profile, 9, htv405Clock, htv405Reply, 5
    ));
    assert(htv405Reply[13] == 0x8a);
    assert(htv405Reply[14] == 0x42);
    assert(rainpoint::hasOrdinaryTrailer(htv405Reply));

    // The 2026-08-23 successful local association reached step 10, then sent
    // 0b/82 with state 1 instead of transitioning to selector-2 0b/83. This
    // is a bounded retry of logical 04/82, not a new pairing branch. Re-anchor
    // its counter and answer it in the stock gateway's measured 39 ms slot.
    rainpoint::Htv405PairingSession htv405LateRetrySession(htv405Profile);
    htv405LateRetrySession.arm(28'000);
    for (std::size_t index = 0; index <= 9; ++index) {
        const auto request = htv405Request(
            htv405Profile, index, index == 0 ? 0 : 6
        );
        const auto* step = htv405LateRetrySession.claimReply(
            request, 28'100 + static_cast<std::uint32_t>(index) * 100
        );
        if (htv405Profile.steps[index].replyExpected) {
            assert(step == &htv405Profile.steps[index]);
            assert(htv405LateRetrySession.finishReply(
                true, 28'110 + static_cast<std::uint32_t>(index) * 100
            ));
        } else {
            assert(step == nullptr);
        }
    }
    assert(htv405LateRetrySession.completedSteps() == 10);
    const auto htv405ObservedLateRepeat = fromHex(
        "79f4882f28b984028094a980130b828102018000000000000000000000000000000000002324"
    );
    assert(htv405LateRetrySession.claimReply(
        htv405ObservedLateRepeat, 29'200
    ) == &htv405Profile.steps[8]);
    assert(htv405LateRetrySession.replyCounterOffset() == 7);
    assert(
        htv405LateRetrySession.replyStartDelayOverrideUs() ==
        rainpoint::kHtv405Selector2ShortRepeatReplyStartDelayUs
    );
    assert(rainpoint::buildHtv405PairingReply(
        htv405Profile,
        8,
        htv405Clock,
        htv405Reply,
        htv405LateRetrySession.replyCounterOffset()
    ));
    assert(htv405Reply[13] == 0x8b);
    assert(htv405Reply[14] == 0xc2);
    assert(htv405LateRetrySession.finishReply(true, 29'210));
    assert(htv405LateRetrySession.completedSteps() == 10);

    // Once the earlier repeat is accepted, state 2 is the final xx/02
    // request. Its acknowledgement keeps the re-anchored offset, allowing the
    // stock xx/83 transcript to resume normally at logical step 10.
    const auto htv405AdvancedOrdinary = htv405Request(
        htv405Profile, 9, 7
    );
    assert(htv405AdvancedOrdinary[13] == 0x0c);
    assert(htv405AdvancedOrdinary[14] == 0x02);
    assert(htv405AdvancedOrdinary[17] == 0x02);
    assert(htv405LateRetrySession.claimReply(
        htv405AdvancedOrdinary, 29'300
    ) == &htv405Profile.steps[9]);
    assert(htv405LateRetrySession.replyCounterOffset() == 7);
    assert(htv405LateRetrySession.replyStartDelayOverrideUs() == 0);
    assert(htv405LateRetrySession.finishReply(true, 29'310));
    assert(htv405LateRetrySession.completedSteps() == 10);
    const auto htv405ResumedTransition = htv405Request(
        htv405Profile, 10, 7
    );
    assert(htv405ResumedTransition[13] == 0x0c);
    assert(htv405ResumedTransition[14] == 0x83);
    assert(htv405LateRetrySession.claimReply(
        htv405ResumedTransition, 29'400
    ) == &htv405Profile.steps[10]);
    assert(htv405LateRetrySession.finishReply(true, 29'410));
    assert(htv405LateRetrySession.completedSteps() == 11);

    // Probe.10 then observed the correct selector-2 03/83 families with their
    // state triplet still one phase behind the stock transcript. The route,
    // counter, marker, selector, and remaining payload stay exact.
    const auto htv405ObservedControllerOrdinary = fromHex(
        "79f4882f28b984028094a980130b030182008000000000000000000000000000000000007661"
    );
    assert(rainpoint::htv405RequestMatches(
        htv405Profile, 11, htv405ObservedControllerOrdinary, 5
    ));
    auto htv405ShiftedControllerOrdinary =
        htv405ObservedControllerOrdinary;
    htv405ShiftedControllerOrdinary[13] = 0x0d;
    rainpoint::writeTrailer(htv405ShiftedControllerOrdinary, 0xc713);
    assert(htv405LateRetrySession.claimReply(
        htv405ShiftedControllerOrdinary, 29'500
    ) == &htv405Profile.steps[11]);
    assert(htv405LateRetrySession.finishReply(true, 29'510));
    assert(htv405LateRetrySession.completedSteps() == 12);
    const auto htv405ObservedControllerRepeat = fromHex(
        "79f4882f28b984028094a980130b8301820080000000000000000000000000000000000044e4"
    );
    assert(rainpoint::htv405RequestMatches(
        htv405Profile, 12, htv405ObservedControllerRepeat, 5
    ));
    auto htv405ShiftedControllerRepeat = htv405ObservedControllerRepeat;
    htv405ShiftedControllerRepeat[13] = 0x0d;
    rainpoint::writeTrailer(htv405ShiftedControllerRepeat, 0x4f03);
    assert(htv405LateRetrySession.claimReply(
        htv405ShiftedControllerRepeat, 29'600
    ) == &htv405Profile.steps[12]);
    assert(htv405LateRetrySession.finishReply(true, 29'610));
    assert(htv405LateRetrySession.completedSteps() == 13);
    const auto htv405ObservedControllerNext = fromHex(
        "79f4882f28b984028094a980130c030182008000000000000000000000000000000000005d71"
    );
    assert(rainpoint::htv405RequestMatches(
        htv405Profile, 13, htv405ObservedControllerNext, 5
    ));
    auto htv405ShiftedControllerNext = htv405ObservedControllerNext;
    htv405ShiftedControllerNext[13] = 0x0e;
    rainpoint::writeTrailer(htv405ShiftedControllerNext, 0xc713);
    assert(htv405LateRetrySession.claimReply(
        htv405ShiftedControllerNext, 29'700
    ) == &htv405Profile.steps[13]);
    assert(htv405LateRetrySession.finishReply(true, 29'710));
    assert(htv405LateRetrySession.completedSteps() == 14);

    // Probe.11 physically reached step 14, then the valve repeated the 03/83
    // controller-authorization pair with an advancing transaction counter.
    // These retries must be acknowledged without rewinding or advancing the
    // logical transcript until the captured AC extended request appears.
    const auto htv405ObservedLateControllerOrdinary = fromHex(
        "79f4882f28b984028094a980130c030182010000000000000000000000000000000000006471"
    );
    assert(htv405LateRetrySession.claimReply(
        htv405ObservedLateControllerOrdinary, 29'800
    ) == &htv405Profile.steps[11]);
    assert(htv405LateRetrySession.replyCounterOffset() == 6);
    assert(htv405LateRetrySession.finishReply(true, 29'810));
    assert(htv405LateRetrySession.completedSteps() == 14);
    const auto htv405ObservedLateControllerRepeat = fromHex(
        "79f4882f28b984028094a980130c8301820100000000000000000000000000000000000056f4"
    );
    assert(htv405LateRetrySession.claimReply(
        htv405ObservedLateControllerRepeat, 29'900
    ) == &htv405Profile.steps[12]);
    assert(htv405LateRetrySession.replyCounterOffset() == 6);
    assert(htv405LateRetrySession.finishReply(true, 29'910));
    assert(htv405LateRetrySession.completedSteps() == 14);
    const auto htv405ObservedLaterControllerOrdinary = fromHex(
        "79f4882f28b984028094a980130d03018201000000000000000000000000000000000000017a"
    );
    assert(htv405LateRetrySession.claimReply(
        htv405ObservedLaterControllerOrdinary, 30'000
    ) == &htv405Profile.steps[11]);
    assert(htv405LateRetrySession.replyCounterOffset() == 7);
    assert(htv405LateRetrySession.finishReply(true, 30'010));
    assert(htv405LateRetrySession.completedSteps() == 14);
    auto htv405ObservedFinalControllerOrdinary =
        htv405ObservedLaterControllerOrdinary;
    htv405ObservedFinalControllerOrdinary[17] = 0x02;
    rainpoint::writeTrailer(htv405ObservedFinalControllerOrdinary, 0xc713);
    assert(htv405LateRetrySession.claimReply(
        htv405ObservedFinalControllerOrdinary, 30'100
    ) == &htv405Profile.steps[13]);
    assert(htv405LateRetrySession.replyCounterOffset() == 6);
    assert(htv405LateRetrySession.finishReply(true, 30'110));
    assert(htv405LateRetrySession.completedSteps() == 14);

    auto htv405ExtendedStart = htv405Request(htv405Profile, 14, 6);
    assert(htv405LateRetrySession.claimReply(
        htv405ExtendedStart, 30'200
    ) == &htv405Profile.steps[14]);
    assert(htv405LateRetrySession.finishReply(true, 30'210));
    assert(htv405LateRetrySession.completedSteps() == 15);
    const auto htv405ObservedExtendedStartRepeat = fromHex(
        "79f4882f28b984028094a9801311ac8099000000000000000000000000000000000000000fa2"
    );
    assert(htv405LateRetrySession.claimReply(
        htv405ObservedExtendedStartRepeat, 30'300
    ) == &htv405Profile.steps[14]);
    assert(htv405LateRetrySession.replyCounterOffset() == 10);
    assert(htv405LateRetrySession.finishReply(true, 30'310));
    assert(htv405LateRetrySession.completedSteps() == 15);
    // The physical selector-2 request retains state 00 where the stock
    // selector-6 fixture row carried 80. Every other byte remains exact.
    const auto htv405ObservedExtendedNext = fromHex(
        "79f4882f28b984028094a98013122c8099000000000000000000000000000000000000001a2a"
    );
    assert(htv405LateRetrySession.claimReply(
        htv405ObservedExtendedNext, 30'400
    ) == &htv405Profile.steps[15]);
    assert(rainpoint::buildHtv405PairingReply(
        htv405Profile,
        15,
        htv405Clock,
        htv405Reply,
        htv405LateRetrySession.replyCounterOffset()
    ));
    assert(htv405Reply[14] == 0x6c);
    // The valve can retain stale state 00 while retrying this 2C/99 row. The
    // gateway must send the stock advancing state 86 in the measured 39 ms
    // slot; echoing 06 left probe.15 parked in the 99-family loop.
    assert(htv405Reply[18] == 0x86);
    assert(rainpoint::hasOrdinaryTrailer(htv405Reply));
    assert(
        rainpoint::htv405PairingReplyStartDelayUs(14) ==
        rainpoint::kHtv405OrdinaryReplyStartDelayUs
    );
    assert(
        rainpoint::htv405PairingReplyStartDelayUs(15) == 39'000
    );
    assert(
        rainpoint::htv405PairingReplyStartDelayUs(16) == 41'000
    );
    assert(
        rainpoint::htv405PairingReplyStartDelayUs(17) == 39'000
    );
    assert(htv405LateRetrySession.finishReply(true, 30'410));
    assert(htv405LateRetrySession.completedSteps() == 16);
    const auto htv405ObservedEarlierExtendedRepeat = fromHex(
        "79f4882f28b984028094a9801312ac80990000000000000000000000000000000000000028af"
    );
    assert(htv405LateRetrySession.claimReply(
        htv405ObservedEarlierExtendedRepeat, 30'500
    ) == &htv405Profile.steps[15]);
    assert(htv405LateRetrySession.replyCounterOffset() == 10);
    assert(htv405LateRetrySession.replyMarkerRepeat());
    assert(rainpoint::buildHtv405PairingReply(
        htv405Profile,
        15,
        htv405Clock,
        htv405Reply,
        htv405LateRetrySession.replyCounterOffset()
    ));
    htv405Reply[14] = static_cast<std::uint8_t>(
        htv405Reply[14] | 0x80U
    );
    rainpoint::writeTrailer(
        htv405Reply, htv405Profile.steps[15].trailerResidual
    );
    assert(htv405Reply[13] == 0x92);
    assert(htv405Reply[14] == 0xec);
    assert(htv405Reply[18] == 0x86);
    assert(rainpoint::hasOrdinaryTrailer(htv405Reply));
    assert(htv405LateRetrySession.finishReply(true, 30'510));
    assert(htv405LateRetrySession.completedSteps() == 16);
    auto htv405ExtendedPhaseTwo = htv405Request(htv405Profile, 16, 10);
    assert(htv405LateRetrySession.claimReply(
        htv405ExtendedPhaseTwo, 30'600
    ) == &htv405Profile.steps[16]);
    assert(!htv405LateRetrySession.replyMarkerRepeat());
    assert(htv405LateRetrySession.finishReply(true, 30'610));
    assert(htv405LateRetrySession.completedSteps() == 17);
    auto htv405ExtendedFinal = htv405Request(htv405Profile, 17, 10);
    htv405ExtendedFinal[17] = 0x00;
    rainpoint::writeTrailer(htv405ExtendedFinal, 0xc713);
    assert(htv405LateRetrySession.claimReply(
        htv405ExtendedFinal, 30'700
    ) == &htv405Profile.steps[17]);
    assert(rainpoint::buildHtv405PairingReply(
        htv405Profile,
        17,
        htv405Clock,
        htv405Reply,
        htv405LateRetrySession.replyCounterOffset()
    ));
    assert(htv405Reply[14] == 0x6c);
    assert(htv405Reply[18] == 0x86);
    assert(rainpoint::hasOrdinaryTrailer(htv405Reply));
    assert(htv405LateRetrySession.finishReply(true, 30'710));
    assert(htv405LateRetrySession.completedSteps() == 18);
    assert(
        htv405LateRetrySession.state() ==
        rainpoint::PairingSessionState::Completed
    );

    rainpoint::Htv405PairingSession htv405Session(htv405Profile);
    htv405Session.arm(30'000);
    for (std::size_t index = 0;
         index < rainpoint::kHtv405PairingStepCount;
         ++index) {
        std::array<std::uint8_t, rainpoint::kFrameBytes> request{};
        for (std::size_t syncIndex = 0;
             syncIndex < rainpoint::kSync.size();
             ++syncIndex) {
            request[syncIndex] = rainpoint::kSync[syncIndex];
        }
        const auto& endpointA = index == 0
            ? std::array<std::uint8_t, 4>{{0x80, 0x00, 0x00, 0x00}}
            : htv405Profile.valveRoute;
        const auto& endpointB = index == 0
            ? htv405Profile.factoryEndpoint
            : htv405Profile.pairedEndpoint;
        for (std::size_t endpointIndex = 0; endpointIndex < 4; ++endpointIndex) {
            request[5 + endpointIndex] = endpointA[endpointIndex];
            request[9 + endpointIndex] = endpointB[endpointIndex];
        }
        for (std::size_t bodyIndex = 0; bodyIndex < 23; ++bodyIndex) {
            request[13 + bodyIndex] =
                htv405Profile.steps[index].requestBody[bodyIndex];
        }
        rainpoint::writeTrailer(request, 0xc713);
        const auto* step = htv405Session.claimReply(
            request, 31'000 + static_cast<std::uint32_t>(index) * 100
        );
        if (htv405Profile.steps[index].replyExpected) {
            assert(step == &htv405Profile.steps[index]);
            assert(htv405Session.finishReply(
                true, 31'010 + static_cast<std::uint32_t>(index) * 100
            ));
        } else {
            assert(step == nullptr);
            assert(htv405Session.completedSteps() == index + 1);
        }
    }
    assert(
        htv405Session.state() == rainpoint::PairingSessionState::Completed
    );
    assert(
        htv405Session.completedSteps() == rainpoint::kHtv405PairingStepCount
    );
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
    for (std::size_t index = 0; index < 256; ++index) {
        assert(rainpoint::rainpointSymbol(
            profile.steps[0].frame, 320, index, false, 256
        ) == static_cast<std::uint8_t>(index & 1U));
        assert(rainpoint::rainpointSymbol(
            profile.steps[0].frame, 320, index, false, 256, true
        ) == static_cast<std::uint8_t>((index & 1U) ^ 1U));
    }
    for (std::size_t index = 0; index < 320; ++index) {
        assert(rainpoint::rainpointSymbol(
            profile.steps[0].frame, 320, 256 + index, false, 256
        ) == static_cast<std::uint8_t>(index & 1U));
        assert(rainpoint::rainpointSymbol(
            profile.steps[0].frame,
            320,
            256 + index,
            false,
            256,
            true
        ) == static_cast<std::uint8_t>(index & 1U));
    }
    assert(rainpoint::rainpointSymbol(
        profile.steps[0].frame, 320, 576, false, 256
    ) == 0);
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

    const rainpoint::Htv145Link htv145Link{
        {{0xb4, 0x2d, 0x00, 0x8f}},
        {{0xb9, 0x84, 0x02, 0x80}},
    };
    assert(rainpoint::validHtv145Link(htv145Link));
    assert(rainpoint::kHtv145CommandWakeSymbols == 1'200);
    assert((
        rainpoint::kHtv145CommandAttemptOffsetsMs ==
        std::array<std::uint32_t, 3>{{0, 730, 1'670}}
    ));
    std::array<std::uint8_t, rainpoint::kFrameBytes> htv145Frame{};
    assert(rainpoint::buildHtv145OpenFrame(
        htv145Link, 0x97, 60, 0xc713, htv145Frame
    ));
    assert(
        htv145Frame == fromHex(
            "79f4882f28b42d008fb98402809710828081009e000000000000000000000000000000003824"
        )
    );
    assert(rainpoint::buildHtv145CloseFrame(
        htv145Link, 0x97, 0x4f03, htv145Frame
    ));
    assert(
        htv145Frame == fromHex(
            "79f4882f28b42d008fb984028097908180810000000000000000000000000000000000006fcf"
        )
    );
    assert(!rainpoint::buildHtv145OpenFrame(
        htv145Link, 0x97, 61, 0xc713, htv145Frame
    ));
    assert(!rainpoint::buildHtv145OpenFrame(
        htv145Link, 0x7f, 60, 0xc713, htv145Frame
    ));
    assert(rainpoint::nextHtv145CommandSequence(0x9f) == 0x80);

    rainpoint::Htv145CommandResponse htv145Response{};
    const auto htv145OpenResponse = fromHex(
        "79f4882f28b9840280b42d008f9750868010cf92800000409e00569e000000000000000044ce"
    );
    assert(rainpoint::decodeHtv145CommandResponse(
        htv145OpenResponse, htv145Link, htv145Response
    ));
    assert(htv145Response.sequence == 0x97);
    assert(htv145Response.watering);

    // The retained selector-6 association reverses the command-family high
    // marker while preserving byte 2 as the action and offset 18 as the
    // response state. Its five- and fifteen-minute fields also cross the
    // formerly untested low-byte-bit-7 boundary.
    assert(rainpoint::buildHtv145OpenFrame(
        htv145Link, 0x81, 300, 0xc713, htv145Frame, true
    ));
    assert(htv145Frame == fromHex(
        "79f4882f28b42d008fb984028081908280810096008000000000000000000000000000002fde"
    ));
    const auto htv145Selector6OpenResponse = fromHex(
        "79f4882f28b9840280b42d008f81d0868010cf80000000409600d69600800000000000004208"
    );
    assert(rainpoint::decodeHtv145CommandResponse(
        htv145Selector6OpenResponse, htv145Link, htv145Response
    ));
    assert(htv145Response.sequence == 0x81);
    assert(htv145Response.watering);
    assert(rainpoint::buildHtv145OpenFrame(
        htv145Link, 0x82, 900, 0xc713, htv145Frame, true
    ));
    assert(htv145Frame == fromHex(
        "79f4882f28b42d008fb9840280829082808100c2018000000000000000000000000000000d6a"
    ));
    assert(rainpoint::buildHtv145CloseFrame(
        htv145Link, 0x83, 0x4f03, htv145Frame, true
    ));
    assert(htv145Frame == fromHex(
        "79f4882f28b42d008fb984028083108180810000000000000000000000000000000000006121"
    ));
    const auto htv145Selector6CloseResponse = fromHex(
        "79f4882f28b9840280b42d008f83508680104f8000000040800056c2018000000000000052c5"
    );
    assert(rainpoint::decodeHtv145CommandResponse(
        htv145Selector6CloseResponse, htv145Link, htv145Response
    ));
    assert(htv145Response.sequence == 0x83);
    assert(!htv145Response.watering);

    bool htv145Watering = false;
    const auto htv145ActiveState = fromHex(
        "79f4882f28b9840280b42d008f9b810785898090cf9981800040a90156ac0100000000003431"
    );
    assert(rainpoint::decodeHtv145StateReport(
        htv145ActiveState, htv145Link, htv145Watering
    ));
    assert(htv145Watering);
    // The state report's 0x9b is a separate telemetry counter and must never
    // be mistaken for the response to an outbound 0x8c command.
    assert(htv145ActiveState[13] != 0x8c);
    return 0;
}
