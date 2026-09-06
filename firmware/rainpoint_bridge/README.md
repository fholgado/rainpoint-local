# RainPoint radio-node firmware

This directory contains the single supported ESP32/CC1101 firmware for
RainPoint Local. One node receives RainPoint RF telemetry, performs bounded
HCS026 soil-sensor pairing and recovery, sends acknowledgements only for
gateway-assigned sensors, and installs integrity-checked OTA updates.

The unified build includes sensor pairing/ACKs, HTV405 enrollment and bounded
control, and verified OTA. Actuation requires an authenticated gateway,
association-specific endpoints and the add-on's explicit control gate. No build
permits arbitrary RF transmission or the retired serial probes.

HTV145 qualification uses one additional compile option. It retains the exact
counter-2/selector-6 pairing recipe from `.22`, whose 5/6 prefix supported two
local dry opens, automatic stop and active early close. The normal image excludes
HTV145 transmission until its repeated operational/ACK hardware gates are met.

## Supported hardware and wiring

The tested board is an ESP-WROOM-32 development board with USB-C and one 433 MHz
CC1101 module. Use 3.3 V logic and power; never connect CC1101 VCC to 5 V.

| CC1101 pin | Label | ESP32 | Purpose |
|---:|---|---:|---|
| 1 | GND | GND | Power-reference ground |
| 2 | VCC | 3V3 | 1.8–3.6 V module power |
| 3 | GDO0 | GPIO26 | Asynchronous pairing/ACK TX data |
| 4 | CSN | GPIO27 | SPI chip select |
| 5 | SCK | GPIO18 | SPI clock |
| 6 | MOSI | GPIO23 | SPI controller-to-radio data |
| 7 | MISO/GDO1 | GPIO19 | SPI radio-to-controller data |
| 8 | GDO2 | GPIO25 | Reserved |

Use the module’s pin-1 marking and printed labels to orient its 2×4 connector.
Keep wiring short, connect a 433 MHz antenna, and place a 100 nF ceramic bypass
capacitor across CC1101 VCC/GND when practical.

## Behavior

- One radio receives the supported telemetry channels; persistent sensor ACK
  ownership keeps its validated telemetry channel prioritized.
- Authenticated pairing supplies controller, device and companion identities.
  Unknown sensors still need an explicit user pairing gesture.
- HTV405 controls support 1--60 whole-minute opens and use the existing bounded
  transaction, counter and morning-sync rules. The add-on `supervised_htv405_control` gate remains disabled by default.
- The HTV145 qualification image adds a persistent control/ACK profile. Commands
  carry both association endpoints and an expected counter. A rejected profile
  cannot accidentally direct a following command at the previous association.
- HTV145 opens use a 2,400-symbol wake and whole-minute duration bounds; a positive
  open response increments the five-bit counter and a positive close retains it.
  Reports use their own counter. Result 3 and summaries cannot authenticate a
  command or establish current idle state.
- The configured HTV145 owner ACKs only CRC-valid matching reports/summaries, using
  a 320-symbol wake and an explicitly supplied calibrated ACK frequency. The
  40 ms post-reception deadline is derived from stock timing and still needs
  on-air qualification with the cleaned image. ACKs do not consume command counters.
- Maintenance/restarts restore configuration and evidenced counters only. An
  unresolved command is never replayed; missing overdue idle evidence is an
  observation-only anomaly. No speculative startup close is sent.
- OTA retains hash verification, boot health and rollback behavior. Firmware and
  configuration updates remain independently authorized operations.

## Build, flash, and monitor

`rainpoint_bridge` is the only supported PlatformIO environment:

```sh
pio run --project-dir firmware/rainpoint_bridge --environment rainpoint_bridge
python tools/check_firmware_boundaries.py --supervised \
  firmware/rainpoint_bridge/.pio/build/rainpoint_bridge/firmware.bin
```

For the designated dry HTV145 test node:

```sh
RAINPOINT_HTV145_ENABLED=1 pio run --project-dir firmware/rainpoint_bridge \
  --environment rainpoint_bridge
python tools/check_firmware_boundaries.py --supervised --htv145-pairing \
  --htv145-control firmware/rainpoint_bridge/.pio/build/rainpoint_bridge/firmware.bin
```

Production version is `0.15.14`; the isolated image is
`0.15.22-htv145-control.1`. `RAINPOINT_FIRMWARE_VERSION` may label a reproducible
artifact. Retired research, selector, factory-counter, timing, tail and PHY flags
are rejected. Their captures remain under `research/fixtures`; Git retains the
old implementation and the exact `.22` binary remains a separate rollback artifact.

