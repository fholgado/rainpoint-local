# RainPoint ESP32/CC1101 bridge firmware

This is the receive-only firmware scaffold for the ELEGOO ESP-WROOM-32 USB-C
development board and one **433 MHz** CC1101 transceiver. A second module is
supported only as an optional dual-channel receive diagnostic. The firmware
contains no transmit API, no valve commands, and no `STX` path.

## Wiring

Use 3.3 V logic and power for the CC1101. Do not connect its VCC pin to 5 V.

The production wiring uses only the primary radio. If the optional diagnostic
radio is fitted, the modules share SPI clock and data but must have independent
chip-select pins; never connect the two CSN pins together.

| Signal | Primary radio | Optional diagnostic radio | ESP32 |
|---|---|---|---:|
| VCC | VCC | VCC | 3V3 |
| GND | GND | GND | GND |
| SCK | SCK | SCK | GPIO18 |
| MISO | MISO | MISO | GPIO19 |
| MOSI | MOSI | MOSI | GPIO23 |
| CSN | CSN | — | GPIO27 |
| CSN | — | CSN | GPIO14 |
| GDO0 | GDO0 | — | GPIO26, reserved |
| GDO0 | — | GDO0 | GPIO33, reserved |
| GDO2 | GDO2 | — | GPIO25, optional/reserved |
| GDO2 | — | GDO2 | GPIO32, optional/reserved |

Keep the module close to the ESP32, add a 100 nF ceramic capacitor directly
across its VCC/GND pair, and connect the correct 433 MHz antenna before testing.
The optional diagnostic module needs its own decoupling and antenna; combining
two RF ports onto one antenna requires a proper RF combiner or switch.

## Current behavior

- Configures 2-FSK at approximately 20 ksymbols/s and +/-41.26 kHz deviation.
- Uses a conservative 203.125 kHz receive filter.
- Supports RainPoint channel 0 near 433.140 MHz and channel 11 near 434.240 MHz.
- Reconstructs the stripped first two sync bytes into the normalized 38-byte
  frame.
- Reports serial JSON with channel, CC1101 RSSI/LQI, frame hex, sync validity,
  frequency-offset estimate, and the ordinary CRC-CCITT trailer residual.
- Reads back critical modem, sync, packet, and frequency registers at startup
  and refuses to report the radio ready if configuration did not stick.
- Counts received packets, RX FIFO overflows, and FIFO recoveries per radio.
- Emits a `radio_health` record at boot and every 30 seconds so wiring,
  configuration, tuning, and FIFO problems can be distinguished.
- Rejects no research frames solely because their ordinary trailer is invalid.

`recoveries` includes the intentional FIFO reset after a successfully consumed
fixed-length packet as well as overflow recovery; compare it with `packets` and
`overflows` rather than treating it as an error count by itself. The frequency
offset uses the CC1101 `FREQEST` status register and a 26 MHz crystal. These
diagnostics follow the register definitions in the
[TI CC1101 datasheet](https://www.ti.com/lit/ds/symlink/cc1101.pdf).

The production single-radio build alternates channels every 500 ms. Send `0`
over serial to lock channel 0, `1` to lock channel 11, or `s` to resume
scanning. The optional dual-radio diagnostic build fixes the primary radio to
channel 0 and the second radio to channel 11 so both can be evaluated
continuously against the existing RTL-SDR.

The driver now exposes explicit IDLE and RX transitions and validates complete
frames before extracting the 36 bytes that follow the CC1101 hardware sync.
These are prerequisites for a future half-duplex TX path, but they cannot
transmit. RainPoint command traffic uses an approximately 60 ms alternating
wake prefix, longer than the CC1101 packet engine can generate normally. A
future implementation must reproduce that wake sequence using a validated
FIFO/continuous or asynchronous method before an `STX` path is permitted.

## Build and flash

Install PlatformIO, connect the board by USB-C, then run:

```sh
cd firmware/rainpoint_bridge
pio run
pio run --environment esp32dev_single --target upload
pio device monitor
```

The default and production environment is `esp32dev_single`. Use
`esp32dev_dual` only when the optional second receive module is connected:

```sh
pio run --environment esp32dev_dual --target upload
```

GitHub CI explicitly compiles both configurations from a clean environment on
every push and pull request so the diagnostic build cannot silently regress.

The generic `esp32dev` board profile matches the ESP-WROOM-32 development
board. If upload auto-reset does not work, hold **BOOT**, start upload, and
release it when PlatformIO begins connecting.

The hardware-independent protocol test can run without PlatformIO:

```sh
c++ -std=c++17 -Ifirmware/rainpoint_bridge/include \
  firmware/rainpoint_bridge/tests/protocol_test.cpp \
  -o /tmp/rainpoint-protocol-test
/tmp/rainpoint-protocol-test
```

## Next firmware increments

1. Flash on the physical ESP32.
2. Verify the primary CC1101 on both channels while the existing RTL-SDR
   records the same packets; use the optional second radio only for comparative
   diagnostics.
3. Tune deviation, RX bandwidth, AFC, AGC, and frequency calibration from
   measured packet success and CC1101 frequency-offset estimates.
4. Validate the implemented receive-only USB serial transport into
   `rainpointd`.
5. Add authenticated local-network transport only if USB deployment proves
   impractical.
6. Reproduce the long command wake prefix without exposing a command surface.
7. Design transmission as a separate safety-reviewed milestone.
