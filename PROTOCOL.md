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
| Symbol width | 48 microseconds, approximately 20.83 ksymbols/s |
| Sync word | `79 f4 88 2f 28` |
| Normalized frame | 38 bytes |
| Preamble | 320-bit short form or 1,201-bit long wake/command form |
| Receive implementation | RTL-SDR with `rtl_433` |
| Planned transceiver | ESP32 with a 433 MHz CC1101-class radio |

The working `rtl_433` flex decoder is:

```text
n=RainPoint,m=FSK_PCM,s=48,l=48,r=49152,bits>=620,match={40}79f4882f28
```

A 2.0 Msps capture centered at 433.7 MHz has been the most useful general
receive configuration. Installed-device energy has appeared across roughly
433.08--434.38 MHz, so narrower captures can miss valid report types.

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

A second compact-status frame followed a normal Right Bed 57% report by 835
milliseconds:

```text
... 0a 88 39 e0 b1 ...
       |  |  |  +---- signed type-32 RSSI: -79 dBm
       |  |  +------- moisture: 57%
       |  +---------- one-byte type-10 header
       +------------- field code 10 / STA_RH
```

Both values match the independently observed Right Bed state. Its routing
fields do not match the established sensor endpoint, so the decoder retains
these as unassigned status fields rather than updating a device. More samples
are required before defining the association rule.

The controlled 12% sample was produced by removing the Left Bed probe from the
ground. Its display, independently observed reference entity, local decoder,
gateway API, and Home Assistant local entity all reported 12%. This validates
the field across a much wider range than the earlier 58--79% samples.

Example Left Bed frame:

```text
79f4882f28b9840280c4e500240981820385c406000000000000000000000000000000004cea
```

### Sensor fields not yet decoded

- Battery is a one-byte categorical status in HomGar metadata, not a granular
  percentage. The cloud decoder maps raw `0`/`1` to normal and `2`--`4` to low;
  358 retained companion heartbeats from three HCS026 endpoints all contained
  `... 41 81 00 01 00 ...` (allowing the observed `41`/`c1` retransmission-bit
  change). Normalized frame offset 17 is therefore the leading RF battery
  candidate. During the same period, all 5,485 cloud-reference reports carried
  `dc 01` and every battery entity remained normal/100%. The local decoder
  retains offset 17 as provisional research metadata but does not expose it as
  a supported battery entity until a controlled low-battery transition shows
  it changing.
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

`SS` is the transaction sequence. `DD DD` is a little-endian duration stored
in two-second units:

```text
duration_seconds = little_endian(DD DD) * 2
```

Confirmed duration examples:

| Encoded | Requested duration |
|---|---:|
| `fe 01` | 1,020 seconds |

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

This is sufficient to validate ordinary received frames and reject most
demodulation artifacts. It is not yet sufficient to generate arbitrary
commands because the rule selecting the two residues remains unknown. Compact
product-code/status frames are a separate family and do not satisfy this
ordinary-frame rule, so they must be retained rather than rejected globally.

## Receive and decode

Live receive:

```sh
rtl_433 -f 433700000 -s 2000000 -R 0 \
  -X 'n=RainPoint,m=FSK_PCM,s=48,l=48,r=49152,bits>=620,match={40}79f4882f28' \
  -M time:iso:usec -M level -M bits
```

Normalize saved CU8 captures:

```sh
python3 tools/decode_rainpoint_iq.py \
  --sample-rate 2000000 --frequency 433700000 capture.cu8
```

`rainpointd_addon/rainpointd/rf.py` is the executable specification for frame
normalization and confirmed field decoding. Regression examples live in
`test_rainpoint_rf.py`.

## Remaining protocol work

1. Identify the selector between ordinary trailer residues `0xc713` and
   `0x4f03`, then characterize the compact-frame trailer family.
2. Measure the exact carrier center and 2-FSK deviation for CC1101 transmit.
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
