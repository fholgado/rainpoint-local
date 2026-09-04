# HTV145FRF single-zone valve protocol

The `HTV145FRF` is a single-zone valve with a pairing and command protocol
distinct from the HTV405. Receive-side telemetry, duration, water usage, and
categorical battery state are decoded. Local enrollment remains research-only:
the valve now accepts the local association and first ordinary continuation,
but the delayed configuration and terminal stages are not yet complete.

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
| Ordinary stage-1 reply | Payload, carrier, symbol rate, timing, and final low-tone hold now match stock; `.8` measured 149.5 us versus 160.5 us stock and produced no immediate stage-1 retry | Intermediate behavior reproduced, but not independently sufficient to prove acceptance |
| Delayed stage-1a configuration | Valve must emit `81 50` and advance | Candidates `.4`--`.8` retained two completed steps but produced no `81 50`; not accepted |
| Stages 3--5 and retained telemetry | Each next addressed request, then ordinary paired telemetry | Not yet tested locally |

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
probe then showed that the test node lacks continuity from radio GDO2 to ESP32
GPIO25, so it cannot consume the CC1101 serial clock without a wiring change.
A separate raw-FIFO calibration avoids that wire and successfully streams the
complete `300` wake bytes plus `38` frame bytes to `TXFIFO_UNDERFLOW`. Its
impossible endpoint prevents enrollment. SDR waveform equivalence remains a
required gate before that transmitter is used in a live pairing candidate.

The packed clock/date marker positions are branch-specific. Counter 0 carries
its marker in time-low bit 7. Counter 2 carries it in time-high bit 7 and in
date-low bit 7. All remaining clock bits retain their FAT/DOS meaning.

The frequency correction is node-calibration evidence, not a universal device
constant. Absolute centers from separate SDR sessions are insufficient; the
gateway response must be normalized against the valve request oscillator in
the same capture.

Therefore no HTV145 local enrollment profile is advertised as supported until
the delayed configuration and remaining stages complete twice without changing
the frozen prefix. The reusable investigation method is documented in
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

One logical stock command is three byte-identical RF attempts at approximately
`0`, `0.729210`, and `1.668479` seconds. The controller waits for a matching
response; it does not issue repeated logical opens in rapid succession.

The response echoes the command sequence, and the next command advances modulo
the five-bit field. Only a passive stock command or a matching response to a
pending local command can synchronize or advance that counter; periodic
telemetry cannot.

Local commands have not been accepted by the physical valve, so transmit is
not exposed as supported functionality.

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
- Battery and usage evidence:
  `research/fixtures/htv145_cloud_rf_battery_usage_correlation_20260824.json`
- Evidence ledger: [`../research/VALVE_PROTOCOL_STATUS.md`](../research/VALVE_PROTOCOL_STATUS.md)
- Chronology: [`../research/RF_CAPTURE_NOTES.md`](../research/RF_CAPTURE_NOTES.md)
