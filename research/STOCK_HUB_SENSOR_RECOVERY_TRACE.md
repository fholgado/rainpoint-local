# Stock sensor recovery and compact-state trace

Offline evidence, 2026-09-27. This extends the
[firmware reference](STOCK_HUB_FIRMWARE_REFERENCE.md) using the qualified S3
decoder and the retained 1.1.1032/1.1.1040 applications. It changes no running
firmware, association, RF command or live configuration. The
[roadmap](../PROJECT_ROADMAP.md) remains the sole status checklist.

## What this changes

The earlier `set_report_mode` lead is **not evidence of a missing soil-sensor
wake command**. Its direct path is an app `ControlReportMode` request, a local
mode-byte update, and a server acknowledgement containing a current state
snapshot. The [follow-up consumer trace](STOCK_HUB_REPORT_MODE_CONSUMERS.md)
finds a class-0x50 RF report-reply extension; captured HCS026 is class 0x48 and
is excluded. This path needs incoming traffic and is not a soil wake mechanism.

Separately, the stock compact-state decoder now independently corroborates our
existing application parser. That provides a useful bridge to captured fields,
but does not make application field numbers interchangeable with internal
property selectors or normalized RF offsets.

## Report-mode path: established calls, limited semantics

All addresses in this section refer to **1.1.1040**.

| Evidence | Interpretation |
| --- | --- |
| App comparison at `0x42010F3D`, literal `0x4200113C` -> `ControlReportMode`; arguments `addr`, `interval`, optional `port` | Identifies the app-side operation, not a spontaneous device-recovery packet. |
| Caller `0x42011009..0x4201101B` -> `0x4204463C` | Passes address, port, interval and request context to the setter. |
| Setter reads config slot 4 into a 184-byte record at stack +168 | The following offsets belong to that local record, not an RF packet. |
| Checks record +0, +61, +13; successful path requires +13 = `0x50` | Do not call `0x50` a product code: its record-field semantics have not been established. |
| `0x420446E1` loads the record's +84 pointer; `0x42044708` stores the requested interval at pointed-object +6 | A local state update. Persistence and later readers are not established by this store alone. |
| Success diagnostic at `0x3C153C38`: `Start flow report:%d` | Narrows the investigation, but does not prove a flow-meter-only feature or a soil reporting contract. |
| `0x420446F0` -> `_bd_sdev_comm_pkg_sta_string` (`0x4203A8B4`) -> `0x42024A00` | Builds a state string from retained device properties. It is not an identified radio transmitter. |
| `0x42044705` -> `0x42044170` | Calls `bd_sdev_comm_send_control_sever_ack`, not an RF wake builder. |
| Server-ACK formats at `0x3C153BE8` / `0x3C153C04`, queue call `0x420442A8` to `dev_model` | JSON result/data or result/state acknowledgement on the inspected context path. Other request-context branches exist. |

The state-string builder reads property lists at device-record +120/+128 and
refreshes the receiver-RSSI property before formatting its snapshot. Neither
returning an app state snapshot nor acknowledging a mode request proves that a
sensor has supplied a new moisture reading.

**Consequence:** the follow-up trace rules this specific path out for captured
HCS026 soil sensors. Do not send guessed settings. It does not prove absence of
a recovery mechanism elsewhere in the image; see the model-qualified
[consumer evidence](STOCK_HUB_REPORT_MODE_CONSUMERS.md).

## Heartbeat lookup: semantic selector is not a wire type

The earlier bounded result remains: default heartbeat/offline bytes are 8/60,
nonzero configured overrides apply, and an additional branch uses
`off = 2 × (heart + 1)` when a retrieved byte is `0x80` or `0x03`.

The retrieval is now traced further:

1. `0x42040072` calls `0x4202421C` with selector 31, property structures from
   record +120/+128, and a one-byte output buffer.
2. `0x42024255` calls descriptor lookup `0x42024168`.
3. That lookup calls `0x4212B0E8`, which searches descriptors using multiple
   keys, including the requested selector and port-like/defaulted index. It
   returns the matching descriptor's byte at +12.
4. `0x4212B138` uses that returned identifier to locate a stored property entry.
5. `0x42024273` decodes its compact state with `0x42027CC0`, then copies at
   most the requested number of value bytes to the caller.

There is an **indirection through the device's descriptor table**. Therefore,
the number 31 passed by the heartbeat helper is not automatically compact
wire type 31 (battery in the previously correlated app payload), nor does it
identify a command to transmit. Descriptor contents and device-model semantics
are needed to name that byte accurately. The hub timer still does not prove
when a battery-powered sensor listens or retries after missing ACKs.

