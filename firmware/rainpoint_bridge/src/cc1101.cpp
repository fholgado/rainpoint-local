#include "cc1101.h"
#include "rainpoint_pairing.h"

#include <driver/rmt.h>

#include <vector>

namespace rainpoint {
namespace {

constexpr std::uint8_t kReadBurst = 0xc0;
constexpr std::uint8_t kReadSingle = 0x80;

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
constexpr std::uint8_t kPaTable = 0x3e;

constexpr std::uint8_t kReset = 0x30;
constexpr std::uint8_t kFrequencySynthOn = 0x31;
constexpr std::uint8_t kEnterRx = 0x34;
constexpr std::uint8_t kEnterTx = 0x35;
constexpr std::uint8_t kIdle = 0x36;
constexpr std::uint8_t kFlushRx = 0x3a;
constexpr std::uint8_t kRxFifo = 0x3f;

constexpr std::uint8_t kPartNumber = 0x30;
constexpr std::uint8_t kVersion = 0x31;
constexpr std::uint8_t kFrequencyEstimate = 0x32;
constexpr std::uint8_t kMainState = 0x35;
constexpr std::uint8_t kRxBytes = 0x3b;

constexpr std::uint8_t kMainStateIdle = 0x01;
constexpr std::uint8_t kMainStateRx = 0x0d;
constexpr std::uint8_t kMainStateFrequencySynthOn = 0x12;

constexpr std::uint32_t kCrystalFrequencyHz = 26'000'000;
constexpr std::uint16_t kSymbolMicros = 50;
constexpr rmt_channel_t kTxRmtChannel = RMT_CHANNEL_0;

std::int16_t decodeRssi(std::uint8_t raw) {
    const auto signedRaw = raw >= 128
        ? static_cast<std::int16_t>(raw) - 256
        : static_cast<std::int16_t>(raw);
    return static_cast<std::int16_t>(signedRaw * 5 - 740);
}

std::int32_t decodeFrequencyOffset(std::uint8_t raw) {
    const auto signedRaw = raw >= 128
        ? static_cast<std::int16_t>(raw) - 256
        : static_cast<std::int16_t>(raw);
    // FREQEST resolution is crystal_frequency / 2^14. The modules use the
    // standard 26 MHz crystal, giving approximately 1.587 kHz per count.
    return static_cast<std::int32_t>(signedRaw) * 26'000'000L / 16'384L;
}

}  // namespace

Cc1101::Cc1101(SPIClass& spi, int chipSelectPin, int misoPin, int dataPin)
    : spi_(spi),
      chipSelectPin_(chipSelectPin),
      misoPin_(misoPin),
      dataPin_(dataPin) {}

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

void Cc1101::writeBurst(
    std::uint8_t address,
    const std::uint8_t* data,
    std::size_t length
) {
    spi_.beginTransaction(SPISettings(kSpiHz, MSBFIRST, SPI_MODE0));
    digitalWrite(chipSelectPin_, LOW);
    if (waitReady()) {
        spi_.transfer(address | 0x40);
        for (std::size_t index = 0; index < length; ++index) {
            spi_.transfer(data[index]);
        }
    }
    digitalWrite(chipSelectPin_, HIGH);
    spi_.endTransaction();
}

std::uint8_t Cc1101::readRegister(std::uint8_t address) {
    spi_.beginTransaction(SPISettings(kSpiHz, MSBFIRST, SPI_MODE0));
    digitalWrite(chipSelectPin_, LOW);
    std::uint8_t value = 0xff;
    if (waitReady()) {
        spi_.transfer(address | kReadSingle);
        value = spi_.transfer(0);
    }
    digitalWrite(chipSelectPin_, HIGH);
    spi_.endTransaction();
    return value;
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

bool Cc1101::verifyConfiguration() {
    struct ExpectedRegister {
        std::uint8_t address;
        std::uint8_t value;
    };
    constexpr std::array<ExpectedRegister, 18> expected = {{
        {kSync1, 0x79},
        {kSync0, 0xf4},
        {kPacketLength, kRadioPayloadBytes},
        {kPacketControl1, 0x04},
        {kPacketControl0, 0x00},
        {kFrequency2, 0x10},
        {kFrequency1, 0xa8},
        {kFrequency0, 0xc3},
        {kModemConfig4, 0x89},
        {kModemConfig3, 0x93},
        {kModemConfig2, 0x02},
        {kModemConfig1, 0x21},
        {kModemConfig0, 0xf8},
        {kDeviation, 0x45},
        {kFrequencyOffsetCompensation, 0x16},
        {kBitSynchronization, 0x6c},
        {kAgcControl2, 0x43},
        {kAgcControl0, 0x91},
    }};
    for (const auto& item : expected) {
        if (readRegister(item.address) != item.value) {
            return false;
        }
    }
    return true;
}

bool Cc1101::begin(std::uint8_t initialChannel) {
    pinMode(chipSelectPin_, OUTPUT);
    digitalWrite(chipSelectPin_, HIGH);
    pinMode(misoPin_, INPUT);
    pinMode(dataPin_, OUTPUT);
    digitalWrite(dataPin_, LOW);
    if (!reset()) {
        return false;
    }
    configureRainPoint();
    if (partNumber() != 0x00 || version() == 0x00 || version() == 0xff) {
        return false;
    }
    configurationValid_ = verifyConfiguration();
    if (!configurationValid_) {
        return false;
    }
    return setChannel(initialChannel);
}

void Cc1101::setFrequency(std::uint32_t frequencyHz) {
    const std::uint32_t word = static_cast<std::uint32_t>(
        (static_cast<std::uint64_t>(frequencyHz) * 65'536ULL +
         kCrystalFrequencyHz / 2) /
        kCrystalFrequencyHz
    );
    writeRegister(kFrequency2, (word >> 16) & 0xff);
    writeRegister(kFrequency1, (word >> 8) & 0xff);
    writeRegister(kFrequency0, word & 0xff);
}

bool Cc1101::restoreReceiveConfiguration(std::uint8_t channel) {
    if (!enterIdle()) {
        return false;
    }
    configureRainPoint();
    configurationValid_ = verifyConfiguration();
    if (!configurationValid_) {
        return false;
    }
    return setChannel(channel);
}

bool Cc1101::transmitAsync(
    const std::array<std::uint8_t, kFrameBytes>& frame,
    std::uint32_t centerFrequencyHz,
    std::uint16_t wakeSymbols,
    bool invert,
    std::uint8_t paTableValue
) {
    if (!hasSync(frame) || !hasOrdinaryTrailer(frame) || wakeSymbols == 0 ||
        wakeSymbols > 2'400 || centerFrequencyHz < 433'000'000 ||
        centerFrequencyHz > 435'000'000) {
        return false;
    }

    const std::uint8_t receiveChannel = channel_;
    if (!enterIdle()) {
        return false;
    }

    // TI CC1101 asynchronous serial mode takes TX data directly on GDO0.
    // Packet automation, whitening, and the FIFO are deliberately bypassed so
    // the ESP32 supplies the complete RainPoint wake, sync, and frame.
    writeRegister(kPacketControl0, 0x30);
    writeRegister(kIocfg0, 0x2e);  // High impedance until GDO0 becomes TX input.
    writeRegister(kChannelNumber, 0);
    setFrequency(centerFrequencyHz);
    writeBurst(kPaTable, &paTableValue, 1);

    const std::size_t symbolCount = rainpointSymbolCount(wakeSymbols);
    std::vector<rmt_item32_t> items((symbolCount + 1) / 2);
    const auto symbolAt = [&](std::size_t index) -> std::uint8_t {
        return rainpointSymbol(frame, wakeSymbols, index, invert);
    };
    for (std::size_t index = 0; index < items.size(); ++index) {
        const std::size_t first = index * 2;
        const std::size_t second = first + 1;
        items[index].level0 = symbolAt(first);
        items[index].duration0 = kSymbolMicros;
        items[index].level1 = second < symbolCount ? symbolAt(second) : 0;
        items[index].duration1 = second < symbolCount ? kSymbolMicros : 1;
    }

    rmt_config_t config = RMT_DEFAULT_CONFIG_TX(
        static_cast<gpio_num_t>(dataPin_),
        kTxRmtChannel
    );
    config.clk_div = 80;  // 80 MHz APB / 80 = one microsecond per tick.
    config.mem_block_num = 1;
    config.tx_config.idle_output_en = true;
    config.tx_config.idle_level = RMT_IDLE_LEVEL_LOW;

    const bool rmtConfigured = rmt_config(&config) == ESP_OK;
    const bool rmtInstalled = rmtConfigured &&
        rmt_driver_install(kTxRmtChannel, 0, 0) == ESP_OK;
    bool sent = rmtInstalled;
    if (sent) {
        // Calibrate and settle the synthesizer with the PA still gated. Going
        // directly from IDLE to TX exposed roughly 140 us of constant carrier
        // before RMT began the alternating RainPoint wake; stock starts the
        // usable carrier and wake together. FSTXON keeps that settling period
        // off-air and makes the subsequent TX transition immediate.
        sent = strobe(kFrequencySynthOn) != 0xff &&
               waitForMainState(kMainStateFrequencySynthOn, 10'000);
    }
    if (sent) {
        digitalWrite(dataPin_, symbolAt(0));
        // Start the long alternating wake asynchronously with the PA still
        // gated, then enter TX immediately. This overlaps the short STX-to-PA
        // transition with the expendable beginning of the 320-symbol wake and
        // avoids exposing a static data level while polling MARCSTATE.
        sent = rmt_write_items(
                   kTxRmtChannel,
                   items.data(),
                   items.size(),
                   false
               ) == ESP_OK;
        if (sent) {
            sent = strobe(kEnterTx) != 0xff;
        }
        const bool rmtCompleted =
            rmt_wait_tx_done(kTxRmtChannel, pdMS_TO_TICKS(100)) == ESP_OK;
        sent = sent && rmtCompleted;
    }
    if (rmtInstalled) {
        rmt_driver_uninstall(kTxRmtChannel);
    }
    digitalWrite(dataPin_, LOW);
    enterIdle();
    return restoreReceiveConfiguration(receiveChannel) && sent;
}

bool Cc1101::waitForMainState(
    std::uint8_t expectedState,
    std::uint32_t timeoutMicros
) {
    const auto started = micros();
    while ((readStatus(kMainState) & 0x1f) != expectedState) {
        if (micros() - started >= timeoutMicros) {
            return false;
        }
        yield();
    }
    return true;
}

bool Cc1101::enterIdle() {
    if (strobe(kIdle) == 0xff) {
        return false;
    }
    return waitForMainState(kMainStateIdle);
}

bool Cc1101::enterReceive() {
    if (strobe(kEnterRx) == 0xff) {
        return false;
    }
    return waitForMainState(kMainStateRx);
}

bool Cc1101::setChannel(std::uint8_t channel) {
    if (channel != 0 && channel != 11) {
        return false;
    }
    if (!enterIdle()) {
        return false;
    }
    strobe(kFlushRx);
    writeRegister(kChannelNumber, channel);
    channel_ = channel;
    return enterReceive();
}

void Cc1101::recoverRx() {
    ++recoveryCount_;
    enterIdle();
    strobe(kFlushRx);
    enterReceive();
}

bool Cc1101::poll(RadioPacket& packet) {
    const auto rxBytes = readStatus(kRxBytes);
    if (rxBytes & 0x80) {
        ++overflowCount_;
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
    packet.frequencyOffsetHz = decodeFrequencyOffset(
        readStatus(kFrequencyEstimate)
    );
    ++packetCount_;
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

bool Cc1101::configurationValid() const {
    return configurationValid_;
}

std::uint32_t Cc1101::packetCount() const {
    return packetCount_;
}

std::uint32_t Cc1101::overflowCount() const {
    return overflowCount_;
}

std::uint32_t Cc1101::recoveryCount() const {
    return recoveryCount_;
}

}  // namespace rainpoint
