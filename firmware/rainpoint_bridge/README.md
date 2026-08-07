# RainPoint ESP32/CC1101 bridge firmware

This is the first receive-only firmware scaffold for the ELEGOO ESP-WROOM-32
USB-C development board and a **433 MHz** CC1101 module. It contains no transmit
API, no valve commands, and no `STX` path.

## Wiring

Use 3.3 V logic and power for the CC1101. Do not connect its VCC pin to 5 V.

| CC1101 | ESP32 |
|---|---:|
| VCC | 3V3 |
| GND | GND |
| SCK | GPIO18 |
| MISO | GPIO19 |
| MOSI | GPIO23 |
| CSN | GPIO27 |
| GDO0 | GPIO26, reserved for the next interrupt-driven revision |
| GDO2 | GPIO25, optional/reserved |

Keep the module close to the ESP32, add a 100 nF ceramic capacitor directly
across CC1101 VCC/GND, and connect the correct 433 MHz antenna before testing.

## Current behavior

- Configures 2-FSK at approximately 20 ksymbols/s and +/-41.26 kHz deviation.
- Uses a conservative 203.125 kHz receive filter.
- Supports RainPoint channel 0 near 433.140 MHz and channel 11 near 434.240 MHz.
- Reconstructs the stripped first two sync bytes into the normalized 38-byte
  frame.
- Reports serial JSON with channel, CC1101 RSSI/LQI, frame hex, sync validity,
  and the ordinary CRC-CCITT trailer residual.
- Rejects no research frames solely because their ordinary trailer is invalid.

The default discovery mode alternates channels every 500 ms. This is useful
for bring-up but cannot guarantee reception because one CC1101 cannot listen to
channels 1.1 MHz apart simultaneously. Send `0` over serial to lock the lower
channel, `1` to lock the upper channel, or `s` to resume scanning. Reliable
production reception will require two radios or continued RTL-SDR reception.

## Build and flash

Install PlatformIO, connect the board by USB-C, then run:

```sh
cd firmware/rainpoint_bridge
pio run
pio run --target upload
pio device monitor
```

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

1. Compile and flash on the physical ESP32.
2. Verify CC1101 identity and receive both channels while the RTL-SDR records
   the same packets.
3. Tune deviation, RX bandwidth, AFC, AGC, and frequency calibration from
   measured packet success and CC1101 frequency-offset estimates.
4. Add a local network transport into `rainpointd` without adding control.
5. Design transmission as a separate safety-reviewed milestone.
