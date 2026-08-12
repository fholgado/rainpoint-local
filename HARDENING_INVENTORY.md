# RainPoint Local hardening and abstraction inventory

## Purpose

This document inventories prototype, research, diagnostic, house-specific, and
production-facing code after the first successful end-to-end local HCS026
pairing through Home Assistant.

Snapshot reviewed and deployed on 2026-08-11:

- `rainpointd` add-on 0.14.0
- `rainpoint_local` integration 0.4.0
- ESP32 bridge firmware 0.5.0
- authenticated Wi-Fi node protocol v2
- successful local enrollment of factory endpoint `15a98024`
- persistent registry-backed HCS026 identity and removal policy
- SQLite-backed enrollment state with one-time legacy JSON migration
- versioned SQLite schema, durable device snapshots, bounded event retention,
  and receiver-specific coverage metrics
- integration-owned entity disabling for gateway-removed devices
- persistent managed radio-node identities and HA diagnostic devices

The objective is not to discard the research record. Captures, recovered
fixtures, and safety tests are evidence that should remain reproducible. The
objective is to keep evidence and experimental controls out of generic runtime
paths unless they are explicitly enabled and accurately represented as
capabilities.

## Gateway and node credentials

Two independent credentials exist:

1. A per-node token authenticates each custom ESP32 radio node to `rainpointd`
   with mutual nonce/HMAC proofs.
2. The `registry_write_token` authenticates Home Assistant requests that mutate
   the local registry or arm the bounded sensor-pairing transmitter.

The second credential is now generated in private add-on data and delivered to
the integration through supported Supervisor discovery. It no longer appears
in ordinary sensor pairing. A separate one-time authentication step remains for
standalone gateways that do not run under Home Assistant Supervisor.

Remaining target behavior:

- formalize credential rotation and revocation after onboarding;
- show a repair or reauthentication flow only when the credential is missing,
  revoked, or rotated;
- support a one-time setup code or physical confirmation for a standalone
  custom local gateway;
- retain supported Supervisor discovery when the gateway and integration run
  on the same Home Assistant installation;
- maintain independent, revocable credentials for every radio node.

`Authenticate gateway` is now separate from `Pair a sensor`. If a credential is
already stored, the pairing form omits the field entirely. The remaining
standalone-gateway work is a generic one-time claim exchange that replaces
manual credential copying outside Supervisor installations.

## Classification

- **Production candidate**: intended to remain in the published runtime after
  hardening.
- **Experimental runtime**: useful executable prototype that must be isolated
  behind an explicit capability or build flag.
- **Research tooling/evidence**: valuable for protocol work and regression
  tests, but not part of a normal installation.
- **House-specific example**: useful locally or as an example, but must not
  determine device identity or behavior for other users.

## Highest-priority findings

| Priority | Finding | Current impact | Required direction |
| --- | --- | --- | --- |
| In progress | TX supports only factory `15a98024` and paired identity `95a98024` | The UI now describes this as a validated HCS026 test-sensor profile rather than generic pairing, but broader sensors remain unsupported | Move profiles into a model/profile registry after a second identity is physically validated |
| In progress | Live receive code previously owned this house's sensor names and singleton valve state | Persistent HCS026 registry entries now layer over the compatibility catalog, immediately drive decoding, and preserve established HA IDs; independent per-valve state is supported | Represent valve endpoint links in the registry, then retire the explicit legacy compatibility profile through a versioned migration |
| P1 | Development replay and raw capture controls still ship in the add-on, although new installs now default to empty `network` mode | The normal image remains broader than a published production package needs | Create explicit development and production profiles/images; keep replay and broad capture out of the published image |
| P0 | Supervisor discovery now provisions the gateway bearer credential automatically, but standalone setup is manual and HTTP remains plaintext | Add-on UX is fixed; standalone onboarding, rotation, scoped access, and transport confidentiality remain incomplete | Add one-time standalone claim, credential rotation, scoped operations, and a reviewed encrypted transport or HA-local authenticated channel |
| P0 | Node protocol authenticates the connection but subsequent TCP messages are neither encrypted nor individually authenticated | Appropriate only for the current trusted-LAN prototype | Define a production session transport with confidentiality, integrity, replay handling, and key rotation before valve control |
| In progress | Forget/delete semantics previously spanned SQLite, pairing JSON, memory, and HA registries | Enrollment mappings now migrate once into SQLite; gateway forget atomically removes registry and enrollment rows, persists suppression, removes current state, and HA integration-disables owned entities | Add HA-native lifecycle tests and define eventual device-registry cleanup/retention policy |
| Completed | Production firmware excludes physical serial probe, tuning, and pairing-arm controls | Local TX bench controls exist only in `esp32dev_single_bench`, and CI inspects binaries for leakage | Keep the research target explicit and the authenticated network command boundary narrow |
| Completed | Gateway identity used to change with the selected receiver transport | Add-on 0.9 persists identity independently and Supervisor discovery migrates legacy transport-derived config entries | Keep identity immutable across transport and radio-node changes |

