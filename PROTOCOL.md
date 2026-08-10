# RainPoint 433 MHz RF protocol

This is the primary protocol reference for the RainPoint devices supported by
this project. It describes behavior demonstrated by local RF captures. Dated
capture notes and cloud-side observations live under `research/` and are not
part of the protocol contract.

## Protocol at a glance

| Property | Confirmed value |
|---|---|
| Devices tested | HTV145FRF valve, HCS026FRF soil sensor, HWG023WBRF-V2 hub |
| Band | 433/434 MHz |
| Modulation | 2-FSK PCM |
| Symbol width | 50 microseconds, 20.0 ksymbols/s |
| Sync word | `79 f4 88 2f 28` |
| Normalized frame | 38 bytes |
| Prefix/wake forms | About 320, 1,200, or 2,400 symbols before sync |
| Receive implementation | RTL-SDR with `rtl_433` |
| Planned transceiver | ESP32 with a 433 MHz CC1101-class radio |

The working `rtl_433` flex decoder is:

```text
n=RainPoint,m=FSK_PCM,s=50,l=50,r=50000,bits>=620,match={40}79f4882f28
```

A 2.0 Msps capture centered at 433.7 MHz has been the most useful general
receive configuration. Installed-device energy has appeared across roughly
433.08--434.38 MHz, so narrower captures can miss valid report types.

### Measured RF parameters

FFT and pulse analysis of 25 clean 2.0 Msps CU8 captures produced:

| Parameter | Measured result |
|---|---:|
| Symbol rate | 20,000 symbols/s |
| Symbol period | 50.0 microseconds; dominant runs were 100 samples at 2.0 Msps |
| Tone separation | 79.997 kHz average |
| Frequency deviation | approximately +/-40.0 kHz |
| Lower channel center | 433.142217 MHz mean across 21 captures |
| Upper channel center | 434.241535 MHz mean across 4 captures |
| Channel separation | approximately 1.100 MHz |
| 95% occupied bandwidth | typically 100--105 kHz |
| 99% occupied bandwidth | typically 180--207 kHz; sensitive to CU8 clipping |

The per-device lower-channel centers differ by several hundred hertz, while
the two channel groups are almost exactly 1.100 MHz apart. The working nominal
centers are therefore `433.140 MHz` and `434.240 MHz`; the additional measured
1--3 kHz is consistent with transmitter and RTL-SDR oscillator error. Both
channels use the same approximately 80 kHz tone separation.

The short prefix is approximately 320 alternating symbols (16 ms). Long
wake/command traffic uses approximately 1,200 alternating symbols (60 ms).
A repeatable 2,400-symbol sensor form lasts 120 ms and begins with a variable
constant-tone interval before a long alternating suffix. The 38-byte frame
itself lasts 15.2 ms. Pulse-slicer start alignment can move the reported prefix
count by a few symbols, so these durations are more portable than a particular
decoded offset.

### Initial CC1101 receive profile

For a CC1101 module with a 26 MHz crystal, the first receive-only prototype
should use this profile and validate it against the RTL-SDR before refinement:

| Setting | Candidate value | Actual result |
|---|---:|---:|
| Modulation | 2-FSK | no Manchester, whitening, FEC, or hardware CRC |
| `MDMCFG4` | `0x89` | 203.125 kHz RX bandwidth; data-rate exponent 9 |
| `MDMCFG3` | `0x93` | 19.9852 ksymbols/s |
| `MDMCFG2` | `0x02` | 2-FSK with exact 16/16 sync qualification |
| `DEVIATN` | `0x45` | 41.2598 kHz expected deviation |
| `FREQ2/1/0` | `10 a8 c3` | 433.139862 MHz base channel |
| `MDMCFG1.CHANSPC_E` | `1` | used with `CHANSPC_M` below |
| `MDMCFG0` | `0xf8` | 99.9756 kHz channel spacing |
| Channel number | `0` or `11` | 433.139862 or 434.239594 MHz |
| `SYNC1/0` | `79 f4` | validate the remaining `88 2f 28` in software |
| `PKTLEN` | `0x24` | 36 bytes after the two hardware-sync bytes |
| `PKTCTRL0` | `0x00` | fixed length; hardware whitening and CRC disabled |
| Fixed received bytes after hardware sync | 36 | prepend `79 f4` to reconstruct the 38-byte normalized frame |