## Compact-state grammar recovered from the stock decoder

`bd_dp_protocal_get_dp_sta_size` is `0x42027CC0..0x42027D5E` in 1.1.1040.
The corresponding 1.1.1032 routine at `0x420269D8..0x42026A76` has the same
bounded field-extraction rules; diagnostic addresses/calls differ.

For header byte `h`:

| Form | Type | Value | Total encoded bytes |
| --- | --- | --- | --- |
| `h < 0x80` | `(h >> 4) & 7` | low nibble `h & 15` | 1 |
| `h >= 0x80`, bits 2..6 < 31 | `8 + ((h >> 2) & 31)` | next `(h & 3) + 1` bytes, little-endian | 2..5 |
| bits 2..6 = 31 | `39 + next_byte` | following `(h & 3) + 1` bytes, little-endian | 3..6 |

The helper copies up to four long-form value bytes into a zero-initialized
word. It outputs the type, value/size when requested, and consumed length.
Its pointer interface alone does not establish robust input bounds checking.
Our local parser must continue rejecting truncation regardless of stock behavior.

Examples: header `88` is type 10 with one byte; `DC` is type 31 with one byte;
`E0` is type 32 with one byte; `FC 0F` is extended type 54 with one byte.
Type meanings still depend on model and context. This is a compact-field
grammar, not a full RF frame decoder or evidence that every field exists on
every product. See [cloud representation](cloud/README.md#cloud-application-payload)
and the independently corroborated
[radio byte-boundary trace](STOCK_HUB_RADIO_PATH_TRACE.md).

### Existing-parser verification

New `tests/test_stock_compact_field_reference.py` exercises the actual existing
`rainpoint_protocol.parse_tlv` function without changing it:

- All 128 inline type/value combinations.
- All 124 direct long-form type/length combinations.
- All 1,024 extended type/length combinations.
- A mixed stream checking exact boundaries and values.
- All long-header truncated payloads, plus missing extension bytes.

Five tests pass. These are independently authored synthetic vectors, not
published firmware bytes, an emulation of the stock binary, or new RF commands.

Two additional capture checks in `tests/test_stock_sensor_frame_reference.py`
connect that grammar to HCS026 packets: five recorded moisture reports contain
native compact field `88 VV` after their two status bytes, where `VV` equals
the independently recorded percentage. Ten stock request/reply pairs echo all
six sequence bits and set the command ACK bit. Paired replies reverse the
native identities; the factory assignment has different identity semantics.
These tests do not reinterpret the preceding status bytes as compact fields or
qualify any new recovery transmission.

## Foreign-destination reconnect: a retained-record condition

**Static, 1.1.1040.** The header checker at `0x4204A170` contains a concrete
reconnect-result path, distinct from both ordinary ACK generation and app
`ControlReportMode`. Use native payload offsets from the radio trace here.

1. It compares incoming `P[1..4]` with the current gateway identity
   (`0x4204A1DD..0x4204A204`). Factory connection and factory-test commands
   have separate branches; the following applies to the ordinary mismatch path.
2. It looks up incoming sender `P[5..8]` via `0x4203B080` at `0x4204A2A3`.
   The helper's diagnostic identifies `bd_sdev_comm_check_dev_id_exist`; its
   aligned loop searches populated 184-byte device records by formatted ID.
3. For a found record, the checker reads the 32-bit field at record +32.
   Diagnostic `0x3C14DABC` describes a known subdevice, destination mismatch,
   reconnect need and a `change` value. **Only a nonzero +32 value** takes the
   ordinary mismatch path to internal result **9** (`0x4204A2F8`,
   `0x4204A35C`). A known ID alone is not enough; the zero branch rejects it.
4. That result is stored in the output reply's first native data byte
   (`0x4204A4D0`). Return value zero skips normal command dispatch in the caller
   (`0x42051C71`) and proceeds to reply-header construction at `0x42051CEA`.
5. The reply builder checks that data byte for 9 (`0x4203A540`,
   `0x4203A58B`). This branch reverses the incoming identities, including the
   incoming, noncurrent gateway identity, instead of loading the current gateway
   ID; its diagnostic is `this is a reconn ack`. It echoes the six-bit sequence
   and sets the command's ACK bit. Ordinary zero-explicit-length replies have
   one data byte, or two when incoming native sequence byte bit 6 is set.

The current-destination, known-record path separately clears record +32 to
zero and writes the record when that field or the received metadata changes
(`0x4204A48E..0x4204A4B6`). A setter and intended persistence path have now been
recovered below; its complete meaning, power-failure durability and device-side
interpretation of result 9 remain unestablished. Do not equate it with a command counter or a blanket license
to respond under another controller's identity.

An offline scan of the public full-frame corpus found **no ACK-flagged packet
whose first native data byte is 9**. Consequently this is a stock-code path,
not a captured successful recovery, a proven explanation of previous stock-hub
interference, or evidence that every supported device responds to it.

**Implication:** stock recovery can depend on retained hub state and a
device-originated packet. This path cannot wake a silent device by itself.
It merits passive correlation and model-specific acceptance evidence before any local
implementation proposal. Our existing authorized factory/paired rejoin remains
the supported recovery path; no result-9 transmitter was added.

### Gateway identity change sets and persists the condition

**Static, expanded Ghidra pass.** App-property parser `0x4200EC64` and desired
reply parser `0x4200F768` compare old/new `MID` values after numeric conversion.
When both are nonzero and differ, they set the byte at `0x3FCA4AD5` to 1 and
emit the `GW_change` diagnostic. The desired-reply path requests `Devs` and
`DevVers`; the app device-list updater is `0x4200E8A8`.

Within that updater's non-reserved-address rebuild branch, the flag gates a
store of 1 to device-record `+32`. At `0x4200EA41..0x4200EA4B`, the flag is
loaded through literal `0x42000EDC` and the value is stored to stack `+0x60`;
the record begins at stack `+0x40`. The selected instructions were independently
decoded with S3 objdump. The record is subsequently passed to
`0x4201DF80(1, 4, record)`. The updater clears the global migration flag when
finished. This is a concrete app identity/device-list migration path, **not a
timer or evidence that every known device is automatically marked on outage**.
It is not an exhaustive inventory of all possible setters.

The configuration slot-4 handler delegates to `0x4201DC70`:

- The full runtime device record is 184 bytes; ordinary reads copy that size.
- Writes compare its first `0x34` (52) bytes. If different, they call the KV
  setter using the descriptor's length/type, then copy the full record to RAM.
- The image descriptor at `0x3FC9F0A8` has length `0x34` and type 9. Record
  `+32` therefore lies in the saved prefix, unlike later runtime pointers.
- `HAL_Kv_Set` at `0x420ADFA4` dispatches type 9 to a blob setter and calls
  its commit helper, with separate write/commit failure branches. Boot config
  loading reads the retained records and tests `+32`, setting bit 3 of runtime
  byte `+115` when nonzero.

This establishes an **intended write/commit and restore path** for the condition,
not proof that any particular write succeeded or that association changes are
power-failure atomic. RAM is updated even when the KV operation reports failure.
No private NVS values were read or published. Evidence and helper scripts are
in the ignored `analysis/ghidra-20260927/` bundle described in
[decompilation](STOCK_HUB_DECOMPILATION.md#expanded-protocol-pass).

## Cross-version findings and limits

The report-mode setter also exists in 1.1.1032 at `0x42041010..0x420410FB`:
the same record gates, state packaging, server-ACK call (`0x42040B3C`) and
mode-byte store are visible. It is not a newly discovered 1040 wake feature.

The exact heartbeat-helper diagnostic name is absent from 1032, but that does
not prove absence of equivalent logic, a newly introduced timeout, or a fix
between versions. Recovering and comparing the older caller chain is required
before making such a claim.

## Reproducibility and remaining evidence boundary

The subsequent [offline lifecycle trace](STOCK_HUB_OFFLINE_RECOVERY_STATE.md)
resolves HCS026's deadline expiry and class-specific callback: update offline
state, clear a per-property metadata field, and notify the platform—no RF wake
on those inspected paths. A known native-01 announcement can reuse retained
association/channel. This does not prove what the sensor sends after an outage.
The retained HTV145 descriptor maps semantic selector31 to compact field24;
the corresponding HCS026/HTV405 tables remain absent.

Private, Git-ignored evidence is retained under
`captures/stock-hub-firmware/2026-09-27-adzoj0e3/analysis/sensor-recovery-20260927/`:
bounded disassembly, per-image segment hashes, identifier candidates and the
offline `rainpoint_sensor_research.py` script. Literal-load scans are navigation
candidates; instructions, call arguments and aligned branches support claims.
No NVS/FAT values, firmware bytes or credentials belong in the public note.

Next useful evidence is the descriptor mapping for the heartbeat selector,
additional reconnect triggers, and a captured
device-originated reconnect exchange with model-qualified acceptance.
The local retained-selector/revocation defects are separately reproducible and
do not depend on discovering a remote wake packet. See the
[local regression audit](STOCK_HUB_LOCAL_REGRESSION_AUDIT.md) and
[review-first improvement plan](STOCK_FIRMWARE_IMPROVEMENT_PLAN.md).
