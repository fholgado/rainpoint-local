# Valve recovery: what transfers between models

October 3, 2026. Offline comparison of source, retained capture fixtures and
stock-hub disassembly references. No RF, deployment or live-state changes.
Project status remains solely in [PROJECT_ROADMAP.md](../PROJECT_ROADMAP.md).

## Conclusion

**Reuse the recovery architecture and native phase model, not the HTV213
startup bytes or its physical qualification.** A valve's announcement/report
sequence is independent of the gateway's command sequence. Recovery should
return its saved association/configuration and preserve the gateway's command
journal; the subsequent command must establish acceptance separately.

The HTV213 result demonstrates that one battery change did **not require**
resetting the gateway counter. It does not reveal whether the valve persisted
an exact expected counter, cleared an acceptance window, or accepts multiple
phases. Its earlier accepted jump to phase 62 makes those alternatives important.
Sources: [local recovery](fixtures/htv213_local_battery_rejoin_20261003.json),
[retained-phase control](fixtures/htv213_local_post_battery_control_20261003.json),
and [boundary experiment](fixtures/htv213_local_counter_boundary_20260930.json).

## Evidence and limits by model

| Model | Direct evidence | Not established |
| --- | --- | --- |
| HTV213, two ports | One stock and one local battery-only rejoin return the saved association, then service both ports' state/settings/empty plans. Local phase-2 OPEN receives a matching positive `a1`, active/automatic-idle reports and a 60-second summary; next gateway phase becomes 3. | Every reset branch, repeated battery cycles, receiver counter-retention algorithm or general production support. |
| HTV145, one port | Stock successive opens use both phase parities; local adjacent OPENs 8/9 and earlier OPEN 63 → CLOSE 0 are accepted. Existing pairing/telemetry/control association is operational. | A locally qualified battery-only `01/81` recovery, post-battery retained-phase control, or phase-zero OPEN. |
| HTV405, four ports | Stock and local controls use both phase parities. October 2 native OPENs 2/3 on dry Zone 2 complete with positive owner ACKs, persisted radio receipts, active/idle reports and verified legacy handback. | Successful battery-only retained assignment, post-battery retained-phase control, or native phase-zero OPEN. |