The CC1101's closest deviation setting is about 1.26 kHz above the measured
value; receive validation will show whether `0x45` or the next-lower `0x44`
performs better. The 203 kHz filter is intentionally conservative enough to
cover the clipped-capture 99% bandwidth and oscillator error.

This is a receive profile, not yet a safe transmit recipe. The CC1101 hardware
preamble generator is shorter than RainPoint's observed 40-, 150-, and
300-byte-equivalent prefixes. Transmit firmware will need FIFO/continuous or
asynchronous streaming to reproduce the complete wake sequence, sync, frame,
and retry timing rather than relying on ordinary packet-mode preamble output.

## Frame format

Every decoded packet normalizes to:

```text
79 f4 88 2f 28 | endpoint A (4) | endpoint B (4) | body (23) | trailer (2)
```

| Offset | Length | Meaning | Status |
|---:|---:|---|---|
| 0 | 5 | Sync word | Confirmed |
| 5 | 4 | Endpoint A | Confirmed field; physical direction is role-dependent |
| 9 | 4 | Endpoint B | Confirmed field; physical direction is role-dependent |
| 13 | 23 | Message body | Partially decoded |
| 36 | 2 | CRC-CCITT-derived trailer | Partially confirmed; selector unresolved |

The endpoint fields should not yet be treated as ordinary source and
destination MAC addresses. Their order reverses in valve request/response
traffic, while sensor reports use two observed route shapes.

## Known endpoints

| Association | Endpoint | Evidence |
|---|---|---|
| Hub/controller side of valve exchange | `b42d008f` | Open and close requests |
| HTV145FRF valve side of exchange | `b9840280` | Immediate valve responses |
| Right Bed HCS026FRF | `9ce58024` | Repeated moisture matches |
| Left Bed HCS026FRF | `c4e50024` | Controlled 58% and 12% matches |
| Front Yard Sensor 1 | `ce628024` | Repeated 59% matches |
| Front Yard Sensor 2 | `d1e28024` | Repeated 78--79% matches |
| Sensor companion/acknowledgement route | `39840280` | Short frames following lower-channel reports |

Friendly names are installation-specific. The stable endpoint values are the
portable part of the protocol.

## HCS026FRF enrollment lifecycle

Two controlled sensors established the same receive-side enrollment sequence.
An unpaired sensor announces a factory identity through endpoint `80000000`.
The subsequent sequence uses a paired identity formed by setting bit 7 of the
factory identity's first byte:

| Sensor | Factory identity | Paired identity |
|---|---|---|
| Test Sensor A | `1bce0024` | `9bce0024` |
| Test Sensor B | `15a98024` | `95a98024` |

Both enrollments used sensor message types `01`, `02`, `02`, and `03` at the
same repeatable cadence. The sensor frames occupied a lower channel near
433.14 MHz. Each was followed by a roughly 31 ms burst on a second channel;
the normal decoder missed these because they use only a 320-symbol wake prefix.
Offline clock recovery extracted valid 38-byte frames with the established sync
word and trailer residues. Their endpoint direction is paired sensor identity
to `39840280`, confirming that they are stock RainPoint gateway replies.

The initial replies immediately following each factory announcement were:

| Sensor | Reply channel | Initial gateway reply |
|---|---:|---|
| A | ~433.471 MHz | `79f4882f289bce002439840280814088050304f000adf18a0d00808000000000000000004c41` |
| B | ~433.472 MHz | `79f4882f2895a98024398402808140880503847000f4730a0d008080000000000000000060a8` |

Subsequent gateway acknowledgements moved to a per-sensor channel: about
434.021 MHz for Sensor A and 433.912 MHz for Sensor B. All recovered first
enrollment and rejoin frames are retained in
`research/fixtures/hcs026_gateway_pairing_replies.json`.

