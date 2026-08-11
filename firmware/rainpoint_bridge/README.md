# RainPoint ESP32/CC1101 bridge firmware

This is the receive firmware and bounded sensor-pairing node for the
ELEGOO ESP-WROOM-32 USB-C development board and one **433 MHz** CC1101
transceiver. A second module is supported only as an optional dual-channel
receive diagnostic. The firmware contains no valve commands. Its only TX path
is the explicit Test Sensor B pairing profile recovered from controlled stock
gateway captures.

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
| GDO0 | GDO0 | — | GPIO26, required for pairing TX data |
| GDO0 | — | GDO0 | GPIO33, receive diagnostic only |
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
- Reports USB serial JSON with a stable node ID, channel, CC1101 RSSI/LQI,
  frame hex, sync validity,
  frequency-offset estimate, and the ordinary CRC-CCITT trailer residual.
- Reads back critical modem, sync, packet, and frequency registers at startup
  and refuses to report the radio ready if configuration did not stick.
- Counts received packets, RX FIFO overflows, and FIFO recoveries per radio.
- Emits a `radio_health` record at boot and every 30 seconds so wiring,
  configuration, tuning, and FIFO problems can be distinguished.
- Rejects no research frames solely because their ordinary trailer is invalid.
- Optionally mirrors the same records over an outbound Wi-Fi TCP connection to
  `rainpointd`. The node authenticates with a nonce/HMAC proof and never sends
  its enrollment token over the network.
- Contains a three-reply Sensor B pairing profile from the successful stock
  repeat-enrollment capture, a 320-symbol wake prefix, and provisional 250 ms
  response deadline. It requires the sensor's later terminal message `03`
  before declaring enrollment complete.
- Uses the ESP32 RMT peripheral and CC1101 asynchronous serial mode to supply
  the complete 20 ksymbol/s wake, sync, and frame on GDO0.
- Starts disarmed after every boot. In production builds, only an authenticated
  protocol-v2 gateway command for factory endpoint `15a98024` enables the
  time-limited automatic reply sequence.
- Transmits the validated sequence at the configured 10 dBm prototype setting and returns to the
  receive configuration after every 31.2 ms reply.
- Reports pairing state, command ID, completed steps, and armed state over
  serial and the authenticated Wi-Fi connection. The only accepted network
  commands start or cancel the fixed sensor-pairing profile.

