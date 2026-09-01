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
frame described by
[`../../protocol_documentation/common.md`](../../protocol_documentation/common.md).

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

The current request body is now known exactly:

```text
deviceName, productKey, mid, addr, port, mode, duration, param, hid
```

For the legacy RF valve path, `param` is empty, `mode` is `1` to open or `0`
to close, and `duration` is supplied in whole seconds. There is no request
nonce, timestamp, sequence number, checksum, CRC mode, or trailer selector.
The optional cloud response `data.state` is an application TLV state snapshot,
not the hub-to-valve RF frame. Consequently, the hub firmware must construct
the RF sequence field and trailer after receiving this higher-level command.

The integration deliberately does not automatically retry ordinary transient
failures for this endpoint because an irrigation start is not idempotent: a
duplicate could restart or extend a watering session. Cloud result code `4`
is treated as a non-fatal busy/already-in-state result. These are useful safety
semantics for a future local controller, but neither behavior identifies the
RF trailer selector.

## Product catalog metadata

The data-driven product catalog in `homeassistant-homgar` supplies useful
semantic labels and compatibility identifiers even though it describes
HomGar application payloads rather than raw RF frames:

| Device | Model code | Product code | Relevant declared fields |
|---|---:|---:|---|
| HWG023WBRF-V2 | 289 (`0x0121`) | 1 | Supported-device registry |
| HTV145FRF | 302 (`0x012e`) | 31 (`0x1f`) | water control, battery, RSSI, work state, alarm, event times, duration, last usage |
| HCS026FRF | 317 (`0x013d`) | 72 (`0x48`) | battery, RSSI, `STA_RH` soil moisture |

The hub explicitly lists model codes 302 and 317 as supported subdevices. That
confirms compatibility and gives future pairing captures concrete byte
signatures to search in both byte orders. It does not reveal the enrollment
exchange, device address assignment, or RF trailer algorithm.

For HTV145FRF specifically, `CTL_WATER` is declared as endpoint `7`, DP code
`1`, DP type `2`, and length `2`. Its shared valve default parameter begins
`58 02`, which is `600` when interpreted as a little-endian 16-bit integer and
matches the integration's ten-minute default watering duration. This supports
a two-byte duration/value at the application-device boundary. It should not be
copied directly into an RF command: observed RF request durations use a
different half-second representation. The remaining default bytes
`0a 00 1e 00 00...` are not yet assigned meanings.

No catalog field represents either observed ordinary-frame CRC residue
(`0xc713` or `0x4f03`). The catalog and API therefore describe the semantic
command that enters the hub, while the unresolved selector belongs to a lower
RF framing layer.

The catalog describes HCS026 battery as a one-byte `STA_BAT` value. The
accompanying cloud decoder treats `0`/`1` as normal (`100%`) and `2`--`4` as
low (`10%`). Its `STA_RSSI` value is receiver-measured at the hub. These facts
refine the RF experiments but do not imply that either cloud TLV appears
unchanged in every over-the-air report.

Four exact cloud/local observations on 2026-08-24 matched the installed soil
sensors within one second. Moisture and categorical battery agreed in every
pair, while local receiver RSSI differed from stock-gateway RSSI as expected.
The app addresses 2--5 did not map to normalized RF offset 15, so migration
must not infer cloud address from that byte. The redacted observations are in
`../fixtures/hcs026_cloud_rf_correlation_20260824.json`.

The retained RF journal also contains 1,346 trailer-valid moisture relay
reports on the original HTV145 controller route. Of those, 775 occurred within
two seconds of an identified Right Bed report and all 775 carried the same
value. This is strong evidence for the cloud model's Associated Controller
behavior, but the relay envelope lacks the sensor endpoint; the local decoder
retains the value as unassigned instead of risking a cross-device update.

### Four-zone valve family clue

The catalog describes `HTV405FRF` as product code `38`, model code `38`, and a
single device with `portNumber: 4`. It declares four `CTL_WATER` values on RF
application endpoint 7: DP IDs 46–49 map to ports 1–4, each retaining DP code
1, DP type 2, and length 2. Work state, alarm, event time, duration, and recent
event time are likewise repeated per port, while battery and RSSI are declared
at port 0. Its default parameter repeats the same valve parameter block four
times separated by `|`.