The two first-enrollment sequences had the same cadence within measurement
error:

| Transition | Sensor A | Sensor B |
|---|---:|---:|
| factory `01` to paired `01` | 2.983 s | 2.992 s |
| paired `01` to paired data `02` | 5.915 s | 5.890 s |
| paired data `02` to short `02` | 1.942 s | 1.942 s |
| short `02` to paired data `03` | 3.878 s | 3.898 s |

These intervals are useful for recognizing a complete enrollment sequence but
are not treated as hard deadlines; RF packet loss must not create a false
association.

A battery power cycle caused Sensor A to announce its factory identity; the
stock RainPoint gateway replied with a rejoin frame and restored its paired
identity without an app action. Deleting Sensor B from the app produced no RF
frame. Until its next power cycle it continued transmitting on the paired
identity; after reboot it returned to factory announcements.

In a controlled local-only test, Sensor B emitted factory messages `01`, `02`,
and `04` six seconds apart while the RTL-SDR receiver remained healthy. It did
not emit the paired identity and never flashed blue because no gateway reply
was transmitted. Physical pairing therefore requires a transceiver; listening
alone can discover the factory identity but cannot complete enrollment.

The receive decoder recognizes this strict factory/paired structure and can
create a generic HCS026 device from a trailer-valid paired telemetry report.
The enrollment monitor opens an explicit learning window, reports the factory
candidate, and persists only a matching factory-to-paired transition. The
current receiver deliberately transmits nothing. The recovered stock-gateway
frames are transmit candidates for the future ESP32/CC1101 prototype, not yet
an enabled control path.

### Sensor B dry-run pairing reply plan

The executable prototype contains one deliberately narrow reply profile for
factory identity `15a98024` / paired identity `95a98024`. It advances only
after the matching sensor trigger has been observed:

| Step | Sensor trigger | Reply frequency |
|---:|---|---:|
| 1 | Factory message `01` | 433.4715 MHz |
| 2 | Paired message `01` | 433.9115 MHz |
| 3 | Paired data message `02` | 433.9115 MHz |
| 4 | Paired short message `02` | 433.9115 MHz |
| 5 | Paired data message `03` | 433.9115 MHz |

Each planned waveform has a 320-symbol alternating wake (16 ms) and a 304-bit
frame (15.2 ms), or 31.2 ms of RF before any implementation-specific guard
silence. The provisional reply deadline is 250 ms after the matching trigger;
this is a conservative engineering bound, not a measured protocol constant.
Duplicates are ignored, while timeout, out-of-order triggers, or interruption
fail the plan closed. Firmware 0.3.0 implements this exact profile as an
explicitly armed physical bench path using ESP32 RMT timing and CC1101
asynchronous serial TX. It starts disarmed, uses approximately 0 dBm output,
accepts no network command, and contains no valve frame path. Physical SDR
validation remains required before its timing or polarity is considered
confirmed.

## HCS026FRF soil-moisture reports

Data-rich HCS026FRF frames carry a packed moisture value at one of two body
positions. The decoder looks for a marker whose low seven bits equal `0x44`.
The following byte contains half the percentage and the high bit of the next
byte is the odd-value flag:

```text
percent = value * 2 + bool(odd_flag & 0x80)
```

The marker begins at normalized frame offset 18 or 20, depending on the report
layout. Detection is restricted to confirmed HCS026 endpoint IDs to prevent a
marker-like sequence in a valve frame from creating a false sensor reading.

Confirmed examples:

| Sensor endpoint | Relevant bytes | Result |
|---|---|---:|
| `ce628024` | `... c4 1d 80 ...` | 59% |
| `d1e28024` | `... c4 27 80 ...` | 79% |
| `c4e50024` | `... 44 1d 00 ...` | 58% |
| `c4e50024` | `... c4 06 00 ...` | 12% |
| `9ce58024` | `... 44 20 00 ...` | 64% |
| `9bce0024` | `... c4 00 80 ...` | 1% |
| `95a98024` | `... c4 05 00 ...` | 10% |

