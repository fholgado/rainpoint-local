# RainPoint local protocol research

This document records only behavior demonstrated by captures from the owner's
RainPoint installation. Identifiers and credentials are intentionally omitted.

## Devices

| Role | Model | Transport |
|---|---|---|
| Hub | HWG023WBRF-V2 | Wi-Fi to HomGar cloud; 433.7 MHz to accessories |
| Valve | HTV145FRF | 433.7 MHz RF through the hub |
| Soil probes | HCS026FRF | 433.7 MHz RF broadcasts through the hub |

The hub has not exposed a listening TCP service in the tested port range. It
initiates its own outbound connections.

## Cloud-side flow

The hub maintains an encrypted MQTT connection:

```text
hub → HomGar/Aliyun broker: TCP 1883 with TLS
```

Despite the conventional plaintext port number, records begin with TLS
application-data framing (`17 03 03`).

Observed normal traffic:

- 31-byte TLS heartbeat in each direction about every 55 seconds.
- 217-byte hub telemetry records during periodic status reporting. A passive
  capture at 10:07:20 EDT correlated one exactly with an HCS026FRF soil report.
- 301-byte cloud-to-hub record for valve start.
- 299-byte cloud-to-hub record for valve stop.
- 244/245-byte hub response records after valve commands.

Valve actions also cause short TLS 1.2 connections from the hub to a second
HomGar endpoint on TCP 1446. The endpoint presents a certificate for
`*.homgarus.com` and selected cipher suite `0x009d`
(`TLS_RSA_WITH_AES_256_GCM_SHA384`).

### MQTT observer envelope

The Home Assistant integration receives plaintext observer messages on an
Aliyun-style topic:

```text
/sys/<product-key>/<observer-device>/thing/service/property/set
```

The JSON envelope has this shape:

```json
{
  "method": "thing.service.property.set",
  "id": "<message-id>",
  "params": {
    "param": "#P<prefix>|{\"D01\":{\"time\":<ms>,\"value\":\"10#...\"},\"update\":{\"time\":<ms>,\"value\":1},\"state\":{\"time\":<ms>,\"value\":\"0,-47\"}}|<ms>|<suffix>#"
  },
  "version": "1.0.0"
}
```

`D01` is RF accessory address 1, the HTV145FRF valve in this installation.
Other accessory addresses are represented as `D02`, `D03`, and so on.

The observer credentials used by Home Assistant are not assumed to be the
physical hub's credentials. Publishing to the observer topic is therefore not
yet evidence that a message can control the hub.

## RF status payload

The value beginning with `10#` is a compact TLV stream represented as hex.
The current decoder treats the first two decimal characters and `#` as an
envelope and parses the remaining bytes.

### TLV header

For the observed frames:

- Header high bit clear: one-byte inline value; type code is bits 6–4.
- Header high bit set:
  - payload length is `(header & 0x03) + 1`
  - short type code is `((header >> 2) & 0x1f) + 8`
  - short code 31 introduces an extended type
- Multi-byte numeric values are little-endian.

### Observed fields

| Type | Meaning | Encoding |
|---:|---|---|
| 2 | Alarm | low nibble |
| 10 | Humidity / soil moisture | unsigned percent |
| 15 | Last water usage | little-endian integer, tenths of liters |
| 19 | Session duration | little-endian seconds |
| 21 | Event/end time | packed local wall-clock |
| 30 | Valve work state | low nibble: 0 idle, 1 irrigation |
| 31 | Battery status | 0/1 normal, 2–4 low |
| 32 | RSSI | signed 8-bit dBm |
| 54 | Report time | packed local wall-clock |

The event-time field contains the hub/device's local wall-clock. Home
Assistant later applies the site's timezone to expose a UTC timestamp.

## Labeled valve frames

### Running

```text
10#E1B900DC01D82120B724A0FC19AD58029F2E000000FF0FAA9CFC19
```

Decoded:

