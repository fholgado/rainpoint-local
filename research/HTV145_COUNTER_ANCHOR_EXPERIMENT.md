# One-zone idle-close counter-anchor experiment

Question: does the locally paired selector-6 HTV145 accept an idle close with a
counter different from its retained command counter, and then accept an open
using that newly established counter, as the HTV405 does?

The retained-counter UI cannot answer this question: restoring a radio's saved
counter is not a valve exchange.
Status and completion gates remain in [PROJECT_ROADMAP.md](../PROJECT_ROADMAP.md).

## Original numeric-counter sequence (superseded)

This original procedure used a numeric counter and fixed action marker. The
command-phase tests below supersede those assumptions; it is retained to explain
the earlier captures, not as an executable recovery recipe.

Use only the dry one-zone valve and its current ACK owner, with the stock gateway
off. Preserve the existing association and calibrated selector-6 packet shape.
Record radio diagnostics and independent IQ across the command/response channel.
Do not change the four-zone valve, radio owners, marker polarity, carrier,
trailer residue, wake length, or repetition timing during this comparison.

1. Snapshot fresh idle evidence and authenticated baseline counter C. At the next
   report, send an idle close with C and require a matching positive immediate
   idle response. This establishes that the packet shape and receive opportunity
   work before changing the counter.
2. At another fresh report, send the same close shape with P different from C.
   Prefer encoded counter `0x80` (five-bit zero). If C is already zero, first use
   `0x9f`; a same-counter test cannot demonstrate synchronization.
3. Only after a positive immediate idle response naming P, send one 60-second
   open with P. Require its matching watering response and independent watering
   evidence. Do not treat a routine telemetry counter or ACK as command proof.
4. At least 15 seconds after that open, close with the accepted next command
   counter. Require a matching close response and independent idle report.
   Never send another logical open after an uncertain result.

Allow one logical command per stage, using the existing bounded firmware burst
(2400-symbol wake; repeated identical frames at 0, 730 and 1670 ms). Wait at most
30 minutes for a report opportunity. Maintain at least 15 seconds between logical
commands. Preserve exact timestamps and raw frames, plus serial and independent
RF evidence; a three-second immediate-response window defines probe acceptance.

## Interpretation and follow-up

- Positive different-counter idle response plus successful open at P supports an
  idle-close anchor on this association. Repeat later with a second noncurrent
  counter, including wraparound, before calling it a general recovery mechanism.
- An explicit negative reply at P after the baseline succeeds is evidence that
  this anchor does not work under the tested conditions. Preserve its result code.
- No response is inconclusive. Stop without opening. Compare captured carrier,
  timing, wake and report-relative delivery before deciding on another trial.
- A positive close reply without the subsequent open does not establish usable
  synchronization. Log it as partial evidence, not success.

## Execution boundary

`tools/prepare_htv145_counter_anchor.py` produces exact candidate packets and
conditional stages from the live association and readiness snapshot. It is
preparation only and has no transmitter. The current runtime suppresses idle
closes and only permits its authenticated counter; do not bypass these checks by
labelling the experimental counter authenticated or reusing old exchange frames.

Before live execution, add an isolated dry-trial reservation that distinguishes
the probe counter from the authoritative counter, and a bounded report-triggered
firmware send compiled out of production. Reserve and invalidate gateway counter
certainty before a different-counter frame can leave the radio. Block concurrent
UI commands; maintain single-owner report ACKs. Positive matching evidence alone
may restore counter certainty. A restart, capture loss, timeout, foreign command,
or unexpected watering ends the trial without speculative counter restoration.
Any later open needs a new evidence-based recovery if this trial is inconclusive.

## September 6, 2026 result

The dry baseline close at retained counter `0x83` received an explicit result-3
reply at 14:55:46 UTC. Independent RTL-SDR IQ decoded the same close and response
as the radio diagnostics, both with residue `4f03`. The decoder timestamps for the close and reply were about 375 ms apart. The result code's precise
meaning remains unknown. This establishes RF reception and a negative command
exchange, not counter authentication.

The runner stopped at the baseline gate: **no different-counter close and no
open were sent**. Thus the HTV405-style anchor remains unproven on HTV145. The
retained counter was invalidated and must not be restored from the pre-trial
snapshot after this actual RF rejection. A future comparison needs a newly
verified positive baseline and investigation of why the retained baseline failed.