## Runtime inventory

### Protocol and decoding

| Path | Classification | Finding | Disposition |
| --- | --- | --- | --- |
| `rainpointd_addon/rainpoint_protocol.py` | Production candidate | Core decoder is stored at the add-on root and imported through container path layout | Move to an installable, transport-neutral `rainpoint_protocol` package with typed decoded models and explicit compatibility tests |
| `rainpointd_addon/rainpointd/rf.py` | Mixed | Confirmed normalization now receives a device catalog instead of owning house endpoint constants; provisional fields and evidence commentary remain | Move provisional decoders behind evidence/status metadata and continue extracting typed protocol observations |
| `rainpointd_addon/rainpointd/valve_protocol.py` | Experimental runtime | Offline builders use this house's hub and valve endpoints | Parameterize endpoint identities and move builders into an explicitly experimental control package until physical TX is validated |
| `rainpointd_addon/rainpointd/pairing_protocol.py` | Experimental runtime/evidence | Embeds Sensor B's exact identities and three recovered reply frames | Preserve captured frames as fixtures; make runtime pairing profiles data-driven and capability-labelled, with no generic HCS026 claim yet |
| `research/fixtures/*.json` | Research evidence | Captures are used by regression tests and prove recovered behavior | Keep tracked, immutable, documented, and separated from mutable runtime state |

### Gateway service

| Path | Classification | Finding | Disposition |
| --- | --- | --- | --- |
| `rainpointd_addon/rainpointd/gateway.py` | Production candidate with prototype coupling | A roughly 900-line object owns devices, events, registry, pairing, nodes, learning, health, and command dispatch; it hard-codes the Sensor B profile and RF calibration | Split into protocol ingestion, device registry, association service, node manager, and capability/command service with explicit interfaces |
| `rainpointd_addon/rainpointd/rtl433.py` | Adapter with legacy defaults | Process management is separate from transport-neutral frame ingestion and observes live registry catalog changes, but `seed()` still creates compatibility devices before RF is heard | Remove compatibility seeding from publishable production mode after a versioned identity migration |
| `rainpointd_addon/rainpointd/ingest.py` | Production candidate | Provides one dynamically registry-backed frame-to-device/event path shared by SDR, serial, and network adapters, including independent per-valve state | Evolve its dictionary boundary into typed protocol observations and explicit lifecycle policy |
| `rainpointd_addon/rainpointd/replay.py` | Development | Maps fixtures to this house's device IDs and names | Retain for tests/development, but exclude from a normal production process and add-on default |
| `rainpointd_addon/rainpointd/esp32.py` | Thin transport adapter | Serial and network telemetry now publish through the transport-neutral `FrameIngestor` rather than instantiating an RTL-SDR process adapter | Keep message validation in the adapter and evolve shared ingestion toward typed observations |
| `rainpointd_addon/rainpointd/esp32_network.py` | Prototype production candidate | Mutual HMAC handshake and bounded commands are strong prototype boundaries; protocol v1 and bench capability vocabulary remain accepted; socket/thread code has only coarse message validation | Retire protocol v1 on a schedule, define typed message schemas, bound connection/thread resources, and replace trusted-LAN TCP before control |
| `rainpointd_addon/rainpointd/http.py` | Prototype API | Uses `ThreadingHTTPServer`; GET telemetry, nodes, endpoints, registry, and raw events are unauthenticated; write token is global; API errors are loosely typed | Define a versioned schema, scoped authentication, structured errors, rate/resource limits, and a production server or HA-native transport |
| `rainpointd_addon/rainpointd/safety.py` | Research/experimental | Good hardware-independent valve safety state machine, but it is not connected to command transport or hardware | Keep and clearly label as an unintegrated prerequisite; do not let tests imply production valve control exists |

