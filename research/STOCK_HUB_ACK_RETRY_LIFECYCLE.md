# Stock hub ACK, retry and rejection lifecycle

Date: 2026-09-27. Selected stock firmware 1.1.1040, ESP32-S3. Offline
decompilation, independently checked S3 instructions and local isolated tests;
no live hub, RF, cloud, firmware or irrigation changes. This is protocol
evidence, not a second work list; status lives in [the roadmap](../PROJECT_ROADMAP.md).

## Findings

- Ordinary outgoing transactions retain the complete packet and permit **four
  retransmissions** on a **700 ms periodic timer**. Neither retransmission
  constructs a new header nor allocates a new sequence.
- A reply must match gateway identity, device identity, command/ACK flag and
  **all six phase bits**. Matching removes the transaction **before** its result
  is interpreted. A matched rejection is terminal for that transaction; it is
  not a demonstrated counter-reset instruction.
- The inspected expiry path reports failure and frees the transaction. It does
  not establish a special resynchronization exchange or reset the global
  generator. No inference about the valve's internal acceptance state follows.
- There is one newly traced source of less-obvious global phase consumption:
  conditional RF result forwarding generates a fresh header and then replaces
  its phase with the originating request's phase. That consumes the generator
  without exposing that generated value in the forwarded packet.
- Incoming reports and outgoing-command ACKs use different paths. Do not apply
  the command-retry budget to sensor-report acknowledgements.

## Transaction and timer evidence

`0x4204A8E0` creates a 28-byte pending record. Relevant fields:

| Offset | Meaning from the accesses |
| --- | --- |
| 0 | Expected native command with bit 7 set |
| 1 | Expected six-bit phase supplied by the caller |
| 2 | Caller-supplied queue priority/ordering flag |
| 3 | Signed retry budget |
| 4 | Retained transport-packet length |
| 8 | Heap copy of the already constructed transport packet |
| 12 | Device identity |
| 16 | Originating operation/context pointer |
| 20, 24 | List links |

The getter `0x42045910` reads the factory-test flag at `0x3FCA712A`;
`0x4204A170` also uses that byte in explicitly named factory-test validation.
When it is zero, insertion writes retry budget 4. When nonzero, budget is 0.
This is not a newly discovered deployed-radio tuning option.

At `0x4204AB58..0x4204AB8D`, the insertion path chooses a timer period:

| Path | Period passed to timer | Effect if no other queue activity intervenes |
| --- | ---: | --- |
| Ordinary | 700,000 microseconds | Four retries, then expiry on the fifth callback |
| Factory-test flag nonzero | 2,000,000 microseconds | First callback expires, no retries |
| Continue after expiry, same next device | 700,000 microseconds | Restarts the shared queue timer |
| Continue to a different device | 1,500,000 microseconds | Restarts the shared queue timer |

Thus an isolated ordinary request has nominal sends at initial, 0.7, 1.4, 2.1
and 2.8 seconds and expiry around 3.5 seconds. These are **scheduler timings,
not measured on-air edges**. Task latency, queue changes and RF work can alter
actual times; do not publish 3.5 seconds as a universal device timeout.

The timer evidence needs assembly, not just decompiled call arguments:

- `0x42040B80 = 0x000AAE60` (700,000), `0x420412A0 = 0x001E8480`
  (2,000,000), and `0x42040B90 = 0x0016E360` (1,500,000).
- Call sites put the 64-bit interval in argument registers and callback
  `0x42038BAC` plus periodic flag 1 on the stack. Some older C exports silently
  omitted those arguments and showed only a misleading `10` argument. That 10
  is the copied timer argument length, **not a ten-second or ten-ms period**.
