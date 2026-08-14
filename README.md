# RainPoint Local

RainPoint Local is an open, local-first Home Assistant stack for RainPoint
433 MHz irrigation devices. It receives sensor and valve telemetry without the
vendor cloud, pairs and recovers supported soil sensors through custom radio
nodes, and preserves Home Assistant identity while a user migrates from the
stock RainPoint gateway.

Valve transmission is deliberately disabled until pairing, close commands, and
the independent safety controller have passed physical validation.

## What works today

### HCS02x soil sensors

- Decode moisture, confirmed full/low battery state, report time, RF endpoint,
  signal provenance, and reporting cadence from local RF.
- Discover compatible sensors by protocol evidence rather than household IDs.
- Pair HCS026-class sensors from the Home Assistant UI without asking users to
  copy RF identities or credentials.
- Derive the stable paired endpoint from the factory announcement and retain an
  existing HA device/entity history during reassociation.
- Recover a known dormant sensor with a long press and one bounded gateway
  reply—no battery removal, HA deletion, or open pairing window.
- Persist exactly one custom radio-node ACK owner per sensor and restore all
  assignments after gateway, network, radio-node, or OTA restart.
- Deduplicate reception from multiple Wi-Fi radio nodes and an optional SDR
  while retaining per-receiver coverage metrics.

The generalized pairing path and routine acknowledgement behavior have been
physically validated across independent HCS026 identities and the existing bed
sensors. Multiple sensors can share pairing selector 4; selectors are not
device slots.

### Radio nodes

- One standard ESP32/CC1101 firmware image supports receive, sensor pairing,
  known-sensor recovery, persistent ACK assignments, Identify, diagnostics,
  Wi-Fi commissioning, and managed OTA.
- New nodes create a temporary Wi-Fi setup portal, are discovered in Home
  Assistant, and use the ESP32 BOOT button for physical adoption confirmation.
- Each node has an independent credential and makes an outbound authenticated
  connection to the local gateway, allowing nodes to be placed near different
  garden areas.
- OTA images are size/SHA-256 checked, health-confirmed after reboot, and use a
  three-unconfirmed-boot rollback policy.

### Valve telemetry and safety groundwork

- Decode the tested HTV145 frame family, open/closed state, configured duration,
  last-session duration, and water usage.
- Correlate local RF valve events with Home Assistant/cloud observations.
- Exercise a hardware-independent fail-closed controller for startup state,
  open acknowledgement, client loss, run deadlines, watchdog expiry, close
  retries, and persistent faults.

The physical valve-control boundary still rejects all requests.

## Architecture

```text
HCS02x sensors / HTV145 valve
              |
           433 MHz
              |
   +----------+-----------+
   |                      |
ESP32 + CC1101 nodes   optional RTL-SDR
   | authenticated Wi-Fi  | receive-only
   +----------+-----------+
              |
          rainpointd
  protocol + registry + ACK ownership
              |
       versioned local API
              |
 Home Assistant rainpoint_local
```

The transport boundary is intentionally generic: HA consumes the same devices
whether a frame arrived through a radio node or the SDR. A sensor may be heard
by many receivers, but only its explicitly assigned custom node may transmit an
acknowledgement.

## Components

1. `custom_components/rainpoint_local` — HACS-compatible Home Assistant custom
   integration.
2. `rainpointd_addon` — Home Assistant app/add-on that owns protocol decoding,
   persistence, radio-node sessions, pairing, ACK ownership, and OTA artifacts.
3. `firmware/rainpoint_bridge` — the single supported ESP32/CC1101 radio-node
   firmware.
4. `hardware/rainpoint_carrier` — passive carrier PCB design for the tested
   ESP32 and 8-pin CC1101 module.

## Home Assistant installation

HACS can install the custom integration but cannot run the gateway service.
For development on Home Assistant OS:

1. Copy `rainpointd_addon` to `/addons/rainpointd`.
2. Reload the app store and install **RainPoint Local Gateway**.
3. Copy `custom_components/rainpoint_local` into the HA configuration directory
   or install it through HACS.