### Persistence and lifecycle

| Path | Classification | Finding | Disposition |
| --- | --- | --- | --- |
| `rainpointd_addon/rainpointd/storage.py` | Production candidate | SQLite schema v4 adds transactional migration, durable snapshots, bounded retention, per-receiver coverage, and managed radio nodes while preserving device registry, suppression, and enrollment state | Keep future migrations additive and validate them against anonymized production-scale database fixtures in CI |
| `rainpointd_addon/rainpointd/pairing.py` | Production candidate | The state machine uses an enrollment repository; legacy JSON mappings are conflict-checked, imported once into SQLite, and archived as `.migrated` | Add schema-versioned migration coverage and keep transient pairing windows deliberately in memory |
| Gateway `_devices` memory | Prototype with removal policy | Accepted and compatibility devices remain observable; a persisted removed endpoint is retained as raw RF only and cannot recreate a device until accepted again | Expand this into explicit observed, paired, accepted, ignored, and removed states, then make HA exposure/reconciliation consume that policy |

### Add-on packaging

| Path | Classification | Finding | Disposition |
| --- | --- | --- | --- |
| `rainpointd_addon/config.yaml` | Mixed | New installs default to empty network mode, but the package still exposes replay/research capture, accepts node credentials as a JSON string, always requests USB and `/share:rw`, and exposes both ports on the host | Separate production and developer options, narrow permissions, provide structured node onboarding, and avoid host port exposure where HA-local ingress works |
| `rainpointd_addon/run.sh` | Mixed | Production startup branches directly into replay, broad capture, RTL-SDR, or serial research modes | Move development branches to an explicit dev entry point/profile and validate incompatible options before launch |
| `rainpointd_addon/Dockerfile` | Prototype packaging | Uses `base:latest` and unpinned Alpine packages; always copies replay fixtures | Pin/reproduce build inputs, add image validation/SBOM policy, and omit fixtures from the production image |
| `rainpointd_addon/DOCS.md` | Documentation | Version text is already stale and mixes end-user setup with research controls | Generate/review release docs with each version; split operator docs from developer/research docs |

## Firmware inventory

| Path | Classification | Finding | Disposition |
| --- | --- | --- | --- |
| `firmware/rainpoint_bridge/src/main.cpp` | Mixed monolith | RF scanning, frame output, pairing state, TX timing, serial CLI, and network command handling share one large file | Split radio receive, pairing engine, command policy, diagnostics, and application orchestration into testable units |
| `firmware/rainpoint_bridge/include/rainpoint_pairing.h` | Experimental runtime | Strong bounded state machine, but compiled around a fixed recovered Sensor B sequence | Keep the state machine; inject validated profile data and endpoint identities through a constrained profile interface |
| Serial commands in `main.cpp` | Isolated research tooling | `pairing_probe_b`, `pairing_arm_b`, clock, polarity, frequency, power, and channel controls compile only in `esp32dev_single_bench`; CI checks the binary boundary | Keep the research target explicit and never ship it as the default image |
| `firmware/rainpoint_bridge/src/wifi_transport.cpp` | Prototype production candidate | Factory firmware now creates a physical-serial setup token and reports bounded node health, but Wi-Fi provisioning remains tab-delimited, JSON parsing is manual, and transport is plain TCP | Replace serial commissioning with a temporary AP or BLE exchange, robust serialization, credential rotation, and OTA/rollback design |
| Channel diagnostics | Debug behavior | The single-radio build emits frequent `radio_channel` records while scanning, producing high serial/network volume | Rate-limit or aggregate channel state; expose diagnostics on demand rather than per dwell change |
| `esp32dev_dual` environment | Diagnostic build | Optional second radio is not the target distributed-node architecture | Keep only as an explicitly diagnostic CI build or move to a research PlatformIO environment |
| Firmware update path | Missing production function | Firmware 0.5 remains USB-flashed; no signed OTA, compatibility negotiation, rollback, or fleet version management exists | Define this before distributed nodes are treated as appliances |

