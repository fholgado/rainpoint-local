# RF capture evidence

This is the chronological research record for conclusions promoted into the
current definitions under
[`../protocol_documentation/`](../protocol_documentation/). It intentionally
keeps chronology and correlation details out of those normative references.

Raw IQ captures are retained locally and are not committed because they can be
large and may include unrelated nearby traffic.

## Initial local decode — 2026-08-06

A Nooelec NESDR receiver captured HCS026FRF and HTV145FRF traffic. The first
250 ksample/s recording centered at 433.7 MHz clipped much of the signal, but
it aligned Left Bed and Right Bed reports with independently observed state.

A corrected 1.024 Msps recording centered near 434 MHz captured a complete
short valve cycle. Replaying the IQ through `rtl_433` established:

- 2-FSK PCM with 50-microsecond / 20-ksymbol/s timing,
- sync word `79f4882f28`,
- 38-byte normalized frames,
- approximately 320-, 1,200-, and 2,400-symbol wake/prefix forms, and
- request, response, and confirmation bursts around open and close actions.

The useful capture family was retained as files `g004` through `g009`. Their
SHA-256 values were recorded during analysis, but file names and absolute
household action times are not part of the protocol specification.

## Physical-layer refinement — 2026-08-07

FFT and pulse analysis across 25 clean wide-band captures refined the initial
rtl_433 tolerance-based timing. Dominant runs were 100 samples at 2.0 Msps,
establishing a 50.0 microsecond symbol and 20.0 ksymbol/s rate. Both observed
RF channels used essentially the same 79.997 kHz tone separation, or +/-40.0
kHz deviation.

Twenty-one lower-channel samples averaged 433.142217 MHz; four upper-channel
samples averaged 434.241535 MHz. Their approximately 1.100 MHz separation and
per-device offsets support nominal centers of 433.140 and 434.240 MHz, with the
remaining error attributed to device and RTL-SDR oscillators. Typical 95%
occupied bandwidth was 100--105 kHz. The 99% result was usually 180--207 kHz
and varied with CU8 clipping, supporting a conservative 203.125 kHz initial
CC1101 receive bandwidth.

Several Front Yard Sensor 1 reports also exposed a repeatable 2,400-symbol
prefix. It begins with a variable constant-tone interval and ends with a long
alternating sequence before sync. This joins the approximately 320-symbol
short and 1,200-symbol long forms and makes ordinary CC1101 packet-mode
preamble generation insufficient for faithful future transmission.

## Valve endpoint and action correlation

Repeated controlled cycles assigned the `b42d008f` / `b9840280` exchange to
the RainPoint valve and separated it from an unrelated irrigation system.
Requests preceded the independently recorded state change, immediate responses
followed, and later confirmation frames surrounded the transition.

Three cycles produced transaction bytes `9b`, `9c`, and `9d`; later cycles
continued `9e`, `9f`, then wrapped to `80`. Each cycle echoed its transaction
byte across request and response frames.

Exact open or close packets were sometimes repeated about 0.7 seconds later,
including an identical trailer. This established deterministic per-frame
encoding and the absence of a per-burst nonce.

Subsequent corpus analysis established CRC-CCITT (`0x1021`, initial value zero)
over normalized bytes 0--35. Of 705 usable unique ordinary frames, 687 (97.4%)
had transmitted-trailer XOR residues `0xc713` or `0x4f03`; the other 18 were
visibly clipped or corrupted. Both residues occurred across prefix forms
and in open/close commands, leaving only the residue-selection rule unresolved.

### HTV405FRF crossed zone trial — 2026-08-17

An isolated, unpressurized HTV405FRF (FCC ID `2AWDBHTV145FRF`) was enrolled
through the stock gateway. Its factory endpoint `14a98013` became paired
endpoint `94a98013`; the same high-bit identity transition previously observed
on HCS026 sensors therefore also applies to this valve sample.

The stock app exercised every zone at both 60 and 120 seconds. The retained
trial contains all eight openings, manual or automatic stops for all four
zones, and the later closed-state reports. All four ports shared the single
paired endpoint. The crossed values established the selector and duration
formulas now defined in
[`../protocol_documentation/htv405frf.md`](../protocol_documentation/htv405frf.md).
Notably, byte 14 correlated with zone in the opening subset but changed on stop
frames and is not part of the stable zone formula.

The first 60-second trials were allowed to time out. Later openings were closed
after capture. Automatic and manual paths used the same stop-body signature,
then emitted a separate closed-state report roughly 1--9 seconds later. The
local trial bundle is `four-zone-stock-enrollment-20260817`; raw household
events remain ignored while the generalized protocol fixtures are committed.

