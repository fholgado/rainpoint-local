# Stock terminal pairing: a parameter read, not a new enrollment opcode

Research date: 2026-09-27. Sources: private stock hub **1.1.1040** offline
ESP32-S3 code and retained public RF fixtures. No radio, hub, cloud request,
deployment or runtime change was used for the original analysis. The approved
source follow-up is described below. Status belongs to the
[roadmap](../PROJECT_ROADMAP.md); physical qualification follows the
[improvement plan](STOCK_FIRMWARE_IMPROVEMENT_PLAN.md).

## Result

**Follow-up, Sep 27:** the [retained HTV145 descriptor](STOCK_HUB_POSTBOOT_TRACE.md)
now qualifies the empty per-port-array branch for fresh initialization with
that model table. A separately approved source repair answers bounded repeated
plan requests without changing the proven prefix; see below. Neither result
establishes full physical enrollment or the original RF failure cause.

The HTV145 request previously called terminal `2c/99` is native command
**`0x59`: read device parameters**. Its captured data is parameter ID `0x32`;
the stock reply is command `0xD9`, data `00 32 00`. HTV405 uses the same command
family but requests four IDs with different returned data. Shared command
dispatch does not establish shared parameter semantics across models.

Most importantly, three failed local trials did **not** reach that request.
They repeated native **`0x06`: read plan parameters**, despite one transmitted
`0x86` response. Therefore changing the terminal `0xD9` serializer alone would
not address the observed point of failure. Why the valve did not accept the
preceding reply remains unproven; the gateway image cannot tell us the valve's
receive conditions.

Evidence labels: **Static** means qualified bounded code/constant; **Capture**
means retained RF evidence; **Corroborated** means agreement between both;
**Inference** remains a hypothesis. The
[valve-state trace](STOCK_HUB_VALVE_STATE_TRACE.md) defines the native payload
conversion and six-bit phase. Offsets below use that native payload `P`.

## Dispatch and response construction

**Static.** Dispatcher `0x42051788` extracts command low seven bits and passes
the payload at `P+12` plus its declared length. Comparison at `0x420518EB`
selects decimal 89 (`0x59`) and jumps to `0x42051AEA`; its call at
`0x42051AF0` enters **`0x42028BA8`**. The directly referenced diagnostic names
this function `bd_dp_protocal_rd_dev_param` (`0x3C14E530`).

The handler calls **`0x42025400`**, named
`_bd_dp_protocal_combin_dev_param` (`0x3C14E78C`), at `0x42028C1D`. Relevant
behavior:

- A one-byte request containing zero selects the read-all path
  (`0x42025467..0x42025489`, diagnostic `rd all param`). Nonzero bytes select
  individual parameter IDs.
- Values come from the selected device's parameter table at context `+124`;
  descriptors come from context `+120`. Lookups at `0x42025561` and
  `0x4202559B` call `0x4212B180` and `0x4212B210` respectively. Those helpers
  compare the requested wire ID with each record's field at `+12`.
- Each output item begins with the requested ID (`0x420255DF`). The serializer
  uses descriptor type at `+32`; types 8/9 add a length byte
  (`0x420255E2..0x42025608`). Other types use their size mapping. Actual values
  are copied or generated according to the descriptor's semantic code.
- When combination returns nonzero, the wrapper adds one to the byte count
  and prefixes status `0`; if it returns zero, status is `2` and reply length
  becomes one (`0x42028C20..0x42028C3D`, `0x42028C8C..0x42028CA6`). These are
  handler results, not proof that a valve received the response.
- The transport wrapper `0x42052854` copies that data into its reply buffer.
  The outer receive path calls the common reply-header builder `0x4203A4FC`
  at `0x42051CEA`, preserving all six sequence bits and setting command bit 7.

This is a general parameter-read operation. No HTV145-only product gate or
pairing-window requirement was found within this bounded handler. Earlier
identity/context validation still applies; this is not an assertion that
arbitrary unpaired devices receive parameter responses.

## Captured payloads: common operation, model-specific data

**Capture.** These independently retained exchanges agree with that structure:

| Capture | Phase(s) | Request data | Reply data |
| --- | --- | --- | --- |
| HTV145, stock Sep 1, counter-2 branch | 8 | `32` | `00 32 00` |
| HTV145, stock Sep 5, selector-2 branch | 5 | `32` | `00 32 00` |
| HTV405, stock Aug 17 fixture | 15–18 | `32`, `33`, `34`, `35` | `00 <ID> 0c`, then twelve `64` bytes |

