#pragma once

#include <Arduino.h>
#include <SPI.h>

#include <array>
#include <cstddef>
#include <cstdint>

#include "rainpoint_protocol.h"

namespace rainpoint {

struct RadioPacket {
    std::array<std::uint8_t, kRadioPayloadBytes> payload{};
    std::int16_t rssiTenthsDbm = 0;
    std::int32_t frequencyOffsetHz = 0;
    std::uint8_t lqi = 0;
    std::uint32_t receivedAtMicros = 0;
};

class Cc1101 {
public:
    Cc1101(SPIClass& spi, int chipSelectPin, int misoPin, int dataPin);

    bool begin(std::uint8_t initialChannel = 0);
    bool enterIdle();
    bool enterReceive();
    bool setChannel(std::uint8_t channel);
    bool setReceiveFrequency(std::uint32_t centerFrequencyHz);
    bool restoreReceiveChannel(std::uint8_t channel);
    bool prepareTransmit();
    bool cacheTransmitFrequency(std::uint32_t centerFrequencyHz);
    bool transmitAsync(
        const std::array<std::uint8_t, kFrameBytes>& frame,
        std::uint32_t centerFrequencyHz,
        std::uint16_t wakeSymbols,
        bool invert = false,
        std::uint8_t paTableValue = 0x60,
        std::uint8_t deviationRegister = 0x45,
        std::uint32_t startAtMicros = 0,
        std::uint16_t leadingMarkSymbols = 0
    );
    bool poll(RadioPacket& packet, bool recoverAfterRead = true);
    void recoverReceive();
    std::uint8_t channel() const;
    std::uint8_t partNumber();
    std::uint8_t version();
    bool configurationValid() const;
    std::uint32_t packetCount() const;
    std::uint32_t overflowCount() const;
    std::uint32_t recoveryCount() const;

private:
    static constexpr std::uint32_t kSpiHz = 4'000'000;
    static constexpr std::size_t kMaximumCachedTransmitFrequencies = 2;

    struct CachedFrequencyCalibration {
        std::uint32_t centerFrequencyHz = 0;
        std::uint8_t frequencyCalibration3 = 0;
        std::uint8_t frequencyCalibration2 = 0;
        std::uint8_t frequencyCalibration1 = 0;
        bool valid = false;
    };

    bool reset();
    bool waitReady(std::uint32_t timeoutMicros = 2'000);
    void configureRainPoint();
    bool restoreReceiveConfiguration(std::uint8_t channel);
    void setFrequency(std::uint32_t frequencyHz);
    bool verifyConfiguration();
    bool waitForMainState(
        std::uint8_t expectedState,
        std::uint32_t timeoutMicros = 10'000
    );
    void recoverRx();
    std::uint8_t strobe(std::uint8_t command);
    void writeRegister(std::uint8_t address, std::uint8_t value);
    void writeBurst(
        std::uint8_t address,
        const std::uint8_t* data,
        std::size_t length
    );
    std::uint8_t readRegister(std::uint8_t address);
    std::uint8_t readStatus(std::uint8_t address);
    void readBurst(std::uint8_t address, std::uint8_t* data, std::size_t length);

    SPIClass& spi_;
    int chipSelectPin_;
    int misoPin_;
    int dataPin_;
    std::uint8_t channel_ = 0;
    bool configurationValid_ = false;
    bool transmitPrepared_ = false;
    std::array<
        CachedFrequencyCalibration,
        kMaximumCachedTransmitFrequencies
    > cachedTransmitFrequencies_{};
    std::uint32_t packetCount_ = 0;
    std::uint32_t overflowCount_ = 0;
    std::uint32_t recoveryCount_ = 0;
};

}  // namespace rainpoint
