# RainPoint Local project roadmap

### Installed-valve phase trial build — September 30

- [x] Implement the explicitly enabled two-run radio guard, full-phase builders and offline guard/replay tests.
- [x] Add the protected `phase-trial` signing profile and production-exclusion check.
- [x] Obtain protected signing approval; verify the unpublished `0.19.0-phase-trial.1` artifact (run 36787747965).
- [x] Test atomic counter handback, release acknowledgment and four-zone telemetry coexistence offline.
- [x] Verify gateway admission/handback; back up HA and deploy gateway 0.39.10 plus signed trial firmware to the front node only.
- [x] Capture front HTV145 phase-2 acceptance, watering and automatic stop after one 60-second run; stop further trials on monitor failure.
- [x] Reproduce/fix Arduino `word(...)` macro collision in the trial verifier; replay actual RX with Arduino-compatible regression tests.
- [x] Implement explicit no-watering recovery with stored RF evidence, atomic counter handoff and correlated radio release; preserve failed history.
- [x] Merge focused recovery firmware PR #26; submit protected `phase-trial.2` build 36796917397. Local full suite: 879 tests, two optional skips.
- [x] Restore front command availability through verified no-RF recovery (Oct 1): gateway 0.39.11, signed front firmware `phase-trial.2`, correlated radio acknowledgment and retained counter 129; preserve failed history.
- [x] Verify normal front controls after recovery: two 60-second runs, positive phase-3/5 ACKs, active/automatic-idle reports and counters 129 → 130 → 131 (Oct 1).
- [x] Remove inventoried local HA/Mac backups with user approval; retain live data, RF evidence and stock firmware. HA ~42.5 GB free, Mac ~89 GiB free (Oct 1).
- [x] Qualify front adjacent phases 8 → 9 after the user's 35-minute run: two 60-second runs with positive ACK, active/automatic-idle RF and verified production handback; idle, retained counter 133 (Oct 1).
- [x] Implement explicit dry-outlet trial selection and legacy-record migration; 886-test suite passed/two skips, final 39 focused tests and ESP32/boundary/native checks passed. Firmware PR #27; gateway companion remains source-only.
- [x] Merge dry-outlet firmware PR #27; submit protected signing run 36864829701 (`phase-trial.3`).
- [x] Deploy gateway 0.39.12 and signed veggie firmware `phase-trial.3`; confirm both radios healthy. One normal Zone 2/60-second baseline opened and stopped automatically at phase 1; adjacent trials withheld on verifier mismatch.
- [x] Replay/fix generated-association HTV405 outlet packing in gateway/radio verifiers; actual Zone 2 regression, wrong-outlet/model and migration checks pass. Full suite: 890 tests/two skips; final 36 focused tests and ESP32/native/boundary checks pass.
- [x] Merge focused verifier fix PR #28; submit protected `phase-trial.4` signing run 36872047806. Gateway 0.39.13 correction package: 28 staged-runtime tests passed.
- [x] Verify approved signing run 36872047806; deploy tested gateway 0.39.13 and signed veggie `.4`, with healthy OTA confirmation and exact source hashes (Oct 1).
- [x] Qualify dry Zone 2 adjacent phases 4 → 5 after the separately approved phase-3/60-second baseline: positive owner ACKs, active/automatic-idle RF, correlated release and production counter 3 (Oct 1). Preserve the earlier stale-idle rejection.

- [x] Merge scoped native-control firmware candidate PR #29; clean-tree CI, 649 tests/two optional skips and `.6` build pass (Oct 2).
- [x] Verify approved signing run 37085918246 and deploy signed veggie `.6` plus matched gateway `0.39.14-native-trial.2`; radio healthy/authenticated (Oct 2).
- [x] Correct private trial storage for the gateway's read-only `/share` mount; persist receipts in `/data`, keep inputs read-only, and pass 10 launcher tests.
- [x] Qualify native dry Zone 2 phases 2 → 3: positive ACKs, active/automatic-idle RF, durable receipts and no-RF legacy handback; idle, retained counter 2 (Oct 2).
- [x] Recover on dry Zone 2 and confirm a new phase-1/60-second legacy baseline after the original timeout; preserve both attempts.
- [x] Fix selected-outlet recovery, morning readiness, duplicate receiver provenance, network-mode authorization and idle-only routine decoding; remove the finished private launcher.
- [ ] Qualify native-control restart/lifecycle behavior and HTV145 before enabling native allocation by default. Existing legacy irrigation remains enabled.

Build procedure: [bounded phase trial](docs/VALVE_PHASE_TRIAL.md).

Last reviewed: 2026-10-03

This is the only live checklist. Completed implementation does not imply physical
qualification. Detailed history and proof are in the
[evidence index](research/IMPLEMENTATION_EVIDENCE_20260912.md), not the task text.

## Current work order

Carrier exception (Sep 14): Rev A's radio rows are reversed. Keep it unpowered
with a directly plugged radio. Rev B passes CAD/pin checks; physical acceptance
is pending. See `hardware/rainpoint_carrier/REV_A_REWORK.md` for salvage checks.

