# RainPoint radio-node firmware

This directory contains the single supported ESP32/CC1101 firmware for
RainPoint Local. One node receives RainPoint RF telemetry, performs bounded
HCS026 soil-sensor pairing and recovery, sends acknowledgements only for
gateway-assigned sensors, and installs integrity-checked OTA updates.

It does **not** implement valve control or arbitrary RF transmission. Historical
pairing captures and experiments live under `research/`; they are protocol
evidence, not alternative firmware builds.

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

- Receives the two observed RainPoint 2-FSK telemetry channels near 433.14 and
  434.24 MHz and publishes normalized 38-byte frames with RSSI/LQI provenance.
- Locks an ACK-owning node to the HCS026 telemetry channel; unassigned nodes
  scan both channels to broaden passive coverage.
- Supports the validated HCS026 automatic pairing profile without asking users
  for RF IDs. Unknown sensors require an explicit Home Assistant pairing flow.
- Recovers a known dormant sensor from its strict factory announcement with one
  bounded reply and preserves its existing HA identity.
- Accepts at most eight persistent sensor ACK assignments from the authenticated
  local gateway and restores all of them after reconnect or reboot.
- Starts with RF transmission disarmed and fails closed on timeout, network
  loss, unexpected pairing state, invalid command, or driver failure.
- Reports radio, heap, reset, temperature, loop-latency, network, Wi-Fi, OTA,
  pairing, and acknowledgement diagnostics every 30 seconds.
- Uses a temporary setup access point, Home Assistant discovery, BOOT-button
  physical confirmation, per-node credentials, and an Identify LED flow.
- Downloads OTA images only from its configured gateway, verifies size and
  SHA-256, requires gateway-plus-radio health confirmation, and rolls back
  after three unconfirmed boots. Release signatures remain future hardening.

## Build, flash, and monitor

Install PlatformIO and connect the ESP32 over USB-C:

```sh
pio run --project-dir firmware/rainpoint_bridge
pio run --project-dir firmware/rainpoint_bridge --target upload
pio device monitor --baud 115200
```

`rainpoint_bridge` is the only PlatformIO environment. CI builds the same image
and checks that obsolete local RF bench commands are absent while pairing,
ACK, and OTA capabilities are present.

The generic `esp32dev` board definition matches the tested board. If automatic
upload reset fails, hold **BOOT**, begin upload, and release it when PlatformIO
starts connecting.

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

```sh
python tools/firmware_manifest.py \
  firmware/rainpoint_bridge/.pio/build/rainpoint_bridge/firmware.bin \
  /tmp/rainpoint-radio-node-manifest.json \
  --version 0.11.0 --environment rainpoint_bridge
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

## Remaining hardware gates

- Accumulate at least 72 hours of unattended reporting with the stock gateway
  unavailable to the locally paired sensors.
- Test ACK-owner reassignment and interrupted/power-loss OTA rollback.
- Add signed releases and a reviewed secure session transport.
- Capture, reconstruct, and validate valve pairing and fail-safe close before
  enabling any physical valve control.
