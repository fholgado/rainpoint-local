# Bounded valve command-phase trial

Current candidate: protected signing run `37085918246` produced unpublished
`0.19.0-phase-trial.6` from source `2216165e5d74b4c9fb7a754ce76122117d49b9ce`.
Publisher signature, binary size/hash and experimental-build boundaries were
verified before updating Vegetable Garden only on October 2. The matched gateway
is `0.39.14-native-trial.2`; Front Garden's radio firmware is unchanged.
Installation and OTA health are not native-control qualification.

The private qualification launcher keeps operator inputs in read-only `/share`
and persists exclusive attempt markers, results and observation status in `/data`.
Its initial worker failed before any valve command because `/share` is mounted
read-only. The correction preserves that mount restriction and passed ten
launcher tests. Existing requests are ignored on restart; failed requests cannot
be repeated. The approved live budget remains one legacy baseline plus two
native 60-second opens on dry Zone 2, followed by no-RF handback.

The optional `phase-trial` signing profile builds firmware
`0.19.0-phase-trial.4` for the installed HTV145FRF and HTV405FRF experiment.
It uses the existing RF waveform, association, body and trailer builders with
the complete six-bit command phase supplied separately from the action.
Ordinary production builds omit its commands and capability.
The build retains correlated ACK-ownership confirmations, saved sensor rejoin
channels, and full-phase response matching used by the current garden radios.

The authenticated radio accepts two adjacent, 60-second opens on one reserved
outlet per authorization (HTV145: port 1; HTV405: ports 1–4). It persists each attempted command before transmission, rejects
duplicates and phase jumps, and blocks ordinary valve commands while locked.
Each run requires a matching positive `a1` response and independent active then
idle reports for the selected outlet. Missing or negative confirmation stops the trial. A reboot
retains a failed lock; it cannot restart the allowance. This trial excludes
phase zero and counter-boundary experiments.

After two confirmed runs, an explicit release updates the radio to the existing
production counter recipe. The gateway must atomically persist that projection
before requesting release, keep its lock until the radio acknowledges, and
provide an association-specific positive command/result baseline for admission.
The firmware alone does not provide those gateway controls. Installing or
signing an image does not establish physical acceptance.

## Building and signing

Use the single `rainpoint_bridge` environment. A local validation build uses
`RAINPOINT_VALVE_PHASE_EXPERIMENT=1` and
`RAINPOINT_FIRMWARE_VERSION=0.19.0-phase-trial.4`; check the binary with
`tools/check_firmware_boundaries.py --phase-trial FIRMWARE_BIN`.
The default checker rejects trial commands in production images.

In GitHub, run **Prepare signed firmware (no publication)** on `main` with
profile **phase-trial**. Validation and compilation complete before the
`firmware-signing` environment requests human approval. The signing job verifies
the clean source commit and the reviewed public key, then produces the private
workflow artifact `signed-firmware-unpublished`. It does not publish a release
or deploy a radio. The production profile remains the default.

See [the project roadmap](../PROJECT_ROADMAP.md) for gateway readiness and the
separate live-test qualification gate.

## September 30 installed trial result

Gateway 0.39.10 and signed firmware `0.19.0-phase-trial.1` were deployed to the
front HTV145 owner only. One 60-second port-1 OPEN at native phase 2 was sent,
without retry. Authenticated radio RX recorded a positive phase-2 `a1` at
23:47:10 UTC, active/countdown telemetry at 23:47:16, idle at 23:48:12 and a
summary at 23:48:14. This establishes acceptance of that even-phase OPEN and
automatic closure, not completion of the two-run experiment or general phase
qualification. The veggie node was not flashed or exercised.

The trial monitor timed out despite the positive RF result. Its field-reader
lambda was named `word`; ESP32 Arduino.h defines `word(...)` as
`makeWord(__VA_ARGS__)`. Thus `word(23)` compiled as a conversion of the number
23 rather than a read of the two-byte duration. The duration check could never
pass. Macro-free native tests missed this hardware-build difference.

Renaming the helper to `readLe16` fixes the source. The regression compiles the
real guard both with and without Arduino's macro, including replay of the
[redacted actual RX](../research/fixtures/htv145_phase2_trial_20260930.json).
The macro-enabled test failed before the fix and passes afterward. Neither the
RF command builder nor its duration, timing, power or association changed.