Primary sources: HTV213 fixtures above and
[stock lifecycle](fixtures/htv213_stock_lifecycle_20260928.json);
HTV145 [stock controls](fixtures/htv145_selector2_stock_pairing_control_20260905.json),
[active-close boundary](fixtures/htv145_active_counter_recovery_20260906.json)
and [installed trial evidence](../docs/VALVE_PHASE_TRIAL.md#october-1-adjacent-phase-confirmation);
HTV405 [stock early stops](fixtures/htv405_stock_early_stop_20260824.json)
and [resumed native qualification](../docs/VALVE_PHASE_TRIAL.md#october-2-resumed-native-qualification--passed).

The historical file named
[`htv405_battery_rejoin_full_exchange_20260824.json`](fixtures/htv405_battery_rejoin_full_exchange_20260824.json)
does **not** document a successful full exchange: its result records assignment
TX, only step 1/18, and no paired traffic or terminal confirmation. It is a
failed battery-boot/fresh-transcript attempt, not evidence of retained recovery.

## Shared implementation versus model-specific work

- **Shared, capture-backed:** native `02/82`, `05/85`, page-zero `06/86`;
  replies echo all six request-phase bits; report flags select revision/time/unit
  fields. The pure
  [`valveConfiguration::prepareReply`](../firmware/rainpoint_bridge/include/rainpoint_valve_configuration.h)
  supports one/two/four ports. Actual C++ replay tests cover 24 enrollment and
  20 HTV213 lifecycle pairs, without RF. These are reusable body semantics,
  not proof of another model's startup transport.
  Source: [`tests/test_valve_configuration.py`](../tests/test_valve_configuration.py).
- **Shared hub behavior:** the known-device branch returns saved address,
  selector, timing and configuration revision, with current local clock;
  direct responses do not allocate a master phase. The traced master allocator
  uses six bits and includes `63 → 0 → 1`; full-phase result matching is common.
  This is stock **hub** code, not valve-receiver decompilation.
  Sources: [association persistence](STOCK_HUB_ASSOCIATION_PERSISTENCE.md#native-assignment-construction-contract)
  and [cross-model phase audit](VALVE_FULL_PHASE_CROSS_MODEL_AUDIT.md).
- **Model-specific:** announcement class/model/descriptor/software bytes,
  allowed startup variants, destination/header branches, request-selector to
  assignment-carrier mapping, saved routine carrier, waveform/CRC tail and
  receive turnaround. HTV213's `03`/`07` allowlist cannot be copied to HTV145 or
  HTV405. Battery-only HTV213 startup itself produced `07`, so that byte cannot
  universally distinguish boot from button pairing. Address is a saved device
  slot, not port count; configuration revision is not command phase.
  Sources: the
  [HTV213 protocol](../protocol_documentation/htv213frf.md#retained-reply-owner)
  and common `prepareRetainedAssignment`, which explicitly admits **HTV213 only**.
- **Different tails:** HTV145 stock enrollment includes an empty `59/d9`
  parameter array; HTV405 includes four twelve-byte arrays. HTV213's selected
  lifecycle has no recovered `59/d9`. Do not replace the working enrollment
  state machines with its two-port tail or invent missing parameter contents.
  Source: [native pairing comparison](PAIRING_NATIVE_COMPARISON.md).

Production one-/four-zone control still uses the qualified legacy logical
counter recipe and close-only recovery. Native full-phase control is opt-in;
HTV405's successful trial does not silently migrate existing associations.
The generic [`ValveRecovery`](../rainpointd_addon/rainpointd/valve_recovery.py)
has an empty production `QUALIFIED_PROFILES` table. HTV213 recovery is installed
through its separate experimental retained owner, not that generic production
dispatcher. Keeping these distinctions avoids claiming that merging source
enabled battery recovery on installed garden radios.

## HTV213 promotion implication

The verified HTV213 pairing, both-outlet controls, explicit stop, command wrap,
gateway/node restoration and now battery-recovery/control path are sufficient
to **begin production-source integration preparation**. No further long soak is
needed to justify that source work. Preserve the accepted RF path while moving
association/recovery/control into normal model-specific ownership and HA setup;
remove experimental operator assumptions rather than copying them into the
product. Default builds currently omit this runtime, so a merge alone cannot
make it a general supported model.

The first source-preparation step separates the ordinary
[`ControlJournal`](../rainpointd_addon/rainpointd/htv213_control.py) and
[radio transport](../rainpointd_addon/rainpointd/htv213_control_transport.py)
from experimental counter jumps/CRC retries. HA ownership and controls use
these shared modules directly. Existing storage keys, records, wire commands,
canary capability and association-local wrap qualification remain unchanged;
there is no live migration or firmware change. Temporary-database tests replay
post-battery control and verify restart, cross-association isolation and old
trial compatibility. Normal enrollment/model-menu integration remains pending.

Actual production enablement still depends on the existing roadmap's reviewed
qualification boundaries: reconcile repeat-enrollment/post-configuration
evidence, complete the remaining dry missing-response/overdue check, and verify
the resulting normal setup/reconnect/control path. Do not turn one successful
battery cycle into a claim about every branch, or introduce an arbitrary new
repeat-count/soak gate. Native-allocation lifecycle gates for the **other**
models are separate and need not block HTV213 source preparation.

## Practical next order

1. **Implement offline first:** extend retained-assignment parsing only after
   obtaining each model's known-owner boot/response capture. Reuse the shared
   serializer/configuration responder, but keep transport/profile admission
   model-specific. Preserve existing pairing prefixes and command counters.
2. **HTV405 first physical capture:** its dry outlets and already qualified
   native-control path make it the lower-burden next model. Battery removal
   affects the whole four-zone chassis: schedule it while Zone 1 irrigation is
   idle. Capture one battery-only startup with no pairing window or button hold.
   If its current owner does not recover it, a stock-owned capture is needed
   to learn the actual retained reply; another fresh-pairing transcript is not
   an equivalent reference.
3. **HTV405 verification after the profile exists:** one battery-only cycle,
   unchanged association, observed requested per-port exchanges, then one
   60-second dry Zone 2 command at the retained next phase with positive ACK,
   active and automatic-idle evidence. Do not reset/sync before this command:
   that would obscure whether retained-phase recovery worked.
4. **Repeat that compact check for HTV145:** capture its battery-only boot and
   known-owner reply before selecting the profile; then one 60-second command
   on a dry/disconnected valve, or an explicitly approved front-garden run.
   No arbitrary counter search, soak or broad sensor re-pair is needed to answer
   this question.

These are qualification procedures, not another status checklist. Existing
roadmap gates own scheduling and completion. A missing exchange should drive
capture/profile diagnosis; it is not evidence that resetting every valve's
counter to 1 is correct. Separate later wrap or hub-restart tests from battery
recovery so their causes remain interpretable.
