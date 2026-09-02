# RainPoint Local project roadmap

Last reviewed: 2026-09-01

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
| Monolithic `PROTOCOL.md` | Split into current per-device definitions under `protocol_documentation/`; chronology retained in RF capture notes; open work tracked here |
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

- [ ] Keep the HA pairing wizard in a visible `Finalizing pairing` state while
      the selected HTV405 node finishes its optional tail. Do not expose a
      usable Run now action until the node is disarmed and
      `rf_control_available=true`. The 2026-09-01 pairing was authoritative and
      ultimately completed with `optional_tail_timeout`, but an immediate Run
      now attempt failed before RF dispatch with `radio_node_unavailable` while
      the selected node was still armed. This is a lifecycle/feedback defect,
      not a pairing or command-counter failure.

### HTV145 single-zone valve

- [x] Decode stock enrollment/control evidence sufficiently to build a bounded,
      compile-gated candidate.
- [x] Implement the generalized HA pairing lifecycle without exposing the
      unaccepted research transmitter as a production control.
- [x] Preserve the rejected local assignment corpus through probe `.17` and
      establish one explicit red gate: the selected node transmitted two
      decodable assignments, but the valve emitted zero addressed stage-1
      requests. Small timing, carrier, prelude, and copied-identity changes are
      closed as leading hypotheses until new stock evidence exposes another
      discriminator. The frozen result is
      `research/fixtures/htv145_probe17_scheduler_rejection_20260901.json`.
- [x] Confirm the manufacturer's distinct HTV145 lifecycle gestures. Ordinary
      pairing is a long press followed by starting the app search. A documented
      timer reset removes the batteries for at least ten seconds, then requires
      holding the timer button while reinstalling four fresh alkaline cells
      until the red LED flashes rapidly. A plain battery cycle, a long press
      after boot, and that reset sequence must not be classified as equivalent.

#### HTV145 controlled rebuild

Complete these gates in order. Do not make another stage-0 RF change until the
capture matrix has identified one coherent fresh-enrollment branch.

Test the current hypotheses in this order: first, that documented factory
reset, retained re-pair, and battery rejoin are different valve states; second,
that the valve accepts at most the first assignment offered during one pairing
session; third, that another assignment field is session-derived rather than
static; and fourth, that a stock-only pre-assignment RF event or waveform
feature is still missing. Each hypothesis must predict a distinguishing
observation before it changes transmitted firmware.

- [x] Implement authenticated radio-node maintenance controls in firmware, the
      local gateway, and HA before the next stock-gateway recording:
  - enter a bounded **receive-only** mode that keeps RF reception, normalized
    logging, Wi-Fi, diagnostics, identify, and maintenance traffic available
    while rejecting every pairing, routine-ACK, and valve-control transmission;
  - restore normal RF mode explicitly, with automatic timeout recovery so a
    forgotten experiment cannot leave irrigation radio support disabled;
  - remotely reboot a node without requiring OTA or physical power removal;
  - expose requested/effective RF mode, remaining timeout, last mode change,
    reboot result, and rejected-TX count in HA diagnostics;
  - require the custom local gateway to verify that every adopted node is
    effectively receive-only before declaring a stock capture ready.
- [x] Deploy the maintenance-capable image to every adopted radio node and
      physically verify receive-only entry, capture-readiness blocking,
      automatic normal-mode recovery, explicit restore, and remote reboot.
      Do not begin the controlled stock-gateway capture matrix until this gate
      is complete.
      - 2026-09-01: all three adopted nodes entered bounded receive-only mode
        together, aggregate capture readiness returned `ready: true` with no
        blockers, and all three explicitly returned to normal operation with
        their sensor/valve ACK assignments intact. Automatic timeout recovery
        and remote reboot/reconnect were also physically verified on the OTA
        test node.
