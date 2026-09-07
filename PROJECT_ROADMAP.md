# RainPoint Local project roadmap

Last reviewed: 2026-09-06

This is the only live project-status checklist. Device references describe
current protocol facts; research records and fixtures preserve experimental
evidence. A transmitted frame alone never closes a physical acceptance gate.

## Current work order

The user authorized this order while hardware assistance is unavailable:

1. Verify Right Bed's direct-radio recovery.
2. Reconcile this roadmap and streamline protocol, operational, and research docs.
3. Qualify the dry one-zone valve's ACK/control persistence across restarts.
4. Collect durable sensor/valve reliability and morning-sync evidence.

Other phases retain the order below. Later work interrupts qualification only
when it protects irrigation reliability or invalidates existing evidence.
No additional four-zone watering is implied by passive monitoring.

## Established baseline

- [x] Preserve one canonical HA identity per physical device and suppress
  forgotten endpoints. Pairing registration now reuses an established valve
  ID; the duplicate single-zone device was removed with working entity IDs,
  history, ACK owner, counter, and schedules preserved.
- [x] Support one canonical checkout and one PlatformIO environment. Production
  firmware excludes the HTV145 qualification transmitter; its isolated dry-test
  image is a deliberate exception, not fleet-wide release qualification.
- [x] Pair and recover independent HCS026 identities, persist a single ACK owner,
  and pre-fill known devices' saved names and HA areas on re-addition.
- [x] Complete three HA-initiated HTV405 generated-identity enrollments and decode
  all four zones with whole-minute durations from 1 through 60.
- [x] Validate HTV405 fixed-zero idle counter assignment, bounded authenticated
  control, rollover, automatic stop, and Zone 1 early stop.
- [x] Validate HTV145 partial-association dry open, automatic stop, early close,
  persistent selector-6 controls, and non-watering fixed-zero counter recovery.
- [x] Expose both valves' morning-sync controls. One-zone retries are bounded to
  three total attempts, each requiring new owner idle evidence after failure.
- [x] Remove unsupported HTV405 usage entities and the one-zone phantom zones.

Current evidence: [sensor fixtures](research/fixtures/),
[HTV405 sync](research/HTV405_MORNING_SYNC_DESIGN.md),
[HTV145 recovery](research/fixtures/htv145_idle_result3_counter_recovery_20260906.json).
Historical trial sequences remain in [RF capture notes](research/RF_CAPTURE_NOTES.md)
and version history, not this checklist.

## Phase 1 — HA device lifecycle

### Shared UI and sensors

- [ ] Return to the integration device list after removal. HA's supported
  removal hook has no frontend-navigation callback; do not emulate this with
  unrelated backend mutations.
- [ ] Complete three consecutive pair → report → remove → re-pair cycles on
  unchanged final firmware, including an installed sensor and both test sensors.
- [ ] Verify physical removal clears entities, suppression/re-enrollment state,
  and ACK assignment; re-pairing must not create a duplicate.

### Four-zone valve

- [ ] Qualify the retained RX/FIFO recovery correction during a fresh pairing.
- [ ] Remove through HA, verify all four controls, durations, association, and
  routing are cleared, then re-pair without duplicate devices.
- [ ] Physically qualify the implemented effective/raw pairing outcome split:
  terminal acceptance remains completed when the optional tail later times out;
  pre-terminal timeout remains failed. Preserve raw diagnostics and do not cancel RF.
- [ ] Keep the HA wizard at **Finalizing pairing** while the optional tail is
  armed; expose controls only once disarmed and `rf_control_available=true`.

### Single-zone valve

- [ ] Complete the controlled lifecycle matrix with fresh batteries: repeated
  identical stock reset/enrollment, retained long-press re-pair, and battery
  rejoin. Retain full exchanges, ordering, app metadata, and independent outcomes.
- [ ] Complete the terminal stage after the frozen accepted assignment/configuration
  prefix. Each new boundary requires two unchanged accepted repetitions.
- [ ] Complete three fresh local terminal enrollments on unchanged firmware.
- [ ] Verify stable identity after HA removal/re-pair; treat retained re-pair and
  battery rejoin as separate lifecycle paths.
- [ ] Define HA operational enrollment from valve-owned evidence while clearly
  distinguishing it from full six-stage terminal completion.

Exit: every supported family can pair/remove through HA, with repeated physical
acceptance and one stable HA representation. Dry one-zone control does not close
its full-enrollment gate.

## Phase 2 — persistence, recovery, and coexistence

