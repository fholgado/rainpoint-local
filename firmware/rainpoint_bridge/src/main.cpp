#include <Arduino.h>
#include <SPI.h>

#include <array>
#include <cctype>
#include <cstdint>

#include "cc1101.h"
#include "rainpoint_pairing.h"
#include "rainpoint_protocol.h"
#include "wifi_transport.h"

#if RAINPOINT_RADIO_COUNT != 1 && RAINPOINT_RADIO_COUNT != 2
#error "RAINPOINT_RADIO_COUNT must be 1 or 2"
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
constexpr std::uint32_t kHealthIntervalMs = 30'000;

SPIClass radioSpi(VSPI);
rainpoint::Cc1101 primaryRadio(
    radioSpi,
    kPrimaryChipSelectPin,
    kSpiMisoPin,
    kPrimaryDataPin
);
rainpoint::WifiTransport wifiTransport;
#if RAINPOINT_RADIO_COUNT == 2
rainpoint::Cc1101 diagnosticRadio(
    radioSpi,
    kDiagnosticChipSelectPin,
    kSpiMisoPin,
    kDiagnosticDataPin
);
#endif
rainpoint::SensorBPairingSession pairingSession;
rainpoint::PairingSessionState reportedPairingState =
    rainpoint::PairingSessionState::Disarmed;
bool pairingInvert = false;
std::int32_t pairingFrequencyOffsetHz = 0;
std::int8_t pairingPowerDbm = 0;
rainpoint::PairingLocalDateTime pairingLocalDateTime{};
bool pairingLocalDateTimeSet = false;
std::uint32_t pairingLocalDateTimeSetAtMs = 0;
bool pairingRequiresNetwork = false;
String pairingCommandId;
std::uint32_t lastHealthReport = 0;
String serialCommand;

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

void reportHealth() {
#if RAINPOINT_RADIO_COUNT == 1
    printRadioHealth("primary", primaryRadio);
#else
    printRadioHealth("primary", primaryRadio);
    printRadioHealth("diagnostic", diagnosticRadio);
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
        case rainpoint::PairingFailureReason::ReplyFailed:
            return "reply_failed";
        case rainpoint::PairingFailureReason::ReplyDeadlineMissed:
            return "reply_deadline_missed";
    }
    return "unknown";
}

void reportPairingStatus(const char* detail = nullptr) {
    String line;
    line.reserve(320);
    line += "{\"type\":\"pairing_tx_status\",\"node_id\":\"";
    line += wifiTransport.nodeId();
    line += "\",\"profile\":\"sensor_b\",\"factory_endpoint\":"
            "\"15a98024\",\"paired_endpoint\":\"95a98024\"";
    if (!pairingCommandId.isEmpty()) {
        line += ",\"command_id\":\"";
        line += pairingCommandId;
        line += '"';
    }
    line += ",\"state\":\"";
    line += pairingStateName(pairingSession.state());
    line += "\",\"completed_steps\":";
    line += pairingSession.completedSteps();
    line += ",\"step_count\":";
    line += rainpoint::kSensorBPairingProfile.size();
    line += ",\"awaiting_terminal_confirmation\":";
    line += pairingSession.awaitingTerminalConfirmation() ? "true" : "false";
    line += ",\"terminal_trigger\":\"paired_message_3\"";
    line += ",\"failure_reason\":\"";
    line += pairingFailureReasonName(pairingSession.failureReason());
    line += '"';
    line += ",\"tx_armed\":";
    line += pairingSession.state() == rainpoint::PairingSessionState::Armed
        ? "true"
        : "false";
    line += ",\"invert\":";
    line += pairingInvert ? "true" : "false";
    line += ",\"frequency_offset_hz\":";
    line += pairingFrequencyOffsetHz;
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
    reportedPairingState = pairingSession.state();
}

void restoreScanningAfterPairing() {
#if RAINPOINT_RADIO_COUNT == 1
    scanChannels = true;
    lastChannelChange = millis();
#endif
}

void cancelPairing(const char* detail) {
    pairingSession.cancel();
    pairingRequiresNetwork = false;
    restoreScanningAfterPairing();
    reportPairingStatus(detail);
}