### Confirmed paired-layout battery flag

The two newly enrolled sensors use a distinct paired body structure beginning
with `82 04`. A controlled three-cell to two-cell to three-cell transition on
Test Sensor A correlated the stock app, the LCD low-battery icon, and RF byte
17 bit `0x04`:

```text
full: ... 03 01 82 04 85 c4 00 80 ...  # 1%, bit 0x04 set
low:  ... 03 01 82 04 81 c4 00 80 ...  # 1%, bit 0x04 clear
```

For this validated layout, bit set maps to normal/`100%` and bit clear maps to
low/`10%`, matching the categorical values exposed by the stock integration.
The moisture field and every other compared byte remained unchanged. The
normalized regression corpus is stored in
`research/fixtures/hcs026_pairing_battery.json`.

### Product-code/TLV report

One Front Yard Sensor 2 transmission used `d1e28048` in endpoint B rather than
its ordinary `d1e28024`. The `0x48` suffix equals the HomGar product code for
the HCS021/HCS024/HCS026 soil-sensor family. Its body carried:

```text
2c 03 04 0f 0a 88 4f
                  ^^ 79%
               ^^ one-byte HomGar TLV header for type 10 / STA_RH
```

The ordinary `d1e28024` companion acknowledgement arrived 180 milliseconds
later, and surrounding independently decoded reports held steady at 79%.
`rainpointd` therefore canonicalizes a known HCS026 `...48` identity back to
its established `...24` endpoint and decodes `88 VV` as direct percentage
`VV`. It does not apply that rule to an unknown endpoint.

A compact-status family was observed three times within 0.835--1.040 seconds
of a normal Right Bed 57% report:

```text
... 0a 88 39 e0 b1 ...
       |  |  |  +---- signed type-32 RSSI: -79 dBm
       |  |  +------- moisture: 57%
       |  +---------- one-byte type-10 header
       +------------- field code 10 / STA_RH
```

All three carried moisture 57% and hub RSSI -79 dBm, matching the independently
observed Right Bed state. Two forms used a slot-like `0x0b` byte before the
same compact `88 39 e0 b1` TLVs instead of field code `0x0a`. Their routing
fields varied and did not provide a stable Right Bed identity, so the decoder
retains these as unassigned status fields rather than updating a device. The
repeatable timing and values associate the family with Right Bed, but more
samples are required before defining a safe automatic routing rule.

The controlled 12% sample was produced by removing the Left Bed probe from the
ground. Its display, independently observed reference entity, local decoder,
gateway API, and Home Assistant local entity all reported 12%. This validates
the field across a much wider range than the earlier 58--79% samples.

Example Left Bed frame:

```text
79f4882f28b9840280c4e500240981820385c406000000000000000000000000000000004cea
```

### Sensor fields not yet decoded

- Older installed sensors use a separate companion-heartbeat battery family.
  The cloud decoder maps raw `0`/`1` to normal and `2`--`4` to low; 358
  retained companion heartbeats from three HCS026 endpoints all contained
  `... 41 81 00 01 00 ...` (allowing the observed `41`/`c1` retransmission-bit
  change). Normalized frame offset 17 is therefore the leading RF battery
  candidate for that older layout. During the same period, all 5,485
  cloud-reference reports carried `dc 01` and every battery entity remained
  normal/100%. The local decoder retains this companion value as provisional
  research metadata. The confirmed paired-layout battery flag described above
  is decoded separately and exposed.
- Hub-reported RSSI is receiver-measured rather than generated by the sensor.
  It can appear in separate compact status traffic, but that traffic's device
  association is not yet decoded.
- The meaning of the first body byte and companion heartbeat fields remains
  provisional.

The gateway currently exposes SDR signal metadata separately as
`rf_rssi_db`; it must not be presented as the stock hub's RSSI value.

## HTV145FRF valve protocol

### Request and response roles