### HTV405FRF isolated re-enrollment — 2026-08-17

Deleting and re-enrolling only the dry test valve produced a raw 2.0 Msps IQ
archive spanning the factory announcement, stock-gateway assignment, and the
complete paired message sequence through message `09`. The factory endpoint
`14a98013` again became `94a98013`, with companion route `39840280`.

Ordinary demodulation recovered the lower-channel valve messages but initially
missed the first gateway reply. That burst had the expected 31 ms envelope,
but used a biased tone pair near 433.471 and 433.541 MHz. A threshold and clock
search recovered 1,804 agreeing candidates for the exact valid frame:

```text
79f4882f2894a980133984028080c08585030670009d97118d00808000000000000000002f8c
```

Later gateway replies moved near 434.351 MHz and returned to the ordinary
approximately 80 kHz tone spacing. The compact generalized transcript is
committed as `fixtures/htv405_gateway_pairing_replies.json`; the verified
111 MB raw capture remains ignored locally. The temporary raw-capture add-on
was removed after copying and checksum verification, and the production add-on
was restored to normal RTL-SDR operation.

### HTV405FRF local-assignment comparison — 2026-08-18

Near-field IQ captures compared cached-calibration firmware `0.12.4` with a
fresh successful stock-gateway enrollment. The local reply measured near
433.505847 MHz with the correct approximately 70 kHz initial tone separation.
Cached CC1101 calibration reduced the request-to-reply silent gap to roughly
0.7--0.9 ms. The valve nevertheless continued sending factory announcements,
so it rejected the first assignment before entering the paired exchange.

After deleting the valve from the HomGar app and enrolling it again, the stock
gateway sent this assignment:

```text
79f4882f2894a980133984028080c085850302f000a64c920d010080000000000000000008fa
```

The valve's very next frame used paired endpoint `94a98013` and route
`b9840280`. The first three routine stock replies exactly matched the existing
fixture, which isolates the remaining uncertainty to the initial assignment.
The rejected local assignment was:

```text
79f4882f2894a980133984028080c0858503067000b84c128d0080800000000000000000948d
```

The new stock sample's `a6 4c` bytes are the ordinary packed local time
09:37:12. Its surrounding marker layout differs from the selector-6 fixture,
but a later continuous capture established that this is a coherent selector-2
branch rather than evidence that the selector-6 local template is malformed.

The 90-second continuous 2.0 Msps enrollment capture placed the factory
announcement at 26.917473--26.948703 seconds and the accepted stock assignment
at 26.999359 seconds. The real receive-complete gap is therefore 50.656 ms,
not the approximately zero-delay estimate derived from separate signal-file
close timestamps. That timing error explains why carrier-correct firmware
`0.12.4` was rejected immediately.

The third successful assignment was:

```text
79f4882f2894a980133984028080c0858503027000e0ce920d01008000000000000000002d3c
```

It again selected branch 2. Clearing the marker bit from `ce` produces packed
local time 09:55:00, exactly matching the continuous timeline. Subsequent
valve request bodies used `82` rather than the selector-6 fixture's `86`, and
routine stock replies appeared on the selector-2 channel branch. The next
local candidate therefore retains the independently successful selector-6
template, removes the sensor-specific four-minute clock lead, and waits 50 ms
after receive completion before starting its cached frequency hop.

That 0.12.5 trial produced a local assignment about 51.4 ms after request
completion, yet the valve remained on factory endpoint `14a98013`. With timing,
carrier, deviation, and waveform now independently bounded, 0.12.6 moves the
entire experimental enrollment state machine to the selector-2 branch seen in
the two most recent accepted stock pairings. The initial marker layout, request
marker `82`, and both selector-2 reply channels are treated as one unit.

The decoded 0.12.6 local reply was
`79f4882f2894a980133984028080c08585030270009cd5920d0100800000000000000000c863`.
It retained selector 2 and the `0x4f03` trailer family, and its carrier appeared
near 433.550 MHz. Its packed time decoded to 10:44:56, however, roughly four
minutes ahead of the physical attempt even though the gateway command contained
the current time. The 0.12.7 trial moves the firmware elapsed-time anchor until
after transmit-frequency preparation and changes no other protocol variable.