Two preceding setup attempts emitted no RF: the first lacked an authenticated
probe capability; the second reached the node before its saved profile was
restored. An exact, non-transmitting rejection allowed recovery of that second
attempt's pre-test state. Neither is valve evidence, and that recovery does not
apply to the subsequent result-3 exchange.

Temporary probe reservations, capability, API actions and firmware paths were
removed after this trial. Clean candidate `0.15.16-htv145-control.1` retains the
normal command and report-ACK behavior. Raw IQ, serial logs, runner and exact
experimental source patch remain in the untracked September 6 capture output.
The redacted minimal exchange is
`fixtures/htv145_counter_anchor_baseline_negative_20260906.json`; its regression
requires that result 3 cannot authenticate the anchor. RTL-SDR used automatic
gain at 1 Msps, centered on 434.350 MHz; this is command-channel evidence.

Cleanup validation: 451 Python tests passed (two optional skips), native C++
protocol tests passed, and clean production/candidate PlatformIO builds passed.
The clean one-zone OTA image was health-confirmed; the owner is configured with
no pending command and no authenticated counter. Gateway 0.34.7 projects
Recovery required with retained restoration disabled. The four-zone owner
remains on 0.15.14, synchronized and idle, with its morning schedule enabled.

## Fresh baseline later on September 6

After a new user-assisted pairing gesture, the clean radio again recorded the
accepted counter-2 selector-6 prefix with five of six steps. Gateway completion
evidence is distinct from a complete six-step RF transcript; the operator LED
result was not recorded for this attempt.

An isolated one-shot trial sent a 60-second open with explicitly **unverified**
first-command counter `0x81`. The valve's matching positive response established
next counter `0x82`. An active close at `0x82`, about 20 seconds later, received a
matching positive idle response, followed by independent idle telemetry at
15:53:23 UTC. Independent IQ recovered both commands and both replies; the
open reply used residue `c713`, the close reply `4f03`. Command wakes clustered
at 2,399/2,401 symbols, consistent with the intended 2,400-symbol recipe.

This establishes a fresh operational command baseline, not an idle-close anchor.
The earlier successful close was active; the rejected earlier baseline was idle.
That state difference is now an explicit discriminator for the next comparison,
not a reason to interpret result 3 as a counter-specific rejection. A future
idle/different-counter trial must preserve this distinction and stop on uncertainty.

The temporary bootstrap permit, HTTP actions and firmware command were removed
again after this one open. Clean gateway 0.34.9 / candidate
`0.15.19-htv145-control.1` retain the normal command and owner-revocation paths.
Evidence: `fixtures/htv145_fresh_pairing_control_baseline_20260906.json`.

Cleanup verification: 454 Python tests passed (two optional skips), the native
protocol test passed, and clean production/research builds passed. After the
clean OTA and gateway restart, the one-zone owner was configured, counter
authenticated at `0x82`, idle and ready with no pending command. The four-zone
valve remained idle and synchronized with its morning schedule enabled.

## Repeated idle close and command-phase evidence

The subsequent one-shot idle-close test sent exactly the previously accepted
active-close frame: counter `0x82`, marker `0x10`, close body and residue `4f03`.
The valve returned result 3, independently decoded from IQ. The runner stopped:
no counter-zero probe and no open followed. The normal uncertainty rule cleared
counter authentication; no saved counter was restored after this rejection.
The temporary gateway route was removed in 0.34.10; firmware stayed on clean
candidate `0.15.19-htv145-control.1`.

Comparing the original stock command frames reveals a confound in the earlier
idle-state interpretation. The five accepted commands progress as:

| Action | Counter / marker | Combined phase |
|---|---|---|
| Open | `81/90` | 3 |
| Open | `82/10` | 4 |
| Close | `82/90` | 5 |
| Open | `83/10` | 6 |
| Close | `83/90` | 7 |

The raw marker's high bit alternates even on consecutive opens. Treating it as
a fixed pairing/action polarity loses this progression. A candidate six-bit
command phase is `((counter & 0x1f) << 1) | (marker >> 7)`. The fresh local
open/close pair used phases 3 and 4; the rejected idle close repeated phase 4.
Its next-phase close would keep counter `0x82`, change marker to `0x90`, and
recompute the trailer. This is prepared offline only. It has not been transmitted
or used to authenticate runtime state. Wraparound and counter-zero anchoring
also remain unqualified.

