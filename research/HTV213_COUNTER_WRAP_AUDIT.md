# HTV213 master-counter wrap audit

2026-09-30. Offline audit of retained stock application images, bounded private
disassembly, redacted RF fixtures and current local source. No RF, hardware,
network, deployment or live-state changes. Project gates remain in the
[roadmap](../PROJECT_ROADMAP.md).

## Result and confidence

**High-confidence static result:** the stock master generator emits
`1..63,0,1..`, not `1..63,1..`. **Capture result:** HTV213 device reports have
been observed at `63` followed by `1`, with matching report ACKs. These are
independent directions; neither report wrap nor the gateway's generator proves
HTV213 acceptance of master command `21` at phase zero. The subsequent bounded
local experiment below qualifies that boundary for one association; it does not
turn report-counter observations into master-counter evidence.

### Primary firmware evidence

The private stock bundle is
`captures/stock-hub-firmware/2026-09-27-adzoj0e3/`. Its analysis artifacts below
remain private; no firmware bytes or disassembly are reproduced here.

| Evidence | Qualified interpretation |
| --- | --- |
| `analysis/valve-state-20260927/sequence_generator.txt`, `0x42037920..0x42037943` | Loads the one byte at `0x3FCA710F`; increments/stores it; compares **the old value** with 63; replaces the stored value with 1 only when the old value exceeds 63. Therefore old 63 returns 64, and old 64 returns 1. |
| `analysis/valve-state-20260927/master_internal_header.txt`, `0x4203A435..0x4203A447` | Calls that generator and masks the returned value to six bits before placing it in native payload byte 9. Returned 64 becomes **wire phase 0**. |
| `analysis/valve-state-20260927/actuator_header.txt`, `0x420500E2..0x420500E7` | Actual actuator command `0x21` calls this master-header builder. This is not merely an unrelated diagnostic counter. |
| `analysis/version-lifecycle-20260927/ota0-counter.asm`, `0x42036190..0x420361B3`; `ota1-counter.asm`, `0x42037920..0x42037943` | The same generator body occurs in 1.1.1032 and 1.1.1040. Only the three PC-relative literal-load displacement operands differ; every resolved literal names `0x3FCA710F`. |

