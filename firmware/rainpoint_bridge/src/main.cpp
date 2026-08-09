#include <Arduino.h>
#include <SPI.h>

#include <array>
#include <cstdint>

#include "cc1101.h"
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
constexpr std::uint32_t kScanDwellMs = 500;
constexpr std::uint32_t kHealthIntervalMs = 30'000;

SPIClass radioSpi(VSPI);
rainpoint::Cc1101 primaryRadio(radioSpi, kPrimaryChipSelectPin, kSpiMisoPin);
rainpoint::WifiTransport wifiTransport;
#if RAINPOINT_RADIO_COUNT == 2
rainpoint::Cc1101 diagnosticRadio(
    radioSpi,
    kDiagnosticChipSelectPin,
    kSpiMisoPin
);
#endif
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
#if RAINPOINT_RADIO_COUNT == 1
            if (serialCommand == "0") {
                scanChannels = false;
                selectChannel(0);
            } else if (serialCommand == "1") {
                scanChannels = false;
                selectChannel(11);
            } else if (serialCommand == "s" || serialCommand == "S") {
                scanChannels = true;
                lastChannelChange = millis();
            } else
#endif
            if (!wifiTransport.handleProvisioningCommand(serialCommand)) {
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
        wifiTransport.nodeId() + "\",\"mode\":\"receive_only\","
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
    if (millis() - lastHealthReport >= kHealthIntervalMs) {
        reportHealth();
        lastHealthReport = millis();
    }
    delay(1);
}
