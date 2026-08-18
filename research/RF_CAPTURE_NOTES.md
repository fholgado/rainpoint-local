# RF capture evidence

This is a concise research record for the conclusions promoted into
[`../PROTOCOL.md`](../PROTOCOL.md). It intentionally keeps chronology and
correlation details out of the primary protocol reference.

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
formulas promoted into `PROTOCOL.md`; notably, byte 14 correlated with zone in
the opening subset but changed on stop frames and is not part of the stable
zone formula.

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
09:37:12. Its following `92 0d` bytes do not match the local builder's forced
`12 8d` flag layout, and other nearby bytes also vary across the two successful
stock assignments. The earlier hypothesis that only reply timing prevented
acceptance is therefore superseded: assignment-field semantics are now the
primary lead. Signal-grabber file timestamps are too coarse to determine the
successful stock turnaround precisely, so the next controlled enrollment
should use one continuous IQ recording and provide a third assignment sample.

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

## Current capture guidance

- Use 2.0 Msps centered at 433.7 MHz for broad passive operation.
- Use a focused center near 433.15 MHz when diagnosing lower-channel Left Bed
  reports.
- Keep the original IQ whenever a new field or device is identified.
- Correlate irrigation actions against Home Assistant Recorder and include
  unrelated irrigation devices so their traffic is not mislabeled.
- Treat receiver placement and antenna geometry as part of the system; a valid
  packet can be missed even when the protocol decoder is correct.