- `0x420AEABC` is the timer wrapper. Flag 1 takes `0x40377F04`, whose instruction
  shape matches `esp_timer_start_periodic`; the other branch reaches
  `0x40377E9C`, matching `esp_timer_start_once`. Both consume a microsecond
  interval. Their create/start/stop behavior and struct accesses were compared
  with the pinned [ESP-IDF 5.1.6 timer source](https://github.com/espressif/esp-idf/blob/v5.1.6/components/esp_timer/src/esp_timer.c).
- `0x42038BAC` posts main-task message `0x3D` rather than running RF directly
  from the timer callback. `0x420443F8` handles pending-list timeout work.

The timeout handler reads the **old** retry value, decrements it, then retries
only when the old signed value was at least one (`0x4204442C..0x4204443A`).
Four therefore means four additional sends, not four total attempts.

## Exact retransmission, queue policy and failure

At `0x42044552..0x420445F7`, timeout allocates a replacement retained copy,
marks transport metadata byte `+1` as a retransmission, copies the complete
transport record, hands the original to RF, and stores the replacement with
its embedded payload pointer repaired. This does **not** alter the native
protocol's phase or command data. Transport metadata offsets are not RF packet
offsets.

Insertion prioritizes native commands `0x21`, `0x74`, `0x75`, or a nonzero
caller ordering flag, and permits immediate sending for those selected command
families even when the named timer already exists. This is a shared queue, not
a separately timed, persistent per-valve transaction journal.

Only outgoing native `0x20` has a deduplication/coalescing branch here
(`0x4204AA32..0x4204AACC`): matching expected command, device, packet length and
body removes the old queued entry before inserting the new one. The compared
body excludes the 12-byte native header. **Do not generalize this into valve
OPEN deduplication:** native control `0x21` is not covered by that branch.

On exhausted budget, `0x4204443D..0x4204454E`:

1. Invokes control-result callback `0x42044170` with locally generated result 2
   for expected replies `0xA1`/`0xDC`, or the corresponding configuration-result
   callback for `0xA0`.
2. Runs device-specific cleanup `0x4203B0FC` and the separate `0xF4` context
   cleanup where applicable.
3. Unlinks/frees the retained packet and queue record; continues or stops the
   shared timer according to the remaining list.

That local timeout result is **not an RF rejection received from a valve**.
Similarly, `0x4203A684` reporting success only means its RF-task enqueue
succeeded. An enqueue failure and a missing RF acknowledgement are different
failure categories; neither proves the valve rejected a command.

`0x4203B0FC` passes record offset **40 decimal** to `0x4212AFE4` for
control-type devices. That helper only checks whether six bytes are nonzero;
its return value is discarded here. No write occurs. This is not a write to
the last-seen/offline deadline at offset **64 decimal**, and is not evidence of
a counter or offline reset.

## Reply correlation and result processing

The whole dispatcher is `0x42051BD0`; `0x42051DD3` is an interior branch, not an
independent complete function. ACK-bit-set native commands first call
`0x4204A550`, which requires:

1. Destination identity equals this hub's current identity.
2. Native reply command equals the pending expected command, including ACK bit.
3. All six phase bits equal the queued phase.
4. Source identity equals that pending device.

The matching entry is removed before dispatch to a command-specific handler.
`0xA1`/`0xDC` enter control handler `0x4204E320`; `0xA0` enters configuration
handling; `0xF4`/`0xF5` have their own handlers. A second identical ACK normally
has no pending entry and is not delivered as another control completion. This
does not rule out ambiguity after phase reuse/wrap with another matching live
transaction; no authenticated transaction generation is carried by the tuple.

The control handler interprets result and supplied state after correlation.
Its result translation helper `0x4203EC18` maps RF values 2/4 to platform 3,
6 to 4, `0x11` to 7, and `0x12` to 8; zero stays zero and other values pass
through with a diagnostic. Those numbers alone do not establish friendly
error meanings. Short replies/no context return through the operation-result
callback. Longer replies can parse state via `0x42046670` and update the device
record; receiving a matched ACK is not equivalent to a confirmed OPEN.

No counter-reset write or fresh corrective control transaction appears in
this matched-reply/timeout sequence. This is a **bounded negative finding**,
not proof that no recovery behavior exists elsewhere or inside the valve.

## A generator advance can be hidden by phase echoing

`0x42044170` handles results for more than the app's ordinary command path.
When its operation context starts with mode 3 and context byte 12 is nonzero,
it builds an RF result-forwarding packet:

- At `0x420443AA`, it calls the general header builder `0x4203A344` for native
  `0xB3`.
- That builder unconditionally calls generator `0x42037920` when the output
  buffer exists (`0x4203A435`).
- At `0x420443AD..0x420443BF`, the caller then replaces the generated six-bit
  phase with the originating context's phase.

This is a real conditional generation side effect, **not a reset**. It is not
established that normal cloud/app valve control enters this forwarding mode,
and it does not explain historical overnight failures by itself. It does
show why counting visible watering commands need not reconstruct every advance
of the shared hub generator. Do not infer a per-valve strict-next rule from it.

## Reports and repeated requests are a separate ACK path

For commands without the ACK bit, `0x42051BD0` validates the header, dispatches
the request through `0x42051788`, constructs a reply using `0x4203A4FC`, logs
the prepared packet through `0x4201F650` (`tmp_buf`), delays via
`0x420AE4CC(10)`, then enqueues RF. The response header echoes the incoming full
phase rather than allocating a new one.

No whole-request phase cache is visible in this dispatcher or the inspected
sensor-report handler `0x42050690`. That is not proof of no duplicate
suppression: lower RF delivery and device-specific consumers may affect repeats.
The [Sep 28 helper trace](STOCK_HUB_PAIRING_CONFIGURATION_TRACE.md#diagnostic-output-is-not-a-prepared-reply-cache)
corrects the earlier store interpretation: `4201F650` formats a stack-local
diagnostic and logs it; it does not retain a response cache.
The 700-ms outgoing retry timer is not the report
reply latency; the isolated delay call is not an end-to-end timing measurement.

The previously traced class-0x50 report-mode extension remains separate and
does not apply to our class-0x48 HCS026 soil sensors. See
[report-mode consumers](STOCK_HUB_REPORT_MODE_CONSUMERS.md).

## Consequences for our implementation and validation

The current local policies already retain identical full command frames:
HTV145 attempts at 0/730/1670 ms; HTV405 retries at 650/1450 ms following the
initial send and a 3-second response-listen window. Those bounded policies are
not stock-exact, but this research does not justify changing successful timings
or increasing watering attempts merely to copy the vendor. Preserve the
recent full-six-bit matching repair and explicit confirmed-state requirement.

Existing regression coverage exercises the useful invariants: wrong-phase
positive/negative responses leave the correct transaction pending, a duplicate
OPEN does not create another pending command, and duplicate completion does
not consume another counter or dispatch again. The two focused suites
`tests.test_stock_sequence_regressions` and
`tests.test_command_response_correlation` were rerun for this trace: **15 tests
passed**. They test
our implementation; they do not execute the stock firmware or prove valve-side
replay semantics.

Tomorrow's short canary plan need not grow: verify one dry command's correlated
state response and preserve its attempt/timeout trace. Do not deliberately
lose a live irrigation ACK or sweep new counters to reproduce the vendor's
queue behavior. Remaining uncertainty belongs in the roadmap, not additional
speculative device commands.

## Reproducibility

Private evidence remains Git-ignored beneath the selected firmware's
`analysis/ghidra-20260927/`: `paths-1` (insertion/timeout), `qualified-exports`
(matcher/header), `config-callers` (control/report consumers), and
`offline-recovery-2`/`offline-recovery-4` (timer, outcome, complete dispatcher).
S3-qualified objdump independently checked the numeric literals, full timer
calling convention, signed decrement, phase generation and subsequent overwrite.
Only selected application instructions/literals were inspected; no credentials
or device-specific records are reproduced here.
