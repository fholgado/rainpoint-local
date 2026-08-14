# RainPoint Local hardening inventory

This inventory distinguishes the working local prototype from requirements for
publication or physical valve control. Historical experiments belong under
`research/`; normal operators should encounter one gateway, one integration,
and one radio-node firmware.

## Consolidated in this baseline

- One PlatformIO environment, `rainpoint_bridge`, replaces the receive-only,
  dual-radio, bench, identity-specific pairing, ACK, and unified candidates.
- The standard firmware contains receive, HCS026 pairing/recovery, persistent
  ACK ownership, commissioning, diagnostics, Identify, and OTA. It contains no
  serial RF probe commands or valve command path.
- Runtime device identity comes from the persistent registry and protocol
  evidence. Original-house names and dashboards are isolated under `examples`.
- Pairing requires no copied RF ID or management token and preserves existing
  HA identity during reassociation.
- Each sensor has at most one custom ACK owner; all assignments are restored
  after node reconnect or OTA reboot.
- Captured frames remain immutable regression fixtures. Automated tests remain
  because they are the executable evidence and safety boundary, not alternative
  product variants.

## Runtime boundaries still to harden

| Area | Current boundary | Publication requirement |
|---|---|---|
| Node transport | Mutual nonce/HMAC authentication over trusted-LAN TCP | Encryption, per-session integrity/replay handling, rotation, and revocation |
| Gateway API | Versioned HTTP API with bearer-authenticated mutations | Typed schemas/errors, scoped credentials, rate/resource limits, reviewed server transport |
| OTA | Gateway-hosted, size/SHA-256 checked, health-confirmed rollback | Asymmetric release signatures plus interrupted/power-loss rollback tests |
| HA updates | Five-second coordinator polling | Event-driven updates with slow reconciliation |
| Device lifecycle | Persistent registry, suppression, reassociation, stable IDs | HA-native config-flow/entity/device-registry test harness and formal migrations |
| Packaging | HA app supports network nodes and optional SDR | Reproducible pinned build and narrower network-only publication profile |
| Protocol core | Transport-neutral ingestion but dictionary-heavy models | Installable typed protocol/identity package independent of HA and installation names |
| Sensor operations | Physically validated pairing, recovery, and ACKs | Multi-day soak, owner reassignment, coexistence, and wider hardware-revision evidence |
| Valve operations | Local decode and offline safety state machine | Isolated pairing, close-first test, bounded open, watchdog, and audited fail-closed integration |

## Repository disposition

- `custom_components/rainpoint_local`: HA adapter and UI.
- `rainpointd_addon/rainpointd`: local gateway, persistence, association, node,
  and command authority.
- `firmware/rainpoint_bridge`: sole supported radio firmware.
- `research/fixtures`: captured protocol evidence used by regression tests.
- `research/cloud`: historical cloud investigation, never a runtime dependency.
- `tools`: developer capture, analysis, artifact, and acceptance utilities.
- `examples/federico-garden`: explicitly house-specific dashboard/configuration.
- ignored `captures/`, `.pio/`, databases, and installed upstream snapshots:
  local evidence/build inputs that must not enter normal clones.

## Deliberately retained tests

The Python and C++ suites protect decoding, pairing state, endpoint derivation,
ACK generation, persistence, API authorization, OTA integrity, multi-receiver
deduplication, and valve safety. Removing these would erase the evidence that
made consolidation safe. CI therefore builds one firmware image but continues
running the full protocol and safety regression matrix.

## Next cleanup boundary

Do not perform architecture work intended for the eventual HomGar merge yet.
First finish the sensor reliability baseline and the end-to-end test-valve
prototype. After that gate, extract provider-neutral models and coordinate the
identity/authority migration described in `CLOUD_TO_LOCAL_MIGRATION.md`.
