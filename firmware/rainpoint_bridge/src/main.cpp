#include <Arduino.h>
#include <SPI.h>
#include <esp_system.h>

#include <array>
#include <cctype>
#include <cstdint>

#include "cc1101.h"
#include "rainpoint_ack.h"
#if RAINPOINT_HTV145_TX_CANDIDATE == 1
#include "rainpoint_htv145_control.h"
#endif
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
#include "rainpoint_htv145_pairing.h"
#endif
#include "rainpoint_pairing.h"
#include "rainpoint_protocol.h"
#include "rainpoint_rf_maintenance.h"
#include "rainpoint_valve_control.h"
#include "rainpoint_valve_pairing.h"
#include "wifi_transport.h"
#if RAINPOINT_OTA_CANDIDATE == 1
#include "ota_trial.h"
#endif

#if RAINPOINT_RADIO_COUNT != 1 && RAINPOINT_RADIO_COUNT != 2
#error "RAINPOINT_RADIO_COUNT must be 1 or 2"
#endif

#if RAINPOINT_RESEARCH_BENCH != 0 && RAINPOINT_RESEARCH_BENCH != 1
#error "RAINPOINT_RESEARCH_BENCH must be 0 or 1"
#endif

#if RAINPOINT_SUPERVISED_HTV405_CONTROL != 0 && RAINPOINT_SUPERVISED_HTV405_CONTROL != 1
#error "RAINPOINT_SUPERVISED_HTV405_CONTROL must be 0 or 1"
#endif

#if RAINPOINT_SENSOR_A_CANDIDATE != 0 && RAINPOINT_SENSOR_A_CANDIDATE != 1
#error "RAINPOINT_SENSOR_A_CANDIDATE must be 0 or 1"
#endif

#if RAINPOINT_PAIRING_GENERALIZATION != 0 && RAINPOINT_PAIRING_GENERALIZATION != 1
#error "RAINPOINT_PAIRING_GENERALIZATION must be 0 or 1"
#endif

#if RAINPOINT_ROUTINE_ACK_CANDIDATE != 0 && RAINPOINT_ROUTINE_ACK_CANDIDATE != 1
#error "RAINPOINT_ROUTINE_ACK_CANDIDATE must be 0 or 1"
#endif

#if RAINPOINT_OTA_CANDIDATE != 0 && RAINPOINT_OTA_CANDIDATE != 1
#error "RAINPOINT_OTA_CANDIDATE must be 0 or 1"
#endif

#if RAINPOINT_VALVE_PAIRING_CANDIDATE != 0 && RAINPOINT_VALVE_PAIRING_CANDIDATE != 1
#error "RAINPOINT_VALVE_PAIRING_CANDIDATE must be 0 or 1"
#endif

#if RAINPOINT_HTV145_TX_CANDIDATE != 0 && RAINPOINT_HTV145_TX_CANDIDATE != 1
#error "RAINPOINT_HTV145_TX_CANDIDATE must be 0 or 1"
#endif

#if RAINPOINT_HTV145_TX_CANDIDATE == 1 && RAINPOINT_RESEARCH_BENCH != 1
#error "HTV145 transmit candidate requires the research-bench build"
#endif

#if RAINPOINT_HTV145_PAIRING_CANDIDATE != 0 && RAINPOINT_HTV145_PAIRING_CANDIDATE != 1
#error "RAINPOINT_HTV145_PAIRING_CANDIDATE must be 0 or 1"
#endif

#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1 && RAINPOINT_RESEARCH_BENCH != 1
#error "HTV145 pairing candidate requires the research-bench build"
#endif

#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1 && RAINPOINT_VALVE_PAIRING_CANDIDATE != 1
#error "HTV145 pairing candidate requires valve pairing support"
#endif

#if RAINPOINT_HTV145_POST_FRAME_TAIL_CANDIDATE != 0 && RAINPOINT_HTV145_POST_FRAME_TAIL_CANDIDATE != 1
#error "RAINPOINT_HTV145_POST_FRAME_TAIL_CANDIDATE must be 0 or 1"
#endif

#if RAINPOINT_HTV145_POST_FRAME_TAIL_CANDIDATE == 1 && (RAINPOINT_RESEARCH_BENCH != 1 || RAINPOINT_HTV145_PAIRING_CANDIDATE != 1)
#error "HTV145 post-frame tail candidate requires the research pairing build"
#endif

#if RAINPOINT_ROUTINE_ACK_CANDIDATE == 1 && RAINPOINT_PAIRING_GENERALIZATION != 1
#error "Routine acknowledgement trials require generalized pairing"
#endif

#if RAINPOINT_SENSOR_A_CANDIDATE == 1 && RAINPOINT_PAIRING_GENERALIZATION == 1
#error "Select only one experimental pairing firmware mode"
#endif

#ifndef RAINPOINT_STATUS_LED_PIN
#error "RAINPOINT_STATUS_LED_PIN must identify the board status LED"
#endif

