# HTV145FRF single-zone valve protocol

The `HTV145FRF` is a single-zone valve with a pairing and command protocol
distinct from the HTV405. Receive-side telemetry, duration, water usage, and
categorical battery state are decoded. Local enrollment remains research-only:
the valve accepts the local association, delayed configuration, and following
continuation through the stage-4 request. The terminal stage remains unproven.
On September 5, the unchanged `.22` candidate nevertheless supported two
positively acknowledged dry opens, an automatic stop and a positively
acknowledged early close on one 5/6 association. Step 6 is not required for those
observed controls. Durable runtime counters and the report ACK cycle remain
separate integration work.

## Identity

| Property | Definition |
|---|---|
| Factory endpoint suffix | `8f` |
| Factory-derived paired route | Factory endpoint with `0x80` set in its first byte |
| Logical zones | One |
| App model | `HTV145FRF` |

The factory-derived route becomes the controller side of accepted stock
commands. The association also contains a valve route and companion endpoint;
the companion is commonly the valve route with its first-byte high bit
cleared. Endpoint A and endpoint B change roles between enrollment, commands,
and responses and must not be interpreted as fixed source and destination
fields.

## Stock new-enrollment transcript

The accepted stock association is a six-stage exchange with one delayed
configuration transmission between stages 1 and 2:

| Stage | Valve request body prefix | Stock gateway behavior |
|---:|---|---|
| 0 | `80 80 84 02 ff 8f 97` | Assignment to companion, selector 5, about 50.55 ms |
| 1 | `81 01 07 82 25` | Reply `81 41 01`, about 50.40 ms |
| 1a | no request | Selector-5 branch: long-wake config `81 90 01 01` to valve route; selector-6 counter-0/counter-2 branches use `81 10 01 01`. The counter-2 branch uses a 2,400-symbol stock wake about 2,952.55 ms after the normalized stage-1 request end |
| 2 | `81 d0 00 80` | Observe only |
| 3 | `81 82 81 02` | Reply `81 c2 87 80 2c 01 05`, about 50.70 ms |
| 4 | `82 03 01 82` | Reply `82 43 00 80`, about 53.35 ms |
| 5 | `82 ac 80 99` | Reply `82 ec 81 80 19`, about 45.05 ms |

Stage 1a uses the 2,400-symbol stock wake-up form; the remaining replies use
the 320-symbol form. The stage-2 response moves to the response carrier
selected by the association. Exact captured endpoints, clocks, trailers, and
complete bodies are retained in the HTV145 pairing fixtures and the
table-driven candidate in `valve_pairing_protocol.py`.

A second accepted stock association used counter `3`, selector `6`, and a
routine carrier near 434.461993 MHz. Its request counters progressed
`3, 4, 4, 5, 5`; its delayed configuration used `81 10` to `81 50` and arrived
about 3.630 seconds after stage 1. The first four replies used residue `0xc713`
and the last used `0x4f03`.

A fresh reset followed by button-first/app-second enrollment exposed a third
accepted branch. The valve transmitted factory counters `0`, `1`, and `2` at
approximately 126.585, 128.087, and 132.085 seconds. Counters `0` and `2` used
the 433.143 MHz request carrier; counter `1` used a separate carrier near
434.306 MHz. The gateway accepted counter `2`, selected selector `6` with its
channel high flag clear, and therefore assigned response subchannel `12`:

```text
channel = 2 * selector + high_flag = 2 * 6 + 0 = 12
center = 433.0315 MHz + channel * 110 kHz = 434.3515 MHz
```

Valve stages 1 and 3--5 remained on the lower request carrier. Gateway replies,
the delayed stage 1a configuration, and the valve's stage-2 response used the
assigned 434.3515 MHz carrier. The complete branch finished successfully in the
stock app. Counter `1` is consequently a real upper-carrier factory sweep
announcement, not an absent value or a paired continuation.

A controlled app-first/button-second enrollment then accepted the first new
factory announcement, counter `0`, after 52.15 ms. The earlier
button-first/app-second trial accepted counter `2` only after counters `0` and
`1` had passed before the app entered search. Both trials selected selector
`6`, response subchannel `12`, and the same six-stage exchange family. In these
controlled trials the accepted counter is therefore the current factory-sweep
position echoed at assignment time; it is not the app Device Address or the
assigned RF subchannel. A local enrollment candidate should respond to the
first supported factory announcement it observes after arming rather than
wait for a hard-coded counter.

These are complete association profiles, not interchangeable parameter
choices. The app Device Address does not identify the selector: an app address
of `1` has been observed with selector `6`.

## Local enrollment status

The current research candidate uses the coherent stock counter-2/selector-6
branch. It deliberately ignores counter 0 and counter 1, sends exactly one
assignment at counter 2, and never mixes HTV405 or counter-0 continuation
fields into the session.

The following boundaries are physically established:

| Boundary | Device-originated evidence | Status |
|---|---|---|
| Stage 0 assignment | Valve sends its addressed stage-1 request; white LED follows | Accepted in two unchanged trials; frozen |
| Ordinary stage-1 reply and delayed stage-1a configuration | Valve emits `81 50`, then its addressed stage-3 request | Accepted twice unchanged with `.10`; frozen |
| Stage-3 reply | Valve sends the addressed stage-4 request | Accepted with the frozen prefix |
| Stage-4 reply / stage-5 terminal | Expected `84/2c` request is absent; retries follow | Not accepted; node progress remains `5/6` |
| Retained telemetry and local control | Ordinary paired reports and matching command responses | Not established |

The white LED is the most difficult and useful breakpoint: it is positive
device-side proof that the initial association was accepted. It is not proof
of complete enrollment. Once it appears, the addressed stage-1 request gives
the investigation a deterministic request/reply loop instead of silence.