- battery 100%
- RSSI -71 dBm
- work state irrigation
- duration 600 seconds
- event/end local time 2026-07-30 10:00:36
- report local time 2026-07-30 09:50:42
- prior usage 4.6 L
- alarm 0

### Stopped

```text
10#E1B900DC01D80020B700000000AD00009F64000000FF0FE89CFC19
```

Decoded:

- battery 100%
- RSSI -71 dBm
- work state idle
- duration 0
- last usage 10.0 L
- report local time 2026-07-30 09:51:40
- alarm 0

The raw status frames are reports from the valve. They are not yet the
over-the-air RF command needed to open or close it.

## Soil-moisture frames

All observed HCS026FRF frames share the same four-field layout:

```text
RSSI → battery → soil moisture → report time
```

| Sensor | Moisture | RSSI | Raw payload |
|---|---:|---:|---|
| Right Bed | 58% | -70 dBm | `10#E1BA00DC01883AFF0F6C9CFC19` |
| Left Bed | 63% | -75 dBm | `10#E1B500DC01883FFF0F2090FC19` |
| Front Yard 1 | 61% | -80 dBm | `10#E1B000DC01883DFF0F0745FB19` |
| Front Yard 2 | 82% | -77 dBm | `10#E1B300DC018852FF0FD281FC19` |

Sensor identity is supplied by the surrounding MQTT `Dxx` address, not by an
obvious stable identifier in the decoded TLV fields.

## Control API metadata

HomGar product metadata for HTV145FRF identifies valve control as:

```text
identity: CTL_WATER
dpId: 46
dpCode: 1
endpoint: 7
dpLen: 2
dpPort: 1
```

The existing cloud integration calls:

```text
POST /app/device/controlWorkMode
```

with hub/device identifiers plus:

```json
{
  "port": 1,
  "mode": 1,
  "duration": 600,
  "param": ""
}
```

Stop uses mode and duration `0`.

This describes the cloud request but not the hub-to-valve RF command.

## Labeled local RF captures (2026-08-06)

A Nooelec NESDR SMArt v5 passively captured the installed devices. Home
Assistant recorder timestamps positively correlate local RF bursts with the
HomGar integration's raw payload and valve state changes.

The first 250 ksample/s capture centered at 433.7 MHz clipped most of the
transmission. Despite that limitation, it produced two useful soil-sensor
correlations:

| RF capture time | HA raw-payload time | Device |
|---|---|---|
| 11:01:15.562 | 11:01:15.655 | Left Bed HCS026FRF |
| 11:02:33.795 | 11:02:34.533 | Right Bed HCS026FRF |

A corrected 1.024 Msps capture centered at 433.92 MHz recorded one short valve
cycle. The raw files are intentionally retained locally rather than committed.

| File | RF time | HA correlation | SHA-256 |
|---|---|---|---|
| `g004_433.92M_1024k.cu8` | 11:08:40.017 | valve open at 11:08:40.677 | `560072d3f3a414bf0e20893333590150defd2a9c9db1ad691e1a86b0da8bb848` |
| `g005_433.92M_1024k.cu8` | 11:08:40.395 | same open exchange | `10387364cbea3ff8796239b2bacfffc3d941583d155e4f2e705c7135f24bc060` |
| `g006_433.92M_1024k.cu8` | 11:08:46.443 | running report at 11:08:46.533 | `8df74ffdd2c6af7b4c0972ad588d689fcd8ef51c37fc63e85e24ddb2db361463` |
| `g007_433.92M_1024k.cu8` | 11:09:00.498 | valve close at 11:09:01.182 | `2df35809e608b6e40393622c71618a8ced9f69da41c1aee63d8e72b8bc5bfe2a` |
| `g008_433.92M_1024k.cu8` | 11:09:00.878 | same close exchange | `1934e0f21cf49f97716849636f7ed8e560e65acf8eda4f207073e9c1b9ed95d0` |
| `g009_433.92M_1024k.cu8` | 11:09:06.952 | stopped report at 11:09:07.044 | `5cefbcc445ba96fb61eafd64aa8cbf3b1c57e198b98b2f302ec3cc86ce2f18c8` |

