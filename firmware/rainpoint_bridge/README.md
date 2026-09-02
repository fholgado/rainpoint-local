# RainPoint radio-node firmware

This directory contains the single supported ESP32/CC1101 firmware for
RainPoint Local. One node receives RainPoint RF telemetry, performs bounded
HCS026 soil-sensor pairing and recovery, sends acknowledgements only for
gateway-assigned sensors, and installs integrity-checked OTA updates.

The standard build does **not** expose valve control and no build permits
arbitrary RF transmission. The same source can produce an explicitly gated
supervised HTV405 build. Its association-specific commands are accepted only
from an authenticated protocol-v2 gateway with the matching beta enabled and
the valve assigned to that node.

The source tree also contains the physically validated HTV405 enrollment
implementation. It can run only after the authenticated gateway supplies the
factory endpoint and both association routes, and it matches the captured
request sequence exactly. The sequence has 18 valve-originated steps and 17
bounded gateway replies; one step intentionally advances without transmitting.
Home Assistant offers this pairing flow only when a compatible supervised node
is online.

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
- Compiles the association-specific HTV405 enrollment implementation. The
  supervised build also accepts the bounded `valve_control_tx_candidate`
  command vocabulary for 1--60 whole-minute opens on Zones 1--4 and Zone 1
  early-close. One- and two-minute opens and a 20-minute Zone 1 run are
  physically validated. Control requires explicit association
  identities, a persisted response-authenticated counter, and the calibrated
  carrier profile.
- Contains a separate HTV145 single-zone candidate behind both
  `RAINPOINT_RESEARCH_BENCH=1` and `RAINPOINT_HTV145_TX_CANDIDATE=1`. It uses
  the retained 1,200-symbol wake and one bounded three-attempt RF burst,
  accepts only explicit association endpoints/carrier/residue, and advances
  its command counter only from a matching response or independent state
  confirmation. The standard image compiles this path out.
- Contains a separately gated HTV145 pairing profile behind
  `RAINPOINT_HTV145_PAIRING_CANDIDATE=1`. It reproduces the complete captured
  six-stage enrollment, including the delayed 2,400-symbol controller command
  and temporary routine-carrier receive window, without changing HTV405
  enrollment. Keep it on the OTA test node until physical acceptance.
- The HTV145 candidate reports bounded-attempt evidence separately from its
  verdict: attempts started/sent, matching-route and invalid-trailer frames,
  classified response/state frames, response and state outcomes, a precise
  failure class, and whether the command counter is ambiguous. These fields
  feed the disabled dry-valve acceptance transcript; they are not a public
  actuator interface.
- Keeps valve control absent from standard builds. In a supervised build, the
  gateway/HA boundary is disabled by default, token-protected, and restricted
  to the assigned HTV405 association. The coordinator spaces operations by at
  least 15 seconds, never advances state from transmit success, and never emits
  a speculative startup or counter-recovery command.
- Recovers a known dormant sensor from its strict factory announcement with one
  bounded reply and preserves its existing HA identity.
- Accepts at most eight persistent sensor ACK assignments from the authenticated
  local gateway and restores all of them after reconnect or reboot.
- Accepts an association-specific controller/companion identity from the
  authenticated gateway for pairing, recovery, and routine ACKs. Firmware with
  this boundary advertises `configurable_rf_controller_identity`; the gateway
  refuses to give a custom-identity association to an older node.
- Starts with RF transmission disarmed and fails closed on timeout, network
  loss, unexpected pairing state, invalid command, or driver failure.
- Accepts authenticated maintenance commands for a bounded 60--3,600 second
  receive-only interval. Reception, normalized logging, Wi-Fi, diagnostics,
  Identify, and maintenance remain active, while a CC1101 driver guard blocks
  every pairing, acknowledgement, and valve-control transmission. The node
  automatically restores normal mode when the interval expires.
- Supports authenticated remote reboot. A reboot intentionally returns to
  normal RF mode so a forgotten maintenance interval cannot silently disable
  irrigation support after power recovery.
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