Continuous SDR captures of candidates `.4`--`.7` preserved counter-2
assignment acceptance and the addressed stage-1 request but produced no
`81 50`. They establish that the CC1101 emitted every requested wake symbol;
the earlier apparent 64-symbol shortfall came from a lossy synchronous SDR
capture, not from transmitter truncation. Candidate `.5` matched the stock
post-frame low tail, `.6` matched the stock 2,400-symbol wake and total burst
duration, and `.7` matched the stock absolute configuration timing. None was
sufficient to advance the valve beyond two completed steps.

The validated counter-2 physical definition is:

| Property | Current definition |
|---|---:|
| Assignment wake | 320 alternating symbols |
| Symbol rate | 20,000 symbols/s |
| Deviation | CC1101 `0x45` |
| Node frequency correction | +122.759 kHz on the OTA test node |
| Assignment delay | 49.650 ms from the captured request boundary |
| Assigned response carrier | 434.3515 MHz nominal; node setting is calibrated against the valve oscillator |
| Ordinary stage-1 delay | 68.700 ms from the captured request boundary |
| Delayed configuration boundary | 2,952.55 ms after the normalized stage-1 request end |
| Delayed configuration wake | 2,400 alternating symbols |
| Delayed configuration low tail | About 201.5 us stock; candidate `.7` measured about 212.5 us |

The candidate-.3 ordinary response measured 434.351533 MHz versus stock at
434.351790 MHz and eliminated the valve's retries. A later lossless capture
proved that its apparent short long-wake result was a capture artifact.
Candidate `.7` emits the exact configuration frame with a 2,400-symbol wake,
`135.340 ms` total duration versus `135.361 ms` stock, approximately the stock
low-tone tail, and the exact stock request-to-frame delay. An unchanged,
unclipped `.7` repeat showed that the local short and long replies share the
same carrier, `0x45` deviation, symbol rate, and boundary quality. It exposed
one previously unfrozen difference: the ordinary stage-1 reply retained its
final low tone for only `31.0 us` versus `160.5 us` stock.

Candidate `.8` changed only that boundary. Its ordinary reply measured
`149.5 us` of final low-tone hold, but the valve again stopped at `2/6` without
emitting `81 50`. Its long configuration was byte-identical to the selector-6
stock frame, all 2,399 wake transitions were recovered, and no clipping was
present. A later balanced-wake reanalysis corrected the earlier payload-biased
FFT result: stock deviation is about `40.149 kHz`, while local deviation is
about `41.223 kHz`. The centers differ by only about `456 Hz`, and all 2,704
wake-plus-frame symbols have identical polarity. The logical transcript is
therefore frozen. The later non-enrolling calibration confirms the same 2-FSK
family and no wake-to-frame profile change; the small quantized deviation
difference remains measured but does not justify changing the accepted
stage-1 profile.

A controlled full-factory-reset repeat of unchanged candidate `.8` again
produced the white flash and addressed stage-1 request, then stopped at `2/6`
without `81 50`. Retained valve session state is therefore not the missing
condition. The other radio nodes only reported receive observations; no
competing pairing or HTV145 acknowledgement transmission was present. Their
different Home Assistant `observed_at` times reflect network ingestion and
must not be used as RF retry timing; the continuous IQ capture is authoritative
and contains only the first stage-1 exchange.

Additional offline checks ruled out two implementation-side explanations. The
2.8-second interval in which the CC1101 waits in synthesizer-on state has no
detectable carrier above the surrounding noise floor, so there is no evidence
that local-oscillator leakage jams the valve. Transition timing also has no
error concentrated at the ESP32 RMT driver's 128-symbol refill boundaries.
The local wake does have more threshold-crossing jitter than stock, but the
same behavior on the short stage-1 reply is sufficient to suppress retries and
is not yet causal.

Transmit level is not the next discriminator. One accepted stock counter-2
capture happened to put the long configuration about `1.5 dB` below its short
reply, but a second accepted counter-0 capture put the long transmission about
`0.6 dB` above its short reply. That variation is session geometry, not an
encoded power rule.

A non-enrolling four-frame calibration closes the configuration-modulation
hypothesis. The accepted stock transmission is sharp-transition 2-FSK (about
`2 us` from 10% to 90%); CC1101 GFSK takes about `14 us` and is plainly
different. Register `0x44` undershoots the stock deviation, while `0x45`
remains the closest justified CC1101 family. Symbol-aligned measurements of
all 304 frame bits also show that neither stock nor candidate `.8` changes
carrier or deviation at the wake-to-frame boundary.

Candidate `.9` tested the synthesizer pre-arm discriminator. Unlike `.8`, it
kept the radio in receive configuration until `20 ms` before the frozen
configuration boundary instead of holding FSTXON for roughly `2.8 s`. The
valve again accepted stage 0, emitted the addressed stage-1 request, and then
stopped at `2/6` without `81 50`. Its lossless SDR capture measured a
`135.339 ms` configuration burst, all `2,399` wake transitions, a frame
boundary within about `0.15 ms` of stock, and about `210.5 us` of final low
tone. Long synthesizer pre-arm dwell is therefore not the missing condition.

Worst-case wake analysis found higher transition-fit residuals locally than
in stock, but the same local signature is present on the short stage-1 reply
that suppresses retries. No isolated long-burst refill discontinuity or
frequency drift was found. The next justified discriminator is the transmitter
implementation: reproduce the delayed configuration with a CC1101-clocked
synchronous or FIFO-backed path, first to an impossible endpoint for SDR
comparison, while freezing the accepted assignment and ordinary reply.

The first synchronous-serial calibration exposed two implementation facts,
not new valve semantics. Fixed packet length truncated the long wake after
exactly `15.2 ms`; infinite length fixed that cutoff. A forced-low/high GDO2
probe then identified a missing radio-GDO2-to-ESP32-GPIO25 connection. Once
that jumper was added, synchronous calibration counted exactly `2,712` clock
edges: `2,704` supplied symbols plus the documented eight-bit transmit latency,
and restored receive mode. Lossless SDR showed that the CPU-polled data feeder
nevertheless corrupted the synchronous on-air stream: no exact sync or frame
was recoverable. That path is excluded.