The filing labels HCS026FRF modulation as ASK. The local wideband samples,
however, are detected as two-tone FSK when replayed through `rtl_433`'s min/max
FSK detector. Approximate tone estimates vary by burst:

| File | Lower tone | Upper tone | Burst role |
|---|---:|---:|---|
| `g004` | 434.183 MHz | 434.378 MHz | open exchange, 135 ms |
| `g005` | 434.069 MHz | 434.103 MHz | open exchange reply, 31 ms |
| `g006` | 434.164 MHz | 434.318 MHz | running confirmation, 31 ms |
| `g007` | 434.160 MHz | 434.369 MHz | close exchange, 135 ms |
| `g008` | 434.089 MHz | 434.133 MHz | close exchange reply, 31 ms |
| `g009` | 434.175 MHz | 434.340 MHz | stopped confirmation, 31 ms |

These frequency estimates are provisional because several upper tones were
near the capture passband edge. Future captures use a 1.024 MHz window centered
at 434.0 MHz. Do not infer hub-versus-valve direction from carrier frequency
until additional exchanges are captured with relative signal-strength or
proximity evidence.

### Confirmed modulation and frame extraction

A community HCS021FRF investigation supplied the missing demodulator settings:

```sh
rtl_433 -f 434000000 -s 1024000 -R 0 \
  -X 'n=RainPoint,m=FSK_PCM,s=48,l=48,r=49152,bits>=620,match={40}79f4882f28'
```

Those settings decode every labeled valve file and the right-bed exchange.
They confirm 2-FSK pulse-code modulation with 48 microsecond symbols. The two
observed preamble forms are 320 alternating bits for short packets and 1,201
bits before sync for long wake/command packets.

Both forms normalize to a 38-byte frame beginning with the same five-byte sync
word:

```text
79 f4 88 2f 28 | endpoint A (4) | endpoint B (4) | body (23) | trailer (2)
```

Endpoint direction and the trailer algorithm remain provisional. The endpoint
order reverses between the initial valve exchange packets, but more evidence is
needed before naming either field as source or destination.

Normalized frames from the short valve cycle:

| Role | Frame |
|---|---|
| Open command candidate | `79f4882f28b42d008fb98402809710828081009e000000000000000000000000000000003824` |
| Open response candidate | `79f4882f28b9840280b42d008f9750868010cf92800000409e00569e000000000000000044ce` |
| Running confirmation candidate | `79f4882f28b42d008fb98402809ec10100060000000000000000000000000000000000006bea` |
| Close command candidate | `79f4882f28b42d008fb984028097908180810000000000000000000000000000000000006fcf` |
| Close response candidate | `79f4882f28b9840280b42d008f97d08680104f90800000408000569e00000000000000001f46` |
| Stopped confirmation candidate | `79f4882f28b42d008fb98402809f410100060000000000000000000000000000000000003c64` |

`tools/decode_rainpoint_iq.py` automates the flex decode, finds sync across both
preamble alignments, and emits normalized JSON without assigning unproven
direction semantics.

The long packet at 11:09:16.876 normalized to:

```text
79f4882f28b42d008f9ce580240784830701800544200000000000000000000000000000308a
```

Its moisture field is `200`: `0x20 * 2` plus a clear odd-value flag, or 64%.
Home Assistant recorded Right Bed at 64% at 11:09:17.985, 91 ms after the
following short RF packet began (about 60 ms after it completed). This confirms
direct local moisture extraction for one HCS026FRF report. The decoder exposes
the result as `soil_moisture_percent`.

A subsequent receive-only session confirmed the field twice more without any
user action:

