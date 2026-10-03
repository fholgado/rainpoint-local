# Stock configuration versions and valve configuration fields

2026-09-28. Offline evidence from the retained ESP32-S3 hub application
**1.1.1040**, checked against the public HCS026/HTV145/HTV405 captures. This is
hub behavior, not a decompilation of the sensors or valves. No live requests,
RF transmissions or runtime changes were made. Status belongs in the
[roadmap](../PROJECT_ROADMAP.md).

## Findings that change our interpretation

- The version returned during enrollment and native `20` notification is a
  **configuration revision**, separate from RF phase/counter and RF selector.
- Configuration acquisition is asynchronous: the hub requests parameters,
  installs a matching response, then conditionally notifies the device. A
  delayed `20 02 00` therefore need not be a fixed timed pairing stage.
- The captured fourteen-byte valve configuration has a recoverable field
  layout. Several names are corroborated only by diagnostics; their units
  must remain unqualified.
- Completion of the parameter download, acceptance of a notification, and
  successful valve control are different observations.

## Revision lifecycle

Slot 3 is the forty-byte `subdev_ver` table, indexed by association address
minus one. It is persisted through the configuration API, not derived from
the six-bit packet phase. The following are concrete writers/readers, not an
exhaustive claim about every model or reset mode.

| Event | Observed behavior | Primary anchor |
| --- | --- | --- |
| New pending controller association becomes established | Sets that address's revision to **1** when the enrollment context has no existing-device reference. The existing-device branch loads its record instead. | `4204D658`, instructions `4204D786..4204D7D5` |
| Soil report establishes a pending association | Corresponding new-association branch also initializes revision 1. | `42050690`; compare the shared RF add path `4203F37C` |
| Platform device-list reconstruction | Writes revision 1 for reconstructed entries, independently of a radio packet counter. | `4200E8A8` |
| Matching parameter response accepted | Stores the supplied revision if different; it does **not** blindly increment it. | `4204D27C`, `4204D53D..4204D56D` |
| Controller rain-delay setting changes locally | Stores the four-byte setting, increments that address's revision by one, then sends notification kind 0. | `4204AD80`, `4204ADE1..4204AE2E` |
| Platform reconciliation removes an entry | Clears its revision and removes associated state in a separate reconciliation path. | `4200D7E4`, `420510C4` |

The local increment is an eight-bit load/add/store (`4204AE12..4204AE17`),
so this path truncates on overflow. That is an implementation observation,
not a recommendation to cycle revisions through zero: other paths treat
zero as absent/unconfigured. No overnight revision reset is established by
this trace. These findings do not explain or redefine valve control-counter
resets.

### Connection replies and report replies are different

In the successful native `01` connection reply path, `420473A8` appends
configuration version 1 for a newly assigned sender, or the retained slot-3
value for an existing sender (`420478F3..42047935`). This is not the native
`02` report's flag-conditional layout.

For native `02`, flags are the request's second data byte. **Bit 1 means mask
`0x02`, not mask `0x01`.** At `4204DBB4..4204DBD2`, that bit controls appending
the configuration revision after reply status. Bit 2 separately requests
time data; bit 7 requests unit data. Thus `00 01` and `00 02` can be status
zero with revisions one and two, not different enrollment success codes.
The version byte is not a control-counter acknowledgment. No configuration
meaning for report flags bit 0 is established here.

## Acquisition, pending state and completion

The direct dataflow is:

```text
platform revision list → requested address/revision pairs
→ parameter fetch task → response parsing/model parser
→ store configuration + revision → conditional native20 notification
```

`4200D7E4` compares incoming platform revisions with slot 3. Existing entries
needing parameters feed `420452C8`, which retains address and expected-version
lists. `42039DF8` builds an HTTP-task message and sets its update state to 2
before queueing it (`42039F8E..42039FA8`). This is a **parameter-acquisition
state**, not radio enrollment stage 2.

The shared update object contains list pointers at `+0/+4`, state at `+8`,
retry bookkeeping at `+9`, an error/retry flag at `+10`, and a refresh flag at
`+11`. Failures can return it to state 1 for retry. This is not a claim that
these numeric states are suitable for a public API.

`42011998` parses the returned list, passing address, revision and parameter
string to `4204D27C`. That consumer requires an active update, address in the
pending list (`420407AC`), and matching requested revision (`4204085C`) before
model-specific parsing and storage. The latter sets the refresh flag on a
revision mismatch. These guards argue against installing an arbitrary stale
cloud response solely because its RF address matches.

`42045450` then reconciles the response address/version lists with outstanding
requests, compacts remaining entries and retries them. When none remain it
frees both lists and clears bytes `+8..+11` (`4204575C..420457B1`). Its list
completion is based on returned metadata; the outer parser does not gate list
insertion on the return value of every per-device parse. Therefore even this
hub-side completion must not be equated with proof that a valve received or
applied the new configuration.

## Where native `20` kind 0 comes from

Builder `4204ABA0` sends `{configuration_revision, update_kind[, value]}`.
The two concrete kind-0 origins are:

