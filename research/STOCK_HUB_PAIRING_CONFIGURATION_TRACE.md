# Stock pairing configuration: shared operations, model-specific data

2026-09-28; offline analysis of retained ESP32-S3 stock **1.1.1040** and public
HCS026, HTV145 and HTV405 RF fixtures. No devices, RF, cloud requests or runtime
code were changed. Status remains in the [roadmap](../PROJECT_ROADMAP.md).

## What this adds

The longer valve transcripts consist of ordinary report/configuration reads,
repeated per port, rather than an established universal “18-step enrollment”
algorithm. The stock handlers share dispatch and serialization, but obtain
different model-specific configuration arrays. This supports sharing structural
decoders while keeping qualified model payloads and proven pairing prefixes
separate.

An important terminology correction: **native `20`'s first data byte is an
update-version value from `subdev_ver`, not the device's RF channel**. This
also narrows interpretation of the captured delayed configuration `02 00`:
it fits version 2, update kind 0. That interpretation is distinct from the
startup kind 1 and channel-change kind 4 paths.

## Shared dispatch, without a universal stage counter

`42051788` dispatches on the low seven command bits. Native offsets use the
[qualified byte conversion](STOCK_HUB_RADIO_PATH_TRACE.md), not normalized
capture offsets. Source anchors below are application virtual addresses.

| Native command | Handler | Established role |
| --- | --- | --- |
| `01` | `420473A8` | Connection/assignment, with distinct known-sender and new-device branches. |
| `02` | `4204D658` | Controller report: consumes flags, port and state; can establish a pending association record and returns requested metadata. |
| `03` / `0A` | `42050690` | Device report/reply handling; captured HCS026 moisture uses `03`. |
| `05` | `42044724` | Read controller configuration for a port. |
| `06` | `4203D480` | Read a page of plan configuration for a port. |
| `59` | `42028BA8` | Read parameter IDs through descriptors or the per-port fallback. |

These handlers are not evidence that every supported device must issue every
operation, in the same order or at the same phase. The captured HTV405 sequence
repeats reads across four ports; HTV145 has one. The preserved HCS026 first
enrollments use report/configuration operations, not the valve's entire tail.
The existing [terminal trace](STOCK_HUB_TERMINAL_PAIRING_TRACE.md) already shows
the same `59` request at different full phases across HTV145 profiles.

## Command `05`: same envelope, different configuration arrays

Handler `42044724` requires declared body length **2**, extracts the transport
selector from native `P[12]` and port from `P[13]`, and retrieves the association
record. Its class predicate resolves through literal `42040B28` to
`4212B5D0`: classes `1F`, `20`, `21`, `25`, `26`; class **`48`** is explicitly
accepted as an additional case.

