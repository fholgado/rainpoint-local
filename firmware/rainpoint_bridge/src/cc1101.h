#pragma once

#include <Arduino.h>
#include <SPI.h>

#include <array>
#include <cstdint>

#include "rainpoint_protocol.h"

namespace rainpoint {

struct RadioPacket {
    std::array<std::uint8_t, kRadioPayloadBytes> payload{};
    std::int16_t rssiTenthsDbm = 0;
    std::uint8_t lqi = 0;
};

class Cc1101 {
public:
    Cc1101(SPIClass& spi, int chipSelectPin, int misoPin);

    bool begin(std::uint8_t initialChannel = 0);
    bool setChannel(std::uint8_t channel);
    bool poll(RadioPacket& packet);
    std::uint8_t channel() const;
    std::uint8_t partNumber();
    std::uint8_t version();

private:
    static constexpr std::uint32_t kSpiHz = 4'000'000;

    bool reset();
    bool waitReady(std::uint32_t timeoutMicros = 2'000);
    void configureRainPoint();
    void recoverRx();
    std::uint8_t strobe(std::uint8_t command);
    void writeRegister(std::uint8_t address, std::uint8_t value);
    std::uint8_t readStatus(std::uint8_t address);
    void readBurst(std::uint8_t address, std::uint8_t* data, std::size_t length);

    SPIClass& spi_;
    int chipSelectPin_;
    int misoPin_;
    std::uint8_t channel_ = 0;
};

}  // namespace rainpoint