The raw-FIFO calibration produced the exact intended 38-byte frame with stable
hardware timing and no clipping. Its center was `639 Hz` above stock and its
measured deviation `901 Hz` wider. It emitted about `2,410` alternating symbols
before sync and lasted `135.779 ms`, versus `2,400` and `135.361 ms` stock.
Candidate `.10` therefore changes only the delayed configuration transmitter
from ESP32 RMT to CC1101 FIFO while keeping the accepted stage-0 assignment and
ordinary stage-1 reply frozen. Two unchanged clean live trials produced the
exact valve-originated `81 50` request and advanced through the next two
addressed requests, moving node progress from `2/6` to `5/6`. This freezes the
assignment-through-configuration prefix and directly establishes that
hardware-clocked FIFO transmission solved the delayed-configuration boundary.

Enrollment is not terminal yet. The zero-based step-4 reply matched the stock
frame, carrier, 320-symbol wake, and schedule, but candidate `.10` lasted
`31.2285 ms` versus `31.358 ms` stock. Candidate `.11` added only the proven
`115 us` final-low hold and brought the burst to `31.3505 ms`, within `7.5 us`
of stock. The valve nevertheless emitted the same `84/03`, `84/83`, `85/03`,
and `85/83` retry family instead of the stock terminal `84/2c` request. Matching
tail duration alone was insufficient; interactions with other waveform
differences remain untested. The remaining measured
discriminator is symbol-edge stability: `.11` transition-fit RMS was `3.802`
samples versus `0.5531` stock. Two impossible-endpoint candidate `.12`
captures recovered the exact reply and all 320 wake symbols with FIFO RMS
`0.430--0.459` samples. FIFO therefore removes the jitter, but its 115 us
driver hold produced only `68--69 us` of measured post-frame low tone versus
`160.5 us` stock and `161.5 us` in `.11`. Two candidate `.13` calibrations
proved why: the CC1101 had already entered `TXFIFO_UNDERFLOW` before the driver
delay, so increasing it to `207 us` left the on-air tail unchanged at `69 us`.
Candidate `.14` retains the complete accepted prefix and exact FIFO waveform
while removing that ineffective off-air delay so receive mode is restored
immediately. Since matching the tail alone did not restore acceptance in `.11`,
the next discriminating observation was a controlled live `.14` trial.
Its impossible-endpoint calibration recovered the exact frame, all 320 wake
symbols, and transition-fit RMS `0.337` samples without clipping; the node then
restored receive successfully. The first approved live `.14` trial again
reached `5/6`, with the exact step-4 reply followed by `84/03` and `85/03`
lower-carrier retries, not terminal `84/2c`. Its SDR recording clipped heavily,
so decoded frame contents establish the exchange but precise analog waveform
comparisons are inconclusive. Hardware-clocked step 4 has not yet demonstrated
terminal acceptance. The accepted assignment/configuration prefix stays frozen.
Evidence is in
[`research/fixtures/htv145_fifo_configuration_acceptance_20260904.json`](../research/fixtures/htv145_fifo_configuration_acceptance_20260904.json).

The older selector-6 clock/date masks differ between its counter-0 and
counter-2 transcripts: counter 0 sets time-low bit 7, while counter 2 sets
time-high and date-low bit 7. The fresh selector-2 transcript also sets
time-low bit 7; counter alone therefore does not identify the clock mask.
The selected research profile preserves its own captured masks.

The frequency correction is node-calibration evidence, not a universal device
constant. Absolute centers from separate SDR sessions are insufficient; the
gateway response must be normalized against the valve request oscillator in
the same capture.

Therefore no HTV145 local enrollment profile is advertised as supported until
the remaining stage completes twice without changing the frozen prefix. The
reusable investigation method is documented in
[`research/PAIRING_REVERSE_ENGINEERING_PLAYBOOK.md`](../research/PAIRING_REVERSE_ENGINEERING_PLAYBOOK.md).

## Routine telemetry and state

The status marker is normalized offset `20`:

```text
frame[20] low 7 bits == 0x4f
frame[20] == 0xcf -> watering
frame[20] == 0x4f -> idle
```

The terminal session summary has normalized bytes `14..18`:

```text
82 07 85 80 80
```

It is idle, includes final usage and duration, and does not include a battery
state.

## Duration

HTV145 uses the same packed two-second scalar as HTV405. Low-byte bit 7 is a
mandatory marker and its displaced data bit moves to extension byte 21 bit 7:

```text
units = seconds / 2
field = little_endian_u16(units) with low-byte bit 7 replaced by 1
extension = units & 0x80
seconds = ((little_endian_u16(field) & ~0x80) |
           (extension & 0x80)) * 2
```

Validated whole-minute examples include:

| Field | Extension | Duration |
|---|---:|---:|
| `9e 00` | `00` | 60 seconds |
| `f8 00` | `00` | 240 seconds |
| `96 00` | `80` | 300 seconds |
| `c2 01` | `80` | 900 seconds |
| `fe 01` | `80` | 1,020 seconds |

The retained 1,020-second selector-5 command has an ordinary open marker and
extension `0x80`, while 600- and 1,200-second selector-6 commands have extension
`0x00`. That separates the duration extension from association-marker polarity.

## Water usage

Usage is encoded in three consecutive bytes. For bytes `first`, `second`, and
`third`:

```text
half_tenths = ((second & 0x7f) << 8) | (first & 0x7f) | (third & 0x80)
tenths_liter = half_tenths * 2 + bool(second & 0x80)
liters = tenths_liter / 10
```

Routine status reports store the triplet immediately after the status region;
terminal summaries use normalized offsets `24..26`. Terminal duration is at
offsets `28..29`.

## Battery state

Routine usage/status reports carry a categorical battery bit at normalized
offset `17`:

