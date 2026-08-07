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

- 2-FSK PCM with 48-microsecond symbols,
- sync word `79f4882f28`,
- 38-byte normalized frames,
- 320-bit and 1,201-bit preamble forms, and
- request, response, and confirmation bursts around open and close actions.

The useful capture family was retained as files `g004` through `g009`. Their
SHA-256 values were recorded during analysis, but file names and absolute
household action times are not part of the protocol specification.

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
visibly clipped or corrupted. Both residues occurred with both preamble forms
and in open/close commands, leaving only the residue-selection rule unresolved.

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

No retained HCS026 RF frame contained the catalog-implied `dc 01` one-byte
battery TLV signature. However, all 358 companion heartbeats in the analyzed
window used `... 41 81 00 01 00 ...`, with normalized offset 17 fixed at
`0x01`. During the same period, all 5,485 cloud-reference reports contained
`dc 01` and every stock battery entity reported normal/100%. Offset 17 is now
the leading RF battery-status candidate, but a controlled normal-to-low
transition remains necessary before promotion to a supported field.

## Current capture guidance

- Use 2.0 Msps centered at 433.7 MHz for broad passive operation.
- Use a focused center near 433.15 MHz when diagnosing lower-channel Left Bed
  reports.
- Keep the original IQ whenever a new field or device is identified.
- Correlate irrigation actions against Home Assistant Recorder and include
  unrelated irrigation devices so their traffic is not mislabeled.
- Treat receiver placement and antenna geometry as part of the system; a valid
  packet can be missed even when the protocol decoder is correct.