Back up the node's settings and preserve a verified rollback image before
flashing. Never distribute an installation's settings or credentials. Use the
existing OTA procedure below; for USB use the tested `esp32dev` board and select
the intended serial port explicitly. If automatic reset fails, hold **BOOT**
until the uploader starts connecting.

## Bounded morning synchronization

Firmware 0.15.11 advertises `htv405_bounded_sync_wait`; gateway 0.34.2 accepts
this capability during authenticated enrollment/reconnection. The supervised
`valve_control_close` command can specify `wait_for_report`, `idle_only`, and
`wait_timeout_seconds` (1–7200), with `confirmed_idle: true` from the gateway's
known-idle reservation. A fresh link report supplies the RF opportunity. Any
watering report invalidates this attempt; the gateway also cancels it if another
receiver hears watering. The node expires the wait independently of the gateway.
The response listener may finish after the wait deadline if RF
already transmitted within the window.

`valve_control_cancel_wait` clears only the queued wait with the exact original
command ID. Its acknowledgement includes that ID and `close_queued: false`.
It cannot cancel an already transmitted command or fabricate an idle response.
The incoming command filter and deadline guard run in native protocol tests;
the gateway runtime gate still controls their availability.

## First-boot commissioning

1. Power a new node. It creates **RainPoint Local Setup xxxxxx**.
2. Join that network and enter only the home Wi-Fi name and password.
3. In Home Assistant, accept the discovered RainPoint radio node and choose its
   friendly name and area.
4. Use **Identify** if needed, then press the ESP32 BOOT button when prompted.
5. Home Assistant supplies the gateway address and one-time node credential;
   the node restarts and mutually authenticates.

An adopted node stops advertising the commissioning service. Holding BOOT for
ten seconds clears Wi-Fi/adoption state and returns it to first-boot setup.

### USB recovery

At 115200 baud, `show_node` displays non-secret node configuration. On an
unconfigured board it also exposes the generated setup token for recovery.
`clear_wifi` clears commissioning state and rotates that token. The legacy
`configure_wifi` tab-separated command remains a recovery path, not normal UX.

## Sensor pairing and recovery

Pair sensors from **Settings → Devices & services → RainPoint Local →
Configure → Pair sensor**. Select the radio node closest to the sensor. The
stock RainPoint gateway must be powered off during the short pairing exchange
so it cannot race the selected local transmitter.

Do not delete an existing HA device before reassociation. The gateway derives
the paired endpoint from the factory identity and preserves the existing device
and entity history. A later long press can recover a known dormant sensor
without opening a pairing window or removing its batteries.

## OTA releases

After the first OTA-capable image is installed over USB, compatible staged
releases appear on the radio node’s Home Assistant Update entity. Build and
verify the standard artifact manifest with:

Production and supervised builds report the `unified` firmware variant.
Research-only HTV145 probes report a distinct variant and must never be staged
as compatible with `unified` nodes.

```sh
python tools/firmware_manifest.py \
  firmware/rainpoint_bridge/.pio/build/rainpoint_bridge/firmware.bin \
  /tmp/rainpoint-radio-node-manifest.json \
  --version 0.15.11 --environment rainpoint_bridge
python tools/firmware_manifest.py \
  firmware/rainpoint_bridge/.pio/build/rainpoint_bridge/firmware.bin \
  /tmp/rainpoint-radio-node-manifest.json --verify
```

The current OTA transport is intended for a trusted LAN. Node/gateway HMAC
authentication and artifact hashing are implemented; encrypted sessions,
credential rotation, and asymmetric release signatures remain publication
hardening requirements.

## Developer verification

The hardware-independent protocol regression runs without PlatformIO:

```sh
c++ -std=c++17 -Ifirmware/rainpoint_bridge/include \
  firmware/rainpoint_bridge/tests/protocol_test.cpp \
  -o /tmp/rainpoint-protocol-test
/tmp/rainpoint-protocol-test
```

Captured frames remain in `research/fixtures`. Keep uncertain protocol fields
explicitly provisional and add a regression fixture before changing any
pairing, acknowledgement, channel, or trailer behavior.

## Qualification status

The sole live checklist for firmware, OTA, sensor, and valve hardware gates is
`../../PROJECT_ROADMAP.md`. This document describes how to build and operate the
firmware and must not maintain a second completion list.