| RF time | Moisture field | Local result | HA device/recorder time |
|---|---|---:|---|
| 11:35:33.326 | `1f0` | 62% | 11:35:34.517, 62% |
| 11:37:30.086 | `1f0` | 62% | 11:37:30.927, 62% |

The preceding packed byte varied from `44` to `c4`, confirming that its high
bit must be masked independently of the three-nibble moisture field.

### Persistent Pi capture and irrigation correlation (2026-08-06)

The protected Home Assistant app received the SDR directly and retained valid
non-moisture frames in its read-only event stream. A controlled irrigation
experiment confirmed the existing valve endpoint pair and revealed additional
RainPoint endpoints.

Home Assistant recorder correlation separated an unrelated Zigbee valve action
from two RainPoint Zone 1 cycles. Only the RainPoint cycles aligned with the
`b42d008f` / `b9840280` request-response exchanges, within 1.3 seconds of the
corresponding HA transitions.

The RF request precedes the cloud-backed HA transition, while the response and
confirmation surround it. This independently assigns `b42d008f` / `b9840280`
to the RainPoint Zone 1 valve and rules out the Zigbee front-bed valve.

| Role | Endpoint A | Endpoint B | Evidence |
|---|---|---|---|
| Hub/controller | `b42d008f` | `b9840280` | Start/stop requests; endpoint order reverses in responses |
| HTV145 valve | `b9840280` | `b42d008f` | Immediate response to each request |
| Front Yard Sensor 1 | `ce628024` | `39840280` | Full HA battery/RSSI/moisture/raw-payload update followed its RF frame by 97 ms |
| Left Bed sensor | `c4e50024` | `39840280` | Full HA battery/RSSI/moisture/raw-payload update followed its RF frame by 89 ms |

The first valve cycle used message byte `0x98`; the next used `0x99`. The
request body, not that rolling byte, distinguishes open (`10 82 ...`) from
close (`90 81 ...`). Confirmation frames advanced from `0x90` to `0x92` and
`0x93` during subsequent activity. This is strong evidence that the apparent
message-type byte contains a transaction or sequence value rather than a fixed
command opcode.

### Controlled three-cycle valve command capture

A 60-minute broad capture recorded three short, manually stopped Zone 1 runs.
Home Assistant Recorder supplied the authoritative valve transitions, while
the gateway event log supplied RF burst start times. Each cycle produced the
same command and response shapes:

To avoid publishing household activity times, the table keeps only delays from
the beginning of each RF request:

| Cycle | Open response | HA open | Close response | HA closed |
|---|---:|---:|---:|---:|
| 1 | +373 ms | +550 ms | +373 ms | +646 ms |
| 2 | +377 ms | +664 ms | +376 ms | +664 ms |
| 3 | +374 ms | +550 ms | +1,063 ms | +1,254 ms |

The first body byte was `9b`, `9c`, then `9d`; it advanced once per watering
cycle and was echoed by every request/response packet in that cycle. The
second body byte reliably identifies the action and direction:

| Body byte 1 | Endpoint order | Meaning |
|---:|---|---|
| `10` | `b42d008f` to `b9840280` | open request |
| `50` | `b9840280` to `b42d008f` | open response |
| `90` | `b42d008f` to `b9840280` | close request |
| `d0` | `b9840280` to `b42d008f` | close response |

The complete request bodies were stable except for that sequence byte:

```text
open:  SS 10 82 80 81 00 f8 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
close: SS 90 81 80 81 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
```

Here `SS` was `9b`, `9c`, or `9d`. All three runs used the HA duration setting
of four minutes, making `f8` a duration/setpoint candidate that needs captures
at other configured durations before it can be decoded.

The third close request was transmitted twice, 690 ms apart, as the exact same
38-byte frame, including trailer `35f2`. This proves there is no per-burst nonce
and that the trailer is deterministic for a given frame. It does not yet prove
that an older sequence value can be replayed in a later session.