- [ ] Replace the HTV145 test valve's batteries with four fresh alkaline cells,
      leave the stock RainPoint gateway under manual control, and record this
      controlled lifecycle matrix as separate continuous-IQ trials:
  1. [x] documented factory reset with the stock gateway off and every custom
     node confirmed receive-only;
     - 2026-09-01: a checksummed 180-second capture recovered a six-frame,
       two-carrier factory sweep: counters `0`, `1`, lower/upper variants of
       `2`, `3`, and `4`. No assignment, paired-route request, or configuration
       response followed. The reset therefore cleared the retained association
       even though its LED sequence was not visibly distinct from ordinary
       pairing.
  2. [x] documented factory reset followed by a complete stock enrollment using
     the manual's exact button-then-app order;
     - 2026-09-01: the stock gateway accepted factory counter `2`, completed all
       six stages, and enrolled successfully. The capture proved that counter
       `1` is a real upper-carrier factory announcement and that the accepted
       counter-2 assignment selects response subchannel `12` at 434.3515 MHz.
  3. [x] repeat the documented reset with stock app search armed before the
     valve long press. Compare which factory counter is accepted against the
     button-first counter-2 transcript without assuming counter `1` wins;
     - 2026-09-01: the already-searching stock gateway accepted the first new
       factory announcement, counter `0`, after 52.15 ms. It selected the same
       selector `6` / response subchannel `12` and completed the same six-stage
       exchange family. The controlled ordering comparison therefore supports
       first-observed sweep acceptance, not a fixed target counter;
     - 2026-09-01 local timing-only trial: after the same documented reset,
       the OTA test node was positively confirmed armed before the valve long
       press. The probe transmitted at least one assignment and remained at
       step `1/6`; it observed the factory sweep through counter `3`, but no
       addressed stage-1 valve request or terminal confirmation followed. The
       current shared session can answer counter `0` with the older selector-5
       branch and then answer counter `3` again with selector `6`, so this is a
       rejected multi-assignment baseline rather than evidence against the new
       stock counter-0/selector-6 transcript. Do not repeat this image.
  4. [ ] a second documented factory reset and identical button-first complete
     stock enrollment;
  5. [ ] ordinary long-press re-pairing without a factory reset;
  6. [ ] ordinary battery removal/reinstallation while the accepted stock
     association remains registered.
- [ ] For both new complete stock enrollments, retain the full factory sweep,
      the first gateway transmission, every addressed continuation, the first
      routine report, app Device Address, button/app ordering, and LED result.
      Classify stable, clock-derived, identity-derived, branch-derived,
      session-generated, and still-unknown fields. Treat the 2026-08-28
      counter-3/selector-6 recording as retained-association evidence, not as a
      universal fresh-enrollment branch.
- [x] Extend the IQ analyzer with a stage-0 verdict that fails when an
      assignment is transmitted without an addressed stage-1 request. The fast
      fixture replay and raw-IQ replay must report the same red/green result,
      and each physical attempt must retain the exact assignment plus the
      following factory fallbacks or paired request.
  - 2026-09-02: bounded raw-IQ replay now agrees with both independent
    outcomes. It reports the accepted stock counter-0 assignment as
    `accepted` after recovering one addressed stage-1 request, and probe `.25`
    as `rejected_assignment_without_stage_1` after recovering the local
    assignment, zero addressed stage-1 requests, and the continuing factory
    sweep. The red/green evidence is retained in
    `research/fixtures/htv145_stage0_raw_replay_differential_20260902.json`.