The capture is evidence, not permission to rewrite the failed trial as passed.
The initial deployed guard remained locked because its existing release command
requires two completed runs. The separately approved no-watering recovery below
preserves that failure history; do not erase the journal/NVS, retry the open, or
infer a counter from a report's independent phase.

Private evidence is retained under `captures/installed-phase-20260930/`.
The five-minute IQ file is 1,200,000,000 bytes, SHA-256
`9ae7938c092accf994c3a71a0baa9f3c9156bb44bf160dbf064f777ff99ee518`.
The initial 40-second scan yielded no valid decoded frames; this is a coverage
limitation, not radio silence. The result above rests on authenticated node RX,
not independently decoded SDR IQ. The baseline request was reconstructed from
retained command parameters and the received ACK, not captured over the air.

## Explicit no-watering incident recovery

Version `phase-trial.2` corrects the Arduino macro collision and adds
`valve_phase_trial_recovery`. The authenticated gateway recovery operation is
limited to the first failed HTV145 phase-2 run. It accepts three existing event
IDs, not caller-invented packet bytes. Positive owner ACK, matching active
report and owner idle must have valid CRCs, the reserved route/phase/port and
60-second duration, and ordered timestamps within the original attempt. A later
command response or new watering report invalidates the anchor. Current idle,
unchanged ownership, unchanged last production transmission and no pending
command remain prerequisites.

The gateway atomically stores the evidence and the existing odd-open counter
projection before requesting radio recovery. The radio independently replays
the supplied frames against its preserved NVS authorization, attempted command
ID, phase and selector. It persists a distinct **Recovered** terminal state
before releasing its lock. The gateway waits for that state with the exact
recovery ID. Neither side rewrites the failed attempt as a successful trial.

The recovery command cannot transmit RF. Duplicate requests retain the same
recovery ID, do not reapply the radio counter, and cannot reopen the trial.
No NVS/database deletion, speculative close, counter search or pairing is
involved. Its firmware must be signed through the protected approval workflow;
source/build validation is not deployment or live recovery confirmation.

### October 1 recovery verification

After a verified backup of HA configuration and the current gateway journal,
gateway `0.39.11` was deployed from the tested recovery-only package. Protected
signing run `36796917397` produced front firmware `0.19.0-phase-trial.2` from
commit `390ab69a2426a9df7bdd286e02aef003dee9fa8e`; its publisher signature and
SHA-256 `2d66f6abab607335735157f590d277d2a5c174a047fdbfcd92c2eaed170e05bd`
were independently verified. Only the front node was updated, and it reported
`confirmed` / `gateway_and_radio_healthy` with no pending OTA candidate.

One recovery request used the retained original ACK, active and owner-idle
event IDs. The gateway entered `recovering`, then received the matching radio
stage-7 acknowledgment and recorded `recovered`. The production counter handoff
is 129 (legacy odd-open encoding); the original one-run failure remains in the
journal rather than becoming a completed experiment. Normal front command
availability is restored. Both installed valves reported idle, and the veggie
node remained on `0.19.0`. No open, close, sync, pairing or second trial command
was sent. This verifies recovery, not a subsequent watering run or the remaining
adjacent-phase qualification. Private OTA/recovery receipts are retained beside
the original evidence in `captures/installed-phase-20260930/`.

### Normal-control confirmation after recovery

Later on Oct 1 the user authorized front-garden watering tests. Two normal
public-control port-1 requests each specified 60 seconds, with no application
retry, counter probe, manual stop, re-pairing or additional flash. The second
request followed RF-confirmed automatic closure of the first.

| Run | Native command/ACK phase | Positive ACK | Active report | Automatic idle | Retained counter |
| --- | --- | --- | --- | --- | --- |
| 1 | 3 | 0.67 s | 6.77 s | 62.72 s | 129 → 130 |
| 2 | 5 | ~0.7 s | ~6.7 s | ~62.8 s | 130 → 131 |

Times are observation offsets from request dispatch, not measured mechanical
opening durations. CRC-valid, accepted matching-route RF packets establish
acknowledgment, active port-1 state and return to idle; API acceptance alone
was not counted as success. Status-report phases are independent and were not
used to infer the next command phase. Both transactions completed normally.
This validates the recovered legacy control path and sequential counter advance,
not the still-pending adjacent even/odd trial or long-idle qualification.
Total requested watering was 120 seconds; the vegetable garden was untouched.

