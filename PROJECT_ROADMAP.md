# RainPoint Local project roadmap

Last reviewed: 2026-08-26

This is the single source of truth for active project status, ordering, and
completion. Architecture documents describe intended boundaries, protocol
documents record wire evidence, research plans preserve procedures and trial
history, and hardware checklists remain operational checklists. None of those
documents independently schedules work.

## Working rules

- Work phases in order unless a later item blocks the active phase.
- Mark an item complete only when its stated evidence exists. A successful RF
  transmission is not evidence that a device accepted a command.
- Update this file in the same commit that completes or changes a tracked gate.
- A newly discovered issue enters the active phase only when it blocks its exit
  criteria, invalidates evidence, or protects irrigation safety/reliability.
  Everything else goes to [Backlog](#backlog).
- Preserve redacted RF fixtures and concise trial results in `research/`; link
  them from the relevant task rather than copying research journals here.
- Use **stock RainPoint gateway** for the vendor hub and **custom local
  gateway** for `rainpointd` plus its ESP32/CC1101 radio nodes.

## Status-source disposition

| Former source | Role after consolidation |
|---|---|
| Root `README.md` remaining gates | Replaced by a link to this roadmap |
| `INTEGRATION_EVOLUTION_BACKLOG.md` | Absorbed here and removed |
| `PROTOCOL.md` remaining work | Retained as unscheduled wire-evidence questions |
| `FULL_STACK_ARCHITECTURE.md` phases | Architecture description only |
| `HARDENING_INVENTORY.md` | Boundary inventory only |
| `CLOUD_TO_LOCAL_MIGRATION.md` readiness gates | Deferred product-design constraints only |
| `research/*PLAN.md` and protocol status | Evidence ledgers and reusable procedures only |
| Carrier preorder checklist | One physical-operation checklist, not project status |

## Phase 0 — one clean baseline (complete)

Before the baseline cleanup, the deployed radio nodes spanned three firmware
versions, and historical invalid-trailer HTV405 observations left three phantom
four-zone devices beside the one canonical valve. Further reliability
measurements would have been ambiguous until that baseline was clean.

- [x] Reject invalid or provisional valve identities before they can create a
      Home Assistant device.
- [x] Remove the three known phantom HTV405 records through the supported
      lifecycle path; preserve the canonical association and its HA history.
- [x] Verify dashboards, automations, notifications, and watchdogs reference
      only the canonical local valve and local moisture entities.
- [x] Publish one consolidated supervised radio-node image containing the
      validated sensor, custom-identity, OTA, diagnostics, HTV405 pairing, and
      HTV405 control paths without the HTV145 research transmitter.
- [x] Upgrade the valve-owning node first and prove its association, command
      counter, ACK assignments, and controls survived.
- [x] Upgrade the remaining nodes one at a time and run the same reconnect,
      receiver, ACK-owner, and diagnostic checks after each update.
- [x] Reconcile the installed gateway package/version label with the running
      source and retain one rollback artifact.

Exit criteria: every deployed node runs the same firmware; the existing
sensors and valve remain usable; HA exposes one canonical HTV405 device; and a
normal observation window creates no replacement phantoms.

On 2026-08-26, all three adopted nodes were upgraded sequentially to the
unified `0.15.0-supervised-beta.10` image. Each retained its node ID,
authenticated, returned disarmed, and restored its gateway-owned sensor ACK
assignments. The canonical HTV405 retained its Vegetable Garden control owner
and authenticated command-counter state. Front Yard required roughly two
minutes to reconnect and reported weak Wi-Fi near -90 dBm; placement/network
quality remains an operational concern, not a firmware-identity failure.

## Current focus: Phase 1 — Home Assistant device lifecycle

- [x] Present the custom gateway's user-pairable profiles under Sensors and
      Valves, list supported models beneath each category, and filter radio
      nodes by the selected profile's advertised capability.
- [x] Start HCS026 and HTV405 enrollment from HA without copied RF identities;
      the selected node adopts the first strict model-specific factory
      announcement within the bounded session. Physical repetition gates below
      remain open.
- [ ] After a successful device removal, navigate back to the RainPoint Local
      device list instead of leaving the user on the deleted device's error
      page.

Home Assistant's supported integration removal hook controls whether removal
is allowed but exposes no frontend-navigation callback. Backend removal is now
family-neutral; the remaining redirect is an upstream HA frontend constraint,
not a gateway lifecycle mutation.

### HCS026-class soil sensors

- [x] Pair independent sensor identities from the HA UI without copied RF IDs,
      setup tokens, or CLI commands.
- [x] Auto-advance the pairing flow after physical terminal evidence.
- [x] Physically enroll a disposable sensor under a generated, persisted custom
      RF controller identity.
- [ ] Complete three consecutive pair -> report -> remove -> re-pair cycles on
      unchanged final firmware, including one installed sensor and both test
      sensor identities.
- [ ] Confirm removal clears the device, entities, suppression state, and ACK
      assignment, and that re-pairing does not leave a duplicate.

### HTV405 four-zone valve

- [x] Reproduce local association and accept paired valve-originated traffic as
      terminal evidence.
- [x] Merge partial HTV405 zone observations across concurrent SDR and radio
      node receivers without replacing previously known booleans with unknown.
      The regression replays the exact 2026-08-26 complete-idle then partial
      Zone 3 idle sequence that had changed Zone 1 from Off to Unknown in HA.
- [x] Let the selected node finish its bounded HTV405 association work after HA
      receives terminal evidence; naming the device must not cancel remaining
      protocol replies. The 2026-08-26 generated-identity validation reached
      the `13/2C/99` tail and then transitioned directly into ordinary paired
      reports. The stock transcript's later `9A` rows are not a universal
      completion requirement.
- [x] Count strict selector-`0x07` paired-link reports as device activity without
      replacing the latest definitive zone/watering state, then prove the valve
      continues reporting after association. The validated valve reported on
      the generated route every approximately 40 seconds through the command
      acceptance trial.
- [x] Complete three consecutive HA-initiated new-enrollment trials on unchanged
      final firmware.
- [x] Pair once under a generated custom controller identity and create exactly
      one capability-correct HA device.
- [ ] Confirm HA removal clears all four zone controls, duration entities,
      association state, and node routing; then re-pair without a duplicate.

Software coverage now proves that removal deletes the valve link and routing,
ordinary reports cannot defeat suppression, and an explicit pairing session
can restore the same stable device ID exactly once. Physical HA removal and
re-pair evidence is still required before checking the gate.

Three strict generated-identity HA enrollments are now retained. The third,
performed on the consolidated beta.10 image on 2026-08-26, produced the physical
white success flash, reached the accepted `13/2C/99` tail at 16/18, and was
independently confirmed by another radio receiving ordinary traffic addressed
to the generated controller. HA reused `htv405-94a98013`, created no duplicate,
and reset the authenticated command counter to `1`. Earlier copied-identity
white flashes and retained-association rejoins remain excluded from this count.

- [ ] Once HA accepts command-scoped HTV405 terminal evidence, make the selected
      node leave the bounded tail in a successful/disarmed diagnostic state.
      The third accepted trial correctly remained armed so it could answer the
      optional final stock-tail messages, but when those messages never arrived
      its local five-minute timer later reported `session_timeout`/`failed` even
      though HA had already finalized a valid association. Fix this misleading
      post-success status without sending an RF cancellation or regressing the
      proven 16/18 completion path.

Success criteria for this diagnostic fix:

1. Only an active-session valve frame addressed to the generated controller
   may set the authoritative pairing outcome to `completed`.
2. The selected node remains visibly armed while it can answer optional tail
   requests; control and unrelated RF commands remain blocked during that time.
3. If the optional tail expires after accepted terminal evidence, the effective
   node pairing state is `completed`/disarmed with no pairing failure. The raw
   node result remains available separately as `failed`/`session_timeout` with
   tail state `optional_tail_timeout` for protocol research.
4. A timeout before terminal evidence remains a real failure and the HA flow
   continues to abort as `pairing_timeout` or `pairing_failed`.
5. The fix sends no RF cancellation, changes no pairing payload/frequency/
   timing, creates no duplicate device, and does not reset the authenticated
   valve command counter after the first accepted terminal frame.

Gateway 0.33.11 implements this effective/raw outcome split and is deployed.
Automated coverage reproduces both the observed post-terminal 16/18 timeout and
a real pre-terminal timeout; all 317 Python regressions and the native firmware
protocol test pass. Leave this physical gate open until one later HTV405 pairing
shows `pairing_outcome=completed`, raw node `failed`/`session_timeout`, tail
`optional_tail_timeout`, and an available counter-synchronized valve after the
five-minute node window expires.

### HTV145 single-zone valve

- [x] Decode stock enrollment/control evidence sufficiently to build a bounded,
      compile-gated candidate.
- [x] Implement the generalized HA pairing lifecycle without exposing the
      unaccepted research transmitter as a production control.
- [x] Preserve two rejected selector-5 local trials, restore the probe-.2
      49.5 ms accepted assignment prefix, and require continuous IQ evidence
      before changing stage 0 again.
- [ ] Capture at least two additional complete stock-gateway HTV145
      enrollments and record the app Device Address for each. Compare the
      assignment selector, assignment carrier, first paired request marker,
      and routine carrier as one coherent branch before changing the local
      transcript. This repeats the evidence path that exposed the decisive
      selector-2/selector-6 branches during HTV405 development.
- [ ] Complete three consecutive local pairings with fresh batteries and
      valve-originated terminal evidence.
- [ ] Confirm removal and re-pairing preserve the intended stable physical
      identity without stale entities.

Exit criteria: a user can pair and remove every supported family entirely from
HA, each family completes three consecutive final-build trials, and each
physical device has exactly one HA representation.

The 2026-08-26 HTV145 stage-0 discriminator trials all stopped at 1/6: an
on-air reply close to the stock 50.55 ms slot, a six-to-ten-foot separation
trial, and a generated custom controller/companion identity. Continuous IQ
already shows that the local assignment payload, carrier, deviation, wake, and
clock structure match the one retained stock success. These negatives make
small timing, near-field saturation, and retained-controller collision poor
next hypotheses. Only one successful stock selector (`5`) is retained, while
HTV405 required multiple stock enrollments to reveal that selector and carrier
must move together. Corrected bounded-IQ analysis recovered all four
lower-channel paired requests and the controller-configuration response from
the stock success, but zero paired requests after the rejected local
assignments; the stall is valve-side rejection, not a node receive-channel
miss. Preserve the known 49.5 ms prefix until the additional HTV145 stock
branch matrix exists.

## Phase 2 — persistence, recovery, and coexistence

- [x] Persist one sensor ACK owner and restore assignments after ordinary node
      reconnect, gateway reconnect, and successful OTA.
- [x] Freeze recurring stock-gateway HTV405 idle/watering reply evidence and
      implement an association-scoped, non-actuating liveness ACK on the
      valve's single durable control-node owner.
- [ ] Complete the HTV405 liveness soak. The first authorization-scoped over-air
      ACK transmitted successfully on 2026-08-26, and its single-owner
      assignment survived an immediate custom-gateway restart; prove subsequent
      routine valve reports continue across multiple cycles and longer node/
      gateway restarts before closing this gate.
- [ ] Battery-cycle each supported sensor family and restore the same HA device,
      paired identity, and routine reporting without opening pairing.
- [ ] Capture the stock RainPoint gateway's complete battery-rejoin exchange for
      each valve family before changing either proven new-enrollment path.
- [ ] Reproduce retained-association battery rejoin locally for HTV405 and
      HTV145, including authenticated idle/control traffic as terminal proof.
- [ ] Restart HA, the custom local gateway, and each assigned node while devices
      are idle; restore associations, counters, ACK owners, and availability.
- [ ] Deliberately reassign one sensor ACK owner and prove the old owner is
      revoked before the new owner can transmit.
- [ ] With the stock RainPoint gateway powered, prove a custom-identity sensor
      keeps reporting and receiving only its custom-node acknowledgements while
      legacy stock-owned devices continue normally.
- [ ] Repeat coexistence with a custom-identity valve and confirm neither
      gateway steals the association, controls the other's cohort, or creates
      duplicate HA devices.
- [ ] Document the recovery path for every destructive association transition.

Exit criteria: device battery changes and infrastructure restarts do not require
full re-pairing, and stock-owned and custom-owned device cohorts operate at the
same time without conflicting authority.

## Phase 3 — reliable valve control

### HTV405

- [x] Confirm one- and two-minute bounded opens on Zones 1--4 with authenticated
      responses, independent active reports, and valve-owned automatic stops.
- [x] Confirm local explicit early stop on Zone 1.
- [x] Complete an installed 20-minute Zone 1 irrigation run with a valve-owned
      return to idle.
- [ ] Capture stock-gateway commands for durations whose two-second count
      already contains low-byte bit 7, including five and fifteen minutes,
      before constructing them locally. The 2026-08-26 guarded trial proved
      the additive candidates (`16 01` for 300 seconds and, by the same model,
      `42 02` for 900 seconds) are not accepted command encodings: retained
      counter `3` rejected the former, then immediately accepted the proven
      60-second `9e 00` payload and advanced to `4`. Gateway 0.33.14 now
      rejects every duration outside the physically accepted 1-, 2-, and
      20-minute set before reserving a counter or dispatching RF.
- [ ] Retain the end-to-end installed result across RF evidence, usage decode,
      HA completion notification, automation outcome, and watchdog outcome.
- [ ] Confirm local explicit early stop on Zones 2--4.
- [x] Validate control under a generated custom controller identity. A fresh
      generated-identity association initializes the independent command
      counter at `1`: the 2026-08-26 Zone 1 command received an authenticated
      counter-`1` response, independent active reports, and a valve-owned
      automatic stop after 60 seconds. Pairing now initializes that counter
      once without waiting for the unrelated routine telemetry sequence.
- [ ] Preserve an authenticated watering-command counter when an existing
      valve is re-paired to the unchanged custom controller, companion,
      selector, and valve route. The guarded 2026-08-26 five-minute trial found
      that the gateway reset its stored counter to `1` even though earlier
      authenticated responses had established `3` as next; sequence `1`, its
      same-counter retry, and the final sequence-`2` recovery all timed out.
      A guarded discriminator subsequently proved the valve had retained
      sequence `3`; preserve that authenticated value across a same-identity
      repair while continuing to initialize a genuinely new association at
      `1`. The subsequent retained sequence-`4` one-minute run also
      authenticated, advanced to `5`, and stopped itself after 61.414 seconds,
      proving sequence-`3` acceptance was not an isolated coincidence. A new
      physical same-identity repair remains the final gate. Evidence is
      retained in
      `research/fixtures/htv405_same_identity_repair_counter_20260826.json`.
- [ ] Physically verify gateway/node restart during idle and during a bounded
      run remains observation-only and reconciles from subsequent valve reports.
- [ ] Exercise late response, RF timeout, duplicate request, 15-second hardware
      interval, authenticated counter recovery, and positively observed overdue
      anomaly handling without speculative opens or startup closes.

The 2026-08-27 scheduled 15-minute run used authenticated next counter `5`, but
the disproven additive `42 02` duration payload received no positive response
and the valve remained idle. A same-counter retry failed identically. That
isolates unsupported duration construction—not counter progression—as the
failure cause. Gateway 0.33.13 still closes two recovery gaps exposed during
the postmortem: any authenticated node may contribute the exact valve response
during a pending window, and an already-chosen bounded retry candidate becomes
available automatically after its safety guard. Keep this gate open until a
scheduled run uses a validated duration and obtains valve-owned open and
automatic-idle evidence without manual synchronization.
- [ ] Repeat association and control acceptance on a second HTV405 specimen or
      independently evidenced compatible profile.

### HTV145

- [ ] With fresh batteries, obtain new valve-originated idle and positively
      confirmed stock-command evidence.
- [ ] Physically accept exactly one bounded local open on its evidenced carrier,
      with an immediate response or independent active-state fallback.
- [ ] Confirm valve-owned automatic stop, explicit early stop after the hardware
      interval, durable counter progression, and restart without command replay.
- [ ] Promote controls into HA only after the preceding physical gates pass.

### HA and irrigation behavior

- [ ] Confirm HA state changes only from valve responses or independent state
      telemetry, never from command intent alone.
- [ ] Validate one-active-zone enforcement, per-zone durations, scheduled local
      irrigation, completion/failure notifications, and watchdog behavior.
- [ ] Confirm stale moisture data cannot suppress irrigation indefinitely: use
      only sufficiently recent readings and follow the documented fallback after
      the configured 6--8 hour limit.

The deployed household script now waters from the remaining fresh readings
when only part of a bed's sensor set is stale, and uses the bounded fallback
only when no configured reading is fresh. Keep this gate open until a scheduled
cycle validates both branches. Its valve path also waits through the daemon's
bounded timeout guard and retries a failed open at most twice; each retry still
requires an authenticated valve response, and a final failure remains a
critical notification.
- [ ] Verify timestamps and schedules in at least one non-Eastern timezone in
      addition to the existing UTC/offset/DST software coverage.

Exit criteria: both valve families pair and operate through HA, every accepted
command has device-owned confirmation, and normal failure modes remain bounded,
observable, and recoverable.

The exact generated-identity tail, four incomplete-association negative trials,
and the validated fresh-association counter-`1` result are frozen in
`research/fixtures/htv405_generated_identity_control_gap_20260826.json`.

## Phase 4 — complete field decoding

- [x] Decode HCS026 moisture, categorical full/low battery, report time, RF
      identity, receiver provenance, and reporting cadence.
- [x] Decode HTV145 open/idle state, requested and last-session duration, water
      usage, and categorical normal/low battery.
- [x] Decode HTV405 zone selection, open/idle state, the complete two-byte
      requested/remaining duration fields (including sessions over 254
      seconds), and controller/telemetry counters for the tested association
      profiles.
- [ ] Correlate every exposed valve field against the cloud integration over the
      same timestamped sessions: battery, active zone, requested duration,
      actual duration, remaining time when transmitted, automatic stop, and
      water usage.
- [ ] Produce a controlled HTV405 normal-to-low battery transition and keep its
      battery entity unavailable until RF correlation is repeatable.
      Offset 17 mask `0x08` is the leading bounded candidate: the equivalent
      HTV145 status bit is independently confirmed, and it remained clear in
      all 34 strictly decoded fresh-cell HTV405 stock-route status frames while
      the cloud reported 100%. Historical HA data cannot label the weak-cell
      side because that cloud entity was unavailable until after replacement.
- [x] Mark each field as confirmed, provisional, categorical-only, or not
      transmitted locally; never synthesize an unavailable protocol value.
- [ ] Ensure product/model discovery is capability- and product-code based, not
      tied to one seller name, household endpoint, or friendly name.

Exit criteria: local valve entities agree with independently timestamped cloud
or physical observations, and every unsupported value is explicitly unavailable.

## Phase 5 — stability qualification

- [ ] Complete a persisted minimum 72-hour sensor cadence/ACK soak across the
      installed multi-node layout.
- [ ] Include a sustained stock/custom coexistence interval in that soak.
- [ ] Complete at least three scheduled irrigation cycles using only local
      sensor authority and local valve control.
- [ ] Include one HA restart, custom gateway restart, node reboot, node OTA, and
      device battery cycle without identity loss or command replay.
- [ ] Confirm weak-link placement is adequate or relocate the affected radio
      node before accepting the soak.
- [ ] Observe no phantom devices, duplicate ACK owners, false watering states,
      stale-data decisions, or notification reconnect flapping.
- [ ] Reject a wrong-checksum OTA artifact, interrupt a download, power-cycle a
      candidate boot, prove rollback after unhealthy boots, and retain USB
      recovery.

Exit criteria: the persisted soak report and irrigation evidence meet every
criterion above without an unexplained recovery intervention.

## Phase 6 — open-source hardening

- [ ] Remove installation-specific IDs, names, paths, allowlists, and behavior
      from production code; keep deliberate household examples under `examples/`.
- [ ] Separate protocol/identity models, gateway authority, HA adaptation,
      firmware transport, and research tools behind reviewed interfaces.
- [ ] Replace dictionary-heavy runtime boundaries with typed, versioned models
      and structured errors; add formal HA config-entry/entity migrations.
- [ ] Finish event-driven HA updates with slow reconciliation fallback.
- [ ] Remove superseded probes, hard-coded profiles, temporary acceptance
      endpoints, obsolete feature gates, and retired firmware artifacts.
- [ ] Remove dormant two-radio firmware support, secondary-radio diagnostics,
      and its compile-time feature gate; support one CC1101 per distributed
      radio node as the sole production hardware topology.
- [ ] Keep genuine safety boundaries: scoped authentication, association-bound
      transmission, bounded duration, device-owned confirmation, command
      spacing, at-most-once opens, and rollback.
- [ ] Add encrypted node sessions, integrity/replay protection, credential
      rotation/revocation review, API resource limits, reproducible packaging,
      and asymmetric OTA release signatures.
- [ ] Run CI, security review, redaction checks, and release installation tests
      from a clean environment.

Exit criteria: a new contributor can build and test one production stack without
household knowledge, research-only transmit paths cannot enter release builds,
and publication/security gates are documented and enforced.

## Phase 7 — research infrastructure and documentation

- [ ] Make the receive-only SDR capture/decoder pipeline run as a managed Mac
      service and optionally forward normalized observations to the custom
      gateway; production HA operation must not depend on the SDR.
- [ ] Keep research tooling isolated in this repository while protocol APIs are
      changing; decide before public release whether its dependencies, raw data,
      and compile-gated transmit probes warrant a separate
      `rainpoint-local-research` repository.
- [ ] If split, keep redacted protocol fixtures and shared typed models with the
      production protocol package and move raw captures, capture orchestration,
      and unsafe probes to the research repository.
- [ ] Rewrite documentation around quick start, supported-device/capability
      matrix, architecture, pairing/removal, OTA, wiring, protocol confidence,
      troubleshooting, and contributor research workflow.
- [ ] Archive narrative journals and superseded plans; retain evidence ledgers
      and procedural checklists with explicit links back to this roadmap.
- [ ] Clean merged branches, temporary worktrees, deployment backups, and stale
      firmware catalogs after preserving the minimum rollback artifacts and
      redacted fixtures.

Exit criteria: production documentation is concise and user-oriented, research
work has an explicit boundary, and the Mac can perform future SDR investigations
without coupling the production stack to the Home Assistant host.

## Deferred integration milestone

Cloud-to-local provider migration and a possible merge with the existing
HomGar integration remain deferred until Phases 0--5 pass. Design review may
continue, but no live authority handoff should ship before repeatable local
pairing, control, recovery, coexistence, and stable identity are proven.

## Backlog

These items are intentionally outside the active stabilization sequence unless
one becomes a blocker:

- Discover and qualify additional RainPoint sensor and valve families.
- Determine whether HCS026 P1--P6 soil selection is transmitted, device-local,
  or cloud metadata.
- Determine whether any pairing field controls long-term telemetry channel;
  current evidence says the known selector does not.
- Optimize multi-node channel scheduling and placement beyond the stability
  threshold required by Phase 5.
- Treat **Add device** as a reversible stepped wizard (category, model, radio
  node, physical action, and details) whose language and navigation make Back
  return exactly one step without abandoning the live session. This matters for
  recoverable consumer setup; promote it when Phase 1 protocol reliability is
  no longer the limiting factor and validate it with an end-to-end HA UI trial.
- Finish carrier-PCB manufacturing and enclosure optimization using the
  separate physical preorder checklist.
- Implement cloud-to-local authority migration in coordination with the HomGar
  maintainers after the deferred milestone opens.

When adding a backlog item, record why it matters and the evidence that would
promote it into an active phase. Do not implement it merely because it was
noticed during unrelated work.
