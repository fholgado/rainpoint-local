# HTV145FRF single-zone valve protocol

The `HTV145FRF` is a single-zone valve with a pairing and command protocol
distinct from the HTV405. Receive-side telemetry, duration, water usage, and
categorical battery state are decoded. Local enrollment remains research-only:
the valve accepts the local association, delayed configuration, and following
continuation through the stage-4 request. The terminal stage remains unproven.

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

The packed clock/date marker positions are branch-specific. Counter 0 carries
its marker in time-low bit 7. Counter 2 carries it in time-high bit 7 and in
date-low bit 7. All remaining clock bits retain their FAT/DOS meaning.

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

Association branch markers are:

| Profile | Open marker | Close marker |
|---|---|---|
| Selector 5 | `0x10` | `0x90` |
| Selector 6 | `0x90` | `0x10` |

Duration extension byte 21 is determined only by the packed duration value,
not by this selector branch.

Both stock opens and closes use **2,400 alternating wake symbols** (2,399
transitions before sync), about `135.36 ms` including the frame. Candidate
`.15` used only 1,200 symbols; its earlier silence did not test the stock wake.
The accepted selector-6 opens use trailer residue `c713`, while closes use
`4f03`; preserve them separately in the association profile.

One logical stock command is three byte-identical RF attempts at approximately
`0`, `0.729210`, and `1.668479` seconds. The controller waits for a matching
response; it does not issue repeated logical opens in rapid succession.

An accepted open response advances the command sequence modulo the five-bit
field; an accepted close retains it. The stock sequence is open `81`, close
`82`, open `82`, close `83`. Only a passive stock command or a matching response to a
pending local command can synchronize or advance that counter; periodic
telemetry cannot.

Local command acceptance has not been demonstrated, so transmit is not exposed
as supported functionality. Following the original `.15` trial, candidate `.16`
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