Private receipts and RF events are in
`captures/installed-phase-20260930/normal-controls-after-recovery-20261001/`.
The user also requested deletion of existing local backups. Managed HA backups,
inventoried manual recovery copies and identified Mac HA database/archive copies
were removed; the live gateway journal and original RF/firmware research remain.
Consequently the pre-recovery backup referenced above is no longer retained.

### October 1 adjacent-phase confirmation

After the user's 35-minute front irrigation reported idle, gateway `0.39.11`
and front firmware `0.19.0-phase-trial.2` completed exactly two guarded
60-second runs at adjacent native phases **8 then 9**, without retry, sync,
reset or flashing. Admission used the user's positive phase-7 ACK and retained
counter 132; its request was reconstructed from the known 2,100-second command,
not captured independently over the air.

| Phase | Positive ACK | Active report | Automatic idle |
| --- | --- | --- | --- |
| 8 | 0.71 s | 6.70 s | 62.59 s |
| 9 | 0.71 s | 6.87 s | 62.28 s |

Offsets are from each local attempt marker, not measured mechanical durations.
A separate read-only audit of CRC-valid, accepted matching-route node RX
confirmed both full-phase positive `a1` replies with 60-second duration and
independent port-1 active/idle `02` reports. The second run followed the first
confirmed idle. The gateway then recorded `released`, the authenticated owner's
matching authorization reported release, and the production retained counter
was 133. The valve was idle and normal controls unlocked; no further watering
was sent to test that handback.

This qualifies adjacent even/odd opens for this HTV145 association and build,
not phase wrap, long-idle behavior or the four-zone model. The failed September
30 trial remains in history. Private receipts, RF events and the independent
audit are in
`captures/installed-phase-20260930/front-adjacent-after-user-run-20261001/`.

### Dry-outlet selection and local-profile correction

The user identified HTV405 outlets 2–4 as dry. Gateway `0.39.12` and trial
firmware `.3` add an explicit `port` to admission, durable reservations and
radio commands. A non-default port requires `valve_phase_trial_ports` at both
admission and authenticated transport; an older radio cannot silently run port 1.
The selected outlet cannot change for the second run. Stock `a1` carries
control/work mode rather than outlet identity. Generated local associations
pack the outlet into the state nibble: Zone 2's positive open returned `41`
instead of stock `21`. Acceptance also requires matching
outlet-specific active and idle `02` reports. The baseline request must identify
that same outlet, so use an authorized normal dry-outlet baseline first if none
is available. Do not reuse a Zone 1 baseline for Zone 2.

The radio record remains 88 bytes with `port` in former padding. Its new magic
version distinguishes valid outlet records from legacy padding: old records
migrate explicitly to port 1, and malformed new outlets fail closed. No pairing
prefix, ordinary production control builder or RF waveform changes.

On Oct 1, gateway `0.39.12` and signed veggie firmware `.3` were deployed after
backup `6497cbd1`, publisher verification and gateway-package tests. Both garden
radios reconnected. One ordinary Zone 2 request specified 60 seconds and native
phase 1. The owner received a positive ACK after ~0.77 seconds; independent
accepted reports showed active Zone 2 after ~1.41 seconds and automatic idle
after ~62.34 seconds. Production retained the next counter 1. The helper
incorrectly reported missing confirmation: the ACK was logged under its control
alias, and it assumed the stock native outlet layout. No adjacent trial was
admitted or transmitted.

The generated command body is `[01, port << 1, 01, seconds_low, seconds_high]`,
preserving the existing builder; the stock form is
`[port, 02, 01, seconds_low, seconds_high]`. Local active `02` rows retain native
port byte `01` and pack the active outlet into state `port << 5 | 01`; local
idle clears that state to zero. The production decoder already handles this.
Gateway `.13` and trial firmware `.4` reuse that decoder for the experiment,
accept the model-qualified local ACK layout, and require selected-outlet active
evidence before global idle can complete a run. Persisted model selection uses
another former padding byte; older records migrate without reopening locks.
The [anonymized actual exchange](../research/fixtures/htv405_local_port2_baseline_20261001.json)
reproduces the old failure in both radio and gateway regressions. It proves
normal phase-1 control, not acceptance of adjacent phases. The front remains
on signed `.2`; four-zone adjacent qualification remains incomplete.

