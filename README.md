# RainPoint Local

RainPoint Local is an open, local-first Home Assistant stack for RainPoint
433 MHz irrigation devices. It receives sensor and valve telemetry without the
vendor cloud, pairs and recovers supported soil sensors through custom radio
nodes, and preserves Home Assistant identity while a user migrates from the
stock RainPoint gateway.

Supervised HTV405 control is available as a disabled-by-default beta. Local
enrollment, isolated one- and two-minute opens on all four zones, and Zone 1
early stop have passed physical validation, including direct valve responses,
automatic stop, and controller-counter progression. The gateway and HA expose
1--60 whole-minute bounded runs; durations longer than two minutes remain a
field-acceptance gate. Enabling the beta adds four HA valve entities and four
duration controls, and requires compatible supervised firmware on the valve's
assigned radio node.

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

### Valve telemetry and supervised control

- Locally enroll the isolated HTV405 through a bounded, association-specific
  transcript without the stock RainPoint gateway.
- Open every HTV405 zone for physically validated one- and two-minute runs and
  early-close the confirmed active Zone 1 on the enrolled selector-2 carrier,
  accepting state only from the valve's authenticated response or later
  telemetry.
- Configure the next run independently for each zone from 1--60 whole minutes;
  longer encodings are regression-tested while installed field acceptance is
  still pending.
- Track the independent controller command counter from matching valve replies;
  routine telemetry cannot overwrite it.
- Decode the tested HTV145 frame family, open/closed state, configured duration,
  last-session duration, and water usage.
- Separate HTV145 command and telemetry counters, model a stock command as one
  logical operation with a bounded burst of identical RF attempts, and persist
  an at-most-once candidate reservation across gateway restarts.
- Run the isolated HTV145 one-shot acceptance harness through a separate,
  disabled-by-default research gate; it is token-protected and intentionally
  absent from the Home Assistant entity/control model. Its first correct-
  channel transmission was independently received but the already-low-battery
  valve remained silent, so fresh-battery physical acceptance is still open.
- Correlate local RF valve events with Home Assistant/cloud observations.
- Exercise a hardware-independent duration-bounded controller: startup and
  client loss are observation-only, missing acknowledgements block further
  commands, explicit early-stop can retry, and only a positively observed
  overdue run can trigger an anomaly close.

The gateway/HA valve-control boundary rejects all requests unless the explicit
`supervised_htv405_control` option is enabled. Even then, it requires an
authenticated candidate node, a complete durable association, an
evidence-synchronized command counter, and no command already pending.
The HTV145 transmitter implementation is compiled out of standard firmware and
remains undeployed pending supervised acceptance with the isolated dry valve.

## Architecture

```text
HCS02x sensors / HTV405 and HTV145 valves
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
- [research/FOUR_ZONE_VALVE_TEST_PLAN.md](research/FOUR_ZONE_VALVE_TEST_PLAN.md)
  — receive-only enrollment and crossed zone/duration capture sequence for the
  isolated four-zone test valve.
- [research/VALVE_PROTOCOL_STATUS.md](research/VALVE_PROTOCOL_STATUS.md) —
  concise confirmed-versus-pending evidence ledger for both valve families.

Cloud-specific investigation is isolated under `research/cloud` and is not a
runtime dependency.

## Remaining gates

- Accumulate a multi-day unattended sensor reliability baseline and perform a
  controlled ACK-owner reassignment.
- Improve final radio-node placement where Wi-Fi or RF margins are weak.
- Add encrypted node sessions, per-node credential rotation, replay protection,
  and asymmetric OTA release signatures before treating the trusted-LAN
  prototype as publishable.
- Complete the installed HTV405 Zone 1 longer-duration field run and retain its
  authenticated response, active report, valve-owned automatic stop, usage,
  Home Assistant completion notification, and watchdog outcome.
- Physically verify observation-only recovery after gateway and radio-node
  restarts; the association profile, authenticated controller counter, and
  expected completion of an active bounded run are stored separately from
  lower-channel telemetry.
- Physically exercise explicit local early-stop on Zones 2--4, late-response
  recovery, and positively observed overdue-run anomaly close while preserving
  the enforced 15-second hardware command interval.
- Physically accept the separate HTV145 long-wake path: explicit association
  residue, one bounded three-attempt burst, immediate-response/state-report
  fallback, durable command counter, restart without replay, and valve-owned
  automatic stop. Correct channel-11 transmission is captured; repeat with
  fresh valve batteries to establish valve acceptance.
- Validate retained association and authenticated controller-counter recovery
  across a battery change, and capture an independently known low-battery RF
  transition before exposing valve battery state.
- Generalize the local association/control evidence with another valve before
  beginning cloud-to-local migration work with the existing HomGar integration.
- Physically validate the staged, durably persisted custom RF controller
  identity with a disposable sensor, then prove stock/custom device-cohort
  coexistence before exposing the generalized Home Assistant valve pairing
  flow. Existing assignments retain their original controller identity; the
  `39840280` companion route remains retained-association evidence rather than
  the default for a new local enrollment.

Start and finish the sensor reliability gate with persisted snapshots rather
than screenshots:

```bash
python3 tools/sensor_soak.py prepare \
  --gateway-url http://homeassistant.local:8787 \
  --output captures/sensor-soak-start.json

python3 tools/sensor_soak.py finish captures/sensor-soak-start.json \
  --gateway-url http://homeassistant.local:8787 \
  --minimum-hours 72 \
  --output captures/sensor-soak-report.json
```

The report requires every starting soil sensor to remain registered and fresh,
advance at least once per effective 30-minute interval, and retain enough
connected authenticated ACK-owner capacity. Snapshot outputs remain local
evidence under the ignored `captures/` directory.

## Safety

RainPoint Local remains receive-only by default. The supervised HTV405 beta
enforces bounded duration, explicit target identity, authenticated node state,
durable at-most-once command reservations, and valve-originated confirmation.
Restart, client loss, and missing telemetry do not generate RF traffic, and a
failed or ambiguous command does not trigger an immediate retry. A timed-out
bounded HTV405 open can retain only the same and next counter as candidates for
a later explicit request, after the entire possible run plus a guard interval;
unexpected watering or an explicit transport/response failure cancels that
path. Never
test unknown RF commands against an installed irrigation zone without
isolation and a ready manual stop.