## Home Assistant integration inventory

| Path | Classification | Finding | Disposition |
| --- | --- | --- | --- |
| `custom_components/rainpoint_local/config_flow.py` | Production candidate | Pairing now works, but gateway auth is embedded in the pairing form; area is free text; only one hard-coded pairing profile exists behind a generic label | Add one-time gateway claim/reauth, hide stored secrets, use HA selectors, and render model/capability-specific pairing choices |
| `custom_components/rainpoint_local/api.py` | Prototype client | Plain HTTP, dictionary responses, repeated request code, and minimal compatibility validation | Add typed response models, explicit capability negotiation, structured errors, and an authenticated production transport |
| `custom_components/rainpoint_local/sensor.py` and `binary_sensor.py` | Production candidate | Dynamic discovery adds entities; coordinator reconciliation now integration-disables entities for gateway-removed devices and re-enables only those it disabled when a device returns | Add HA-native tests for forget, user-disabled preservation, rename, reload, and device-registry cleanup policy |
| `custom_components/rainpoint_local/__init__.py` | Prototype migration | Removes one obsolete entity suffix on every setup rather than using a formal migration path | Add config-entry/entity migrations and version tests |
| `custom_components/rainpoint_local/coordinator.py` | Production candidate | Polls every five seconds even though normal sensors report much less often | Prefer push/event cursors or a materially slower poll with immediate refresh after commands |
| `custom_components/rainpoint_local/entity.py` | Production candidate | Device metadata is supplied dynamically, but name/area lifecycle already required a one-off registry repair | Centralize canonical device metadata and test HA device-registry updates |
| Integration metadata/tests | Release gap | No code owner, HA integration test harness, config-flow tests, diagnostics platform, repairs, or quality-scale artifacts | Add pytest-homeassistant-custom-component coverage and HACS/release validation before publication |

## Repository and research inventory

| Path | Classification | Finding | Disposition |
| --- | --- | --- | --- |
| `tools/` | Research tooling | Useful IQ and event analysis, but several tools contain this house's endpoint/name maps and HA assumptions | Move under `research/tools` or a separate developer package; accept endpoints/config as arguments; add fixture-based smoke tests |
| `research/RF_CAPTURE_PLAN.md` | Research procedure | Operational capture instructions are isolated from end-user docs and retain safety warnings | Keep under `research/` |
| `research/PAIRING_BENCH_TEST.md` | Research procedure | Describes explicit bench-only serial probe/TX controls and requires the original RainPoint gateway off during enrollment | Keep linked to the bench firmware target and update only from controlled evidence |
| `examples/federico-garden/garden-local-dashboard.yaml` | House-specific example | This home's beds, schedules, valves, and entity IDs are now explicitly isolated as an example | Add a minimal generic dashboard only when the public entity model stabilizes |
| `PROTOCOL.md` | Protocol evidence | Valuable, but mixes stable protocol claims, unresolved candidates, dated experiments, and exact house identities | Split a normative supported-protocol document from an evidence notebook; retain confidence/evidence labels |
| `FULL_STACK_ARCHITECTURE.md` | Architecture | Useful target design, but some phase/status language predates the completed pairing prototype | Reconcile with the product brief and this inventory, then make it the technical architecture source of truth |
| `INTEGRATION_EVOLUTION_BACKLOG.md` | Stale planning | Says not to build pairing/registry UI even though that work is now complete | Rewrite around the verified milestone and current valve-control gate |
| `LOCAL_DEVELOPMENT.md` and root `README.md` | Mixed docs | Development, operator, protocol, and research instructions overlap | Give each audience one entry point and link outward rather than duplicating status text |
| `homgar-installed/` | Ignored vendor snapshot | Contains a local copy of another integration, compiled caches, and a large product-model catalog without a tracked provenance workflow | Do not publish the copied tree; record upstream commit/license and extract only permitted model metadata through a reproducible script |
| `captures/rf/` | Ignored local evidence | About 12 MB of local IQ material is correctly excluded from Git | Keep outside normal clones; maintain a redacted fixture-promotion process and optional external archive manifest |
| `firmware/rainpoint_bridge/.pio/` | Ignored build output | About 84 MB of generated PlatformIO output is correctly excluded | Leave ignored; document cleanup/build-cache expectations only |
| `PRODUCT_BRIEF.md` | Untracked product document | Intentionally outside current commits, so architectural decisions can diverge from code unnoticed | Decide explicitly whether to track a reviewed version or keep it external and link a stable shared location |