The decoded 0.12.7 local reply was
`79f4882f2894a980133984028080c0858503027000e0d7920d01008000000000000000007bc1`.
Its packed time decoded to 10:59:00, exactly matching the physical attempt, and
all non-clock payload bytes matched the accepted 09:55 selector-2 assignment.
The valve still remained on factory endpoint `14a98013`, while the node reported
one completed step. This eliminates the node clock-anchor defect. A continuous
local-attempt capture is now required to compare the sub-millisecond response
gap and PA/wake envelope with the accepted 50.656 ms stock exchange; close times
from separate signal-grabber files are not sufficient for that comparison.

That continuous local capture recovered a second valid 0.12.7 reply,
`79f4882f2894a980133984028080c0858503027000c6d9920d0100800000000000000000d0b2`,
whose 11:10:12 clock again matched the attempt. Using the same power-envelope
detector, the accepted stock timeline measured 81.9 ms request-start to
reply-start while the local timeline measured 83.2 ms. Firmware 0.12.8 changes
only the software delay from 50 ms to 49 ms, targeting a physical reply about
0.3 ms later than stock instead of 1.3 ms later.

The 0.12.8 trial was still rejected after one reply. A like-for-like spectral
comparison then corrected the stored selector-2 initial center. The local reply
measured 433.546375 MHz and the accepted stock reply measured 433.556430 MHz;
their adjacent valve requests measured 433.141757 and 433.141711 MHz, only 46
Hz apart. The approximately 10.055 kHz reply difference is therefore real, not
SDR oscillator drift. Tone separation and deviation matched within tens of Hz.
Firmware 0.12.9 raises only the initial selector-2 command center by 10.055 kHz
and leaves its routine reply channel untouched.

## Multi-channel sensor discovery

A 1.024 Msps window near 434 MHz retained upper-channel notification traffic
but missed some data-rich Left Bed and Front Yard reports. Expanding to 2.0
Msps around 433.7 MHz exposed traffic down to roughly 433.08 MHz.

The wider and focused recordings assigned:

| Sensor | Endpoint | Confirmed values |
|---|---|---|
| Right Bed | `9ce58024` | 58--64% |
| Left Bed | `c4e50024` | 58%, later 12% |
| Front Yard Sensor 1 | `ce628024` | 59% |
| Front Yard Sensor 2 | `d1e28024` | 78--79% |

These captures also revealed two moisture-field positions with the same packed
half-value plus odd-flag representation.

## Scheduled watering capture — 2026-08-07

The scheduled 17-minute run produced `fe 01` in the open request. The Home
Assistant recorder independently reported 1,020 seconds at the same moment.
Earlier controlled four-minute commands produced `f8 00`, while the recorder
reported 240 seconds. Together with the earlier one-minute `9e 00` command,
these establish a two-second unit with bit 7 of the low byte forced on rather
than a plain little-endian integer.

Fourteen retained valve commands included seven opens and seven closes. Twelve
had an observed valve-to-hub response within three seconds. Ten responses
arrived in 0.372--0.380 seconds and two in 1.062--1.083 seconds. A future local
controller should wait at least 1.5 seconds for the initial acknowledgement
and must not immediately retry an open operation.

A scheduled 17-minute run retained the pre-run, open, watering, close, and
post-run sequence. The open request contained `fe 01` at normalized offsets
19--20, which decodes as:

```text
little_endian(fe 01) * 2 = 1020 seconds
```

The valve response carried `ec 03` in the packed usage field. It independently
matched 175.2 liters (46.2829435731476 US gallons). Shorter historical sessions
provided the additional 0.9, 1.0, 2.8, 10.2, and 16.6 liter fixtures used by
the decoder tests.

## Controlled Left Bed sample — 2026-08-07

Moving the receiver antenna close to the Left Bed sensor and removing the probe
from soil produced a displayed value of 12%. A focused 433.15 MHz / 1.024 Msps
capture decoded:

```text
79f4882f28b9840280c4e500240981820385c406000000000000000000000000000000004cea
```

The local decoder returned 12%, `rainpointd` stored 12%, and Home Assistant's
local `sensor.left_bed_soil_moisture` entity updated to 12% four seconds later.
The recording had approximately 15 dB analyzer SNR. This established that the
earlier unavailable state was a reception problem rather than a distinct
packet format.

## Product metadata correlation — 2026-08-07

The HomGar product catalog assigns product code 72 (`0x48`) to HCS021FRF,
HCS024FRF, and HCS026FRF. A scan of all 2,189 events retained by the deployed
gateway found no ordinary telemetry containing the exact model codes for the
hub (`0x0121`), valve (`0x012e`), or sensor (`0x013d`). Those identifiers are
therefore pairing/control-plane candidates, not established telemetry fields.