1. Review the validated [stock-informed source fixes](research/STOCK_FIRMWARE_IMPROVEMENT_PLAN.md), then approve the [short canary test plan](docs/STOCK_INFORMED_VALIDATION.md) before deployment.
2. Deploy the native-only integration after review, then improve/test pairing under Devices & services.
3. Collect targeted lifecycle results and continue stable-release qualification; no new 72-hour baseline is required.

Completed stock-reference trials: dry HTV213FRF two-zone valve, both ports,
early stop, >30-minute/>3-hour idle controls, hub-only RST restart, and valve battery rejoin. Follow the [capture procedure](research/TWO_ZONE_STOCK_CAPTURE_PLAN.md)
for separately approved lifecycle tests; the finite unattended controls are finished.
Do not alter production irrigation or claim local support from stock-only tests.

Completed passive baseline: used HCS012ARF rain gauge, battery boot and
stock-app pairing; zero rain/battery OK confirmed. Nonzero rainfall remains
unqualified. No local enrollment or transmit path is enabled.

Stock firmware research remains read-only. Installed adjacent-phase qualification
completed Oct 1: HTV145 phases 8 → 9 and HTV405 dry Zone 2 phases 4 → 5, each
with two 60-second opens, full-phase positive ACKs, independent active/automatic
idle and correlated production handback. No retries, counter jumps or wet
Zone 1 commands were used for the four-zone trial. Earlier verifier failures
and stale-idle rejection remain preserved in the
[trial evidence](docs/VALVE_PHASE_TRIAL.md). Production counter allocation is
unchanged; counter-boundary and broader lifecycle trials are separate gates.
The Oct 1–2 follow-up adds a shared codec, durable allocator and opt-in standard-
control adapter with persistent radio receipts and HA progress/failure state.
Live production still uses the legacy allocator. The signed `.6` candidate is
installed on Vegetable Garden; dry Zone 2 native qualification passed Oct 2.
Normal gateway startup and legacy allocation are restored. Native allocation
remains opt-in until model-specific restart/lifecycle qualification is complete.
The approved off-device update lookup offered no newer image for this
hub on Sep 27. The user initially approved source changes/tests for ownership
cleanup, retained-channel recovery and remaining-time decoding without deployment.
On Sep 29, gateway-only `0.39.1` was approved and deployed to match the new
research radio's capabilities. Both garden radios reconnected with ACK ownership
ready; existing radio firmware and integration stayed unchanged.
The subsequent unattended-work approval also covers source/test repairs for
full-phase reply matching and bounded single-zone plan-request retries. These
are implemented offline; hardware acceptance and deployment remain separate.
The latest valve-learning implementation adds capture-tested reply builders and
durable recovery configuration/progress with owner checks. The HTV213 reply-owner
handler now consumes explicit per-port configuration and opt-in retained rejoin
(Oct 3; source only). **Live recovery is disabled** pending signed deployment and
physical acceptance; other model handlers remain unfinished.
Existing pairing prefixes and production startup/counter behavior are unchanged.
See the [expanded regression audit](research/STOCK_HUB_LOCAL_REGRESSION_AUDIT.md)
and [replacement-firmware assessment](research/STOCK_HUB_CUSTOM_FIRMWARE_FEASIBILITY.md).
Recovery branch: `codex/retained-valve-recovery`; earlier research is merged to main. Refine and qualify our existing
firmware first; a stock-hardware port comes afterward. Keep the stock hub intact
as a reference, and keep vendor images private.

No extra watering, pairing, battery cycles, radio flashing or outage tests without
the required user authorization. Keep RF pairing prefixes frozen unless evidence
requires a change. Command intent and transmitted ACKs are not device confirmation.

### Alpha cohort preparation

