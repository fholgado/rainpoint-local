# RainPoint Local project roadmap

Last reviewed: 2026-09-08

This is the only live project-status checklist. Device references describe
current protocol facts; research records and fixtures preserve experimental
evidence. A transmitted frame alone never closes a physical acceptance gate.

## Current work order

The user prioritized single-zone promotion ahead of the selected hardening work.
The verified association now uses standard firmware and HA controls, preserving
bounded commands, counter recovery and evidence-based state. The user connected
the single-zone valve to the front irrigation on September 8. Its dashboard,
manual run, scheduled decision and watchdog now target the local valve.

September 8 follow-through order: verify the first front-garden scheduled run
and completion; then finish the prior pass's rendered HA wizard/UI checks and
fixes; then qualify the consolidated firmware on remaining production owners.
Firmware qualification must cover persisted association/counter restore without
startup actuation, valve-confirmed bounded controls, ACK/report continuity and
the overnight check. New-ID pairing alone does not qualify control ownership.

The selected unattended implementation/review pass is complete (original list numbers):

- [x] **1.** Audit production defaults: empty fresh installs, accepted identity
  recovery, explicit ACK routes, and a regression guard against household IDs.
- [x] **2.** Move the unused bench coordinator out of the app and remove the
  manual phase-string parser; retain authenticated counter restoration and
  qualification tools still required by open physical gates.
- [x] **4.** Apply known sensor events directly in HA, retain authoritative
  snapshots for valves/topology, handle cursor resets and retry failed snapshots.
- [x] **5.** Keep accepted pairing visibly finalizing until its selected radio is
  disarmed and available; optional-tail failure cannot erase terminal acceptance.
- [x] **6.** Add a pre-transmission review with model/radio Back choices and Cancel;
  preserve selected values and scope cancellation to the flow's own command.
- [x] **7.** Add config version 3 migration with stable identities/user options,
  canonical credential storage and refusal of unsupported future versions.
- [x] **11.** Review retained four-zone staleness evidence: time, reboot/reconnect
  and ACK failures remain confounded. No additional watering was authorized or run.
- [x] **12.** Review auth boundaries; bound HTTP concurrency, reads, event windows
  and setup attempts; persist rotated tokens privately and atomically.
  Encrypted sessions and signed OTA remain publication gates below.
- [x] **15.** Add deterministic source archives, isolated fresh-install/restart
  smoke tests, a digest-pinned base image and a CI production-container build.
- [x] **16.** Remove merged legacy worktrees/branches and archive superseded
  backups/firmware; retain installed images and explicit rollback releases.
- [x] **18.** Recheck command-phase, shared-counter and battery-field evidence.
  Unsupported battery and arbitrary action-order semantics remain unavailable.

- [x] Inspect the deployed wizard in HA with explicitly user-enabled browser
  access. September 8: both categories, HCS02x and HTV405 models, friendly radio
  labels, radio/timeout preservation, category return and pre-arm cancellation
  were exercised in the rendered UI. No pairing or watering was started; all
  three radios remained connected, normal and unarmed. HA's stale browser
  connection recovered with a page refresh, without a server or radio restart.
- [x] Deploy and verify the selected native pairing navigation improvements.
  Integration 0.16.2 renders Next for model and radio forms and Back on review.
  Live September 8 verification covered sensor and valve flows, review Back
  retaining a non-default radio/300-second window, and Change device model
  returning to categories. No Start pairing was clicked. These are native menu
  actions, not footer Back buttons on every screen. The user deferred a dedicated
  wizard; its remaining requirement is recorded in the backlog below.
- [x] Verify removal of "Add with setup code" from the management menu in HA.
  The user requested removal on September 8. New radios use discovery and BOOT
  confirmation; existing registrations/credentials are unchanged. The hidden
  legacy callback remains for an already-open manual registration flow, not as
  a normal sensor/valve pairing option.
  Validation: 524 Python tests passed (two optional skips), native C++ protocol
  test and deterministic package smoke passed, HA configuration check passed,
  and deployed file hashes matched. Only HA was restarted; both valves remained
  idle, all six sensors available and three radios connected/normal/unarmed.
  Record this HA restart as an intervention in the ongoing mixed-version soak,
  not uninterrupted final-release uptime.