- [x] Verify Right Bed resumed consecutive accepted moisture reports directly
  from ESP32 radios without SDR assistance. The retained recovery window contains
  208 accepted observations over about 11 hours; maximum gap 469.581 seconds.
  Evidence: [direct reporting recovery](research/fixtures/hcs026_direct_reporting_recovery_20260906.json).
  This does not prove every ACK was accepted or complete the 72-hour soak.
- [ ] Complete four-zone liveness qualification across repeated report cycles
  and longer gateway/node restarts, with persistent single-owner ACK evidence.
- [ ] Battery-cycle each supported sensor family and restore the same HA device,
  association, and routine reporting without opening pairing.
- [ ] Record stock battery-rejoin exchanges for both valves, then reproduce local
  retained-association recovery with device-owned terminal/operational proof.
- [ ] Restart HA, gateway, and each assigned node while idle; verify identities,
  counters, ACK owners, availability, and no replay.
- [ ] Reassign one sensor ACK owner and verify revocation precedes replacement TX.
- [ ] Qualify sustained stock/custom coexistence for sensors and valves with
  separate ownership, normal stock operation, and no duplicate HA devices.
- [ ] Document recovery for every destructive association transition.

Exit: ordinary battery changes and infrastructure restarts do not require full
re-pairing; independent stock/custom cohorts operate without conflicting authority.

## Phase 3 — reliable valve control

### Four-zone valve

- [ ] Retain one installed run's RF response, duration, HA notification,
  automation outcome, and watchdog outcome together.
- [ ] Verify explicit early stop on Zones 2–4.
- [ ] Physically re-pair an unchanged association and confirm the already
  authenticated counter is preserved. Software regression coverage exists.
- [ ] Restart gateway/node during an active bounded run without replay or
  speculative close. Idle restart and subsequent control have passed.
- [ ] Qualify late response, RF timeout, duplicate requests, command spacing,
  authenticated recovery, and positively observed overdue anomalies.
- [ ] Complete stable-owner retained-counter checks 1, 4, 8, and 12 hours after
  morning sync, away from report windows. Preserve actual counter continuity,
  latency, automatic idle, and remaining user-authorized watering budget.
  Do not replay missed checkpoints or count an intervening command as a clean hold.
- [ ] Isolate causes of counter staleness: time, owner reboot/reconnect, ACK gaps,
  and stock maintenance traffic. Fixed-anchor recovery does not require this
  causal result, but a single overnight failure cannot establish expiry.
- [ ] Repeat association/control on a second specimen or compatible hardware profile.

Morning scheduling is enabled on the installed valves, and the last observed
status for both is Ready. That deployment state does not complete the controlled
retention matrix. The last-zone idle-reply correction is deployed; see the
[current sync design](research/HTV405_MORNING_SYNC_DESIGN.md).

### Single-zone valve

- [x] Qualify idle radio/gateway restart, valve-owned automatic stop across an
  active gateway restart, and early close after an active owner reboot. Counter
  state survives, no actuator is replayed, and the corrected reconnect trial has
  matching positive RF replies and independent idle. Gateway 0.34.15 also blocks
  commands while a reboot is pending, preserving the counter instead of sending
  through the stale connection. Evidence:
  [restart recovery](research/fixtures/htv145_restart_recovery_20260906.json).
- [ ] Qualify report/summary ACK on-air timing, residue, and suppression of retries
  on the cleaned image. Continued reports and gateway/radio ACK diagnostics do
  not replace independent waveform evidence; SDR access is currently unavailable.
- [ ] Complete the high-marker command-phase model for arbitrary action ordering,
  including consecutive opens. Alternating open/close and rollover are supported;
  fixed action polarity is not a universal model.
- [ ] Repeat operational acceptance on fresh user-assisted associations with
  fresh batteries and independent state evidence.
- [ ] Promote ordinary HA actuation only after its physical gates pass.

### HA and irrigation

- [ ] Verify HA watering state changes only from authenticated responses or
  independent valve telemetry, never from outbound command intent.
- [ ] Qualify one-active-zone enforcement, per-zone durations, local schedules,
  completion/failure notifications, and watchdog behavior end to end.
- [ ] Exercise scheduled irrigation with some sensors stale and with all sensors
  stale; verify the configured 6–8-hour bounded fallback cannot suppress watering
  indefinitely. The deployed script handles these branches; scheduled evidence
  remains required.
- [ ] Verify live timestamps/schedules in a non-Eastern timezone in addition to
  existing UTC/offset/DST software tests.

Exit: accepted commands have valve-owned confirmation; failure and restart behavior
are bounded, observable, and recoverable.

## Phase 4 — field decoding

