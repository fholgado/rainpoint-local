# RainPoint Local

A local Home Assistant stack for RainPoint 433/434 MHz irrigation devices.
ESP32/CC1101 radios communicate with the devices; `rainpointd` owns decoding,
associations, ACK ownership, counters, and safety; the HA integration exposes
telemetry and qualified controls. Normal operation does not need the vendor cloud
or an SDR.

**Alpha 1 is available — sensors and both valve families.**
Start with [Getting started: agent-assisted setup](GETTING_STARTED.md).
Give the guide to your agent to install the gateway and integration, help flash
your radio, and hand you off to device pairing in Home Assistant.
Download [Alpha 1 (`v0.18.0-alpha.1`)](https://github.com/fholgado/rainpoint-local/releases/tag/v0.18.0-alpha.1).
Use gateway **0.39.0**, HA integration **0.18.0** and signed radio firmware
**0.19.0** together. See [release notes and known limitations](docs/ALPHA_1.md).
We're inviting builders to help validate fresh installs and device lifecycle
behavior; alpha does not mean those remaining tests have already passed.

## Device support

| Family | Current capability | Limit |
|---|---|---|
| HCS02x / HCS026FRF | Pair, recover, moisture, categorical battery, persistent ACK owner | Full lifecycle/coexistence soak remains open |
| HTV405FRF | Local pairing, four zones, 1–60 minute controls, ACKs, idle counter sync | Supervised experimental use; battery unavailable; no water-usage capability |
| HTV145FRF | State, duration, usage, categorical battery, bounded HA controls/ACKs/sync | Verified partial association; field qualification ongoing |

Read [device communication references](protocol_documentation/) for packet rules
and [the roadmap](PROJECT_ROADMAP.md) for remaining qualification work.

## Install on Home Assistant OS

Install **RainPoint Local Gateway** from HA's app/add-on repository and
**RainPoint Local** from HACS. Both use this repository URL; HACS installs only
the integration, not the gateway or radio firmware. The
[getting-started guide](GETTING_STARTED.md) walks your agent through installation,
USB flashing and Wi-Fi adoption, then guides you through pairing in HA.

The existing HomGar/RainPoint cloud integration is not required or replaced.
For detailed settings or recovery, see the [add-on guide](rainpointd_addon/DOCS.md)
and [firmware guide](firmware/rainpoint_bridge/README.md).

## Operation

HA watering notifications are enabled by default; mobile forwarding is optional.
See [notification behavior](docs/ALPHA_NOTIFICATIONS.md). These features and
fresh-pairing counter initialization are deployed in the reference installation;
independent clean-install and physical onboarding acceptance remain separate.

Each device has one persistent transmitting ACK owner; other radios may receive
and forward reports. Firmware restores assignments after reconnect. HA state
comes from device responses or independent telemetry, not command intent.

Valve actuation requires a supported paired device and a capable, available owner;
no research switch or mandatory two-run unlock is required. Counter readiness and
device-response confirmation still apply. Both valve families expose counter
status and morning synchronization settings. Each single-zone association has
its own control, duration and persisted counter state.

Both families enforce bounded durations, command spacing, and durable command
reservations. Startup and missing telemetry never send a speculative close.
Unknown counters block ordinary control until explicit recovery is confirmed.

## Development

Use the canonical checkout and Git branches; do not create additional worktrees.

```sh
PYTHONPATH=rainpointd_addon python3 -m rainpointd
```

This starts an empty network gateway. Use the explicit
[captured replay example](examples/captured-replay/) for offline sample data. See [local development](LOCAL_DEVELOPMENT.md)
for runtime options and [AGENTS.md](AGENTS.md) for the complete required Python
and native regression commands. Install the development test dependencies with
`python3 -m pip install -r tests/requirements.txt` in a virtual environment first.
Build only the `rainpoint_bridge` PlatformIO
environment; production must exclude experimental transmit paths.

## Documentation map

| Need | Document |
|---|---|
| Agent-assisted installation, flashing and HA pairing | [Getting started](GETTING_STARTED.md) |
| Alpha 1 versions, downloads and known limitations | [Alpha 1](docs/ALPHA_1.md) |
| Node parts and Amazon shopping links | [Quick BOM](GETTING_STARTED.md#quick-bom-per-radio-node) |
| Fresh installation tests without household devices | [Isolated HA testing](docs/ISOLATED_HA_TESTING.md) |
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

See [security boundaries](SECURITY.md) before deploying or exposing listeners.