namespace {

constexpr int kSpiSckPin = 18;
constexpr int kSpiMisoPin = 19;
constexpr int kSpiMosiPin = 23;
constexpr int kPrimaryChipSelectPin = 27;
constexpr int kDiagnosticChipSelectPin = 14;
constexpr int kPrimaryDataPin = 26;
constexpr int kDiagnosticDataPin = 33;
constexpr std::uint32_t kScanDwellMs = 500;
constexpr std::uint8_t kHcs026TelemetryChannel = 0;
constexpr std::uint32_t kHealthIntervalMs = 30'000;
constexpr std::uint32_t kIdentifyToggleMs = 250;
#if RAINPOINT_SUPERVISED_HTV405_CONTROL == 1
// Supervised HTV405 control. This association-normalized selector-2 base
// plus the node's pairing calibration (97,154 Hz on the validated bench node)
// requests 433,518,527 Hz and lands on the accepted ~433.471 MHz carrier.
// The actual gateway-to-valve command precedes the lower-channel valve state
// report and uses the established late selector-2 reply branch. The prior
// probe mistakenly replayed the lower-channel state report itself.
constexpr std::uint32_t kHtv405ControlBaseCenterHz = 433'421'373;
constexpr std::uint32_t kValveProbeFreshPhaseMs = 90'000;
constexpr std::uint32_t kValveProbeMinimumCloseDelayMs = 15'000;
// Both captured stock control commands (open and close) place their sync word
// after the long ~2,400-symbol wake. The prior 320-symbol probe reproduced an
// ordinary acknowledgement, not a gateway command, and produced no valve
// state response even with the correct live transaction phase.
constexpr std::uint16_t kValveProbeWakeSymbols = 2'400;
// Every captured HTV405 control command is accepted under one of the two
// ordinary CRC families. The exact selector-2 Zone 1 / 120-second stock command
// reproduced by this probe uses 0x4f03; live link reports show that their own
// family is not a reliable predictor for the following controller command.
constexpr std::uint16_t kValveProbeTrailerResidual = 0x4f03;
constexpr std::uint8_t kValveProbePowerDbm = 10;
// The valve confirms a command on the control carrier, not its lower idle-
// report carrier. A single long-wake frame proved vulnerable to an occasional
// complete RF miss in the installed garden. Repeat the identical idempotent
// frame twice unless a valve response arrives first, matching the bounded
// retry shape already validated by the single-zone protocol without changing
// the reserved counter or requested duration.
constexpr std::array<std::uint32_t, 2> kValveProbeRetryDelayMs{{650, 1'450}};
constexpr std::uint32_t kValveProbeResponseListenMs = 3'000;
// Bounded span covering both the selector-6 and selector-2 gateway carriers.
// Pairing calibration remains independently bounded.
constexpr std::int32_t kValveProbeMaxFrequencyOffsetHz = 1'500'000;
#endif

SPIClass radioSpi(VSPI);
rainpoint::Cc1101 primaryRadio(
    radioSpi,
    kPrimaryChipSelectPin,
    kSpiMisoPin,
    kPrimaryDataPin
);
rainpoint::WifiTransport wifiTransport;
#if RAINPOINT_OTA_CANDIDATE == 1
rainpoint::OtaTrial otaTrial;
bool radiosHealthy = false;
#endif
#if RAINPOINT_RADIO_COUNT == 2
rainpoint::Cc1101 diagnosticRadio(
    radioSpi,
    kDiagnosticChipSelectPin,
    kSpiMisoPin,
    kDiagnosticDataPin
);
#endif
rainpoint::PairingProfile activePairingProfile =
#if RAINPOINT_SENSOR_A_CANDIDATE == 1
    rainpoint::kSensorAHcs026CandidateProfile;
#else
    rainpoint::kValidatedHcs026Profile;
#endif
rainpoint::PairingSession pairingSession(activePairingProfile);
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
rainpoint::Htv405PairingProfile activeValvePairingProfile{};
rainpoint::Htv405PairingSession valvePairingSession(activeValvePairingProfile);
bool valvePairingActive = false;
bool valvePairingKnownRejoin = false;
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
rainpoint::htv145::PairingProfile activeHtv145PairingProfile{};
rainpoint::htv145::PairingSession htv145PairingSession(
    activeHtv145PairingProfile
);
bool valvePairingHtv145 = false;
#endif
#endif
std::uint8_t pairingAssignedChannel = rainpoint::pairingChannelFromReply(
    activePairingProfile.steps[0].frame
);
rainpoint::PairingSessionState reportedPairingState =
    rainpoint::PairingSessionState::Disarmed;
bool pairingInvert = false;
std::int32_t pairingFrequencyOffsetHz = 0;
std::int8_t pairingPowerDbm = 0;
rainpoint::PairingLocalDateTime pairingLocalDateTime{};
bool pairingLocalDateTimeSet = false;
std::uint32_t pairingLocalDateTimeSetAtMs = 0;
bool pairingRequiresNetwork = false;
bool pairingAutomaticDiscovery = false;
bool pairingFactoryAdopted = false;
String pairingCommandId;
#if RAINPOINT_ROUTINE_ACK_CANDIDATE == 1
rainpoint::RoutineAckAuthorizations routineAckAuthorizations;
rainpoint::Htv405RoutineAckAuthorizations htv405RoutineAckAuthorizations;
std::uint32_t routineAckTransmissions = 0;
std::uint32_t routineAckFailures = 0;
std::uint32_t htv405RoutineAckTransmissions = 0;
std::uint32_t htv405RoutineAckFailures = 0;
std::uint32_t sensorRecoveryTransmissions = 0;
std::uint32_t sensorRecoveryFailures = 0;
std::uint32_t sensorRecoveryCompletions = 0;
void reportRoutineAckStatus(
    const char* state,
    const rainpoint::RoutineAckAuthorization& authorization,
    const std::array<std::uint8_t, rainpoint::kFrameBytes>* frame = nullptr
);
void reportSensorRecoveryStatus(
    const char* state,
    rainpoint::PairingTrigger trigger,
    const rainpoint::RoutineAckAuthorization& authorization,
    const std::array<std::uint8_t, rainpoint::kFrameBytes>* frame = nullptr
);
void reportHtv405RoutineAckStatus(
    const char* state,
    const rainpoint::Htv405RoutineAckAuthorization& authorization,
    const std::array<std::uint8_t, rainpoint::kFrameBytes>* frame = nullptr
);
#endif
std::uint32_t lastHealthReport = 0;
std::uint32_t lastLoopAt = 0;
std::uint32_t maximumLoopGapMs = 0;
String serialCommand;
String identifyCommandId;
std::uint32_t identifyUntilMs = 0;
std::uint32_t lastIdentifyToggleMs = 0;
bool identifyLedOn = false;
rainpoint::RfMaintenanceState rfMaintenance;
String rfMaintenanceCommandId;
std::uint32_t rfRejectedCommandCount = 0;
bool nodeRestartPending = false;

#if RAINPOINT_SUPERVISED_HTV405_CONTROL == 1
struct ValveControlProbe {
    rainpoint::Htv405ValveLink link{};
    rainpoint::Htv405GatewayControlLink gatewayControlLink{};
    rainpoint::Htv405Phase nextPhase{};
    rainpoint::Htv405Phase currentReportPhase{};
    std::uint8_t commandSequence = 0;
    bool commandRepeat = false;
    std::int32_t frequencyOffsetHz = 0;
    std::uint8_t selector = 0x05;
    std::uint8_t commandZone = 1;
    std::uint8_t transmittedZone = 0;
    std::uint8_t confirmedActiveZone = 0;
    std::uint8_t lastReportedActiveZone = 0;
    std::uint16_t latestReportTrailerResidual = 0;
    std::uint16_t openDurationSeconds = 60;
    std::uint32_t phaseObservedAtMs = 0;
    std::uint32_t openSentAtMs = 0;
    std::uint32_t commandBurstStartedAtMs = 0;
    rainpoint::Htv405Phase transmittedPhase{};
    std::array<std::uint8_t, rainpoint::kFrameBytes> commandFrame{};
    std::uint8_t commandAttemptsSent = 0;
    bool configured = false;
    bool phaseValid = false;
    bool manualPhaseConfigured = false;
    bool commandCounterAuthenticated = false;
    bool commandPendingConfirmation = false;
    bool confirmedStateValid = false;
    bool confirmedWatering = false;
    std::uint8_t lastConfirmedSequence = 0;
    bool ackQueued = false;
    bool ackSent = false;
    bool openQueued = false;
    bool closeQueued = false;
    bool openSent = false;
    bool closeSent = false;
    bool responseListenActive = false;
    std::uint32_t responseListenUntilMs = 0;
    String commandId;
};

ValveControlProbe valveControlProbe;
#endif

#if RAINPOINT_HTV145_TX_CANDIDATE == 1
struct Htv145ControlCandidate {
    rainpoint::Htv145Link link{};
    std::array<std::uint8_t, rainpoint::kFrameBytes> commandFrame{};
    String commandId;
    std::uint32_t centerHz = 0;
    std::uint32_t durationSeconds = 0;
    std::uint32_t burstStartedAtMs = 0;
    std::uint32_t nextAttemptAtMs = 0;
    std::uint32_t immediateResponseDeadlineMs = 0;
    std::uint32_t stateConfirmationDeadlineMs = 0;
    std::uint16_t trailerResidual = 0;
    std::int8_t powerDbm = 0;
    std::uint8_t nextSequence = 0;
    std::uint8_t transmittedSequence = 0;
    std::uint8_t attemptsSent = 0;
    std::uint8_t successfulAttempts = 0;
    std::uint16_t observedFrames = 0;
    std::uint16_t matchingRouteFrames = 0;
    std::uint16_t invalidTrailerFrames = 0;
    std::uint16_t classifiedResponseFrames = 0;
    std::uint16_t classifiedStateFrames = 0;
    std::uint16_t conflictingStateFrames = 0;
    bool invert = false;
    bool configured = false;
    bool counterAuthenticated = false;
    bool pending = false;
    bool commandWatering = false;
    bool listeningOnCommandCarrier = false;
    bool immediateResponseWindowClosed = false;
};

Htv145ControlCandidate htv145ControlCandidate;
#endif

#if RAINPOINT_RADIO_COUNT == 1
bool scanChannels = true;
std::uint32_t lastChannelChange = 0;
#endif

String hexString(const std::uint8_t* data, std::size_t length) {
    constexpr char digits[] = "0123456789abcdef";
    String result;
    result.reserve(length * 2);
    for (std::size_t index = 0; index < length; ++index) {
        result += digits[data[index] >> 4];
        result += digits[data[index] & 0x0f];
    }
    return result;
}

bool parseRawHexEndpoint(
    const String& value,
    std::array<std::uint8_t, 4>& endpoint
) {
    if (value.length() != endpoint.size() * 2) {
        return false;
    }
    for (std::size_t index = 0; index < endpoint.size(); ++index) {
        const auto nibble = [](char value) -> int {
            if (value >= '0' && value <= '9') {
                return value - '0';
            }
            if (value >= 'a' && value <= 'f') {
                return value - 'a' + 10;
            }
            if (value >= 'A' && value <= 'F') {
                return value - 'A' + 10;
            }
            return -1;
        };
        const int high = nibble(value[index * 2]);
        const int low = nibble(value[index * 2 + 1]);
        if (high < 0 || low < 0) {
            return false;
        }
        endpoint[index] = static_cast<std::uint8_t>((high << 4) | low);
    }
    return true;
}

bool parseHexEndpoint(
    const String& value,
    std::array<std::uint8_t, 4>& endpoint
) {
    if (!parseRawHexEndpoint(value, endpoint)) {
        return false;
    }
    return (endpoint[0] & 0x80U) != 0 && endpoint[3] == 0x24;
}

bool parseHexFactoryEndpoint(
    const String& value,
    std::array<std::uint8_t, 4>& endpoint
) {
    if (value.length() != endpoint.size() * 2) {
        return false;
    }
    String paired = value;
    const char highNibble = paired[0];
    if (highNibble < '0' || highNibble > '7') {
        return false;
    }
    const int associatedNibble = highNibble - '0' + 8;
    paired.setCharAt(
        0,
        static_cast<char>(
            associatedNibble < 10
                ? '0' + associatedNibble
                : 'a' + associatedNibble - 10
        )
    );
    if (!parseHexEndpoint(paired, endpoint)) {
        return false;
    }
    endpoint[0] &= 0x7fU;
    return true;
}

bool parseDecimalField(
    const String& value,
    std::size_t offset,
    std::size_t length,
    std::uint16_t& result
) {
    result = 0;
    for (std::size_t index = 0; index < length; ++index) {
        const char digit = value[offset + index];
        if (digit < '0' || digit > '9') {
            return false;
        }
        result = static_cast<std::uint16_t>(result * 10 + digit - '0');
    }
    return true;
}

bool parsePairingLocalDateTime(
    const String& value,
    rainpoint::PairingLocalDateTime& result
) {
    if (value.length() != 14) {
        return false;
    }
    std::uint16_t fields[6]{};
    const std::size_t offsets[] = {0, 4, 6, 8, 10, 12};
    const std::size_t lengths[] = {4, 2, 2, 2, 2, 2};
    for (std::size_t index = 0; index < 6; ++index) {
        if (!parseDecimalField(value, offsets[index], lengths[index], fields[index])) {
            return false;
        }
    }
    result = {
        fields[0],
        static_cast<std::uint8_t>(fields[1]),
        static_cast<std::uint8_t>(fields[2]),
        static_cast<std::uint8_t>(fields[3]),
        static_cast<std::uint8_t>(fields[4]),
        static_cast<std::uint8_t>(fields[5]),
    };
    return rainpoint::validPairingLocalDateTime(result);
}

String jsonStringField(const String& input, const char* key) {
    const String marker = String('"') + key + "\":\"";
    const int start = input.indexOf(marker);
    if (start < 0) {
        return String();
    }
    const int valueStart = start + marker.length();
    const int end = input.indexOf('"', valueStart);
    return end < 0 ? String() : input.substring(valueStart, end);
}

bool jsonLongField(const String& input, const char* key, long& result) {
    const String marker = String('"') + key + "\":";
    int position = input.indexOf(marker);
    if (position < 0) {
        return false;
    }
    position += marker.length();
    if (position >= static_cast<int>(input.length())) {
        return false;
    }
    bool negative = false;
    if (input[position] == '-') {
        negative = true;
        ++position;
    }
    if (position >= static_cast<int>(input.length()) ||
        !std::isdigit(static_cast<unsigned char>(input[position]))) {
        return false;
    }
    long value = 0;
    while (position < static_cast<int>(input.length()) &&
           std::isdigit(static_cast<unsigned char>(input[position]))) {
        value = value * 10 + input[position] - '0';
        ++position;
    }
    if (position >= static_cast<int>(input.length()) ||
        (input[position] != ',' && input[position] != '}')) {
        return false;
    }
    result = negative ? -value : value;
    return true;
}

bool jsonBoolField(const String& input, const char* key, bool& result) {
    const String marker = String('"') + key + "\":";
    const int position = input.indexOf(marker);
    if (position < 0) {
        return false;
    }
    const String value = input.substring(position + marker.length());
    if (value.startsWith("true") &&
        (value.length() == 4 || value[4] == ',' || value[4] == '}')) {
        result = true;
        return true;
    }
    if (value.startsWith("false") &&
        (value.length() == 5 || value[5] == ',' || value[5] == '}')) {
        result = false;
        return true;
    }
    return false;
}

bool validCommandId(const String& value) {
    if (value.length() != 32) {
        return false;
    }
    for (std::size_t index = 0; index < value.length(); ++index) {
        if (!std::isxdigit(static_cast<unsigned char>(value[index]))) {
            return false;
        }
    }
    return true;
}

void emitLine(const String& line) {
    Serial.println(line);
    wifiTransport.sendLine(line);
}

void printPacket(
    const char* radioName,
    const std::array<std::uint8_t, rainpoint::kFrameBytes>& frame,
    const rainpoint::RadioPacket& packet,
    const rainpoint::Cc1101& radio
) {
    const auto residual = rainpoint::trailerResidual(frame);
    char residualHex[5];
    std::snprintf(residualHex, sizeof(residualHex), "%04x", residual);
    String line;
    line.reserve(360);
    line += "{\"type\":\"rainpoint_rf\",\"node_id\":\"";
    line += wifiTransport.nodeId();
    line += "\",\"radio\":\"";
    line += radioName;
    line += "\",\"channel\":";
    line += radio.channel();
    line += ",\"rssi_dbm\":";
    line += String(packet.rssiTenthsDbm / 10.0f, 1);
    line += ",\"lqi\":";
    line += packet.lqi;
    line += ",\"frequency_offset_hz\":";
    line += packet.frequencyOffsetHz;
    line += ",\"sync_valid\":";
    line += rainpoint::hasSync(frame) ? "true" : "false";
    line += ",\"trailer_residual\":\"";
    line += residualHex;
    line += "\",\"trailer_valid\":";
    line += rainpoint::hasOrdinaryTrailer(frame) ? "true" : "false";
    line += ",\"frame\":\"";
    line += hexString(frame.data(), frame.size());
    line += "\"}";
    emitLine(line);
}

void printRadioHealth(const char* name, const rainpoint::Cc1101& radio) {
    char line[320];
    std::snprintf(
        line,
        sizeof(line),
        "{\"type\":\"radio_health\",\"node_id\":\"%s\","
        "\"radio\":\"%s\",\"channel\":%u,"
        "\"configuration_valid\":%s,\"packets\":%lu,\"overflows\":%lu,"
        "\"recoveries\":%lu}\n",
        wifiTransport.nodeId().c_str(),
        name,
        radio.channel(),
        radio.configurationValid() ? "true" : "false",
        static_cast<unsigned long>(radio.packetCount()),
        static_cast<unsigned long>(radio.overflowCount()),
        static_cast<unsigned long>(radio.recoveryCount())
    );
    String output(line);
    output.trim();
    emitLine(output);
}

void printNodeHealth() {
    char counter[32];
    String line;
    line.reserve(640);
    line += "{\"type\":\"node_health\",\"node_id\":\"";
    line += wifiTransport.nodeId();
    line += "\",\"uptime_seconds\":";
    line += millis() / 1'000;
    line += ",\"free_heap_bytes\":";
    line += ESP.getFreeHeap();
    line += ",\"minimum_free_heap_bytes\":";
    line += ESP.getMinFreeHeap();
    line += ",\"largest_free_block_bytes\":";
    line += ESP.getMaxAllocHeap();
    line += ",\"cpu_frequency_mhz\":";
    line += ESP.getCpuFreqMHz();
    line += ",\"device_temperature_c\":";
    line += String(temperatureRead(), 1);
    line += ",\"maximum_loop_gap_ms\":";
    line += maximumLoopGapMs;
    line += ",\"reset_reason_code\":";
    line += static_cast<int>(esp_reset_reason());
    line += ",\"ip_address\":\"";
    line += wifiTransport.localIp();
    line += "\",\"wifi_rssi_dbm\":";
    line += wifiTransport.wifiRssiDbm();
    line += ",\"network_bytes_sent\":";
    std::snprintf(
        counter,
        sizeof(counter),
        "%llu",
        static_cast<unsigned long long>(wifiTransport.networkBytesSent())
    );
    line += counter;
    line += ",\"network_bytes_received\":";
    std::snprintf(
        counter,
        sizeof(counter),
        "%llu",
        static_cast<unsigned long long>(wifiTransport.networkBytesReceived())
    );
    line += counter;
    line += ",\"wifi_reconnects\":";
    line += wifiTransport.wifiReconnects();
    line += ",\"gateway_connect_attempts\":";
    line += wifiTransport.gatewayConnectAttempts();
    line += ",\"gateway_authentications\":";
    line += wifiTransport.gatewayAuthentications();
    line += ",\"rf_mode\":\"";
    line += rfMaintenance.mode() == rainpoint::RfOperatingMode::ReceiveOnly
        ? "receive_only"
        : "normal";
    line += "\",\"rf_mode_remaining_seconds\":";
    line += rfMaintenance.remainingSeconds(millis());
    line += ",\"rf_mode_changed_uptime_ms\":";
    line += rfMaintenance.changedAtMs();
    line += ",\"rf_blocked_transmit_count\":";
    line += primaryRadio.blockedTransmitCount();
    line += ",\"rf_rejected_command_count\":";
    line += rfRejectedCommandCount;
    line += ",\"node_reboot_pending\":";
    line += nodeRestartPending ? "true" : "false";
#if RAINPOINT_ROUTINE_ACK_CANDIDATE == 1
    line += ",\"routine_ack_authorized_sensors\":";
    line += static_cast<unsigned int>(routineAckAuthorizations.activeCount());
    line += ",\"routine_ack_receive_channel\":";
    line += routineAckAuthorizations.activeCount() > 0
        ? kHcs026TelemetryChannel
        : primaryRadio.channel();
    line += ",\"routine_ack_transmissions\":";
    line += routineAckTransmissions;
    line += ",\"routine_ack_failures\":";
    line += routineAckFailures;
    line += ",\"htv405_routine_ack_authorized_valves\":";
    line += static_cast<unsigned int>(
        htv405RoutineAckAuthorizations.activeCount()
    );
    line += ",\"htv405_routine_ack_transmissions\":";
    line += htv405RoutineAckTransmissions;
    line += ",\"htv405_routine_ack_failures\":";
    line += htv405RoutineAckFailures;
    line += ",\"sensor_recovery_transmissions\":";
    line += sensorRecoveryTransmissions;
    line += ",\"sensor_recovery_failures\":";
    line += sensorRecoveryFailures;
    line += ",\"sensor_recovery_completions\":";
    line += sensorRecoveryCompletions;
#endif
    line += "}";
    emitLine(line);
    maximumLoopGapMs = 0;
}

void reportHealth() {
#if RAINPOINT_RADIO_COUNT == 1
    printRadioHealth("primary", primaryRadio);
#else
    printRadioHealth("primary", primaryRadio);
    printRadioHealth("diagnostic", diagnosticRadio);
#endif
    printNodeHealth();
#if RAINPOINT_OTA_CANDIDATE == 1
    emitLine(otaTrial.status(wifiTransport.nodeId()));
#endif
}

const char* pairingStateName(rainpoint::PairingSessionState state) {
    switch (state) {
        case rainpoint::PairingSessionState::Disarmed:
            return "disarmed";
        case rainpoint::PairingSessionState::Armed:
            return "armed";
        case rainpoint::PairingSessionState::Completed:
            return "completed";
        case rainpoint::PairingSessionState::Failed:
            return "failed";
    }
    return "unknown";
}

const char* pairingFailureReasonName(rainpoint::PairingFailureReason reason) {
    switch (reason) {
        case rainpoint::PairingFailureReason::None:
            return "none";
        case rainpoint::PairingFailureReason::SessionTimeout:
            return "session_timeout";
        case rainpoint::PairingFailureReason::TerminalConfirmationTimeout:
            return "terminal_confirmation_timeout";
        case rainpoint::PairingFailureReason::UnexpectedTrigger:
            return "unexpected_trigger";
        case rainpoint::PairingFailureReason::Stage0Rejected:
            return "stage_0_rejected";
        case rainpoint::PairingFailureReason::ReplyFailed:
            return "reply_failed";
        case rainpoint::PairingFailureReason::ReplyDeadlineMissed:
            return "reply_deadline_missed";
    }
    return "unknown";
}

rainpoint::PairingSessionState currentPairingState() {
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
    if (valvePairingActive) {
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
        if (valvePairingHtv145) {
            return htv145PairingSession.state();
        }
#endif
        return valvePairingSession.state();
    }
#endif
    return pairingSession.state();
}

std::size_t currentPairingCompletedSteps() {
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
    if (valvePairingActive) {
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
        if (valvePairingHtv145) {
            return htv145PairingSession.completedSteps();
        }
#endif
        return valvePairingSession.completedSteps();
    }
#endif
    return pairingSession.completedSteps();
}

rainpoint::PairingFailureReason currentPairingFailureReason() {
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
    if (valvePairingActive) {
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
        if (valvePairingHtv145) {
            return htv145PairingSession.failureReason();
        }
#endif
        return valvePairingSession.failureReason();
    }
#endif
    return pairingSession.failureReason();
}

void reportPairingStatus(const char* detail = nullptr) {
    String line;
    line.reserve(416);
    line += "{\"type\":\"pairing_tx_status\",\"node_id\":\"";
    line += wifiTransport.nodeId();
    line += "\",\"profile\":\"";
    line +=
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
        valvePairingActive ?
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
            (valvePairingHtv145 ? rainpoint::htv145::kProfileId :
                rainpoint::kAutomaticHtv405ProfileId) :
#else
            rainpoint::kAutomaticHtv405ProfileId :
#endif
#endif
        activePairingProfile.id;
    line += "\",\"factory_endpoint\":\"";
    if (!pairingAutomaticDiscovery || pairingFactoryAdopted) {
        line += hexString(
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
            valvePairingActive ?
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
                (valvePairingHtv145
                    ? activeHtv145PairingProfile.factoryEndpoint.data()
                    : activeValvePairingProfile.factoryEndpoint.data()) :
#else
                activeValvePairingProfile.factoryEndpoint.data() :
#endif
#endif
            activePairingProfile.factoryEndpoint.data(),
            4
        );
    }
    line += "\",\"paired_endpoint\":\"";
    if (!pairingAutomaticDiscovery || pairingFactoryAdopted) {
        line += hexString(
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
            valvePairingActive ?
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
                (valvePairingHtv145
                    ? activeHtv145PairingProfile.pairedEndpoint.data()
                    : activeValvePairingProfile.pairedEndpoint.data()) :
#else
                activeValvePairingProfile.pairedEndpoint.data() :
#endif
#endif
            activePairingProfile.pairedEndpoint.data(),
            4
        );
    }
    line += '"';
    if (!pairingCommandId.isEmpty()) {
        line += ",\"command_id\":\"";
        line += pairingCommandId;
        line += '"';
    }
    line += ",\"state\":\"";
    line += pairingStateName(currentPairingState());
    line += "\",\"completed_steps\":";
    line += currentPairingCompletedSteps();
    line += ",\"step_count\":";
    line +=
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
        valvePairingActive
            ?
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
                (valvePairingHtv145
                    ? activeHtv145PairingProfile.steps.size()
                    : activeValvePairingProfile.stepCount)
#else
                activeValvePairingProfile.stepCount
#endif
            :
#endif
        activePairingProfile.stepCount;
    line += ",\"assigned_channel\":";
    line += pairingAssignedChannel;
    line += ",\"automatic_discovery\":";
    line += pairingAutomaticDiscovery ? "true" : "false";
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
    line += ",\"retained_association_rejoin\":";
    line += valvePairingActive && valvePairingKnownRejoin ? "true" : "false";
    if (valvePairingActive) {
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
        if (valvePairingHtv145) {
            line += ",\"counter_offset\":0";
            line += ",\"counter_offset_known\":false";
            line += ",\"selector2_configuration_transmitted\":false";
            line += ",\"selector2_configuration_sequence\":0";
            line += ",\"reply_marker_repeat\":false";
            line += ",\"htv145_later_sweep_branch\":false";
            line += ",\"htv145_factory_sweep_observed\":";
            line += htv145PairingSession.factorySweepObserved()
                ? "true" : "false";
            line += ",\"htv145_last_factory_sweep_counter\":";
            line += static_cast<unsigned int>(
                htv145PairingSession.lastFactorySweepCounter()
            );
            line += ",\"htv145_assignment_locked\":";
            line += htv145PairingSession.assignmentLocked()
                ? "true" : "false";
            line += ",\"htv145_accepted_factory_counter\":";
            line += static_cast<unsigned int>(
                htv145PairingSession.acceptedFactoryCounter()
            );
            line += ",\"htv145_stage0_accepted\":";
            line += htv145PairingSession.stage0Accepted()
                ? "true" : "false";
            line += ",\"htv145_stage0_rejected\":";
            line += htv145PairingSession.stage0Rejected()
                ? "true" : "false";
        } else
#endif
        {
        line += ",\"counter_offset\":";
        line += static_cast<unsigned int>(
            valvePairingSession.counterOffset()
        );
        line += ",\"counter_offset_known\":";
        line += valvePairingSession.counterOffsetKnown() ? "true" : "false";
        line += ",\"selector2_configuration_transmitted\":";
        line += valvePairingSession.selector2ConfigurationTransmitted()
            ? "true" : "false";
        line += ",\"selector2_configuration_sequence\":";
        line += static_cast<unsigned int>(
            valvePairingSession.selector2ConfigurationSequence()
        );
        line += ",\"reply_marker_repeat\":";
        line += valvePairingSession.replyMarkerRepeat() ? "true" : "false";
        }
    }
#endif
    line += ",\"factory_adopted\":";
    line += pairingFactoryAdopted ? "true" : "false";
    line += ",\"awaiting_terminal_confirmation\":";
    line +=
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
        valvePairingActive ? "false" :
#endif
        (pairingSession.awaitingTerminalConfirmation() ? "true" : "false");
    line += ",\"terminal_trigger\":\"";
    line +=
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
        valvePairingActive ? "final_reply" :
#endif
        "paired_message_3";
    line += '"';
    line += ",\"failure_reason\":\"";
    line += pairingFailureReasonName(currentPairingFailureReason());
    line += '"';
    line += ",\"tx_armed\":";
    line += currentPairingState() == rainpoint::PairingSessionState::Armed
        ? "true"
        : "false";
    line += ",\"invert\":";
    line += pairingInvert ? "true" : "false";
    line += ",\"frequency_offset_hz\":";
    line += pairingFrequencyOffsetHz;
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
    if (valvePairingActive) {
        const std::uint32_t profileCenterHz =
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
            valvePairingHtv145
                ? activeHtv145PairingProfile.steps[0].channelCenterHz
                :
#endif
            activeValvePairingProfile.steps[0].channelCenterHz;
        line += ",\"profile_initial_center_hz\":";
        line += profileCenterHz;
        line += ",\"effective_initial_tx_center_hz\":";
        line += static_cast<std::int64_t>(profileCenterHz) +
            pairingFrequencyOffsetHz;
    }
#endif
    line += ",\"power_dbm\":";
    line += pairingPowerDbm;
    line += ",\"local_clock_set\":";
    line += pairingLocalDateTimeSet ? "true" : "false";
    if (detail != nullptr) {
        line += ",\"detail\":\"";
        line += detail;
        line += '"';
    }
    line += '}';
    emitLine(line);
    reportedPairingState = currentPairingState();
}

void restoreScanningAfterPairing() {
#if RAINPOINT_RADIO_COUNT == 1
    scanChannels = true;
    lastChannelChange = millis();
#endif
}

void cancelPairing(const char* detail) {
    pairingSession.cancel();
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
    valvePairingSession.cancel();
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
    htv145PairingSession.cancel();
#endif
#endif
    pairingRequiresNetwork = false;
    restoreScanningAfterPairing();
    reportPairingStatus(detail);
}

void setAllRadioTransmitEnabled(bool enabled) {
    primaryRadio.setTransmitEnabled(enabled);
#if RAINPOINT_RADIO_COUNT == 2
    diagnosticRadio.setTransmitEnabled(enabled);
#endif
}

const char* rfModeName() {
    return rfMaintenance.mode() == rainpoint::RfOperatingMode::ReceiveOnly
        ? "receive_only"
        : "normal";
}

void reportRfMaintenanceStatus(const char* detail) {
    String line = "{\"type\":\"rf_maintenance_status\",\"node_id\":\"";
    line += wifiTransport.nodeId();
    line += "\",\"command_id\":\"";
    line += rfMaintenanceCommandId;
    line += "\",\"requested_mode\":\"";
    line += rfModeName();
    line += "\",\"effective_mode\":\"";
    line += rfModeName();
    line += "\",\"remaining_seconds\":";
    line += rfMaintenance.remainingSeconds(millis());
    line += ",\"changed_uptime_ms\":";
    line += rfMaintenance.changedAtMs();
    line += ",\"blocked_transmit_count\":";
    line += primaryRadio.blockedTransmitCount();
    line += ",\"rejected_command_count\":";
    line += rfRejectedCommandCount;
    line += ",\"reboot_pending\":";
    line += nodeRestartPending ? "true" : "false";
    line += ",\"detail\":\"";
    line += detail;
    line += "\"}";
    emitLine(line);
}

bool rfCommandMayTransmit(const String& type) {
    if (type == "pairing_start" ||
        type == "routine_ack_configure" ||
        type == "htv405_routine_ack_configure" ||
        type == "firmware_update_start") {
        return true;
    }
#if RAINPOINT_SUPERVISED_HTV405_CONTROL == 1
    if (type == "valve_control_open" || type == "valve_control_close") {
        return true;
    }
#endif
#if RAINPOINT_HTV145_TX_CANDIDATE == 1
    if (
        type == "htv145_control_open" ||
        type == "htv145_control_close"
    ) {
        return true;
    }
#endif
    return false;
}

void enterRfReceiveOnly(
    const String& commandId,
    std::uint32_t durationSeconds
) {
    // Disable the physical transmit boundary before cancelling any workflow.
    setAllRadioTransmitEnabled(false);
    rfMaintenance.enterReceiveOnly(millis(), durationSeconds);
    rfMaintenanceCommandId = commandId;
    if (currentPairingState() == rainpoint::PairingSessionState::Armed) {
        cancelPairing("rf_receive_only");
    }
#if RAINPOINT_SUPERVISED_HTV405_CONTROL == 1
    valveControlProbe.ackQueued = false;
    valveControlProbe.openQueued = false;
    valveControlProbe.closeQueued = false;
    valveControlProbe.commandPendingConfirmation = false;
    valveControlProbe.responseListenActive = false;
#endif
#if RAINPOINT_HTV145_TX_CANDIDATE == 1
    if (htv145ControlCandidate.pending) {
        htv145ControlCandidate.pending = false;
        htv145ControlCandidate.counterAuthenticated = false;
        htv145ControlCandidate.commandId.clear();
    }
#endif
    primaryRadio.restoreReceiveChannel(kHcs026TelemetryChannel);
    reportRfMaintenanceStatus("receive_only_started");
}

void resumeRfNormal(const String& commandId, const char* detail) {
    rfMaintenance.resumeNormal(millis());
    setAllRadioTransmitEnabled(true);
    rfMaintenanceCommandId = commandId;
    reportRfMaintenanceStatus(detail);
}

void pollRfMaintenance() {
    if (!rfMaintenance.tick(millis())) {
        return;
    }
    setAllRadioTransmitEnabled(true);
    rfMaintenanceCommandId.clear();
    reportRfMaintenanceStatus("receive_only_expired");
}

#if RAINPOINT_RESEARCH_BENCH == 1
bool handlePairingProbe(const String& command) {
    for (std::size_t index = 0;
         index < activePairingProfile.stepCount;
         ++index) {
        const String expected = String("pairing_probe_b ") + (index + 1) +
            " 15a98024";
        if (command != expected) {
            continue;
        }
        if (pairingSession.state() == rainpoint::PairingSessionState::Armed) {
            emitLine(
                "{\"type\":\"command_error\","
                "\"error\":\"pairing_is_armed\"}"
            );
            return true;
        }
        const auto& step = activePairingProfile.steps[index];
        const std::int64_t adjustedFrequency =
            static_cast<std::int64_t>(step.channelCenterHz) +
            pairingFrequencyOffsetHz;
        const bool sent = primaryRadio.transmitAsync(
            step.frame,
            static_cast<std::uint32_t>(adjustedFrequency),
            step.wakeSymbols,
            pairingInvert,
            rainpoint::pairingPaTableValue(pairingPowerDbm)
        );
        String line =
            "{\"type\":\"pairing_tx_probe\",\"profile\":\"";
        line += activePairingProfile.id;
        line += "\","
            "\"step\":";
        line += index + 1;
        line += ",\"channel_center_hz\":";
        line += static_cast<long>(adjustedFrequency);
        line += ",\"success\":";
        line += sent ? "true" : "false";
        line += '}';
        emitLine(line);
        return true;
    }
    return false;
}
#endif

#if RAINPOINT_RADIO_COUNT == 1
void selectChannel(std::uint8_t channel) {
    if (primaryRadio.setChannel(channel)) {
        lastChannelChange = millis();
        emitLine(
            String("{\"type\":\"radio_channel\",\"node_id\":\"") +
            wifiTransport.nodeId() + "\",\"channel\":" + channel + "}"
        );
    }
}
#endif

#if RAINPOINT_SUPERVISED_HTV405_CONTROL == 1
bool parseSignedLongValue(const String& value, long& result) {
    if (value.isEmpty() || value.length() > 11) {
        return false;
    }
    std::size_t index = 0;
    if (value[0] == '-' || value[0] == '+') {
        index = 1;
    }
    if (index == value.length()) {
        return false;
    }
    for (; index < value.length(); ++index) {
        if (!std::isdigit(static_cast<unsigned char>(value[index]))) {
            return false;
        }
    }
    result = value.toInt();
    return true;
}

std::uint32_t valveProbeCenterHz() {
    return static_cast<std::uint32_t>(
        static_cast<std::int64_t>(kHtv405ControlBaseCenterHz) +
        valveControlProbe.frequencyOffsetHz
    );
}

bool valveProbeHasFreshPhase(std::uint32_t now) {
    return valveControlProbe.phaseValid &&
        now - valveControlProbe.phaseObservedAtMs <= kValveProbeFreshPhaseMs;
}

bool valveProbeMatchesLink(
    const std::array<std::uint8_t, rainpoint::kFrameBytes>& frame
) {
    if (!valveControlProbe.configured) {
        return false;
    }
    for (std::size_t index = 0; index < 4; ++index) {
        if (frame[5 + index] !=
                valveControlProbe.link.controllerEndpoint[index] ||
            frame[9 + index] != valveControlProbe.link.valveEndpoint[index]) {
            return false;
        }
    }
    return true;
}

void reportValveProbeStatus(
    const char* state,
    const std::array<std::uint8_t, rainpoint::kFrameBytes>* frame = nullptr
) {
    const std::uint32_t now = millis();
    String line;
    line.reserve(560);
    line += "{\"type\":\"valve_control_probe\",\"node_id\":\"";
    line += wifiTransport.nodeId();
    line += "\",\"state\":\"";
    line += state;
    if (validCommandId(valveControlProbe.commandId)) {
        line += "\",\"command_id\":\"";
        line += valveControlProbe.commandId;
    }
    line += "\",\"configured\":";
    line += valveControlProbe.configured ? "true" : "false";
    if (valveControlProbe.configured) {
        line += ",\"controller_endpoint\":\"";
        line += hexString(
            valveControlProbe.link.controllerEndpoint.data(), 4
        );
        line += "\",\"valve_endpoint\":\"";
        line += hexString(valveControlProbe.link.valveEndpoint.data(), 4);
        line += "\",\"companion_endpoint\":\"";
        line += hexString(
            valveControlProbe.gatewayControlLink.companionEndpoint.data(), 4
        );
        line += "\",\"selector\":";
        line += valveControlProbe.selector;
        line += ",\"center_hz\":";
        line += static_cast<unsigned long>(valveProbeCenterHz());
        line += ",\"command_zone\":";
        line += valveControlProbe.commandZone;
    }
    line += ",\"command_phase_source\":\"";
    line += valveControlProbe.commandCounterAuthenticated
        ? "authenticated_valve_response"
        : (valveControlProbe.manualPhaseConfigured ? "manual_bench" : "none");
    line += '"';
    if (valveControlProbe.manualPhaseConfigured) {
        line += ",\"command_sequence\":";
        line += valveControlProbe.commandSequence;
        line += ",\"command_repeat\":";
        line += valveControlProbe.commandRepeat ? "true" : "false";
    }
    line += ",\"command_counter_valid\":";
    line += valveControlProbe.manualPhaseConfigured ? "true" : "false";
    line += ",\"phase_valid\":";
    line += valveControlProbe.phaseValid ? "true" : "false";
    line += ",\"phase_fresh\":";
    line += valveProbeHasFreshPhase(now) ? "true" : "false";
    line += ",\"command_pending_confirmation\":";
    line += valveControlProbe.commandPendingConfirmation ? "true" : "false";
    if (valveControlProbe.commandPendingConfirmation) {
        line += ",\"transmitted_sequence\":";
        line += valveControlProbe.transmittedPhase.sequence;
        line += ",\"transmitted_repeat\":";
        line += valveControlProbe.transmittedPhase.repeat ? "true" : "false";
        line += ",\"transmitted_zone\":";
        line += valveControlProbe.transmittedZone;
    }
    line += ",\"command_attempts_sent\":";
    line += valveControlProbe.commandAttemptsSent;
    line += ",\"confirmed_state_valid\":";
    line += valveControlProbe.confirmedStateValid ? "true" : "false";
    if (valveControlProbe.confirmedStateValid) {
        line += ",\"confirmed_watering\":";
        line += valveControlProbe.confirmedWatering ? "true" : "false";
        line += ",\"last_confirmed_sequence\":";
        line += valveControlProbe.lastConfirmedSequence;
        if (valveControlProbe.confirmedWatering) {
            line += ",\"confirmed_active_zone\":";
            line += valveControlProbe.confirmedActiveZone;
        }
    }
    if (valveControlProbe.lastReportedActiveZone != 0) {
        line += ",\"last_reported_active_zone\":";
        line += valveControlProbe.lastReportedActiveZone;
    }
    if (valveControlProbe.phaseObservedAtMs != 0) {
        line += ",\"phase_age_ms\":";
        line += now - valveControlProbe.phaseObservedAtMs;
        line += ",\"next_sequence\":";
        line += valveControlProbe.nextPhase.sequence;
        line += ",\"next_repeat\":";
        line += valveControlProbe.nextPhase.repeat ? "true" : "false";
        char residualHex[5];
        std::snprintf(
            residualHex,
            sizeof(residualHex),
            "%04x",
            valveControlProbe.latestReportTrailerResidual
        );
        line += ",\"latest_report_trailer_residual\":\"";
        line += residualHex;
        line += '"';
        line += ",\"command_trailer_residual\":\"4f03\"";
    }
    line += ",\"open_sent\":";
    line += valveControlProbe.openSent ? "true" : "false";
    line += ",\"open_queued\":";
    line += valveControlProbe.openQueued ? "true" : "false";
    line += ",\"close_sent\":";
    line += valveControlProbe.closeSent ? "true" : "false";
    line += ",\"close_queued\":";
    line += valveControlProbe.closeQueued ? "true" : "false";
    if (valveControlProbe.openSent) {
        line += ",\"open_age_ms\":";
        line += now - valveControlProbe.openSentAtMs;
        line += ",\"open_duration_seconds\":";
        line += valveControlProbe.openDurationSeconds;
    }
    if (frame != nullptr) {
        line += ",\"frame\":\"";
        line += hexString(frame->data(), frame->size());
        line += '"';
    }
    line += '}';
    emitLine(line);
}

void reportValveProbeError(const char* error) {
    String line = "{\"type\":\"command_error\",\"node_id\":\"";
    line += wifiTransport.nodeId();
    line += "\",\"command\":\"valve_control_probe\"";
    if (validCommandId(valveControlProbe.commandId)) {
        line += ",\"command_id\":\"";
        line += valveControlProbe.commandId;
        line += '"';
    }
    line += ",\"error\":\"";
    line += error;
    line += "\"}";
    emitLine(line);
}

bool transmitQueuedValveProbe(
    rainpoint::Cc1101& radio,
    std::uint32_t startAtMicros
) {
    if (!valveControlProbe.ackQueued && !valveControlProbe.openQueued &&
        !valveControlProbe.closeQueued) {
        return false;
    }

    std::array<std::uint8_t, rainpoint::kFrameBytes> frame{};
    const bool acknowledging = valveControlProbe.ackQueued;
    const bool opening = valveControlProbe.openQueued;
    const rainpoint::Htv405Phase commandPhase{
        valveControlProbe.commandSequence,
        valveControlProbe.commandRepeat,
    };
    const bool built = acknowledging
        ? rainpoint::buildHtv405GatewayLinkAckFrame(
            valveControlProbe.gatewayControlLink,
            valveControlProbe.currentReportPhase,
            0xc713,
            frame
        )
        : opening
        ? rainpoint::buildHtv405GatewayOpenFrame(
            valveControlProbe.gatewayControlLink,
            commandPhase,
            valveControlProbe.commandZone,
            valveControlProbe.selector,
            valveControlProbe.openDurationSeconds,
            kValveProbeTrailerResidual,
            frame
        )
        : rainpoint::buildHtv405GatewayCloseFrame(
            valveControlProbe.gatewayControlLink,
            commandPhase,
            valveControlProbe.commandZone,
            valveControlProbe.selector,
            kValveProbeTrailerResidual,
            frame
        );
    const bool sent = built && radio.transmitAsync(
        frame,
        valveProbeCenterHz(),
        acknowledging ? 320 : kValveProbeWakeSymbols,
        false,
        rainpoint::pairingPaTableValue(kValveProbePowerDbm),
        rainpoint::kOrdinaryDeviationRegister,
        startAtMicros
    );
    valveControlProbe.ackQueued = false;
    valveControlProbe.openQueued = false;
    valveControlProbe.closeQueued = false;
    valveControlProbe.phaseValid = false;
    if (!sent) {
        reportValveProbeError(
            built ? "gateway_command_transmit_failed"
                  : "gateway_command_build_failed"
        );
        return true;
    }
    if (acknowledging) {
        valveControlProbe.ackSent = true;
        valveControlProbe.phaseValid = false;
        if (!radio.restoreReceiveChannel(kHcs026TelemetryChannel)) {
            reportValveProbeError("ordinary_receiver_restore_failed");
        }
        reportValveProbeStatus("gateway_link_ack_sent", &frame);
        return true;
    } else {
        valveControlProbe.commandFrame = frame;
        valveControlProbe.commandBurstStartedAtMs = millis();
        valveControlProbe.commandAttemptsSent = 1;
        valveControlProbe.responseListenActive =
            radio.setReceiveFrequency(valveProbeCenterHz());
        valveControlProbe.responseListenUntilMs =
            millis() + kValveProbeResponseListenMs;
        if (!valveControlProbe.responseListenActive) {
            reportValveProbeError("control_response_receiver_tune_failed");
        }
    }
    // A successful radio write only proves that the bridge transmitted. It
    // does not prove that the valve accepted the frame, so do not advance the
    // authoritative transaction phase here. The next received valve frame is
    // the only source allowed to move that state forward.
    valveControlProbe.transmittedPhase = commandPhase;
    valveControlProbe.transmittedZone = valveControlProbe.commandZone;
    valveControlProbe.commandPendingConfirmation = true;
    if (opening) {
        valveControlProbe.openSent = true;
        valveControlProbe.openSentAtMs = millis();
        reportValveProbeStatus(
            valveControlProbe.commandZone == 1
                ? "gateway_open_zone_1_sent"
                : "gateway_open_zone_candidate_sent",
            &frame
        );
    } else {
        valveControlProbe.closeSent = true;
        reportValveProbeStatus(
            valveControlProbe.commandZone == 1
                ? "gateway_close_zone_1_sent"
                : "gateway_close_zone_candidate_sent",
            &frame
        );
    }
    return true;
}

bool observeValveProbeFrame(
    const std::array<std::uint8_t, rainpoint::kFrameBytes>& frame,
    rainpoint::Cc1101& radio,
    std::uint32_t receivedAtMicros
) {
    if (!valveProbeMatchesLink(frame)) {
        return false;
    }

    rainpoint::Htv405GatewayCommandResponse response{};
    if (rainpoint::decodeHtv405GatewayCommandResponse(frame, response)) {
        if (!valveControlProbe.commandPendingConfirmation) {
            reportValveProbeStatus(
                "unsolicited_gateway_command_response_observed", &frame
            );
            return false;
        }
        if (response.sequence !=
                valveControlProbe.transmittedPhase.sequence) {
            reportValveProbeStatus(
                "gateway_command_response_sequence_mismatch", &frame
            );
            return false;
        }
        if (response.zone != valveControlProbe.transmittedZone) {
            reportValveProbeStatus(
                "gateway_command_response_zone_mismatch", &frame
            );
            return false;
        }

        valveControlProbe.commandPendingConfirmation = false;
        valveControlProbe.responseListenActive = false;
        valveControlProbe.commandSequence =
            rainpoint::nextHtv405GatewayCommandSequence(
                response.sequence, response.watering
            );
        valveControlProbe.commandRepeat = false;
        valveControlProbe.manualPhaseConfigured = true;
        valveControlProbe.commandCounterAuthenticated = true;
        valveControlProbe.confirmedStateValid = true;
        valveControlProbe.confirmedWatering = response.watering;
        valveControlProbe.confirmedActiveZone = response.watering
            ? valveControlProbe.transmittedZone
            : 0;
        valveControlProbe.lastConfirmedSequence = response.sequence;
        if (response.watering) {
            valveControlProbe.openSent = true;
            valveControlProbe.closeSent = false;
        } else {
            valveControlProbe.openSent = false;
            valveControlProbe.closeSent = true;
        }
        if (!radio.restoreReceiveChannel(kHcs026TelemetryChannel)) {
            reportValveProbeError("ordinary_receiver_restore_failed");
        }
        const bool zoneOne = valveControlProbe.transmittedZone == 1;
        reportValveProbeStatus(
            response.watering
                ? (zoneOne
                    ? "zone_1_open_confirmed"
                    : "zone_candidate_open_response_confirmed")
                : (zoneOne
                    ? "zone_1_closed_confirmed"
                    : "zone_candidate_closed_response_confirmed"),
            &frame
        );
        valveControlProbe.commandId.clear();
        return false;
    }

    rainpoint::Htv405GatewayCommandRejection rejection{};
    if (rainpoint::decodeHtv405GatewayCommandRejection(frame, rejection)) {
        if (!valveControlProbe.commandPendingConfirmation ||
            rejection.sequence !=
                valveControlProbe.transmittedPhase.sequence) {
            reportValveProbeStatus(
                "unsolicited_gateway_command_rejection_observed", &frame
            );
            return false;
        }
        // Keep the pending fields present in the report so the authenticated
        // gateway can match this rejection to the exact durable reservation.
        // The rejection proves the valve stayed idle but does not distinguish
        // a stale counter from an unsupported payload.
        reportValveProbeStatus("gateway_command_rejected", &frame);
        valveControlProbe.commandPendingConfirmation = false;
        valveControlProbe.responseListenActive = false;
        valveControlProbe.openSent = false;
        valveControlProbe.closeSent = false;
        if (!radio.restoreReceiveChannel(kHcs026TelemetryChannel)) {
            reportValveProbeError("ordinary_receiver_restore_failed");
        }
        valveControlProbe.commandId.clear();
        return false;
    }

    rainpoint::Htv405Phase nextPhase{};
    if (!rainpoint::nextHtv405Phase(frame, nextPhase)) {
        return false;
    }
    // Selector 0x05/0x85 is the state-bearing report family. Selector 0x07
    // remains useful for link phase, but its pair/odd-looking fields cycle and
    // must never overwrite an authenticated zone or watering state.
    rainpoint::Htv405StateReport state{};
    const bool stateReport = rainpoint::decodeHtv405StateReport(frame, state);
    const std::uint8_t reportedZone = stateReport ? state.zone : 0;
    const bool watering = stateReport && state.watering;
    valveControlProbe.nextPhase = nextPhase;
    valveControlProbe.currentReportPhase.sequence =
        static_cast<std::uint8_t>(frame[13] & 0x1fU);
    valveControlProbe.currentReportPhase.repeat =
        (frame[14] & 0x80U) != 0;
    valveControlProbe.latestReportTrailerResidual =
        rainpoint::trailerResidual(frame);
    valveControlProbe.phaseObservedAtMs = millis();
    valveControlProbe.phaseValid = true;
    if (stateReport) {
        valveControlProbe.confirmedStateValid = true;
        valveControlProbe.confirmedWatering = watering;
        if (watering && reportedZone >= 1 && reportedZone <= 4) {
            valveControlProbe.confirmedActiveZone = reportedZone;
            valveControlProbe.lastReportedActiveZone = reportedZone;
        } else if (!watering) {
            valveControlProbe.confirmedActiveZone = 0;
        }
    }
    if (valveControlProbe.commandPendingConfirmation) {
        reportValveProbeStatus(
            watering && reportedZone == valveControlProbe.transmittedZone
                ? "commanded_zone_open_state_reported"
                : "post_command_link_state_reported",
            &frame
        );
    }
    if (transmitQueuedValveProbe(
            radio,
            receivedAtMicros + rainpoint::kHtv405OrdinaryReplyStartDelayUs
        )) {
        return true;
    }
    reportValveProbeStatus(
        stateReport ? "link_state_report_observed" : "link_phase_report_observed",
        &frame
    );
    return false;
}

void pollValveProbeResponseListener() {
    if (!valveControlProbe.responseListenActive) {
        return;
    }
    const std::uint32_t now = millis();
    if (valveControlProbe.commandPendingConfirmation &&
        valveControlProbe.commandAttemptsSent >= 1 &&
        valveControlProbe.commandAttemptsSent <=
            kValveProbeRetryDelayMs.size()) {
        const std::size_t retryIndex =
            valveControlProbe.commandAttemptsSent - 1;
        if (now - valveControlProbe.commandBurstStartedAtMs >=
                kValveProbeRetryDelayMs[retryIndex]) {
            const bool sent = primaryRadio.transmitAsync(
                valveControlProbe.commandFrame,
                valveProbeCenterHz(),
                kValveProbeWakeSymbols,
                false,
                rainpoint::pairingPaTableValue(kValveProbePowerDbm),
                rainpoint::kOrdinaryDeviationRegister
            );
            ++valveControlProbe.commandAttemptsSent;
            const bool listening = sent && primaryRadio.setReceiveFrequency(
                valveProbeCenterHz()
            );
            if (!listening) {
                reportValveProbeError(
                    sent ? "control_response_receiver_tune_failed"
                         : "gateway_command_retry_transmit_failed"
                );
                valveControlProbe.commandPendingConfirmation = false;
                valveControlProbe.responseListenActive = false;
                valveControlProbe.openSent = false;
                valveControlProbe.closeSent = false;
                valveControlProbe.commandId.clear();
                primaryRadio.restoreReceiveChannel(kHcs026TelemetryChannel);
                return;
            }
            reportValveProbeStatus("gateway_command_retry_sent");
        }
    }
    if (static_cast<std::int32_t>(
            now - valveControlProbe.responseListenUntilMs
        ) < 0) {
        return;
    }
    valveControlProbe.responseListenActive = false;
    if (!primaryRadio.restoreReceiveChannel(kHcs026TelemetryChannel)) {
        reportValveProbeError("ordinary_receiver_restore_failed");
    }
    if (valveControlProbe.commandPendingConfirmation) {
        // Emit while the pending fields are still present so the gateway can
        // match and durably fail the exact reservation instead of leaving it
        // stuck forever after a missed response.
        reportValveProbeStatus("gateway_command_response_timeout");
        valveControlProbe.commandPendingConfirmation = false;
        valveControlProbe.openSent = false;
        valveControlProbe.closeSent = false;
        valveControlProbe.commandId.clear();
    }
}

bool configureValveProbe(const String& command) {
    constexpr std::size_t prefixLength = 19;
    const String fields = command.substring(prefixLength);
    const int firstSpace = fields.indexOf(' ');
    const int secondSpace = firstSpace < 0
        ? -1
        : fields.indexOf(' ', firstSpace + 1);
    const int thirdSpace = secondSpace < 0
        ? -1
        : fields.indexOf(' ', secondSpace + 1);
    const int fourthSpace = thirdSpace < 0
        ? -1
        : fields.indexOf(' ', thirdSpace + 1);
    if (firstSpace <= 0 || secondSpace <= firstSpace + 1 ||
        thirdSpace <= secondSpace + 1 || fourthSpace <= thirdSpace + 1 ||
        fields.indexOf(' ', fourthSpace + 1) >= 0) {
        reportValveProbeError("invalid_config_syntax");
        return true;
    }

    rainpoint::Htv405ValveLink link{};
    rainpoint::Htv405GatewayControlLink gatewayControlLink{};
    long selector = 0;
    long offset = 0;
    const bool parsedController = parseRawHexEndpoint(
        fields.substring(0, firstSpace), link.controllerEndpoint
    );
    const bool parsedValve = parseRawHexEndpoint(
        fields.substring(firstSpace + 1, secondSpace),
        link.valveEndpoint
    );
    const bool parsedCompanion = parseRawHexEndpoint(
        fields.substring(secondSpace + 1, thirdSpace),
        gatewayControlLink.companionEndpoint
    );
    const bool parsedSelector = parseSignedLongValue(
        fields.substring(thirdSpace + 1, fourthSpace), selector
    );
    const bool parsedOffset = parseSignedLongValue(
        fields.substring(fourthSpace + 1), offset
    );
    gatewayControlLink.pairedEndpoint = link.valveEndpoint;
    if (!parsedController || !parsedValve || !parsedCompanion ||
        !parsedSelector || !parsedOffset ||
        !rainpoint::validHtv405ValveLink(link) ||
        !rainpoint::validHtv405GatewayControlLink(gatewayControlLink) ||
        (selector != 5 && selector != 133) ||
        offset < -kValveProbeMaxFrequencyOffsetHz ||
        offset > kValveProbeMaxFrequencyOffsetHz) {
        reportValveProbeError("invalid_config_values");
        return true;
    }
    if (currentPairingState() == rainpoint::PairingSessionState::Armed) {
        reportValveProbeError("pairing_is_armed");
        return true;
    }

    const std::int64_t center =
        static_cast<std::int64_t>(kHtv405ControlBaseCenterHz) + offset;
    if (center < 433'000'000 || center > 435'000'000 ||
        !primaryRadio.prepareTransmit()) {
        reportValveProbeError("transmitter_prepare_failed");
        return true;
    }

    // Valve enrollment already caches the initial-assignment and routine-
    // reply carriers, which intentionally consumes the CC1101 driver's two
    // bounded calibration slots. A control carrier that is not cached remains
    // supported: transmitAsync() performs the normal on-demand synthesizer
    // calibration before entering TX. Treat the cache as an optimization, not
    // an authorization requirement, so a completed pairing cannot make the
    // separately gated control probe impossible to configure.
    primaryRadio.cacheTransmitFrequency(
        static_cast<std::uint32_t>(center)
    );

    valveControlProbe = ValveControlProbe{};
    valveControlProbe.link = link;
    valveControlProbe.gatewayControlLink = gatewayControlLink;
    valveControlProbe.selector = static_cast<std::uint8_t>(selector);
    valveControlProbe.frequencyOffsetHz = static_cast<std::int32_t>(offset);
    valveControlProbe.configured = true;
#if RAINPOINT_RADIO_COUNT == 1
    scanChannels = false;
    selectChannel(0);
#endif
    reportValveProbeStatus("configured_waiting_for_report");
    return true;
}

bool transmitValveProbeOpen(
    std::uint8_t zone,
    bool immediate,
    std::uint16_t durationSeconds
) {
    if (!valveControlProbe.configured) {
        reportValveProbeError("not_configured");
    } else if (zone < 1 || zone > 4) {
        reportValveProbeError("invalid_zone");
    } else if (currentPairingState() ==
            rainpoint::PairingSessionState::Armed) {
        reportValveProbeError("pairing_is_armed");
    } else if (valveControlProbe.commandPendingConfirmation) {
        reportValveProbeError("command_confirmation_pending");
    } else if (valveControlProbe.openSent &&
            valveControlProbe.confirmedWatering) {
        reportValveProbeError("open_already_sent");
    } else if (!valveControlProbe.manualPhaseConfigured) {
        reportValveProbeError("command_counter_unknown");
    } else if (valveControlProbe.openQueued ||
            valveControlProbe.closeQueued) {
        reportValveProbeError("command_already_queued");
    } else {
        valveControlProbe.commandZone = zone;
        valveControlProbe.openDurationSeconds = durationSeconds;
        valveControlProbe.openQueued = true;
        if (immediate) {
            transmitQueuedValveProbe(primaryRadio, 0);
        } else {
            reportValveProbeStatus("open_queued_waiting_for_link_report");
        }
    }
    return true;
}

bool transmitValveProbeAck() {
    if (!valveControlProbe.configured) {
        reportValveProbeError("not_configured");
    } else if (currentPairingState() ==
            rainpoint::PairingSessionState::Armed) {
        reportValveProbeError("pairing_is_armed");
    } else if (valveControlProbe.ackQueued ||
            valveControlProbe.openQueued ||
            valveControlProbe.closeQueued) {
        reportValveProbeError("command_already_queued");
    } else {
        valveControlProbe.ackQueued = true;
        reportValveProbeStatus("link_ack_queued_waiting_for_report");
    }
    return true;
}

bool transmitValveProbeClose(std::uint8_t zone, bool immediate) {
    const std::uint32_t now = millis();
    if (!valveControlProbe.configured) {
        reportValveProbeError("not_configured");
    } else if (zone < 1 || zone > 4) {
        reportValveProbeError("invalid_zone");
    } else if (currentPairingState() ==
            rainpoint::PairingSessionState::Armed) {
        reportValveProbeError("pairing_is_armed");
    } else if (valveControlProbe.commandPendingConfirmation) {
        reportValveProbeError("command_confirmation_pending");
    } else if (!valveControlProbe.manualPhaseConfigured) {
        reportValveProbeError("command_counter_unknown");
    } else if (valveControlProbe.openQueued ||
            valveControlProbe.closeQueued) {
        reportValveProbeError("command_already_queued");
    } else if (valveControlProbe.openSent &&
            now - valveControlProbe.openSentAtMs <
            kValveProbeMinimumCloseDelayMs) {
        reportValveProbeError("minimum_close_delay_not_elapsed");
    } else {
        valveControlProbe.commandZone = zone;
        valveControlProbe.closeQueued = true;
        if (immediate) {
            transmitQueuedValveProbe(primaryRadio, 0);
        } else {
            reportValveProbeStatus("close_queued_waiting_for_link_report");
        }
    }
    return true;
}

bool configureValveProbeCommandPhase(const String& command) {
    constexpr std::size_t prefixLength = 18;
    const String fields = command.substring(prefixLength);
    const int separator = fields.indexOf(' ');
    if (separator <= 0 || fields.indexOf(' ', separator + 1) >= 0) {
        reportValveProbeError("invalid_phase_syntax");
        return true;
    }

    long sequence = 0;
    long repeat = 0;
    if (!valveControlProbe.configured ||
        !parseSignedLongValue(fields.substring(0, separator), sequence) ||
        !parseSignedLongValue(fields.substring(separator + 1), repeat) ||
        sequence < 0 || sequence > 0x1f || (repeat != 0 && repeat != 1)) {
        reportValveProbeError("invalid_phase_values");
        return true;
    }

    // Bench-only explicit phase control allows a physical trial to continue
    // after a manual valve action without resetting its validated RF link.
    // Clearing queued/sent flags here is intentional; endpoints, selector,
    // carrier correction, and every pairing parameter remain unchanged.
    valveControlProbe.commandSequence = static_cast<std::uint8_t>(sequence);
    valveControlProbe.commandRepeat = repeat == 1;
    valveControlProbe.manualPhaseConfigured = true;
    valveControlProbe.commandCounterAuthenticated = false;
    valveControlProbe.openQueued = false;
    valveControlProbe.closeQueued = false;
    valveControlProbe.ackQueued = false;
    valveControlProbe.openSent = false;
    valveControlProbe.closeSent = false;
    valveControlProbe.commandPendingConfirmation = false;
    valveControlProbe.openSentAtMs = 0;
    reportValveProbeStatus("command_phase_configured");
    return true;
}

bool handleValveProbeCommand(const String& command) {
    if (command.startsWith("valve_probe_config ")) {
        return configureValveProbe(command);
    }
    if (command == "valve_probe_status") {
        reportValveProbeStatus("status");
        return true;
    }
    if (command == "valve_probe_ack_once") {
        return transmitValveProbeAck();
    }
    if (command == "valve_probe_open_1_60") {
        return transmitValveProbeOpen(1, false, 60);
    }
    if (command == "valve_probe_open_1_60_now") {
        return transmitValveProbeOpen(1, true, 60);
    }
    if (command == "valve_probe_open_1_120") {
        return transmitValveProbeOpen(1, false, 120);
    }
    if (command == "valve_probe_open_1_120_now") {
        return transmitValveProbeOpen(1, true, 120);
    }
    if (command == "valve_probe_open_2_60_now") {
        return transmitValveProbeOpen(2, true, 60);
    }
    if (command == "valve_probe_open_3_60_now") {
        return transmitValveProbeOpen(3, true, 60);
    }
    if (command == "valve_probe_open_4_60_now") {
        return transmitValveProbeOpen(4, true, 60);
    }
    if (command == "valve_probe_close_1") {
        return transmitValveProbeClose(1, false);
    }
    if (command == "valve_probe_close_1_now") {
        return transmitValveProbeClose(1, true);
    }
    if (command == "valve_probe_close_2_now") {
        return transmitValveProbeClose(2, true);
    }
    if (command == "valve_probe_close_3_now") {
        return transmitValveProbeClose(3, true);
    }
    if (command == "valve_probe_close_4_now") {
        return transmitValveProbeClose(4, true);
    }
    if (command.startsWith("valve_probe_phase ")) {
        return configureValveProbeCommandPhase(command);
    }
    return false;
}
#endif

#if RAINPOINT_HTV145_TX_CANDIDATE == 1
void reportHtv145CandidateStatus(
    const char* state,
    const char* confirmation = nullptr,
    const std::array<std::uint8_t, rainpoint::kFrameBytes>* frame = nullptr,
    const char* failureClass = nullptr
) {
    String line;
    line.reserve(900);
    line += "{\"type\":\"htv145_control_candidate\",\"node_id\":\"";
    line += wifiTransport.nodeId();
    line += "\",\"state\":\"";
    line += state;
    line += "\",\"configured\":";
    line += htv145ControlCandidate.configured ? "true" : "false";
    line += ",\"counter_authenticated\":";
    line += htv145ControlCandidate.counterAuthenticated ? "true" : "false";
    line += ",\"pending\":";
    line += htv145ControlCandidate.pending ? "true" : "false";
    if (htv145ControlCandidate.configured) {
        line += ",\"controller_endpoint\":\"";
        line += hexString(
            htv145ControlCandidate.link.controllerEndpoint.data(), 4
        );
        line += "\",\"valve_endpoint\":\"";
        line += hexString(
            htv145ControlCandidate.link.valveEndpoint.data(), 4
        );
        line += "\",\"center_hz\":";
        line += htv145ControlCandidate.centerHz;
        line += ",\"next_sequence\":";
        line += htv145ControlCandidate.nextSequence;
    }
    if (!htv145ControlCandidate.commandId.isEmpty()) {
        line += ",\"command_id\":\"";
        line += htv145ControlCandidate.commandId;
        line += '"';
    }
    if (!htv145ControlCandidate.commandId.isEmpty()) {
        line += ",\"transmitted_sequence\":";
        line += htv145ControlCandidate.transmittedSequence;
        line += ",\"attempts_started\":";
        line += htv145ControlCandidate.attemptsSent;
        line += ",\"attempts_sent\":";
        line += htv145ControlCandidate.successfulAttempts;
        line += ",\"observed_frames\":";
        line += htv145ControlCandidate.observedFrames;
        line += ",\"matching_route_frames\":";
        line += htv145ControlCandidate.matchingRouteFrames;
        line += ",\"invalid_trailer_frames\":";
        line += htv145ControlCandidate.invalidTrailerFrames;
        line += ",\"classified_response_frames\":";
        line += htv145ControlCandidate.classifiedResponseFrames;
        line += ",\"classified_state_frames\":";
        line += htv145ControlCandidate.classifiedStateFrames;
        line += ",\"conflicting_state_frames\":";
        line += htv145ControlCandidate.conflictingStateFrames;
        line += ",\"immediate_response_window_closed\":";
        line += htv145ControlCandidate.immediateResponseWindowClosed
            ? "true" : "false";
        line += ",\"immediate_response_outcome\":\"";
        if (htv145ControlCandidate.classifiedResponseFrames > 0) {
            line += "classified";
        } else if (htv145ControlCandidate.invalidTrailerFrames > 0 ||
            htv145ControlCandidate.matchingRouteFrames >
                htv145ControlCandidate.classifiedStateFrames) {
            line += "corrupt_or_foreign";
        } else {
            line += "none_observed";
        }
        line += "\",\"state_confirmation_outcome\":\"";
        if (htv145ControlCandidate.classifiedStateFrames >
                htv145ControlCandidate.conflictingStateFrames) {
            line += "matching";
        } else if (htv145ControlCandidate.conflictingStateFrames > 0) {
            line += "conflicting";
        } else if (!htv145ControlCandidate.pending &&
            htv145ControlCandidate.immediateResponseWindowClosed) {
            line += "missed";
        } else {
            line += "pending";
        }
        line += '"';
        line += ",\"requested_watering\":";
        line += htv145ControlCandidate.commandWatering ? "true" : "false";
        if (htv145ControlCandidate.commandWatering) {
            line += ",\"duration_seconds\":";
            line += htv145ControlCandidate.durationSeconds;
        }
    }
    if (confirmation != nullptr) {
        line += ",\"confirmation\":\"";
        line += confirmation;
        line += '"';
    }
    if (failureClass != nullptr) {
        line += ",\"failure_class\":\"";
        line += failureClass;
        line += "\",\"counter_ambiguous\":";
        line += htv145ControlCandidate.successfulAttempts > 0
            ? "true" : "false";
    }
    if (frame != nullptr) {
        line += ",\"frame\":\"";
        line += hexString(frame->data(), frame->size());
        line += '"';
    }
    line += '}';
    emitLine(line);
}

void restoreHtv145CandidateReceive() {
    htv145ControlCandidate.listeningOnCommandCarrier = false;
#if RAINPOINT_RADIO_COUNT == 1
    scanChannels = true;
    selectChannel(kHcs026TelemetryChannel);
#else
    primaryRadio.restoreReceiveChannel(kHcs026TelemetryChannel);
#endif
}

const char* htv145CandidateFailureClass(const char* state) {
    if (strcmp(state, "transmit_failed") == 0 &&
        htv145ControlCandidate.successfulAttempts == 0) {
        return "nothing_transmitted";
    }
    if (strcmp(state, "response_receiver_tune_failed") == 0) {
        return "transmitted_but_response_receiver_failed";
    }
    if (strcmp(state, "conflicting_command_response") == 0) {
        return "conflicting_authenticated_response";
    }
    if (strcmp(state, "gateway_connection_lost_counter_unsynchronized") == 0) {
        return htv145ControlCandidate.successfulAttempts > 0
            ? "gateway_lost_after_transmission"
            : "gateway_lost_before_transmission";
    }
    if (htv145ControlCandidate.invalidTrailerFrames > 0 ||
        htv145ControlCandidate.matchingRouteFrames >
            htv145ControlCandidate.classifiedResponseFrames +
            htv145ControlCandidate.classifiedStateFrames) {
        return "corrupt_or_foreign_matching_route_response";
    }
    if (htv145ControlCandidate.immediateResponseWindowClosed) {
        return "state_confirmation_missed_after_no_immediate_response";
    }
    return "transmitted_no_matching_response_or_state";
}

void failHtv145Candidate(const char* state) {
    // Once any attempt may have reached the air, failure to observe the valve
    // makes the outbound counter ambiguous. Fail closed and require a new
    // passive stock/local synchronization before accepting another command.
    htv145ControlCandidate.counterAuthenticated = false;
    htv145ControlCandidate.pending = false;
    reportHtv145CandidateStatus(
        state, nullptr, nullptr, htv145CandidateFailureClass(state)
    );
    restoreHtv145CandidateReceive();
    htv145ControlCandidate.commandId.clear();
}

void confirmHtv145Candidate(
    const char* confirmation,
    const std::array<std::uint8_t, rainpoint::kFrameBytes>& frame
) {
    htv145ControlCandidate.nextSequence =
        rainpoint::nextHtv145CommandSequence(
            htv145ControlCandidate.transmittedSequence
        );
    htv145ControlCandidate.counterAuthenticated = true;
    htv145ControlCandidate.pending = false;
    reportHtv145CandidateStatus("confirmed", confirmation, &frame);
    restoreHtv145CandidateReceive();
    htv145ControlCandidate.commandId.clear();
}

bool transmitNextHtv145CandidateAttempt() {
    if (!htv145ControlCandidate.pending ||
        htv145ControlCandidate.attemptsSent >=
            rainpoint::kHtv145CommandAttemptOffsetsMs.size()) {
        return false;
    }
    const bool sent = primaryRadio.transmitAsync(
        htv145ControlCandidate.commandFrame,
        htv145ControlCandidate.centerHz,
        rainpoint::kHtv145CommandWakeSymbols,
        htv145ControlCandidate.invert,
        rainpoint::pairingPaTableValue(
            htv145ControlCandidate.powerDbm
        )
    );
    ++htv145ControlCandidate.attemptsSent;
    if (sent) {
        ++htv145ControlCandidate.successfulAttempts;
    }
    if (!sent || !primaryRadio.setReceiveFrequency(
            htv145ControlCandidate.centerHz
        )) {
        failHtv145Candidate(
            sent ? "response_receiver_tune_failed" : "transmit_failed"
        );
        return false;
    }
    htv145ControlCandidate.listeningOnCommandCarrier = true;
    if (htv145ControlCandidate.attemptsSent <
            rainpoint::kHtv145CommandAttemptOffsetsMs.size()) {
        htv145ControlCandidate.nextAttemptAtMs =
            htv145ControlCandidate.burstStartedAtMs +
            rainpoint::kHtv145CommandAttemptOffsetsMs[
                htv145ControlCandidate.attemptsSent
            ];
    }
    reportHtv145CandidateStatus(
        "bounded_burst_attempt_sent", nullptr,
        &htv145ControlCandidate.commandFrame
    );
    return true;
}

bool startHtv145Candidate(
    const String& commandId,
    bool watering,
    std::uint32_t durationSeconds
) {
    if (!htv145ControlCandidate.configured ||
        !htv145ControlCandidate.counterAuthenticated ||
        htv145ControlCandidate.pending ||
        currentPairingState() == rainpoint::PairingSessionState::Armed) {
        return false;
    }
    std::array<std::uint8_t, rainpoint::kFrameBytes> frame{};
    const bool built = watering
        ? rainpoint::buildHtv145OpenFrame(
            htv145ControlCandidate.link,
            htv145ControlCandidate.nextSequence,
            durationSeconds,
            htv145ControlCandidate.trailerResidual,
            frame
        )
        : rainpoint::buildHtv145CloseFrame(
            htv145ControlCandidate.link,
            htv145ControlCandidate.nextSequence,
            htv145ControlCandidate.trailerResidual,
            frame
        );
    if (!built) {
        return false;
    }
    htv145ControlCandidate.commandFrame = frame;
    htv145ControlCandidate.commandId = commandId;
    htv145ControlCandidate.durationSeconds = durationSeconds;
    htv145ControlCandidate.transmittedSequence =
        htv145ControlCandidate.nextSequence;
    htv145ControlCandidate.commandWatering = watering;
    htv145ControlCandidate.attemptsSent = 0;
    htv145ControlCandidate.successfulAttempts = 0;
    htv145ControlCandidate.observedFrames = 0;
    htv145ControlCandidate.matchingRouteFrames = 0;
    htv145ControlCandidate.invalidTrailerFrames = 0;
    htv145ControlCandidate.classifiedResponseFrames = 0;
    htv145ControlCandidate.classifiedStateFrames = 0;
    htv145ControlCandidate.conflictingStateFrames = 0;
    htv145ControlCandidate.immediateResponseWindowClosed = false;
    htv145ControlCandidate.pending = true;
    htv145ControlCandidate.burstStartedAtMs = millis();
    htv145ControlCandidate.immediateResponseDeadlineMs =
        htv145ControlCandidate.burstStartedAtMs +
        rainpoint::kHtv145ImmediateResponseWindowMs;
    htv145ControlCandidate.stateConfirmationDeadlineMs =
        htv145ControlCandidate.burstStartedAtMs +
        rainpoint::kHtv145StateConfirmationWindowMs;
#if RAINPOINT_RADIO_COUNT == 1
    scanChannels = false;
#endif
    return transmitNextHtv145CandidateAttempt();
}

void observeHtv145CandidateFrame(
    const std::array<std::uint8_t, rainpoint::kFrameBytes>& frame
) {
    if (!htv145ControlCandidate.pending) {
        return;
    }
    ++htv145ControlCandidate.observedFrames;
    const bool matchingRoute = rainpoint::htv145RouteMatches(
        frame,
        htv145ControlCandidate.link.valveEndpoint,
        htv145ControlCandidate.link.controllerEndpoint
    );
    if (matchingRoute) {
        ++htv145ControlCandidate.matchingRouteFrames;
        if (!rainpoint::hasOrdinaryTrailer(frame)) {
            ++htv145ControlCandidate.invalidTrailerFrames;
            return;
        }
    }
    rainpoint::Htv145CommandResponse response{};
    if (rainpoint::decodeHtv145CommandResponse(
            frame, htv145ControlCandidate.link, response
        )) {
        ++htv145ControlCandidate.classifiedResponseFrames;
        if (response.sequence != htv145ControlCandidate.transmittedSequence ||
            response.watering != htv145ControlCandidate.commandWatering) {
            failHtv145Candidate("conflicting_command_response");
            return;
        }
        confirmHtv145Candidate("matching_immediate_response", frame);
        return;
    }
    bool watering = false;
    if (rainpoint::decodeHtv145StateReport(
            frame, htv145ControlCandidate.link, watering
        )) {
        ++htv145ControlCandidate.classifiedStateFrames;
        if (watering != htv145ControlCandidate.commandWatering) {
            ++htv145ControlCandidate.conflictingStateFrames;
            return;
        }
        // This report has its own telemetry counter. It proves resulting state
        // but never supplies or overwrites the outbound command counter.
        confirmHtv145Candidate("matching_independent_state_report", frame);
    }
}

void pollHtv145Candidate() {
    if (!htv145ControlCandidate.pending) {
        return;
    }
    const std::uint32_t now = millis();
    if (htv145ControlCandidate.attemptsSent <
            rainpoint::kHtv145CommandAttemptOffsetsMs.size() &&
        static_cast<std::int32_t>(
            now - htv145ControlCandidate.nextAttemptAtMs
        ) >= 0) {
        transmitNextHtv145CandidateAttempt();
        return;
    }
    if (htv145ControlCandidate.listeningOnCommandCarrier &&
        static_cast<std::int32_t>(
            now - htv145ControlCandidate.immediateResponseDeadlineMs
        ) >= 0) {
        // The fallback watering/idle report is on the ordinary telemetry
        // carrier. Restore it once the immediate response window closes.
        restoreHtv145CandidateReceive();
        htv145ControlCandidate.immediateResponseWindowClosed = true;
#if RAINPOINT_RADIO_COUNT == 1
        scanChannels = false;
#endif
    }
    if (static_cast<std::int32_t>(
            now - htv145ControlCandidate.stateConfirmationDeadlineMs
        ) >= 0) {
        failHtv145Candidate("confirmation_timeout_counter_unsynchronized");
    }
}
#endif

void reportNetworkCommandError(const String& commandId, const char* error) {
    String line = "{\"type\":\"command_error\",\"node_id\":\"";
    line += wifiTransport.nodeId();
    line += "\",\"command_id\":\"";
    line += commandId;
    line += "\",\"error\":\"";
    line += error;
    line += "\"}";
    emitLine(line);
}

void setIdentifyLed(bool on) {
    identifyLedOn = on;
    digitalWrite(RAINPOINT_STATUS_LED_PIN, on ? HIGH : LOW);
}

void reportIdentifyStatus(bool active) {
    String line = "{\"type\":\"identify_status\",\"node_id\":\"";
    line += wifiTransport.nodeId();
    line += "\",\"command_id\":\"";
    line += identifyCommandId;
    line += "\",\"active\":";
    line += active ? "true" : "false";
    line += "}";
    emitLine(line);
}

void pollIdentify() {
    if (identifyUntilMs == 0) {
        return;
    }
    const std::uint32_t now = millis();
    if (static_cast<std::int32_t>(now - identifyUntilMs) >= 0) {
        identifyUntilMs = 0;
        setIdentifyLed(false);
        reportIdentifyStatus(false);
        identifyCommandId.clear();
        return;
    }
    if (now - lastIdentifyToggleMs >= kIdentifyToggleMs) {
        lastIdentifyToggleMs = now;
        setIdentifyLed(!identifyLedOn);
    }
}

void handleNetworkCommand() {
    String command;
    if (!wifiTransport.takeCommand(command)) {
        return;
    }
    const String type = jsonStringField(command, "type");
    const String commandId = jsonStringField(command, "command_id");
    if (!validCommandId(commandId)) {
        reportNetworkCommandError("invalid", "invalid_command_id");
        return;
    }
    if (type == "rf_mode_set") {
        const String mode = jsonStringField(command, "mode");
        if (mode == "normal") {
            resumeRfNormal(commandId, "normal_restored");
            return;
        }
        long durationSeconds = 0;
        if (mode != "receive_only" ||
            !jsonLongField(command, "duration_seconds", durationSeconds) ||
            durationSeconds < static_cast<long>(
                rainpoint::RfMaintenanceState::kMinimumReceiveOnlySeconds
            ) ||
            durationSeconds > static_cast<long>(
                rainpoint::RfMaintenanceState::kMaximumReceiveOnlySeconds
            )) {
            reportNetworkCommandError(commandId, "invalid_rf_mode_request");
            return;
        }
        enterRfReceiveOnly(
            commandId, static_cast<std::uint32_t>(durationSeconds)
        );
        return;
    }
    if (type == "node_reboot") {
        nodeRestartPending = true;
        rfMaintenanceCommandId = commandId;
        reportRfMaintenanceStatus("reboot_scheduled");
        return;
    }
    if (!rfMaintenance.transmitAllowed() && rfCommandMayTransmit(type)) {
        ++rfRejectedCommandCount;
        reportNetworkCommandError(commandId, "rf_receive_only");
        reportRfMaintenanceStatus("transmit_command_rejected");
        return;
    }
    if (type == "identify_start") {
        long durationSeconds = 0;
        if (!jsonLongField(command, "duration_seconds", durationSeconds) ||
            durationSeconds < 3 || durationSeconds > 60) {
            reportNetworkCommandError(commandId, "invalid_identify_duration");
            return;
        }
        identifyCommandId = commandId;
        identifyUntilMs = millis() +
            static_cast<std::uint32_t>(durationSeconds) * 1'000U;
        lastIdentifyToggleMs = millis();
        setIdentifyLed(true);
        reportIdentifyStatus(true);
        return;
    }
#if RAINPOINT_HTV145_TX_CANDIDATE == 1
    if (type == "htv145_control_configure") {
        rainpoint::Htv145Link link{};
        const String controller = jsonStringField(
            command, "controller_endpoint"
        );
        const String valve = jsonStringField(command, "valve_endpoint");
        long centerHz = 0;
        long powerDbm = 0;
        long trailerResidual = 0;
        bool invert = false;
        if (!parseRawHexEndpoint(controller, link.controllerEndpoint) ||
            !parseRawHexEndpoint(valve, link.valveEndpoint) ||
            !rainpoint::validHtv145Link(link) ||
            !jsonLongField(command, "center_hz", centerHz) ||
            centerHz < 433'000'000 || centerHz > 435'000'000 ||
            !jsonLongField(command, "power_dbm", powerDbm) ||
            powerDbm < -128 || powerDbm > 127 ||
            !rainpoint::validPairingPowerDbm(
                static_cast<std::int8_t>(powerDbm)
            ) ||
            !jsonLongField(
                command, "trailer_residual", trailerResidual
            ) ||
            (trailerResidual != 0xc713 && trailerResidual != 0x4f03) ||
            !jsonBoolField(command, "invert", invert) ||
            htv145ControlCandidate.pending ||
            currentPairingState() == rainpoint::PairingSessionState::Armed ||
            !primaryRadio.prepareTransmit()) {
            reportNetworkCommandError(
                commandId, "invalid_htv145_control_profile"
            );
            return;
        }
        primaryRadio.cacheTransmitFrequency(
            static_cast<std::uint32_t>(centerHz)
        );
        htv145ControlCandidate = Htv145ControlCandidate{};
        htv145ControlCandidate.link = link;
        htv145ControlCandidate.centerHz =
            static_cast<std::uint32_t>(centerHz);
        htv145ControlCandidate.powerDbm =
            static_cast<std::int8_t>(powerDbm);
        htv145ControlCandidate.trailerResidual =
            static_cast<std::uint16_t>(trailerResidual);
        htv145ControlCandidate.invert = invert;
        htv145ControlCandidate.configured = true;
        htv145ControlCandidate.commandId = commandId;
        reportHtv145CandidateStatus("configured_counter_required");
        htv145ControlCandidate.commandId.clear();
        return;
    }
    if (type == "htv145_control_sync") {
        long nextSequence = 0;
        if (!htv145ControlCandidate.configured ||
            htv145ControlCandidate.pending ||
            !jsonLongField(command, "next_sequence", nextSequence) ||
            nextSequence < 0x80 || nextSequence > 0x9f) {
            reportNetworkCommandError(
                commandId, "invalid_htv145_control_sync"
            );
            return;
        }
        htv145ControlCandidate.nextSequence =
            static_cast<std::uint8_t>(nextSequence);
        htv145ControlCandidate.counterAuthenticated = true;
        htv145ControlCandidate.commandId = commandId;
        reportHtv145CandidateStatus("counter_synchronized");
        htv145ControlCandidate.commandId.clear();
        return;
    }
    if (type == "htv145_control_open") {
        long expectedSequence = 0;
        long durationSeconds = 0;
        if (!jsonLongField(
                command, "expected_sequence", expectedSequence
            ) ||
            expectedSequence != htv145ControlCandidate.nextSequence ||
            !jsonLongField(command, "duration_seconds", durationSeconds) ||
            durationSeconds < 60 || durationSeconds > 3'600 ||
            durationSeconds % 60 != 0 ||
            !startHtv145Candidate(
                commandId, true,
                static_cast<std::uint32_t>(durationSeconds)
            )) {
            reportNetworkCommandError(
                commandId, "invalid_htv145_control_open"
            );
        }
        return;
    }
    if (type == "htv145_control_close") {
        long expectedSequence = 0;
        if (!jsonLongField(
                command, "expected_sequence", expectedSequence
            ) ||
            expectedSequence != htv145ControlCandidate.nextSequence ||
            !startHtv145Candidate(commandId, false, 0)) {
            reportNetworkCommandError(
                commandId, "invalid_htv145_control_close"
            );
        }
        return;
    }
    if (type == "htv145_control_status") {
        htv145ControlCandidate.commandId = commandId;
        reportHtv145CandidateStatus("status_requested");
        htv145ControlCandidate.commandId.clear();
        return;
    }
#endif
#if RAINPOINT_SUPERVISED_HTV405_CONTROL == 1
    if (type == "valve_control_configure") {
        valveControlProbe.commandId = commandId;
        const String controller = jsonStringField(
            command, "controller_endpoint"
        );
        const String valve = jsonStringField(command, "valve_endpoint");
        const String companion = jsonStringField(
            command, "companion_endpoint"
        );
        long selector = 0;
        long frequencyOffsetHz = 0;
        if (!jsonLongField(command, "selector", selector) ||
            !jsonLongField(
                command, "frequency_offset_hz", frequencyOffsetHz
            )) {
            reportNetworkCommandError(
                commandId, "invalid_valve_control_profile"
            );
            return;
        }
        String local = "valve_probe_config ";
        local += controller;
        local += ' ';
        local += valve;
        local += ' ';
        local += companion;
        local += ' ';
        local += selector;
        local += ' ';
        local += frequencyOffsetHz;
        configureValveProbe(local);
        if (valveControlProbe.configured) {
            valveControlProbe.commandId = commandId;
        }
        return;
    }
    if (type == "valve_control_sync") {
        valveControlProbe.commandId = commandId;
        long sequence = -1;
        if (!jsonLongField(command, "next_sequence", sequence) ||
            sequence < 0 || sequence > 0x1f ||
            !valveControlProbe.configured ||
            valveControlProbe.commandPendingConfirmation ||
            currentPairingState() == rainpoint::PairingSessionState::Armed) {
            reportNetworkCommandError(
                commandId, "invalid_valve_control_sync"
            );
            return;
        }
        String local = "valve_probe_phase ";
        local += sequence;
        local += " 0";
        configureValveProbeCommandPhase(local);
        // This path is accepted only over the authenticated protocol-v2
        // session and the daemon supplies a counter previously confirmed by
        // this same association. It is distinct from manual serial recovery.
        valveControlProbe.commandCounterAuthenticated = true;
        reportValveProbeStatus("command_phase_restored_by_gateway");
        return;
    }
    if (type == "valve_control_open") {
        valveControlProbe.commandId = commandId;
        long zone = 0;
        long durationSeconds = 0;
        long expectedSequence = -1;
        if (!jsonLongField(command, "zone", zone) ||
            zone < 1 || zone > 4 ||
            !jsonLongField(
                command, "duration_seconds", durationSeconds
            ) || durationSeconds < 60 || durationSeconds > 3'600 ||
            durationSeconds % 60 != 0 ||
            !jsonLongField(
                command, "expected_sequence", expectedSequence
            ) || expectedSequence != valveControlProbe.commandSequence ||
            !valveControlProbe.commandCounterAuthenticated) {
            reportNetworkCommandError(
                commandId, "invalid_valve_control_open"
            );
            return;
        }
        transmitValveProbeOpen(
            static_cast<std::uint8_t>(zone),
            true,
            static_cast<std::uint16_t>(durationSeconds)
        );
        return;
    }
    if (type == "valve_control_close") {
        valveControlProbe.commandId = commandId;
        long zone = 0;
        long expectedSequence = -1;
        if (!jsonLongField(command, "zone", zone) ||
            zone < 1 || zone > 4 ||
            !jsonLongField(
                command, "expected_sequence", expectedSequence
            ) || expectedSequence != valveControlProbe.commandSequence ||
            !valveControlProbe.commandCounterAuthenticated) {
            reportNetworkCommandError(
                commandId, "invalid_valve_control_close"
            );
            return;
        }
        transmitValveProbeClose(static_cast<std::uint8_t>(zone), true);
        return;
    }
    if (type == "valve_control_status") {
        reportValveProbeStatus("status_requested_by_gateway");
        return;
    }
#endif
#if RAINPOINT_ROUTINE_ACK_CANDIDATE == 1
    if (type == "routine_ack_configure") {
        const String endpointValue = jsonStringField(
            command, "paired_endpoint"
        );
        long assignedChannel = 0;
        long frequencyOffsetHz = 0;
        long powerDbm = 0;
        bool invert = false;
        rainpoint::RoutineAckAuthorization authorization{};
        if (currentPairingState() == rainpoint::PairingSessionState::Armed ||
            !parseHexEndpoint(endpointValue, authorization.pairedEndpoint) ||
            !parseRawHexEndpoint(
                jsonStringField(command, "controller_endpoint"),
                authorization.controllerEndpoint
            ) ||
            !parseRawHexEndpoint(
                jsonStringField(command, "companion_endpoint"),
                authorization.companionEndpoint
            ) ||
            !jsonLongField(command, "assigned_channel", assignedChannel) ||
            !jsonLongField(command, "frequency_offset_hz", frequencyOffsetHz) ||
            !jsonLongField(command, "power_dbm", powerDbm) ||
            !jsonBoolField(command, "invert", invert) ||
            assignedChannel < 0 || assignedChannel > 255 ||
            frequencyOffsetHz < -rainpoint::kMaxPairingFrequencyOffsetHz ||
            frequencyOffsetHz > rainpoint::kMaxPairingFrequencyOffsetHz ||
            powerDbm < -128 || powerDbm > 127) {
            reportNetworkCommandError(commandId, "invalid_ack_configuration");
            return;
        }
        authorization.pairingChannel = static_cast<std::uint8_t>(
            assignedChannel
        );
        authorization.frequencyOffsetHz = static_cast<std::int32_t>(
            frequencyOffsetHz
        );
        authorization.powerDbm = static_cast<std::int8_t>(powerDbm);
        authorization.invert = invert;
        authorization.active = true;
        const bool authorized = routineAckAuthorizations.authorize(
            authorization
        );
        reportRoutineAckStatus(
            authorized ? "configured_by_gateway" : "configuration_rejected",
            authorization
        );
        return;
    }
    if (type == "routine_ack_revoke") {
        rainpoint::RoutineAckAuthorization authorization{};
        const bool valid = parseHexEndpoint(
            jsonStringField(command, "paired_endpoint"),
            authorization.pairedEndpoint
        );
        if (!valid) {
            reportNetworkCommandError(commandId, "invalid_ack_endpoint");
            return;
        }
        const bool revoked = routineAckAuthorizations.revoke(
            authorization.pairedEndpoint
        );
        reportRoutineAckStatus(
            revoked ? "revoked_by_gateway" : "authorization_not_found",
            authorization
        );
        return;
    }
    if (type == "htv405_routine_ack_configure") {
        long frequencyOffsetHz = 0;
        long powerDbm = 0;
        bool invert = false;
        rainpoint::Htv405RoutineAckAuthorization authorization{};
        if (currentPairingState() == rainpoint::PairingSessionState::Armed ||
            !parseRawHexEndpoint(
                jsonStringField(command, "controller_endpoint"),
                authorization.controllerEndpoint
            ) ||
            !parseRawHexEndpoint(
                jsonStringField(command, "valve_endpoint"),
                authorization.valveEndpoint
            ) ||
            !parseRawHexEndpoint(
                jsonStringField(command, "companion_endpoint"),
                authorization.companionEndpoint
            ) ||
            !jsonLongField(command, "frequency_offset_hz", frequencyOffsetHz) ||
            !jsonLongField(command, "power_dbm", powerDbm) ||
            !jsonBoolField(command, "invert", invert) ||
            frequencyOffsetHz < -rainpoint::kMaxPairingFrequencyOffsetHz ||
            frequencyOffsetHz > rainpoint::kMaxPairingFrequencyOffsetHz ||
            powerDbm < -128 || powerDbm > 127) {
            reportNetworkCommandError(
                commandId, "invalid_htv405_ack_configuration"
            );
            return;
        }
        authorization.frequencyOffsetHz = static_cast<std::int32_t>(
            frequencyOffsetHz
        );
        authorization.powerDbm = static_cast<std::int8_t>(powerDbm);
        authorization.invert = invert;
        authorization.active = true;
        const std::uint32_t centerHz =
            rainpoint::routineHtv405AckCenterHz(authorization);
        const bool radioReady = centerHz >= 433'000'000 &&
            centerHz <= 435'000'000 && primaryRadio.prepareTransmit() &&
            primaryRadio.cacheTransmitFrequency(centerHz);
        const bool authorized = radioReady &&
            htv405RoutineAckAuthorizations.authorize(authorization);
        reportHtv405RoutineAckStatus(
            authorized ? "configured_by_gateway" : "configuration_rejected",
            authorization
        );
        return;
    }
    if (type == "htv405_routine_ack_revoke") {
        rainpoint::Htv405RoutineAckAuthorization authorization{};
        if (!parseRawHexEndpoint(
                jsonStringField(command, "valve_endpoint"),
                authorization.valveEndpoint
            )) {
            reportNetworkCommandError(commandId, "invalid_htv405_ack_endpoint");
            return;
        }
        const bool revoked = htv405RoutineAckAuthorizations.revoke(
            authorization.valveEndpoint
        );
        reportHtv405RoutineAckStatus(
            revoked ? "revoked_by_gateway" : "authorization_not_found",
            authorization
        );
        return;
    }
#endif
#if RAINPOINT_OTA_CANDIDATE == 1
    if (type == "firmware_update_start") {
        const String url = jsonStringField(command, "url");
        const String version = jsonStringField(command, "version");
        const String sha256 = jsonStringField(command, "sha256");
        long sizeBytes = 0;
        if (!jsonLongField(command, "size_bytes", sizeBytes) ||
            sizeBytes <= 0 || currentPairingState() ==
                rainpoint::PairingSessionState::Armed) {
            reportNetworkCommandError(commandId, "invalid_update_request");
            return;
        }
        otaTrial.install(
            commandId,
            url,
            version,
            sha256,
            static_cast<std::size_t>(sizeBytes),
            wifiTransport.gatewayHost()
        );
        emitLine(otaTrial.status(wifiTransport.nodeId()));
        return;
    }
#endif
    if (type == "pairing_cancel") {
        if (!pairingCommandId.isEmpty() && commandId != pairingCommandId) {
            reportNetworkCommandError(commandId, "pairing_command_mismatch");
            return;
        }
        pairingCommandId = commandId;
        cancelPairing("cancelled_by_gateway");
        return;
    }
    if (type != "pairing_start") {
        reportNetworkCommandError(commandId, "unsupported_command");
        return;
    }
    if (currentPairingState() == rainpoint::PairingSessionState::Armed) {
        reportNetworkCommandError(commandId, "pairing_is_armed");
        return;
    }
    const String profile = jsonStringField(command, "profile");
    const String factory = jsonStringField(command, "factory_endpoint");
    const String clock = jsonStringField(command, "local_clock");
    long durationSeconds = 0;
    long frequencyOffsetHz = 0;
    long maximumPairingFrequencyOffsetHz =
        rainpoint::kMaxPairingFrequencyOffsetHz;
    long powerDbm = 0;
    bool invert = false;
    rainpoint::PairingLocalDateTime parsedClock{};
    const rainpoint::PairingProfile* requestedProfile = nullptr;
    bool requestedAutomaticDiscovery = false;
    bool requestedAutomaticRejoin = false;
    bool requestedValvePairing = false;
    bool requestedValveRejoin = false;
    bool requestedValveAutomaticDiscovery = false;
    std::array<std::uint8_t, 4> requestedFactoryEndpoint{};
    std::array<std::uint8_t, 4> requestedControllerEndpoint{};
    std::array<std::uint8_t, 4> requestedValveRoute{};
    std::array<std::uint8_t, 4> requestedCompanionEndpoint{};
    bool requestedKnownFactory = false;
#if RAINPOINT_PAIRING_GENERALIZATION == 1
    const String sensorAFactory = hexString(
        rainpoint::kSensorAHcs026CandidateProfile.factoryEndpoint.data(),
        rainpoint::kSensorAHcs026CandidateProfile.factoryEndpoint.size()
    );
    const String sensorBFactory = hexString(
        rainpoint::kValidatedHcs026Profile.factoryEndpoint.data(),
        rainpoint::kValidatedHcs026Profile.factoryEndpoint.size()
    );
    const bool requestedHcs026ControllerIdentity =
        parseRawHexEndpoint(
            jsonStringField(command, "controller_endpoint"),
            requestedControllerEndpoint
        ) &&
        parseRawHexEndpoint(
            jsonStringField(command, "companion_endpoint"),
            requestedCompanionEndpoint
        ) &&
        rainpoint::validRfControllerIdentity(
            requestedControllerEndpoint, requestedCompanionEndpoint
        );
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
    const bool requestedHtv405Profile =
        profile == rainpoint::kAutomaticHtv405ProfileId;
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
    const bool requestedHtv145Profile =
        profile == rainpoint::htv145::kProfileId;
    if (requestedHtv145Profile) {
        maximumPairingFrequencyOffsetHz =
            rainpoint::htv145::kMaximumPairingFrequencyOffsetHz;
    }
#else
    const bool requestedHtv145Profile = false;
#endif
    const bool requestedValveFactoryParsed =
        parseRawHexEndpoint(factory, requestedFactoryEndpoint);
    requestedValveAutomaticDiscovery =
        requestedHtv405Profile && factory.isEmpty();
#endif
    if (
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
        (requestedValveAutomaticDiscovery ||
            ((requestedHtv405Profile || requestedHtv145Profile) &&
                requestedValveFactoryParsed)) &&
        parseRawHexEndpoint(
            jsonStringField(command, "valve_route"), requestedValveRoute
        ) &&
        parseRawHexEndpoint(
            jsonStringField(command, "companion_endpoint"),
            requestedCompanionEndpoint
        )
#else
        false
#endif
    ) {
        requestedValvePairing = true;
        jsonBoolField(command, "known_rejoin", requestedValveRejoin);
    } else if (profile == rainpoint::kAutomaticHcs026ProfileId &&
        factory.isEmpty() && requestedHcs026ControllerIdentity) {
        requestedProfile = &rainpoint::kSensorAHcs026CandidateProfile;
        requestedAutomaticDiscovery = true;
    } else if (profile == rainpoint::kAutomaticHcs026ProfileId &&
        requestedHcs026ControllerIdentity &&
        parseHexFactoryEndpoint(factory, requestedFactoryEndpoint)) {
        requestedProfile = &rainpoint::kSensorAHcs026CandidateProfile;
        requestedKnownFactory = true;
        jsonBoolField(command, "known_rejoin", requestedAutomaticRejoin);
    } else if (profile == rainpoint::kSensorAHcs026CandidateProfile.id &&
        factory == sensorAFactory) {
        requestedProfile = &rainpoint::kSensorAHcs026CandidateProfile;
    } else if (profile == rainpoint::kValidatedHcs026Profile.id &&
        factory == sensorBFactory) {
        requestedProfile = &rainpoint::kValidatedHcs026Profile;
    }
#else
    const String expectedFactory = hexString(
        activePairingProfile.factoryEndpoint.data(),
        activePairingProfile.factoryEndpoint.size()
    );
    if (profile == activePairingProfile.id && factory == expectedFactory) {
        requestedProfile = &activePairingProfile;
    }
#endif
    if (requestedProfile == nullptr && !requestedValvePairing) {
        reportNetworkCommandError(commandId, "unsupported_pairing_profile");
        return;
    }
    if (!jsonLongField(command, "duration_seconds", durationSeconds) ||
        durationSeconds < 10 || durationSeconds > 900) {
        reportNetworkCommandError(commandId, "invalid_pairing_duration");
        return;
    }
    if (!jsonLongField(command, "frequency_offset_hz", frequencyOffsetHz) ||
        frequencyOffsetHz < -maximumPairingFrequencyOffsetHz ||
        frequencyOffsetHz > maximumPairingFrequencyOffsetHz) {
        reportNetworkCommandError(commandId, "pairing_offset_out_of_range");
        return;
    }
    if (!jsonLongField(command, "power_dbm", powerDbm) ||
        powerDbm < -128 || powerDbm > 127 ||
        !rainpoint::validPairingPowerDbm(static_cast<std::int8_t>(powerDbm))) {
        reportNetworkCommandError(commandId, "pairing_power_invalid");
        return;
    }
    if (!jsonBoolField(command, "invert", invert) ||
        !parsePairingLocalDateTime(clock, parsedClock)) {
        reportNetworkCommandError(commandId, "pairing_parameters_invalid");
        return;
    }

    pairingAutomaticDiscovery =
        requestedAutomaticDiscovery || requestedValveAutomaticDiscovery;
    pairingFactoryAdopted = !pairingAutomaticDiscovery;
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
    valvePairingActive = requestedValvePairing;
    valvePairingKnownRejoin = requestedValvePairing && requestedValveRejoin;
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
    valvePairingHtv145 = requestedValvePairing &&
        profile == rainpoint::htv145::kProfileId;
#endif
    if (requestedValvePairing) {
        const bool profileBuilt =
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
            valvePairingHtv145
                ? rainpoint::htv145::buildProfile(
                    requestedFactoryEndpoint,
                    requestedValveRoute,
                    requestedCompanionEndpoint,
                    activeHtv145PairingProfile
                )
                :
#endif
            (requestedValveAutomaticDiscovery
                ? rainpoint::initializeAutomaticHtv405Profile(
                    requestedValveRoute,
                    requestedCompanionEndpoint,
                    activeValvePairingProfile
                )
                : rainpoint::buildAutomaticHtv405Profile(
                    requestedFactoryEndpoint,
                    requestedValveRoute,
                    requestedCompanionEndpoint,
                    activeValvePairingProfile
                ));
        if (!profileBuilt) {
            reportNetworkCommandError(commandId, "valve_association_invalid");
            valvePairingActive = false;
            return;
        }
        if (!primaryRadio.prepareTransmit()) {
            reportNetworkCommandError(commandId, "valve_transmitter_prepare_failed");
            valvePairingActive = false;
            return;
        }
        pairingAssignedChannel =
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
            valvePairingHtv145 ? 12 :
#endif
            0;
    } else
#endif
    {
        activePairingProfile = *requestedProfile;
#if RAINPOINT_PAIRING_GENERALIZATION == 1
    // Same-selector coexistence is physically validated: addressed sensors can
    // share one RF channel, so selector allocation must not imply uniqueness.
    pairingAssignedChannel = 4;
    const bool channelAssigned = requestedAutomaticDiscovery
        ? rainpoint::buildAutomaticHcs026Profile(
            rainpoint::kSensorAHcs026CandidateProfile.factoryEndpoint,
            requestedControllerEndpoint,
            requestedCompanionEndpoint,
            pairingAssignedChannel,
            activePairingProfile
        )
        : requestedKnownFactory
            ? (requestedAutomaticRejoin
                ? rainpoint::buildAutomaticHcs026RejoinProfile(
                    requestedFactoryEndpoint,
                    requestedControllerEndpoint,
                    requestedCompanionEndpoint,
                    pairingAssignedChannel,
                    activePairingProfile
                )
                : rainpoint::buildAutomaticHcs026Profile(
                    requestedFactoryEndpoint,
                    requestedControllerEndpoint,
                    requestedCompanionEndpoint,
                    pairingAssignedChannel,
                    activePairingProfile
                ))
        : rainpoint::assignPairingChannel(
            activePairingProfile, pairingAssignedChannel
        );
    if (!channelAssigned) {
        reportNetworkCommandError(commandId, "pairing_channel_invalid");
        return;
    }
#else
    pairingAssignedChannel = rainpoint::pairingChannelFromReply(
        activePairingProfile.steps[0].frame
    );
#endif
    }
    pairingCommandId = commandId;
    pairingFrequencyOffsetHz = static_cast<std::int32_t>(frequencyOffsetHz);
    pairingPowerDbm = static_cast<std::int8_t>(powerDbm);
    pairingInvert = invert;
    pairingLocalDateTime = parsedClock;
    pairingLocalDateTimeSet = true;
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
    if (valvePairingActive) {
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
        const std::uint32_t initialCenterHz = valvePairingHtv145
            ? activeHtv145PairingProfile.steps[0].channelCenterHz
            : activeValvePairingProfile.steps[0].channelCenterHz;
        const std::uint32_t routineCenterHz = valvePairingHtv145
            ? activeHtv145PairingProfile.steps[1].channelCenterHz
            : activeValvePairingProfile.steps[1].channelCenterHz;
#else
        const std::uint32_t initialCenterHz =
            activeValvePairingProfile.steps[0].channelCenterHz;
        const std::uint32_t routineCenterHz =
            activeValvePairingProfile.steps[1].channelCenterHz;
#endif
        const std::uint32_t initialFrequency = static_cast<std::uint32_t>(
            static_cast<std::int64_t>(initialCenterHz) +
            pairingFrequencyOffsetHz
        );
        const std::uint32_t routineFrequency = static_cast<std::uint32_t>(
            static_cast<std::int64_t>(routineCenterHz) +
            pairingFrequencyOffsetHz
        );
        if (!primaryRadio.cacheTransmitFrequency(initialFrequency) ||
            !primaryRadio.cacheTransmitFrequency(routineFrequency)) {
            reportNetworkCommandError(
                commandId, "valve_frequency_calibration_failed"
            );
            valvePairingActive = false;
            return;
        }
    }
#endif
#if RAINPOINT_RADIO_COUNT == 1
    scanChannels = false;
    selectChannel(0);
#endif
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
    if (valvePairingActive) {
        const auto durationMs =
            static_cast<std::uint32_t>(durationSeconds) * 1'000U;
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
        if (valvePairingHtv145) {
            // HTV145 owns an independent one-shot transcript. It must never
            // inherit HTV405 retries, resynchronization, or retained-rejoin
            // behavior while the fresh-enrollment prefix is being proven.
            htv145PairingSession.arm(millis(), durationMs);
        } else
#endif
        {
            valvePairingSession.arm(
                millis(), durationMs, requestedValveRejoin
            );
        }
    } else
#endif
    {
        pairingSession.arm(
            millis(), static_cast<std::uint32_t>(durationSeconds) * 1'000U
        );
    }
    // Frequency calibration is part of pairing preparation. Anchor the
    // supplied wall clock only after preparation so that its duration is not
    // added again when constructing the first reply.
    pairingLocalDateTimeSetAtMs = millis();
    // A valve enrollment is explicitly authorized by the authenticated
    // pairing_start command and remains bounded by its session timeout. Keep
    // that session armed if the gateway listener is temporarily stopped for
    // simultaneous raw SDR capture; sensor pairing retains the existing
    // fail-closed connection requirement.
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
    pairingRequiresNetwork = !valvePairingActive;
#else
    pairingRequiresNetwork = true;
#endif
    reportPairingStatus(
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
        valvePairingActive && valvePairingKnownRejoin
            ? "waiting_for_cold_boot_rejoin" :
#endif
        "waiting_for_factory_message_1"
    );
}

#if RAINPOINT_RESEARCH_BENCH == 1 && RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
bool handleHtv145PreludeCalibration(const String& command) {
    const String prefix = "htv145_prelude_calibration ";
    if (!command.startsWith(prefix)) {
        return false;
    }
    const String offsetValue = command.substring(prefix.length());
    const long frequencyOffsetHz = offsetValue.toInt();
    if (offsetValue.isEmpty() || frequencyOffsetHz < -250'000 ||
        frequencyOffsetHz > 250'000 ||
        currentPairingState() == rainpoint::PairingSessionState::Armed) {
        emitLine(
            "{\"type\":\"command_error\","
            "\"error\":\"htv145_prelude_calibration_invalid\"}"
        );
        return true;
    }

    const std::int64_t adjustedFrequency =
        static_cast<std::int64_t>(rainpoint::kHtv405InitialChannelCenterHz) +
        frequencyOffsetHz;
    if (adjustedFrequency < 433'000'000 || adjustedFrequency > 435'000'000 ||
        !primaryRadio.prepareTransmit() ||
        !primaryRadio.cacheTransmitFrequency(
            static_cast<std::uint32_t>(adjustedFrequency)
        )) {
        emitLine(
            "{\"type\":\"command_error\","
            "\"error\":\"htv145_prelude_calibration_prepare_failed\"}"
        );
        return true;
    }

    // This deliberately unaddressed frame keeps the ordinary assignment
    // waveform realistic without enrolling or controlling a RainPoint device.
    // Only the leading prelude parameters below vary across the four shots.
    std::array<std::uint8_t, rainpoint::kFrameBytes> frame{};
    for (std::size_t index = 0; index < rainpoint::kSync.size(); ++index) {
        frame[index] = rainpoint::kSync[index];
    }
    constexpr std::array<std::uint8_t, 4> source{{0xde, 0xad, 0xc0, 0xde}};
    constexpr std::array<std::uint8_t, 4> destination{{0xf0, 0x0d, 0xca, 0xfe}};
    for (std::size_t index = 0; index < source.size(); ++index) {
        frame[5 + index] = source[index];
        frame[9 + index] = destination[index];
    }
    frame[13] = 0x80;
    frame[14] = 0xc0;
    frame[15] = 0x85;
    frame[16] = 0x85;
    rainpoint::writeTrailer(frame, 0x4f03);

    struct PreludeVariant {
        std::int8_t frequencyOffsetRegister;
        std::uint8_t deviationRegister;
    };
    constexpr std::array<PreludeVariant, 4> variants{{
        {12, 0x41},
        {12, 0x42},
        {13, 0x41},
        {13, 0x42},
    }};
    for (std::size_t index = 0; index < variants.size(); ++index) {
        const auto& variant = variants[index];
        String line;
        line.reserve(240);
        line += "{\"type\":\"htv145_prelude_calibration\",\"variant\":";
        line += index + 1;
        line += ",\"state\":\"starting\",\"center_hz\":";
        line += static_cast<std::uint32_t>(adjustedFrequency);
        line += ",\"prelude_polarity\":\"reversed\",\"fsctrl0\":";
        line += static_cast<int>(variant.frequencyOffsetRegister);
        line += ",\"deviatn\":\"0x";
        line += variant.deviationRegister == 0x41 ? "41" : "42";
        line += "\"}";
        emitLine(line);
        Serial.flush();
        delay(250);

        const bool sent = primaryRadio.transmitAsync(
            frame,
            static_cast<std::uint32_t>(adjustedFrequency),
            rainpoint::kPairingWakeSymbols,
            false,
            // Keep this near-field measurement below the RTL-SDR's clipping
            // point. Live pairing retains its separately configured power.
            rainpoint::pairingPaTableValue(0),
            rainpoint::kHtv405InitialDeviationRegister,
            micros() + 20'000,
            rainpoint::htv145::kCounter0AssignmentPreludeSymbols,
            variant.frequencyOffsetRegister,
            variant.deviationRegister,
            true
        );
        line = "{\"type\":\"htv145_prelude_calibration\",\"variant\":";
        line += index + 1;
        line += sent
            ? ",\"state\":\"transmitted\"}"
            : ",\"state\":\"transmit_failed\"}";
        emitLine(line);
        delay(750);
    }
    emitLine(
        "{\"type\":\"htv145_prelude_calibration\","
        "\"state\":\"complete\"}"
    );
    return true;
}
#endif

void handleSerialCommand() {
    while (Serial.available()) {
        const char value = static_cast<char>(Serial.read());
        if (value == '\n' || value == '\r') {
            if (serialCommand.isEmpty()) {
                continue;
            }
            bool handled = false;
#if RAINPOINT_RESEARCH_BENCH == 1
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
            handled = handleHtv145PreludeCalibration(serialCommand);
#endif
#if RAINPOINT_SUPERVISED_HTV405_CONTROL == 1
            if (!handled) {
                handled = handleValveProbeCommand(serialCommand);
            }
#endif
            if (!handled && serialCommand == "pairing_plan_b") {
                handled = true;
                for (std::size_t index = 0;
                     index < activePairingProfile.stepCount;
                     ++index) {
                    const auto& step = activePairingProfile.steps[index];
                    String line;
                    line.reserve(360);
                    line += "{\"type\":\"pairing_dry_run\",\"step\":";
                    line += index + 1;
                    line += ",\"trigger\":\"";
                    line += rainpoint::pairingTriggerName(step.trigger);
                    line += "\",\"channel_center_hz\":";
                    line += step.channelCenterHz;
                    line += ",\"wake_symbols\":";
                    line += step.wakeSymbols;
                    line += ",\"reply_delay_ms\":";
                    line += activePairingProfile.replyDelayMs;
                    line += ",\"reply_deadline_ms\":";
                    line += step.replyDeadlineMs;
                    line += ",\"transmit_enabled\":false,\"frame\":\"";
                    line += hexString(step.frame.data(), step.frame.size());
                    line += "\"}";
                    emitLine(line);
                }
            }
            if (!handled && serialCommand == "pairing_arm_b 15a98024") {
                handled = true;
                if (!pairingLocalDateTimeSet) {
                    emitLine(
                        "{\"type\":\"command_error\","
                        "\"error\":\"pairing_local_clock_required\"}"
                    );
                    serialCommand = "";
                    continue;
                }
#if RAINPOINT_RADIO_COUNT == 1
                scanChannels = false;
                selectChannel(0);
#endif
                pairingCommandId.clear();
                pairingSession.arm(millis());
                pairingRequiresNetwork = wifiTransport.authenticated();
                reportPairingStatus("waiting_for_factory_message_1");
            } else if (!handled && serialCommand == "pairing_cancel") {
                handled = true;
                cancelPairing("cancelled_by_operator");
            } else if (!handled && serialCommand == "pairing_status") {
                handled = true;
                reportPairingStatus();
            } else if (!handled && serialCommand.startsWith("pairing_probe_b ")) {
                handled = handlePairingProbe(serialCommand);
            } else if (!handled && serialCommand.startsWith("pairing_offset_hz ")) {
                handled = true;
                const long offset = serialCommand.substring(18).toInt();
                if (
                    offset < -rainpoint::kMaxPairingFrequencyOffsetHz ||
                    offset > rainpoint::kMaxPairingFrequencyOffsetHz
                ) {
                    emitLine(
                        "{\"type\":\"command_error\","
                        "\"error\":\"pairing_offset_out_of_range\"}"
                    );
                } else if (
                    pairingSession.state() ==
                    rainpoint::PairingSessionState::Armed
                ) {
                    emitLine(
                        "{\"type\":\"command_error\","
                        "\"error\":\"pairing_is_armed\"}"
                    );
                } else {
                    pairingFrequencyOffsetHz = offset;
                    reportPairingStatus("frequency_offset_updated");
                }
            } else if (!handled && serialCommand.startsWith("pairing_power_dbm ")) {
                handled = true;
                const long requested = serialCommand.substring(18).toInt();
                if (!rainpoint::validPairingPowerDbm(requested)) {
                    emitLine(
                        "{\"type\":\"command_error\","
                        "\"error\":\"pairing_power_invalid\"}"
                    );
                } else if (
                    pairingSession.state() ==
                    rainpoint::PairingSessionState::Armed
                ) {
                    emitLine(
                        "{\"type\":\"command_error\","
                        "\"error\":\"pairing_is_armed\"}"
                    );
                } else {
                    pairingPowerDbm = static_cast<std::int8_t>(requested);
                    reportPairingStatus("power_updated");
                }
            } else if (!handled && serialCommand.startsWith("pairing_clock_local ")) {
                handled = true;
                if (
                    pairingSession.state() ==
                    rainpoint::PairingSessionState::Armed
                ) {
                    emitLine(
                        "{\"type\":\"command_error\","
                        "\"error\":\"pairing_is_armed\"}"
                    );
                } else {
                    rainpoint::PairingLocalDateTime parsed{};
                    if (!parsePairingLocalDateTime(
                            serialCommand.substring(20), parsed
                        )) {
                        emitLine(
                            "{\"type\":\"command_error\","
                            "\"error\":\"pairing_clock_invalid\"}"
                        );
                    } else {
                        pairingLocalDateTime = parsed;
                        pairingLocalDateTimeSet = true;
                        pairingLocalDateTimeSetAtMs = millis();
                        reportPairingStatus("local_clock_updated");
                    }
                }
            } else if (!handled && serialCommand == "pairing_invert on") {
                handled = true;
                if (pairingSession.state() ==
                    rainpoint::PairingSessionState::Armed) {
                    emitLine(
                        "{\"type\":\"command_error\","
                        "\"error\":\"pairing_is_armed\"}"
                    );
                } else {
                    pairingInvert = true;
                    reportPairingStatus("polarity_updated");
                }
            } else if (!handled && serialCommand == "pairing_invert off") {
                handled = true;
                if (pairingSession.state() ==
                    rainpoint::PairingSessionState::Armed) {
                    emitLine(
                        "{\"type\":\"command_error\","
                        "\"error\":\"pairing_is_armed\"}"
                    );
                } else {
                    pairingInvert = false;
                    reportPairingStatus("polarity_updated");
                }
            }
#if RAINPOINT_RADIO_COUNT == 1
            if (!handled && serialCommand == "0") {
                handled = true;
                scanChannels = false;
                selectChannel(0);
            } else if (!handled && serialCommand == "1") {
                handled = true;
                scanChannels = false;
                selectChannel(11);
            } else if (
                !handled && (serialCommand == "s" || serialCommand == "S")
            ) {
                handled = true;
                scanChannels = true;
                lastChannelChange = millis();
            }
#endif
#endif
            if (
                !handled &&
                !wifiTransport.handleProvisioningCommand(serialCommand)
            ) {
                emitLine(
                    String("{\"type\":\"command_error\",\"node_id\":\"") +
                    wifiTransport.nodeId() + "\",\"error\":\"unknown_command\"}"
                );
            }
            serialCommand = "";
        } else if (serialCommand.length() < 512) {
            serialCommand += value;
        } else {
            serialCommand = "";
            emitLine(
                String("{\"type\":\"command_error\",\"node_id\":\"") +
                wifiTransport.nodeId() + "\",\"error\":\"command_too_long\"}"
            );
        }
    }
}

#if RAINPOINT_ROUTINE_ACK_CANDIDATE == 1
void reportRoutineAckStatus(
    const char* state,
    const rainpoint::RoutineAckAuthorization& authorization,
    const std::array<std::uint8_t, rainpoint::kFrameBytes>* frame
) {
    String line = "{\"type\":\"routine_ack_status\",\"node_id\":\"";
    line += wifiTransport.nodeId();
    line += "\",\"state\":\"";
    line += state;
    line += "\",\"paired_endpoint\":\"";
    line += hexString(
        authorization.pairedEndpoint.data(),
        authorization.pairedEndpoint.size()
    );
    line += "\",\"assigned_channel\":";
    line += authorization.pairingChannel;
    line += ",\"channel_center_hz\":";
    line += static_cast<unsigned long>(
        rainpoint::routineAckCenterHz(authorization)
    );
    line += ",\"authorized_sensor_count\":";
    line += static_cast<unsigned int>(routineAckAuthorizations.activeCount());
    line += ",\"transmissions\":";
    line += routineAckTransmissions;
    line += ",\"failures\":";
    line += routineAckFailures;
    if (frame != nullptr) {
        line += ",\"frame\":\"";
        line += hexString(frame->data(), frame->size());
        line += '"';
    }
    line += '}';
    emitLine(line);
}

void reportHtv405RoutineAckStatus(
    const char* state,
    const rainpoint::Htv405RoutineAckAuthorization& authorization,
    const std::array<std::uint8_t, rainpoint::kFrameBytes>* frame
) {
    String line = "{\"type\":\"htv405_routine_ack_status\",\"node_id\":\"";
    line += wifiTransport.nodeId();
    line += "\",\"state\":\"";
    line += state;
    line += "\",\"valve_endpoint\":\"";
    line += hexString(
        authorization.valveEndpoint.data(),
        authorization.valveEndpoint.size()
    );
    line += "\",\"channel_center_hz\":";
    line += static_cast<unsigned long>(
        rainpoint::routineHtv405AckCenterHz(authorization)
    );
    line += ",\"authorized_valve_count\":";
    line += static_cast<unsigned int>(
        htv405RoutineAckAuthorizations.activeCount()
    );
    line += ",\"transmissions\":";
    line += htv405RoutineAckTransmissions;
    line += ",\"failures\":";
    line += htv405RoutineAckFailures;
    if (frame != nullptr) {
        line += ",\"frame\":\"";
        line += hexString(frame->data(), frame->size());
        line += '"';
    }
    line += '}';
    emitLine(line);
}

void reportSensorRecoveryStatus(
    const char* state,
    rainpoint::PairingTrigger trigger,
    const rainpoint::RoutineAckAuthorization& authorization,
    const std::array<std::uint8_t, rainpoint::kFrameBytes>* frame
) {
    String line = "{\"type\":\"sensor_recovery_status\",\"node_id\":\"";
    line += wifiTransport.nodeId();
    line += "\",\"state\":\"";
    line += state;
    line += "\",\"phase\":\"";
    line += rainpoint::pairingTriggerName(trigger);
    line += "\",\"paired_endpoint\":\"";
    line += hexString(
        authorization.pairedEndpoint.data(),
        authorization.pairedEndpoint.size()
    );
    line += "\",\"transmissions\":";
    line += sensorRecoveryTransmissions;
    line += ",\"failures\":";
    line += sensorRecoveryFailures;
    line += ",\"completions\":";
    line += sensorRecoveryCompletions;
    if (frame != nullptr) {
        line += ",\"frame\":\"";
        line += hexString(frame->data(), frame->size());
        line += '"';
    }
    line += '}';
    emitLine(line);
}

void authorizeRoutineAckFromCompletedPairing() {
    rainpoint::RoutineAckAuthorization authorization{
        activePairingProfile.pairedEndpoint,
        activePairingProfile.sensorRoute,
        activePairingProfile.companionEndpoint,
        pairingAssignedChannel,
        pairingFrequencyOffsetHz,
        pairingPowerDbm,
        pairingInvert,
        true,
    };
    const bool authorized = routineAckAuthorizations.authorize(authorization);
    reportRoutineAckStatus(
        authorized ? "authorized_until_reboot" : "authorization_failed",
        authorization
    );
}
#endif

#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
bool activeValvePairingArmed() {
    return currentPairingState() == rainpoint::PairingSessionState::Armed;
}

std::size_t activeValvePairingCompletedSteps() {
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
    if (valvePairingHtv145) {
        return htv145PairingSession.completedSteps();
    }
#endif
    return valvePairingSession.completedSteps();
}

const rainpoint::Htv405PairingStep* claimActiveValvePairingReply(
    const std::array<std::uint8_t, rainpoint::kFrameBytes>& frame,
    std::uint32_t nowMs
) {
    return valvePairingSession.claimReply(frame, nowMs);
}

std::uint8_t activeValvePairingReplyCounterOffset() {
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
    if (valvePairingHtv145) {
        return 0;
    }
#endif
    return valvePairingSession.replyCounterOffset();
}

bool activeValvePairingIsSelector2ConfigurationStep(
    std::size_t replyStep
) {
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
    if (valvePairingHtv145) {
        return false;
    }
#endif
    return valvePairingSession.isSelector2ConfigurationStep(replyStep);
}

void markActiveValvePairingSelector2ConfigurationTransmitted(
    std::uint8_t sequence
) {
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
    if (valvePairingHtv145) {
        return;
    }
#endif
    valvePairingSession.markSelector2ConfigurationTransmitted(sequence);
}

std::uint32_t activeValvePairingReplyStartDelayOverrideUs() {
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
    if (valvePairingHtv145) {
        return 0;
    }
#endif
    return valvePairingSession.replyStartDelayOverrideUs();
}

bool activeValvePairingReplyMarkerRepeat() {
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
    if (valvePairingHtv145) {
        return false;
    }
#endif
    return valvePairingSession.replyMarkerRepeat();
}

bool finishActiveValvePairingReply(bool success, std::uint32_t nowMs) {
    return valvePairingSession.finishReply(success, nowMs);
}

void tickActiveValvePairing(std::uint32_t nowMs) {
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
    if (valvePairingHtv145) {
        htv145PairingSession.tick(nowMs);
        return;
    }
#endif
    valvePairingSession.tick(nowMs);
}
#endif

#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1 && RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
void processHtv145PairingFrame(
    const std::array<std::uint8_t, rainpoint::kFrameBytes>& frame,
    const rainpoint::RadioPacket& packet,
    rainpoint::Cc1101& radio
) {
    const std::size_t beforeStep = htv145PairingSession.completedSteps();
    const rainpoint::htv145::PairingStep* step =
        htv145PairingSession.claimReply(frame, millis());
    if (step != nullptr) {
        auto replyDateTime = pairingLocalDateTime;
        const bool pairingClockValid =
            rainpoint::advancePairingLocalDateTime(
                replyDateTime,
                (millis() - pairingLocalDateTimeSetAtMs) / 1'000
            );
        std::array<std::uint8_t, rainpoint::kFrameBytes> replyFrame{};
        const std::size_t replyStep = static_cast<std::size_t>(
            step - activeHtv145PairingProfile.steps.data()
        );
        const bool built = pairingClockValid &&
            rainpoint::htv145::buildReply(
                activeHtv145PairingProfile,
                replyStep,
                replyDateTime,
                replyFrame
            );
        const std::uint32_t transmitCenterHz =
            static_cast<std::uint32_t>(
                static_cast<std::int64_t>(step->channelCenterHz) +
                pairingFrequencyOffsetHz
            );
        bool sent = built && radio.transmitAsync(
            replyFrame,
            transmitCenterHz,
            rainpoint::kPairingWakeSymbols,
            pairingInvert,
            rainpoint::pairingPaTableValue(pairingPowerDbm),
            step->deviationRegister,
            packet.receivedAtMicros +
                rainpoint::htv145::replyStartDelayUs(replyStep),
            0,
            0,
            0,
            false,
#if RAINPOINT_HTV145_POST_FRAME_TAIL_CANDIDATE == 1
            replyStep == 0
                ? rainpoint::htv145::kStage0PostFrameLowHoldAdjustmentUs
                : 0
#else
            0
#endif
        );
        if (sent && replyStep == 1) {
            std::array<std::uint8_t, rainpoint::kFrameBytes>
                configurationFrame{};
            sent = rainpoint::htv145::buildConfigurationReply(
                activeHtv145PairingProfile, configurationFrame
            ) && radio.transmitAsync(
                configurationFrame,
                transmitCenterHz,
                rainpoint::htv145::kConfigurationWakeSymbols,
                pairingInvert,
                rainpoint::pairingPaTableValue(pairingPowerDbm),
                step->deviationRegister,
                packet.receivedAtMicros +
                    rainpoint::htv145::kConfigurationReplyStartDelayUs
            );
            // The configuration response is sent on the same routine carrier.
            sent = sent && radio.setReceiveFrequency(transmitCenterHz);
        }
        htv145PairingSession.finishReply(sent, millis());
        reportPairingStatus(sent ? "reply_transmitted" : "transmit_failed");
    } else if (htv145PairingSession.completedSteps() > beforeStep) {
        if (beforeStep == 2) {
            radio.restoreReceiveChannel(kHcs026TelemetryChannel);
        }
        reportPairingStatus("no_reply_step_observed");
    }
    if (htv145PairingSession.state() !=
        rainpoint::PairingSessionState::Armed) {
        pairingRequiresNetwork = false;
        restoreScanningAfterPairing();
    }
}
#endif

void pollRadio(const char* name, rainpoint::Cc1101& radio) {
    rainpoint::RadioPacket packet;
    const bool deferReceiveRecovery = &radio == &primaryRadio &&
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
        valvePairingActive &&
        activeValvePairingArmed();
#else
        false;
#endif
    if (!radio.poll(packet, !deferReceiveRecovery)) {
        return;
    }
    const auto frame = rainpoint::reconstructFrame(packet.payload);
    bool valveProbeTransmitted = false;
#if RAINPOINT_SUPERVISED_HTV405_CONTROL == 1
    if (&radio == &primaryRadio) {
        valveProbeTransmitted = observeValveProbeFrame(
            frame, radio, packet.receivedAtMicros
        );
    }
#endif
#if RAINPOINT_HTV145_TX_CANDIDATE == 1
    if (&radio == &primaryRadio) {
        observeHtv145CandidateFrame(frame);
    }
#endif
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
    if (&radio == &primaryRadio && valvePairingActive &&
        activeValvePairingArmed()) {
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
        if (valvePairingHtv145) {
            processHtv145PairingFrame(frame, packet, radio);
        } else
#endif
        {
        if (pairingAutomaticDiscovery && !pairingFactoryAdopted) {
            std::array<std::uint8_t, 4> factoryEndpoint{};
            if (!rainpoint::htv405FactoryAnnouncement(
                    frame, factoryEndpoint
                )) {
                printPacket(name, frame, packet, radio);
                return;
            }
            if (!rainpoint::adoptAutomaticHtv405FactoryEndpoint(
                    factoryEndpoint, activeValvePairingProfile
                )) {
                cancelPairing("automatic_valve_profile_build_failed");
                printPacket(name, frame, packet, radio);
                return;
            }
            pairingFactoryAdopted = true;
            reportPairingStatus("factory_identity_adopted");
        }
        const std::size_t beforeStep = activeValvePairingCompletedSteps();
        const rainpoint::Htv405PairingStep* step =
            claimActiveValvePairingReply(frame, millis());
        if (step != nullptr) {
            auto replyDateTime = pairingLocalDateTime;
            const bool pairingClockValid =
                rainpoint::advancePairingLocalDateTime(
                    replyDateTime,
                    (millis() - pairingLocalDateTimeSetAtMs) / 1'000
                );
            std::array<std::uint8_t, rainpoint::kFrameBytes> replyFrame{};
            const std::size_t replyStep = static_cast<std::size_t>(
                step - activeValvePairingProfile.steps.data()
            );
            const bool built = pairingClockValid &&
                rainpoint::buildHtv405PairingReply(
                    activeValvePairingProfile,
                    replyStep,
                    replyDateTime,
                    replyFrame,
                    activeValvePairingReplyCounterOffset()
                );
            if (built && activeValvePairingReplyMarkerRepeat()) {
                replyFrame[14] = static_cast<std::uint8_t>(
                    replyFrame[14] | 0x80U
                );
                rainpoint::writeTrailer(
                    replyFrame, step->trailerResidual
                );
            }
            const std::uint32_t replyStartDelayOverrideUs =
                activeValvePairingReplyStartDelayOverrideUs();
            const std::uint32_t replyStartDelayUs =
                replyStartDelayOverrideUs != 0
                ? replyStartDelayOverrideUs
                : rainpoint::htv405PairingReplyStartDelayUs(replyStep);
            const std::int64_t adjustedFrequency =
                static_cast<std::int64_t>(step->channelCenterHz) +
                pairingFrequencyOffsetHz;
            bool sent = built && radio.transmitAsync(
                replyFrame,
                static_cast<std::uint32_t>(adjustedFrequency),
                rainpoint::kPairingWakeSymbols,
                pairingInvert,
                rainpoint::pairingPaTableValue(pairingPowerDbm),
                step->deviationRegister,
                packet.receivedAtMicros + replyStartDelayUs
            );
            if (sent && activeValvePairingIsSelector2ConfigurationStep(
                    replyStep
                )) {
                std::array<std::uint8_t, rainpoint::kFrameBytes>
                    configurationFrame{};
                // The long-wake controller configuration shares the shifted
                // transaction counter of the immediate 82/41 acknowledgement.
                // Retain that exact sequence in diagnostics. Live trials on
                // 2026-08-26 ruled out treating it as a watering-command
                // counter: fresh pairing independently initialized that
                // counter at 1 and received an authenticated response.
                sent = rainpoint::buildHtv405Selector2ConfigurationReply(
                    activeValvePairingProfile,
                    configurationFrame,
                    activeValvePairingReplyCounterOffset()
                ) && radio.transmitAsync(
                    configurationFrame,
                    static_cast<std::uint32_t>(adjustedFrequency),
                    rainpoint::kHtv405Selector2ConfigurationWakeSymbols,
                    pairingInvert,
                    rainpoint::pairingPaTableValue(pairingPowerDbm),
                    step->deviationRegister,
                    packet.receivedAtMicros +
                        rainpoint::
                            kHtv405Selector2ConfigurationReplyStartDelayUs
                );
                if (sent) {
                    markActiveValvePairingSelector2ConfigurationTransmitted(
                        configurationFrame[13] & 0x7fU
                    );
                }
            }
            finishActiveValvePairingReply(sent, millis());
            reportPairingStatus(sent ? "reply_transmitted" : "transmit_failed");
        } else if (activeValvePairingCompletedSteps() > beforeStep) {
            reportPairingStatus("no_reply_step_observed");
        }
        if (!activeValvePairingArmed()) {
            pairingRequiresNetwork = false;
            restoreScanningAfterPairing();
        }
        }
    }
#endif
    if (&radio == &primaryRadio &&
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
        !valvePairingActive &&
#endif
        pairingSession.state() == rainpoint::PairingSessionState::Armed) {
        const auto pairingStateBeforeFrame = pairingSession.state();
        if (pairingAutomaticDiscovery && !pairingFactoryAdopted) {
            std::array<std::uint8_t, 4> factoryEndpoint{};
            if (!rainpoint::hcs026FactoryAnnouncement(
                frame, factoryEndpoint
            )) {
                printPacket(name, frame, packet, radio);
                return;
            }
            if (!rainpoint::buildAutomaticHcs026Profile(
                factoryEndpoint,
                activePairingProfile.sensorRoute,
                activePairingProfile.companionEndpoint,
                pairingAssignedChannel,
                activePairingProfile
            )) {
                cancelPairing("automatic_profile_build_failed");
                printPacket(name, frame, packet, radio);
                return;
            }
            pairingFactoryAdopted = true;
            reportPairingStatus("factory_identity_adopted");
        }
        const rainpoint::PairingReplyStep* step =
            pairingSession.claimReply(frame, millis());
        if (step != nullptr) {
            const std::int64_t adjustedFrequency =
                static_cast<std::int64_t>(step->channelCenterHz) +
                pairingFrequencyOffsetHz;
            delay(activePairingProfile.replyDelayMs);
            auto replyFrame = step->frame;
            auto replyDateTime = pairingLocalDateTime;
            const bool pairingClockValid =
                rainpoint::advancePairingLocalDateTime(
                    replyDateTime,
                    (millis() - pairingLocalDateTimeSetAtMs) / 1'000
                );
            if (step->trigger == rainpoint::PairingTrigger::FactoryAnnouncement &&
                (!pairingClockValid || !rainpoint::applyPairingLocalDateTime(
                    replyFrame, replyDateTime
                ))) {
                pairingSession.finishReply(false, millis());
                reportPairingStatus("invalid_local_clock");
                restoreScanningAfterPairing();
                printPacket(name, frame, packet, radio);
                return;
            }
            const bool sent = radio.transmitAsync(
                replyFrame,
                static_cast<std::uint32_t>(adjustedFrequency),
                step->wakeSymbols,
                pairingInvert,
                rainpoint::pairingPaTableValue(pairingPowerDbm)
            );
            pairingSession.finishReply(sent, millis());
            reportPairingStatus(sent ? "reply_transmitted" : "transmit_failed");
            if (pairingSession.state() !=
                rainpoint::PairingSessionState::Armed) {
                pairingRequiresNetwork = false;
                restoreScanningAfterPairing();
            }
        }
#if RAINPOINT_ROUTINE_ACK_CANDIDATE == 1
        if (pairingStateBeforeFrame == rainpoint::PairingSessionState::Armed &&
            pairingSession.state() ==
                rainpoint::PairingSessionState::Completed) {
            authorizeRoutineAckFromCompletedPairing();
        }
#endif
    }
#if RAINPOINT_ROUTINE_ACK_CANDIDATE == 1
    if (&radio == &primaryRadio &&
        currentPairingState() != rainpoint::PairingSessionState::Armed) {
        rainpoint::PairingTrigger recoveryTrigger{};
        const auto* recoveryAuthorization =
            rainpoint::authorizedHcs026ControlFrame(
                frame, routineAckAuthorizations, recoveryTrigger
            );
        if (recoveryAuthorization != nullptr) {
            if (recoveryTrigger == rainpoint::PairingTrigger::PairedMessage3) {
                ++sensorRecoveryCompletions;
                reportSensorRecoveryStatus(
                    "completed", recoveryTrigger, *recoveryAuthorization
                );
            } else {
                std::array<std::uint8_t, rainpoint::kFrameBytes> reply{};
                const std::uint32_t receivedAtMs = millis();
                const bool built = rainpoint::buildKnownHcs026RecoveryReply(
                    recoveryTrigger, *recoveryAuthorization, reply
                );
                if (built) {
                    delay(rainpoint::kKnownSensorRecoveryDelayMs);
                    const bool beforeDeadline = millis() - receivedAtMs <
                        rainpoint::kKnownSensorRecoveryDeadlineMs;
                    const bool sent = beforeDeadline && radio.transmitAsync(
                        reply,
                        rainpoint::routineAckCenterHz(*recoveryAuthorization),
                        rainpoint::kPairingWakeSymbols,
                        recoveryAuthorization->invert,
                        rainpoint::pairingPaTableValue(
                            recoveryAuthorization->powerDbm
                        )
                    );
                    if (sent) {
                        ++sensorRecoveryTransmissions;
                    } else {
                        ++sensorRecoveryFailures;
                    }
                    reportSensorRecoveryStatus(
                        sent ? "reply_transmitted" :
                            (beforeDeadline ? "transmit_failed" :
                                "deadline_missed"),
                        recoveryTrigger,
                        *recoveryAuthorization,
                        &reply
                    );
                }
            }
        }
        const auto* authorization = routineAckAuthorizations.match(frame);
        if (authorization != nullptr) {
            std::array<std::uint8_t, rainpoint::kFrameBytes> reply{};
            const std::uint32_t receivedAtMs = millis();
            const bool built = rainpoint::buildRoutineHcs026Acknowledgement(
                frame, *authorization, reply
            );
            if (built) {
                delay(rainpoint::kRoutineAckDelayMs);
                const bool beforeDeadline =
                    millis() - receivedAtMs < rainpoint::kRoutineAckDeadlineMs;
                const bool sent = beforeDeadline && radio.transmitAsync(
                    reply,
                    rainpoint::routineAckCenterHz(*authorization),
                    rainpoint::kRoutineAckWakeSymbols,
                    authorization->invert,
                    rainpoint::pairingPaTableValue(authorization->powerDbm)
                );
                if (sent) {
                    ++routineAckTransmissions;
                } else {
                    ++routineAckFailures;
                }
                reportRoutineAckStatus(
                    sent ? "transmitted" :
                        (beforeDeadline ? "transmit_failed" : "deadline_missed"),
                    *authorization,
                    &reply
                );
            }
        }
        const auto* valveAuthorization =
            htv405RoutineAckAuthorizations.match(frame);
        if (valveAuthorization != nullptr && !valveProbeTransmitted) {
            std::array<std::uint8_t, rainpoint::kFrameBytes> reply{};
            const bool built = rainpoint::buildRoutineHtv405Acknowledgement(
                frame,
                *valveAuthorization,
                rainpoint::kHtv405RoutineAckTrailerResidual,
                reply
            );
            const bool sent = built && radio.transmitAsync(
                reply,
                rainpoint::routineHtv405AckCenterHz(*valveAuthorization),
                rainpoint::kHtv405RoutineAckWakeSymbols,
                valveAuthorization->invert,
                rainpoint::pairingPaTableValue(valveAuthorization->powerDbm),
                rainpoint::kOrdinaryDeviationRegister,
                packet.receivedAtMicros +
                    rainpoint::kHtv405OrdinaryReplyStartDelayUs
            );
            if (sent) {
                ++htv405RoutineAckTransmissions;
            } else {
                ++htv405RoutineAckFailures;
            }
            reportHtv405RoutineAckStatus(
                sent ? "transmitted" :
                    (built ? "transmit_failed" : "build_failed"),
                *valveAuthorization,
                &reply
            );
        }
    }
#endif
    if (deferReceiveRecovery) {
        // A successful reply already restored RX; repeating recovery here is
        // harmless and keeps non-matching/no-reply valve frames on the normal
        // receive path without delaying the time-critical transmit start.
        radio.recoverReceive();
    }
    printPacket(name, frame, packet, radio);
}

bool beginRadio(
    const char* name,
    rainpoint::Cc1101& radio,
    std::uint8_t channel
) {
    if (!radio.begin(channel)) {
        emitLine(
            String("{\"type\":\"radio_error\",\"node_id\":\"") +
            wifiTransport.nodeId() + "\",\"radio\":\"" + name +
            "\",\"channel\":" + channel +
            ",\"error\":\"cc1101_not_found\"}"
        );
        return false;
    }
    emitLine(
        String("{\"type\":\"radio_ready\",\"node_id\":\"") +
        wifiTransport.nodeId() + "\",\"radio\":\"" + name +
        "\",\"channel\":" + channel + ",\"part\":" +
        radio.partNumber() + ",\"version\":" + radio.version() + "}"
    );
    return true;
}

}  // namespace

void setup() {
    Serial.begin(115200);
    delay(250);
#if RAINPOINT_OTA_CANDIDATE == 1
    otaTrial.begin();
#endif
    pinMode(RAINPOINT_STATUS_LED_PIN, OUTPUT);
    setIdentifyLed(false);
    wifiTransport.begin();
    emitLine(
        String("{\"type\":\"boot\",\"node_id\":\"") +
        wifiTransport.nodeId() +
#if RAINPOINT_SUPERVISED_HTV405_CONTROL == 1
        "\",\"mode\":\"radio_node\",\"local_tx_controls\":true,"
#else
        "\",\"mode\":\"radio_node\",\"local_tx_controls\":false,"
#endif
        "\"pairing_tx_available\":true,"
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
        "\"valve_pairing_tx_candidate\":true,"
        "\"htv405_auto_identity_pairing\":true,"
#else
        "\"valve_pairing_tx_candidate\":false,"
        "\"htv405_auto_identity_pairing\":false,"
#endif
        "\"valve_control_available\":false,"
#if RAINPOINT_HTV145_TX_CANDIDATE == 1
        "\"htv145_control_candidate\":true,"
#else
        "\"htv145_control_candidate\":false,"
#endif
#if RAINPOINT_SUPERVISED_HTV405_CONTROL == 1
        "\"valve_control_probe\":true,"
#else
        "\"valve_control_probe\":false,"
#endif
        "\"tx_armed\":false,"
#if RAINPOINT_ROUTINE_ACK_CANDIDATE == 1
        "\"routine_ack_candidate\":true,"
        "\"routine_ack_authorization_persistent\":false,"
        "\"htv405_routine_ack_available\":true,"
#else
        "\"routine_ack_candidate\":false,"
        "\"htv405_routine_ack_available\":false,"
#endif
#if RAINPOINT_OTA_CANDIDATE == 1
        "\"ota_trial\":true,"
#else
        "\"ota_trial\":false,"
#endif
        "\"wifi_configured\":" +
        (wifiTransport.configured() ? "true" : "false") +
        ",\"radio_count\":" + RAINPOINT_RADIO_COUNT + "}"
    );

    // Keep every device deselected before the shared SPI bus is started.
    pinMode(kPrimaryChipSelectPin, OUTPUT);
    digitalWrite(kPrimaryChipSelectPin, HIGH);
#if RAINPOINT_RADIO_COUNT == 2
    pinMode(kDiagnosticChipSelectPin, OUTPUT);
    digitalWrite(kDiagnosticChipSelectPin, HIGH);
#endif
    radioSpi.begin(kSpiSckPin, kSpiMisoPin, kSpiMosiPin);

    bool ready = beginRadio("primary", primaryRadio, 0);
#if RAINPOINT_RADIO_COUNT == 2
    ready = beginRadio("diagnostic", diagnosticRadio, 11) && ready;
#endif
    if (!ready) {
        emitLine(
            String("{\"type\":\"fatal\",\"node_id\":\"") +
            wifiTransport.nodeId() +
            "\",\"error\":\"radio_initialization_failed\"}"
        );
        while (true) {
            delay(1'000);
        }
    }
#if RAINPOINT_OTA_CANDIDATE == 1
    radiosHealthy = ready;
#endif
#if RAINPOINT_RADIO_COUNT == 1
    lastChannelChange = millis();
#endif
    reportHealth();
    lastHealthReport = millis();
}

void loop() {
    const std::uint32_t loopAt = millis();
    if (lastLoopAt != 0) {
        maximumLoopGapMs = max(maximumLoopGapMs, loopAt - lastLoopAt);
    }
    lastLoopAt = loopAt;
    const bool gatewayWasAuthenticated = wifiTransport.authenticated();
    wifiTransport.poll();
    const bool gatewayReconnected =
        !gatewayWasAuthenticated && wifiTransport.authenticated();
#if RAINPOINT_OTA_CANDIDATE == 1
    otaTrial.confirmHealthy(wifiTransport.authenticated(), radiosHealthy);
#endif
    if (pairingRequiresNetwork && !wifiTransport.authenticated()) {
        cancelPairing("gateway_connection_lost");
    }
#if RAINPOINT_HTV145_TX_CANDIDATE == 1
    if (htv145ControlCandidate.pending && !wifiTransport.authenticated()) {
        failHtv145Candidate("gateway_connection_lost_counter_unsynchronized");
    }
#endif
    pollRfMaintenance();
    handleNetworkCommand();
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
    // Pairing status emitted while the gateway was down could not be
    // delivered. Replay the authoritative node state on reconnection so the
    // controller can distinguish a completed transcript from a white-LED-only
    // association attempt.
    if (gatewayReconnected && valvePairingActive) {
        reportPairingStatus("gateway_reconnected");
    }
#endif
    if (gatewayReconnected) {
        reportRfMaintenanceStatus("gateway_reconnected");
    }
    if (nodeRestartPending) {
        delay(250);
        ESP.restart();
        return;
    }
#if RAINPOINT_OTA_CANDIDATE == 1
    // Restart only after unwinding the authenticated network-command handler.
    // A physical 0.9 -> 0.10 trial reached verified_sha256 but remained inside
    // that handler until an external reset. Deferring the partition switch to
    // the top-level loop keeps the command transport out of the restart path.
    if (otaTrial.restartPending()) {
        delay(250);
        ESP.restart();
        return;
    }
#endif
    pollIdentify();
    handleSerialCommand();
#if RAINPOINT_RADIO_COUNT == 1
    pollRadio("primary", primaryRadio);
#if RAINPOINT_SUPERVISED_HTV405_CONTROL == 1
    pollValveProbeResponseListener();
#endif

    if (scanChannels) {
#if RAINPOINT_ROUTINE_ACK_CANDIDATE == 1
        // Locally enrolled HCS026 sensors return to telemetry channel 0 after
        // their gateway assigns reply selector 4 or 5. Missing one report
        // batch can leave a battery sensor dormant indefinitely. An ACK owner
        // therefore stays on the proven telemetry channel and hops only for
        // its bounded reply; nodes without assignments continue broad scans.
        if (routineAckAuthorizations.activeCount() > 0 &&
            primaryRadio.channel() != kHcs026TelemetryChannel) {
            selectChannel(kHcs026TelemetryChannel);
        } else if (routineAckAuthorizations.activeCount() == 0 &&
            millis() - lastChannelChange >= kScanDwellMs) {
            selectChannel(primaryRadio.channel() == 0 ? 11 : 0);
        }
#else
        if (millis() - lastChannelChange >= kScanDwellMs) {
            selectChannel(primaryRadio.channel() == 0 ? 11 : 0);
        }
#endif
    }
#else
    pollRadio("primary", primaryRadio);
    pollRadio("diagnostic", diagnosticRadio);
#endif
#if RAINPOINT_HTV145_TX_CANDIDATE == 1
    // Drain a matching response before deciding whether the bounded command
    // burst needs its next byte-identical RF attempt.
    pollHtv145Candidate();
#endif
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
    if (valvePairingActive) {
        tickActiveValvePairing(millis());
    } else
#endif
    {
        pairingSession.tick(millis());
    }
    if (currentPairingState() != reportedPairingState) {
        if (currentPairingState() != rainpoint::PairingSessionState::Armed) {
            pairingRequiresNetwork = false;
            restoreScanningAfterPairing();
        }
        reportPairingStatus("state_changed");
    }
    if (millis() - lastHealthReport >= kHealthIntervalMs) {
        reportHealth();
        lastHealthReport = millis();
    }
    delay(1);
}
