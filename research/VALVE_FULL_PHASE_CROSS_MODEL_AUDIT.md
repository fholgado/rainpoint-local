# Valve command phases across HTV145, HTV213 and HTV405

2026-09-30. Offline audit of retained capture fixtures, stock disassembly and
current source. No hardware, live-state, flashed-firmware or deployment changes. Project
status remains in [PROJECT_ROADMAP.md](../PROJECT_ROADMAP.md).

## Conclusion

All three models use a six-bit native command phase independent of watering
action. The one- and four-zone implementations retain a narrower, historically
qualified action/counter recipe; this is a local representation, not evidence
of a different five-bit wire protocol. Their existing recovery remains useful
but does not establish the valve's general acceptance algorithm.

There is **already one-zone evidence of OPEN 63 → CLOSE 0**, and four-zone
operational records of the corresponding wrap. The new two-zone experiment
adds independently captured **OPEN 62 → OPEN 63 → OPEN 0 → OPEN 1**, including
the deliberate initial jump. It must not erase those earlier findings or be
generalized into arbitrary phase acceptance on every receiver.

## Primary evidence

For a normalized 38-byte frame `N`, the native payload and phase are:

```text
P[i]  = ((N[i+4] << 1) | (N[i+5] >> 7)) & 255
phase = P[9] & 63 = ((N[13] & 31) << 1) | (N[14] >> 7)
```

Native command `21` carries port/mode/action in its body; `a1` replies echo the
full phase. In particular, normalized `10/90` includes the phase's low bit, not
a permanent OPEN/CLOSE or association-selector flag. The transform is exercised
against independently labeled captures by
[`stock_payload` and `StockValveFrameReferenceTests`](../tests/test_stock_valve_frame_reference.py),
lines 21–79.