This evidence supports a duplicate-phase explanation, but the exact meaning of
result 3 and the next-phase idle close still need a controlled physical test.
Do not conclude that idle closes are categorically unsupported, or that the
valve forgot its association. `tools/analyze_htv145_command_phase.py` reads the
stock fixture and checks this sequence; the regression also compares the exact
accepted and rejected close bytes. Evidence:
`fixtures/htv145_repeated_idle_close_rejection_20260906.json`.

Cleanup validation: 455 Python tests passed (two optional skips), and the native
protocol test passed. No firmware change was needed for this trial. The clean
gateway removes the temporary route, leaves counter authentication false after
result 3, and preserves the existing single ACK owner and idle telemetry.


## Next-phase and fixed-zero idle-close comparison, September 6

With the same selector-6 association, ACK owner, carrier, residue and 2,400-symbol
wake, a report-triggered phase-5 close (`82/90`) received result 3 at 17:17 UTC.
Subsequent close-only probes at phase 6 (`83/10`), phase 0 (`80/10`) and phase 1
(`80/90`) also received result 3. Independent IQ recovered every request and
negative reply. Thus neither the predicted next phase nor either zero-counter
marker established an idle-close anchor. These replies do not establish whether
rejected commands advance state, or whether the valve rejects closes while idle.

The phase-5/phase-1 replies use marker `d0`, which the original strict negative
reply decoder omitted. The radio heard CRC-valid matching-route frames but called
that an unclassified response timeout. The new redacted fixture
`fixtures/htv145_next_phase_idle_close_rejection_20260906.json` reproduces the gap;
both Python and native decoders now recognize the captured negative family with
either marker, without treating it as positive state or counter evidence.

The next isolated discriminator is a single 60-second dry open at phase 5,
predicted from the last positively accepted phase-4 close. This is explicitly an
assumed phase, not synchronization. A durable one-use permit is consumed before
dispatch; restart cannot replay the opening. Ordinary controls remain blocked.
Only a direct matching positive reply permits follow-up phase control. If accepted,
compare an active close at deliberately different phase 0 with the expected phase-6
close, spaced at least 15 seconds apart and within the original timer. A successful
phase-0 close must be followed by a positively acknowledged phase-1 bounded open,
phase-2 early close and independent idle before claiming usable active recovery.
A negative or unanswered opening ends this discriminator without another opening.


## Active recovery and rollover results

The phase-5 assumed open received a positive immediate reply at 17:30:48 UTC,
then independent watering telemetry. An active phase-0 close succeeded at
17:31:11, despite the identical phase-0 idle close having returned result 3.
The phase-1 open and phase-2 early close both succeeded with subsequent
independent watering and idle reports. This proves usable active recovery on
this unchanged association; the earlier rejected closes did not prevent the
predicted phase-5 open.

A second sequence accepted phase-3 open, deliberately different phase-62 close,
phase-63 open and phase-0 close across rollover. All eight positive request/reply
pairs from both trials were independently recovered from low-gain command-channel
IQ. Every stage has a subsequent matching independent state report. The redacted
fixture is `fixtures/htv145_active_counter_recovery_20260906.json`.

The proven distinction is operational: the tested arbitrary anchors are accepted
while watering and rejected while idle. This does not establish the meaning of
all result-3 responses or prove that all 64 phases are interchangeable. Neither
ordinary reports nor their ACKs authorize a guessed command counter. A daily
one-zone idle-close synchronization, like the four-zone method, is unsupported
by this evidence; do not introduce unwanted watering merely to synchronize.

The gateway adopted the final positive phase-0 close from its own persisted RF
event, after validating the matching command and subsequent idle. The temporary
handoff rejected stale/nonlatest/negative replies and sent no RF. Normal next
numeric counter is `0x80`, with the existing qualified open marker. Cleanup
removes phase probes, the durable assumed-open permit and the handoff action;
the matching positive exchange replaces the consumed experimental permit in
persistent state. Release 0.34.11 and clean candidate 0.15.22 retain only the
negative-marker diagnostic fix and regression evidence.


