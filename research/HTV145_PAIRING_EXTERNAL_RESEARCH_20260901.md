# HTV145FRF stage-zero pairing research

Date: 2026-09-01

## Scope

This report asks one narrow question: why does the current local HTV145FRF
candidate's counter-0 assignment get rejected before the valve emits its first
addressed paired request, even though the decoded frame and measured waveform
closely match accepted stock traffic?

The source set is deliberately limited to manufacturer documentation, FCC
filings, upstream source/commit history, and this repository's controlled RF
fixtures. It does not modify runtime code or the project roadmap.

## Executive conclusion

No public source exposes an HTV145FRF pairing key, message-authentication
algorithm, or complete enrollment state machine. More importantly, the
available evidence does **not** support counter 0 being the wrong counter:
the stock gateway has accepted counter 0 and completed enrollment. Nor does it
support another blind timing, power, carrier, deviation, or static-byte tweak.

The current evidence leaves two serious classes of explanation:

1. **The decoded assignment omits a physical/framing discriminator.** A valid
   38-byte decode does not prove equivalence of preamble phase, packet boundary,
   PA ramp, any post-frame tail, or all frequency behavior across the burst.
2. **Acceptance depends on lifecycle or session context not visible as a new
   random byte.** Fresh enrollment and retained re-pairing use observably
   different assignment branches. An earlier-protocol RainPoint/Baldr family
   also has variable pairing payload and session material, establishing vendor
   precedent without proving that HTV145 uses the same design.

An explicit random nonce in the visible HTV145 assignment is currently a weaker
hypothesis: two independently reset, successful stock enrollments used the same
fresh-association constants apart from the accepted sweep counter, live clock,
and integrity trailer. The next useful discriminator is therefore the one
already identified by the local evidence: **replay one freshly accepted stock
assignment exactly under a controlled reset lifecycle before changing any more
fields.**

## Overnight engineering result

The retained raw IQ now provides a deterministic stage-zero feedback loop, not
just a decoded-fixture approximation. The analyzer recovered the stock
counter-0 request, its assignment, and the valve's addressed stage-1 request,
and therefore returned `accepted`. Against probe `.25`, the same analyzer
recovered the request and local assignment but no addressed stage-1 request,
and therefore returned `rejected_assignment_without_stage_1`. Those verdicts
agree with the independent physical and radio-node outcomes. The bounded
results, exact frames, hashes, and decision centers are retained in
[`htv145_stage0_raw_replay_differential_20260902.json`](fixtures/htv145_stage0_raw_replay_differential_20260902.json).

The repository now also has a strict preparation tool for tomorrow's replay:
[`tools/prepare_htv145_exact_replay.py`](../tools/prepare_htv145_exact_replay.py).
It refuses a rejected or uncontrolled fixture and emits an immutable 38-byte
assignment, accepted stage-1 frame, reply timing, route, selector, channel, and
trailer checks from a successful fresh stock counter-0 enrollment. It does not
enable a transmitter or alter the frozen `.25` candidate.

A second pass did find one previously hidden physical difference. Two accepted
stock assignments occupy about `31.36 ms` above the energy threshold, while
probes `.24` and `.25` occupy about `31.22 ms`; the approximately `0.13 ms`
separation persists across thresholds from 3 through 25. Sync-aligned phase
histograms also differ near the wake boundary. A stock stage-1 reply has the
same long energy duration but a different backward wake count, so it would be
premature to call this simply a “322-symbol wake.” The evidence instead raises
packet start/ending phase, PA ramp, and post-frame tail within H1. Exact values
are retained in
[`htv145_stock_local_assignment_edge_discriminator_20260902.json`](fixtures/htv145_stock_local_assignment_edge_discriminator_20260902.json).

## Verified external facts

### Pairing and reset lifecycle

The official HTV145FRF/HWG023WBRF manual defines this user flow:

- select HTV145FRF (or scan/enter its serial number), put the timer in rapid-red
  pairing mode, and only then advance the app to automatic pairing;
- a normal long press restarts the timer and enters pairing mode;
- the documented timer reset is different: remove all batteries, wait ten
  seconds, then hold the timer button while inserting four fresh AA alkaline
  cells until rapid red flashing begins;
- success is a white light held for two seconds; failure is red held for two
  seconds.