Across otherwise identical `9b`/`9c`/`9d` requests, the trailer XOR deltas are
consistent with the CRC-CCITT polynomial `0x1021`. None of the common CRC-16
initialization/final-XOR variants, nor a simple contiguous frame slice, matches
all request and response trailers yet. Treat `0x1021` as a differential clue,
not a completed checksum algorithm.

Short `.. c1 01 00 06 ..`, `.. 41 01 00 06 ..`, and `.. 42 00 80 ..` frames
also surrounded the commands. Their counters advance independently, so they
remain classified as status/heartbeat candidates rather than open/close
commands.

The Right Bed HCS026 endpoint `9ce58024` reported 60% before watering and 61%
afterward. HA recorded the same 61% value 1.3 seconds later. No other HomGar
moisture entity changed in the capture window, and no second HCS026
moisture-layout endpoint was observed in that experiment. Subsequent persistent
capture assigned `c4e50024` to Left Bed and `ce628024` to Front Yard Sensor 1
through sub-100-ms HA recorder correlations. Front Yard Sensor 2 remains
unassigned because it has not produced a directly correlated update.

## Local architecture decision

### Preferred: direct 433 MHz bridge

Use an ESP32 with a CC1101-class transceiver, or an SDR during discovery, to
receive the soil broadcasts and transmit valve commands locally.

Advantages:

- Removes both HomGar cloud services.
- Does not depend on compromising or replacing hub firmware.
- One local radio can expose valve and soil entities to Home Assistant.
- The sensor application payload is already decoded.

Remaining RF unknowns:

- pairing and accessory-address semantics
- trailer checksum or message-authentication algorithm
- duration/setpoint encoding in the open request
- sequence freshness and replay protection, if any

### Public RF clues

The FCC filing for the exact HTV145FRF confirms a single 433.7 MHz Part 15
transmitter. A prior `rtl_433` investigation of an older RainPoint
temperature/humidity sensor at 433.9 MHz found OOK with Manchester-style
encoding and proposed this flex decoder:

```sh
rtl_433 -f 433900000 -R 0 \
  -X 'n=RainPoint,m=OOK_MC_ZEROBIT,s=500,l=500,r=1500' \
  -S unknown
```

That older sensor is not the HCS026FRF. The 2026-08-06 local captures do not
match its timing, so this decoder remains historical context rather than the
working hypothesis.

### Alternative: emulate the HomGar services for the original hub

Redirect the hub to a local MQTT broker and secondary API endpoint, then
reproduce the command/status protocol.

Advantages:

- Retains the existing RF hub and paired devices.

Additional unknowns:

- broker hostname used by the physical hub
- physical hub MQTT credentials
- certificate-validation behavior
- purpose and required responses of TCP 1446
- whether commands require cloud-generated signatures or counters

Because the hub exposes no local listener and all relevant paths are TLS, this
route currently has more unknowns than the direct-RF bridge.

## Next safe experiments

1. Capture several full-band soil reports centered at 434.0 MHz and correlate
   each with the Home Assistant raw payload.
2. Recover stable bit rows from the labeled IQ files and determine preamble,
   sync, bitrate, line coding, address, and checksum.
3. Capture additional short valve cycles with different requested durations to
   separate command, acknowledgement, and status fields.
4. Implement and validate receive-only soil sensing first.
5. Consider exact replay only after close behavior, counters, and independent
   timeout safety are understood.

## References

- Exact valve FCC filing:
  <https://fccid.io/2AWDBHTV145FRF>
- Prior RainPoint RF analysis in `rtl_433`:
  <https://github.com/merbanan/rtl_433/issues/1781>
- Community HCS021FRF FSK decoding and sensor-field notes:
  <https://github.com/user-attachments/files/26152016/rainpoint_decoding.txt>
- `rtl_433` receiver and analyzer:
  <https://github.com/merbanan/rtl_433>
- Cloud integration research source:
  <https://github.com/martinpeniak/tao-irrigation>