- [ ] Replace the shared HTV405 session reuse with a dedicated research-only
      HTV145 state machine and one canonical transcript definition consumed by
      the analyzer, gateway tests, and generated firmware table. The initial
      harness must select one evidence-backed lifecycle/selector branch before
      arming, transmit at most one assignment, never fall through to a second
      branch in the same session, and remain receive-only afterward.
  - 2026-09-01: probe `.19` now isolates HTV145 behind a dedicated one-shot
    session and the controlled counter-0/selector-6/subchannel-12 transcript.
    It exposes separate assignment-lock and stage-0 accept/reject diagnostics,
    and the IQ analyzer now fails an assignment that is not followed by the
    addressed stage-1 request. Unit, firmware-protocol, and PlatformIO builds
    pass; this gate remains open until the physical stage-0 boundary and raw-IQ
    verdict are reproduced twice without changing the frozen prefix.
  - 2026-09-01 first physical `.19` result: the armed node locked one counter-0
    assignment, reached `1/6`, then failed `stage_0_rejected` when counter `2`
    arrived without an addressed stage-1 request. A later ordinary long press
    happened after that terminal failure and therefore had no armed local
    transmitter; it is not a second protocol result. Preserve the frozen `.19`
    prefix and use `tools/run_htv145_stage0_hitl.sh` with bounded continuous IQ
    before changing any RF field. The redacted diagnostic fixture is
    `research/fixtures/htv145_probe19_stage0_rejection_20260901.json`.
  - 2026-09-01 continuous-IQ `.19` result: the red-capable harness reproduced
    `stage_0_rejected` and captured the assignment on air. Stock and local
    valve factory carriers differed by only `31 Hz`, but the local assignment
    was `+9.979 kHz` above the directly measured stock assignment
    (`433.556628` versus `433.546649 MHz`). Both used `35.004 kHz` deviation;
    the local reply was also approximately `0.85 ms` late. Probe `.20` changes
    only the HTV145 selector-6 initial carrier by `-9.979 kHz`; payload, wake,
    deviation, and timing remain frozen until the carrier hypothesis receives
    a physical verdict. This also corrects an analyzer mistake where its
    configured decision center had been recorded as a measured carrier.
  - 2026-09-01 physical `.20` result: the node again reached `1/6` and failed
    `stage_0_rejected`, but direct IQ measurement showed that the intended
    carrier-only experiment never reached RF. The assignment remained at
    `433.556232 MHz`, about `9.583 kHz` above stock and only normal capture
    drift from `.19`; timing was `52.5 ms` and deviation remained `35.004 kHz`.
    The live HTV145 path still shared HTV405 profile/calibration plumbing, so
    this red result does not reject the corrected-carrier hypothesis. Fixture:
    `research/fixtures/htv145_probe20_carrier_not_applied_rejection_20260901.json`.
  - 2026-09-01 probe `.21` separates the live HTV145 pairing module from
    HTV405: independent profile and step types, matcher, state machine, reply
    builders, timing, and model-specific `45 kHz` calibration. The four-zone
    path is unchanged. Node diagnostics now expose the profile initial center,
    supplied offset, and effective initial TX center so a profile/calibration
    mismatch is visible before the next RF trial. Native protocol, gateway,
    and PlatformIO builds pass.
  - 2026-09-01 physical `.21` result: an ordinary long press produced the clean
    counter-0 factory announcement, the isolated node emitted exactly one
    selector-6 assignment, and the valve rejected it before stage 1. A fresh
    documented reset is therefore not required to exercise this boundary.
    Direct IQ measurement placed the local assignment at `433.504260 MHz`,
    `42.389 kHz` below the accepted stock assignment, while deviation remained
    `35.004 kHz`; the reply began `52.85 ms` after the request ended versus
    stock's `52.15 ms`. Probe `.22` changes only the node-specific HTV145
    frequency correction from `45.000` to `87.389 kHz`; timing and every frame
    field remain frozen for one discriminating carrier-only trial. Fixture:
    `research/fixtures/htv145_probe21_isolated_carrier_rejection_20260901.json`.
  - 2026-09-01 physical `.22` result: the carrier correction landed at
    `433.546741 MHz`, within `92 Hz` of the accepted stock reference, with the
    same `35.004 kHz` deviation, decoded selector-6 packet, and 320-symbol wake.
    The valve nevertheless rejected stage zero. These center/deviation values
    came from unconstrained FFT peaks and are superseded by the balanced-wake
    analysis below; preserve this attempt as a rejection record, not as proof
    that the PHY matched. The reply started `52.45 ms` after the request versus
    stock's `52.15 ms`. An accepted local HTV405 enrollment was about `1.25 ms`
    earlier than its stock reference, so this smaller delta still does not
    justify a timing-only probe. Fixtures:
    `research/fixtures/htv145_probe22_calibrated_carrier_rejection_20260901.json`.
    `research/fixtures/htv405_stock_local_waveform_control_20260901.json`.
  - 2026-09-01 physical-layer follow-up: `.22` was about `10.26 dB` stronger
    than stock at the SDR and clipped `45.9%` of captured I/Q bytes while stock
    clipped none. No additional exact-sync stock frame appeared on six known
    carriers in the `5.8 s` before assignment. Before changing semantics,
    repeat unchanged `.22` at reduced TX power with a non-clipping SDR capture;
    treat valve-receiver overload as a hypothesis, not a conclusion.
  - 2026-09-01 reduced-power verdict: unchanged `.22` at `0 dBm` reduced active
    captured magnitude by `12.69 dB` and eliminated ADC-rail clipping, but the
    valve again rejected the counter-0 selector-6 assignment before stage 1.
    Transmit overload is closed, but the clean capture exposed an analyzer
    error: payload-weighted FFT peaks did not represent the two FSK tones.
    Decoder-independent balanced-wake analysis recovered all `319` wake
    transitions. Accepted stock used deviation register `0x45`; local `.22`
    used `0x43`. Normalizing each assignment against the valve request from the
    same session placed local `.22` `35.370 kHz` below stock. Full-band energy
    inventory found no stock-only burst in the `6.82 s` before assignment.
    Probe `.23` changes only those two independently disproven PHY values:
    frequency correction `87.389` to `122.759 kHz`, and initial deviation
    `0x43` to `0x45`. Payload, endpoints, selector, clock builder, wake, timing,
    power, polarity, and one-shot state remain frozen. If the on-air `.23`
    waveform matches and stage zero still fails, replay one freshly accepted
    stock assignment exactly before considering more semantic changes.
    Fixtures:
    `research/fixtures/htv145_probe22_reduced_power_rejection_20260901.json`.
    `research/fixtures/htv145_balanced_wake_phy_discriminator_20260901.json`.
  - 2026-09-01 unattended `.23` preparation: the isolated firmware and gateway
    metadata now encode the balanced-wake correction, the candidate version is
    `.23`, and regression tests assert both the `122.759 kHz` node calibration
    and `0x45` initial deviation. The physical gate remains open until the
    bounded stage-zero harness records the transmitted waveform and either an
    addressed stage-1 request or the next factory fallback.
  - 2026-09-01 preflight found `.23` could not arm because the shared validated
    pairing guard rejected its evidence-backed `122.759 kHz` calibration before
    any RF transmission. Probe `.24` changes no RF field or state-machine
    behavior; it gives only the gated HTV145 research profile a `150 kHz`
    calibration bound while retaining the generic `100 kHz` sensor/HTV405
    boundary. The physical waveform verdict therefore remains a test of the
    unchanged `.23` RF hypothesis.
  - 2026-09-01 physical `.24` result: the bounded node again stopped at `1/6`,
    but the clean IQ capture closed the intended PHY discriminator. Relative
    to the same valve request, the assignment was only `+354 Hz` from accepted
    stock, used the same `0x45` deviation family and 320-symbol wake, had no
    clipping, and started `0.648 ms` later. The decoded frame matched stock in
    every static byte, but its live clock encoded `17:56` as `01:56`: the
    HTV145 builder incorrectly cleared the legitimate high-hour bit as though
    it were a branch marker. Probe `.25` changes only that disproven clock
    rule. RF profile, static payload, selector, endpoints, wake, scheduler,
    power, polarity, and one-shot state remain frozen.
  - 2026-09-01 physical `.25` result: the emitted clock correctly represented
    `19:13:08`, but the valve still continued its sweep and the node stopped at
    `1/6` with `stage_0_rejected`. The clock-wrap hypothesis is closed. Freeze
    `.25`; at that point the next planned discriminator was exact replay of a
    freshly accepted stock assignment. The later edge evidence below narrows
    the first physical change further without reopening any `.25` field.
  - 2026-09-02 edge follow-up: two accepted stock assignments each remain
    above the energy threshold for about `31.36 ms`, versus `31.22--31.23 ms`
    for rejected probes `.24` and `.25`. Sync-aligned backward-wake histograms
    differ too, but an accepted stock continuation proves that count cannot be
    translated directly into one fixed wake-symbol constant. Preserve this as
    a packet-boundary/start-phase/PA-tail hypothesis, not as probe `.26` yet.
    Median sync alignment now localizes most of the duration difference after
    the normalized frame: both accepted stock assignments and an accepted
    stage-1 reply retain about `160 us` of post-frame RF energy, while both
    rejected local assignments retain only `45--47 us`. Frequency-resolved
    bins identify the accepted tail as the low FSK tone even for two frames
    whose final payload bit is high. The local driver already drives GDO0 low
    before immediate `SIDLE`; a research-only, stage-0-only build gate now adds
    the measured `115 us` difference and leaves every normal image unchanged.
    It compiles and passes the firmware boundary check, but is not staged or
    deployed. The next fresh stock capture must reproduce the approximately
    `160 us` low tail before that single-variable candidate is authorized. If
    a matching on-air tail remains rejected, exact accepted-byte replay is
    next; do not reopen payload or wake-length guesses. Evidence:
    `research/fixtures/htv145_stock_local_assignment_edge_discriminator_20260902.json`.