The same manual says the timer uses 433 MHz RF and should remain close to the
gateway during enrollment. Model selection is a supported path, so scanning a
per-unit serial number is not a required input to every successful pairing.
See the [official RainPoint manual, pairing pages 14-18 and reset/LED pages
45-46](https://service.rainpointonline.com/hc/en-us/article_attachments/16776664689423).
RainPoint's [official troubleshooting page](https://www.rainpointonline.com/pages/troubleshooting-faq-htv145frf-hwg040wrf-sprinkler-timer)
independently describes the timer-to-gateway link as RF and tells users to
long-press the timer until it flickers quickly before searching.

These instructions establish that “ordinary long-press re-pair” and
“battery-assisted factory reset” must remain separate test lifecycles. They do
not specify any RF packet fields.

### Radio hardware family

The FCC authorization identifies the product as a 433.7 MHz Part 15.231
transmitter with an internal antenna. The filing's model-difference declaration
says HTV145FRF, HTV347FRF, HTV405FRF, HTV447FRF, and HTV102B use the same circuit
and RF module; only the model names differ. See the [FCC filing index](https://fccid.io/2AWDBHTV145FRF),
[model-difference exhibit](https://fccid.io/2AWDBHTV145FRF/Letter/Model-Difference-8255007),
and [test report](https://fccid.io/2AWDBHTV145FRF/Test-Report/Test-Report-1-8255000).

That is useful negative evidence: because the same CC1101-based local hardware
has produced an HTV405 enrollment waveform accepted by a physical valve, a
gross “wrong radio family” explanation for HTV145 is unlikely. It does **not**
show that HTV145 and HTV405 share firmware or pairing semantics.

The FCC report labels the modulation “ASK” and reports a 183.5 kHz 20 dB
bandwidth, while the controlled HTV145 captures decode as 20 ksymbol/s FSK.
The compliance report's modulation label is therefore not precise enough to
override measured protocol evidence. The [internal-photo exhibit](https://fccid.io/2AWDBHTV145FRF/Internal-Photos/Internal-Photos-8255004)
shows a single controller board and wire antenna, but its photographs do not
identify a protocol secret or prove the absence of protected state.

### Manufacturer-derived cloud model metadata

The current upstream HomGar integration's model catalog classifies HTV145FRF as
product code 31 (`0x1f`), category 2, model code 302, and a one-port device. It
defines cloud datapoints for water control, battery, two RSSI values, working
state, alarm, event time, duration, and last usage. See the pinned
[`product_models.json` HTV145FRF entry](https://github.com/brettmeyerowitz/homeassistant-homgar/blob/7df33e67e9dbaf4a91c474c9f313575b5e76c701/custom_components/homgar/data/product_models.json#L4909-L5075).

The catalog was introduced wholesale in the integration's
[v3 decoder architecture commit](https://github.com/brettmeyerowitz/homeassistant-homgar/commit/2f8ca59).
It contains no local RF endpoint assignment, sweep-counter, subchannel,
reply-delay, packed-clock, or integrity rules. It can validate model identity
and capabilities, but it cannot produce a pairing reply.

### Evidence from the upstream rtl_433 RainPoint/Baldr family

The upstream `bresser_garden` decoder covers an older Fujian Baldr/HomGar/
RainPoint family (HTV103/HTV203 and HCS005), not HTV145. Its sync word, 33-byte
frame envelope, identifiers, and CRC are different, so its bytes must not be
ported into HTV145. See the merged [rtl_433 protocol work](https://github.com/merbanan/rtl_433/pull/3621)
and its [decoder source at the merge commit](https://github.com/merbanan/rtl_433/blob/0ab15c7/src/devices/bresser_garden.c).

It does establish relevant vendor-family precedent:

- a device identity survives a power cycle;
- a real power-up announcement differs from a later re-announcement;
- the soil-sensor announcement contains a varying session/pairing nibble;
- the gateway's pairing acknowledgement varies between captures and remains
  opaque in the decoder;
- RF communication channel can be changed as configuration;
- device and gateway counters have defined echo/wrap behavior.

Those observations make lifecycle-dependent or session-derived pairing data a
credible HTV145 hypothesis. They are an analogy only, not evidence that an
HTV145 assignment uses the same fields or algorithms.

### Firmware 126

The controlled app record identifies the test HTV145 as firmware 126, but no
manufacturer release note, public firmware image, FCC exhibit, or upstream
source found in this review maps version 126 to a pairing change. The FCC test
sample's generic “Software Version V1.0” cannot be equated to app firmware 126.
Version-specific pairing behavior therefore remains unverified.

## Verified local evidence

The following statements come from this repository's normalized captures and
fixtures, not from public documentation.

1. **Counter 0 is valid stock behavior.** With stock app search armed before
   the valve gesture, the gateway accepted the first counter-0 factory request
   and the complete six-stage enrollment succeeded. With the valve started
   first, counters 0 and 1 passed before the app searched, and stock accepted
   counter 2. The factory counter is the current sweep position, not a device
   address or RF channel. See
   [`htv145_counter0_app_first_stock_enrollment_20260901.json`](fixtures/htv145_counter0_app_first_stock_enrollment_20260901.json)
   and
   [`htv145_counter2_stock_enrollment_20260901.json`](fixtures/htv145_counter2_stock_enrollment_20260901.json).
2. **Fresh and retained association branches differ.** The two documented-reset
   stock enrollments share the same fresh-association values at normalized
   assignment offsets 19, 25, and 26 (`0x70`, `0x01`, `0x00`). A retained
   long-press pairing uses (`0xf0`, `0x02`, `0x80`). The retained capture still
   showed app Device Address 1, so offset 25 is not simply the app's address.
   See
   [`htv145_later_sweep_stock_enrollment_20260828.json`](fixtures/htv145_later_sweep_stock_enrollment_20260828.json).
3. **No obvious random field appears in two fresh stock sessions.** Their
   assignment differences are accounted for by the echoed sweep position,
   its branch bits, packed clock, and integrity trailer. This does not rule out
   an implicit bit, hidden physical discriminator, or state outside the frame.
4. **Probe `.25` closed the known static-byte and clock defects.** Its on-air
   counter-0 assignment matches accepted stock in every static byte, carries a
   valid live packed clock, uses a 320-symbol wake and the stock deviation
   family, is not clipped, and falls inside the observed stock reply-delay
   range. The valve nevertheless continued its factory sweep and never emitted
   the addressed stage-1 request. See
   [`htv145_probe25_clock_correct_rejection_20260901.json`](fixtures/htv145_probe25_clock_correct_rejection_20260901.json).
5. **Several attractive physical explanations have already been falsified.**
   Reduced transmit power eliminated SDR clipping without acceptance. Balanced
   wake analysis corrected the earlier carrier/deviation measurement error,
   and the corrected candidate still failed. Full-band energy inventory found
   no stock-only burst in the 6.82 seconds before assignment, although an
   unknown weak or unusual pre-assignment signal cannot be excluded. See
   [`htv145_probe22_reduced_power_rejection_20260901.json`](fixtures/htv145_probe22_reduced_power_rejection_20260901.json)
   and
   [`htv145_balanced_wake_phy_discriminator_20260901.json`](fixtures/htv145_balanced_wake_phy_discriminator_20260901.json).
6. **The local transmitter is capable of accepted family traffic.** A locally
   generated HTV405 enrollment was accepted despite timing farther from its
   stock reference than the HTV145 candidate. See
   [`htv405_stock_local_waveform_control_20260901.json`](fixtures/htv405_stock_local_waveform_control_20260901.json).

## What the evidence rules out

| Candidate explanation | Verdict | Reason |
|---|---|---|
| “The valve only accepts counter 3” | Ruled out | Stock accepted counter 0 and counter 2 in controlled enrollments. |
| App Device Address selects the RF branch | Ruled out | Address 1 has appeared with selector 6, and assignment offset 25 changed while app address remained 1. |
| A serial/QR scan is mandatory | Ruled out as a universal requirement | The official model-selection path does not require it. |
| The HTV405 18-stage flow should be reused | Ruled out | HTV145 stock evidence is a distinct six-stage exchange. |
| Gross reply timing mismatch | Poor hypothesis | Local timing is inside the observed accepted stock range. |
| Near-field overload / SDR clipping | Ruled out for the tested setup | Unclipped 0 dBm trial still failed at stage zero. |
| Known carrier/deviation error | Ruled out for `.25` | Corrected balanced-wake PHY still failed. |
| Incorrect evening packed time | Ruled out | `.25` carried the corrected live time and still failed. |
| A visible random nonce byte | Not supported | Two fresh stock sessions expose no unexplained random byte, but the sample is small. |

## Ranked remaining hypotheses

### H1 - decoded-byte equality is not full waveform equality

**Why it remains:** The receiver's successful decode proves data recovery, not
that every acquisition cue matches stock. The unmeasured candidates include
alternating-wake starting phase, exact boundary between wake and sync, PA
turn-on/turn-off shape, post-frame carrier/tail, short frequency transients,
and any packet-engine behavior outside the normalized 38 bytes.

Two independent accepted stock assignments are now measured about `0.13 ms`
longer than two rejected local replies at every tested energy threshold. The
stock assignments' dominant sync-aligned backward count is also two symbols
above local. Because a stock continuation has the same long energy duration
but a different backward count, the durable finding is a packet-boundary/edge
difference, not yet a confirmed wake-symbol constant.

**Prediction:** A byte-identical assignment rebuilt by the CC1101 can still
fail, while a raw replay of the accepted stock RF burst succeeds. Conversely,
if a recent stock frame replayed through the current CC1101 succeeds, the
missing discriminator is semantic/dynamic rather than analog.

### H2 - lifecycle/session context selects more than the visible fresh template

**Why it remains:** Fresh reset and retained long-press pairings have different
stock assignment branches. The older RainPoint/Baldr family also distinguishes
power-up from re-announcement and carries varying pairing material. Although
the documented reset was exercised in local trials, we have not yet classified
stock factory reset, normal re-pair, app deletion, and battery rejoin as a
complete controlled matrix.

**Prediction:** Repeated stock captures will make offsets 19/25/26 cluster by
lifecycle, or reveal another field/trailer choice correlated with the valve's
retained state. A local reply using the lifecycle-matched cluster will advance
to stage 1; a mismatched branch will leave the valve sweeping.

### H3 - the assignment contains an implicit session bit or freshness rule

**Why it remains:** The two accepted CRC residual families could carry an
implicit distinction, and the live clock is the only ordinary dynamic field in
the fresh assignment. A value can also be interpreted as both time and
freshness material without adding a separate random byte.

**Why it is not first:** `.25` uses the same residual as its accepted counter-0
reference and carries a correct current clock. Two fresh stock sessions do not
show an unexplained nonce.

**Prediction:** Exact recent-stock bytes succeed, but regenerating only the
clock/trailer fails. Several independent fresh stock counter-0 captures would
show a repeatable relationship between clock bits, request time, and residual.

### H4 - the gateway reply tracks the valve oscillator more tightly than the
current fixed node carrier

**Why it remains:** The `.25` reply-to-request offset is about 4.2 kHz lower
than the accepted counter-0 reference. This is small relative to the measured
deviation/bandwidth and is not the leading explanation, but it is a cleanly
falsifiable residual.

**Prediction:** Per-attempt AFC that transmits at the measured request center
plus the stock reply offset succeeds while the otherwise identical fixed-center
trial fails.

### H5 - a stock-only pre-assignment signal or gateway state exists outside the
known decoder

**Why it remains:** A decoder looking for the known sync cannot find a signal
with another sync/modulation, and the older vendor-family decoder itself notes
unclassified long frames and opaque pairing acknowledgements.

**Why it is lower:** The local full-band energy inventory found no stock-only
burst during the measured pre-assignment interval.

**Prediction:** Two spatially separated receivers and energy-based clustering,
without a sync filter, reveal a gateway-origin burst before accepted stock
stage zero that is absent from local attempts.

### H6 - firmware 126 has a revision-specific rule

**Why it remains:** Public sources do not document firmware 126.

**Why it is last:** All accepted and rejected captures in the current work are
from the same physical test valve, so firmware revision alone cannot explain
stock success versus local failure.

## Recommended experiment sequence

Do not modify the frozen `.25` fields before completing experiments 1 and 2.

### 1. Acquire one more fresh stock counter-0 reference

1. Use the documented battery-assisted reset exactly.
2. Keep every custom node receive-only.
3. Arm stock app search before the valve gesture so the first counter-0 request
   is eligible.
4. Record continuous raw IQ from before reset completion through the first
   routine paired report, plus app Device Address, app firmware, LED result,
   request center, assignment center, delay, and the full stock assignment.
5. Compare every normalized byte and both integrity residuals with the existing
   fresh counter-0 and counter-2 fixtures.

This either strengthens the “no visible nonce” finding or identifies a dynamic
field before another local transmit experiment.

### 2. Run the exact-replay discriminator

First validate the new accepted fixture and produce the replay manifest:

```console
python3 tools/prepare_htv145_exact_replay.py \
  research/fixtures/<fresh-stock-counter0>.json
```

The tool must succeed before those bytes are staged in the separately gated
research firmware. Do not hand-copy or regenerate the assignment. Capture the
replay itself through the SDR: “exact” still requires checking packet start,
wake-to-sync boundary, and tail against the new edge fixture, not merely the 38
decoded bytes.

Use two separate, documented-reset trials:

- **Trial 2A:** answer the first counter-0 request with the newly captured stock
  assignment bytes unchanged, as soon after capture as practical.
- **Trial 2B:** answer the first counter-0 request with `.25`, changing only the
  live packed clock and corresponding trailer.

For both, retain raw IQ and require an addressed stage-1 valve request as the
only stage-zero success signal.

Interpretation:

| 2A exact replay | 2B regenerated | Meaning |
|---|---|---|
| Pass | Fail | Clock/trailer/session derivation is wrong; diff those bytes only. |
| Pass | Pass | The former failure was lifecycle/intermittency; repeat unchanged twice. |
| Fail | Fail | Visible bytes are insufficient; move to waveform/state experiments. |
| Fail | Pass | Replay was stale or the trials were not lifecycle-equivalent; repeat with tighter controls. |

### 3. If exact bytes still fail, compare acquisition and packet edges

Measure stock and local bursts against the valve request from the same session:

- first alternating symbol polarity and exact wake-symbol count;
- wake-to-sync transition timing;
- symbol timing across the complete frame, not only its median;
- both tone centers as a function of time;
- PA amplitude ramp at burst start/end;
- carrier or data after the final trailer bit;
- request-end to first RF energy, first wake symbol, sync, and payload.

If the CC1101 cannot reproduce a discovered difference, a transmit-capable SDR
raw-IQ replay becomes justified. The existing receive-only RTL-SDR cannot run
that experiment.

### 4. Complete the lifecycle matrix with stock traffic

Capture separately, without treating them as interchangeable:

1. ordinary long-press re-pair while the association is retained;
2. battery removal/reinstallation while still registered;
3. app deletion while the valve remains powered;
4. battery restart after app deletion;
5. documented factory reset and fresh enrollment.

Classify assignment offsets 19, 25, and 26, the integrity residual, destination
route, selector, accepted sweep counter, and whether a shorter rejoin exchange
occurs. This is the path to correct rejoin support even if it is not the stage-0
root cause.

### 5. Only then test the lower-priority residuals

1. request-relative AFC reply placement;
2. energy-based stock-only pre-assignment burst search with receivers near both
   gateway and valve;
3. a second physical stock gateway or second HTV145, if one becomes available,
   to separate gateway-bound state from per-unit valve behavior.

## Tomorrow's first session

The next operator session should be deliberately short and produce one binary
answer before any new probe number is created:

1. Put all custom nodes into verified receive-only mode and start bounded Mac
   SDR recording before touching the valve. Use
   `tools/capture_rainpoint_continuous_iq.sh --duration-seconds 300 --gain 0.9`;
   it does not stop the custom local gateway.
2. Use the documented battery-assisted reset, arm stock app search first, and
   complete one fresh stock counter-0 enrollment. Record the white result and
   app Device Address.
3. Stop the stock capture and run both the stage-zero analyzer and
   `prepare_htv145_exact_replay.py`. Do not proceed if either rejects the
   fixture or if the new stock edge measurement does not reproduce the retained
   approximately `31.36 ms` burst family.
4. Power down the stock gateway, perform a second documented reset, and arm the
   separately gated local exact-replay image before initiating the valve's
   pairing gesture.
5. Count only the addressed stage-1 valve request as success. Retain the local
   assignment, factory fallback, raw IQ, node verdict, and LED result whether
   it passes or fails.

If exact replay passes, freeze stage zero twice before building stage 1. If it
fails, do not guess another byte: use the already captured stock/local windows
to separate wake start phase, sync boundary, and post-frame energy, then test
one measured edge behavior at a time.

## Freeze criteria

Stage zero should be frozen only after two consecutive trials, with identical
settings, produce the addressed stage-1 request. LED state and successful TX
completion are supporting evidence only. Once frozen, later stage work must not
change the request matcher, lifecycle profile, assignment bytes, integrity
choice, wake, carrier/deviation, scheduler, or endpoint routing.

## Source limitations

- No manufacturer protocol specification, firmware-126 release note, or public
  firmware image was found.
- FCC schematics and operational-description content are not publicly exposed
  beyond metadata in this filing.
- The HomGar integration is a cloud datapoint implementation, not a local RF
  enrollment implementation.
- The rtl_433 family is valuable comparative evidence but is not wire-compatible
  with HTV145FRF.
- FCC test-report labels are compliance metadata and conflict with the measured
  FSK captures; controlled on-air evidence remains authoritative for the local
  protocol.
