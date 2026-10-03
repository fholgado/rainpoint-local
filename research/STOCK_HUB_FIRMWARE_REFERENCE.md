# Stock hub firmware reference — retained 1.1.1040 baseline

Evidence consolidated through 2026-09-28 for the **HWG023WBRF-V2** reference hub.
This is a subsystem reference, not a complete decompilation, recovered source
tree, or claim that **1.1.1040 is the latest available firmware**. Its baseline
is the privately retained image; update discovery and acquisition provenance
belong in [the update note](STOCK_HUB_UPDATE_DISCOVERY.md). A subsequently
acquired version requires its own inventory and address map before these
findings can be transferred to it.

The initial reference analysis changed no runtime code, hub configuration,
credentials, pairing state, RF behavior or hardware. Subsequent approved
source-only repairs are recorded in the [implementation plan](STOCK_FIRMWARE_IMPROVEMENT_PLAN.md);
none were deployed. Analysis includes bounded
instruction inspection, identifier-filtered application scans and a narrow,
CRC-checked private NVS export for the approved off-device lookup. No arbitrary
configuration strings are published. The vendor returned no newer offering
for this hub; no image was downloaded. Work priority and completion remain solely in
[PROJECT_ROADMAP.md](../PROJECT_ROADMAP.md).

## How to read the evidence

| Label | Meaning |
| --- | --- |
| **Inventory** | Retained image metadata or validated bytes; not necessarily runtime behavior. |
| **Static** | Bounded instructions corroborated by constants/diagnostics in the 1.1.1040 application. |
| **Identifier** | A string exists at the stated address; execution, feature enablement and semantics are not established. |
| **Capture** | Observed RF/app/device behavior in linked fixtures; the stock image version at capture time is not established unless the fixture says so. |
| **Inference** | A bounded interpretation of evidence, not a directly established fact. |
| **Unresolved** | The retained analysis does not answer this question. |

All `0x420…` code addresses and `0x3C…` data addresses below are **1.1.1040
runtime virtual addresses**, not flash offsets, recovered source symbols or
addresses portable to 1.1.1032. Diagnostic function names identify useful
search anchors; they are not an original symbol table. Instruction limitations
and a reproducible inspection procedure are described at the end.

## 1. Boot, image identity and persistent storage

