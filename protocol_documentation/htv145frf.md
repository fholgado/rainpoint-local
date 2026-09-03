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
| 1a | no request | Long-wake config `81 90 01 01` to valve route, 2,400-symbol stock wake, about 2,952.55 ms after the normalized stage-1 request end |
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
| Ordinary stage-1 reply | Valve stops retrying the stage-1 request after the response carrier was corrected to within 257 Hz of stock | Accepted once; prefix remains unchanged |
| Delayed stage-1a configuration | Valve must emit `81 50` and advance | Not yet accepted |
| Stages 3--5 and retained telemetry | Each next addressed request, then ordinary paired telemetry | Not yet tested locally |

The white LED is the most difficult and useful breakpoint: it is positive
device-side proof that the initial association was accepted. It is not proof
of complete enrollment. Once it appears, the addressed stage-1 request gives
the investigation a deterministic request/reply loop instead of silence.

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

The candidate-.3 ordinary response measured 434.351533 MHz versus stock at
434.351790 MHz and eliminated the valve's retries. Its delayed configuration
was nevertheless only 132.119 ms on-air versus stock at 135.361 ms and did not
elicit `81 50`. Candidate `.4` changes only that research-only long wake from
2,400 requested symbols to 2,464 so the emitted waveform should reproduce the
stock 2,400-symbol duration. This candidate is built and installed but has not
received a physical verdict.

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
- Command and duration evidence:
  `research/fixtures/htv145_selector6_stock_duration_commands_20260828.json`
- Battery and usage evidence:
  `research/fixtures/htv145_cloud_rf_battery_usage_correlation_20260824.json`
- Evidence ledger: [`../research/VALVE_PROTOCOL_STATUS.md`](../research/VALVE_PROTOCOL_STATUS.md)
- Chronology: [`../research/RF_CAPTURE_NOTES.md`](../research/RF_CAPTURE_NOTES.md)