- [x] Keep firmware-catalog staging within the runtime's 32-release bound.
      Staging probe `.22` temporarily produced a 33-entry catalog that the
      gateway rejected. The staging tool now refuses overflow before writing
      an artifact and accepts only explicit, existing, same-variant release
      IDs for supersession; regression tests cover both outcomes.
- [ ] Prove and freeze the initial assignment boundary. It passes only when
      two consecutive unchanged trials produce the expected addressed stage-1
      valve request. Freeze its request matcher, assignment payload, endpoints,
      selector, carrier, prelude, deviation, wake, scheduler, clock derivation,
      and trailer in a regression fixture and a separate commit.
- [ ] Build the remaining exchange incrementally without modifying a frozen
      prefix:
  1. stage-1 ordinary reply plus its coupled delayed long-wake configuration,
     proven by the valve's configuration response and next addressed request;
  2. stage-3 reply, proven by the stage-4 request;
  3. stage-4 reply, proven by the stage-5 request;
  4. stage-5 reply, proven by ordinary paired telemetry on the new association.
  Each boundary requires two consecutive unchanged progressions before it is
  frozen. LED state and transmit completion are supporting observations only.
- [ ] Complete three consecutive local pairings with fresh batteries and
      valve-originated terminal evidence on the unchanged final candidate.