```text
bit 0x08 clear  normal/full category -> expose 100%
bit 0x08 set    low category         -> expose 10%
```

The terminal session summary does not carry this bit, so it must not overwrite
the last valid battery category.

## Stock control request

The command body starts with a five-bit command sequence, followed by a branch
marker and operation:

```text
body[0] = 0x80 | (sequence & 0x1f)
body[2] = 0x82 open, 0x81 close
```

The older stock captures supplied these marker combinations:

| Profile | Open marker | Close marker |
|---|---|---|
| Selector 5 | `0x10` | `0x90` |
| Selector 6 | `0x90` | `0x10` |

These are observations, not fixed association rules. In the fresh September 5
selector-2 session, the first open used `90`, later opens used `10`, and both
explicit closes used `90`. The marker can change within one association; its
full state rule remains unresolved. Explicit research probes can select it per
command without changing the runtime's existing profile assumptions.

Duration extension byte 21 is determined only by the packed duration value,
not by this selector branch.

Both stock opens and closes use **2,400 alternating wake symbols** (2,399
transitions before sync), about `135.36 ms` including the frame. Candidate
`.15` used only 1,200 symbols; its earlier silence did not test the stock wake.
The older accepted selector-6 opens use trailer residue `c713`, while closes
use `4f03`. The fresh selector-2 opens instead use `4f03`, with `c713` closes.
Retain the exact captured variant for each transaction; neither observation
establishes a universal action-to-trailer mapping.

One logical stock command is three byte-identical RF attempts at approximately
`0`, `0.729210`, and `1.668479` seconds. The controller waits for a matching
response; it does not issue repeated logical opens in rapid succession.

The older selector-6 sequence was open `81`, close `82`, open `82`, close `83`.
The fresh selector-2 trace instead has open `81` with automatic stop, then open
`82`/close `82` and open `83`/close `83`. A single "next sequence after open"
value is therefore insufficient to choose both the next open and its early
close across the observed branches. The existing helper embodies the older
trace, so the isolated trial uses explicit fields rather than its convenience
close. Only a passive stock command or matching response can authenticate a
command counter; periodic telemetry cannot.

Before the successful `.22` experiment below, local command acceptance had not
been demonstrated. Following the original `.15` trial, candidate `.16`
sent one user-authorized 60-second open with the corrected 2,400-symbol wake and
assumed counter `1`. SDR recovered three exact commands, with approximately
`135.25 ms` duration and no clipping, but no matching valve response or later
state across five investigated carriers through the nominal automatic-stop time.

Two separate `.17` close-only probes used counters `1` and `0`, marker `10`,
residue `4f03`, and the corrected wake. Each elicited three valid matching-route
frames in node diagnostics. SDR recovered the same negative result family,
with normalized bytes `14..18 = 50 86 83 00 4f` and the submitted sequence
echoed at byte 13. Successful stock replies instead have `86 80` at bytes
15--16. The exact meaning of result code `3` remains unresolved. Its
idle-looking marker does **not** confirm a physical close or authenticate the
next counter. Addressed `02/82 81 06` association traffic also appeared later
on the lower carrier after the counter-0 probe.

This establishes command reception and a valve-originated non-success result,
not a supported local open/close pair or proof that step 6 is mandatory. The
counter guesses, association state, and other command fields remain separate
possible causes. Candidate `.18` recognizes the captured negative family,
retains the frame in failure diagnostics, and stops its pending command without
authenticating the counter. It changes no pairing payload, timing, or RF driver.

The latest first stock 60-second open and the earlier local open have identical
normalized bytes 13 through 35, including sequence `81`, marker `90` and
duration `9e 00`. Their trailer residues differ: `4f03` stock versus `c713`
local. This supplied the new command variant for the user's requested 5/6
control experiment. The successful stock command belongs to selector 2, while
the accepted local prefix belongs to selector 6; transfer between these branches
is a hypothesis, not proof that the earlier packet was malformed.

Preparation restored the original `.22` binary unchanged and proposed one
continuous pairing/control recording. After verifying its accepted prefix, the
first command would use sequence `81`, marker `90`, residue `4f03` and 60 seconds
on channel 12. The proposed close retained `81` with marker `90`/residue `c713`.
That cross-branch close hypothesis failed in the actual experiment below. The
prepared uninterrupted recorder also encountered a progress-reset guard issue;
the retained evidence distinguishes that incident from RF behavior.

This is a user-authorized dry research experiment before terminal enrollment,
not a supported HA transmit path. Native replay reproduced all five successful
stock commands exactly. The recorder's real control block was exercised offline
to reject insufficient progress, an armed radio, a stale pairing review, and a
stale open response. Preparation evidence is retained in
[`htv145_partial_control_variant_preparation_20260905.json`](../research/fixtures/htv145_partial_control_variant_preparation_20260905.json);
the [canonical roadmap](../PROJECT_ROADMAP.md) records the physical gate.

## Accepted local control after 5/6 (2026-09-05)

The user authorized one `.22` pairing arm and reported a white/success LED. The
radio again reached 5/6. Filtered CRC-valid RF recovered the configuration
response, addressed continuations and exact local replies, followed by
`84/03` through `85/83` retries. The terminal exchange remained absent.

Stopping pairing clears the node's live progress fields. The prepared recorder
incorrectly required those fields to retain 5/6 after disarm and therefore sent
no command. The corrected gate uses the saved, command-scoped prefix together
with current disarmed state; its offline replay now includes cleared progress.
Control continued on the unchanged valve association in separate recordings,
with a test-radio restart before each. No additional valve gesture or pairing
arm occurred. This result does not claim uninterrupted radio-session control.

These transactions were independently recovered from RF and positively
acknowledged by the valve on the first transmitted attempt:

| Action | Counter | Marker | Trailer residue | Result |
|---|---|---|---|---|
| First 60-second open | `81` | `90` | `4f03` | Positive reply; automatic stop and idle report |
| Second 60-second open | `82` | `90` | `4f03` | Positive reply and watering reports |
| Active early close | `83` | `10` | `4f03` | Positive reply and subsequent idle reports |