1. **Parameter installation:** `4204D27C` stores the supplied revision, then
   sends a notifier only when the record's six-byte secondary identifier at
   `+40` is absent (predicate `4212AFE4` returns zero), with nonempty
   parameters, a supported RF class, and either device-change metadata or a
   changed revision. Device-change value 1 selects kind 2. Otherwise record
   byte `+57` zero selects kind 1; nonzero selects kind 0
   (`4204D5A8..4204D5E9`). The exact boolean predicate is established; byte
   `+57` is receive-wrapper metadata, **not** independently proved to mean
   “configuration successfully applied.”
2. **Rain-delay edit:** `4204AE58` detects a changed per-port delay and calls
   `4204AD80`. That function updates bytes 8–11, increments slot 3 and sends
   kind 0 directly (`4204AE23..4204AE2E`).

Other direct callers preserve separate purposes: `4204BBC0` selects kind 4
for its channel-change case, kind 1 for startup case, and kind 0 for other
nonzero input; `4204AD38` sends kind 3 with value 3 to class `24`; the
class-24 configuration parser `4204B454` sends kinds 1/2/3 according to its
changed fields. The alternate builder `4204B874` accepts an explicit kind
and optional payload. These are not all valve enrollment operations.

For the captured HTV145 delayed body `02 00`, parameter arrival after a new
association is a concrete supported explanation: revision 1 was initially
advertised, a supplied revision 2 is installed, and the eligible kind-0 path
can notify it. **The recording alone does not identify the initiating cloud
response or prove this exact branch ran.** No fixed three-second timer is
established for the notification; replay timing and prefix should not be
changed on this inference alone. `A0` status zero is evidence of a radio reply,
not completion of every downstream configuration read.

## Fourteen-byte valve configuration layout

The native `05` reply is status followed by a per-port configuration array.
For class `1F` (captured HTV145/HTV405), `42040510` checks a fourteen-byte
layout. Instructions `420405CC..42040631` read fields and pass them in order
to a diagnostic format at literal `42004560`. Offsets below exclude reply
status; little-endian widths are established by the instruction loads.

| Array bytes | Shape | Stock label / evidence | Captured value |
| --- | --- | --- | --- |
| 0–1 | unsigned LE16 | Default work time; diagnostic label, units unproved here | 600 |
| 2–3 | unsigned LE16 | Mist open; diagnostic label, units unproved | 10 |
| 4–5 | unsigned LE16 | Interval; diagnostic label, units unproved | 30 |
| 6 | unsigned byte | Associated soil address; returned by `42040510`, used by `42040684` to maintain the soil/controller association | 0 |
| 7 bits 0–6 | unsigned seven-bit value | Humidity threshold; diagnostic label, scale unproved | 0 |
| 7 bit 7 | one-bit flag | `rainday`; do not yet rename as a specific app setting | 0 |
| 8–11 | unsigned LE32 | Delay; `4204AD80`/`4204AE58` functionally update it through the rain-delay path; units unproved | 0 |
| 12 | unsigned byte | `cali`; no calibrated units or mathematical effect established | 0 |
| 13 | unsigned byte | `press`; no pressure units or enum meaning established | 0 |

The captured array is `58 02 0A 00 1E 00 00 00 00 00 00 00 00 00` in both
valve fixtures. These values are settings from those captures, not universal
defaults. In particular **600 is not proof of either the command duration
encoding or the valve's currently remaining watering time**.

Legacy parser `42043928` decodes the first per-port hexadecimal segment into
this stored array; `42042F64` and descriptor parser `42024384` supply alternate
configuration input paths. The image therefore explains serialization, but
the exact selected settings/revision can depend on a parameter response not
present in an RF-only recording. No private cloud configuration was read to
fill that gap.

## Consequences for the local implementation

An offline analyzer can expose these raw fields with explicit unqualified-unit
labels, and track configuration revision independently from association,
RF selector and command phase. Synthetic regression inputs can verify those
separations without device access. A future configuration writer needs its own
versioning/application contract; a successful packet reply alone is inadequate.

For the next short physical trial, the existing pairing prefix should stay
frozen. Correlate report flags, advertised revision, configuration reads and
notification response; only a captured parameter event or controlled one-field
setting change can settle the remaining value/trigger ambiguity. No broad
re-pairing or live cloud dependency is justified by this note.

### Evidence locations

Public comparisons: [pairing configuration trace](STOCK_HUB_PAIRING_CONFIGURATION_TRACE.md),
[HTV145 fixture](fixtures/htv145_counter2_stock_enrollment_20260901.json),
[HTV405 fixture](fixtures/htv405_gateway_pairing_replies.json), and
[soil fixture](fixtures/hcs026_gateway_pairing_replies.json).

Private derived evidence remains owner-only and Git-ignored under the retained
bundle's `analysis/ghidra-20260927/configuration-lifecycle-1/` through `-4/`,
plus reused `config-callers/` exports. `configuration_lifecycle_evidence.py`
checks four explicitly selected code-format constants and ten aligned S3
instruction regions in `configuration-lifecycle-verification/`. Function
labels are hints; field widths, writes, conditions and callers were checked
against the instruction/dataflow evidence. No vendor source or private
identifiers are published here.