- [ ] Confirm removal and re-pairing preserve the intended stable physical
      identity without stale entities, then implement retained re-pair and
      battery-rejoin behavior as separate lifecycle paths without reopening the
      frozen fresh-enrollment transcript.

Exit criteria: a user can pair and remove every supported family entirely from
HA, each family completes three consecutive final-build trials, and each
physical device has exactly one HA representation.

The 2026-08-26 HTV145 stage-0 discriminator trials all stopped at 1/6: an
on-air reply close to the stock 50.55 ms slot, a six-to-ten-foot separation
trial, and a generated custom controller/companion identity. Continuous IQ
shows matching decoded payload structure, wake length, and clock construction,
but the later balanced-wake discriminator proved the carrier normalization and
deviation did not match. These negatives make blind timing, near-field
saturation, and retained-controller collision poor next hypotheses while
leaving probe `.23` as the current evidence-backed PHY test. The later
2026-08-28 stock exchange supplies a second
coherent branch: counter `3`, selector `6`, assignment to the retained valve
route, and a 434.461993 MHz routine carrier. Corrected bounded-IQ
analysis recovered all four
lower-channel paired requests and the controller-configuration response from
each stock success, but zero paired requests after the rejected local
assignments; the stall is valve-side rejection, not a node receive-channel
miss. Probe `.8` observed the August 28 physical sweep through counters `0`,
`2`, and `3`, automatically answered counter `3`, and reported one completed
transmit step; the valve emitted no paired continuation. That result proves
the failed trial was not an operator timing miss and rejects the hypothesis
that the captured counter-3 frame alone is sufficient in every retained
state. The event journal retains counter `0` from the SDR, counter `2` from the
selected node, and counter `3` from a second node. Probe `.9` then answered the
first evidenced selector-5 branch while a full IQ recording independently
captured the result. The valve rejected it, fell through counters `2` and `3`,
and the node also emitted the exact selector-6 reply; neither branch produced
paired traffic. The progressively shorter visible phases therefore represent
a bounded fallback sequence. A symbol-resolved re-analysis of probe `.12`
corrected the former claim that factory counter `1` was missing: the valve sent
counter `1` on an alternate 433.363 MHz solicitation carrier, which the
single-center analyzer did not inspect. The counter-0 local waveform
matches the accepted stock assignment within 122 Hz, with identical deviation,
packet-sync timing, static payload, and valid current packed clock. Raw-envelope
comparison then exposed what frame decoding hid: stock places a 256-symbol
continuous high mark before the normal 320-symbol alternating wake, producing
43.8 ms total RF versus 31.3 ms locally. Both sync words arrive about 66.6 ms
after the request ends. Evidence is frozen in
`research/fixtures/htv145_first_branch_local_rejection_20260828.json`. Probe
`.10` adds only this lead-in and advances RF start 12.8 ms to preserve the
proven sync instant. The 2026-08-28 physical `.10` trial remained at step 1/6:
the selected node heard the factory sweep, transmitted its reply, then observed
the valve fall through to counter `3` without any paired continuation. The
recovered leading mark is therefore not sufficient by itself. Before changing
payload, carrier, timing, or branch selection again, record the `.10` reply with
continuous IQ and compare its actual on-air mark polarity, length, wake, sync,
and envelope directly with the accepted stock counter-0 exchange. That capture
showed the earlier decoder description was incomplete: stock uses a
256-symbol alternating prefix at a shifted center and larger deviation, not a
constant mark. Probe `.11` successfully changed RF settings within one
continuous symbol stream while preserving the ordinary wake and assignment,
but its coarse `+13`/`0x47` settings over-shifted and over-deviated the prefix;
the valve again stopped at 1/6. Empirical comparison with the accepted stock
prefix and the known-good ordinary `0x45` HTV405 waveform mapped probe `.12`
to FSCTRL0 offset `12` and DEVIATN `0x46`, but that probe still failed. The
estimator used for that inference excludes frequencies near the SDR's DC
artifact, and one of the stock prelude tones falls inside the excluded band.
Direct symbol measurement instead shows stock reversing prelude polarity at
the ordinary-wake boundary and using about 30.2 kHz deviation, while probe
`.12` retained the wake polarity and used about 44.4 kHz. Their ordinary wakes
both measure about 34.8--34.9 kHz. This is a material waveform mismatch, not a
minor timing or counter failure, and is frozen in
`research/fixtures/htv145_probe12_prelude_rejection_20260828.json`.