- [x] Publish [Alpha 1](https://github.com/fholgado/rainpoint-local/releases/tag/v0.18.0-alpha.1): gateway 0.39.0, integration 0.18.0, signed firmware 0.19.0.
- [x] Publish source/USB/OTA artifacts, checksums, compatibility metadata and rollback instructions.
- [x] Add the agent-assisted guide, hardware BOM and separate app-store/HACS installation paths.
- [x] Declare HACS prerelease selection, codeowners, branding and redacted issue reporting.
- [x] Pass HACS/hassfest, container, firmware and Python CI for Alpha 1.
- [x] Qualify discovery, menus, reload and removal on real HA Core 2026.7.0 and 2026.9.1.
- [x] Audit default notifications and provide optional mobile/stale-report blueprints.
- [x] Deploy TLS, signed OTA and per-association single-zone state to all reference radios.
- [x] Verify post-update watering and automatic stop for both valve families.
- [x] Fix standalone manual TLS credentials and entry-scoped registry lookups; qualify HA Core 2026.7.0/2026.9.1 and deploy integration 0.18.1.
- [x] Verify default notification delivery/deduplication/dismissal for both valves on clean HA Core (not rendered UI).
- [ ] Validate fresh HA OS app/HACS installation and adoption on aarch64 and amd64. **Tester.**
- [x] Deploy matched gateway 0.39.1; verify garden-node authentication and ACK restoration without watering.
- [x] Complete fresh native adoption of the research test node on gateway 0.39.1; verify authentication, health and accepted RF reception.
- [ ] Make failed native radio adoption retryable without repeating Wi-Fi setup; align UI and credential expiry.
- [ ] Exercise rendered pairing/removal/cancellation screens for sensors and both valves. **Tester.**
- [ ] Verify default notifications in the rendered HA panel and optional mobile forwarding. **Tester.**
- [ ] Qualify multiple physical single-zone valves on one node; eight slots are implemented. **Hardware.**
- [ ] Record independent-house reporting, watering duration/stops and overnight recovery. **Tester.**

Alpha 1 is available now; the remaining acceptance items do not block participation.
[Known limitations](docs/ALPHA_1.md) distinguish supported features from unproven behavior.

## Established baseline

- [x] Use one production firmware/environment for sensors and both valve families.
- [x] Preserve one HA device per physical endpoint; suppress removed/forgotten routes.
- [x] Persist sensor ACK ownership, names and areas across re-addition.
- [x] Complete three HA-initiated HTV405 generated-identity enrollments.
- [x] Decode HTV405 zones and whole-minute durations 1–60; verify Zone 1 early stop.
- [x] Verify HTV145 custom-ID partial association, first open, automatic stop and early close.
- [x] Support fixed-zero counter recovery and bounded morning synchronization for both valves.
- [x] Initialize fresh HTV145 counter once; keep pairing-derived and response-confirmed state distinct.
- [x] Remove mandatory two-run unlock and obsolete supervised-control app switches.
- [x] Remove HTV405 water-usage entities and HTV145 phantom zones.
- [x] Migrate reference dashboards/automations to local valves and moisture sensors.
- [x] Correct scheduled duration/notification handling for all whole minutes 1–60.
- [x] Fix slow OTA transfers and verify the affected radio updates successfully.
- [x] Observe recovery after the reference HA/network outage without radio reboot.
- [x] Move regression tests under tests/; clean merged branches and obsolete deployment artifacts.

## Phase 1 — HA device lifecycle

### Shared UI and sensors

- [x] Add native Next/review Back actions, friendly radio labels and preserved selections.
- [x] Remove the “Add with setup code” menu; use discovery and BOOT confirmation.
- [x] Remove the custom wizard/sidebar from source at user request; preserve native pairing and session-ownership checks. The removed implementation remains in Git history.
- [ ] Deploy native-only integration 0.18.3 with an HA restart; live HA still has 0.18.2's panel until then.
- [ ] Improve and physically qualify native pairing for sensors and both valves.
- [ ] Revisit native HA device-page navigation after removal; the removed panel's redirect does not apply there.
- [ ] Complete three sensor pair → report → remove → re-pair cycles on unchanged firmware.
- [ ] Verify removal clears entities, suppression and ACK ownership; re-addition stays duplicate-free.

### Four-zone valve

- [x] Show Finalizing pairing until the selected node is ready.
- [ ] Qualify RX/FIFO recovery during fresh pairing.
- [ ] Verify optional-tail timeout preserves acceptance while pre-terminal timeout fails.
- [ ] Remove/re-pair through HA; verify all four controls, durations and routes are cleaned up.

### Single-zone valve

- [x] Implement generic factory-ID discovery, custom-ID handoff and persistent selected ownership.
- [x] Define operational pairing separately from full six-stage terminal completion.
- [ ] Physically verify current discovery → pairing → owner setup → user-requested control.
- [x] Verify sustained reporting/control on the reference custom-ID association; four scheduled runs and reported stops in the [Sep 17–22 field review](research/FIELD_RELIABILITY_20260922.md).
- [ ] Compare stock reset/enrollment, retained long-press pairing and battery rejoin with fresh batteries.
- [ ] Complete the terminal stage without changing the proven prefix; repeat each new boundary twice.
- [ ] Complete three unchanged full local enrollments.
- [ ] Remove/re-pair through HA and retain one identity; qualify battery rejoin separately.

## Phase 2 — persistence, recovery, and coexistence

- [x] Confirm direct ESP32 sensor reporting recovery without SDR assistance.
- [x] Verify repeated HTV405 report/ACK cycles with one assigned owner across five days.
- [ ] Qualify longer, controlled gateway/node outages with one ACK owner.
- [ ] Battery-cycle sensors; restore the same HA identity and reports without arming pairing.
- [ ] Capture stock battery rejoin for both valves, then prove equivalent local recovery.
- [x] Observe production-node reconnection, restored ownership and fresh device reports after the Sep 22 HA-host restart.
- [ ] Qualify controlled HA/gateway/radio idle restarts with explicit state-persistence and no-replay assertions.
- [ ] Reassign a sensor ACK owner; prove revocation occurs before replacement transmissions.
- [x] Implement explicit sensor/HTV405 owner handoff and deletion journaling, correlated confirmations and HA cleanup diagnostics; source-only, physical qualification pending.
- [x] Preserve sensor selector 4/5 in recovery requests/profile construction; test storage/reconnect and reject incompatible older firmware.
- [ ] Qualify selector-5 recovery and cleanup on the OTA test node after deployment approval; include lost confirmation, reconnect and deletion/re-addition.
- [ ] Audit re-pairing onto a different node separately from explicit owner reassignment; preserve proven RF prefixes and require old-owner revocation before any new automatic ACK grant.
- [ ] Qualify stock/custom coexistence with separate identities and no duplicate HA devices.
- [x] Document [device/association recovery](docs/DEVICE_RECOVERY.md), deletion guards and unverified battery-rejoin limits.

## Phase 3 — reliable valve control

### Shared command-phase qualification

- [x] Reconcile all three models' six-bit phase evidence; retain prior one-/four-zone rollover qualifications ([audit](research/VALVE_FULL_PHASE_CROSS_MODEL_AUDIT.md), Sep 30).
- [x] Add offline one-/four-zone full-phase builders; replay captured commands and all 64 phase/action combinations without runtime changes (Sep 30).
- [x] Decode native reply control/work mode separately from phase; reproduce the stock port-4 reply mislabel and retain native negative results in offline tests (Sep 30).
- [x] Add source-only two-run journal; test durable pre-send reservations, restart/commit failure, evidence matching, timeout and budget exhaustion (Sep 30). No live caller.
- [x] Prepare an isolated full-phase canary with durable reservations and parity-independent reply matching; preserve production counters, recovery and exact retry bytes.
- [x] Complete HTV145 adjacent phases 8 → 9 and verified counter handback (Oct 1).
- [x] Complete HTV405 dry Zone 2 adjacent phases 4 → 5 with positive ACK, active/automatic-idle and verified production counter handback to 3 (Oct 1). Boundary tests need separate approval.
- [x] Prepare the shared native-phase codec and source-only durable allocator; test legacy-state preservation, pending-command rejection, exact bytes, restart, commit failure, duplicates and negative/missing results (Oct 1).
- [x] Bind opt-in standard controls to the native allocator, persistent radio receipts and HA transaction feedback; test duplicate/restart/negative/missing evidence. Production and pairing unchanged (Oct 2; source only).
- [x] Implement source-only native recovery, atomic legacy handback and retired-epoch archival; retain failed history and block legacy probes (Oct 2).
- [x] Audit older tests against current paths and evidence; retain legacy, migration and captured-packet regressions. No obsolete or exact duplicate tests found (Oct 2).
- [x] Prepare private dry-outlet qualification limits: two 60-second native attempts, durable budget, expiry/reboot lock and blocked HA commands; gateway/radio enforce scope independently (Oct 2; source only).
- [x] Qualify HTV405 native OPEN phases 2 → 3 and correlated no-RF handback on dry Zone 2; restore ordinary startup and retained counter 2 (Oct 2).
- [x] Rehearse public native OPEN → CLOSE → OPEN for HTV145/HTV405 with adjacent phases and independently confirmed state (Oct 3; offline only).
- [ ] Qualify native no-RF recovery, reboot/lost receipts and fresh-epoch readmission on dry hardware.
- [ ] Qualify native-mode OPEN/CLOSE and same-action rollover on dry outlets with bounded, separately approved tests.
- [ ] Consolidate/sign the production build without experiment controls; stage the matched gateway/radio rollout after qualification.

### Four-zone valve

- [ ] Correlate one installed run's RF, duration, HA feedback, automation and watchdog outcomes.
- [ ] Verify explicit early stop on Zones 2–4.
- [ ] Re-pair an unchanged association and confirm its authenticated counter is preserved.
- [ ] Restart gateway/node during a bounded run; verify no replay or speculative close.
- [ ] Qualify late replies, RF timeout, duplicates, spacing, recovery and observed overdue runs.
- [ ] Test retained counters at 1/4/8/12 hours after sync without intervening commands.
- [ ] Separate counter-staleness causes: elapsed time, restart/reconnect, ACK gaps and stock traffic.
- [x] Restore HTV405 remaining-time low bit; test captured 895-versus-894 and 0–3,600 seconds; deployed with gateway 0.39.1.
- [ ] Repeat association/control on another specimen or compatible hardware profile.

### Single-zone valve

- [x] Verify idle and active-run restart recovery, automatic stop and early close without replay.
- [x] Promote the proven association to standard firmware and HA controls.
- [x] Verify the first front-garden scheduled run and valve-reported stop.
- [x] Correlate the Sep 21 scheduled single-zone run's HA trace with RF-reported start/stop and 35-minute duration.
- [ ] Measure report/summary ACK timing, residue and retry suppression independently on air.
- [ ] Complete the command-phase model for arbitrary action order, including consecutive opens.
- [ ] Repeat operational acceptance on fresh associations/batteries.
- [ ] Correlate scheduled-run HA traces, rendered success/failure feedback and actual push delivery.

### HA and irrigation

- [x] Prove soil ACK/nonmeasurement traffic preserves stale moisture through ingestion, restart and HA reporting properties (Sep 27); local regression tests pass.
- [ ] Verify deployed watering stale-input fallback and valve state/link timestamp presentation; offline soil tests do not qualify these consumers.
- [ ] Verify end-to-end watering state comes only from responses/telemetry, never outbound intent.
- [ ] Qualify one-active-zone enforcement, per-zone durations, schedules, notices and watchdog.
- [ ] Exercise scheduled fallback with some/all moisture readings stale beyond 6–8 hours.
- [ ] Verify live schedules/timestamps outside Eastern time; UTC/offset/DST software tests exist.

## Phase 4 — field decoding

- [x] Decode sensor moisture/categorical battery and HTV145 state/duration/usage/categorical battery.
- [x] Decode HTV405 zones, durations and control counters; omit unsupported water usage.
- [ ] Compare all supported fields against timestamped physical/cloud observations.
- [ ] Validate HTV405 battery byte 17 mask 0x08 with a controlled normal-to-low transition.
- [x] Audit discovery against product codes/capabilities, not names or household endpoints; add cross-layer contract tests.

## Phase 5 — stability qualification

- [x] Implement the durable, fixed-window, read-only reliability collector.
- [x] Review the completed 72-hour collection: 874 snapshots, 66,569 events, no collector gaps.
- [x] Update standalone collection for TLS using HA's saved credential; retain the old evidence database.
- [x] Preserve the partial Sep 13 integration 0.18.1 baseline; pause collection and its follow-up for the user-approved wizard deployment/testing. This is not a completed qualification.
- [x] Review the [Sep 17–22 passive field evidence](research/FIELD_RELIABILITY_20260922.md): sustained reporting, seven bounded runs and restart recovery; record the brief sensor freshness exception.
- [ ] **Deferred by user Sep 13:** revisit a new 72-hour baseline if needed; it does not block native-flow testing or current alpha work. Keep collection/follow-up paused and preserve existing evidence; do not automatically restart.
- [x] Observe at least three successful local scheduled watering cycles; six scheduled runs plus one manual run had valve-reported starts/stops.
- [ ] Include the separately qualified stock/custom coexistence scenario in stability acceptance.
- [ ] Include HA/gateway restart, node reboot/OTA and device battery cycle without state loss/replay.
- [ ] Validate weak-link placement from evidence before relocating radios.
- [x] Verify the Sep 22 gateway inventory has eight expected devices and six unique sensor ACK assignments.
- [ ] Qualify historical HA duplicate/false-state absence, stale-data decisions and alert flapping under failure conditions.
- [x] Verify interrupted OTA retains the running image and a later retry can succeed.
- [ ] Physically test bad-checksum OTA, boot-time power loss, unhealthy rollback and USB recovery.

## Phase 6 — open-source hardening

- [x] Remove household runtime defaults; keep captures/probes and replay examples outside production.
- [x] Fix the concurrent registry-test read race without changing RF assertions.
- [x] Add event-driven sensor updates with authoritative snapshots and slow reconciliation.
- [x] Implement HA config version 3 migration and schema 25 per-valve storage migration.
- [x] Implement TLS, credential lifecycle, API limits and approved publisher-signed OTA.
- [x] Enforce signed OTA and test rejection before flash in the host-linked verifier.
- [x] Retire dual-radio production builds; keep one supported radio environment.
- [x] Audit typed/versioned protocol, gateway, HA and research interfaces; preserve established contracts.
- [x] Retire obsolete firmware-checker variants; retain only research controls required by open tests.
- [x] Review Alpha 1 installable artifacts and add repeatable private-file/key checks to CI.
- [ ] Define and test the signed catalog v2 compatibility contract for independently versioned integration, gateway and firmware releases; authenticate hardware/profile/variant/channel, protocol ranges, capabilities and monotonic generation, and reject tampering, replay and downgrade.
- [ ] Add a GitHub Releases catalog adapter behind the gateway's existing resolver, retain the strict local/offline adapter and last-known-good cache, publish immutable channel-specific assets through the approved workflow, and qualify dependency ordering plus offline staged updates. The HA integration remains a presentation/install client, not a second release resolver.

See the [software audit](research/ALPHA_SOFTWARE_AUDIT_20260912.md) for scope and evidence.

Always preserve authentication, association-bound TX, bounded duration, spacing,
device-owned confirmation, at-most-once opens and rollback. These are invariants,
not tasks to mark “done once.”

## Phase 7 — documentation and research infrastructure

- [x] Verify private stock-hub backup and document offline implementation audit, reproduced ACK defects and custom-firmware feasibility (Sep 27); no hardware port or protocol fix implied.
- [x] Resolve and run approved model/region-specific firmware lookup (Sep 27): no newer image offered for 1.1.1040; private response retained, no download or hub update.
- [x] Consolidate the retained firmware reference and prepare a review-first local improvement plan; keep unresolved protocol coverage explicit.
- [x] Replace the crashing offline analysis path with the official S3 decoder; verify synthetic raw-input decoding and nine bounded firmware regions (Sep 27).
- [x] Qualify offline Ghidra decompilation: six matching load segments, seven selected functions and counter-harness checks; [evidence](research/STOCK_HUB_DECOMPILATION.md), Sep 27.
- [x] Expand to 215 function exports; verify boot sequence zero-fill, reconnect migration setter/storage and conditional per-port parameter replies (Sep 27).
- [x] Corroborate native framing/CRC against 516 valid public frames; explain the one-bit offset and both legacy residues without changing runtime codecs.
- [x] Trace six-bit command generation, retained-packet retries, ACK matching and native valve durations; add capture-backed tests (Sep 27).
- [x] Trace report-mode server ACK and compact-state grammar across both retained versions; rule out a direct soil-wake interpretation of that path.
- [x] Validate stock-informed source repairs with the complete Python suite, native protocol tests and unified firmware build; no deployment (Sep 27; results in the improvement plan).
- [x] Trace `ReciCH` to native `20` channel notification and startup notification; both consume the shared sequence. No qualifying channel-change capture yet.
- [ ] Qualify channel-change acceptance, absolute RF mapping and durable retune with an approved capture.
- [x] Trace report-mode readers: class-0x50 report replies carry the mode; captured HCS026 class 0x48 is excluded. This is not a soil wake mechanism.
- [x] Trace HCS026 offline callbacks and known-announcement recovery: no wake TX on the inspected expiry path; incoming known announcements retain association/channel.
- [x] Resolve retained HTV145 heartbeat selector 31 to compact field 24; no HCS026/HTV405 descriptor available in this snapshot.
- [ ] Resolve model-qualified heartbeat descriptors and capture reconnect-result-9 acceptance before new recovery behavior.
- [x] Decode terminal `59/D9` as parameter read; prove failed trials repeat preceding `06` requests ignored by the pre-fix matcher.
- [x] Reproduce three sequence-correlation defects offline: wrong-phase negative replies consume reservations; an opposite-action positive reply authenticates the HTV405 node, unlike the gateway.
- [x] Fix full-six-bit response matching and bounded HTV145 plan retries in source; preserve first-reply bytes and idle-anchor behavior. Offline regressions pass; not deployed.
- [ ] Qualify those repairs on the idle node using the short canary plan; count only observed device acceptance, not transmitted replies.
- [x] Qualify retained HTV145 descriptor: no category-0 parameters, so fresh initialization selects the empty per-port terminal array.
- [x] Trace cloud-gated startup notifications consuming the shared sequence before transmission acceptance.
- [x] Trace stock ACK/timeout lifecycle: four retained-packet retries at 700-ms timer intervals; no reset established on those paths. Qualify conditional hidden phase consumption.
- [x] Compare retained versions: generator instruction body and full-phase ACK matching agree; no generator-algorithm change found.
- [x] Compare native pairing shapes across HCS026/HTV145/HTV405: 42 captured rows; distinguish shared commands, per-port repeats and gateway-originated phases (Sep 28).
- [x] Replay three recorded HTV145 failures through the native session; preserve initial replies, bound retries and reject false completion; reconcile native/legacy protocol docs (Sep 28).
- [x] Trace model-specific `05` settings and `06` plan paging; correct `20` notification byte to configuration version, not RF channel. Offline suite: 696 passed, two skips; native protocol passed (Sep 28).
- [x] Trace configuration revisions and fourteen-byte valve settings; distinguish asynchronous settings arrival from fixed pairing stages ([evidence](research/STOCK_HUB_CONFIGURATION_LIFECYCLE.md), Sep 28).
- [x] Trace saved associations, known rejoin and three direct sequence-generator callers; no periodic reset established ([evidence](research/STOCK_HUB_ASSOCIATION_PERSISTENCE.md), Sep 28).
- [x] Add offline semantic trace analysis and capture-backed retry/missing-response checks; 708 tests passed, two optional NumPy skips, native protocol passed (Sep 28). No device acceptance implied.
- [ ] Audit local enrollment durability under storage failures; inject save/restart failures before changing admission behavior.
- [ ] Qualify valve settings units and notification triggers with controlled one-field changes; keep proven pairing prefixes frozen.
- [ ] Resolve later sequence restoration/reset rules and HTV405 terminal descriptors; boot clear alone does not explain overnight failures.
- [x] Capture HTV213 stock enrollment and both-zone automatic stops; verify 60/120-second RF commands, replies and summaries ([evidence](research/HTV213_STOCK_CAPTURE_FINDINGS_20260928.md), Sep 28).
- [x] Qualify stock HTV213 explicit close after 35 seconds: matched response, independent idle and 34-second summary; preserve redacted fixtures (Sep 28).
- [x] Freeze HTV213 stock evidence in 44 redacted frames and six tests; full suite 714 passed/two optional skips, native protocol passed (Sep 28). No local two-zone TX enabled.
- [x] Qualify stock HTV213 control after >30 minutes idle: phase-7 open, matching reply, idle and 60-second summary (Sep 28). Unrecorded intervals remain coverage gaps.
- [x] Qualify stock HTV213 control after >3 hours idle: phase 8, matching reply, port-2 idle and 60-second summary (Sep 28). Gaps do not establish counter resets.
- [x] Capture HTV213 hub-only RST recovery: startup `20` kind 1/phase 2, then accepted phase-3 open and 60-second stop with valve left powered (Sep 28); no decoded re-pairing.
- [x] Capture HTV213 battery rejoin without pairing mode: retained assignment, per-port state/settings/plans, then phase-4 control and confirmed 60-second stop (Sep 28).
- [x] Implement offline firmware `02/05/06` responder: retained revision/selector, per-model ports, full-phase echo and explicit settings/plan knowledge; replay 44 captured exchanges across all three valves.
- [x] Preserve 64 redacted lifecycle frames and regression coverage for idle, hub restart, battery rejoin and report-phase wrap; no inferred counter-reset rule.
- [x] Add explicit `20` kind-0/kind-1 body builder without automatic counter allocation, reset or production dispatch.
- [x] Validate valve-learning source: 728 Python tests passed/two optional skips, both native protocol executables passed, unified firmware compiled; no deployment.
- [x] Persist explicit recovery settings/progress; check authenticated ownership and journal before dispatch. Test restart, duplicate delivery and failed commits without changing counters.
- [x] Delete recovery state atomically with its association; test rollback and isolation from other valves.
- [x] Trace/build HTV213 retained `01/81`: distinguish device address, request carrier selector, saved routine selector and native clock. Keep other models unqualified.
- [x] Validate recovery source: 741 Python tests passed/two optional skips, both native protocol executables passed and unified firmware compiled (Sep 29); no deployment.
- [x] Implement isolated HTV213 dry-pairing candidate: stock-byte replay, full-phase replies, both-port configuration and bounded authenticated cancellation; default firmware excludes it.
- [x] Validate candidate offline: 762 Python tests (two optional skips), native protocol test, canary/default builds and production exclusion check passed (Sep 29); not deployed or RF-qualified.
- [x] Deploy gateway 0.39.2 and HTV213 pairing.1 to the unassigned test node; verify flash hash, authentication, valid radio RX and disarmed state. Garden firmware unchanged (Sep 29).
- [x] Reproduce/fix HTV213 firmware ingress dropping start/cancel commands; compile the actual gate in both modes and pass 41 targeted tests. RF sequence unchanged (Sep 29).
- [x] Flash/verify pairing.2 and confirm start/cancel reach the test node; first RF trial captured a rejected announcement variant (Sep 29).
- [x] Replay/fix exact HTV213 repeat announcement `0b…07`; retain original assignment bytes, timing, configuration and rejoin rejection.
- [x] Restore/verify pairing.3 after USB reconnection: application hash verified, authenticated reconnect, radio configured and TX disarmed (Sep 29).
- [x] SDR-confirm three pairing.3 assignment replies; valve still rejects. Reproduce selector-11/request versus selector-12/TX mismatch and measure ~45.5-kHz configured/on-air offset.
- [x] Fix request-derived HTV213 reply carrier with native regression and two-slot cache test; preserve payload, phase echo and timing. Prepare a bounded node-only correction from captured RF.
- [x] Restore/verify pairing.4 via explicit USB RTS reset and one serial retry: device hash verified, authenticated reconnect and TX disarmed (Sep 30).
- [x] SDR-verify pairing.4 corrected carrier, accepted assignment and both-port reports/ACKs on Test Node B (Sep 30); freeze this prefix, not a universal frequency correction.
- [x] Reproduce/fix HTV213 post-notification RX handoff: restore base frequency, not just channel index; native runtime replay covers positive/missing/mismatched ACK and restore failure (Sep 30).
- [x] Validate/deploy pairing.5 to Test Node B only: 770 tests/two optional skips, native protocol and both builds passed; USB hash verified, authenticated and disarmed (Sep 30).
- [x] SDR-verify pairing.5 assignment, positive notification ACK and both-port settings/plan replies; preserve 30 redacted frames and native replay, 17 focused tests passed (Sep 30).
- [x] Implement isolated HTV213 controls and durable phase reservations; replay stock open/stop, channel handoff, disconnect and no-retry paths. Default firmware excludes controls (Sep 30).
- [x] Deploy the control canary to Test Node B; capture one phase-3/60-second port-1 command. No acceptance; later port-2 idle confirms retained local identity. Preserve negative fixture (Sep 30).
- [x] Diagnose/fix the omitted final native CRC bit in the experimental RMT path; preserve pairing and production streams (Sep 30).
- [x] RF-qualify control.2 on Test Node B: one authorized phase-3/60-second port-1 retry produced matching open ACK, countdown, idle and summary. Preserve both attempts and redacted replay (Sep 30).
- [x] RF-qualify HTV213 port-2/60s at phase 4 and port-1 early stop at phases 5→6; preserve redacted native replay (Sep 30).
- [x] Implement/deploy isolated HTV213 routine owner; SDR confirms both-port reports with phase-echo ACKs (Sep 30).
- [x] Recover Test Node B with a hash-verified control.4 flash and authenticated reconnect (Sep 30); intermittent USB failures remain unexplained.
- [x] Verify radio/gateway owner restoration, 300-second Port 2 and post-HA-restart 60-second Port 1 runs with RF acceptance/idle/summaries (Sep 30).
- [x] Expose two-outlet dry-canary HA controls; verify duplicate-open disabling and persistent notifications. Fix ACK-before-watering duration omission (Sep 30).
- [x] Replay missing/late confirmations and overdue completion; fix stale-idle display, missing-summary classification and duplicate overdue alerts (Sep 30; offline qualification).
- [x] Prepare opt-in retained-rejoin replies with request-derived carrier and both-port replay; leave deployed responder disabled and pairing unchanged (Sep 30).
- [x] Independently audit stock master wrap through zero and shared allocation; preserve [evidence](research/HTV213_COUNTER_WRAP_AUDIT.md) (Sep 30).
- [x] RF-qualify HTV213 master phases 62→63→0→1: four one-minute runs, full completion evidence and redacted replay; enable wrap only for the qualified association (Sep 30).
- [ ] Qualify HTV213 missing-response/overdue handling on dry hardware; offline replay passes, physical loss remains untested.
- [ ] After HTV213 qualification, audit other device transmit paths for the omitted native CRC bit; do not change proven production paths speculatively.
- [ ] Verify HTV213 post-configuration reports and repeat complete enrollment before promotion. Stock gateway off; ask before arming.
- [ ] Qualify HTV213 routine ACK ownership and retained rejoin before HA model-menu or operational support; preserve existing one-/four-zone paths.
- [x] Wire opt-in HTV213 retained replies to explicit durable per-port configuration; replay real RX/TX, restore after reconnect and keep master counters unchanged (Oct 3; source only).
- [x] Add unpublished `htv213-recovery` signing profile and production/cross-profile exclusion tests; retain protected human approval (Oct 3; source only).
- [x] Validate recovery source: 956 tests/two optional skips, native protocol and candidate/default firmware builds pass; no live changes (Oct 3).
- [x] Push recovery source for review in PR #31; prepare matched gateway 0.39.15 and protected control.5 signing profile (Oct 3). Deployment remains pending.
- [ ] Sign/deploy the HTV213 recovery candidate to Test Node B, then verify battery rejoin without pairing mode and one short dry control; no counter reset inferred.
- [ ] Add other model recovery handlers after model-specific retained-assignment captures; preserve proven enrollment.
- [ ] Isolate whether startup `20` kind 1 changes valve counter acceptance; restart trace shows correlation, not causation.
- [x] Capture HCS012ARF first boot and stock-app pairing: checksum-valid OOK reports retain the same ID, zero rain and battery OK (Sep 28); local support remains unqualified.
- [ ] Qualify HCS012 rainfall increments, accumulation/reset and battery flags against stock-app readings before adding a local model profile.
- [ ] Qualify active CMT profile, physical GPIOs, absolute channels and full CRC bit with passive capture; static tables/FIFO mapping are documented.
- [x] Keep current device protocols separate from historical experiments.
- [x] Shorten this roadmap; preserve detailed evidence and distinguish implementation from acceptance.
- [x] Implement a storage-bounded Mac SDR journal/service runner and receive-only TLS forwarding; test child lifecycle and real gateway authentication.
- [ ] Install/qualify the Mac SDR service, dedicated identity and USB recovery; Sep 12 check found no supported USB receiver.
- [x] Keep research in this repo through alpha, excluded from installation artifacts (user approved Sep 12).
- [ ] Revisit research-repo separation before stable release.
- [x] Keep one canonical checkout; preserve raw RF evidence and installed/rollback artifacts.

HA must remain independent of SDR. Check current hardware availability when
scheduling capture tests rather than treating an old unplugged-device note as current.

## Deferred migration and backlog

- [ ] Review and finalize the separate [irrigation app requirements](docs/IRRIGATION_APP_REQUIREMENTS.md), including the daily overview and advisory overlap warnings, alongside the [initial UI concepts](docs/irrigation-ui/README.md). Requirements and design work only; implementation waits for product review and does not change the hardware qualification order.

Cloud-to-local migration and a HomGar merge remain deferred until lifecycle,
recovery, control, field and stability acceptance is complete. No integration-merge
implementation or hardware optimization in this pass.

- [x] Preserve verbatim source timestamps plus explicit UTC receipt time in the new Mac SDR journal; never reinterpret old captures.
- [x] Scope device lookups to their owning gateway on modern HA; retain the 2026.7 fallback and reject cross-entry matches.
- [ ] Discover new device families and determine whether sensor P1–P6 soil type is local/RF/cloud.
- [ ] Identify sensor MCU/debug pads from the planned PCB inspection; assess read-only firmware access before connecting a programmer. Not an alpha release gate.
- [ ] Trace stock per-model capabilities, rain-gauge reset/calibration and timezone serialization; promote only model-qualified fields with packet evidence.
- [ ] Decide whether to support the stock ESP32-S3/CMT2300A hub as another radio platform after passive mapping; require shared protocol logic, board-specific signed OTA and approved restore/RX-only tests before any TX.
- [ ] Determine whether pairing can select the long-term telemetry channel.
- [ ] Characterize compact product/status integrity before generating those messages.
- [ ] Optimize channel scheduling/placement beyond the required stability floor.
- [x] Correct Rev A's reversed radio rows with Rev B; pass four physical-position tests, ERC/DRC/parity and regenerate fabrication/assembly/fit artifacts. Withdraw Rev A order archives; physical acceptance remains separate.
- [ ] Verify Rev B module numbering, all eight connections and first-board power/RF operation; CAD checks alone do not pass this gate.
- [ ] Verify a removable Rev A crossover harness if salvaging existing boards; no live testing without user readiness.
- [ ] Finish carrier enclosure work under its separate physical checklist.

Promote side work only if it blocks acceptance, invalidates evidence or protects
irrigation reliability; otherwise keep it in the backlog.