All requests are native `0x59` and replies `0xD9`; every reply echoes the full
request phase. The differing HTV145 phases disprove treating the terminal
operation as requiring a universal stage-counter value.

Sources: [HTV145 Sep 1](fixtures/htv145_counter2_stock_enrollment_20260901.json),
[HTV145 Sep 5](fixtures/htv145_selector2_stock_pairing_control_20260905.json),
[HTV405 stock exchanges](fixtures/htv405_gateway_pairing_replies.json).

The HTV405 bytes fit a length-prefixed, 12-byte parameter value. **Do not assign
a watering, battery, monthly schedule or percentage meaning solely from the
twelve repeated 100 values.** Likewise the final zero in the HTV145 reply could
be a scalar value or a zero-length value; the captured bytes alone do not
identify its descriptor type. Do not hard-code one model's response for another.

### Per-port fallback: a stronger length interpretation

**Static, expanded decompilation.** The same combiner has a second serializer
when the ordinary lookup misses and device context `+124` is zero:

1. Require requested ID at least `0x32`; calculate `index = ID - 0x32`.
2. Require index below port count at context `+28`.
3. Select the port structure at `*(context + 84) + index * 36`.
4. Emit the requested ID, the length byte at port-structure `+16`, and that
   many bytes from the pointer at `+20`. Zero length emits no value bytes.

The gates are at `0x420256C9..0x42025717`; serialization is at
`0x42025718..0x42025758`. These branch targets were independently decoded with
the S3 toolchain; starting linear decoding in intervening padding is misleading.
The outer wrapper still prefixes status zero.

**Conditional capture interpretation:** on this branch, IDs `32`–`35` are ports
0–3, HTV145 `00 32 00` means an empty byte array, and HTV405 `00 <ID> 0c` plus
twelve bytes means a 12-byte per-port array. This fits both captured families
without inventing a new enrollment opcode. However, the actual runtime context
that selects fallback versus descriptor serialization has not been established
for these captures. The zeros and lengths are therefore not yet universally
qualified model definitions; the data's application meaning also remains open.