Before another valve trial, keep the proven assignment frame, selector branch,
ordinary carrier, ordinary wake, sync instant, and response scheduling frozen.
Add one non-pairing bench probe that emits a small prelude-only calibration
matrix: reversed prelude polarity, FSCTRL0 offsets `12` and `13`, and DEVIATN
values `0x41` and `0x42`. Capture all four variants through the SDR and select
the least-error stock match by center shift, tone separation, polarity,
boundary continuity, and symbol count. Only that measured winner may enter the
next automatic pairing image. A live success requires addressed valve-originated
paired traffic before the next factory fallback frame, followed by the captured
six-stage HTV145 transcript; neither TX completion nor the white LED is enough.
Keep fresh identity allocation gated until one more stock enrollment exists.

The 2026-08-30 low-gain calibration completed that matrix without transmitting
an addressed assignment. FSCTRL0 `13`, DEVIATN `0x42`, and prelude-only polarity
reversal were the closest tested stock match: +20.65 kHz center shift and
31.77 kHz deviation versus stock's +20.28 kHz and 30.21 kHz, with an unchanged
34.99 kHz ordinary wake. Probe `.15` then changed only those measured prelude
settings. A continuous SDR capture proved that the node answered factory
counter `0` with selector `5`, then answered the later counter `3` fallback with
selector `6`; the valve emitted no paired-stage traffic after either reply.
The actual counter-0 prefix measured +20.64 kHz, 31.74 kHz deviation, reversed
polarity, and 12.67 ms on-air versus stock's approximately 12.45 ms. This is a
real valve-side rejection, not a missed node transmission or operator window.
The next trial replayed unchanged probe `.15` with the valve's retained stock
controller/companion identity. The LED remained in a different blinking
pattern, but continuous IQ again showed the complete factory fallback sweep,
counter-0 selector-5 and counter-3 selector-6 local assignments, and zero
paired-stage traffic. Retained identity is therefore not sufficient. An
initial whole-frame carrier estimator suggested a common 5.46 kHz-high error,
but the controlled probe `.16` disproved it. The August 30 `.16` attempt was
well inside the five-minute arm and SDR windows: the valve's counter-0 request
started at 53.116 seconds, the node began its reply at 53.184 seconds, and the
valve continued its fallback sweep with no paired-address traffic. Direct
comparison of only the alternating wakes removes payload-symbol bias: probe
`.15` was within about 7 Hz of the accepted stock request-to-assignment delta,
whereas `.16` moved 5.57 kHz low. Probe `.17` therefore restores the zero
HTV145-only correction while preserving `.15` modulation, prelude, timing,
payload, branch selection, and identity handling. Carrier selection is frozen
again. The next physical probe varies one remaining evidenced discriminator
relative to `.15`: a counter-0-only +500 us scheduler adjustment, centered on
the 49.85 and 50.20 ms local observations versus the accepted stock 50.55 ms
slot. It does not move the independently timed counter-3 fallback branch.
Evidence is frozen in
`research/fixtures/htv145_probe15_calibrated_prelude_rejection_20260830.json`
and
`research/fixtures/htv145_probe15_retained_identity_rejection_20260830.json`,
with the estimator correction in
`research/fixtures/htv145_probe16_carrier_correction_rejection_20260830.json`.

Probe `.17` then preserved the probe-`.15` carrier, calibrated prelude,
payload, selector branches, and retained identity while moving only the
counter-0 assignment scheduler by `+500 us`. A dedicated continuous IQ capture
measured the actual selector-5 assignment at `50.800 ms` after the counter-0
request ended, only about `0.25 ms` later than the accepted stock `50.55 ms`
observation. The unchanged fallback branch answered counter `3` at `54.800 ms`.
Both assignments echoed the correct counter and used the correct destination
and selector, but the valve emitted zero addressed stage-1 requests. This
rejects the small scheduler mismatch as the missing enrollment discriminator.
Do not create probe `.18` from another small timing, carrier, or identity guess;
resume only after a new stock/local discriminator is evidenced. The complete
result is frozen in
`research/fixtures/htv145_probe17_scheduler_rejection_20260901.json`.

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
      return to idle. On 2026-09-01, unified firmware
      `0.15.0-supervised-beta.11` accepted freshly initialized counter `1`,
      reported a 1,200-second Zone 1 run, and returned itself to idle after the
      requested duration.
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
      run remains observation-only and reconciles from subsequent valve
      reports. The idle half passed on 2026-09-01: restarting gateway `0.33.21`
      emitted no valve command and restored authenticated next counter `4`;
      power-cycling the assigned beta.11 Vegetable Garden Radio restored its
      identity, three sensor ACK assignments, HTV405 liveness/control profile,
      and disarmed state. A subsequent 60-second open authenticated counter
      `4` -> `5` and ended with valve-owned idle telemetry. Keep this gate open
      only for restart during an active bounded run.
