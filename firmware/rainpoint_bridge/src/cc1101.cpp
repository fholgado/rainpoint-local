#include "cc1101.h"
#include "rainpoint_htv145_pairing.h"
#include "rainpoint_pairing.h"
#include "rainpoint_valve_pairing.h"

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
constexpr std::uint8_t kCalibrate = 0x33;
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
constexpr std::uint8_t kMainStateTx = 0x13;

// Intentional controller replies must not be suppressed by the receiver's
// clear-channel assessment. Preserve RXOFF_MODE=RX and TXOFF_MODE=RX while
// selecting CCA_MODE=always so an explicit STX cannot silently remain in
// FSTXON after a strong, recently completed valve request.
constexpr std::uint8_t kTransmitMainStateMachine1 = 0x0f;

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

bool Cc1101::prepareTransmit() {
    if (transmitPrepared_) {
        return true;
    }
    rmt_config_t config = RMT_DEFAULT_CONFIG_TX(
        static_cast<gpio_num_t>(dataPin_),
        kTxRmtChannel
    );
    config.clk_div = 80;  // 80 MHz APB / 80 = one microsecond per tick.
    config.mem_block_num = 1;
    config.tx_config.idle_output_en = true;
    config.tx_config.idle_level = RMT_IDLE_LEVEL_LOW;
    transmitPrepared_ = rmt_config(&config) == ESP_OK &&
        rmt_driver_install(kTxRmtChannel, 0, 0) == ESP_OK;
    return transmitPrepared_;
}

void Cc1101::setTransmitEnabled(bool enabled) {
    transmitEnabled_ = enabled;
}

bool Cc1101::transmitEnabled() const {
    return transmitEnabled_;
}

std::uint32_t Cc1101::blockedTransmitCount() const {
    return blockedTransmitCount_;
}