The scan did find one coherent extended Front Yard Sensor 2 sequence:

```text
10:36:56.394  79f4882f28 b9840280 d1e28048 2c03040f0a884f...
10:36:56.574  79f4882f28 d1e28024 39840280 9641810001...
```

The `0x48` endpoint suffix matches the HCS02x product code. In the first body,
`88 4f` follows HomGar's compact TLV grammar: type 10 (`STA_RH`) with a
one-byte value of `0x4f`, or 79%. Normal Front Yard Sensor 2 reports immediately
before and after this sequence also decoded to 79%. This supplies a confirmed
third HCS026 moisture layout and explains at least one previously strange
packet without making the cloud representation a runtime dependency.

Another compact-status frame followed a normal Right Bed 57% report by 835
milliseconds. Its body contained `0a 88 39 e0 b1`, which decodes as type-10
moisture 57% and signed type-32 RSSI -79 dBm. Both matched the independently
observed Right Bed cloud state. Because that frame's routing fields were
`b9000101` and `685a011f`, not the established Right Bed endpoint, the local
decoder retains the decoded values for research but does not yet apply them to
the device.

Reanalysis of all 2,900-plus persisted events found two earlier instances of
the same compact `88 39 e0 b1` values. Each arrived within 1.040 seconds of a
normal Right Bed 57% report. Those instances used a slot-like `0x0b` before
the type-10 header and also had unstable routing fields. Three independent
timing/value matches associate this compact family with Right Bed, but the
unstable route still prevents safe automatic assignment.

The latest expanded corpus contained 1,456 unique ordinary frames with valid
residues: 732 used `0xc713` and 724 used `0x4f03`. Single-bit, pairwise-XOR,
route, message-counter, and global-alternation tests failed to predict the
selector above near-chance accuracy. This materially narrows the remaining
possibilities to omitted transmitter state, a nonlinear rule, or two checksum
states accepted without an exposed selector.

No retained HCS026 RF frame contained the catalog-implied `dc 01` one-byte
battery TLV signature. All 358 formerly labeled companion heartbeats used
`... 41 81 00 01 00 ...`, but later same-file IQ analysis established these as
stock-gateway acknowledgements 177--188 ms after sensor reports. Offset 17 is
therefore not a battery candidate. Supported battery state comes from the
marker-relative field validated in controlled Sensor A/B tests.

## HTV405FRF successful local enrollment — 2026-08-19

Unified firmware `0.14.0-combined.1` physically enrolled the isolated valve
after the stock-app registration was removed and the stock gateway was
disconnected. A bounded 433.7 MHz / 2.0 Msps signal-grabber run retained the
factory request, local assignment, first two local routine replies, and the
subsequent paired traffic. The valve gave the white success flash and changed
from factory endpoint `14a98013` to paired endpoint `94a98013`.

The local assignment decoded as:

```text
79f4882f2894a980133984028080c0858503027000bc8c930d01008000000000000000006d56
```

Its measured center was 433.556537 MHz, only 107 Hz above the independently
accepted stock selector-2 assignment at 433.556430 MHz. Its packed clock
matched the physical attempt. The first two routine replies decoded cleanly at
433.476260 MHz. The selected node reported three completed replies, while the
valve continued through paired sequence 6 in the bounded capture.

An immediately preceding attempt with the same firmware and association inputs
was rejected after reply 1. No protocol or frequency constant changed between
the attempts, so enrollment still has an intermittent RF/reception component.
Completion is now based on a strict paired-link frame seen by any receiver
during the active session after the selected node reports at least one reply.
This avoids both failure modes encountered during testing: requiring one node
to observe the entire stock transcript, and treating an old persistent valve
registry entry as proof of a new enrollment. The compact evidence is retained
in `fixtures/htv405_local_pairing_success.json`; backup slug `b8fa839c` keeps
the ignored IQ files.

## HTV405FRF successful local control — 2026-08-23

The isolated dry valve accepted a Zone 1 gateway command only after the
transmitter moved from the historical selector-6 control carrier to the
selector-2 carrier chosen by its local enrollment. The accepted 120-second
open used controller counter 3 and was followed immediately by a valid
high-channel watering response, then by ordinary lower-channel watering and
countdown reports. The valve automatically returned to idle after 120 seconds.