This is a strong cloud-model clue that the four-zone timer is one associated
chassis with an explicit port selector rather than four independently enrolled
RF devices. It does not locate that selector in the over-the-air frame. Other
four-port RF valve models, including `HTV0542FRF` and `HTV445FRF`, also use
product code 38 with different model codes. Product code 38 should therefore
be tested as a four-zone functional-family identifier, not treated as an exact
model name.

A subsequent dry-bench cloud-control matrix opened and stopped all four ports
through the stock gateway. The retained application payloads confirmed the
catalog mapping directly: work-state DP IDs 25--28 and session-duration DP IDs
37--40 each changed only for the commanded port. Active state decoded as 33;
the first stopped update decoded as 32 and retained the requested 60-second
duration; a later idle refresh decoded as 0 and cleared it. Shared battery DP
24 stayed at 100 percent, while RSSI DP 23 varied from -20 to -30 dBm. The
cloud values and independently observed RF command/state pairs are frozen in
`../fixtures/htv405_stock_cloud_control_matrix_20260824.json`.

A separate 60-second matrix allowed all four zones to expire with no explicit
close. Every zone emitted independently decoded active and idle RF reports,
with idle arriving 60.947--61.645 seconds after cloud acceptance. The Zone 1
and Zone 4 cloud idle updates followed their RF idle reports by 113 and 111
milliseconds, respectively. This confirms that the physical valve owns its
duration even if HA, the network, or the custom gateway disappears. The
timelines are retained in
`../fixtures/htv405_stock_auto_stop_20260824.json`.

Explicit early-stop was then crossed independently on Zones 2--4. Each close
was followed by a valve-originated idle RF report 5.780--6.082 seconds after
cloud acceptance. Direct high-carrier captures on Zones 3 and 4 showed that
open and close reused the same transaction sequence within each session
(`0x0a`, then `0x0b` for the following session). Earlier authenticated-response
captures showed the other branch: a confirmed open advanced close to the next
sequence, while a confirmed close did not consume another sequence. Together
they show one advancement per watering session at its first authenticated
response, not one advancement per command. Exact commands and timelines are
in `../fixtures/htv405_stock_early_stop_20260824.json`.

For the original HTV145FRF, four exact cloud/RF correlations exposed a
categorical low-battery flag at RF offset 17 bit `0x08`. They also showed that
offset 23 bit `0x80` restores a missing high data bit in the packed last-usage
field; correcting it changes the correlated 93.1 L and 81.9 L observations
from the former underreported 67.5 L and 56.3 L. The evidence is retained in
`../fixtures/htv145_cloud_rf_battery_usage_correlation_20260824.json`.

### Address allocation and replacement behavior

The tested stock installation initially occupied app addresses 1--6. After
the former address-6 accessory was deleted, the newly enrolled HTV405FRF was
assigned address 6 rather than 7. Addresses therefore appear sequential for
an empty gateway, but they are reusable slots rather than a permanently
increasing identity.

This exposed a replacement edge case in the observed cloud integration. Its
Home Assistant identity is derived from the hub and address, so the new valve
initially inherited the deleted sensor's address-6 device/entity identity.
Reloading the integration created the valve-zone entities and refreshed model
metadata, but some surviving entity IDs still contained the old sensor model
and its obsolete soil-moisture entity remained unavailable. A future combined
cloud/local integration must include product family or a stable device ID when
reconciling replacements at a reused address; `(hub, address)` alone is not a
durable physical-device identity.

Two app/RF correlations on 2026-08-24 exposed an additional identity rule.
The RainPoint app's device IDs are 32-bit values whose upper byte matched the
catalogued product code in both tested families: the Left Bed HCS026FRF ID
begins with product code `0x48`, and the HTV405FRF ID begins with product code
`0x26` (decimal 38). Installation-specific lower 24-bit values are redacted;
they did not directly identify the devices' observed RF endpoints. This is
useful migration metadata and a two-family hypothesis, not yet a universal
identifier rule.

Source snapshot:
<https://github.com/brettmeyerowitz/homeassistant-homgar/blob/main/custom_components/homgar/data/product_models.json>

Control implementation snapshots:

- <https://github.com/brettmeyerowitz/homeassistant-homgar/blob/main/custom_components/homgar/api/client.py>
- <https://github.com/brettmeyerowitz/homeassistant-homgar/blob/main/custom_components/homgar/valve.py>

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