- [ ] Exercise late response, RF timeout, duplicate request, 15-second hardware
      interval, authenticated counter recovery, and positively observed overdue
      anomaly handling without speculative opens or startup closes.
- [x] Physically validate deterministic, non-actuating HTV405 command-counter
      synchronization while the valve is independently confirmed idle.
      Gateway 0.33.31 first fixed the action-alias defect that discarded a valid
      closed response. Successor and skip-one tests then showed that close can
      select a new counter. The exhaustive 2026-09-02 test visited all 32
      five-bit values in bit-reversed order from authenticated next `10`; every
      value returned a matching idle response and became the retained next
      counter. Open `31` proved rollover to `0`. A production-shaped close `0`,
      15-second interval, open `0` sequence authenticated next `1` and ended on
      valve-owned automatic idle. Gateway 0.33.36 therefore replaces the old
      scan with a fixed close-`0` anchor, repeats only that anchor once after
      silence, stops on a second silence or strict rejection, and normalizes
      persisted legacy scan state before transmitting.
- [x] Implement fixed-anchor synchronization and a requested HTV405 open as one
      explicit, observable transaction. Gateway 0.33.37 queues no open until
      close `0` receives an authenticated idle response and the 15-second
      command interval has elapsed. It cancels or fails queued work on gateway
      restart, node or transport loss, rejection, timeout, unexpected watering,
      or operator cancellation, and never replays an open after restart. HA
      0.13.6 exposes a phase/result sensor, removes valve actuation features
      while active to prevent duplicate clicks, and permits cancellation only
      before open dispatch. Regression coverage includes authenticated air and
      node-reported responses, late replies, duplicate requests, node loss,
      restart, timeout, unexpected watering, operator cancellation, and the
      exact 15-second boundary.
- [x] Physically validate the one-click synchronized HTV405 start transaction.
      On 2026-09-02, deployed gateway 0.33.37 moved a 60-second Zone 1 request
      through synchronization, authenticated anchor confirmation, the exact
      15-second interval, open-response confirmation, independent watering
      telemetry, valve-owned automatic idle, and restored start availability.
      The live state surface exposed every phase and disabled starts throughout
      active work. Gateway 0.33.38 additionally labels the final idle result
      **Watering completed** instead of retaining the earlier start-confirmed
      wording.
- [ ] Determine what causes an authenticated HTV405 counter to become stale.
      Timestamped routine-ACK outcomes and radio-node connection/reboot
      checkpoints are now durable. Hold the gateway and owner node stable and
      test the exact next counter after controlled 1-, 4-, 8-, and 12-hour idle
      intervals, then compare a stock-gateway open after a similar interval to
      distinguish wall-clock reset, owner-node continuity loss, ACK gaps, and a
      stock-only maintenance exchange. This causal research no longer blocks
      deterministic fixed-anchor recovery.

The frozen overnight timeline, competing hypotheses, and controlled
discriminator are retained in
`research/fixtures/htv405_overnight_counter_drift_20260902.json`. The interval
alone is not yet causal: after the last authenticated `4` -> `5` command, the
owner node recorded at least one reboot, 33 connection events, 421 routine ACK
transmissions, and three aggregate ACK failures before inspection. Those
events make loss of ACK-owner continuity at least as plausible as a pure
wall-clock expiry until the new timestamped diagnostics complete a stable
soak. The retained counter-`3` closed response validates the non-actuating
probe mechanism independently of that still-unknown reset cause.

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

The 2026-08-29 scheduled 20-minute run failed for a distinct transport reason.
The gateway correctly reserved authenticated counter `7`, but the valve heard
neither the original one-shot frame nor the same-counter bounded recovery. A
controlled discriminator then sent the known-good 60-second command twice with
the same counter and payload: the first transmission timed out, while the
second was accepted immediately and the valve later returned itself to idle.
This isolates intermittent one-shot RF delivery from counter progression and
duration encoding. Firmware beta.11 therefore sends one logical HTV405 command
as a bounded burst of up to three identical frames at 0, 650, and 1,450 ms,
cancelling remaining attempts on the first authenticated response. Gateway
0.33.17 also recognizes the strict `d0/86/83/00` negative reply; because that
reply proves watering did not begin, it can retry the same counter after the
15-second hardware interval instead of waiting through the requested run.
Pairing, association, duration, and counter-advancement rules are unchanged.
The 2026-09-01 installed run closes the beta.11 scheduled-run gate: the valve
authenticated the 20-minute open and later supplied independent automatic-idle
telemetry. Two subsequent early-stop trials then authenticated open `2` -> next
`3`, close `3` -> next `3`, open `3` -> next `4`, and close `4` -> next `4`.
This physically repeats the conditional rule that an accepted open advances
the session counter while an accepted close leaves that counter available for
the next open. Exact responses are retained in
`research/fixtures/htv405_generated_identity_counter_continuity_20260901.json`.

