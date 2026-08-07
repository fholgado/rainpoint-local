#include "cc1101.h"

namespace rainpoint {
namespace {

constexpr std::uint8_t kReadBurst = 0xc0;

constexpr std::uint8_t kIocfg2 = 0x00;
constexpr std::uint8_t kIocfg0 = 0x02;
constexpr std::uint8_t kFifoThreshold = 0x03;
constexpr std::uint8_t kSync1 = 0x04;
constexpr std::uint8_t kSync0 = 0x05;
constexpr std::uint8_t kPacketLength = 0x06;
constexpr std::uint8_t kPacketControl1 = 0x07;
constexpr std::uint8_t kPacketControl0 = 0x08;
constexpr std::uint8_t kChannelNumber = 0x0a;
constexpr std::uint8_t kFrequencySynthControl1 = 0x0b;
constexpr std::uint8_t kFrequencySynthControl0 = 0x0c;
constexpr std::uint8_t kFrequency2 = 0x0d;
constexpr std::uint8_t kFrequency1 = 0x0e;
constexpr std::uint8_t kFrequency0 = 0x0f;
constexpr std::uint8_t kModemConfig4 = 0x10;
constexpr std::uint8_t kModemConfig3 = 0x11;
constexpr std::uint8_t kModemConfig2 = 0x12;
constexpr std::uint8_t kModemConfig1 = 0x13;
constexpr std::uint8_t kModemConfig0 = 0x14;
constexpr std::uint8_t kDeviation = 0x15;
constexpr std::uint8_t kMainStateMachine1 = 0x17;
constexpr std::uint8_t kMainStateMachine0 = 0x18;
constexpr std::uint8_t kFrequencyOffsetCompensation = 0x19;
constexpr std::uint8_t kBitSynchronization = 0x1a;
constexpr std::uint8_t kAgcControl2 = 0x1b;
constexpr std::uint8_t kAgcControl1 = 0x1c;
constexpr std::uint8_t kAgcControl0 = 0x1d;
constexpr std::uint8_t kFrontEnd1 = 0x21;
constexpr std::uint8_t kFrontEnd0 = 0x22;
constexpr std::uint8_t kFrequencyCalibration3 = 0x23;
constexpr std::uint8_t kFrequencyCalibration2 = 0x24;
constexpr std::uint8_t kFrequencyCalibration1 = 0x25;
constexpr std::uint8_t kFrequencyCalibration0 = 0x26;
constexpr std::uint8_t kTest2 = 0x2c;
constexpr std::uint8_t kTest1 = 0x2d;
constexpr std::uint8_t kTest0 = 0x2e;

constexpr std::uint8_t kReset = 0x30;
constexpr std::uint8_t kEnterRx = 0x34;
constexpr std::uint8_t kIdle = 0x36;
constexpr std::uint8_t kFlushRx = 0x3a;
constexpr std::uint8_t kRxFifo = 0x3f;

constexpr std::uint8_t kPartNumber = 0x30;
constexpr std::uint8_t kVersion = 0x31;
constexpr std::uint8_t kRxBytes = 0x3b;

std::int16_t decodeRssi(std::uint8_t raw) {
    const auto signedRaw = raw >= 128
        ? static_cast<std::int16_t>(raw) - 256
        : static_cast<std::int16_t>(raw);
    return static_cast<std::int16_t>(signedRaw * 5 - 740);
}

}  // namespace

Cc1101::Cc1101(SPIClass& spi, int chipSelectPin, int misoPin)
    : spi_(spi), chipSelectPin_(chipSelectPin), misoPin_(misoPin) {}

bool Cc1101::waitReady(std::uint32_t timeoutMicros) {
    const auto started = micros();
    while (digitalRead(misoPin_) != LOW) {
        if (micros() - started >= timeoutMicros) {
            return false;
        }
        yield();
    }
    return true;
}

bool Cc1101::reset() {
    digitalWrite(chipSelectPin_, HIGH);
    delayMicroseconds(5);
    digitalWrite(chipSelectPin_, LOW);
    delayMicroseconds(10);
    digitalWrite(chipSelectPin_, HIGH);
    delayMicroseconds(45);

    spi_.beginTransaction(SPISettings(kSpiHz, MSBFIRST, SPI_MODE0));
    digitalWrite(chipSelectPin_, LOW);
    if (!waitReady()) {
        digitalWrite(chipSelectPin_, HIGH);
        spi_.endTransaction();
        return false;
    }
    spi_.transfer(kReset);
    const bool ready = waitReady(10'000);
    digitalWrite(chipSelectPin_, HIGH);
    spi_.endTransaction();
    delay(1);
    return ready;
}

std::uint8_t Cc1101::strobe(std::uint8_t command) {
    spi_.beginTransaction(SPISettings(kSpiHz, MSBFIRST, SPI_MODE0));
    digitalWrite(chipSelectPin_, LOW);
    if (!waitReady()) {
        digitalWrite(chipSelectPin_, HIGH);
        spi_.endTransaction();
        return 0xff;
    }
    const auto status = spi_.transfer(command);
    digitalWrite(chipSelectPin_, HIGH);
    spi_.endTransaction();
    return status;
}

void Cc1101::writeRegister(std::uint8_t address, std::uint8_t value) {
    spi_.beginTransaction(SPISettings(kSpiHz, MSBFIRST, SPI_MODE0));
    digitalWrite(chipSelectPin_, LOW);
    if (waitReady()) {
        spi_.transfer(address);
        spi_.transfer(value);
    }
    digitalWrite(chipSelectPin_, HIGH);
    spi_.endTransaction();
}

std::uint8_t Cc1101::readStatus(std::uint8_t address) {
    spi_.beginTransaction(SPISettings(kSpiHz, MSBFIRST, SPI_MODE0));
    digitalWrite(chipSelectPin_, LOW);
    std::uint8_t value = 0xff;
    if (waitReady()) {
        spi_.transfer(address | kReadBurst);
        value = spi_.transfer(0);
    }
    digitalWrite(chipSelectPin_, HIGH);
    spi_.endTransaction();
    return value;
}

void Cc1101::readBurst(
    std::uint8_t address,
    std::uint8_t* data,
    std::size_t length
) {
    spi_.beginTransaction(SPISettings(kSpiHz, MSBFIRST, SPI_MODE0));
    digitalWrite(chipSelectPin_, LOW);
    if (waitReady()) {
        spi_.transfer(address | kReadBurst);
        for (std::size_t index = 0; index < length; ++index) {
            data[index] = spi_.transfer(0);
        }
    }
    digitalWrite(chipSelectPin_, HIGH);
    spi_.endTransaction();
}

void Cc1101::configureRainPoint() {
    writeRegister(kIocfg2, 0x29);  // CHIP_RDYn; reserved for diagnostics.
    writeRegister(kIocfg0, 0x06);  // Assert on sync, deassert at packet end.
    writeRegister(kFifoThreshold, 0x47);
    writeRegister(kSync1, 0x79);
    writeRegister(kSync0, 0xf4);
    writeRegister(kPacketLength, kRadioPayloadBytes);
    writeRegister(kPacketControl1, 0x04);  // Append RSSI and LQI.
    writeRegister(kPacketControl0, 0x00);  // Fixed length, no CRC/whitening.
    writeRegister(kFrequencySynthControl1, 0x06);
    writeRegister(kFrequencySynthControl0, 0x00);
    writeRegister(kFrequency2, 0x10);
    writeRegister(kFrequency1, 0xa8);
    writeRegister(kFrequency0, 0xc3);  // 433.139862 MHz with 26 MHz crystal.
    writeRegister(kModemConfig4, 0x89);  // 203 kHz BW, DRATE_E=9.
    writeRegister(kModemConfig3, 0x93);  // 19.9852 ksymbols/s.
    writeRegister(kModemConfig2, 0x02);  // 2-FSK, exact 16-bit sync.
    writeRegister(kModemConfig1, 0x21);  // Four-byte TX preamble, CHANSPC_E=1.
    writeRegister(kModemConfig0, 0xf8);  // 99.9756 kHz channel spacing.
    writeRegister(kDeviation, 0x45);     // 41.2598 kHz expected deviation.
    writeRegister(kMainStateMachine1, 0x3f);  // Remain in RX after packet.
    writeRegister(kMainStateMachine0, 0x18);  // Calibrate from IDLE to RX.
    writeRegister(kFrequencyOffsetCompensation, 0x16);
    writeRegister(kBitSynchronization, 0x6c);
    writeRegister(kAgcControl2, 0x43);
    writeRegister(kAgcControl1, 0x40);
    writeRegister(kAgcControl0, 0x91);
    writeRegister(kFrontEnd1, 0x56);
    writeRegister(kFrontEnd0, 0x10);
    writeRegister(kFrequencyCalibration3, 0xe9);
    writeRegister(kFrequencyCalibration2, 0x2a);
    writeRegister(kFrequencyCalibration1, 0x00);
    writeRegister(kFrequencyCalibration0, 0x1f);
    writeRegister(kTest2, 0x81);
    writeRegister(kTest1, 0x35);
    writeRegister(kTest0, 0x09);
}

bool Cc1101::begin() {
    pinMode(chipSelectPin_, OUTPUT);
    digitalWrite(chipSelectPin_, HIGH);
    pinMode(misoPin_, INPUT);
    if (!reset()) {
        return false;
    }
    configureRainPoint();
    if (partNumber() != 0x00 || version() == 0x00 || version() == 0xff) {
        return false;
    }
    return setChannel(0);
}

bool Cc1101::setChannel(std::uint8_t channel) {
    if (channel != 0 && channel != 11) {
        return false;
    }
    strobe(kIdle);
    strobe(kFlushRx);
    writeRegister(kChannelNumber, channel);
    channel_ = channel;
    strobe(kEnterRx);
    delay(1);
    return true;
}

void Cc1101::recoverRx() {
    strobe(kIdle);
    strobe(kFlushRx);
    strobe(kEnterRx);
}

bool Cc1101::poll(RadioPacket& packet) {
    const auto rxBytes = readStatus(kRxBytes);
    if (rxBytes & 0x80) {
        recoverRx();
        return false;
    }
    constexpr std::size_t kBytesWithStatus = kRadioPayloadBytes + 2;
    if ((rxBytes & 0x7f) < kBytesWithStatus) {
        return false;
    }

    std::array<std::uint8_t, kBytesWithStatus> received{};
    readBurst(kRxFifo, received.data(), received.size());
    for (std::size_t index = 0; index < packet.payload.size(); ++index) {
        packet.payload[index] = received[index];
    }
    packet.rssiTenthsDbm = decodeRssi(received[kRadioPayloadBytes]);
    packet.lqi = received[kRadioPayloadBytes + 1] & 0x7f;
    recoverRx();
    return true;
}

std::uint8_t Cc1101::channel() const {
    return channel_;
}

std::uint8_t Cc1101::partNumber() {
    return readStatus(kPartNumber);
}

std::uint8_t Cc1101::version() {
    return readStatus(kVersion);
}

}  // namespace rainpoint