The first open's measured carrier was `434.351406 MHz`, with 2,399 recovered
wake transitions, a `135.229 ms` burst and no clipping. Direct response delays
were `268.735`, `274.059` and `270.590 ms` from command sync to response sync.
The first idle report followed its open by `61.900415 s`. In the second run,
the explicit close followed open by `20.476064 s`; independent idle followed
close by `6.142533 s`, before the 60-second timer would expire.

The initial same-counter close (`81/90/c713`) was not acknowledged, and later
watering telemetry proved it had not stopped that run. After automatic stop,
a marker-only `81/10/c713` probe also went unanswered. The older selector-6
close `82/10/4f03` then elicited three result-3 replies while already idle;
changing only its trailer to `c713` produced silence. A further bounded open
at `82/90/4f03`, followed while active by `83/10/4f03`, completed the positive
open/close exchange. An already-idle explanation for result 3 is now plausible,
but its general meaning remains unresolved and it must not authenticate a
counter or be classified as an accepted close.

This validates incrementing the close counter after open on this selector-6
association, unlike the latest selector-2 same-counter close trace. Both actions
used residue `4f03` here. The working packets should be retained as an
association profile, not generalized to every selector or lifecycle.

The new result-3 layout has byte 17 `10`, while the existing narrow recognizer
expects `00`; `.22` therefore reported it as corrupt/foreign rather than a
classified negative result. Routine telemetry here uses family byte 16 `86`,
outside the runtime's current `85`-only state recognizer. These limitations did
not create the positive verdict: exact direct replies and raw watering/idle
frames provide the evidence. The reports also repeat an older 60-second session
summary, including during the second run, because report ACKs are missing.
Those summaries cannot establish the second run's elapsed duration.

Both the Python and native firmware regressions preserve the three accepted
command packets. Raw captures, negative probes, node results and the recorder
incident are retained in
[`htv145_partial_pairing_control_acceptance_20260905.json`](../research/fixtures/htv145_partial_pairing_control_acceptance_20260905.json).
The valve finished idle and all radios connected/disarmed. Firmware stayed at
the exact `.22` artifact; no HA control path was promoted.

The read-only `tools/analyze_htv145_control_iq.py` separates commands, accepted
responses, and negative replies, including wake histograms. The pairing analyzer's
`--require-terminal` mode additionally requires a valid terminal `2c 80 99`
request and its matching `6c 81 80 19` reply; assignment acceptance alone cannot
produce a successful terminal verdict. These are exchange gates, not proof of
retained operation after a subsequent restart.

