# Stock report-mode consumers and heartbeat descriptors

2026-09-27, stock ESP32-S3 application **1.1.1040**, offline analysis only.
This extends [sensor recovery](STOCK_HUB_SENSOR_RECOVERY_TRACE.md); the
[roadmap](../PROJECT_ROADMAP.md) remains the sole status checklist. No firmware,
private configuration values, credentials or vendor pseudocode are published.

## Result

The app's `ControlReportMode` byte **does have a downstream device-reply path**.
For the runtime device class byte `50`, it is included in a reply to an incoming
report and is cleared when the stock cloud connection is absent. It is not an
unsolicited wake command, and the retail model corresponding to this class has
not been established. **The captured HCS026 class is `48`, excluded from this
reply-extension predicate and from the setter's class-`50` condition.**

The heartbeat property's descriptor is loaded from retained, model-specific
data. Static callback registration alone cannot resolve its wire identifier.

## Mode byte: setter to reply

Addresses are application virtual addresses, not flash offsets. Record offsets
refer to the 184-byte runtime device structure, not packet offsets.

| Step | Image evidence | Bounded interpretation |
| --- | --- | --- |
| App request | `4204463C`; previously traced from `ControlReportMode` | Successful setter requires record `+13 == 50`, stores interval byte at `*(record +84) +6`, and sends a server ACK. The setter itself is not an RF transmit. |
| Incoming dispatch | `42051788`, call `42051999` | Native commands `03` and `0A` enter report handler `42050690`. This is driven by an incoming device/relay report. |
| Class gate | `42050ECC..42050EDE`, helper `42037944` | A class predicate gates extra reply fields. Literal `42003A1C = 0001FC95` selects class bytes `49,4B,4D,50,53..59`; the mode-byte branch specifically tests `50`. These are not established retail model codes. |
| Local connection guard | `42050F0C..42050F19` | With a nonnull object pointer, helper `42022BE4` is called. A zero result clears object `+6` before reply serialization. |
| Reply values | `42050F4C..42050F51`, `42050F84..42050FB5` | Reads the four-byte value at object `+12`, then the byte at `+6`; appends the four value bytes in little-endian order followed by the mode byte. The preceding variable-length fields mean this is not one universal fixed packet offset. |
| Output boundary | `42051070..420510B1` | The handler rejects a zero incoming first data byte on this output path; otherwise copies its constructed body into the response buffer and wraps it with `42037ECC`. This is a prepared response in the established RF dispatch path, not proof that a device received or accepted it. |

The extension is inside the handler's **positive parse-result branch**. It is
not appended unconditionally to every report ACK, and preceding reply fields
also depend on incoming flags and relay context.

The redacted stock first-enrollment fixtures for both HCS026 test sensors have
native command `01` and bytes `FF 48 3D 01` at native offsets `13..16`: extended
class `48`, model `013D`. The stock connection handler loads this class at
`42047423..4204742C` and stores it to record `+13` at `420475ED` (record begins
at stack `+98`, store at `+A5`). Thus this exclusion is tied to the captured
sensor, not merely a guessed retail label. Sources:
[`hcs026_gateway_pairing_replies.json`](fixtures/hcs026_gateway_pairing_replies.json),
[`hcs026frf.md`](../protocol_documentation/hcs026frf.md), and the private bounded
assembly verification below.

The inspected branch also has a local state-change notification call to
`4203D474`. Its currently exported implementation is a no-op apart from a
record-base accessor; it does not establish another radio command.

`42022BE4` is identified by `bd_dev_model_get_connect_sta` and reads the
connection state at base `3FCA6EFC +8`. In `4201EC14`, a loop waits for this
predicate, sleeps 2,000 ms and logs `wait_conneted_to_ali` before packaging a
cloud base-information report. This supports a **cloud/device-model connection
gate**, not an RF receiver-ready or sensor-awake test. The setter `42021438`
updates the same state under its mutex. Exact interval units and the device's
interpretation of zero remain unverified.

A second mode reset is explicit: main-task message `1A` calls `4203ECE0`.
When its input begins with byte `1` and a nonzero address, that helper reads the
record and clears object `+6` for class `50`. The origin/meaning of this event
has not been established; it must not be labelled an app-exit event or a
timeout on that evidence alone.

**Consequence:** a stock app may request different reporting through a reply
when a suitable device next transmits. This path cannot make a completely
silent device transmit. Do not infer that the stock hub's loss of cloud service
explains our soil-sensor outages, or replicate this cloud dependency locally.

## Heartbeat descriptor mapping

The earlier helper `4203FFE4` uses defaults 8/60, configured overrides, and
semantic selector 31 through `4202421C`. The expanded trace establishes where
its table comes from:

1. `42023F84` initializes record `+120` using `420234E0` and the **16-bit model
   code at record `+46`**. This differs from the one-byte class at `+13`.
2. `420234E0` searches an in-memory cache by that model code. On a miss,
   `42023414` reads **configuration slot 14**, then parses the returned blob
   with `4205DED4` to create the descriptor table.
3. Missing descriptors are queued by `42023BD8` in a `modelCode` collection.
   This routine queues model data; it does not directly send a sensor command.
4. Descriptor lookup `4212B0E8` matches category at descriptor `+20`, semantic
   selector at `+16` and port/index at `+36` (zero defaults to one). It returns
   the descriptor byte at `+12`, which locates the corresponding stored field.
5. Property setter `42024D18` uses the same descriptor lookup before updating a
   stored compact value. Some callers supply selector 31 from BLE advertisement
   bits 4–5 (`4201A248`), a rain-gauge record byte (`4203142C`), or a leakage
   alarm's parsed value (`42058FC8`). These are corroborating value sources,
   not a model-qualified mapping for HCS026 or either valve.

Therefore **selector 31 must not be mechanically equated with every compact
wire type 31**, even though several observed paths are consistent with a small
status/battery-category value. The exact retained descriptor for each relevant
model is the missing mapping evidence. No slot-14 blob or private NVS value was
read during this pass. This also bounds the pairing-tail research: whether
record `+124` is populated depends on available descriptor categories, not
merely a hardcoded valve class.

The separate [post-boot pass](STOCK_HUB_POSTBOOT_TRACE.md) subsequently recovered
only the retained HTV145 descriptor and qualified its terminal fallback. No
active HCS026 descriptor was present, so this soil heartbeat mapping remains
unresolved.

## Verification and limits

Primary evidence is the retained, validated application and its private Ghidra
exports, described in [decompilation](STOCK_HUB_DECOMPILATION.md). Relative to
that ignored `analysis/ghidra-20260927/` directory:

- `config-callers/42050690.{c,asm}`, `4203ECE0` and `4204463C` establish the
  report handling/reset/setter paths (export filenames use lowercase hex).
- `postboot-2/`, `postboot-4/`, `postboot-5/` and `postboot-6/` retain the
  predicate, cloud gate, descriptor loader and setter exports.
- `report-consumers-verification/selected.asm` independently decodes selected
  branches with the qualified S3 objdump. Its manifest records the original
  app hash, class-mask, connection-base literals and two public sensor-class
  fixture checks. Decode starts are actual branch targets; linear decoding
  through padding was misleading. The retained `verify.py` reproduces them.

The seven existing sensor-frame and compact-field reference tests pass. These
check previously captured field grammar and reply correlation, not execution of
the vendor binary or acceptance of a new report-mode command.

This is static analysis, not a successful RF experiment or an exhaustive scan
of every reader. It warrants narrowing the recovery hypothesis and identifying
the correct model data before any new transmitter is implemented. Existing
authorized, owner-routed sensor ACK/rejoin remains the local recovery mechanism.