An idempotent close at counter 4 produced a valid high-channel idle response.
Firmware `0.14.0-valve-control-probe.34` then completed a second independent
cycle: open at counter 5, automatic counter advance from the authenticated
response, and close at counter 6 without manual counter input. The close was
confirmed by both the immediate high-channel response and later lower-channel
idle reports.

This falsifies the earlier hypothesis that the lower telemetry sequence can be
mapped to the controller counter by a fixed offset. The controller counter is
advanced only by a matching command response. It also proves that operation
byte `0x90` means open and `0x10` means close; it is not a primary/repeat bit.
The exact generalized frames and carrier findings are promoted into
[`../protocol_documentation/htv405frf.md`](../protocol_documentation/htv405frf.md)
and frozen in firmware protocol tests.

### Retained crossed-zone re-audit — 2026-08-23

The persistent gateway journal still contained 79 frames for paired valve
endpoint `94a98013` across the August 17 trial. Sixteen CRC-valid lower-channel
reports were promoted into
`fixtures/htv405_crossed_zone_reports_20260817.json`: open and close for every
zone at both 60 and 120 seconds. The decoder reproduced the complete crossed
matrix exactly.

No CRC-valid high-carrier gateway command for Zones 2--4 survived in that
journal. The only high-carrier-looking candidate, event 73432, used unsupported
residue `0xf3e0` and is not safe construction evidence. Zone 1 remains the sole
transmit-enabled command body until a future focused high-carrier capture.

## Current capture guidance

- Use 2.0 Msps centered at 433.7 MHz for broad passive operation.
- Use a focused center near 433.15 MHz when diagnosing lower-channel Left Bed
  reports.
- Keep the original IQ whenever a new field or device is identified.
- Correlate irrigation actions against Home Assistant Recorder and include
  unrelated irrigation devices so their traffic is not mislabeled.
- Treat receiver placement and antenna geometry as part of the system; a valid
  packet can be missed even when the protocol decoder is correct.

## Promoted protocol chronology — 2026-08-10 through 2026-09-01

The monolithic protocol reference originally mixed these dated experiments
with the current wire definition. They are retained here after the normative
material was split into `protocol_documentation/`. Exact bytes remain in the
linked fixtures and executable protocol tests.

### HCS02x enrollment, battery, recovery, and ACKs — 2026-08-10 to 2026-08-15

- Two HCS026 test sensors established that a factory endpoint with suffix `24`
  becomes paired by setting the first-byte high bit. The paired moisture value
  matched both the sensor LCD and RainPoint app.
- Repeated stock and local enrollment captures reduced the accepted sensor
  exchange to three gateway replies followed by a terminal sensor frame. The
  stock RainPoint gateway had to be powered off to prevent competing replies.
- A bridged-cell low-voltage experiment changed both the LCD indicator and RF
  categorical battery bit; restoring normal batteries cleared both. This is
  the evidence behind the `100%` normal / `10%` low presentation rather than a
  continuous voltage percentage.
- Power-cycle and dormant-sensor trials showed that a known sensor can repeat a
  strict factory announcement or paired recovery sequence without becoming a
  new logical device. Recovery now preserves its endpoint and ACK owner.
- Long-running comparison with the stock gateway revealed the missing liveness
  requirement: routine moisture reports need a device-specific ACK roughly
  177--188 ms after sync. Once the custom nodes reproduced that ACK, the test
  sensors continued periodic reporting instead of going dormant.

Reference evidence:
`fixtures/hcs026_gateway_pairing_replies.json`,
`fixtures/hcs026_pairing_battery.json`, and the pairing/ACK regression tests.

### Cross-layer metadata and valve-field correlation — 2026-08-24

The RainPoint app and cloud integration were used only as correlation oracles
while the SDR retained the actual RF frames:

- App Device Address was falsified as a generic RF selector. Observed examples
  include HCS026 address `2` on selector `4`, HTV405 address `6` on its stock
  selector-6 profile, and HTV145 address `1` on selector `6`.
- HCS product code `0x48` was correlated with the shared HCS021/HCS024/HCS026
  capability family. Routine moisture frames still cannot identify the exact
  retail model.
- The HTV145 low-battery valve established its categorical battery bit and the
  three-byte water-usage formula. Terminal summaries established the final
  usage and duration offsets but contained no battery field.
- A cloud-driven HTV405 matrix covered all four zones and timed/early-stop
  operation. It confirmed mutually exclusive zones, automatic stop, and the
  distinction between command counters and periodic telemetry counters.
- Stock HTV405 routine reports and replies established the valve ACK envelope
  later adopted by the custom node owner.