- [ ] Finish fleet qualification of standard firmware 0.16.2 after the current
  soak. The Front Yard owner is already on 0.16.2 with confirmed custom-ID
  open/automatic stop/early close; the other nodes retain their installed images.

Gateway 0.36.4 and integration 0.16.2 are deployed. Firmware 0.16.2 contains the
post-command RX restoration fix, without changing the frozen pairing sequence.
Software/research completion does not resolve the physical or publication gates.

The existing 72-hour collector continues independently. Software completion does
not close physical gates requiring pairing gestures, power changes, SDR, or a
new watering budget. Later phases remain ordered below unless this selected
sequence or irrigation reliability requires otherwise.

## Established baseline

- [x] Preserve one canonical HA identity per physical device and suppress
  forgotten endpoints. Pairing registration now reuses an established valve
  ID; the duplicate single-zone device was removed with working entity IDs,
  history, ACK owner, counter, and schedules preserved.
- [x] Support one canonical checkout and one PlatformIO environment. Both valve
  families use the standard firmware; production controls require an evidenced
  association. Deployment does not replace the remaining physical qualifications.
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
- [x] Implement **Finalizing pairing** while the optional tail is armed; preserve
  backend command readiness guards. Rendered/physical qualification remains above.

### Single-zone valve

- [x] Remove the new-controller-ID HA handoff dependency on an existing catalog
  link. Command-scoped captured-report replay now preserves the HA device,
  decodes the first report, retires the old route, and survives gateway restart.
  Invalid/unrelated/session-expired reports and old control authority are rejected.
  The frozen radio pairing sequence is unchanged (gateway 0.36.1).
- [x] Physically verify new-ID handoff and subsequent ACK/control enrollment
  through the chosen node. The September 7/8 partial 5/6 exchanges preserved the
  existing HA device and disarmed normally. September 8 bounded qualification
  and the corrected standard-firmware recovery/control trial below established
  command authority and owner telemetry/ACK operation without further re-pairing.
- [ ] Verify sustained reporting and control on this custom-ID association.
  The successful bounded tests do not qualify overnight persistence, battery
  rejoin, repeated new enrollments or full six-stage terminal completion.