`recoveries` includes the intentional FIFO reset after a successfully consumed
fixed-length packet as well as overflow recovery; compare it with `packets` and
`overflows` rather than treating it as an error count by itself. The frequency
offset uses the CC1101 `FREQEST` status register and a 26 MHz crystal. These
diagnostics follow the register definitions in the
[TI CC1101 datasheet](https://www.ti.com/lit/ds/symlink/cc1101.pdf).

The production single-radio build alternates channels every 500 ms. The
optional dual-radio diagnostic build fixes the primary radio to channel 0 and
the second radio to channel 11 so both can be evaluated continuously against
the existing RTL-SDR.

Local RF probe, tuning, channel-lock, and pairing-arm commands are compiled
only into `esp32dev_single_bench`. They are absent from production binaries; CI
inspects both images to enforce that boundary. The bench procedure lives in
[`research/PAIRING_BENCH_TEST.md`](../../research/PAIRING_BENCH_TEST.md).

The research-bench-only commands are:

```text
pairing_status
pairing_plan_b
pairing_probe_b 1 15a98024
pairing_probe_b 2 15a98024
pairing_offset_hz -2000
pairing_power_dbm 10
pairing_invert off
pairing_clock_local 20260811145556
pairing_arm_b 15a98024
pairing_cancel
```

`pairing_probe_b` emits one captured reply so the independent RTL-SDR can
measure it before a sensor is involved. The active repeat-enrollment replies
use 433.4715 MHz. The offset is limited to +/-100 kHz. Bench power can be set
to 0, 5, 7, or 10 dBm. Polarity, offset, and power cannot be changed while
armed. `pairing_clock_local` supplies the fresh target gateway-local time
packed into the initial reply. The successful bench test used the observed
RainPoint gateway clock, four minutes ahead of the Mac; this correction is not
assumed universal beyond the currently fixed Sensor B profile. The supplied
time advances internally after the command, so
the reply does not become stale while the operator prepares the sensor.
`pairing_arm_b` locks the primary receiver to the lower sensor
channel, expires after two minutes, and responds only to the three validated
Sensor B trigger layouts in order. After the replies it remains armed through
the short message `02` until terminal message `03` confirms completion. Duplicate earlier triggers
are ignored; timeout, an unexpected later trigger, TX failure, or loss of an
active gateway connection fails closed. `pairing_cancel` disarms immediately.

The driver uses explicit IDLE/RX/TX transitions and restores the validated
packet receive profile after each asynchronous pairing reply. Valve command
traffic uses a different approximately 60 ms alternating wake and remains
unimplemented. No pairing TX result should be considered valid until the
independent SDR confirms carrier, deviation, polarity, symbol timing, and the
complete decoded frame from physical hardware.

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

Build `esp32dev_single_bench` only for controlled RF research where local
serial TX controls are explicitly required:

```sh
pio run --environment esp32dev_single_bench --target upload
```

GitHub CI explicitly compiles all three configurations from a clean environment
and verifies that production images contain none of the local TX bench command
strings.

The generic `esp32dev` board profile matches the ESP-WROOM-32 development
board. If upload auto-reset does not work, hold **BOOT**, start upload, and
release it when PlatformIO begins connecting.

## Wi-Fi provisioning for prototype testing

Wi-Fi is optional. An unconfigured node continues to work over USB exactly as
before. Each board derives a stable ID such as `rp-001122334455` from its ESP32
hardware identifier. Open the serial monitor at 115200 baud and enter:

```text
show_node
```

Generate a separate 32-byte token for this node (`openssl rand -hex 32` is one
option), add the node-ID/token pair to `rainpointd`, then provision the board
with one tab-separated line:

```text
configure_wifi<TAB>SSID<TAB>PASSWORD<TAB>HA_HOST<TAB>8790<TAB>64_HEX_TOKEN
```

Use literal Tab characters and press Enter. Restart the ESP32 after it reports
`configuration_saved`. The board stores the values in ESP32 NVS, connects as a
Wi-Fi station, and makes an outbound connection to the configured Home
Assistant host. `show_node` reports only non-secret configuration. `clear_wifi`
erases the saved Wi-Fi and token values.

This is a trusted-LAN prototype transport. Separate nonce/HMAC proofs
authenticate both the node and `rainpointd` and keep the token itself off the
network, but TCP telemetry is not encrypted or individually signed. Before a
published setup or any valve control, the transport will need further review.
Protocol v2 accepts only the bounded `pairing_start` and `pairing_cancel`
messages after authentication. It contains no generic RF or valve command.

The hardware-independent protocol test can run without PlatformIO:

```sh
c++ -std=c++17 -Ifirmware/rainpoint_bridge/include \
  firmware/rainpoint_bridge/tests/protocol_test.cpp \
  -o /tmp/rainpoint-protocol-test
/tmp/rainpoint-protocol-test
```

## Next firmware increments

1. Flash firmware 0.4.0 and verify the node authenticates to `rainpointd` as
   protocol v2 while disarmed.
2. Start the fixed Sensor B workflow from Home Assistant with the original
   RainPoint gateway powered off.
3. Confirm terminal message `03`, registry creation, and ordinary moisture
   entities end to end.
4. Characterize routine post-enrollment acknowledgements and long-term report
   behavior.
5. Generalize pairing only from additional controlled device captures.
6. Implement and validate the distinct valve wake and close command before any
   bounded open test.