Reference evidence:
`fixtures/app_device_metadata_rf_correlation_20260824.json`,
`fixtures/hcs026_cloud_rf_correlation_20260824.json`,
`fixtures/htv145_cloud_rf_battery_usage_correlation_20260824.json`,
`fixtures/htv145_cloud_rf_terminal_summary_correlation_20260824.json`,
`fixtures/htv405_stock_cloud_control_matrix_20260824.json`, and
`fixtures/htv405_stock_routine_ack_20260824.json`.

### Generated custom-gateway identity and valve enrollment — 2026-08-25 to 2026-08-26

- HTV405 was enrolled with a generated custom controller/companion identity
  while retaining its physical valve endpoint. This proved that copying the
  stock gateway identity is unnecessary and provided the migration/coexistence
  identity model.
- The accepted generated enrollment ended on a strict paired-link frame even
  when the custom exchange did not observe the stock transcript's final `9a`
  tail. The command sequence was initialized independently at `1`.
- Same-identity repair and retained-takeover experiments showed that enrollment
  sequence bytes do not reveal the next command counter. Control still depends
  on durable authenticated command responses.
- Stock HTV145 enrollment was captured as a distinct six-stage exchange plus a
  delayed long-wake configuration transmission. Reusing HTV405's 18-stage
  state machine was decisively rejected.

Reference evidence:
`fixtures/htv405_generated_identity_pairing_20260825.json`,
`fixtures/htv405_same_identity_repair_counter_20260826.json`,
`fixtures/htv405_retained_takeover_20260824.json`, and
`fixtures/htv145_factory_enrollment_20260825.json`.

### HTV145 branch and timing refinement — 2026-08-28 to 2026-09-01

- A second accepted stock HTV145 enrollment exposed a selector-6 branch with a
  different counter, carrier, delayed-config marker, and residue progression.
  It proved that branch fields form a coherent profile and cannot be varied
  independently.
- Stock control captures established three byte-identical attempts per logical
  command and confirmed the branch-specific open/close marker inversion.
- Prelude, retained-identity, carrier-correction, and scheduler probes each
  improved one measured dimension but were rejected before a complete local
  association. The final probe-17 assignment was structurally and temporally
  plausible on both captured branches but still did not elicit stage 1.
- These negative results are preserved to prevent future work from repeating
  small timing tweaks without a new discriminating hypothesis.

Reference evidence:
`fixtures/htv145_later_sweep_stock_enrollment_20260828.json`,
`fixtures/htv145_selector6_stock_duration_commands_20260828.json`,
`fixtures/htv145_prelude_calibration_matrix_20260830.json`, and
`fixtures/htv145_probe17_scheduler_rejection_20260901.json`.

### HTV405 duration and command-counter continuity — 2026-08-31 to 2026-09-01

- Transmitted commands around the low-byte boundary proved that HTV405 duration
  adds a two-byte `0x80` bias. The earlier bitwise-OR interpretation produced
  incorrect long watering times and was removed.
- A generated-identity session then established the response-driven sequence:
  fresh pairing started at `1`; accepted opens advanced the next value; closes
  retained it; gateway and node restarts preserved it; and a later open
  continued from the persisted value.
- Neither periodic telemetry nor a speculative close supplied the command
  counter. Missing responses now remain failures rather than optimistic state
  updates.

Reference evidence:
`fixtures/htv405_beta10_candidate9_on_air_20260831.json` and
`fixtures/htv405_generated_identity_counter_continuity_20260901.json`.

### HTV145 documented reset isolation — 2026-09-01

- Four fresh alkaline cells were installed, then removed for more than ten
  seconds. The timer button was held while the cells were reinstalled until
  rapid red flashing began, matching the manufacturer's reset gesture.
- The stock RainPoint gateway was off and all three custom radio nodes were
  gateway-verified receive-only. The 180-second, 2.0 Msps capture therefore
  contains no custom or stock gateway replies.
- Factory counter `0` appeared at 34.580350 seconds and counter `3` at
  46.080300 seconds. No assignment, paired-route request, or configuration
  response was recovered anywhere in the continuous capture.
- The visible LED sweep did not look meaningfully different from ordinary
  pairing, but the absence of retained paired traffic proves that LED behavior
  is not a sufficient lifecycle classifier.
- The shared NumPy discriminator reduced complete three-carrier analysis from
  a projected 40--50 minutes to about 11 seconds without changing the
  dependency-free fixture path.

Reference evidence:
`fixtures/htv145_factory_reset_stock_off_20260901.json`.