- [x] Bridge fresh local pairing to first-control qualification without a stock
  command or copied counter. Previous dry acceptance required a passive command
  on the same link, and runtime enrollment requires a positive exchange; neither
  could bootstrap a new custom-ID association through that API. Use a
  separately gated, bounded qualification state with explicit old-owner revocation,
  fresh owner idle evidence, close-only counter establishment, and valve-confirmed
  control before enabling public commands. Preserve the proven RF pairing prefix
  and distinguish provisional test ownership from qualified runtime ownership.
  Implementation deployed in gateway 0.36.2: persistent provisional qualification,
  fresh idle anchor, two fixed one-minute runs, response/stop verification,
  public-control blocking and interrupted-test handling. Validation: 510 Python
  tests (two skipped), native protocol tests and isolated release smoke test;
  all radios reconnected and eight device identities remained after deployment.
  Physical qualification remains incomplete; firmware is unchanged. After explicit
  management-token authorization, the old owner confirmed revocation and the new
  owner heard idle telemetry. Its first fixed-zero anchor received result 3 with
  byte 17 `00`, not the qualified `10` layout. Qualification stopped before any
  open, with no authenticated counter. Preserve this rejection boundary; compare
  fresh-association setup and command-phase evidence before proposing an isolated
  bootstrap probe. Do not generalize the anchor decoder from a negative reply.
  [Captured qualification rejection](research/fixtures/htv145_custom_identity_idle_anchor_20260907.json).
  The captured-exchange regression and full 511-test suite pass (two skipped),
  as do native protocol tests. Research controls are disabled again; the selected
  provisional ACK owner remains configured, with public watering blocked.
  September 8 unchanged re-pair follow-up: the same selected node and firmware
  again received a byte-for-byte identical negative anchor reply after fresh idle
  telemetry (one close-only attempt; no opens). Re-pairing alone did not establish
  command authority. Subsequent idle reporting continued. Research access was
  disabled again; all three nodes reconnected and production four-zone controls
  remained available. Compare command acceptance/setup against a proven positive
  exchange next; do not change the frozen pairing prefix or treat this as RF silence.
  Add a separately compiled, explicit dry first-open trial using the captured
  counter-`81` / 60-second command. The earlier positive association opened before
  idle-anchor testing; initialization and recovery are not proven equivalent.
  Candidate reservation must not authenticate a counter, replay after restart,
  retry automatically, or enable public controls.
  September 8, gateway 0.36.3: the isolated first-open trial on unchanged pairing
  accepted `81/90` and completed automatic idle after a requested 60-second run.
  A second confirmed open (`82/90`) and early close (`83/10`, 20 seconds later),
  followed by independent idle, completed public control qualification.
  No stock command, copied counter or additional re-pair was needed. Public
  authority survived an add-on restart; research access is disabled again.
  [Redacted captured exchange](research/fixtures/htv145_custom_identity_first_open_20260908.json)
  now replays through the qualification state machine. This closes this one
  association's bootstrap/control gate, not repeated enrollment, long-term
  stability, full terminal pairing, or battery rejoin. Front Yard returned to
  standard 0.16.0 with OTA health confirmed; retained authority survived radio
  and gateway restarts, and a normal public 60-second open was acknowledged.
  Post-bootstrap idle-anchor recovery exposed two additional boundaries:
  channel selection did not restore the command-retuned base frequency, and
  the result-3 matcher hardcoded zero usage. A receive-only configuration reset
  restored owner reception immediately. Firmware 0.16.2 restores full RX state;
  gateway 0.36.4 and firmware preserve usage bytes in the narrow error matcher.
  Both issues have red/green regressions; unchanged pairing is retained.
  Physical verification passed on September 8: corrected firmware completed OTA
  health, Front Yard received the nonzero-usage anchor and established counter80,
  the public 60-second open was positively acknowledged, and Front Yard itself
  received automatic idle about63seconds after dispatch and resumed report ACKs.
  Final counter81, idle, public controls ready, research disabled. Captured replay
  covers recovery through the subsequent accepted command and independent stop.
  Validation:519 Python tests pass(two optional skips), native C++ protocol and
  actual receive-restoration call-site regression pass; unified firmware build
  and isolated packaged-gateway smoke pass. Production four-zone owner unchanged.
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
  September 8 UI audit: HTV145 remains intentionally excluded from the ordinary
  model picker (`user_pairing_supported=False`), because its research enrollment
  still requires factory/route/companion association inputs and separate control
  qualification. The qualified installed valve's controls do not prove generic
  discovery or unattended first-control setup. Implement and qualify that path
  before advertising user pairing; do not merely flip the metadata flag.

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
- [x] Promote the verified single-zone association to standard firmware and HA
  controls at the user's request. Gateway 0.35.0, integration 0.15.0, firmware
  0.16.0 retain one device, its counter, ACK owner and morning schedule. Dry
  public-API tests confirm one-minute automatic stop, a subsequent open and
  early close after 20 seconds; counter progression is 129 → 130 → 131 → 131.
  A final post-restart one-minute run confirms decoded watering and automatic
  idle reports with counter 132.
  [Promotion evidence](research/fixtures/htv145_standard_firmware_control_20260906.json).
- [x] Connect the promoted single-zone valve to the front garden (user confirmed)
  and migrate the live dashboard, Run Now, scheduled decision and watchdog.
  Preserve 07:00 / 30-minute settings, season toggle and local-moisture/weather
  checks. Enable 06:15 America/New_York morning sync (30-minute window). Remove
  obsolete Sonoff meter automations/cards, keeping historical helpers untouched.
  HA configuration validation and restart succeeded; no watering was triggered
  during cutover. The four-zone decision/control path is unchanged.
