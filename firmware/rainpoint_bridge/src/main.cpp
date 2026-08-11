#include <Arduino.h>
#include <SPI.h>

#include <array>
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
bool pairingRequiresNetwork = false;
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

void reportPairingStatus(const char* detail = nullptr) {
    String line;
    line.reserve(320);
    line += "{\"type\":\"pairing_tx_status\",\"node_id\":\"";
    line += wifiTransport.nodeId();
    line += "\",\"profile\":\"sensor_b\",\"factory_endpoint\":"
            "\"15a98024\",\"state\":\"";
    line += pairingStateName(pairingSession.state());
    line += "\",\"completed_steps\":";
    line += pairingSession.completedSteps();
    line += ",\"step_count\":";
    line += rainpoint::kSensorBPairingProfile.size();
    line += ",\"tx_armed\":";
    line += pairingSession.state() == rainpoint::PairingSessionState::Armed
        ? "true"
        : "false";
    line += ",\"invert\":";
    line += pairingInvert ? "true" : "false";
    line += ",\"frequency_offset_hz\":";
    line += pairingFrequencyOffsetHz;
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
            pairingInvert
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
#if RAINPOINT_RADIO_COUNT == 1
                scanChannels = false;
                selectChannel(0);
#endif
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
            const bool sent = radio.transmitAsync(
                step->frame,
                static_cast<std::uint32_t>(adjustedFrequency),
                step->wakeSymbols,
                pairingInvert
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