### Corrected deployment and freshness rejection

Protected signing run `36872047806` completed after user approval. The verified
`.4` image is from commit `5c3fd03f3398bdf7c5c8183d11bcb67c8aacbe2c`, SHA-256
`4e9c035f0849bda463f6cca5ee64a30349894cdfdf5b29114c231e57069b541b`.
Gateway `0.39.13` matches the tested package's complete source-hash manifest;
only its four correction-package files changed. The veggie radio confirmed
healthy signed OTA with no pending candidate. Front firmware stayed on `.2`.

Trial admission at approximately 14:48 UTC was rejected before reservation or
RF transmission. The latest independent watering-state report was at 13:27:38,
more than an hour earlier. The public snapshot's 14:46:32 `observed_at` reflected
more recent reception; `state_observed_at` correctly retained the older state
timestamp. The guard examines the underlying state, not that public reception
timestamp. Offline replay reproduced rejection with the old state timestamp;
changing only the timestamp to recent reception would incorrectly admit it.
The finite helper's preflight now checks `state_observed_at` when present.

No adjacent open, retry, reset, sync or repeated baseline was sent. All outlets
remained idle, production counter 1 was unchanged, and no experimental lock was
created. Fresh independent idle evidence is required before another admission;
additional baseline watering requires user approval. Private deployment,
signed-OTA and rejection receipts remain beside the baseline evidence.

### October 1 four-zone adjacent-phase confirmation

The user separately approved one fresh 60-second baseline on dry Zone 2,
followed by the two guarded trials. The old admission attempt and its evidence
were preserved. No firmware/configuration change, pairing, reset, sync or
counter guess was needed. Gateway `0.39.13` and veggie firmware `.4` remained
healthy; the wet Zone 1 outlet and front garden were untouched.

The ordinary baseline used the retained counter 1 and native phase 3. Its
positive owner ACK arrived at 0.73 seconds, Zone 2 active at 1.93 seconds, and
automatic idle at 62.94 seconds. This supplied fresh independent state and
advanced the ordinary counter to 2 before admission.

| Trial phase | Positive ACK | Zone 2 active | Automatic idle |
| --- | --- | --- | --- |
| 4 | 0.67 s | 1.53 s | 62.54 s |
| 5 | 0.81 s | 1.55 s | 62.55 s |

Offsets are from each private attempt marker, not measured mechanical durations.
A separate read-only RF audit confirmed matching-route, CRC-valid accepted
packets: both full-phase owner `a1` replies were positive with local mode `41`
and duration 60, followed by independent selected-outlet active and automatic
idle `02` reports. Phase 5 followed confirmed phase-4 idle. Exactly these three
60-second commands were sent; there was no retry or additional handback run.

The gateway recorded two completed transactions and `released`; the owner radio
reported the same released authorization. All four outlets were idle, no
production command was pending, and the retained production counter was 3.
This qualifies adjacent even/odd opens for this HTV405 association and build,
not a general phase allocator, boundary rollover or battery-rejoin policy.
The normal production counter recipe remains unchanged.

Private baseline, trial, independent RF audit and release receipts are retained
in `captures/installed-phase-20260930/four-zone-fresh-baseline-20261001T1653/`.
The evidence uses authenticated radio RX; no independently decoded SDR TX
capture is claimed. Admission reconstructed the baseline request from its exact
positive ACK and known Zone 2/60-second parameters.

## Production allocation preparation — October 1

The installed adjacent-OPEN trials qualify the new wire phases, not a complete
production allocator. `rainpointd/valve_command_phase.py` now provides the shared
gateway codec: strict ordinary-frame integrity, six-bit phase, local one-/four-zone
builders and result matching against retained request context. The canary parser
uses this codec without changing its admission or two-run limit. Native radio and
gateway builders are cross-checked across all 64 phases, both actions, all ports,
and 1/21/60-minute durations. The radio decoder also rejects the reserved phase bit.

At the end of October 1, `rainpointd/valve_phase_commands.py` was a **source-only
allocation foundation**, without a standard-control caller or radio dispatch.
The October 2 candidate adapter below adds those callers; no live activation,
deployment or automatic migration has occurred. Production remains unchanged.