After clean gateway 0.34.11 and candidate 0.15.22 deployment, a normal 60-second
open at numeric counter `0x80` and early close at `0x81` both received matching
positive replies and subsequent independent watering/idle telemetry. The gateway
retained synchronized next counter `0x81`. The first preflight attempt sent no
command because the external SDR had disappeared from USB enumeration. The
successful clean-runtime check used the radio's received RF frames and separate
valve state reports; unlike the eight recovery exchanges above, it has no
independent SDR capture.


## Idle result-3 anchors followed by operational proof (September 6, 18:20 UTC)

The later follow-up overturned the active-only conclusion above. On the unchanged
association, a fresh independent idle report was followed by close phase 0
(`80/10`). It returned result 3, but the subsequent phase-1 bounded open and
phase-2 early close both received positive replies and independent state reports.
A second idle close at phase 62 (`9f/10`) also returned result 3; phase-63 open
and phase-0 early close then succeeded across rollover. Thus an idle result-3
reply does not by itself show that the requested counter was rejected.

These two operational sequences qualify a non-watering fixed-zero counter anchor
on this specimen. They do not establish result 3's meaning for all commands. The
production-facing candidate accepts only the captured zero-anchor response:
ordinary trailer and association route, byte 13 `80`, byte 14 `50`, and either a
positive idle reply or the exact result-3 body with byte 17 `10`. It must match a
durable `idle_anchor` reservation triggered by a new independent idle report from
the assigned ACK owner. The gateway accepts it within 3.5 seconds; the radio's RF
window is 3 seconds. Result 3 remains an error outside that narrow context and
never supplies physical-state evidence. Store its frame separately from the last
independent state observation. Reports and summary ACKs never seed the counter.

`fixtures/htv145_idle_result3_counter_recovery_20260906.json` preserves all six
physical replies and the subsequent watering/idle reports. Each reply was also
present in the gateway's durable RF event log. The external SDR was unavailable
for these trials; there is no new independent IQ capture. All six transmitted
command frames exactly match commands independently IQ-decoded in the preceding
active-recovery fixture. Preserve both evidence sources and their distinct scope.

Gateway 0.34.12 and candidate 0.15.24 implement explicit close-only synchronization:
queue a bounded wait, require a new owner-received idle report, reserve before
transmitting, send the fixed zero close, and authenticate only a matching anchor
reply. The next normal open uses `80/90`. A missing/late reply or new watering
report leaves the counter unknown; restart never replays a transmitted anchor.
The optional local-calendar morning policy is disabled by default, claims at most
one attempt per date, and skips missed windows. It never opens a valve to sync.
Temporary arbitrary-phase and assumed-open experiment commands are removed.


### Clean runtime verification

On gateway 0.34.12 and OTA-confirmed candidate 0.15.24, an explicit Sync counter
request at 19:03:19 UTC began with the gateway counter unknown. The owner's new
idle report at 19:08:37.928 triggered the fixed zero close. Its exact result-3
response at 19:08:38.444 authenticated counter `0x80` without claiming a physical
state change. A normal bounded open at `0x80` received a positive reply at
19:08:58.761 and independent watering at 19:09:04.784. The early close at `0x81`
received a positive reply at 19:09:19.167 and independent idle at 19:09:25.480.
The valve finished idle with synchronized next numeric counter `0x81`.

The redacted fixture's `runtime_verification` section preserves these replies and
independent state frames. This is node/gateway RF evidence, not a new SDR capture.
The installation's close-only morning policy was enabled for 05:30–06:00 Eastern;
the reusable default remains disabled. The four-zone policy was not modified.

Validation: the complete CI Python suite passed 467 tests (two optional skips),
followed by targeted migration/spacing/dispatch-failure checks and 122 API/UI tests
after the final one-zone registry projection fix. The native protocol test and
both production/candidate firmware builds passed. Production excludes the new
HTV145 opcode; the candidate contains no phase/bootstrap/handoff experiment path.


A final gateway rebuild preserved next counter `0x81`, radio authentication,
independent idle, and the enabled morning policy without another actuator
command. Both one-zone catalog aliases now project the same Ready sync state;
four-zone defaults no longer overwrite registered HTV145 devices. The existing
four-zone schedule remained Ready at 05:30 Eastern.
