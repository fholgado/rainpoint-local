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
constexpr int kChipSelectPin = 27;
constexpr std::uint32_t kScanDwellMs = 500;

SPIClass radioSpi(VSPI);
rainpoint::Cc1101 radio(radioSpi, kChipSelectPin, kSpiMisoPin);

bool scanChannels = true;
std::uint32_t lastChannelChange = 0;

void printHex(const std::uint8_t* data, std::size_t length) {
    constexpr char digits[] = "0123456789abcdef";
    for (std::size_t index = 0; index < length; ++index) {
        Serial.write(digits[data[index] >> 4]);
        Serial.write(digits[data[index] & 0x0f]);
    }
}
void printPacket(
    const std::array<std::uint8_t, rainpoint::kFrameBytes>& frame,
    const rainpoint::RadioPacket& packet
) {
    const auto residual = rainpoint::trailerResidual(frame);
    Serial.print("{\"type\":\"rainpoint_rf\",\"channel\":");
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

void selectChannel(std::uint8_t channel) {
    if (radio.setChannel(channel)) {
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

}  // namespace

void setup() {
    Serial.begin(115200);
    delay(250);
    Serial.println("{\"type\":\"boot\",\"mode\":\"receive_only\"}");

    radioSpi.begin(kSpiSckPin, kSpiMisoPin, kSpiMosiPin, kChipSelectPin);
    if (!radio.begin()) {
        Serial.println("{\"type\":\"fatal\",\"error\":\"cc1101_not_found\"}");
        while (true) {
            delay(1'000);
        }
    }
    Serial.printf(
        "{\"type\":\"radio_ready\",\"part\":%u,\"version\":%u}\n",
        radio.partNumber(),
        radio.version()
    );
    lastChannelChange = millis();
}

void loop() {
    handleSerialCommand();

    rainpoint::RadioPacket packet;
    if (radio.poll(packet)) {
        const auto frame = rainpoint::reconstructFrame(packet.payload);
        printPacket(frame, packet);
    }

    if (scanChannels && millis() - lastChannelChange >= kScanDwellMs) {
        selectChannel(radio.channel() == 0 ? 11 : 0);
    }
    delay(1);
}
