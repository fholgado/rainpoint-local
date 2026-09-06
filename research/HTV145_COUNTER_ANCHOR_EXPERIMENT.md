# One-zone idle-close counter-anchor experiment

Question: does the locally paired selector-6 HTV145 accept an idle close with a
counter different from its retained command counter, and then accept an open
using that newly established counter, as the HTV405 does?

The retained-counter UI cannot answer this question: restoring a radio's saved
counter is not a valve exchange.
Status and completion gates remain in [PROJECT_ROADMAP.md](../PROJECT_ROADMAP.md).

## Controlled sequence

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
