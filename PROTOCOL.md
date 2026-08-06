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

- exact modulation parameters, bitrate, line coding, sync word, and framing
- accessory address placement
- checksum or message authentication
- exact open/close command bytes
- replay protection, if any

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
- `rtl_433` receiver and analyzer:
  <https://github.com/merbanan/rtl_433>
- Cloud integration research source:
  <https://github.com/martinpeniak/tao-irrigation>