The default build is production-safe and compiles out all valve-control
transmitters and research commands. For an explicitly authorized supervised
HTV405 node, build the same environment with only the bounded control profile
enabled:

```sh
RAINPOINT_SUPERVISED_HTV405_CONTROL=1 \
  RAINPOINT_FIRMWARE_VERSION=0.15.0-supervised-beta.12 \
  pio run --project-dir firmware/rainpoint_bridge
```

This supervised image retains the authenticated, association-specific HTV405
control boundary without compiling legacy serial RF probes. Keep it on the
experimental OTA channel until the qualification gates in
`../../PROJECT_ROADMAP.md` are complete.

The unaccepted HTV145 candidate requires an additional explicit build gate:

```sh
RAINPOINT_RESEARCH_BENCH=1 \
  RAINPOINT_HTV145_TX_CANDIDATE=1 \
  RAINPOINT_FIRMWARE_VERSION=0.15.0-htv145-control-candidate.3 \
  pio run --project-dir firmware/rainpoint_bridge
```

Do not deploy that artifact before the isolated dry-valve acceptance session.

The independently gated HTV145 pairing candidate is built with:

```sh
  RAINPOINT_RESEARCH_BENCH=1 \
  RAINPOINT_HTV145_PAIRING_CANDIDATE=1 \
  RAINPOINT_FIRMWARE_VERSION=0.15.3-htv145-pairing-probe.25 \
  pio run --project-dir firmware/rainpoint_bridge
```

This isolated probe implements the controlled app-first stock transcript in a
dedicated HTV145 module with its own profile, matcher, state machine, reply
builder, timing, and frequency calibration. It answers only factory counter 0,
assigns selector 6 and response subchannel 12, and requires the exact addressed
stage-1 request before continuing the six-stage exchange. A later factory
announcement is a terminal stage-0 rejection; it can never trigger a second
assignment. Arm before the physical gesture so normal setup starts with counter
0; no operator timing against the LED sequence is required.
Probe `.25` preserves the `.24` RF waveform and one-shot state machine. It
corrects the counter-0 packed clock after direct `.24` evidence showed that
the former marker preservation cleared the FAT/DOS high-hour bit after 4 PM.
Only bit 7 of the time-low byte is the captured counter-0 branch marker; the
time-high and date bytes retain their encoded data bits.

The measured post-frame-tail candidate has one further, separately required
gate:

```sh
RAINPOINT_RESEARCH_BENCH=1 \
  RAINPOINT_HTV145_PAIRING_CANDIDATE=1 \
  RAINPOINT_HTV145_POST_FRAME_TAIL_CANDIDATE=1 \
  pio run --project-dir firmware/rainpoint_bridge
```

It changes only stage-zero transmitter shutdown: after the ordinary frame it
keeps the already-low data input and PA active for another `115 us` before
`SIDLE`. Production, supervised HTV405, ordinary `.25`, and later HTV145 stages
retain a zero hold. Do not stage or flash this artifact until a fresh accepted
stock capture reproduces the retained approximately `160 us` low-tone tail and
the roadmap explicitly authorizes the physical discriminator.
Probe `.24` preserved the `.23` counter-0 transcript, scheduler, calibrated
carrier, and deviation unchanged. It only applies a dedicated research-profile
calibration guard so the evidenced `122.759 kHz` correction can pass the node's
command validation; the generic sensor and HTV405 bound remains unchanged.
Probe `.23` preserved the counter-0 transcript and scheduler from `.22`, while
correcting the initial assignment to the stock gateway's balanced-wake
`0x45` deviation profile and its carrier position relative to the valve's own
factory request oscillator.
Deploy this image only
to the designated OTA test node until three consecutive
pairings satisfy the roadmap's physical acceptance gate.

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

Production and supervised builds report the `unified` firmware variant.
Research-only HTV145 probes report a distinct variant and must never be staged
as compatible with `unified` nodes.

```sh
python tools/firmware_manifest.py \
  firmware/rainpoint_bridge/.pio/build/rainpoint_bridge/firmware.bin \
  /tmp/rainpoint-radio-node-manifest.json \
  --version 0.15.3 --environment rainpoint_bridge
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
