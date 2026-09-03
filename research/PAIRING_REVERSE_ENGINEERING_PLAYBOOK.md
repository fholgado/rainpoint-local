# RainPoint pairing reverse-engineering playbook

This is the repeatable method for adding another RainPoint RF device family.
It captures the lessons that made HCS026 and HTV405 enrollment reliable and
finally made the HTV145 accept a locally generated association. It is an
investigation guide, not a claim that every family uses the same transcript.

## Evidence hierarchy

Pairing progress is established only by the physical device:

1. A device-originated request for the next stage proves the previous gateway
   response was accepted.
2. Ordinary paired telemetry on the new route proves terminal enrollment.
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

## HTV145 diagnosis that established the working path

The unsuccessful approach had several independent faults:

- Early firmware reused a shared valve session and could answer more than one
  factory counter with fields from different association branches.
- Lower-carrier-only analysis hid the real upper-carrier counter-1 sweep and
  encouraged hard-coded counter assumptions.
- Valid decoded bytes, local transmit completion, and LED behavior were treated
  as stronger evidence than the valve's next packet.
- Separate-session absolute FFT estimates selected sidebands and obscured a
  response-carrier error. Some early captures were also clipped.
- A packed-clock data bit was mistaken for a static marker, wrapping evening
  hours into the morning.
- The long-wake decoder normalized events as though every frame had a
  320-symbol wake, which made the first configuration schedule appear 101.5 ms
  late.
- Nominal `2,400` wake symbols were assumed to mean a stock-length on-air
  waveform without measuring its actual duration.

The working path corrected the experimental method as much as the firmware:

1. Controlled stock captures proved first-observed factory-sweep acceptance
   and preserved complete counter-0 and counter-2 profiles.
2. A dedicated one-shot HTV145 state machine selected only the counter-2
   transcript and sent at most one assignment.
3. Balanced-wake, request-relative measurement fixed the assignment PHY and
   branch-specific packed-clock fields.
4. Two unchanged trials produced the valve's addressed stage-1 request and
   white flash, freezing stage 0.
5. Measuring stock and local stage-1 responses exposed a 30.326 kHz local
   carrier error. Correcting only that carrier eliminated all stage-1 retries.
6. The next remaining boundary became observable: local delayed configuration
   lasted 132.119 ms versus stock at 135.361 ms and did not elicit `81 50`.

This is substantial progress even though HTV145 enrollment is not finished:
the valve now responds to the custom gateway, and subsequent failures identify
a specific stage instead of collapsing into silent assignment rejection.

## Current HTV145 next test

Candidate `.4` preserves the accepted assignment and ordinary stage-1 reply.
It adds 64 expendable leading wake symbols only to the counter-2 delayed
configuration, predicting an on-air duration near the stock 135.361 ms. It is
installed on the OTA test node but has not received a physical verdict.

Success requires all three observations:

1. no repeated stage-1 request;
2. valve-originated `81 50` configuration response;
3. the next addressed stage-3 request.

If the duration matches stock but those events remain absent, revert the wake
compensation and compare configuration-specific polarity, post-frame tail, and
CC1101 long-burst termination. Do not reopen the frozen assignment or ordinary
stage-1 carrier.

## Minimum onboarding checklist for the next device

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
