# RainPoint Local

A local Home Assistant stack for RainPoint 433/434 MHz irrigation devices.
ESP32/CC1101 radios communicate with the devices; `rainpointd` owns decoding,
associations, ACK ownership, counters, and safety; the HA integration exposes
telemetry and qualified controls. Normal operation does not need the vendor cloud
or an SDR.

## Device support

| Family | Current capability | Limit |
|---|---|---|
| HCS02x / HCS026FRF | Pair, recover, moisture, categorical battery, persistent ACK owner | Full lifecycle/coexistence soak remains open |
| HTV405FRF | Local pairing, four zones, 1–60 minute controls, ACKs, idle counter sync | Supervised beta; battery unavailable; no water-usage capability |
| HTV145FRF | State, duration, usage, categorical battery, dry-test controls/ACKs/sync | Partial local association; ordinary HA actuation not promoted |

Read [device communication references](protocol_documentation/) for packet rules
and [the roadmap](PROJECT_ROADMAP.md) for qualification gates. A supported codec
or successful RF transmission is not proof of physical acceptance.

## Install on Home Assistant OS

HACS installs the integration; the gateway service is a separate app/add-on.

1. Copy `rainpointd_addon` to `/addons/rainpointd`, reload the app store, and install
   **RainPoint Local Gateway**.
2. Install `custom_components/rainpoint_local` through HACS or copy it into HA's
   custom components directory, then restart HA.
3. Add **RainPoint Local**. Supervisor discovery provisions its management credential.
4. Follow [radio onboarding](NODE_ONBOARDING.md) to commission and adopt a radio.
5. Use the integration's **Configure** flow to add a supported device. Choose the
   nearest suitable radio and power off the stock gateway during local enrollment.
   Known devices retain their saved name, area, and canonical identity.

Back up HA before changing configuration. Keep source backups under
`/share/rainpoint-local/source-backups`, outside `/addons`, and exclude macOS
`._*` files. See the [add-on guide](rainpointd_addon/DOCS.md) for settings and
[firmware guide](firmware/rainpoint_bridge/README.md) for wiring and recovery.

## Operation

Each device has one persistent transmitting ACK owner; other radios may receive
and forward reports. Firmware restores assignments after reconnect. HA state
comes from device responses or independent telemetry, not command intent.

Four-zone actuation requires the explicit `supervised_htv405_control` option and
a capable owner. Default starts use a fixed-zero counter anchor before watering.
Optional morning synchronization allows direct daytime starts with a retained
counter. One-zone counter status and morning settings are available on its
qualified owner, while actuation remains behind the isolated dry-test gate.

Both families enforce bounded durations, command spacing, and durable command
reservations. Startup and missing telemetry never send a speculative close.
Unknown counters block ordinary control until explicit recovery is confirmed.

## Development

Use the canonical checkout and Git branches; do not create additional worktrees.

```sh
PYTHONPATH=rainpointd_addon python3 -m rainpointd
```

This starts the replay-backed gateway. See [local development](LOCAL_DEVELOPMENT.md)
for runtime options and [AGENTS.md](AGENTS.md) for the complete required Python
and native regression commands. Build only the `rainpoint_bridge` PlatformIO
environment; production must exclude experimental transmit paths.

## Documentation map

| Need | Document |
|---|---|
| Packet layouts, ACKs, counters | [Protocol references](protocol_documentation/) |
| Current work and physical gates | [Roadmap](PROJECT_ROADMAP.md) |
| Responsibilities and boundaries | [Architecture](FULL_STACK_ARCHITECTURE.md) |
| HA settings and operation | [Add-on guide](rainpointd_addon/DOCS.md) |
| Radio commissioning | [Node onboarding](NODE_ONBOARDING.md) |
| Research procedures and evidence | [Research index](research/README.md) |
| Proposed cloud migration | [Migration design](CLOUD_TO_LOCAL_MIGRATION.md) |
| Explicit household examples | [Examples](examples/federico-garden/) |

Installation-specific captures, databases, credentials, and build output stay
untracked. Preserve raw captures until useful exchanges have redacted fixtures.