The separate semantic-code-9 completion branch below belongs to descriptor
handling. Do not combine it with this fallback to claim that `32` necessarily
marks enrollment complete. Private expanded evidence is indexed in
[decompilation](STOCK_HUB_DECOMPILATION.md#expanded-protocol-pass).

## A real “last parameter” branch, with a mapping still missing

**Static.** The generic combiner has special handling for semantic code **9**
(`0x42025659..0x42025698`). It obtains a 40-byte configuration array by calling
`0x4201DF80(2, 3, buffer)` and selects the byte at device address minus one.
The static configuration table at `0x3FC9F018`, entry ID 3, names that array
**`subdev_ver`** and specifies size 40. `0x4201C344` resolves the descriptor;
the read branch of `0x4201DF80` copies the configured data to the caller.
This establishes a per-device version-like value, not its user-facing meaning.

That special branch sets an out-flag. The wrapper then clears bit 2 of context
byte `+115` and emits **`last param req`** at `0x42028C5C..0x42028C7F`, before
the common context-save call at `0x42028C89`. It is a real local completion
transition, not a guess based only on the terminal request's position.

**Unresolved mapping:** the per-device runtime descriptor linking wire ID
`0x32` to a semantic code was not recovered. Thus we cannot claim this particular
HTV145 request executes the semantic-code-9 branch. Nor is `subdev_ver` proven
to be valve firmware version, an RF command counter or a battery-rejoin token.
The same wire ID has different captured data in HTV405, reinforcing the need
for model-specific descriptor evidence. No private configuration values were
read or published for this analysis.

## Where the failed local path actually stops

**Static.** Native command `0x06` dispatches to `0x4203D480`, named
`_bd_sdev_comm_read_plan_param` (`0x3C1563A4`). It requires declared data length
3, extracts port at `P[13]`, validates that port against device context, and
reads the plan selector at `P[14]`. Its response can include a status plus
plan data. This is distinct from generic `0x59` device-parameter reads.

**Capture.** Three local trials—
[low gain](fixtures/htv145_low_gain_terminal_retry_20260905.json),
[calibrated tail](fixtures/htv145_calibrated_tail_terminal_retry_20260905.json),
and [receive-edge timing](fixtures/htv145_receive_edge_terminal_retry_20260905.json)—
all contain the following native evidence:

- Valve `0x06` request body `0c 01 00`: port 1, plan selector 0; the first
  data byte is retained as observed without assigning a new semantic label.
- Request phases **7, 8, 9, 10, 11**, same body each time.
- One captured gateway `0x86`, phase 7, status-only data `00`.
- No captured native `0x59` request or terminal exchange.

The phase advances show that these valve-originated retries are not exact
on-air packet repeats. This does not contradict the stock **gateway's**
byte-preserving timeout resend described in the valve-state trace: different
senders and retry paths must not be conflated.

The fixture's independently measured waveform and byte equality remain useful,
but they do not prove receiver acceptance. The narrow failure boundary is
**acceptance of the `0x86` plan-parameter reply / progression to `0x59`**, not
construction of an already-requested terminal reply. We have no proof that an
extra unconditional terminal response, a counter reset, or replaying the
HTV405 tail would solve it.

### Why the pre-repair responder could not recover that exchange

**Historical source-code finding.** The pre-repair
[`requestMatches`](../firmware/rainpoint_bridge/include/rainpoint_htv145_pairing.h)
compares every normalized body byte `13..35` for non-factory steps, including
both parts of the six-bit phase. `PairingSession::claimReply` checks only the
current step. `finishReply` increments the step after a locally successful TX;
it does not wait for evidence that the valve accepted that reply.

Consequently, after sending the phase-7 `0x86` response, the session expects the
terminal request and cannot answer the captured repeated `0x06` requests. Even
an exact repeat of the previous step is no longer eligible; the observed
changed-phase retries also fail the byte-exact matcher. The Python reference
[`request_matches`](../rainpointd_addon/rainpointd/valve_pairing_protocol.py)
likewise includes the captured phase in ordinary body matching.

This is a concrete **retry/recovery gap**, consistent with all three traces.
It is not proof of the initial RF/receiver failure and not proof that answering
the later requests will complete pairing. The known-good first response must
remain preserved while that narrower recovery behavior is independently tested.

## Evidence-led continuation

The approved source implementation now permits four plan-request replies within
ten seconds of the initial plan reply while awaiting the terminal request.
Only phase varies: CRC, route, command, port, length, body and padding checks
remain. Phases must repeat or advance monotonically within four positions of
the original. Responses echo the full phase, retain the same payload/trailer
policy and do not advance logical enrollment. After a retry, terminal must use
the next phase. Session expiry, reply deadlines and receive-edge timing remain
enforced. First replies are byte-identical in native regression tests.

These are bounded implementation choices, not discovered universal device
limits. Native tests also reject malformed inputs, stale terminal packets,
backward phases and retries outside the count/time limits. Retry counts reach
the authenticated gateway status path. See
[implementation/validation](STOCK_FIRMWARE_IMPROVEMENT_PLAN.md#follow-up-source-repairs-and-evidence-sep-27).
This code is not deployed and does not yet establish 6/6 completion.

The following describes the rationale that led to this implementation:

Before another physical iteration, annotate existing transcripts with native
command, full phase, declared length, port and parameter ID. Preserve the
accepted prefix. A reviewable recovery design can retain the last answered
semantic request, recognize valid-CRC repetitions from its authorized association, and
echo each observed full phase in the response while awaiting the next request.
It must retain identity, model, port, body-length, timing, ownership and session
expiry checks; merely ignoring arbitrary bytes in the old matcher is not enough.
Unchanged first-response bytes and bounded retries are now qualified offline;
one explicitly approved physical test is next. Source approval does not
authorize production deployment or transmitting new packets.

Recovering the model-specific parameter descriptor would distinguish a scalar
zero, empty value and completion/version parameter. If it remains unavailable,
a controlled stock capture that changes a known relevant setting is more
informative than another arbitrary RF timing change. The resulting behavior
must still be checked on the valve; this gateway dump cannot establish the
valve's receive state machine.

## Reproduction

Three hardware-free tests in
[`tests/test_stock_terminal_pairing_reference.py`](../tests/test_stock_terminal_pairing_reference.py)
pass against two HTV145 stock profiles, four HTV405 parameter reads and three
failed local trials. They assert independently captured bodies and phase
progression, not a serializer round trip or invented acceptance result.

```sh
python3 -m unittest tests.test_stock_terminal_pairing_reference -v
```

Fifteen bounded disassembly listings, tool/input-hash manifest and helper are
private and Git-ignored under
`captures/stock-hub-firmware/2026-09-27-adzoj0e3/analysis/terminal-pairing-20260927/`
(directory 700, files 600). Branch targets were decoded separately where
padding disrupts linear decoding; see [tooling](STOCK_HUB_DECODER_TOOLING.md).