Preparation requires the latest owner-authenticated positive request/result pair.
The gateway adapter proves its event provenance and that no later send occurred.
The journal checks association/profile, action, port, duration, full
phase and the current legacy counter recipe; it rejects pending commands,
revocation, unresolved maintenance and existing journals. It cannot convert a
telemetry phase or blindly shift a saved legacy counter. In particular, a legacy
counter's next native phase depends on the last action/marker policy.

The additive private metadata record leaves legacy counters, pairing and
transactions byte-for-byte unchanged. Each reservation stores a UUID, exact
normalized request bytes and consumed phase before dispatch. SQLite compare-and-save
checks the legacy snapshot and journal under a writer lock. A second attempt,
changed owner/profile, newer legacy command or stale reservation cannot dispatch.
The transport owns any bounded identical-byte RF repetitions; gateway restart
does not replay an attempted packet or allocate a new phase for an uncertain one.
Positive full-phase results authorize further allocation only, **not a watering
success notification**. Negative native results are retained without normalization;
missing/negative results keep the reservation uncertain and prevent another command.
Automatic native phase-zero rollover remains blocked until model qualification.

The candidate adapter enforces
exclusive allocator ownership, durable radio receipts, capability checks, fresh
independent state timestamps, one-active-port/schedule interlocks and existing HA
transaction feedback. A prepared journal alone is not that interlock. Never let old and
new allocators dispatch in parallel. Independent active/idle evidence remains
necessary for physical outcomes, and restart must not cause a speculative close.
The repository's SQLite durability settings do not by themselves qualify abrupt
power loss; radio persistence and restart/duplicate handling must be tested too.
Retain uncertain history across any separately verified recovery/epoch handoff;
do not reinterpret a negative idle-anchor result as a positive normal command.
The existing close-only recovery recipe remains unchanged and is not replaced by
this journal's normal-command allocation rules.

