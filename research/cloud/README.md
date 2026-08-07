# Archived cloud-side research

This directory isolates observations about the HomGar/RainPoint internet path.
They were useful as a temporary comparison oracle while decoding local RF, but
cloud service emulation is no longer a project objective. Nothing here is a
dependency of the local gateway or Home Assistant integration.

Identifiers and credentials are intentionally omitted.

## Hub network behavior

The HWG023WBRF-V2 hub exposed no confirmed local listening service during the
tested scan. It initiated its own outbound connections:

- a persistent TLS-wrapped MQTT connection on TCP 1883, and
- short TLS 1.2 connections to a second HomGar endpoint on TCP 1446 during
  valve actions.

Despite the conventional MQTT plaintext port, captured records began with TLS
application-data framing. Normal traffic included a small heartbeat about
every 55 seconds and repeatable record-size patterns around sensor reports and
valve actions. Payload contents could not be recovered from passive network
capture alone.

The TCP 1446 endpoint presented a certificate for `*.homgarus.com` during the
observation period.

## Observer MQTT envelope

The pre-existing Home Assistant integration received plaintext observer
messages on an Aliyun-style topic:

```text
/sys/<product-key>/<observer-device>/thing/service/property/set
```

Observed messages used this general envelope:

```json
{
  "method": "thing.service.property.set",
  "id": "<message-id>",
  "params": {
    "param": "#P<prefix>|{...}|<ms>|<suffix>#"
  },
  "version": "1.0.0"
}
```

Accessory values appeared under `D01`, `D02`, and similar keys. The observer
credentials were not shown to be the physical hub's credentials, and observing
this topic did not establish a local control path.

## Cloud application payload

The value beginning with `10#` is a compact TLV stream represented as hex.
This is an application/cloud representation, not the raw 38-byte over-the-air
frame described by [`../../PROTOCOL.md`](../../PROTOCOL.md).

Observed TLV fields were:

| Type | Meaning | Encoding |
|---:|---|---|
| 2 | Alarm | low nibble |
| 10 | Humidity / soil moisture | unsigned percent |
| 15 | Last water usage | little-endian integer, tenths of liters |
| 19 | Session duration | little-endian seconds |
| 21 | Event/end time | packed local wall-clock |
| 30 | Valve work state | 0 idle, 1 irrigation |
| 31 | Battery status | normal or low-state enum |
| 32 | RSSI | signed 8-bit dBm measured by the receiving hub |
| 54 | Report time | packed local wall-clock |

The application payload provided reference values for RF correlation. It does
not define the RF command or local pairing protocol.

## Historical control metadata

Product metadata associated the valve control with:

```text
identity: CTL_WATER
dpId: 46
dpCode: 1
endpoint: 7
dpLen: 2
dpPort: 1
```

The existing integration called `/app/device/controlWorkMode` with a port,
mode, and duration. That described an internet API request only; it did not
explain the hub-to-valve RF command.

## Passive monitoring snapshot — 2026-07-30

A bounded UDM capture found a 217-byte encrypted hub record at the same instant
as a Right Bed sensor update, labeling that network pattern as a sensor/status
publication. It did not reveal plaintext protocol data.

Home Assistant history also showed that two sensors were reporting less
frequently than the others. This prompted RF range and endpoint investigation,
which later demonstrated that receiver bandwidth and antenna placement could
explain missing local observations.

## Disposition

The project will not redirect the stock hub, reproduce HomGar TLS services,
recover hub credentials, or implement a local cloud-service emulator. The
supported direction is a direct local RF bridge using RTL-SDR for receive-only
operation and an ESP32/CC1101-class transceiver for future bounded control.

Historical references:

- <https://fccid.io/2AWDBHWG023WRF>
- <https://github.com/martinpeniak/tao-irrigation>