The September 5 reduced-gain `.18` repeat removed clipping as a limitation:
the exact final reply still had a `70 us` ending, stable FIFO edges, and the
same non-terminal retries. Candidate `.20` then calibrated an active FIFO stop
against compiled unused endpoints. One zero byte follows the unchanged frame.
The CC1101 exposes its TX FIFO threshold on GDO1/MISO while chip select is high;
the driver selects threshold one, watches that GPIO edge, delays a bounded
interval, verifies TX is still active, and strobes SIDLE. It restores GDO1 and
the receive configuration afterward. This uses the existing MISO connection;
see the [TI CC1101 datasheet, Table 41](https://www.ti.com/lit/ds/symlink/cc1101.pdf).

The initial `500 us` active delay truncated the last byte despite a successful
TX diagnostic. At `800 us` the exact packet returned, but its ending remained
only `51--57 us`. Three unchanged `910 us` probes recovered the exact frame and
319 wake transitions, with `157--164 us` of low tone against `160.5 us` stock,
`0.309--0.318` sample transition-fit RMS, no clipping, and receive restored.
The delay is an empirical setting for this test radio; do not interpret it as
a universal FIFO byte latency or automatically apply it to other boards.
Measurements and capture hashes are preserved in
[`htv145_fifo_active_tail_calibration_20260905.json`](../research/fixtures/htv145_fifo_active_tail_calibration_20260905.json).

Candidate `.21` applies this active stop only to zero-based reply 4, preserving
the accepted assignment/configuration prefix, frame bytes, and reply schedule.
The serial-only research calibration command requires three arguments:
`htv145_fifo_step4_calibration OFFSET_HZ ACTIVE_DELAY_US POWER_DBM`.
Delay zero selects the natural baseline; other delays are bounded to `1200 us`,
power is `0` or `10 dBm`, and the command refuses an armed pairing session.
It is compiled out of production and supervised firmware.

For a physical pairing trial, verify the expected firmware, fresh gateway
authentication, and a disarmed node; start a bounded continuous capture at the
proven reduced SDR gain before the user's gesture. Disarm afterward and require
the exact terminal request/reply exchange. Matching the ending and edge timing
on an unused address does not prove terminal enrollment or control acceptance.
The live gates are tracked in [PROJECT_ROADMAP.md](../PROJECT_ROADMAP.md).

The first authorized live `.21` trial on September 5 again reached `5/6` and
the user observed a white LED. All four ordinary replies after assignment
matched the successful stock counter-2 exchange byte for byte. The final reply
had a `162.5 us` low-tone ending, `0.323` sample edge-fit RMS, 319 wake
transitions, and no clipping; the calibrated ending therefore did appear on
air during real pairing. The valve still sent `84/03`, `84/83`, `85/03`, and
`85/83`, with no terminal request in the bounded capture. Matching the ending
and edge stability together was insufficient in this attempt.

A separate same-method comparison of channel-filtered RF envelopes measured
`52.4745--52.5025 ms` between request RF cessation and local reply onset, versus
`52.362--52.372 ms` stock. Across identical envelope thresholds, local was
`112.5--131 us` later. These RF-burst gaps differ from the nominal decoded-frame
gap used by the scheduler. The driver currently timestamps a complete RX FIFO
when software polls it, which is a possible source of latency. This single
comparison identifies a measurable remaining difference; it does not establish
causation or justify an unmeasured constant timing shift. Raw capture hashes,
redacted frames, waveform measurements, and the comparison are preserved in
[`htv145_calibrated_tail_terminal_retry_20260905.json`](../research/fixtures/htv145_calibrated_tail_terminal_retry_20260905.json).

Candidate `.22` changes only the timing anchor for zero-based reply 4. While
waiting for that request, it selects IOCFG1 `0x06`, watches GDO1/MISO go high
for sync, and leaves SPI idle until the packet-end falling edge. The wait is
bounded to `16 ms`; the fixed received payload lasts about `14.4 ms`. This
avoids changing the GDO0 pin configuration used by the accepted RMT prefix.
The original FIFO-poll timestamp remains available for all earlier replies.
The final reply retains its `52,550 us` nominal delay and `910 us` active FIFO
ending, but schedules from the captured edge. It does not subtract a guessed
constant from the old timestamp.

An observation qualifies only after at least `200 us` of continuously observed
high signal, at most `2 ms` before the software sees exactly one complete
packet in the RX FIFO. It is consumed once and cleared by flushes or channel
changes. A missing or ambiguous edge suppresses the experimental reply and
emits `step4_missing_edge`; packet matching and CRC checks remain mandatory.
The `htv145_receive_edge_observation` diagnostic records the edge, FIFO-poll
time, observed high interval, and selected reply deadline after transmission.
These fields distinguish a failed timing experiment from a missing marker.

The serial-only command `htv145_receive_edge_calibration SECONDS` enables
bounded receive-only observation while pairing is disarmed (`1..120` seconds,
or `0` to stop). It does not arm a valve or send an RF probe. Three CRC-valid
incoming frames produced qualified edges `40--48 us` before the FIFO poll;
one was also recovered exactly from the lower-gain SDR recording. Two weaker
frames were not recovered by that decoder, and two invalid-CRC observations
were excluded. Three separate unused-address transmissions from the installed
`.22` image retained `163--164 us` of low tone, exact packets, and no clipping.
This verifies marker acquisition and preservation of the calibrated ending;
absolute marker timing relative to a valve's RF frame end and terminal
acceptance still require the controlled pairing capture. Evidence is in
[`htv145_receive_edge_candidate_calibration_20260905.json`](../research/fixtures/htv145_receive_edge_candidate_calibration_20260905.json).

The first authorized live `.22` trial also stopped at `5/6`. Serial evidence
confirmed a qualified packet-end signal after `13,615 us` of observed high
level, followed by the FIFO poll `40 us` later. The final reply used the edge
plus exactly `52,550 us`, with no fallback. SDR recovered its exact stock
bytes, `163.5 us` low-tone ending, `0.310` sample edge-fit RMS, and no clipping.
At stable 20% and 50% envelope thresholds, local request-RF-end to reply-onset
was `52.404--52.4085 ms`, compared with `52.3655--52.372 ms` stock. The residual
was `36.5--38.5 us`. The 10% local threshold picked up weak residual energy
after the packet and was excluded from timing conclusions.

The valve nevertheless emitted the same `84/03`, `84/83`, `85/03`, `85/83`
retry family. Hardware marker acquisition and the timing change are therefore
demonstrated, while terminal acceptance remains unproven. The initial serial
preflight aborted before arming because fresh Wi-Fi authentication had not
returned; a bounded retry waited for authentication and performed exactly one
authorized arm. The radio was verified disarmed with its persistent sensor
ACK authorization afterward. Evidence is in
[`htv145_receive_edge_terminal_retry_20260905.json`](../research/fixtures/htv145_receive_edge_terminal_retry_20260905.json).

## Fresh stock pairing and cloud control baseline (2026-09-05)

Stock pairing completed again with the current valve and radio placement. This
attempt accepted factory counter `0`, assignment selector `2`, and response
channel `4` near `433.4715 MHz`. The full exchange includes terminal valve
`82/ac/80/99` and gateway `82/ec/81/80/19`. The offline analyzer now recognizes
this captured controller-route assignment and derives its channel instead of
misclassifying it as missing. It previously recognized assignment selectors
5/6 only. This changes analysis, not transmitted firmware.

The user authorized dry watering through the existing HA cloud integration.
Reloading that integration restored its stale unavailable entities. One
association then supplied these accepted transactions:

| Run | Requested duration | Command counter | Result |
|---|---:|---|---|
| A | 60 seconds | Open `81` | Automatic stop; no explicit close sent |
| B | 120 seconds | Open `82`, close `82` | Explicit stop before the timer expired |
| C | 60 seconds | Open `83`, close `83` | Repeated duration and successful explicit stop |

All five commands have CRC-valid direct valve responses with matching counters
and the expected `cf` watering or `4f` idle state. The immediate response uses
the assigned command channel. Command sync to response sync measured
`267.280--273.178 ms`; this is not an RF-end-to-onset delay. The first open has
two exact observed transmissions, with the response following the repeat.
The broad decoder missed these weaker replies; narrow-channel extraction
recovered them. An empty wideband response list alone is not rejection evidence.

The later watering/idle reports use the lower carrier and receive separate
320-symbol gateway `41/c1` acknowledgments on the assigned channel. Final
session summaries receive `42/c2` acknowledgments. These report sequences are
distinct from the command counter echoed in the immediate response. Opens
advanced command counters while both explicit closes retained them. Open/close
wakes again fit the 2,400-symbol form.

The first open used marker `90` and the later opens used `10` without another
pairing in between. Preserve both observations; they do not justify treating
marker polarity as a fixed property of the association. No local pairing or
control candidate was changed or armed from this observation.

Cloud access setup required a recorder rollover before any watering command.
The complete pairing and complete control sequence therefore occupy two raw
files with the same association, with no command during the gap. Explicit
close command syncs occurred `49.397` and `36.762` seconds after their respective
open command syncs; these actual timings supersede the planned approximate
30/20-second UI targets. The cloud duration was restored to its original value,
the valve reported idle, and all custom nodes were connected/disarmed afterward.

This confirms a current successful stock baseline. It does not establish why
local `.22` stops at 5/6: that candidate used counter 2, selector 6, and channel
12. Compare consistent association branches before inferring a timing cause.
The redacted transcript, both raw hashes, five positive responses, reports,
and report acknowledgments are retained in
[`htv145_selector2_stock_pairing_control_20260905.json`](../research/fixtures/htv145_selector2_stock_pairing_control_20260905.json).

## Evidence and implementation

- Receive decode and research command builder:
  `rainpointd_addon/rainpointd/valve_protocol.py`
- Enrollment candidate: `rainpointd_addon/rainpointd/valve_pairing_protocol.py`
- Stock enrollment: `research/fixtures/htv145_gateway_pairing_replies.json`
- Selector-6 enrollment:
  `research/fixtures/htv145_later_sweep_stock_enrollment_20260828.json`
- Counter-2/subchannel-12 enrollment:
  `research/fixtures/htv145_counter2_stock_enrollment_20260901.json`
- App-first counter-0/subchannel-12 enrollment:
  `research/fixtures/htv145_counter0_app_first_stock_enrollment_20260901.json`
- Balanced-wake PHY discriminator:
  `research/fixtures/htv145_balanced_wake_phy_discriminator_20260901.json`
- Configuration PHY calibration:
  `research/fixtures/htv145_configuration_phy_calibration_20260903.json`
- Command and duration evidence:
  `research/fixtures/htv145_selector6_stock_duration_commands_20260828.json`
- Stock control wake/counter reanalysis:
  `research/fixtures/htv145_stock_control_shape_20260905.json`
- Partial-association corrected control and negative replies:
  `research/fixtures/htv145_partial_pairing_control_replies_20260905.json`
- Battery and usage evidence:
  `research/fixtures/htv145_cloud_rf_battery_usage_correlation_20260824.json`
- Evidence ledger: [`../research/VALVE_PROTOCOL_STATUS.md`](../research/VALVE_PROTOCOL_STATUS.md)
- Chronology: [`../research/RF_CAPTURE_NOTES.md`](../research/RF_CAPTURE_NOTES.md)

## Isolated selector-2 candidate preparation (2026-09-05)

The fresh successful stock transcript now has an independent firmware profile,
selected by `RAINPOINT_HTV145_ASSIGNMENT_SELECTOR_CANDIDATE=2`. It requires the
counter-0 branch, the complete research FIFO/tail build gates, and supervised
HTV405 control disabled. Selector 6 and candidate `.22` retain their existing
payloads, carriers and timing. All variants use the one supported
`rainpoint_bridge` environment.

The first physical candidate `.2` assignment was rejected. The node transmitted
one assignment, then observed the valve continue its factory sweep and reported
`stage_0_rejected` at `1/6`. The operator reported "Fail."; no specific LED color
was supplied. Filtered CRC-valid counter-2 and counter-3 requests corroborate the
failure. The broad decoder missed those quiet requests, so its incomplete
`no_assignment_trial` verdict is not the physical result. No valve control was
sent, and the radio was verified disarmed afterward.

Before endpoint redaction and CRC, the assignment differs from fresh stock only
at live clock bytes 21 and 22. Relative to each recording's valve oscillator,
the assignment carrier differs by +601 Hz. The local low-tone ending is 162 us
versus stock 159.5 us, with no clipping. Using the same channel filter and
envelope method, stable 30--60% thresholds put the local first reply
357--360 us later. Lower thresholds are contaminated by noise and higher ones
are sensitive to the weak request ending. This is a measured difference, not an
established rejection cause; clock flags and assignment byte 25 remain uncertain.

A `.3` candidate advancing only the initial software deadline by 350 us was
built and tested, then parked without flashing or arming. Its source patch and
binary are preserved locally; tracked firmware retains `.2`. The existing `.22`
artifact and successful counter-2/selector-6 stock capture remain available for
the final-exchange investigation. Priority and acceptance gates are maintained
in the [canonical roadmap](../PROJECT_ROADMAP.md).

An earlier arm in this session transmitted no assignment: stale progress from
another command prematurely started the recorder's 45-second tail. The runner
now scopes progress and completion to its own command ID. The user explicitly
authorized the subsequent physical attempt described above. Both recordings,
the redacted failed exchange, threshold sensitivity and parked-candidate state
are recorded in
[`htv145_selector2_assignment_rejection_20260905.json`](../research/fixtures/htv145_selector2_assignment_rejection_20260905.json).

The native selector-2 regression reproduces all six stock responses (including
the separate long configuration), consumes the valve's configuration response,
and reaches completion only after `82 ac 80 99` / `82 ec 81 80 19`. It first
failed at the assignment against the older counter-0 selector-6 builder.
Negative checks cover the wrong selector, invalid CRC, and the missing terminal
request. Endpoints come from the association supplied to the builder. The live
clock is advanced normally; selector 2 retains the captured high flags in both
time bytes and date-low. Assignment byte 25 remains the captured, uninterpreted
`03`, so this is a bounded research profile, not a general clock encoding.

`htv145_profile_calibration` is compiled only into this research profile. It
uses fixed unused endpoints and the actual selected reply builders, covering
assignment, ordinary continuations, FIFO configuration and FIFO step 4. It
cannot accept a live endpoint. Production and supervised binary-boundary checks
explicitly exclude the command. The candidate also contains the existing,
separately gated one-minute dry-control probes.

The initial six-frame recording recovered every frame without ADC clipping.
Its initial assignment carrier was 5.253 kHz below the fresh stock measurement;
three repeats with that correction measured 433.582324--433.582447 MHz, versus
stock 433.582308 MHz. Routine replies remained within approximately 1 kHz of
stock. Candidate `0.15.4-htv145-pairing-selector2-candidate.2` encodes the initial
correction only for selector 2. Three step-4 probes at the selected 905 us active
FIFO stop measured 156--156.5 us low tone (stock 159.5 us), exact CRC-valid frames,
no clipping, and less than 0.35 sample edge RMS. Selector 6 retains 910 us.
Short selector-2 replies use the existing 115 us low-hold adjustment; the
hardware-clocked configuration and step-4 receive-end observer are retained.

The stock timing constants were recomputed from exact-sync positions rather
than the coarser inventory timestamps. Request-frame end to reply-wake start
measured 46.5345, 70.0065, 37.681, 53.808 and 49.741 ms for steps 0, 1, 3, 4 and
5. The configuration wake starts 3065.497 ms after the stage-1 request end.
These supply rounded initial deadlines; they do not establish the live radio's
receive-to-transmit offset. Likewise, carrier matching with one SDR must be
checked against the valve's oscillator in the actual attempt. The retained FIFO
configuration path has a shorter final low tone than stock despite comparable
total burst duration; no claim of analog identity is made.

The combined trial keeps recording after terminal enrollment. It requires a
positive direct close response before a one-minute dry open, then an explicit
early close and later idle evidence. The first stock open's marker differs
from subsequent opens, and a stock close retains its open's counter. Use
explicit per-command packet fields during this experiment; the existing
`htv145_dry_close` convenience path's automatic counter choice is not this
trial's evidence. Raw IQ and serial diagnostics stay untracked. Measurements
are preserved in
[`htv145_selector2_candidate_calibration_20260905.json`](../research/fixtures/htv145_selector2_candidate_calibration_20260905.json).
The physical acceptance gates remain in [the roadmap](../PROJECT_ROADMAP.md).

The first post-flash `.2` verification aborted at the long configuration: RF
stopped after 112.212 ms, before its frame sync, and the radio returned
`transmit_failed` with receive restored. Its preceding two short frames were
valid. This failure is retained in the calibration fixture and must not be
counted as a successful configuration. Startup/network scheduling interference
is a hypothesis, not an established cause; the same image is subsequently
checked after startup settles. A successful repeat does not erase that observed
transmit failure or establish pairing reliability.

Two complete unchanged `.2` repeats after startup settled recovered all twelve
frames with no clipping and receive restored. Their step-4 endings measured
162 and 162.5 us, with edge RMS below 0.36 sample; initial carriers measured
433.582146 and 433.582325 MHz. Both long configurations decoded successfully.
These are preparation evidence for the next physical attempt, not evidence
that startup settling fixed the isolated earlier failure.

## Persistent qualification runtime (gateway 0.34.3)

The accepted selector-6 recipe is persisted with separate open/close residues,
marker polarity, command carrier, calibrated report-ACK carrier, and one owner
node. Ordinary firmware excludes this path; the designated dry-test image uses
`RAINPOINT_HTV145_ENABLED=1` and the add-on retains `htv145_dry_acceptance: true`
as its explicit runtime gate. This is not yet a supported HA actuator route.

Management-token-protected POST routes under `/api/v1/research/htv145-control/`:

| Action | Required input and effect |
|---|---|
| `enroll` | `profile`, `command_frame`, `response_frame`, `idle_frame`, `exchange_observed_at`, `idle_observed_at`; require matching positive exchange and independent idle within one hour. Persists owner; configures/synchronizes node without actuation. |
| `status`, `morning-check` | `valve_endpoint`; return counter, fresh state, owner availability, readiness and any overdue-idle anomaly. No RF probe. |
| `open` | `valve_endpoint`, `duration_seconds` (60–3600, whole minutes); reserve durably, then dispatch once using the known counter. |
| `close` | `valve_endpoint`; explicit close with the authenticated counter and minimum 15-second spacing; a fresh known-idle state returns `already_idle` without RF. |
| `revoke` | `valve_endpoint`; wait for the exact node command's revocation acknowledgment before permitting reassignment. |

The profile supplies `node_id`, `controller_endpoint`, `valve_endpoint`,
`center_hz`, `power_dbm`, `invert`, `trailer_residual`,
`command_marker_inverted`, `close_trailer_residual`, and `report_ack_center_hz`.
Endpoint names follow the command direction (`controller_endpoint` transmits
commands); do not reverse them by guessing from their product suffix. Obtain
all identities and calibration from the association under test. Runtime selector-6
uses `command_marker_inverted=true` and both residues `0x4f03`.

Gateway 0.34.4 also permits upgrading a pre-ACK dry-trial profile on the same
association. The old profile must have no report-ACK owner, pending
command or revocation; exchange evidence must postdate its last local command.
Changing radios additionally requires a live authenticated handshake from the
old radio confirming that its firmware no longer supports HTV145 control or ACKs.
An existing ACK owner still requires correlated revocation before replacement.
This upgrade uses the same independent idle and positive-exchange gates and
never opens or closes the valve.

The daemon's maintenance tick restores configuration/counters after connection
changes and expires unresolved reservations without replay. Daytime requests do
not wait for a valve report before sending. A fresh idle observation is required
for a new open; routine report counters never reseed command counters. Unlike
HTV405, HTV145 has no proven idle-close-zero anchor: lost counter certainty requires
new positive command evidence. A missing idle report after the planned duration
plus 30 seconds raises an anomaly without transmitting another command.

Report ACK builders accept captured family bytes `82`, `85`, `86`, reverse the
route, echo byte 13, OR byte 14 with `40`, and write `01 00 01` for state reports
or `00 80 00` for summaries. The runtime uses residue `4f03`, a 320-symbol wake,
and a provisional 40 ms post-reception transmit deadline. The ten stock ACKs
include both ordinary residues; the selected local timing/residue still needs
physical qualification. Session summaries update historical usage/duration only;
they cannot clear current watering or confirm a pending close. Result 3 layouts
with byte 17 `00` or `10` neither authenticate a counter nor prove physical idle.