The remaining production gates are in [the roadmap](../PROJECT_ROADMAP.md#shared-command-phase-qualification).
Historical trial evidence above remains unchanged.

Final offline validation: 908 Python tests passed (two optional skips), including
51 focused codec/journal/canary regressions; the native protocol executable,
unified production ESP32 build, production-exclusion check and `git diff --check`
passed. Nothing was flashed or deployed, and no live command was sent.

## Standard-control candidate — October 2

`native_valve_control.py` now connects the normal gateway valve request to the
shared allocator for an explicitly admitted association. There is no HTTP,
configuration or HA switch for activation. The source-only opt-in additionally
requires candidate capability `valve_native_phase_v1`, the retained owner's
latest positive RF exchange, and a matching native `02` idle report after it
(at most 120 seconds old). A prepared journal alone cannot transmit.

Activation grants this first candidate exclusive **whole-radio** ownership.
The gateway and radio block old command allocators, pairing and reset probes;
normal telemetry acknowledgments remain intact. Production multi-valve support
is unchanged. Multi-association native radio scheduling is not claimed by this
candidate. Disabling the opt-in cannot silently switch an adopted owner back
to the legacy counter recipe.

Each request retains its UUID, full phase and exact normalized bytes before
dispatch. Candidate firmware independently rebuilds those bytes from the
retained association/profile and saves an NVS receipt before RF. Duplicate
requests return the receipt without transmitting; conflicting bytes are
rejected. The initial candidate sends one bounded frame, not a fresh-counter
retry. It retains the established carrier, wake, power and framing. Corrupt NVS
or an attempted command restored after boot stays uncertain, never replayable.
An accepted receipt survives reboot; session readiness still requires a fresh
matching receipt. Reconnect only reports state, without an actuator command.

The existing HA transaction fields now distinguish pending, confirmed and
failed native controls. Confirmation requires all three: exact owner/full-phase
positive RF `a1`, the radio receipt, and independent selected-outlet `02` state.
Physical telemetry and control counters remain separate. Buttons stay disabled
while evidence is pending and during the 15-second command interval. Transport
exceptions/radio rejection fail immediately; missing evidence fails after
15 seconds. Evidence changes and non-actuating deadline events wake HA's event
listener, so failure/availability feedback does not wait for its periodic poll.
Late packets cannot resurrect the transaction. A failed close
preserves the earlier run's expected-stop deadline and observed watering until
fresh idle is actually received. Existing HA notifications consume these fields;
no mobile service or optimistic success notification was added.

Phase zero remains blocked. Uncertain attempts retain their exact history and
exclusive lock. Native recovery/epoch handoff is implemented in source only,
not RF-qualified; the established legacy close-only recovery remains available
only for legacy-owned production associations. Do not clear receipt records, force a
counter, downgrade firmware or replay an OPEN to escape the lock. These explicit
qualification gates remain in [the roadmap](../PROJECT_ROADMAP.md#shared-command-phase-qualification).

The native RF runtime/capability is compiled only in the versioned phase-trial
candidate. The production binary checker rejects all native candidate commands.
No candidate was signed, deployed or flashed during this source work, and no
watering, pairing, reset or live database change was performed.

October 2 offline validation: the full Python suite completed 924 tests with
two optional skips and no failures. Sixteen focused tests cover standard-control
requests, independent confirmation, persistent radio receipts, duplicate/restart
blocking, administrative ownership locks and failure events without HA polling.
The native C++ protocol executable, candidate `0.19.0-phase-trial.5` build,
production build, both firmware-boundary checks and `git diff --check` passed.
These checks do not qualify RF timing, abrupt power loss or native recovery.

### Source-only native maintenance

Candidate `.6` adds `valve_native_handoff_v1`. Maintenance uses the same control
module and private gateway opt-in as normal native requests; no HA/HTTP switch
or automatic retry is introduced. Both operations are **no RF**:

- Recovery requires the exact persisted positive `a1`, a fresh-session accepted
  radio receipt, and matching owner/outlet `02` idle after the requested run
  duration. The radio also requires that exact idle to be its latest locally
  observed state (at most 120 seconds old). Only a failure caused by missing
  independent confirmation is recoverable this way. Missing/negative command
  results, uncertain NVS and unknown command responses remain locked.
- Legacy handback requires a confirmed native command and that same idle proof.
  Only the qualified odd-OPEN/even-CLOSE legacy recipes are admitted: phase
  must be at most 62, and an odd native CLOSE cannot hand back. The retained
  legacy counter becomes `(last_phase + 1) // 2`; an OPEN may end on either
  parity. The radio durably records release before its receipt. SQLite updates
  the legacy counter/state and retires native ownership atomically, only after
  a correlated release receipt.

An unresolved operation exposes verifying/unresolved status and disables
controls. A lost receipt may be requested again explicitly with identical
operation UUID and proof; it only returns the durable result, never waters or
rewinds a counter. Restart never automatically repeats maintenance or actuation.
Database failure retains exclusive ownership even if the radio already released.
The original failed watering transaction and attempted bytes remain failed and
unaltered after recovery. A later fresh epoch requires a new accepted legacy
exchange; admission archives the retired epoch in the same database transaction.

The request carrier selector and native report selector are stored separately:
the captured four-zone command uses selector 5, while its native `02` reports
use 4. Substituting the report selector into the command builder is invalid.
Candidate receipt format is version 2. The earlier native `.5` candidate was
never deployed; any incompatible/corrupt receipt still fails closed and is not
erased or silently migrated. Existing legacy/canary storage is unchanged.

The test audit found no obsolete test modules or exact duplicate test bodies.
Legacy-counter tests remain necessary for production; captured-packet tests
preserve protocol evidence; upgrade/migration and removed-wizard exclusion
tests remain regression coverage. Old fixture dates or firmware-version inputs
alone are not grounds to delete tests.

Maintenance validation on October 2: full suite 938 tests, two optional skips,
no failures. The real C++ receipt guard covers fresh/stale/early idle, exact
result matching, durable recovery/release, duplicate receipt after restart,
failed writes and incompatible NVS. Gateway tests cover atomic database
rollback, source opt-in, unknown results, disabled controls, explicit identical
maintenance retry, retained failed history and archived epoch admission.
Candidate `0.19.0-phase-trial.6`, default production build, native protocol
executable and both firmware-boundary checks passed. No signing, deployment,
flashing, live database mutation or valve actuation occurred.

### Bounded native qualification preparation

The optional private admission scope adds `valve_native_scope_v1`: one retained
outlet, at most two native OPEN attempts of exactly 60 seconds, and a 120–900
second window. Both gateway and radio enforce the outlet/duration/budget. The
gateway requires the internal epoch argument, which the HTTP handler does not
accept or forward; HA controls display unavailable during the scoped trial.
There is no public enrollment/activation switch. Unscoped source/offline standard-
control tests remain unchanged; installed qualification must use the scope.

The reservation/attempt counts against the durable budget regardless of success.
Duplicates return the same receipt, never allocate a new allowance. Repeated
adoption cannot refresh the radio deadline or quota. An MCU restart disables
further scoped RF instead of reconstructing a deadline from untrusted wall time;
fresh status tells the gateway that RF permission is disabled. Explicit no-RF
recovery/handback remains possible with the required fresh proof. Expiry never
clears ownership or restores legacy control by itself.

Proposed first installed test, requiring separate deployment/control approval
and confirmation that HTV405 Zone 2 is still dry:

1. Verify both installed valves idle, healthy ACK ownership, no pending command
   or firmware update, and no scheduled/user watering overlapping the trial.
   Use the matched gateway and signed candidate on the Vegetable Garden radio
   only. Keep the front radio firmware, pairing and irrigation settings intact.
2. Send one legacy Zone 2/60-second baseline. Require exact positive owner ACK,
   independent active and automatic-idle reports. The baseline must leave two
   adjacent nonzero native phases with final phase at most 62; otherwise stop
   without a counter jump. Admit the verified idle association with a 900-second,
   two-attempt native scope. Admission itself transmits no RF.
3. Perform up to two separately journaled native Zone 2/60-second opens. Wait
   for positive full-phase ACK, persisted radio receipt, selected-outlet active
   and automatic idle for each, with at least the existing 15-second spacing.
   Stop on the first missing/negative/mismatched result. Do not retry, probe a
   counter, close another outlet, or force release.
4. After confirmed automatic idle, request non-transmitting handback. Verify
   correlated radio release, atomic retained-counter projection, no active
   native owner, fresh idle and ordinary HA control availability. Persist the
   raw owner RX and maintenance receipts privately. A source/capability match
   or HTTP success is not RF acceptance.

This is at most three one-minute **dry Zone 2** runs including the baseline.
There are no Zone 1/front-garden commands, pairing or valve resets. A failure
without sufficient proof can retain an exclusive lock and require user-assisted
re-pairing; do not erase it to complete the test. Successful normal runs qualify
control and handback, not missing-state recovery or power-loss behavior. Those
remain separate approved tests in the roadmap; no fault is injected silently.

October 2 readiness check: the front, Vegetable Garden and Test Node B radios
were connected/authenticated and all three valves reported idle. The active dry
test valve is HTV213FRF; this one-/four-zone candidate must not be applied to it.
The OTA-test node was offline, and no live node advertised the new native
capabilities. No firmware, gateway, control, reset or pairing change was made
during this readiness check.

Scoped preparation validation: full suite 942 tests, two optional skips, no
failures; candidate `.6` and production builds, both binary-boundary checks,
the native protocol executable and `git diff --check` passed. Nothing was
signed, deployed or actuated. The default production binary remains built last.

### Private signed candidate preparation (October 2)

The focused radio candidate was merged in PR #29, preserving unrelated PCB,
UI and HTV213 work. The clean committed tree passed all CI checks, 649 Python
tests (two optional skips), 27 focused receipt/phase tests and the `.6` firmware
build. Protected signing run `37085918246` targets source commit
`2216165e5d74b4c9fb7a754ce76122117d49b9ce`; preparation passed and signing is
waiting for the user's protected-environment approval. It does not publish or deploy.

The matched gateway is staged over the hash-recorded `.39.13` package. It adds
native control and legacy ownership interlocks, not the unrelated valve-rejoin
candidate. Its private operator mailbox accepts only dry HTV405 Zone 2,
two native 60-second attempts and explicit no-RF handback; public HA/HTTP
cannot activate it. Persisted once-only markers precede dispatch, and restart
ignores existing request files. Seven mailbox tests and 34 native control/receipt
tests pass. Staged-package validation caught an omitted legacy interlock before
deployment; the corrected package must pass before any live update.

The approved live budget remains one legacy baseline plus at most two native
runs. No live changes or controls have occurred during preparation. RF control,
recovery and production promotion remain unqualified until evidence is recorded.

### October 2 qualification stopped at legacy baseline

After protected signing approval, the publisher-verified `.6` image and matched
gateway were installed as described above. All valves reported idle before the
update; Vegetable Garden authenticated and completed healthy OTA confirmation.
The gateway storage correction changed only the private launcher and package
version, retaining read-only `/share` and persistent `/data` receipts.

Exactly one public Zone 2/60-second watering request was made at
`2026-10-03T01:50:23.281319Z` (October 2 local time). The retained legacy sequence
was zero, implying requested native phase 1. At `01:50:26.722979Z` the owner
radio reported `gateway_command_response_timeout`; the gateway durably failed
the transaction and invalidated the unconfirmed counter. There was no positive
ACK, negative ACK, selected-outlet active report or verified automatic-idle
transition for this attempt. A timeout does not prove mechanical non-operation.

No native adoption, native OPEN, handback, re-sync, counter guess, close, pairing
or valve reset followed. Front Garden and wet Zone 1 received no test commands.
There is no active native ownership lock: ordinary availability is instead
blocked by the legacy counter's unsynchronized state. Normal sensor RX continued,
and target valve routine reporting resumed at `01:52:25Z`; this is not evidence
of successful watering or command acceptance.

The private deterministic replay `replay_baseline.py` fails on the saved trace
with `Baseline lacks RF acceptance evidence: ack, active, idle`. The receive-only
IQ scan of seconds 8–28 on 433.140, 434.240 and 434.350 MHz found no validated
exchange. That limited scan cannot establish RF silence or the transmitted
phase. Preserve the full capture and journal under
`captures/native-control-20261002/` for further offline analysis.

Source inspection also found that the normal HTV405 radio path automatically
repeats the identical frame at 650 and 1,450 ms while awaiting a reply. The
operator made no second API request or counter retry, but this baseline path
does not satisfy a strict single-RF-attempt experiment. Actual repeat count was
not retained in the gateway's observation journal. A separately approved dry-
outlet recovery and explicit radio-layer attempt limit are required before
another qualification. Stale counter, RF delivery/reception and missed response
remain hypotheses; an explicit valve rejection was not observed. Native control,
handback and production promotion remain unqualified.

The deployed `.4` and `.6` source commits have identical CC1101 transport and
legacy valve-control builder files. This rules out a change in those files,
not an interaction in the added native handler or a live RF/counter issue.
Sixty focused tests against the exact staged/deployed gateway package passed
after the storage correction; offline success does not repair the live counter.
The bounded 600-second receive-only IQ recording completed at 2,400,000,000
bytes; its SHA-256 independently matches the recorder's checksum. Private
verification receipts and the original IQ remain beside the failed baseline.

### October 2 resumed native qualification — passed

Following the user's recovery/resume approval, a close-only counter-zero anchor
on dry Zone 2 received an authenticated idle response. One new legacy phase-1
OPEN then received a positive owner ACK, selected-outlet active reports and
automatic idle after 60 seconds. The original failed attempt remains preserved.

The first monitor missed those physical packets because a secondary receiver
won duplicate suppression. Receiver metrics retained coverage, not individual
frames. The gateway now stores a bounded physical-reception journal separately
from logical events; exact owner/frame/time evidence survives restart without
inflating logical report cadence. Admission also uses the explicit valve-control
setting, consistent with legacy control on the network receive transport.

Fresh routine HTV405 subtype `0e` idle reports had previously failed the
immediate-report decoder. The adapter now accepts only their same-route,
same-selector, zero-run-marker/zero-timers form with fixed structural markers.
The cycling index is never interpreted as an outlet; active routine reports
remain undecoded here. These fixes have red/green regressions. Rejected
no-RF admissions created no native owner or watering command.

Signed `.6` then accepted native OPEN phases **2 and 3**, each on dry Zone 2 for
60 seconds. Each run had a full-phase positive owner ACK, persisted radio
acceptance receipt, selected-outlet active report and automatic-idle evidence.
The correlated **no-RF handback completed**, retaining legacy counter **2**.
Normal HA control was available and the valve was confirmed idle. Front Garden
and Zone 1 received no commands during this experiment.

The temporary operator launcher was removed and ordinary gateway startup
restored. Native production allocation remains opt-in; this does not qualify
HTV145 native control, wraparound or native-owner restart/lifecycle behavior.
The two resumed IQ recordings (1.8 GB and 1.2 GB) have independently verified
size/SHA-256 receipts. They cover recovery/baseline portions, **not** the later
native runs; native results rely on retained owner RX, physical reports and
correlated radio receipts. Private evidence is under
`captures/native-control-20261002/resume-20261002/admission3/`.