- [ ] Qualify the first front-garden scheduled start, actual irrigation and
  confirmed completion, including the new HA feedback. UI rendering and real
  push delivery still require observation; configuration checks are not watering
  acceptance. Remaining ACK waveform, fresh-association and soak gates stay open.
  The existing six-hour reliability-review heartbeat now explicitly checks the
  September 9 07:00 local run after its window, correlating HA decisions with
  valve-owned confirmation. A justified moisture/weather skip is not an irrigation
  failure or a passed watering test. This follow-up must not trigger extra watering.

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
- [x] Review the first 43.103 hours of the current collection: 523 snapshots,
  39,071 events, no recorded cursor gaps/errors, and six fresh sensors at every
  snapshot. All eight device identities remained present; each sensor retained
  one configured ACK owner. Longest interval between captured sensor observations
  was 563.5 seconds. See [interim evidence](research/RF_CAPTURE_NOTES.md#interim-reliability-review--2026-09-08).
- [ ] After fleet firmware qualification, collect an unchanged-release production
  baseline. The current window contains 61 radio connection events, seven detected
  reboots and multiple firmware versions; it demonstrates continued sensor
  reporting through interventions, not uninterrupted final-version stability.
  Preserve and finish the existing window rather than resetting its deadline.
- [ ] Include sustained stock/custom coexistence and three successful scheduled
  irrigation cycles using only local authority.
- [ ] Include HA/gateway restart, node reboot/OTA, and device battery cycle
  without identity loss or command replay.
- [ ] Confirm weak-link placement is adequate; relocate only if evidence requires it.
- [ ] Observe no phantom devices, duplicate ACK owners, false watering states,
  stale-data decisions, or notification reconnect flapping.
- [ ] Test wrong-checksum OTA, interrupted download, candidate-boot power loss,
  unhealthy-boot rollback, and USB recovery.
  September 7: two interrupted 0.16.0 downloads left a node connected on its
  original 0.15.7 image, with no candidate boot. A third unchanged attempt completed
  the download, rebooted into 0.16.0, and confirmed gateway/radio health. Interrupted
  download retry is physically demonstrated; the other OTA fault cases remain open.
  September 8 repeated this behavior on Front Yard: two interrupted downloads
  retained the running image, and a third unchanged transfer passed SHA and OTA
  health confirmation. Root cause of intermittent transfer interruption remains
  unproven; do not weaken artifact checks or infer a timeout fix from the retry.

Exit: durable evidence meets the complete matrix without unexplained intervention.
Passive monitoring alone cannot qualify battery-cycle or coexistence operations.

## Phase 6 — open-source hardening

- [ ] Isolate the intermittent network-test registry race before calling CI
  deterministic. September 8 PR run 34270093265 failed
  `test_htv145_pairing_handoff_rejects_unproven_frames` (`wrong_session`):
  a direct private-store registry read returned an empty list. The same commit
  passed the branch CI run and 521 local tests (two skips); 20 repetitions of
  the entire rejection-variant test also passed. Unsynchronized test setup/read
  access is a hypothesis, not a proven cause. Preserve rejection assertions and
  pairing behavior until a deterministic interleaving reproduces the failure.

- [x] Complete the production installation-assumption audit. Empty defaults,
  accepted-observation identity recovery, evidence-based ACK routes and generic
  pairing profiles are implemented; historical profiles live only in tests and
  research, and replay samples are explicit `examples/` inputs.
- [ ] Review protocol, gateway, HA, firmware, and research interfaces; introduce
  typed/versioned boundaries, structured errors, and formal HA migrations.
- [x] Finish event-driven HA sensor updates with slow reconciliation fallback
  and authoritative snapshots for valve/control/topology events.
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
- [x] Clean merged branches/worktrees and archive obsolete backups/firmware.
  The active catalog retains installed/rollback releases and the staged update;
  raw evidence is preserved, with one canonical development checkout.

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
- Build a dedicated Add device wizard with actual footer Back/Next buttons on
  every selection/review screen. Deferred by the user on September 8 after
  selecting native-flow improvements first. HA 2026.8's standard data-entry
  forms provide Next labels but no previous-step button contract; preserve
  backend validation and explicit Start pairing authorization in any custom UI.
- Finish carrier manufacturing/enclosure work under its physical preorder checklist.

Promote a backlog item only when evidence makes it a qualification blocker or
irrigation reliability issue; do not implement it merely because it was noticed.