Here “transport selector” describes the first request byte passed to the
response transport builder `42037ECC`, not the association address (the
handler's separate argument) or the slot-3 configuration version. This handler
does not read slot 3. That separation is directly visible even without assuming
a wider interpretation of the selector's radio-channel mapping.

For the ordinary controller branch, the requested port is checked against
record `+28`. Soil class `48` has a separate exception to that upper-bound
check. This is not a reason to reproduce weak validation locally: our supported
soil profile still uses its qualified port, and malformed requests must remain
rejected.

The successful serializer at `42044868..420448AC` selects:

```text
port record = *(device record +84) + (port - 1) * 36
configuration length = port record[0]
configuration bytes = *(port record +8)
reply body = status, configuration bytes
```

The handler copies the stored array unchanged; it does not synthesize one
universal valve/sensor payload. Invalid length/model/ordinary port produces
status 2, while a missing configuration object takes a separate no-reply/error
return. Those are stock-side decisions, not proof of device acceptance.

Public capture comparison:

| Device | Request data | Reply data |
| --- | --- | --- |
| HCS026 first enrollment A/B | `09 01` / `08 01` | `00 01` |
| HTV145 | `0C 01` | `00 58 02 0A 00 1E 00 00 00 00 00 00 00 00 00` |
| HTV405 ports 1–4 | `0C <port>` | Same captured status plus 14 configuration bytes as above |

The soil reply therefore contains **one configuration byte**, while these
valve replies contain **fourteen**. Their equal valve values are captured
settings, not immutable defaults for every installation. This pass does not
assign unverified watering/threshold meanings to individual configuration bytes.

### Where those arrays come from

The class-47/48 soil adapter registers parser `420370D0`. It parses the supplied
configuration string and builds a single 36-byte port record, concatenating
decoded hexadecimal segments into its `+8` array and accumulating length at
`+0`. This is distinct from the water-controller parser `42058AC0`, registered
for the valve class family.

The water parser selects a descriptor-based path when recognized, otherwise
uses legacy parser `42043928` or slash-delimited parser `42042F64`. Those legacy
paths allocate one 36-byte record per port and retain separate controller,
plan and extra-parameter data. Thus configuration can depend on loaded settings
as well as model metadata; the firmware image alone does not supply every
device's current configuration.

## Command `06`: a paged plan read, including an empty response

`4203D480` requires body length **3**: transport selector, port, page selector.
It validates the port and uses the same 36-byte per-port structure. A nonzero
plan-length field at port `+1` enters splitter `4203C1F0`; zero skips it and
leaves the ordinary status-only response. This matches the captured valve
`0C <port> 00` -> `00` exchanges without requiring an additional magic token.

The splitter interprets the last request byte as a **page selector**. Depending
on stored plan flags/record sizes, it selects one or several entries, finds each
entry using its leading length byte (`4203C190`), and copies data without that
storage length prefix. Its more-data flag makes the outer reply status **1**;
the completed/empty captured reply uses **0**. An error status 2 is separate.
Exact plan-entry application semantics and supported maximum paging limits
remain unqualified.

This reinforces the existing bounded retry repair: if a valve repeats the same
plan read with a later full phase, replying to that semantic request is more
defensible than treating local TX success as proof it advanced. It does not
prove why the initial reply was missed or accepted, and does not authorize
loosening identity, CRC, body or timing checks.

## Delayed `20`: configuration version, not selector or command counter

Builder `4204ABA0` reads configuration slot **3**, the 40-byte `subdev_ver`
table (`4204ABF0..4204ABF7`). `4204AC10..4204AC2E` selects entry `address - 1`, writes it as the first
data byte, then writes the update kind. Its diagnostic explicitly identifies
these as `update_ver` and `code` (`4204AC69..4204AC7B`). Kind 3 or 4 can append one value byte; other
kinds have the two-byte body.

This meaning is independently supported by update handler `4204D27C`, which
parses/stores new device parameters, updates the corresponding slot-3 version,
and conditionally calls this notifier. `4204AD80` also increments that version
after a local configuration edit before sending kind 0. The slot-3 value is
therefore configuration-version metadata; it is neither the RF selector at
device record `+27`, the six-bit RF phase, nor proven to be the product's
firmware version.

The stock HTV145 delayed `20` body `02 00` and reply `A0` body `00` are
consistent with version 2, kind 0 and a successful response. The builder and
captured bytes agree structurally. **The exact initiating callback and origin
of that particular capture's approximately three-second delay remain unproven.**
It could include configuration acquisition/processing; do not declare that
delay a universal radio-protocol constant or change the already-proven local
timing based only on this static path.

## Controller report `02` is more than an enrollment checkpoint

`4204D658` reads transport selector, flags and port, then parses state for that
port. If the sender belongs to the temporary connection list, it consumes that
record, initializes the device/model state and persists the association. For
ordinary known records it processes a report without that allocation path.

Its reply is conditional: flags bit 1 requests the slot-3 configuration-version
byte; bit 2 requests five time-related bytes; bit 7 requests two unit-related
bytes. Bits 3–4 supply a battery category on this report family. Consequently a
short `00 01` response is compatible with status zero and version one, not a
universal stage-completion code. In the HTV405 fixture, the fourth port's `02`
reply is `00 02` while the preceding three are `00 01`, consistent with the
version advancing during configuration rather than a fixed success suffix.
The precise triggering update is not identified in that recording. Other
contexts and flags produce other lengths.
Do not infer that sensor reports use the same flags or battery offset.

## Diagnostic output is not a prepared-reply cache

The ordinary request dispatcher's call to `4201F650` with a `tmp_buf` label
does **not** establish a retained response cache. The complete bounded helper
formats the provided bytes into a local diagnostic string. Independently
checked S3 instructions allocate/initialize stack storage at
`4201F650..4201F67B`; the terminal path takes that stack buffer at
`4201F6F0..4201F6F3`, calls logging helper `4202DB4C` at `4201F705`, and returns
at `4201F708`. The helper has no packet-queue or response-cache write.

This corrects the earlier “prepared-packet store” interpretation of that call.
It does not prove the entire receive stack lacks duplicate handling; lower
layers and device-side duplicate policy remain separate questions. Actual
reply queuing must be traced through the dispatcher's queue calls, not this
diagnostic label.

## Practical boundaries

The next physical trial should retain the proven prefix and exercise the
already-implemented bounded plan retries. No new transmitter is justified by
this pass. A model-aware transcript should record native command, phase,
port, page/parameter ID and received reply independently from logical progress.
Completed enrollment, accepted control and long-term reporting remain separate
evidence gates.

Sources are the public
[soil enrollment](fixtures/hcs026_gateway_pairing_replies.json),
[single-zone enrollment](fixtures/htv145_counter2_stock_enrollment_20260901.json)
and [four-zone enrollment](fixtures/htv405_gateway_pairing_replies.json) fixtures,
plus the retained validated application. Private derived exports are in
`analysis/ghidra-20260927/pairing-configuration-1/` and `-2/`; the existing
`config-callers/`, `paths-1/`, `paths-2/` and model-adapter exports are reused.
`verify_pairing_configuration.py` checks three function literals and ten
bounded S3 disassembly regions. Binary/C outputs remain ignored and restricted
to owner access; no vendor implementation or private configuration is published.