4. Restart Home Assistant and add **RainPoint Local**.

Supervisor discovery provisions the integration’s management credential. Users
do not paste that credential during sensor pairing or radio-node adoption.

Pair a sensor from **Settings → Devices & services → RainPoint Local →
Configure**. Select the radio node closest to that sensor. Temporarily power off
the stock RainPoint gateway during the exchange to prevent two transmitters
from racing; reconnect it afterward if cloud-controlled valves still depend on
it. Do not delete an existing HA sensor before reassociation.

See [NODE_ONBOARDING.md](NODE_ONBOARDING.md) for radio-node setup and
[firmware/rainpoint_bridge/README.md](firmware/rainpoint_bridge/README.md) for
wiring, flashing, recovery, and OTA details.

## Development

Run the local gateway with replay fixtures:

```sh
PYTHONPATH=rainpointd_addon python3 -m rainpointd
```

Run it with a receive-only RTL-SDR and `rtl_433`:

```sh
PYTHONPATH=rainpointd_addon python3 -m rainpointd \
  --transport rtl433 --host 0.0.0.0
```

Run the complete Python regression suite:

```sh
python3 -m unittest -v \
  test_rainpoint_protocol.py \
  test_rainpoint_pairing.py \
  test_rainpoint_pairing_protocol.py \
  test_esp32_network.py \
  test_rainpoint_network_transport.py \
  test_integration_migration.py \
  test_api_models.py \
  test_addon_boundaries.py \
  test_firmware_manifest.py \
  test_firmware_catalog.py \
  test_rainpointd.py \
  test_rainpoint_rf.py \
  test_rainpoint_analysis.py \
  test_rainpoint_safety.py \
  test_pairing_profile_analysis.py \
  test_radio_node_acceptance.py \
  test_rf_trial.py
```

Build the one supported radio-node image:

```sh
pio run --project-dir firmware/rainpoint_bridge
python tools/check_firmware_boundaries.py \
  firmware/rainpoint_bridge/.pio/build/rainpoint_bridge/firmware.bin
```

Automated tests remain intentionally comprehensive: they preserve the captured
RF evidence and safety invariants while obsolete experimental firmware forks
have been removed.

## Evidence and portability

Friendly names and dashboards for the original installation live only under
`examples/federico-garden`. Runtime behavior is driven by persistent registry
records and protocol/product evidence, not those names or endpoints.

- [PROTOCOL.md](PROTOCOL.md) — supported RF facts, confidence, and unresolved
  fields.
- [FULL_STACK_ARCHITECTURE.md](FULL_STACK_ARCHITECTURE.md) — component and
  transport responsibilities.
- [CLOUD_TO_LOCAL_MIGRATION.md](CLOUD_TO_LOCAL_MIGRATION.md) — proposed
  cloud-to-local identity-preserving migration.
- [research/DEVICE_PAIRING_VALIDATION_PLAN.md](research/DEVICE_PAIRING_VALIDATION_PLAN.md)
  — retained physical evidence and remaining hardware gates.

Cloud-specific investigation is isolated under `research/cloud` and is not a
runtime dependency.

## Remaining gates

- Accumulate a multi-day unattended sensor reliability baseline and perform a
  controlled ACK-owner reassignment.
- Improve final radio-node placement where Wi-Fi or RF margins are weak.
- Add encrypted node sessions, credential rotation, and asymmetric OTA release
  signatures before treating the trusted-LAN prototype as publishable.
- Capture and validate generic valve enrollment, close, status, and bounded
  open behavior on isolated test hardware.
- Only then connect physical valve commands to the safety controller and begin
  cloud-to-local migration work with the existing HomGar integration.

## Safety

RainPoint Local currently receives valve telemetry but cannot operate a valve.
Future control must always enforce bounded duration, explicit target identity,
positive acknowledgement, fail-closed startup, independent watchdog timing,
close retries, and persistent fault reporting. Never test unknown RF commands
against an installed irrigation zone without isolation and a ready manual stop.
