# One-zone idle-close counter-anchor experiment

Question: does the locally paired selector-6 HTV145 accept an idle close with a
counter different from its retained command counter, and then accept an open
using that newly established counter, as the HTV405 does?

The current retained-counter UI work is paused before deployment. It cannot
answer this question: restoring a radio's saved counter is not a valve exchange.
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
