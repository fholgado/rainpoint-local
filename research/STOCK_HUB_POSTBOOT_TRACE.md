# Stock post-boot state and retained model descriptors

2026-09-27; offline analysis of retained stock ESP32-S3 **1.1.1040** and its
matching flash snapshot. No device, RF, cloud, deployment or runtime-code changes.
Status belongs in [the roadmap](../PROJECT_ROADMAP.md).

## Conclusions

- Boot clears the shared sequence byte, but **the first watering sequence is
  not established**. Startup notification traffic consumes the same generator,
  and normal initialization has a cloud-connection gate before that notification.
- The retained **HTV145 model-302 descriptor has no category-0 parameters**.
  Its ordinary parameter collection therefore stays null on the traced fresh
  initialization path, selecting the legacy per-port fallback for terminal
  request `32`. Under that retained configuration, `00 32 00` represents a
  zero-length per-port array, not the descriptor-based version/completion field.
- No active HCS026/HTV405 model descriptor was found in this snapshot. Their
  field mappings cannot be inferred from HTV145's table.

These findings narrow implementation hypotheses; they do not demonstrate a
newly accepted RF transaction or explain the historical overnight failures.

## Startup order and counter boundaries

The [qualified boot clear](STOCK_HUB_BOOT_STATE_REFERENCE.md) contains sequence
byte `3FCA710F`. Expanded cross-references still identify only generator
`42037920` as a direct reader/writer of that exact address. This is not a
whole-program proof against indirect writes or restoration.

`app_main` (`42013564`) calls:

| Call address | Target | Bounded finding |
| --- | --- | --- |
| `42013582` | `4201EC14` | Base-information reporting; normal, non-factory path waits for the connection predicate below. |
| `42013585` | `420378D8` | Sets up the `sta_sync_task` path. |
| `42013588` | `4203FD6C` | Offline-check initialization and timer/event registration. |
| `42013599` | `4204BBC0(2)` | Startup parameter notification; eligible recipients go through the shared master-header builder. |

The wait in `4201EC14` calls `42022BE4` at `4201ECC5`, branches back while zero,
and invokes its delay helper with `2000` at `4201ECA8..AE`. Its diagnostic is
`wait_conneted_to_ali`. The predicate reads connection-state byte at
`3FCA6EFC + 8`; setter `42021438` updates that state under its mutex. This is a
cloud-connection condition, **not proof of RF readiness or sensor wakefulness**.
The factory-mode branch bypasses this wait.

The [existing channel trace](STOCK_HUB_CHANNEL_CHANGE_TRACE.md) establishes
that startup command `20`, kind `1`, uses `4203A344` and hence the same shared
sequence generator as valve controls. A sequence is consumed at header
construction, before queued transmission or device acceptance. A generated
header is not evidence that the valve saw it. Earlier initialization and
scheduled tasks prevent treating the startup notification as necessarily the
first consumer; no exact initial watering sequence is asserted.

There is still no qualified sequence save/restore path, elapsed-time reset
rule, or valve-side expected-counter mechanism. A reboot clears the byte at a
known stage; it does not justify resetting our per-valve state whenever a radio
reconnects or installing speculative startup transmissions.

## Descriptor source is retained data, not just compiled model dispatch

Device-record initializer `42023F84` reads the model code at record `+46` and
loads its descriptor into `+120` through `420234E0`. The latter caches by model;
on a miss, `42023414` reads configuration slot **14** and parses the blob.

Slot-14 handler `42023D5C` formats its storage key from the descriptor prefix
`dp` and `%s%u`: **`dp<model number>`**. Missing data is placed on a `modelCode`
request list by `42023BD8`; `420240D0` submits that list to `http_task`.
No HTTP request was issued during this research.

This distinction matters: the adapter registration for valve-class families
does not itself supply the parameter table. The initializer callback registered
by `42058EF4` resolves to `4212B7F8`, which simply returns 1. Searching only those
compiled callbacks would not recover the retained model-specific descriptors.

### Targeted extraction and provenance

Only active NVS entries whose key exactly matched `dp` plus a decimal model
number were inspected. Only model **302** was present: one 185-byte blob chunk
and its matching one-chunk index. Entry CRCs, payload CRC, namespace, chunk
start/count and total length agree. No other NVS values, device identifiers,
credentials or user configuration were exported.

Model 302 is independently documented as HTV145FRF by the previously retained
[product catalog reference](cloud/README.md#product-catalog-metadata). The blob
SHA-256 is `dce4738bab45a289d8c2dd745870ca52183d6c7041bd20dd6c189c0e4972a3e8`.
This is a snapshot of retained generic model metadata, not proof that an older
RF capture used the identical table.

The compiled protobuf descriptor reached by wrapper `4205DED4` is at
`3C15987C`; its nested `BDDevDpInfoItem` schema is at `3C159BB4`. The relevant
field mapping is:

| Protobuf field | Name | Decoded structure offset |
| --- | --- | --- |
| 1 | `dp_id` | `+12` |
| 2 | `dp_code` | `+16` |
| 3 | `dp_type` | `+20` |
| 4 | `dp_len` | `+24` |
| 5 | `dp_flag` | `+28` |
| 6 | `dp_data_type` | `+32` |
| 7 | `dp_port` | `+36` |
| 8 | `dp_val` | `+40` |

Parsing the complete 185-byte blob produces 12 rows, all `dp_type` **1 or 2**,
none 0. The compiled helper `4212B0B8` counts rows by the field at `+20`.
`42023628` calls it with category zero at `42023634..3D` and skips allocating
the parameter collection when the result is zero (`42023642`). Its caller
passes record `+124` as that collection's output (`42024005..0D`). These
offsets connect actual retained data to the previously ambiguous branch.

### Terminal request consequence and limits

For a fresh record initialized with this retained HTV145 table, the parameter
collection remains null. The [terminal combiner](STOCK_HUB_TERMINAL_PAIRING_TRACE.md#per-port-fallback-a-stronger-length-interpretation)
therefore falls back to `index = ID - 32`, subject to port count and the
ordinary identity/context checks. It serializes ID, byte-array length, then
value bytes. Thus the captured `00 32 00` fits status zero, port 0's ID, and
zero-length array. No data in this table establishes that ID `32` invokes the
separate semantic-code-9 “last parameter” transition.

This qualifies the branch for the retained model configuration, **not every
historical capture, future cloud metadata version, or possible pre-existing
runtime context**. The HTV405 12-byte arrays still lack an independently
recovered model descriptor. Array application meaning remains unresolved.
The repeated native-`06` failure boundary also remains earlier than this
terminal request; changing terminal serialization alone would not solve it.

## Reproduction and privacy

Private evidence remains under the ignored stock capture bundle's
`analysis/ghidra-20260927/`: `postboot-1/` through `postboot-8/`,
`postboot-verification/` and `model-descriptors/`. This pass exported 42 unique
functions successfully; one requested address (`42022B74`) was not a recognized
function and is retained as a failed navigation lead, not evidence.

`verify_postboot.py` re-reads selected literals from the original app and runs
the qualified S3 decoder on bounded startup/initialization regions. Branch
targets are decoded independently to avoid misreading alignment padding.
`extract_model_descriptors.py` and `qualify_model_descriptor.py` reproduce the
restricted NVS extraction and generic protobuf checks. Binary/C outputs are
private; no vendor implementation is copied into runtime source or this note.