- [x] Decode HCS026 moisture/categorical battery, HTV145 state/duration/usage/
  categorical battery, and HTV405 zones/duration/control counters.
- [ ] Correlate model-supported fields with timestamped cloud or physical state:
  battery, active zone, requested/actual/remaining duration, stop, and HTV145 usage.
- [ ] Validate the HTV405 battery candidate with a controlled normal-to-low
  transition. Byte 17 mask `0x08` remains provisional; routine ACK payloads do
  not establish battery state. Keep HA battery unavailable until validated.
- [ ] Ensure discovery is based on product codes and protocol capabilities,
  not seller names, household endpoints, or friendly names.

Exit: supported fields agree with independent observations; unsupported values
remain explicitly unavailable. See [device references](protocol_documentation/).

## Phase 5 — stability qualification

- [x] Deploy a read-only HA-scheduled snapshot/event collector with a durable
  cursor, fixed window, explicit gap/error records, and automatic completion.
  See [operation](examples/reliability-soak/README.md).
- [ ] Complete a persisted minimum 72-hour multi-node sensor cadence/ACK soak.
  Current collection runs September 7 00:53 UTC through September 10 00:53 UTC;
  completion still requires reviewing the evidence, not just reaching the deadline.
- [ ] Include sustained stock/custom coexistence and three successful scheduled
  irrigation cycles using only local authority.
- [ ] Include HA/gateway restart, node reboot/OTA, and device battery cycle
  without identity loss or command replay.
- [ ] Confirm weak-link placement is adequate; relocate only if evidence requires it.
- [ ] Observe no phantom devices, duplicate ACK owners, false watering states,
  stale-data decisions, or notification reconnect flapping.
- [ ] Test wrong-checksum OTA, interrupted download, candidate-boot power loss,
  unhealthy-boot rollback, and USB recovery.

Exit: durable evidence meets the complete matrix without unexplained intervention.
Passive monitoring alone cannot qualify battery-cycle or coexistence operations.

## Phase 6 — open-source hardening

- [ ] Remove production installation IDs, names, paths, allowlists, and fixed
  profiles; keep deliberate examples under `examples/`.
- [ ] Review protocol, gateway, HA, firmware, and research interfaces; introduce
  typed/versioned boundaries, structured errors, and formal HA migrations.
- [ ] Finish event-driven HA updates with slow reconciliation fallback.
- [ ] Retire remaining superseded probes, temporary acceptance endpoints,
  obsolete gates, firmware artifacts, and dormant two-radio support.
- [ ] Preserve authentication, association-bound TX, bounded duration,
  device-owned confirmation, command spacing, at-most-once opens, and rollback.
- [ ] Add encrypted node sessions, replay protection, credential lifecycle
  review, API limits, reproducible packaging, and asymmetric OTA signatures.
- [ ] Run CI, security/redaction review, and clean-environment installation tests.

Exit: contributors can build one production stack without household knowledge;
research transmit paths cannot enter a release artifact.

## Phase 7 — documentation and research infrastructure

- [x] Streamline current device references, operational guides, architecture,
  and research procedures. Keep chronology in evidence records and status here.
- [ ] Make receive-only SDR capture a managed Mac service with optional normalized
  forwarding. HA production must remain independent of SDR; current USB absence
  prevents live capture qualification.
- [ ] Decide the research repository boundary before publication. If separated,
  keep protocol fixtures/models with production and move raw data/orchestration.
- [ ] Clean merged branches, obsolete backups, and stale firmware catalogs after
  retaining necessary rollback artifacts and redacted fixtures. Do not create
  or use another development checkout.

Exit: concise user-oriented docs, explicit research boundaries, and independent
capture infrastructure.

## Deferred migration and backlog

Cloud-to-local authority handoff and a HomGar integration merge remain deferred
until Phases 0–5 qualify. Design review may continue without live migration.

- Preserve explicit timezone on SDR observations before restoring it as an
  authoritative receiver; do not reinterpret ambiguous historical timestamps.
- Discover additional device families and determine whether HCS026 P1–P6 soil
  selection is RF, device-local, or cloud metadata.
- Determine whether any pairing field controls long-term telemetry channel.
- Characterize compact product/status integrity before constructing that traffic.
- Optimize channel scheduling and placement beyond the required stability floor.
- Make Add device a reversible stepped wizard after protocol reliability stops
  being the limiting factor; validate navigation in HA.
- Finish carrier manufacturing/enclosure work under its physical preorder checklist.

Promote a backlog item only when evidence makes it a qualification blocker or
irrigation reliability issue; do not implement it merely because it was noticed.
