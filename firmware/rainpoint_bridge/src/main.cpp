#include <Arduino.h>
#include <SPI.h>

#include <array>
#include <cstdint>

#include "cc1101.h"
#include "rainpoint_protocol.h"

namespace {

constexpr int kSpiSckPin = 18;
constexpr int kSpiMisoPin = 19;
constexpr int kSpiMosiPin = 23;
constexpr int kLowerChipSelectPin = 27;
constexpr int kUpperChipSelectPin = 14;
constexpr std::uint32_t kScanDwellMs = 500;

SPIClass radioSpi(VSPI);
rainpoint::Cc1101 lowerRadio(radioSpi, kLowerChipSelectPin, kSpiMisoPin);
#if RAINPOINT_RADIO_COUNT == 2
rainpoint::Cc1101 upperRadio(radioSpi, kUpperChipSelectPin, kSpiMisoPin);
#endif

#if RAINPOINT_RADIO_COUNT == 1
bool scanChannels = true;
std::uint32_t lastChannelChange = 0;
#endif

void printHex(const std::uint8_t* data, std::size_t length) {
    constexpr char digits[] = "0123456789abcdef";
    for (std::size_t index = 0; index < length; ++index) {
        Serial.write(digits[data[index] >> 4]);
        Serial.write(digits[data[index] & 0x0f]);
    }
}
void printPacket(
    const char* radioName,
    const std::array<std::uint8_t, rainpoint::kFrameBytes>& frame,
    const rainpoint::RadioPacket& packet,
    const rainpoint::Cc1101& radio
) {
    const auto residual = rainpoint::trailerResidual(frame);
    Serial.print("{\"type\":\"rainpoint_rf\",\"radio\":\"");
    Serial.print(radioName);
    Serial.print("\",\"channel\":");
    Serial.print(radio.channel());
    Serial.print(",\"rssi_dbm\":");
    Serial.print(packet.rssiTenthsDbm / 10.0f, 1);
    Serial.print(",\"lqi\":");
    Serial.print(packet.lqi);
    Serial.print(",\"sync_valid\":");
    Serial.print(rainpoint::hasSync(frame) ? "true" : "false");
    Serial.print(",\"trailer_residual\":\"");
    if (residual < 0x1000) Serial.print('0');
    if (residual < 0x0100) Serial.print('0');
    if (residual < 0x0010) Serial.print('0');
    Serial.print(residual, HEX);
    Serial.print("\",\"trailer_valid\":");
    Serial.print(rainpoint::hasOrdinaryTrailer(frame) ? "true" : "false");
    Serial.print(",\"frame\":\"");
    printHex(frame.data(), frame.size());
    Serial.println("\"}");
}

#if RAINPOINT_RADIO_COUNT == 1
void selectChannel(std::uint8_t channel) {
    if (lowerRadio.setChannel(channel)) {
        lastChannelChange = millis();
        Serial.printf("{\"type\":\"radio_channel\",\"channel\":%u}\n", channel);
    }
}

void handleSerialCommand() {
    if (!Serial.available()) {
        return;
    }
    const char command = static_cast<char>(Serial.read());
    if (command == '0') {
        scanChannels = false;
        selectChannel(0);
    } else if (command == '1') {
        scanChannels = false;
        selectChannel(11);
    } else if (command == 's' || command == 'S') {
        scanChannels = true;
        lastChannelChange = millis();
    }
}
#endif

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
        Serial.printf(
            "{\"type\":\"radio_error\",\"radio\":\"%s\",\"channel\":%u,"
            "\"error\":\"cc1101_not_found\"}\n",
            name,
            channel
        );
        return false;
    }
    Serial.printf(
        "{\"type\":\"radio_ready\",\"radio\":\"%s\",\"channel\":%u,"
        "\"part\":%u,\"version\":%u}\n",
        name,
        channel,
        radio.partNumber(),
        radio.version()
    );
    return true;
}

}  // namespace

void setup() {
    Serial.begin(115200);
    delay(250);
    Serial.printf(
        "{\"type\":\"boot\",\"mode\":\"receive_only\",\"radio_count\":%d}\n",
        RAINPOINT_RADIO_COUNT
    );

    // Keep every device deselected before the shared SPI bus is started.
    pinMode(kLowerChipSelectPin, OUTPUT);
    digitalWrite(kLowerChipSelectPin, HIGH);
#if RAINPOINT_RADIO_COUNT == 2
    pinMode(kUpperChipSelectPin, OUTPUT);
    digitalWrite(kUpperChipSelectPin, HIGH);
#endif
    radioSpi.begin(kSpiSckPin, kSpiMisoPin, kSpiMosiPin);

    bool ready = beginRadio("lower", lowerRadio, 0);
#if RAINPOINT_RADIO_COUNT == 2
    ready = beginRadio("upper", upperRadio, 11) && ready;
#endif
    if (!ready) {
        Serial.println(
            "{\"type\":\"fatal\","
            "\"error\":\"radio_initialization_failed\"}"
        );
        while (true) {
            delay(1'000);
        }
    }
#if RAINPOINT_RADIO_COUNT == 1
    lastChannelChange = millis();
#endif
}

void loop() {
#if RAINPOINT_RADIO_COUNT == 1
    handleSerialCommand();
    pollRadio("scan", lowerRadio);

    if (scanChannels && millis() - lastChannelChange >= kScanDwellMs) {
        selectChannel(lowerRadio.channel() == 0 ? 11 : 0);
    }
#else
    pollRadio("lower", lowerRadio);
    pollRadio("upper", upperRadio);
#endif
    delay(1);
}