bool Cc1101::cacheTransmitFrequency(std::uint32_t centerFrequencyHz) {
    if (centerFrequencyHz < 433'000'000 || centerFrequencyHz > 435'000'000) {
        return false;
    }
    CachedFrequencyCalibration* destination = nullptr;
    for (auto& cached : cachedTransmitFrequencies_) {
        if (cached.valid && cached.centerFrequencyHz == centerFrequencyHz) {
            destination = &cached;
            break;
        }
        if (destination == nullptr && !cached.valid) {
            destination = &cached;
        }
    }
    if (destination == nullptr) {
        return false;
    }

    const std::uint8_t receiveChannel = channel_;
    if (!enterIdle()) {
        return false;
    }
    writeRegister(kChannelNumber, 0);
    setFrequency(centerFrequencyHz);
    const bool calibrated = strobe(kCalibrate) != 0xff &&
        waitForMainState(kMainStateIdle, 10'000);
    const std::uint8_t calibration3 = readRegister(kFrequencyCalibration3);
    const std::uint8_t calibration2 = readRegister(kFrequencyCalibration2);
    const std::uint8_t calibration1 = readRegister(kFrequencyCalibration1);
    const bool valuesValid = calibration3 != 0xff && calibration2 != 0xff &&
        calibration1 != 0xff && calibration1 != 0x3f;
    const bool restored = restoreReceiveConfiguration(receiveChannel);
    if (!calibrated || !valuesValid || !restored) {
        return false;
    }
    *destination = CachedFrequencyCalibration{
        centerFrequencyHz,
        calibration3,
        calibration2,
        calibration1,
        true,
    };
    return true;
}

bool Cc1101::transmitAsync(
    const std::array<std::uint8_t, kFrameBytes>& frame,
    std::uint32_t centerFrequencyHz,
    std::uint16_t wakeSymbols,
    bool invert,
    std::uint8_t paTableValue,
    std::uint8_t deviationRegister,
    std::uint32_t startAtMicros,
    std::uint16_t leadingPreludeSymbols,
    std::int8_t leadingFrequencyOffsetRegister,
    std::uint8_t leadingDeviationRegister,
    bool invertLeadingPrelude
) {
    if (!transmitEnabled_) {
        ++blockedTransmitCount_;
        return false;
    }
    const bool hasLeadingPrelude = leadingPreludeSymbols != 0;
    const bool validatedLeadingProfile =
        leadingDeviationRegister ==
            htv145::kCounter0AssignmentPreludeDeviationRegister
#if RAINPOINT_RESEARCH_BENCH == 1
        || ((leadingFrequencyOffsetRegister == 12 ||
             leadingFrequencyOffsetRegister == 13) &&
            (leadingDeviationRegister == 0x41 ||
             leadingDeviationRegister == 0x42))
#endif
        ;
    if (!hasSync(frame) || !hasOrdinaryTrailer(frame) || wakeSymbols == 0 ||
        wakeSymbols > 2'400 || leadingPreludeSymbols > 2'400 ||
        centerFrequencyHz < 433'000'000 ||
        centerFrequencyHz > 435'000'000 ||
        (deviationRegister != kOrdinaryDeviationRegister &&
         deviationRegister != kHtv405InitialDeviationRegister) ||
        (hasLeadingPrelude &&
         (startAtMicros == 0 || leadingFrequencyOffsetRegister == 0 ||
          !validatedLeadingProfile)) ||
        (!hasLeadingPrelude &&
         (leadingFrequencyOffsetRegister != 0 ||
          leadingDeviationRegister != 0 || invertLeadingPrelude)) ||
#if RAINPOINT_RESEARCH_BENCH != 1
        invertLeadingPrelude ||
#endif
        false) {
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
    writeRegister(kMainStateMachine1, kTransmitMainStateMachine1);
    writeRegister(kChannelNumber, 0);
    setFrequency(centerFrequencyHz);
    writeRegister(
        kFrequencySynthControl0,
        static_cast<std::uint8_t>(
            hasLeadingPrelude ? leadingFrequencyOffsetRegister : 0
        )
    );
    writeRegister(
        kDeviation,
        hasLeadingPrelude ? leadingDeviationRegister : deviationRegister
    );
    writeBurst(kPaTable, &paTableValue, 1);

    const CachedFrequencyCalibration* cachedCalibration = nullptr;
    for (const auto& cached : cachedTransmitFrequencies_) {
        if (cached.valid && cached.centerFrequencyHz == centerFrequencyHz) {
            cachedCalibration = &cached;
            break;
        }
    }
    if (cachedCalibration != nullptr) {
        // TI CC1101 section 28.2 permits fast hopping by restoring FSCAL3--1
        // captured for the destination frequency. Disable automatic
        // calibration for this transition; the PLL then settles in ~75 us
        // instead of spending ~724 us recalibrating after the request.
        writeRegister(kMainStateMachine0, 0x08);
        writeRegister(
            kFrequencyCalibration3,
            cachedCalibration->frequencyCalibration3
        );
        writeRegister(
            kFrequencyCalibration2,
            cachedCalibration->frequencyCalibration2
        );
        writeRegister(
            kFrequencyCalibration1,
            cachedCalibration->frequencyCalibration1
        );
    } else {
        writeRegister(kMainStateMachine0, 0x18);
    }

    const std::size_t symbolCount = rainpointSymbolCount(
        wakeSymbols, leadingPreludeSymbols
    );
    std::vector<rmt_item32_t> items((symbolCount + 1) / 2);
    const auto symbolAt = [&](std::size_t index) -> std::uint8_t {
        return rainpointSymbol(
            frame,
            wakeSymbols,
            index,
            invert,
            leadingPreludeSymbols,
            invertLeadingPrelude
        );
    };
    for (std::size_t index = 0; index < items.size(); ++index) {
        const std::size_t first = index * 2;
        const std::size_t second = first + 1;
        items[index].level0 = symbolAt(first);
        items[index].duration0 = kSymbolMicros;
        items[index].level1 = second < symbolCount ? symbolAt(second) : 0;
        items[index].duration1 = second < symbolCount ? kSymbolMicros : 1;
    }

    bool sent = prepareTransmit();
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
        // Pairing replies have a narrow receive-complete-to-carrier window.
        // Complete allocation, register writes, and synthesizer settling
        // before waiting for the requested on-air deadline. This removes the
        // several milliseconds of first-transmission and Wi-Fi-loop jitter
        // that occurred when callers delayed before entering this function.
        if (startAtMicros != 0) {
            while (static_cast<std::int32_t>(
                       startAtMicros - micros()
                   ) > 500) {
                delayMicroseconds(250);
            }
            while (static_cast<std::int32_t>(
                       startAtMicros - micros()
                   ) > 0) {
                // Deliberately busy-wait only the final 500 us.
            }
        }
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
            // STX can be accepted over SPI without the radio actually leaving
            // FSTXON when CCA inhibits transmission. Confirm the physical TX
            // state instead of reporting an RMT-only success with no carrier.
            sent = strobe(kEnterTx) != 0xff &&
                waitForMainState(kMainStateTx, 2'000);
        }
        if (sent && hasLeadingPrelude) {
            // Keep the PA and RMT stream active while changing only FSCTRL0
            // and DEVIATN at the evidence-derived prelude boundary. This
            // reproduces the stock gateway's seamless shifted alternating
            // prefix without incurring a synthesizer restart between it and
            // the ordinary 320-symbol wake.
            const std::uint32_t transitionAtMicros = startAtMicros +
                leadingPreludeSymbols * kSymbolMicros;
            while (static_cast<std::int32_t>(
                       transitionAtMicros - micros()
                   ) > 500) {
                delayMicroseconds(250);
            }
            while (static_cast<std::int32_t>(
                       transitionAtMicros - micros()
                   ) > 0) {
                // Deliberately busy-wait only the final 500 us.
            }
            writeRegister(kFrequencySynthControl0, 0);
            writeRegister(kDeviation, deviationRegister);
        }
        // Ordinary RainPoint frames use a 320-symbol wake and finish in about
        // 31 ms, but the HTV405 selector-2 configuration command uses the
        // stock gateway's 2,400-symbol wake and lasts about 135 ms. A fixed
        // 100 ms wait truncated that command before its frame reached the
        // air. Derive the completion timeout from the waveform itself and
        // retain a small scheduler margin.
        const std::uint32_t waveformDurationMs = static_cast<std::uint32_t>(
            (symbolCount * kSymbolMicros + 999U) / 1'000U
        );
        const bool rmtCompleted = rmt_wait_tx_done(
            kTxRmtChannel,
            pdMS_TO_TICKS(waveformDurationMs + 25U)
        ) == ESP_OK;
        sent = sent && rmtCompleted;
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

bool Cc1101::setReceiveFrequency(std::uint32_t centerFrequencyHz) {
    if (centerFrequencyHz < 433'000'000 ||
        centerFrequencyHz > 435'000'000 || !enterIdle()) {
        return false;
    }
    strobe(kFlushRx);
    writeRegister(kChannelNumber, 0);
    setFrequency(centerFrequencyHz);
    channel_ = 0;
    return enterReceive();
}

bool Cc1101::restoreReceiveChannel(std::uint8_t channel) {
    if (channel != 0 && channel != 11) {
        return false;
    }
    return restoreReceiveConfiguration(channel);
}

void Cc1101::recoverRx() {
    ++recoveryCount_;
    enterIdle();
    strobe(kFlushRx);
    enterReceive();
}

bool Cc1101::poll(RadioPacket& packet, bool recoverAfterRead) {
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

    // The fixed-length RX FIFO becomes complete at the end of the request.
    // Capture the earliest available deadline anchor before the SPI burst.
    packet.receivedAtMicros = micros();
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
    if (recoverAfterRead) {
        recoverRx();
    }
    return true;
}

void Cc1101::recoverReceive() {
    recoverRx();
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
