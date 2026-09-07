# RainPoint pairing reverse-engineering playbook

This is the repeatable method for adding another RainPoint RF device family.
It captures the lessons that made HCS026 and HTV405 enrollment reliable and
finally made the HTV145 accept a locally generated association. It is an
investigation guide, not a claim that every family uses the same transcript.

## Evidence hierarchy

Pairing progress is established only by the physical device:

1. A device-originated request for the next stage proves the previous gateway
   response was accepted.
2. Ordinary paired telemetry proves the assigned route is in use; distinguish
   operational association from completion of every stock enrollment row.
3. An authenticated control response additionally proves command authority for
   a valve.
4. An app result or distinctive LED is useful corroboration.
5. A locally transmitted frame, decoder match, or gateway log proves only what
   the custom node attempted.

For HTV145, the white flash is the hardest and most valuable breakpoint. It
corresponds to acceptance of the initial association and is followed by an
addressed stage-1 request. It does **not** prove the delayed configuration or
remaining stages completed.

## Keep lifecycle paths separate

Do not use one state machine for these distinct operations:

- fresh enrollment from a factory endpoint;
- retained-association rejoin after a battery change or dormant period;
- routine telemetry acknowledgement;
- authenticated valve control and command-counter synchronization.

Likewise, do not share a continuation table between product families. HCS026
uses a short sensor exchange, HTV405 uses an 18-stage valve exchange, and
HTV145 uses a six-stage exchange with an unsolicited delayed long-wake
configuration transmission. Common framing does not imply a common pairing
transcript.

## Capture the reference before transmitting

For a new family, make two complete stock-gateway captures with fresh
batteries and only one gateway able to transmit:

1. Arm the stock gateway first, then initiate pairing on the device. This
   normally captures acceptance of the first factory announcement.
2. Initiate pairing on the device first, then arm the stock gateway. This
   exposes the factory sweep and shows whether the accepted counter merely
   reflects when the gateway began listening.

Keep recording through the first ordinary report. Record the model, device
ID, app Device Address, LED result, action ordering, and battery state. Use the
Mac-attached SDR at 2.0 Msps around 433.7 MHz so lower, upper-sweep, and assigned
response carriers remain visible while the Home Assistant gateway stays live.

Before trusting the capture:

- verify the stock and custom gateways were never transmitting together;
- avoid ADC clipping and retain the original IQ;
- inventory the full band for unframed energy as well as decoded packets;
- preserve a checksummed, bounded window around the exchange.

## Derive one coherent profile

Build a chronological transcript that records, for every device request and
gateway response:

- endpoints and complete normalized frame;
- request counter and message signature;
- request, assignment, and response carriers;
- response delay measured from a clearly named request boundary;
- wake length, symbol rate, FSK deviation, post-frame tail, and active duration;
- integrity residue and dynamic clock/date fields;
- device evidence that proves the response was accepted.

Treat a captured counter/selector/carrier combination as one branch. Never
splice a selector from one stock run, timing from another branch, and payload
from a different model. Pairing counters are sweep or transcript state; they
are not the app Device Address or a unique RF channel.

Absolute SDR frequency differs between sessions. Compare a gateway response
relative to the device's own request oscillator in the same capture. Measure
the alternating wake with balanced low/high FSK tones; a free-running FFT can
lock to a data-dependent sideband and report a convincing but wrong center.

## Implement with frozen stage gates

Create a model-specific, research-gated profile and progress in this order:

1. **Stage 0:** send one assignment for the selected branch. Pass only when the
   device sends the addressed next-stage request.
2. Repeat stage 0 unchanged. After two passes, freeze its request matcher,
   payload builder, endpoints, carrier, deviation, wake, timing, clock fields,
   trailer, and post-frame behavior.
3. Add only the next response. Pass when the device advances. Repeat unchanged
   before freezing that boundary.
4. Continue one stage at a time through terminal paired telemetry.
5. Validate the same final image three consecutive times before advertising
   support.
6. Test removal/re-pair, battery rejoin, routine ACKs, coexistence, and valve
   control as separate lifecycle gates.

Every candidate must have a unique firmware version, a capture, a redacted
fixture, and a one-sentence single-variable hypothesis. A later-stage change
must not modify a frozen prefix. CI should compile the research branch and
test its canonical frame table without enabling it in production.

## Failure interpretation

Use the device's next action to classify a failure:

| Observation | Interpretation | Next comparison |
|---|---|---|
| Factory sweep continues; no addressed request | Assignment rejected | Exact branch, endpoints, clock fields, assignment PHY |
| Same addressed request repeats | Immediate response rejected | Response carrier/deviation, timing, bytes, tail |
| Immediate request stops, but expected configuration response is absent | Ordinary response likely accepted; delayed configuration rejected | Long-burst start, on-air duration, wake transitions, carrier |
| Terminal telemetry absent after final stage | Enrollment not proven | Final reply and routine receive/ACK route |
| LED/app succeeds but no paired traffic | Supporting UI evidence only | Retain capture and wait for device-originated proof |

Do not respond to failure with several small parameter changes. Rank
hypotheses, state what each predicts, change one discriminator, and revert it
if the predicted boundary does not move.

## Separate pairing, operation, ACKs, and counter recovery

A valve can accept commands on a partial association. Record terminal enrollment
and operational acceptance as separate verdicts; do not use a white LED or local
TX success to claim either. Keep the accepted prefix frozen while investigating
its final stage. Match each result to the current trial's command ID and time.

After an authorized dry pairing trial, capture a bounded open with its matching
reply and independent watering, then automatic idle. Use a second bounded run to
check early close after command spacing. Retain negative results and interrupted
trials; a later success does not erase them.

Capture routine reports and session summaries with their ACKs. Repeated summaries
can belong to a previous run and cannot prove current idle or authenticate a
counter. Distinguish node TX completion from on-air waveform validation and
subsequent device behavior. Keep raw IQ bounded rather than recording it all night.

For restart trials, wait for a changed connection epoch, cleared reboot-pending
state, and restored configuration before submitting a new command. A still-open
old socket is not proof that a rebooted radio has returned.

For explicit counter recovery, use the family's qualified sync API. Wait for the
required owner report and exact response; never infer a counter from telemetry.
Follow recovery with dry bounded control only as a separate authorized test.
Routine daily synchronization must never add watering. Persist attempt budgets,
original deadlines, command IDs, and outcomes across interruptions.

Current byte/timing rules belong in the [device references](../protocol_documentation/),
not in this procedure. Dated findings belong in fixtures and the capture journal.

## Checklist for one device-onboarding operation

- [ ] Record two complete stock pairings with opposite gateway/device arming
      order.
- [ ] Retain app metadata, LED behavior, IQ, checksums, and the first routine
      report.
- [ ] Inventory all observed carriers and unframed RF energy.
- [ ] Generate one model-specific canonical transcript and fixture.
- [ ] Implement one assignment only; no cross-family fall-through.
- [ ] Prove and repeat each boundary before freezing it.
- [ ] Require terminal telemetry; for valves, also require authenticated
      control response.
- [ ] Test retained rejoin, battery change, ACK liveness, coexistence, removal,
      and HA identity after new enrollment is stable.