The superseded adjacent-candidate probes, beta.10/beta.11 radio A/B test, and
raw-IQ proof that candidate `9` was transmitted correctly remain preserved in
`research/fixtures/htv405_beta10_candidate9_on_air_20260831.json` and the RF
capture notes. Their silence-based hypotheses must not be used by production
control now that the exhaustive fixed-anchor result above defines the protocol.

- [ ] Repeat association and control acceptance on a second HTV405 specimen or
      independently evidenced compatible profile.

### HTV145

- [x] Capture and decode stock 300- and 900-second opens on the retained
      selector-6 association. Both received immediate valve responses; the
      duration fields are `96 00` and `c2 01`. The capture also proves the
      command-family high marker reverses by association while request action
      byte `82/81` and response state marker `cf/4f` remain stable.
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
cycle validates both branches. As of 2026-08-31, its valve path accepts only a
new matching authenticated valve response, never command intent or an unrelated
physical-open report. It observes short bounded recovery windows rather than
the requested watering duration, returns immediately after a confirmed bounded
start, and lets valve-owned idle telemetry finish the run. An exhausted retry
now fails immediately with the gateway's exact reason. Every iPhone push is
also mirrored into HA's persistent notification area so the message remains
reviewable after the mobile banner is opened or dismissed.
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
- [ ] Correlate every model-supported valve field against the cloud integration
      over the same timestamped sessions: battery, active zone, requested
      duration, actual duration, remaining time when transmitted, automatic
      stop, and HTV145 water usage. HTV405 declares no water-usage capability.
- [ ] Produce a controlled HTV405 normal-to-low battery transition and keep its
      battery entity unavailable until RF correlation is repeatable.
      Offset 17 mask `0x08` is the leading bounded candidate: the equivalent
      HTV145 status bit is independently confirmed, and it remained clear in
      all 34 strictly decoded fresh-cell HTV405 stock-route status frames while
      the cloud reported 100%. Historical HA data cannot label the weak-cell
      side because that cloud entity was unavailable until after replacement.
- [x] Remove HTV405 water-usage entities from the Home Assistant product/entity
      definition and from every installed or example dashboard. Entity creation
      must follow model capabilities: retain water usage for HTV145, whose RF
      field is confirmed, and omit it entirely for HTV405, whose product model
      declares no flow or water-volume capability.
      - 2026-09-02: gateway `0.33.29` removes the generic product capability and
        placeholder state, integration `0.13.4` rejects new HTV405 usage
        entities and removes stale registry entries, and both the checked-in
        example and installed local dashboard contain no such entity.
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

- [x] Split the monolithic protocol journal into concise shared and per-device
      current definitions under `protocol_documentation/`; retain dated
      discovery history in `research/RF_CAPTURE_NOTES.md` and exact frames in
      redacted fixtures.
- [ ] Make the receive-only SDR capture/decoder pipeline run as a managed Mac
      service and optionally forward normalized observations to the custom
      gateway; production HA operation must not depend on the SDR.
  - 2026-09-02: `tools/capture_rainpoint_continuous_iq.sh` now provides a
    bounded Mac-local continuous-IQ path with deterministic sample count,
    capture metadata, and SHA-256 verification without stopping either HA or
    the custom local gateway. Managed launch/restart and optional normalized
    forwarding remain open.
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
  - 2026-09-01: moved three duplicate-slug RainPoint source backups out of the
    Supervisor-scanned `/addons` directory and removed macOS AppleDouble files
    that prevented translation parsing. The contributor guide now fixes both
    deployment rules; broader catalog/backup retention cleanup remains open.

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
- Repeat fresh generated-identity HTV405 enrollment and command-counter
  initialization on a second specimen or independently compatible product
  before generalizing the profile beyond the tested hardware revision.
- Characterize the compact product/status-frame integrity family before using
  it to construct traffic for a newly supported device family; ordinary-frame
  CRC residues do not prove that separate format.
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