| Endpoint order | Body byte 1 | Meaning |
|---|---:|---|
| `b42d008f` to `b9840280` | `0x10` | Open request |
| `b9840280` to `b42d008f` | `0x50` | Open response |
| `b42d008f` to `b9840280` | `0x90` | Close request |
| `b9840280` to `b42d008f` | `0xd0` | Close response |

The first body byte is a transaction sequence. Observed watering cycles
advanced through `0x9b`, `0x9c`, `0x9d`, `0x9e`, `0x9f`, then `0x80`, strongly
indicating a five-bit counter with a fixed high bit. Every request and response
in one cycle echoes the same sequence value.

### Command bodies

The stable request bodies are:

```text
open:  SS 10 82 80 81 00 DD DD 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
close: SS 90 81 80 81 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

`SS` is the transaction sequence. `DD DD` starts with the watering duration in
two-second units, little-endian, but bit 7 of the low byte is forced on:

```text
units = duration_seconds / 2
DD DD = little_endian_16(units)
DD[0] = DD[0] OR 0x80
```

The forced bit makes arbitrary second values ambiguous. Every independently
correlated command used whole minutes, which resolves the ambiguity: of
`little_endian(DD DD) * 2` and `(little_endian(DD DD) & ~0x80) * 2`, exactly
one is a positive multiple of 60. Initial local construction is therefore
restricted to whole-minute durations.

Confirmed duration examples:

| Encoded | Requested duration |
|---|---:|
| `9e 00` | 60 seconds |
| `f8 00` | 240 seconds |
| `fe 01` | 1,020 seconds |

The 240- and 1,020-second values were independently confirmed in the Home
Assistant recorder at the corresponding RF timestamps. Treating `f8 00` as a
plain 16-bit value would incorrectly produce 496 seconds.

### Representative frames

```text
open request
79f4882f28b42d008fb98402809710828081009e000000000000000000000000000000003824

open response
79f4882f28b9840280b42d008f9750868010cf92800000409e00569e000000000000000044ce

close request
79f4882f28b42d008fb984028097908180810000000000000000000000000000000000006fcf

close response
79f4882f28b9840280b42d008f97d08680104f90800000408000569e00000000000000001f46
```

Exact requests were observed retransmitted without changes, including the
trailer. This proves there is no per-burst nonce. It does not yet prove that a
request from an older transaction can be replayed later.

Across 14 captured commands (seven opens and seven closes), 12 had a retained
reverse-route response within three seconds. Normal response latency was
0.372--0.380 seconds; two responses arrived at 1.062 and 1.083 seconds. This
supports a first acknowledgement timeout of at least 1.5 seconds and argues
against immediately retrying a non-idempotent open command. The two missing
responses were from the scheduled cycle and are consistent with missed RF
reception rather than proven valve non-response.

### Last-session water usage

Valve response frames use `0x4f` or `0xcf` as a marker at normalized frame
offset 20. The next two bytes encode usage in tenths of a liter:

```text
half_tenths = ((second & 0x7f) << 8) | (first & 0x7f)
tenths_liters = half_tenths * 2 + bool(second & 0x80)
liters = tenths_liters / 10
```

Confirmed examples:

| Packed bytes | Result |
|---|---:|
| `85 00` | 1.0 L |
| `84 80` | 0.9 L |
| `8e 00` | 2.8 L |
| `d3 00` | 16.6 L |
| `b3 00` | 10.2 L |
| `ec 03` | 175.2 L |

## Trailer status

For ordinary 38-byte frames, calculate CRC-CCITT with polynomial `0x1021` and
initial value zero over normalized bytes 0--35. XOR that result with the
big-endian trailer. In the retained corpus, 687 of 705 usable unique frames
(97.4%) produce one of exactly two residues:

```text
crc_ccitt(frame[0:36], init=0) XOR trailer in { 0xc713, 0x4f03 }
```

The remaining 18 frames visibly contain clipping, demodulation corruption, or
placeholder trailers. Re-demodulation of retained IQ reproduced both residues
with both short and long preambles, so preamble length is not the selector.
Both residues also occur in hub-to-valve command traffic. A scheduled 1,020
second open and its close used `0x4f03`; controlled short cycles used each
residue across different transaction sequence values.

An expanded passive analysis on 2026-08-07 found 1,456 unique clean frames:
732 used `0xc713` and 724 used `0x4f03`. Every established route contained
both. The best single transmitted-bit predictor was only 51.4% accurate, and
the best two-bit XOR predictor was 53.3%; neither is materially better than
chance for this balanced corpus. Collapsing exact retransmission bursts also
rejected a simple alternating selector. No identical 36-byte payload was
observed with conflicting trailers.

The selector is therefore not a simple exposed frame bit, pairwise parity,
route, message counter, or global toggle. It may depend on omitted transmitter
state or a nonlinear rule. Passive evidence can validate either residue but
cannot yet choose one when constructing a new payload.

Cloud/API correlation narrows this further. The legacy valve-control request
contains only hub/device identity, subdevice address, port, open/close mode,
duration, an empty parameter, and the hub ID. It contains no nonce, timestamp,
RF sequence, checksum mode, or trailer selector. The HTV145FRF product catalog
likewise describes `CTL_WATER` as a two-byte control on endpoint 7 but has no
CRC selector. Therefore the sequence and trailer are generated inside the
hub's RF stack. The two-residue choice is most plausibly hidden transmitter
state, an omitted lower-layer input, or two forms accepted by the receiver;
the cloud API does not provide a missing bit that can simply be copied.

This is sufficient to validate ordinary received frames and reject most
demodulation artifacts. It is not yet sufficient to generate arbitrary
commands because the rule selecting the two residues remains unknown. Compact
product-code/status frames are a separate family and do not satisfy this
ordinary-frame rule, so they must be retained rather than rejected globally.

## Receive and decode

Live receive:

```sh
rtl_433 -f 433700000 -s 2000000 -R 0 \
  -X 'n=RainPoint,m=FSK_PCM,s=50,l=50,r=50000,bits>=620,match={40}79f4882f28' \
  -M time:iso:usec -M level -M bits