bool handlePairingProbe(const String& command) {
    for (std::size_t index = 0;
         index < rainpoint::kSensorBPairingProfile.size();
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
        const auto& step = rainpoint::kSensorBPairingProfile[index];
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
            "{\"type\":\"pairing_tx_probe\",\"profile\":\"sensor_b\","
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
    if (pairingSession.state() == rainpoint::PairingSessionState::Armed) {
        reportNetworkCommandError(commandId, "pairing_is_armed");
        return;
    }
    const String profile = jsonStringField(command, "profile");
    const String factory = jsonStringField(command, "factory_endpoint");
    const String clock = jsonStringField(command, "local_clock");
    long durationSeconds = 0;
    long frequencyOffsetHz = 0;
    long powerDbm = 0;
    bool invert = false;
    rainpoint::PairingLocalDateTime parsedClock{};
    if (profile != "sensor_b" || factory != "15a98024") {
        reportNetworkCommandError(commandId, "unsupported_pairing_profile");
        return;
    }
    if (!jsonLongField(command, "duration_seconds", durationSeconds) ||
        durationSeconds < 10 || durationSeconds > 900) {
        reportNetworkCommandError(commandId, "invalid_pairing_duration");
        return;
    }
    if (!jsonLongField(command, "frequency_offset_hz", frequencyOffsetHz) ||
        frequencyOffsetHz < -rainpoint::kMaxPairingFrequencyOffsetHz ||
        frequencyOffsetHz > rainpoint::kMaxPairingFrequencyOffsetHz) {
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

    pairingCommandId = commandId;
    pairingFrequencyOffsetHz = static_cast<std::int32_t>(frequencyOffsetHz);
    pairingPowerDbm = static_cast<std::int8_t>(powerDbm);
    pairingInvert = invert;
    pairingLocalDateTime = parsedClock;
    pairingLocalDateTimeSet = true;
    pairingLocalDateTimeSetAtMs = millis();
#if RAINPOINT_RADIO_COUNT == 1
    scanChannels = false;
    selectChannel(0);
#endif
    pairingSession.arm(
        millis(), static_cast<std::uint32_t>(durationSeconds) * 1'000U
    );
    pairingRequiresNetwork = true;
    reportPairingStatus("waiting_for_factory_message_1");
}

void handleSerialCommand() {
    while (Serial.available()) {
        const char value = static_cast<char>(Serial.read());
        if (value == '\n' || value == '\r') {
            if (serialCommand.isEmpty()) {
                continue;
            }
            bool handled = false;
            if (serialCommand == "pairing_plan_b") {
                handled = true;
                for (std::size_t index = 0;
                     index < rainpoint::kSensorBPairingProfile.size();
                     ++index) {
                    const auto& step = rainpoint::kSensorBPairingProfile[index];
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
                    line += rainpoint::kPairingReplyDelayMs;
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

void pollRadio(const char* name, rainpoint::Cc1101& radio) {
    rainpoint::RadioPacket packet;
    if (!radio.poll(packet)) {
        return;
    }
    const auto frame = rainpoint::reconstructFrame(packet.payload);
    if (&radio == &primaryRadio &&
        pairingSession.state() == rainpoint::PairingSessionState::Armed) {
        const rainpoint::PairingReplyStep* step =
            pairingSession.claimReply(frame, millis());
        if (step != nullptr) {
            const std::int64_t adjustedFrequency =
                static_cast<std::int64_t>(step->channelCenterHz) +
                pairingFrequencyOffsetHz;
            delay(rainpoint::kPairingReplyDelayMs);
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
    wifiTransport.begin();
    emitLine(
        String("{\"type\":\"boot\",\"node_id\":\"") +
        wifiTransport.nodeId() + "\",\"mode\":\"pairing_tx_bench\","
        "\"pairing_tx_available\":true,\"tx_armed\":false,"
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
#if RAINPOINT_RADIO_COUNT == 1
    lastChannelChange = millis();
#endif
    reportHealth();
    lastHealthReport = millis();
}

void loop() {
    wifiTransport.poll();
    if (pairingRequiresNetwork && !wifiTransport.authenticated()) {
        cancelPairing("gateway_connection_lost");
    }
    handleNetworkCommand();
    handleSerialCommand();
#if RAINPOINT_RADIO_COUNT == 1
    pollRadio("primary", primaryRadio);

    if (scanChannels && millis() - lastChannelChange >= kScanDwellMs) {
        selectChannel(primaryRadio.channel() == 0 ? 11 : 0);
    }
#else
    pollRadio("primary", primaryRadio);
    pollRadio("diagnostic", diagnosticRadio);
#endif
    pairingSession.tick(millis());
    if (pairingSession.state() != reportedPairingState) {
        if (pairingSession.state() != rainpoint::PairingSessionState::Armed) {
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