**Inventory.** Two independent 8 MiB flash reads matched. The partition table
is at flash `0xA000`. Both applications passed esptool 4.11.0 image-checksum and
appended-hash validation and identify ESP32-S3, project `HWG009WB`, ESP-IDF
`v5.1.6-dirty`. The project name is a build label, not proof that this retail hub
is model HWG009WB. The retained source inventory is
[the original analysis](STOCK_HUB_FIRMWARE_ANALYSIS_20260927.md#validated-image-inventory).

| Partition | Flash offset | Allocation | Established role / boundary |
| --- | --- | --- | --- |
| NVS | `0xB000` | 200 KiB | Selected discovery fields mapped below; general schema/transaction semantics unresolved. |
| OTA selection | `0x3D000` | 8 KiB | Two selection records at offsets 0 and `0x1000`. |
| `ota_0` | `0x40000` | 3 MiB | Retained application 1.1.1032. |
| `ota_1` | `0x340000` | 3 MiB | Retained application 1.1.1040. |
| FAT storage | `0x640000` | 1 MiB | Contents intentionally not exposed; association/schedule layout unresolved. |
| Vendor storage | `0x7F8000` | 32 KiB | Vendor region; no inferred credential or pairing schema. |

| Application | Descriptor build time | Validated image SHA-256 |
| --- | --- | --- |
| 1.1.1032 | 2025-09-16 14:14:45 | `5d97e4b2c3ec7554fa89627c3a7e9727518e9d1cf02cac1f53d4076bb9fca7ec` |
| 1.1.1040 | 2026-05-21 18:40:46 | `e596ca60c238ccf639a896c6489014746a42387d000751656e345b7e3f5a041f` |

These hashes are validated image hashes, not the padded partition-file hash,
original ELF hash or a publisher signature. Selection records have sequence
1/state 2 and sequence 2/state 2 with matching sequence CRCs. Standard IDF
selection therefore identifies `ota_1` as the metadata-selected boot candidate.
The separately retained serial boot log also reports 1.1.1040. That is runtime
corroboration, not proof of fallback, custom overrides or anti-rollback behavior.
The format algorithms and primary-source links
are in [the format reference](STOCK_HUB_FIRMWARE_REFERENCES.md#ota-selection-metadata--verified-against-idf-v448).

**Identifier.** `bd_common_nvs_restore` (`0x3C14BC74`),
`_bd_common_nvs_data_init` (`0x3C14BD1C`), `bd_common_nvs_op`
(`0x3C14BE60`), `storage_fat` (`0x3C16C5C4`) and `kv_nvs`
(`0x3C16C7E0`) provide storage-navigation anchors. They do not establish what
factory reset deletes, when association data is committed, or whether command
counters survive stock-hub power loss. No restore trial has been performed.

**Static / inventory.** Discovery uses `gw_app_info` (224 bytes, host/port at
`+64`), `gw_region` (8 bytes) and `gw_dyn` (294 bytes, device name at `+22`).
A narrow export checked NVS entry and blob CRCs before using those values;
`cal_mac` supplies the private six-byte MAC. This does not recover the entire
NVS schema or establish atomic association/counter persistence. See the
[configuration trace](STOCK_HUB_HTTP_UPDATE_TRACE.md#configuration-mapping-and-endpoint).

**Static follow-up.** Slot 4 persists a 52-byte association prefix from a
184-byte runtime record; known rejoin retains address/selector. Configuration
revisions live separately in slot 3, and the shared RF phase is outside both
traced saved records. Native controller `02` promotes a pending association;
ordinary offline expiry differs from incomplete platform-admission cleanup.
RAM can still be updated after a failed persistence operation. These bounded
paths do not establish device-side retention or explain overnight failures;
see [association persistence](STOCK_HUB_ASSOCIATION_PERSISTENCE.md).

## 2. Application and task architecture

The image has separable diagnostic surfaces for radio I/O, subdevice protocol,
application/device model, HTTP, OTA, timers, BLE and storage. This is a useful
navigation map, **not a recovered runtime task topology**. Presence of a task
name does not prove creation on this board or recover its priority, core
affinity, queue depth, stack size or lifetime.

| Subsystem | **Identifier** anchors in DROM | Stronger evidence, if available |
| --- | --- | --- |
| Application | `app_main` `0x3C14808C`; `_app_main_task` `0x3C14839C` | Startup order and board-selection branches unresolved. |
| RF send/receive | `RF_tasks` `0x3C1491A0`; `RF_taskr` `0x3C1492B0`; `BD_RF_Mastersend_task` `0x3C149374`; `BD_RF_MasterRCV_task` `0x3C1493A4`; `BD_RF_app_Main` `0x3C1493BC` | Code references for send/receive helpers near `0x4201555C` / `0x420158F0`; not a complete scheduler trace. |
| Subdevice protocol | `sdev_comm` `0x3C1470E0`; `bd_sdev_common_protocol_parse` `0x3C156064`; `bd_sdev_comm_rf_dp_protocol_process` `0x3C156700` | Several connection, ACK, heartbeat and configuration paths are bounded below. |
| Task messaging | `bd_common_send_msg_to_task_rcv_hdl` `0x3C14BBE0`; task-param setters/getters `0x3C14BE94` / `0x3C14BEC4` | OTA discovery queues message 47; general message ABI unresolved. |
| HTTP | `http_task` `0x3C14734C`; `_bd_http_task` `0x3C14F684` | Discovery dispatch and request preparation traced in section 8. |
| Device model/MQTT | `_dev_model_task` `0x3C14D0B8`; `bd_model_mqtt_recv_thread` `0x3C14D1C4`; `_bd_dm_mqtt_default_recv_handler` `0x3C14D1A0` | Cloud network observations are separate from static task proof. |
| OTA | `ota_task` `0x3C14C014`; `_bd_ota_task` `0x3C1507F4` | Successful discovery callback reaches OTA starter. |
| Timers/state/UI | `timer_task` `0x3C14C008`; `sta_sync_task` `0x3C14C02C`; `button_task` `0x3C14C054`; `_led_hint_task` `0x3C14F958` | Timer vocabulary is not a decoded watering scheduler. |
| Other shared-image paths | `uart_task` `0x3C14C020`; `ook_task` `0x3C14C03C`; `elec_task` `0x3C14C048`; `_ble_host_task` `0x3C148F1C` | Board applicability and peripheral roles unresolved; no second-MCU inference. |

**Unresolved.** Interrupt-to-FIFO dispatch, receive-buffer ownership, task
creation graph, synchronization primitives, queue backpressure, watchdog policy
and precise radio arbitration are not recovered. A local node should not adopt
a stock-looking concurrency design merely from these names.

## 3. Radio hardware, framing and receive/transmit boundaries

### CMT2300A register and FIFO backend

**Static.** `CMT2300A_OOK_Switch` (`0x42015E90`) calls `0x4205DDF4`
six times. That helper loops over `(start + index, table[index])`, forwarding
through `0x42015BF0` to register write `0x42016EB0`. The bank destinations and
lengths match the manufacturer's configuration layout:

| Register start | Length | Table address |
| --- | --- | --- |
| `0x00` | 12 | `0x3C149780` |
| `0x0C` | 12 | `0x3C149774` |
| `0x18` | 8 | `0x3C14976C` |
| `0x20` | 24 | `0x3C149754` |
| `0x38` | 29 | `0x3C149734` |
| `0x55` | 11 | `0x3C149728` |

This proves a register-table loading path, not that this OOK profile is active
during FSK enrollment/telemetry. The follow-up trace separates it from normal
packet profiles and bounds its `A5/6C`, length-11 caller. Normal tables select
32-byte fixed payloads, four-byte sync and hardware CRC. Actual board mode and
per-exchange overrides remain partly unresolved. See
[the radio trace](STOCK_HUB_RADIO_PATH_TRACE.md). Chip register semantics are recorded separately in
[the manufacturer-backed reference](STOCK_HUB_FIRMWARE_REFERENCES.md#cmt2300a-configuration--confirmed-documentation).

**Inference from ordinary instructions.** Candidate GPIOs are 10 register
select/CSB, 11 bidirectional SDIO, 12 SCLK and 13 FIFO select/FCSB. Supporting
entries are register write/read `0x42016EB0` / `0x42016EF8`, byte sender
`0x42016E34` with loop target `0x42016E40`, FIFO write `0x42016F48`, and
GPIO helpers `0x42016C4C`, `0x42016CE0`, `0x42016CF0`. SDK binding,
interrupts, physical continuity and board revision are unqualified. This is
not wiring guidance. See [the bus analysis](STOCK_HUB_FIRMWARE_ANALYSIS_20260927.md#radio-configuration-and-board-mapping-follow-up-evidence).

### Native hardware frame versus the legacy normalized view

**Capture.** Tested devices use 2-FSK at approximately 20 ksymbol/s, sync
`79 f4 88 2f 28`, and a normalized 38-byte frame: sync 0–4, endpoint A 5–8,
endpoint B 9–12, body 13–35, trailer 36–37. Endpoint positions are protocol
roles, not universal source/destination fields. Wake forms include 320,
1,200 and 2,400 symbols. CRC-CCITT over 0–35, initial zero, XOR the received
trailer yields accepted legacy residues `c713` or `4f03`. Their common native
CRC explanation follows; retain qualified transmitter bytes rather than
selecting residues speculatively. See [common protocol](../protocol_documentation/common.md).

**Static plus capture corroboration.** The missing five-byte constant now has
an explanation: hardware sync is **`f3e9105e`**, followed by a 32-byte payload
and CRC-CCITT seeded **`a8a8`**. Our normalized view begins one bit early,
including a leading zero and omitting the final hardware CRC bit. Its familiar
five-byte prefix incorporates seven bits of native payload header `51`.

Native payload byte `p[i] = ((n[i+4] << 1) & 255) | (n[i+5] >> 7)` for
`i=0..31`. This recovers all payload bytes and verifies the observable 15 CRC
bits in 516/518 unique public fixture frames; both exceptions are explicit
corrupted/synthetic negative controls. This is not 516 independent stock trials.

Both normalized residues arise under the same hardware CRC seed. Selecting the
other residue while holding normalized bytes 0–35 fixed changes the final
native payload bit, so neither residue is inherently invalid. This does not
authorize changing successful builders. Register tables, internal-buffer/FIFO
calls and independent tests are in [the radio trace](STOCK_HUB_RADIO_PATH_TRACE.md).

## 4. Association, identity and channel selection

**Static.** Connection handler `_bd_sdev_comm_connect_req` begins at
`0x420473A8`; the new-device path logs allocation at `0x420475A9` and calls
`_bd_sdev_comm_allocate_channel` at `0x42047611`. Allocator `0x420403D4`
builds usage counts through `0x420402B8`, then calls `0x420388D8`, which
compares internal indices 3–14 and selects among minimum-use entries before
returning index plus one. Counts include device and pending-list fields with
conditional weighting. The tie helper `0x420AE4FC` takes an indirect value
modulo candidate count; its source is not identified, so randomness is not
proven. The handler then calls the default-heartbeat helper at `0x4204761D`.

This establishes a usage-based allocation path, but neither its internal-index
mapping to RF selectors nor the products that take every branch. Captures
independently distinguish announcement counters, assigned selectors, app
Device Address and command counters. In two HTV145 stock enrollments, accepted
factory counters 0 and 2 both led to selector 6/subchannel 12. Sources and exact
addresses: [pairing clues](STOCK_HUB_PAIRING_CLUES_20260927.md#connection-setup-calls-a-usage-based-channel-allocator),
[counter-0 fixture](fixtures/htv145_counter0_app_first_stock_enrollment_20260901.json),
[counter-2 fixture](fixtures/htv145_counter2_stock_enrollment_20260901.json).

**Static.** `_bd_sdev_comm_check_header_data` (`0x4204A170`) distinguishes
request and confirmation branches; confirmation near `0x4204A460` references
diagnostic `0x3C154840`. Header packer `0x4203A4FC` has a reconnect-ACK
branch near `0x4203A5BA`, diagnostic `0x3C1527C8`, copying an identity field
from input where another branch loads gateway context. The separately traced
master header at `0x4203A344` packs native byte 0 `51`, device identity 1–4,
gateway identity 5–8, six-bit sequence 9, command 10 and payload length 11.
The one-bit boundary above maps this layout into normalized bytes. Reconnect
branch applicability and retained-state acceptance remain unqualified.

The subsequent [recovery trace](STOCK_HUB_SENSOR_RECOVERY_TRACE.md#foreign-destination-reconnect-a-retained-record-condition)
narrows this: foreign-destination traffic can produce result **9** only when the
sender has a retained record and its `+32` change field is nonzero. The reply
reverses the incoming identities, including the foreign gateway identity. A
known sender alone is insufficient. Expanded decompilation found an app gateway
identity-change/device-list rebuild setter and a KV write/commit/restore path
for that field in the record's 52-byte persisted prefix. Actual device acceptance
remains unknown; no matching result-9 public capture was found. This establishes
a migration trigger, not an outage timer or a way to wake a radio-silent sensor.

**Capture.** Device families have different transcripts, not one universal
handshake:

| Family | Observed exchange / qualification boundary | Evidence |
| --- | --- | --- |
| HCS026 | Validated local/repeat profile: three replies, then observation-only short/terminal messages. Two stock first-enrollment captures contain five replies. Known factory rejoin and authorized paired recovery are distinct. | [Sensor protocol](../protocol_documentation/hcs026frf.md), [pairing fixture](fixtures/hcs026_gateway_pairing_replies.json). |
| HTV405 | 18 observed valve rows / 17 gateway transmissions; the stock final `9a` tail is not necessary for the accepted generated local association. | [Four-zone enrollment](../protocol_documentation/htv405frf.md#new-enrollment), [stock fixture](fixtures/htv405_gateway_pairing_replies.json). |
| HTV145 | Six numbered rows plus unsolicited delayed 2,400-symbol-wake configuration; accepted local prefix reaches 5/6 and supports controls, but final `2c/99` request remains unproven. | [Single-zone enrollment](../protocol_documentation/htv145frf.md#enrollment), [partial-association controls](fixtures/htv145_partial_pairing_control_acceptance_20260905.json). |

These are captured rows, not recovered stock source-code state counts. A white
valve LED, accepted association, complete transcript and accepted command are
different observations. Hub firmware cannot directly reveal the valve LED
state machine. Capability/per-port candidate entries `0x4203F0F0`,
`0x420409AC` and `0x4203DFD0` support investigating model-specific parsing,
but do not yet explain which configuration rows are mandatory.

**Static / capture.** Native `59/D9` is a generic device-parameter read/reply.
HTV145 requests `32` and receives `00 32 00`; HTV405 requests `32`–`35` and
receives different data. A recovered fallback maps `ID - 32` to a port and
returns its length-prefixed byte array, fitting both captures. The retained
HTV145 model descriptor now qualifies this fallback on fresh initialization:
`00 32 00` is an empty array. HTV405 and historical runtime contexts remain
unqualified; see the [descriptor trace](STOCK_HUB_POSTBOOT_TRACE.md).
Three failed local trials instead repeat the preceding `06` plan-read request
at changing phases. The pre-fix matcher ignored these after local transmission;
the source-only repair adds bounded replies while preserving the first response.
It does not establish why that first reply failed or full hardware completion. See the
[terminal trace](STOCK_HUB_TERMINAL_PAIRING_TRACE.md).

## 5. ACKs, recovery and report health

### Stock paths

**Static.** `_bd_sdev_comm_test_gateway_rf_ack` (`0x4203A7E0`) checks the
low five bits of structure byte 11 against 1 and tests a result byte for zero;
diagnostics distinguish invalid length and result-code failure. Its structure
is not mapped to normalized RF bytes. This is not a decoded sensor ACK, valve
command ACK or complete response-correlation contract.

**Static.** `bd_sdev_comm_process_mcu_abnormal_restart` (`0x42051FD0`) has
product-dependent branches and an `MCU restart!!!!` diagnostic.
`bd_sdev_comm_inform_dev_ser` (`0x42052280`) can call parameter-update helper
`0x4204B874`. Neither establishes valve battery-rejoin semantics or a command
counter reset; `ser` must not be expanded to “sequence counter.”
[Detailed boundaries](STOCK_HUB_FIRMWARE_ANALYSIS_20260927.md#acks-counters-and-restart-leads-with-important-boundaries).

**Static.** Pending reply matcher `0x4204A550` checks gateway identity,
command/ACK flag, all six sequence bits and endpoint identity. Retry handler
`0x420443F8` resends the retained packet, changing transport metadata rather
than allocating a new command sequence. This is stronger than the earlier
diagnostic-name inventory, but does not yet establish retry/expiry limits,
all unsolicited-report deduplication, or valve-side acceptance rules. See
[the valve/state trace](STOCK_HUB_VALVE_STATE_TRACE.md).

The subsequent [ACK lifecycle trace](STOCK_HUB_ACK_RETRY_LIFECYCLE.md) qualifies
ordinary transactions as initial send plus up to four identical retransmissions
on a 700-ms periodic timer. Queue activity can alter actual timing. Matched
negative replies consume their own transaction; timeout failure is locally
generated, not a received rejection. No counter reset or special resync packet
was established on these paths. Conditional result forwarding can consume a
generated phase and then overwrite the packet phase with an echoed one.
The [two-version comparison](STOCK_HUB_VERSION_COMPARISON.md) finds unchanged
generator instructions and the same six-bit ACK correlation contract.

The [local sequence audit](STOCK_HUB_SEQUENCE_MATCH_AUDIT.md) reproduces three
consumer gaps: wrong-phase negative responses can clear HTV145/HTV405 pending
reservations, and the HTV405 node accepts an opposite-action positive response
that the gateway rejects. These are synthetic fixture-based regressions, not
proof of an observed false watering confirmation or the cause of a past outage.
The approved source follow-up fixes these with full-phase correlation and
preserves the qualified idle-anchor exception. Unmatched HTV145 positives no
longer consume pending state. Native/Python regressions pass; not deployed.

### Capture-backed ACK contracts

| Device | Known reply behavior | Timing/evidence boundary |
| --- | --- | --- |
| HCS026 | Reverse the validated association route; body bytes 0/1 are report bytes OR `80`/`40`, bytes 2–4 `81 00 01`, remaining body zero; preserve residue. | 320-symbol wake; approximately 177–188 ms from report sync to reply start. [Sensor ACK](../protocol_documentation/hcs026frf.md#routine-report-acknowledgement). |
| HTV405 | ACK uses five-bit report counter, captured repeat flag, body bytes 2–4 `01 00 01`, zero tail, association residue. | Local schedule 49.5 ms after receive completion matches captured response slot. [Four-zone ACK](../protocol_documentation/htv405frf.md#routine-link-report-and-acknowledgement). |
| HTV145 | Reverse association route, echo byte 13, OR byte 14 with `40`; bytes 15–17 `01 00 01` for state or `00 80 00` for summary. | Local selector-6 profile: 320-symbol wake, residue `4f03`, provisional 40 ms post-reception target; durable summary suppression and exact timing remain qualification gates. [Single-zone ACK](../protocol_documentation/htv145frf.md#report-and-summary-acks). |

These use different timing origins; none is a recovered universal stock ACK
delay. Multiple receivers may hear a report, but one persistent custom owner
must reply. The reproduced local failed-revocation handoff/deletion defects are
separate implementation findings, not firmware discoveries or proof of a
historical RF collision. See [implementation comparison](STOCK_HUB_IMPLEMENTATION_COMPARISON_20260927.md).

### Heartbeat and offline policy

**Static.** `bd_sdev_comm_get_heart_and_off_inv` (`0x4203FFE4`) initializes
two output bytes to 8 and 60 at `0x4203FFEE..0x4203FFF6`. Nonzero configured
low/high bytes override them at `0x4204002D..0x4204003E`. A conditional branch
at `0x42040094..0x4204009B` changes the second to `2 × (first + 1)`.
S3-decoder rechecking narrowed the predicate: a successful internal lookup
selector 31 supplies a byte equal to `0x80` or `0x03`. That lookup goes through
a device descriptor before selecting the compact stored field; selector 31
is not necessarily wire type 31. Its semantic meaning and RF mapping remain
unresolved; it is not a decoded wake command.
[Lookup and codec evidence](STOCK_HUB_SENSOR_RECOVERY_TRACE.md).
For the retained HTV145 descriptor only, that semantic selector now resolves
to category-1 compact field24, if its stored value exists. HCS026 and HTV405
remain unqualified. This is not an RF offset or a sensor sleep timer.
The [mode-reader trace](STOCK_HUB_REPORT_MODE_CONSUMERS.md) now connects the
mode byte to incoming class-0x50 report replies, excluding captured HCS026
class 0x48. No remote soil-wake mechanism follows from this path.
Diagnostic `0x3C153654` names the
fields `heart` and `off`. Caller `0x420400E0`, at `0x42040100..0x42040106`,
multiplies the second by 60,000 before deadline helper `0x420AC074`.

**Inference with strong static support.** Defaults are 8-minute heartbeat and
60-minute offline policy with configuration/device overrides. Separate helper
`0x4203FF60` returns fallback 480 or configured low byte × 60, consistent with
480 seconds. This is not the measured configuration of every sensor. The full
SDK time-source binding is not traced. The two diagnostic names are absent in
1.1.1032; equivalent older behavior may still exist under different code/names.
[Full evidence](STOCK_HUB_FIRMWARE_ANALYSIS_20260927.md#heartbeatoffline-policy-instruction-backed-finding).

**Unresolved.** Offline bookkeeping does not prove that a dormant sensor is
listening, that the hub can remotely wake it, or that it retries forever.
`bd_sdev_comm_set_report_mode` at `0x4204463C` is now traced from app request
`ControlReportMode`: it updates a local mode byte and calls a server-ACK builder,
not an identified RF wake transmitter. The equivalent path exists in 1.1.1032.
The downstream class-0x50 reply extension is now traced and excludes captured
HCS026 class 0x48; it does not support the earlier missing-soil-wake hypothesis.
Recovery still requires the demonstrated device-originated
traffic and authorized ACK owner; a fresh heartbeat is not necessarily a new
moisture measurement.

The [offline-state trace](STOCK_HUB_OFFLINE_RECOVERY_STATE.md) follows HCS026
expiry through its registered callback: it marks offline, clears per-property
metadata and reports the change, with no RF wake in the inspected path. Ordinary
incoming traffic refreshes its deadline; a recognized connection announcement
can reuse the retained association and channel without the unknown-device
admission check. This neither proves the sensor periodically announces while
silent nor makes an ordinary outage an identity-migration event.

## 6. Channel change, clocks and timers

**Static.** `ReciCH` writes gateway configuration byte `+164`; a changed flag
gates the call to `0x4204BBC0(1)`. The argument selects notification kind, not
the new RF channel. Builder `0x4204ABA0` emits native command `20`, payload
`[per-device configuration version, 4, new receive selector]`. The separately traced
`app_main` call uses argument 2 and emits `[per-device configuration version, 1]`.
The first byte comes from slot-3 `subdev_ver`, not the device RF channel;
setter/serializer evidence corrected the earlier channel interpretation.
Both call the master header builder and consume the shared six-bit sequence.
Eligible-recipient guards, exact addresses and capture limits are in the
[channel-change trace](STOCK_HUB_CHANNEL_CHANGE_TRACE.md). No retained public
capture confirms either payload; absolute-frequency mapping, device acceptance,
durable retune and rollback are unresolved. Startup sequence consumption is a
possible source of advancement, not proof of overnight counter reset.

The captured HTV145 delayed configuration is the same native command with data
`02 00`: consistent with version 2, update kind 0, not RF channel 2. The exact
callback and delay origin for that recording remain unproven. Native `05`
returns stored per-port controller bytes; `06` reads paged plans, with a
status-only zero response on the empty branch. Controller-report `02` can
request the configuration version in its reply. These are model/context-aware
operations rather than universally numbered pairing checkpoints. See the
[configuration trace](STOCK_HUB_PAIRING_CONFIGURATION_TRACE.md) and
[capture comparison](PAIRING_NATIVE_COMPARISON.md).

The [revision lifecycle trace](STOCK_HUB_CONFIGURATION_LIFECYCLE.md) establishes
an asynchronous parameter-fetch/install/notifier path and local rain-delay
revision increments. It also recovers the fourteen-byte valve settings layout,
without assigning unproved units. Download completion, a notifier ACK, durable
association and accepted controls are separate outcomes. The offline
[trace analyzer](PAIRING_TRACE_ANALYZER.md) exposes these distinctions without
changing the proven local pairing prefix or transmitting anything.

**Static.** The connection handler installs a deadline with constant 10,000
using the known time-add helper. Its lifecycle purpose is unresolved; it is
not evidence to replace the captured approximately 2.95-second HTV145 delayed
configuration or the local pairing window.

**Identifier.** `_bd_sdev_comm_read_plan_param` (`0x3C1563A4`),
`_bd_sdev_comm_check_outlet_plan_trigger` (`0x3C155A50`),
`bd_sdev_comm_timer_timeout_callback` (`0x3C156880`),
`_bd_ota_plantimer_callback` (`0x3C150804`) and the timezone/DST diagnostic
at `0x3C14B59C` identify distinct timer-related areas. Stock schedule storage,
clock resynchronization, DST adjustment, missed-run behavior and separation
between hub plans and valve-local plans are not recovered.

**Capture plus serializer trace.** Sensor assignment carries packed wall-clock/date
in normalized bytes 21–24. Valve native control duration is an unsigned
little-endian value in **seconds**. The earlier normalized two-second scalar is
the same field shifted by one bit, not the native unit; its low seconds bit
continues into the next normalized byte. Cloud duration also uses seconds but
has a separate application representation. HTV405 autonomous
60-second stops occurred 60.947–61.645 seconds after cloud acceptance without
explicit close, supporting valve-owned duration expiry for those trials.
[Sensor clock](../protocol_documentation/hcs026frf.md#new-enrollment),
[duration codec](../protocol_documentation/htv405frf.md#duration),
[expiry fixture](fixtures/htv405_stock_auto_stop_20260824.json).

## 7. Valve controls, telemetry and capabilities

**Static plus capture.** Control builder `0x4204FCAC` uses native command `21`,
then port, control mode, work mode and little-endian seconds at native bytes
12–16. Header sequence comes from global generator `0x42037920` and is stored
in six bits. Normalized byte-15 values `82`/`81` represent lengths 5/3, not
distinct open/close opcodes. The previously named marker/phase bit is part of
the sequence representation; stock consecutive opens corroborate this.

The recovered application entry clears a RAM range containing the sequence byte;
this proves zero at that boot stage, not absence of later restoration/advancement,
a periodic reset, an overnight reboot or valve acceptance of arbitrary sequence
values. See [boot-state evidence](STOCK_HUB_BOOT_STATE_REFERENCE.md).
Generic soil, flow-meter
or battery vocabulary still cannot establish model capability. See
[the valve/state trace](STOCK_HUB_VALVE_STATE_TRACE.md) for exact boundaries.

**Capture.** The device references remain the authoritative byte-level
interoperability definitions:

| Concern | HTV145 | HTV405 |
| --- | --- | --- |
| Association | Store controller, valve route and companion; qualified local branch counter-2/selector-6. | One device, four mutually exclusive zones; selector-2 and selector-6 profiles cannot be mixed. |
| Control | Legacy view splits six-bit sequence across bytes 13–14; byte 15 carries length. Native command `21` plus control mode distinguishes actions; 2,400-symbol wake. | Same broad command family, with one-based zone in normalized byte 17; all zones share command state. |
| Duration | Native little-endian seconds; legacy view splits its bits across normalized bytes 19–21. | Same native units; requested/remaining fields have different offsets. The approved source repair preserves the low remaining-seconds bit (895, formerly 894); not deployed. |
| Result | Positive response family `86`, result `80`, correlated association/counter/action/duration; ordinary result `83` is not success. | Positive correlated response, not transmitted intent, establishes control acceptance. |
| State/history | Repeated session summaries update historical usage/duration, not current watering or pending close. | Strict state report/response establishes zone state; idle zone zero clears all four. |
| Capability | Usage and categorical battery supported by correlated evidence. | Water usage unsupported; local battery bit candidate remains unqualified. |

Full matchers and exceptions: [HTV145](../protocol_documentation/htv145frf.md),
[HTV405](../protocol_documentation/htv405frf.md),
[evidence ledger](VALVE_PROTOCOL_STATUS.md). Device references define the current
implementation; the stock trace explains the representation and records a
source-only remaining-seconds correction, not an already-deployed fix.

Command counters, pairing counters, routine-report counters, physical state
and historical summaries remain separate. The narrow qualified idle counter
anchors do not imply a general reset-on-battery-cycle rule. Stock consecutive
HTV145 opens can change marker polarity, so the local alternating open/close
recipe is not a universal action-to-marker mapping. Restart or missing telemetry
must never cause speculative valve closure or counter search. A stock diagnostic
name supplies no authority to weaken those established control boundaries.

## 8. App/cloud interfaces and OTA

### Application and network observations

**Capture.** The archived network observation found outbound TLS-wrapped MQTT
on TCP 1883 and short TLS 1.2 connections on TCP 1446 during valve actions;
no local listening service was confirmed in that scan. A `*.homgarus.com`
certificate did not expose encrypted payloads. This is an observation of one
test, not proof that every firmware lacks a local service.
[Cloud evidence](cloud/README.md#hub-network-behavior).

The app/cloud `10#` TLV representation and observer MQTT envelope are not raw
38-byte RF frames. App Device Address is a reusable slot; model metadata,
receiver RSSI and categorical battery are not automatically RF fields. The
observed `/app/device/controlWorkMode` body carries semantic port/mode/duration,
not the RF sequence/trailer. No complete cloud-input-to-stock-serializer mapping
has been recovered. Runtime local interoperability must remain independent of
these services. [Cloud/application evidence](cloud/README.md),
[gateway behavior](../protocol_documentation/hwg023wbrf-v2.md#cloudapp-metadata).

### Device-side firmware discovery

**Static.** The URL template at `0x3C14F2D4` is
`%s://%s:%u/app/edge/firmware/upgrade`. Builder `0x4202BC48` reaches
production construction at `0x4202C0D1` using configured protocol/host/port.
Static region host names are not proof of the configured endpoint; the separate
private-LAN development fallback is not a vendor server.

Request construction `0x42030EF8` uses template `0x3C1506A8`:

```json
{"Mac":"<lowercase hyphenated six-octet MAC>","modelCode":"<decimal model code>","currentVersion":"<version>"}
```

All three are strings. Message 47 is set at `0x42030F8D` and queued at
`0x42030F95`; dispatch references `0x4202BDEA` / `0x4202BDEF`.
Success callback `0x42031048` accepts string `data`, copies it to OTA-request
offset +40 and calls `bd_ota_start` (`0x42030D3C`) at `0x42031100`.
**Therefore invoking the hub's discovery path can initiate OTA; it is not a
download-only operation.**

Request preparation calls `_bd_http_modify_req_data` (`0x4202B6D0`) at
`0x4202C562`. The message-47 mask branch calls the helper identified as
`_bd_http_hmac_md5_encoding` (`0x4202B5A4`) at `0x4202BABA`.
The [HTTP trace](STOCK_HUB_HTTP_UPDATE_TRACE.md) establishes POST JSON,
configured regional HTTPS endpoint, device-name/timestamp wrapper, and
HMAC-MD5 over the traced input with raw-digest Base64 encoding. The key is
derived using a firmware-resident format and device name; private values are
not reproduced. The stock client can fall back to HTTP on later retries;
our lookup deliberately did not emulate that behavior.

**Observed off-device result.** On 2026-09-27, the approved model-289/version-
1.1.1040 request using the stock user agent returned HTTP 200, result zero and
empty `data`: no newer image was offered to this hub by this regional service.
No firmware was downloaded and the hub did not run an update check. Full
server validation rules, other rollout cohorts and OTA image authentication
remain unresolved. See [lookup provenance](STOCK_HUB_UPDATE_DISCOVERY.md#live-lookup-result--2026-09-27).

**Identifier.** `_bd_ota_check_image_header` (`0x3C1507AC`),
`_bd_ota_gw_firmware` (`0x3C1507C8`), `_bd_ota_subdev_firmware`
(`0x3C1507DC`) and `_ota_http_event_handler` (`0x3C150844`) locate validation,
gateway/subdevice and HTTP paths. Their names do not prove signed-update
enforcement, subdevice update support on the tested valves, power-loss safety,
downgrade acceptance or update rollback policy.

## 9. Security and preservation

**Inventory.** The private readout manifest records secure boot and flash
encryption disabled. This is a readout-time snapshot, not an eFuse backup or
proof any replacement will boot. A valid ESP image hash establishes integrity,
not publisher authenticity. Stock OTA authentication/signature enforcement has
not been fully audited; discovering a HMAC-labelled request helper does not
establish image authentication.

Raw flash contains private configuration. Keep it, extracted images, derived
disassembly, authentication material and any signed download URL private and
untracked. This document publishes independently described behavior and
addresses, not proprietary code or secrets. Do not clone same-unit flash to
another unit, erase vendor NVS, change OTA selection, burn eFuses or flash a new
image as part of documentation. Backup validity is not demonstrated restore
safety. [Security and preservation assessment](STOCK_HUB_CUSTOM_FIRMWARE_FEASIBILITY.md#preservation-security-and-publication-boundaries).

## 10. Unresolved coverage map

This map defines the limits of the reference, not another project checklist.
Prioritization and acceptance gates belong in [the roadmap](../PROJECT_ROADMAP.md).

| Area | Missing evidence | What would distinguish a supported finding |
| --- | --- | --- |
| Latest version | Other rollout cohorts/regions and any future offered artifact. | Approved lookup offered no newer image for this hub on Sep 27; that scoped result is not a global latest-version claim. |
| Boot/persistence | Stock initialization, schema, commits, reset scope, recovery and rollback. | Bounded boot/storage call paths plus approved, non-destructive observations; metadata alone is insufficient. |
| Task architecture | Creation, queues, priorities, locks, interrupt ownership and buffer lifecycle. | Creation/call graph and argument tracing; string inventory alone is insufficient. |
| Active RF profile | Actual board mode, overrides, absolute frequencies and complete on-air CRC bit. | Static normal/OOK tables and native/normalized mapping are now corroborated; passive same-exchange bus/SDR qualification remains. |
| Pairing readiness | Mandatory/optional parameter rows, retained-state acceptance and per-model parameter semantics. | Terminal command is parameter read; repeated preceding plan-read requests expose a local recovery gap. Initial rejection remains unproven. |
| ACK/retries | All unsolicited duplicate rules and measured end-to-end timing. | Full-phase matching, ordinary four-retry/700-ms timer, queue expiry and result paths traced; no counter reset established there. |
| Dormant recovery | Model-qualified heartbeat descriptors, failed-ACK behavior and battery cycle. | Report-mode consumers are class-0x50 report replies, excluding captured HCS026; controlled device-originated exchanges remain necessary. |
| Channel changes | Absolute-frequency mapping, device acceptance and durable retune. | App-to-serializer and separate startup path are traced; an approved coherent before/after RF capture is still needed. |
| Valve counter/phase | Arbitrary ordering, counter persistence/reset, all negative responses. | Version/model-scoped serializer and response traces validated against captures; `ser`/restart strings are insufficient. |
| Schedules/time | Plan execution location, DST, rain-delay and restart/missed-run behavior. | Timer/storage/command-path traces and matching device evidence; shared-image vocabulary is insufficient. |
| OTA/security | Complete transport auth, image checks, subdevice applicability and failure recovery. | Bounded request/download/validate/select/reboot paths and scoped acquisition provenance; string names are insufficient. |

## 11. Reproducing and extending the reference

The private artifact root is
`captures/stock-hub-firmware/2026-09-27-adzoj0e3/`. Relevant retained files are
`app-ota_1.bin`, `ota_1-irom.bin`, `ota_1-irom.disasm`,
`analysis/rainpoint-stock-irom.elf`, `manifest.json` and the two full reads.
These deliberately are not public documentation dependencies; another reviewer
needs lawful access to an equivalent version-qualified image to reproduce
static claims. Public fixtures and protocol definitions reproduce the separate
capture-derived interpretation.

An ESP application segment starts after an eight-byte segment header containing
load address and length. The initial header is at image +24; subsequent headers
follow the preceding segment bytes. For segment load address `A`, file-data
offset `F` and image offset `P`, virtual address is `A + P - F`. In 1.1.1040,
DROM begins `0x3C140020` and IROM `0x42000020`. Read segment headers for each
image; do not derive addresses by adding a flash partition offset.
[Format reference](STOCK_HUB_FIRMWARE_REFERENCES.md#esp-image-and-partition-formats--confirmed).

For the additional **Identifier** rows, reproduce using a read-only script:
parse the application's segment headers, select DROM (`0x3C000000 <= A <
0x3E000000`), match printable strings, retain only complete identifiers matching
`[A-Za-z_][A-Za-z0-9_]{4,100}`, and print only the exact names listed in this
document with `A + match_offset`. This procedure avoids arbitrary string dumps
and all NVS/FAT access. An identifier address is not a callable entry point.

For already bounded instruction claims, the retained synthetic ELF permits
focused inspection, for example:

```sh
/Users/federicoholgado/.platformio/packages/toolchain-xtensa-esp32/bin/xtensa-esp32-elf-objdump \
  -d --start-address=0x4203FFE4 --stop-address=0x420400A4 \
  captures/stock-hub-firmware/2026-09-27-adzoj0e3/analysis/rainpoint-stock-irom.elf
```

The original installed ESP32 decoder crashed on raw input; ELF wrapping worked
but restored no symbols or source. Follow-up now uses the checksum-verified
official S3 decoder for ESP-IDF 5.1.6, installed separately from production
tools. It passes the synthetic raw-input regression and reads the full IROM
segment. Nine bounded regions agree with the prior ELF analysis. See the
[tool qualification](STOCK_HUB_DECODER_TOOLING.md#completed-local-qualification)
for versions, exact bounds and private reproduction artifacts.

Literal pools, padding and mid-instruction starts still produce plausible
nonsense, even with the correct decoder. Establish entry/branch boundaries,
inspect literals separately and corroborate claims before treating output as
code. This is not whole-image decompilation or qualification of every prior
static inference.

New firmware must be inventoried independently, then traced using diagnostic,
data and control-flow correspondence. A vanished diagnostic does not prove a
removed feature, and an unchanged version label does not prove identical bytes.
Keep capture dates, software versions and evidence classes attached to every
new result before using it to propose local-runtime changes.