```

Normalize saved CU8 captures:

```sh
python3 tools/decode_rainpoint_iq.py \
  --sample-rate 2000000 --frequency 433700000 capture.cu8
```

Measure FSK tones and occupied bandwidth from saved CU8 captures:

```sh
python3 tools/characterize_rainpoint_iq.py \
  --sample-rate 2000000 --frequency 433700000 capture.cu8
```

`rainpointd_addon/rainpointd/rf.py` is the executable specification for frame
normalization and confirmed field decoding. Regression examples live in
`test_rainpoint_rf.py`.

## Remaining protocol work

1. Determine by bounded active acceptance testing whether either ordinary
   trailer residue is accepted for a newly constructed payload, then
   characterize the compact-frame trailer family.
2. Validate the measured channel, rate, deviation, bandwidth, and sync profile
   on receive-only CC1101 hardware, including both RF channels.
3. Test whether a captured request is accepted outside its original sequence
   window.
4. Decode battery-low state with a controlled test sensor.
5. Capture sensor and valve enrollment, association, and forgetting traffic.
6. Confirm retry timing, acknowledgement rules, and safe close behavior before
   enabling Home Assistant control.

## Safety boundary

The current implementation is receive-only. Transmit support must enforce a
local maximum duration, start an independent watchdog before opening, retry an
idempotent close until idle is observed, and fail closed after gateway, Home
Assistant, network, or power loss.

## Evidence and references

The concise capture history is in
[`research/RF_CAPTURE_NOTES.md`](research/RF_CAPTURE_NOTES.md). Cloud-side
observations used only as a comparison oracle are isolated in
[`research/cloud/README.md`](research/cloud/README.md).

- Exact valve FCC filing: <https://fccid.io/2AWDBHTV145FRF>
- Community HCS021FRF FSK notes:
  <https://github.com/user-attachments/files/26152016/rainpoint_decoding.txt>
- `rtl_433`: <https://github.com/merbanan/rtl_433>
- TI CC1101: <https://www.ti.com/product/CC1101>
