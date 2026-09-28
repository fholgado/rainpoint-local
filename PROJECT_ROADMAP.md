# RainPoint Local project roadmap

Last reviewed: 2026-09-27

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

Stock-hub research remains hardware-read-only; no new hardware tests without
approval. The approved off-device update lookup offered no newer image for this
hub on Sep 27. The user approved source changes/tests for ownership cleanup,
retained-channel recovery and remaining-time decoding; **no deployment**.
The subsequent unattended-work approval also covers source/test repairs for
full-phase reply matching and bounded single-zone plan-request retries. These
are implemented offline; hardware acceptance and deployment remain separate.
See the [expanded regression audit](research/STOCK_HUB_LOCAL_REGRESSION_AUDIT.md)
and [replacement-firmware assessment](research/STOCK_HUB_CUSTOM_FIRMWARE_FEASIBILITY.md).
Research branch: `codex/stock-hub-research`. Refine and qualify our existing
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

### Four-zone valve

- [ ] Correlate one installed run's RF, duration, HA feedback, automation and watchdog outcomes.
- [ ] Verify explicit early stop on Zones 2–4.
- [ ] Re-pair an unchanged association and confirm its authenticated counter is preserved.
- [ ] Restart gateway/node during a bounded run; verify no replay or speculative close.
- [ ] Qualify late replies, RF timeout, duplicates, spacing, recovery and observed overdue runs.
- [ ] Test retained counters at 1/4/8/12 hours after sync without intervening commands.
- [ ] Separate counter-staleness causes: elapsed time, restart/reconnect, ACK gaps and stock traffic.
- [x] Restore HTV405 remaining-time low bit; test captured 895-versus-894, 0–3,600 seconds and existing valve regressions. Not deployed.
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
- [ ] Resolve later sequence restoration/reset rules and HTV405 terminal descriptors; boot clear alone does not explain overnight failures.
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