This audit independently parsed both original application images' load segments,
verified their SHA-256 values against the saved version-comparison manifest,
found exactly one matched 36-byte generator body per image after masking only
the six literal-displacement bytes, and resolved all six literals. Bounded
instruction inspection, not pattern matching alone, establishes the old-value
comparison and serializer mask. This confirms the earlier
[sequence trace](STOCK_HUB_VALVE_STATE_TRACE.md#3-counter-generation-a-global-six-bit-header-field)
and [version comparison](STOCK_HUB_VERSION_COMPARISON.md).

The generator addresses a **single shared hub byte**, with no association,
device or port index. Consequently these stock master-header calls are not
allocated independently per valve. That does not establish that every possible
hub transmission consumes a phase: report replies echo request phases, retries
reuse the already built packet, and other paths can consume a generated value
without emitting it unchanged. A gap at one valve therefore need not mean a
lost command to that valve. See the bounded call/reply/retry evidence in the
[sequence trace](STOCK_HUB_VALVE_STATE_TRACE.md#4-retries-reuse-the-packet-acks-match-a-tuple).
Global generation makes a universal strict-next-per-valve rule doubtful, but
does **not** prove arbitrary phase jumps are accepted by HTV213.

### Primary capture evidence

Re-decoding native `P[9] & 63` directly from retained normalized fixture bytes
produced these results; times are fixture-relative seconds:

| Artifact | Master `21/a1` | Device `02/82` boundary |
| --- | --- | --- |
| [Local 300-second run](fixtures/htv213_local_ha_auto300_20260930.json) | Phase 7 at 0.000000 / 0.309072 | Phase 63 at 124.074129 / 124.155133; phase 1 at 144.006822 / 144.087271 |
| [Stock lifecycle](fixtures/htv213_stock_lifecycle_20260928.json), `quiet3h` | Phase 8 at 20.105283 / 20.418206 | Phase 63 at 158.970994 / 159.045662; phase 1 at 179.304944 / 179.375945 |

No phase-zero report is present in these selected fixtures. They establish the
observed report transition and correct echoed ACKs, not complete reception of
every possible packet or the valve firmware's exact report-generator algorithm.
Most importantly, neither boundary contains a master `21` at 63, 0 or 1.
The same stock lifecycle fixture's `hub_restart` accepts master phase 3 after
startup notification `20/a0` at phase 2; this is a different precondition, not
evidence that resetting our journal or issuing a notification enables wrap.

## Receiver behavior not established by hub decompilation

The retained firmware is the **hub**, not the valve. It cannot establish the
valve's command duplicate window, whether zero is accepted, whether phases are
tracked per controller/device/port/command family, the effect of delayed old
requests, or persistence across valve batteries. Positive command ACKs must be
matched on association, command and all six phase bits; accepted command state
and subsequent target-port idle/elapsed summary remain separate observations.
Neither missing ACK nor a source-level modulo operation is acceptance evidence.

## Subsequent authorized local RF result

The user approved the proposed maximum-four-command dry trial. All four
port-1 60-second opens completed, with no retransmission, close, re-pair or
restart between steps. Independent IQ decode found matching `21/a1`, target
watering/idle, elapsed-60 `04`, and report ACKs for each phase. The genuine
starting next phase was 9; the explicit probe recorded the jump to 62 rather
than fabricating an acknowledged seed. The final next phase is 2.

| Master phase | Positive ACK | Idle | Summary |
| --- | --- | --- | --- |
| 62 | +0.310 s | +62.428 s | +69.427 s |
| 63 | +0.310 s | +62.530 s | +66.481 s |
| 0 | +0.308 s | +63.038 s | +73.086 s |
| 1 | +0.309 s | +62.635 s | +66.683 s |

Times are from command sync, not measured hydraulic flow. Source: private
`captures/htv213-local-control-20260930/20260930-151121/boundary-*-{command,finish}.jsonl`
and the [34-frame redacted fixture](fixtures/htv213_local_counter_boundary_20260930.json).
These are selected command/completion windows, not a complete intervening
traffic ledger. One phase-zero scan chunk had approximately 1.04% clipped IQ
components; all required frames and CRCs were recovered. Do not infer silence
from uncaptured windows or make general saturation claims.

This proves the tested receiver accepts the boundary and the initial deliberate
jump. It does not prove arbitrary jumps, duplicate aging, zero on other models,
multi-device allocator equivalence or battery-reset behavior. The gateway now
allows modulo-64 allocation only for associations whose durable boundary audit
records all four completed steps. Unqualified associations still stop before
wrap; uncertainty never frees a phase for retry.

## Bounded dry boundary experiment, not a recovery policy

An explicitly authorized, isolated dry test can avoid 55 intervening opens by
testing a **single deliberate phase jump** followed by the actual boundary.
Preserve the current association and genuine journal history; do not fabricate
an acknowledged seed, reset the hub/valve, re-pair, or change configuration to
make the jump look established. Production builds and the normal wrap gate
remain unchanged. This needs a separately reviewed, compiled-out experiment
with a durable one-shot phase reservation, not manual database editing.

One conservative bounded sequence is master phases **62, 63, 0, 1**, each a
60-second command on the same explicitly selected dry port, no concurrent
commands, no scheduled watering, and stock-hub TX excluded. The first jump from
the currently confirmed phase to 62 is itself the first hypothesis under test.
Advance only after that command has a matching positive `a1`, target-port idle
and qualified elapsed summary; require the same evidence before each following
command. Capture the emitted waveform, including the final native CRC symbol,
and both command/result and report/ACK traffic. At most four opens are admitted;
there is no retry loop, alternate-phase search or automatic close. Any missing,
negative or ambiguous result halts the trial with its phase reservation intact;
allow the requested duration to expire and retain observation-only ownership.

If the first jump fails, there is **no wrap result** and no permission to guess
another phase. If all four succeed, the result qualifies `62→63→0→1` for that
association, port and preparation, including command phase zero; it does not
prove all arbitrary jumps, all ports, reboot recovery, or a naturally traversed
full cycle. A complete naturally generated stock cycle or a separately proven
non-actuating stock master request remains stronger corroboration. Do not invent
idle-close or notification traffic to consume phases: their non-actuating and
receiver-state effects have not been established by this audit.

## Source implications

The existing [HTV213 protocol note](../protocol_documentation/htv213frf.md) is
correct to separate report wrap from the command gate. Make the eventual master
wrap candidate explicitly **63→0→1**, never 63→1 based on reports. Add offline
serializer/result-correlation cases for phases 62, 63, 0 and 1, while retaining
the normal journal's fail-closed behavior until physical qualification. Such
tests prove encoding and bookkeeping only.

[`ControlJournal`](../rainpointd_addon/rainpointd/htv213_control_trial.py) currently
keys records by `controller:valve` and retains the above-63 guard for unqualified
associations. Only a completed boundary audit enables modulo-64 allocation.
This is an association-local experimental policy, **not the stock allocator
contract**. Before claiming stock-compatible multi-device
allocation, review a controller-scoped durable allocator spanning relevant
master builders, while keeping association-specific transaction matching and
echoed report replies separate. Do not silently change allocation scope or
remove the wrap guard on the strength of disassembly alone. A dedicated dry
probe must record the intentional jump as such and consume every attempted
phase durably, including uncertain attempts; normal recovery must never reseed
from report phases or retry a previous open after restart.