| Model/evidence | Re-decoded native phases | What this establishes |
| --- | --- | --- |
| HTV145 stock [selector-2 controls](fixtures/htv145_selector2_stock_pairing_control_20260905.json), `controls`, lines 126 onward | OPEN 3, OPEN 4, CLOSE 5, OPEN 6, CLOSE 7 | Both phase parities support OPEN on the same association. Successive OPENs are separate runs; this does not authorize overlapping watering. Each run retains independently observed watering/idle flags. |
| HTV145 stock [selector-6 duration commands](fixtures/htv145_selector6_stock_duration_commands_20260828.json), `transactions`, lines 40–98 | OPEN 3, CLOSE 4, OPEN 5, CLOSE 6 | Every retained `a1` echoes all six request bits. The apparent reused normalized sequence on CLOSE/OPEN is ordinary full-phase advancement. |
| HTV405 stock [four-port matrix](fixtures/htv405_stock_cloud_control_matrix_20260824.json), `trials`, lines 25–89 | OPEN/CLOSE 3/4, 5/6, 7/8, 9/10 | One progression crosses ports 1–4; active/idle reports corroborate the requested port. |
| HTV405 stock [early-stop runs](fixtures/htv405_stock_early_stop_20260824.json), `runs[1:3]`, lines 34–96 | Port 3 OPEN/CLOSE 20/21; port 4 OPEN/CLOSE 22/23 | OPEN is also even and CLOSE odd. This directly refutes fixed action parity for the four-zone model; both runs retain independent active/idle frames. Port 2 commands are missing and must not be reconstructed as captured evidence. |
| HTV145 local [active-close recovery](fixtures/htv145_active_counter_recovery_20260906.json), `command_transactions`, lines 61–93 | Active CLOSE 62, OPEN 63, CLOSE 0 | Raw command/result/state frames support the earlier boundary under a close-anchor preparation. The receiver accepted phase-zero CLOSE, not phase-zero OPEN. |
| HTV145 local [idle result-3 recovery](fixtures/htv145_idle_result3_counter_recovery_20260906.json), lines 46–77 | Idle CLOSE 62/result 3, OPEN 63/positive, CLOSE 0/positive | Actual radio RX plus independent state reports repeat that boundary. This fixture explicitly lacks independent IQ; request bytes come from unchanged builders matching the earlier capture. Result 3 is a qualified idle-anchor exception, not ordinary actuation success. |
| HTV405 local [overnight/recovery record](fixtures/htv405_overnight_counter_drift_20260902.json), `exhaustive_idle_close_selection`, lines 160–227 | All 32 logical idle-close values; logical OPEN 31, CLOSE 0, OPEN 0 | Under the recorded builder policy these are native even CLOSE phases and OPEN 63 → CLOSE 0 → OPEN 1. Boundary entries are runtime summaries without raw frames, weaker than independent RF replay. Not a phase-zero OPEN test. |
| HTV213 local [boundary fixture](fixtures/htv213_local_counter_boundary_20260930.json), qualified in [boundary audit](HTV213_COUNTER_WRAP_AUDIT.md#subsequent-authorized-local-rf-result) | OPEN 62, 63, 0, 1; initial next phase was 9 | Independent IQ verifies command/result, watering/idle and elapsed-60 summaries for one association and port. No close, re-pair or reset between steps. |

This audit independently re-decoded the HTV145 successive-action and recovery
frames and HTV405 early-stop command bytes with the transform above. It did not
re-decode original IQ or infer missing packets. Historical fixture prose such
as “advances once per watering session” or “selector reverses marker” is an old
interpretation preserved with the evidence, **not** the current wire definition.

The retained stock application disassembly independently supports the shared
model: `sequence_generator.txt`, function `0x42037920`, increments a single hub
byte, compares the old value with 63, and allows returned 64;
`master_internal_header.txt`, `0x4203A435..0x4203A447`, masks that return to six
bits. Consequently the wire progression includes `63→0→1`. These private files
are under `captures/stock-hub-firmware/2026-09-27-adzoj0e3/analysis/valve-state-20260927/`.
The command builder `0x4204FCAC` calls this header at `0x420500E7`; the reply
matcher `0x4204A550` compares both identities, command/ACK byte and all six phase
bits. See the qualified
[stock trace](STOCK_HUB_VALVE_STATE_TRACE.md#3-counter-generation-a-global-six-bit-header-field)
and [version-independent audit](HTV213_COUNTER_WRAP_AUDIT.md#primary-firmware-evidence).
This is hub allocation, not decompilation of any valve receiver.

## Implementation boundary

HTV145 `valve_protocol.py::next_htv145_command_sequence` (lines 449–452) and
`rainpoint_htv145_control.h::nextHtv145CommandSequence` retain a five-bit logical
counter after CLOSE and advance it after OPEN. Its builders choose the sixth
bit through `command_marker_inverted`. HTV405
`rainpoint_valve_control.h::buildHtv405GatewayOpenFrame` (105) and
`::buildHtv405GatewayCloseFrame` (154) similarly choose odd OPEN/even CLOSE;
`::nextHtv405GatewayCommandSequence` (312) implements logical rollover.
Those tested alternating recipes can encode native progression, but cannot
represent arbitrary stock action order through one fixed marker policy.

Changing only `&31` to `&63` would corrupt this representation and lose the low
bit's placement. Changing the builder alone would also leave stored pending
transactions and result matchers inconsistent. The
[full-phase correlation repair](STOCK_HUB_SEQUENCE_MATCH_AUDIT.md#native-phase-versus-the-local-representation)
already ensures opposite-phase replies do not consume the wrong reservation;
preserve that guarantee, the qualified idle-anchor exception, and exact retry
bytes. Stock retries reuse a packet, not a freshly allocated phase.

The source-only
[`rainpoint_valve_command_phase.h`](../firmware/rainpoint_bridge/include/rainpoint_valve_command_phase.h)
now exposes `commandPhase::buildHtv145`, `::buildHtv405` and `::fromNormalized`.
These pure adapters preserve the established body/trailer builders and encode
the full phase independently of action; they introduce no runtime caller,
gateway API, journal or RF authority. Replay covers action parity and logical
rollover without changing ordinary production allocation or recovery. Never
derive the new next phase from report counters or convert a legacy stored
counter without its action/profile/pending-frame context.

The next canary must reserve and persist the complete request phase before TX,
keep uncertain attempts consumed, and match the full phase independently of
the observed watering state. The existing HTV405 positive decoder still ties
phase parity to watering; changing only the builder cannot make an even-phase
OPEN work end to end. A shadow/offline decoder must first pass captured positive
and negative replies and stale/opposite-phase rejection tests. Keep any pending
legacy transaction on its original path through completion; do not reinterpret
its stored five-bit value as a six-bit phase or reseed it on restart. Enable a
new journal only for an explicitly selected test association with traceable
command evidence and no unresolved later send. These are source-integration
prerequisites, not features supplied by the new pure adapters.

### Reply context correction

The retained stock `analysis/ghidra-20260927/config-callers/4204e320.{c,asm}`
identifies native `a1` data byte 1 as control/work state: `0x4204E575` loads
the byte, `0x4204E722` takes its high nibble and `0x4204E725` its low nibble.
The port is obtained separately from retained request context (`+0x15` for
context modes 2/9 at `0x4204E3EC..E3F2`, or `+4` for mode 3 at
`0x4204E408..E40B`) and supplied separately to the state parser. This does not
establish the meanings of every possible mode value.

The four-zone early-stop fixture's first `authenticated_counter_examples` row
demonstrates the distinction: its native port-4 OPEN/phase 9 receives `a1`
phase 9, result 0, state `21` (control mode 2/work mode 1). The old normalized
`frame[17] >> 4` expression yields 1, **not request port 4**. Do not use that
expression to assign ports in a generalized reply matcher. Associate the reply
with the single reserved request after route/phase/result checks, then require
independent target-port state evidence. The already-qualified local recipe is
not altered by this offline finding.

`commandPhase::decodeResultEnvelope` is a source-only shadow parser that keeps
full phase, native result and both mode nibbles separate and intentionally has
no port field. Its tests preserve the native value 6 in the historical
normalized “result 3” negative frame; no negative response becomes actuation
success. It neither matches an association nor changes any durable state.

Regression coverage in [test_valve_command_phase.py](../tests/test_valve_command_phase.py)
compiles the actual C++ builders and shadow parser. It checks all 64 phases
against both actions and existing port/body recipes, exact byte preservation
for every legacy phase, both HTV145 marker policies, stock command/retry and
historical wrap replay, invalid inputs, the port-4 reply counterexample, and
synthetic result-phase independence. Synthetic cases are encoding tests, not
new physical acceptance evidence.

This seam is not a cross-model body unification: HTV405 local port packing
differs from the retained stock multi-port commands. Preserve that distinction;
claim exact stock equality only for qualified layouts. Likewise a correct
normalized 304-bit frame is not a verified on-air packet: HTV213's independently
identified final native CRC bit requires a **305th symbol**. That waveform gate
remains separate from phase encoding, as documented in the
[two-zone command reference](../protocol_documentation/htv213frf.md).

## What remains unknown

The hub's shared allocator and HTV213's one deliberate jump do not establish a
universal receiver duplicate window, arbitrary-jump policy, report-counter
relationship, overnight reset cause or battery persistence. HTV145 phase-zero
OPEN and same-action boundary progression still lack the evidence supplied by
the new HTV213 run. HTV405 needs independent boundary frames and correlation of
both positive and negative results under a general phase builder. Shared-hub
allocation and association-local transaction matching are different concerns;
changing allocator scope needs its own durable-state design.

## Bounded qualification procedure

Use a specifically identified spare, dry valve and isolated owner, with stock
TX and schedules excluded. Use port 1 initially so the phase question is not
mixed with the unresolved local-versus-stock multi-port body mapping. This
experiment cannot qualify ports 2–4. First replay the known-good association's current
command/result bytes offline, then verify one ordinary 60-second run with
independent IQ. Do not re-pair or anchor beforehand merely to hide existing
phase state. Store the real baseline and every reserved attempt before TX.

For the action-parity question, use two sequential 60-second OPENs at adjacent
full phases, with independently confirmed completion between them. This tests
the missing same-action transition without conflating it with a large jump.
After that succeeds, a separately approved boundary test may use at most four
OPENs at `62,63,0,1`; explicitly record the initial jump and its risk. Require
matching full-phase positive replies and target-port watering/idle evidence,
plus the model's qualified completion summary where available. Halt on the
first missing, negative or ambiguous result; no phase search, automatic retry,
reset or speculative close. A user wanting connected garden hardware instead
must explicitly choose the allowed irrigation duration and recovery plan.

Passing qualifies the tested model/association/preparation, not overnight or
battery recovery. Keep proven pairing and ordinary production synchronization
intact until exact-byte replay, persistence/migration tests and the bounded
hardware result justify replacing them.

## Offline validation

### Installed-test preparation, Sep 30

The user chose installed valves and confirmed two 60-second runs on front-garden
HTV145, followed by two on vegetable-garden HTV405 Zone 1. Require independent
closure between runs; stop on missing/negative confirmation. No automatic retry,
counter jump, reset or re-pairing is authorized by this test. No commands have
been sent for this qualification.

Read-only preflight found both owners connected/authenticated on firmware 0.19.0,
both valves idle, and the Mac SDR connected and unused. These are point-in-time
checks, not lasting admission. Both garden radios require signed OTA and lack
the new full-phase capability. Existing Run-now controls cannot exercise this
experiment. The protected signing workflow currently builds default firmware
from main only; no signed experimental image is available.

`valve_phase_trial.py` is an **offline-only journal**, not a runnable experiment.
It retains a matched positive native command/result baseline; reserves exactly
two adjacent phases for port-1/60-second opens; commits attempted state before
calling a transport; and requires matching result plus independent active/idle
reports. Negative/missing confirmation blocks another open. Report phases never
reseed command state. Temporary-database tests cover both model routes, failed
commits, attempted-send restart, stale reservations, wrong owner/phase/port,
early idle and exhausted allowance. Synthetic mutations test software guards,
not receiver acceptance. Admission rejects a baseline that would place phase
zero in this two-run allowance; boundary testing needs separate authorization.

Runtime admission, single-owner exclusion, live baseline freshness, duplicate
transport handling, production-counter handback and signed firmware delivery
remain unimplemented. The journal must not be wired directly to an HTTP route
or used to bypass those requirements. The roadmap retains the runtime and live
qualification gates as incomplete.

Preparation validation: 21 focused builder/journal tests pass, the full suite
ran 855 tests with two optional skips and no failures, and the native protocol
test passes. The final phase-zero admission guard was additionally rerun through
all ten journal tests. No live deployment or watering occurred.

Sep 30: all 11 new native-builder/result-view tests pass. The complete Python
suite ran 845 tests with two optional skips and no failures; the native C++
protocol test and `git diff --check` also pass. No deployment, live database
migration, RF capture or command was performed for this audit.
