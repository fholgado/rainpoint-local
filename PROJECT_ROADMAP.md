# RainPoint Local project roadmap

Last reviewed: 2026-09-12

This is the only live checklist. Completed implementation does not imply physical
qualification. Detailed history and proof are in the
[evidence index](research/IMPLEMENTATION_EVIDENCE_20260912.md), not the task text.

## Current work order

1. Build/test the dedicated pairing wizard without changing the live RF paths.
2. Observe the fixed 72-hour baseline; keep gateway/radio versions and schedules unchanged.
3. Collect physical lifecycle results, then complete stable-release qualification.

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
- [x] Build the catalog-driven wizard with Back/Next, staged progress, scoped cancellation and refresh recovery; pass isolated browser and real HA lifecycle checks.
- [x] Return to the device list after removal in the new panel; native HA's separate device page is unchanged.
- [ ] Deploy integration 0.18.2 after the baseline; physically qualify the new wizard for sensors and both valves.
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
- [ ] Verify sustained reporting/control on the custom-ID association.
- [ ] Compare stock reset/enrollment, retained long-press pairing and battery rejoin with fresh batteries.
- [ ] Complete the terminal stage without changing the proven prefix; repeat each new boundary twice.
- [ ] Complete three unchanged full local enrollments.
- [ ] Remove/re-pair through HA and retain one identity; qualify battery rejoin separately.

## Phase 2 — persistence, recovery, and coexistence

- [x] Confirm direct ESP32 sensor reporting recovery without SDR assistance.
- [ ] Qualify repeated HTV405 report cycles and longer gateway/node restarts with one ACK owner.
- [ ] Battery-cycle sensors; restore the same HA identity and reports without arming pairing.
- [ ] Capture stock battery rejoin for both valves, then prove equivalent local recovery.
- [ ] Restart HA, gateway and assigned radios while idle; preserve state with no command replay.
- [ ] Reassign a sensor ACK owner; prove revocation occurs before replacement transmissions.
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
- [ ] Repeat association/control on another specimen or compatible hardware profile.

### Single-zone valve

- [x] Verify idle and active-run restart recovery, automatic stop and early close without replay.
- [x] Promote the proven association to standard firmware and HA controls.
- [x] Verify the first front-garden scheduled run and valve-reported stop.
- [ ] Measure report/summary ACK timing, residue and retry suppression independently on air.
- [ ] Complete the command-phase model for arbitrary action order, including consecutive opens.
- [ ] Repeat operational acceptance on fresh associations/batteries.
- [ ] Correlate scheduled-run HA traces, rendered success/failure feedback and actual push delivery.

### HA and irrigation

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
- [ ] Review the unchanged-version baseline started Sep 13 00:24 UTC; ends Sep 16 00:24 UTC (gateway 0.39.0, integration 0.18.1, firmware 0.19.0).
- [ ] Include coexistence and three successful local scheduled watering cycles.
- [ ] Include HA/gateway restart, node reboot/OTA and device battery cycle without state loss/replay.
- [ ] Validate weak-link placement from evidence before relocating radios.
- [ ] Observe no phantom devices, duplicate ACK owners, false states, stale decisions or alert flapping.
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
- [ ] Determine whether pairing can select the long-term telemetry channel.
- [ ] Characterize compact product/status integrity before generating those messages.
- [ ] Optimize channel scheduling/placement beyond the required stability floor.
- [ ] Finish carrier manufacturing/enclosure work under its separate physical checklist.

Promote side work only if it blocks acceptance, invalidates evidence or protects
irrigation reliability; otherwise keep it in the backlog.