## Test and CI inventory

Strengths to preserve:

- captured RF frames are regression fixtures rather than undocumented magic;
- pairing and valve-safety state machines have hardware-independent tests;
- both single- and dual-radio firmware variants build in CI;
- network authentication and bounded command vocabulary have negative tests.

Hardening gaps:

- no formatter, linter, static typing, dependency audit, or secret scan;
- no Home Assistant config-flow/entity lifecycle tests;
- no add-on schema/build validation in CI;
- no fuzz/property tests for RF, JSON, and TCP parsers;
- no persistence migration/rollback/retention tests;
- no long-running soak test for node reconnects, duplicate reception, database
  growth, or thread/resource exhaustion;
- no protocol compatibility matrix across gateway and firmware versions;
- no production firmware artifact signing or reproducible release process.

## Recommended cleanup sequence

### 0. Preserve the working milestone

- Tag the known-good end-to-end pairing prototype before structural changes.
- Save the exact firmware/add-on/integration version compatibility tuple.
- Keep Sensor B fixtures and the successful terminal-confirmation sequence as
  immutable regression evidence.

### 1. Draw enforceable production/research boundaries

- Finish explicit `production` and `development` add-on images; firmware now has
  enforced production and `research_bench` targets.
- Remove replay, raw capture, and fixed research profiles from the eventual
  published image; network mode and production firmware are now the defaults.
- Reorganize docs and house dashboard examples without changing runtime logic.

### 2. Extract a generic protocol core

- Create typed frame, device identity, telemetry, association, capability, and
  pairing-profile models.
- Parameterize endpoint identities and remove house names from runtime code.
- Make all transports publish the same typed observations.

### 3. Define one device and association authority

- Consolidate enrollment and registry persistence.
- Specify observed/paired/accepted/ignored/removed states.
- Implement transactional forget, rename, migration, and HA reconciliation.
- Support multiple valves and multiple radio nodes without singleton IDs.

### 4. Replace manual credentials with onboarding

- Add gateway claim, secret rotation, and repair flows.
- Remove the token from ordinary pairing forms.
- Replace the `node_tokens` JSON option with a persistent node registry and
  managed commissioning sessions.
- Wire **Add local radio node** only after HA can provision, auto-detect,
  represent, rotate, and revoke a node end to end; the current generic Add
  control adds a gateway entry and must not be described as node pairing.
- Review transport encryption and replay protection before valve control.

### 5. Harden release surfaces

- Add HA-native tests, add-on validation, lint/type/security checks, schema
  migrations, retention, diagnostics, and compatibility testing.
- Pin build inputs and define signed firmware/release artifacts.

### 6. Generalize only from evidence

- Pair the second test sensor and compare its required reply fields with Sensor
  B before claiming model-wide HCS026 enrollment.
- Convert validated differences into profile parameters, not installation
  conditionals.
- Keep valve TX disabled until endpoint parameterization, counters/replay
  semantics, physical waveform validation, and the safety controller are joined
  in one bounded end-to-end path.

## Proposed first cleanup pass

The safest first implementation pass is intentionally nonfunctional:

1. Tag the current working prototype.
2. ~~Move house dashboard and capture/bench documents into `examples/` and
   `research/`.~~ Completed.
3. Add explicit module-level stability labels (`production`, `experimental`,
   `research`) and remove stale planning statements.
4. ~~Introduce a device identity/friendly-name boundary while preserving
   current defaults for this installation during migration.~~ Completed with
   an injected catalog; persistent registry-backed configuration remains.
5. Split the HA gateway-authentication step from sensor pairing so stored
   credentials disappear from the pairing UI.
6. Add HA config-flow and entity lifecycle tests before deeper refactors.

This creates clear boundaries and test coverage before changing RF behavior.
