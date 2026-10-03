# Pairing transcripts in native commands

2026-09-28. Offline comparison of existing public captures, with command names
qualified against saved stock firmware. No new RF, physical acceptance or
deployment is implied. Status remains in [the roadmap](../PROJECT_ROADMAP.md).

## Result

The three tested device families share an envelope, not one enrollment recipe.
Both valves repeat the same parameter/plan-read families; four-zone enrollment
expands them across ports. The single-zone failure captures stop on repeated
plan reads **before** the terminal parameter request. A sensor's captured stock
five-reply sequence and validated three-reply profile are distinct evidence,
not conflicting mandatory-stage counts.

The legacy capture is shifted one bit relative to the stock payload. The
[native boundary trace](STOCK_HUB_VALVE_STATE_TRACE.md#1-the-normalizedraw-boundary)
and [common specification](../protocol_documentation/common.md) define conversion.
Commands below are hexadecimal native values; lengths exclude the native header.
The ACK bit says response, not success or gateway origin.

## Device comparison

| Native exchange | HCS026 first enrollments | HTV145 stock enrollment | HTV405 stock enrollment |
| --- | --- | --- | --- |
| `01 → 81` | Request/reply data lengths 7/16 | Lengths 8/11 | Lengths 8/11 |
| `02 → 82` | Not present in selected sequences | One addressed 15-byte state/confirmation-family report | Five 15-byte report rows, port values 1,2,3,4,4; one has no reply |
| `03 → 83` | Three report/ACK pairs | Not present in selected enrollment rows | Not present in selected enrollment rows |
| Gateway `20 →` device `a0` | Not present in selected sequences | Delayed `02 00` configuration, result `00` | Not present in selected 18-row fixture |
| `05 → 85` | Request length 2; reply data `00 01` | One per-port request; 15-byte reply | Ports 1–4; same 15-byte reply each |
| `06 → 86` | Not present in selected sequences | One plan read; reply data `00` | Ports 1–4; reply data `00` each |
| `59 → d9` | Not present in selected sequences | ID `32`; reply data `00 32 00` | IDs `32..35`; each reply is `00 ID 0c` then twelve `64` bytes |

“Not present” is scoped to these fixture rows, not an unsupported device command.
The `05` handler returns stored **model-specific per-port configuration**: the
sensor's one-byte configuration is not the valves' fourteen-byte configuration.
The `06` zero-only reply represents the empty plan branch in the traced stock
handler; it is not an acknowledgement that the physical valve has completed
enrollment. See the [configuration trace](STOCK_HUB_PAIRING_CONFIGURATION_TRACE.md).

### Captured ordering and phase domains

- HCS026 A/B: `01,03,03,05,03`, phases **2,3,4,5,6**; five gateway replies.
- HTV145 counter-2: `01,02,05,06,59`, valve-request phases **4,5,6,7,8**.
  Between `02` and `05`, the gateway sends `20` at phase **2**, and the valve
  replies `a0` at phase **2**.
- HTV145 Aug-25: the same valve-request families at phases **1,2,3,4,5**.
  Its gateway-originated `20/a0` pair instead uses phase **3**.
- HTV405: `01`, five `02` rows, four `05`, four `06`, four `59`;
  valve-request phases **1..18**, with no response recorded for phase **5**.

Direct replies echo all six request-phase bits. The independently initiated
gateway message is not the next valve-generated phase. An `a0` from the valve
is a response to that message, not a new request to answer. These facts prevent
interpreting the entire conversation as one monotonically advancing counter.

The three-reply HCS026 repeat-enrollment record lacks matching request frames;
the extractor deliberately does not invent them. It contains `81,83,83` and
explicitly records no replies to the final short/terminal messages. This is
the relevant comparison for the existing local three-reply profile.

## Shared byte shapes and their limits

Across the two selected HTV145 profiles and all four HTV405 ports, the `85`
reply data is identical:

```text
00 58 02 0a 00 1e 00 00 00 00 00 00 00 00 00
```

That establishes overlap, not that these are universal defaults to copy into
every product. The first byte is the result; the rest is stored per-port data.
Do not assign meanings to individual configuration bytes without the qualified
parser trace. Transport selector, port, update version and parameter ID are
different fields even when their numeric values happen to coincide.

The single-zone `d9` data `00 32 00` is a zero-length per-port array on the
[qualified retained-model initialization path](STOCK_HUB_POSTBOOT_TRACE.md).
Four-zone arrays contain twelve `64` values, but their application meaning is
not established by those bytes. The arrays are not proven authentication keys
or percentages. No active HCS026/HTV405 descriptor exists in the inspected
snapshot; compiled generic handlers alone cannot fill those gaps.

## Local retry replay, not a new physical result

Three failed September 5 captures contain initial native `06` phase 7 and
retries at phases 8,9,10,11, all with data `0c 01 00`. They contain no `59`.
The source-only recovery behavior now answers those later requests without
altering the first reply or claiming logical advancement. The replay exercises
the actual C++ session with captured requests/replies and measured receive-end
offsets. Assignment setup is explicitly synthetic; this is not waveform replay.

All three replays remain **5/6** and eventually expire when no terminal request
arrives. Additional native tests cover identical repeats, count/time bounds,
delayed terminal arrival, malformed route/command/length/padding, clock rollover
and rejection of unsupported phase jumps. A synthetic terminal can qualify
software handling, not prove that the real valve will send it. Actual RF
acceptance and the original first-reply rejection remain unresolved.

## Reproduction and primary evidence

```sh
python3 -m research.pairing_native_transcripts
python3 -m unittest tests.test_pairing_native_transcripts tests.test_htv145_pairing_retries -v
```

The read-only extractor validates normalized length, sync, integrity residue and
native declared length. It prints command, full phase, data length and data,
omitting endpoint identities. It has no serializer or radio interface. The
selected corpus comprises **42 rows / 79 frames / 37 direct request-reply pairs**.
It keeps unsolicited and observation-only rows rather than forcing every packet
into a device-request/gateway-response pair.

Validation on Sep 28: 11 targeted comparison/replay tests passed; the complete
Python suite ran 698 tests (696 passed, two optional NumPy-dependent skips).
The standalone native protocol test also passed. This validates software and
saved evidence only; no deployment or new physical pairing occurred.

Primary captures:

- [HCS026 stock first/repeat enrollment](fixtures/hcs026_gateway_pairing_replies.json).
- [HTV145 counter-2](fixtures/htv145_counter2_stock_enrollment_20260901.json).
- [HTV145 Aug-25](fixtures/htv145_gateway_pairing_replies.json).
- [HTV405 stock](fixtures/htv405_gateway_pairing_replies.json).
- [HTV145 receive-edge failure](fixtures/htv145_receive_edge_terminal_retry_20260905.json),
  [low-gain failure](fixtures/htv145_low_gain_terminal_retry_20260905.json), and
  [calibrated-tail failure](fixtures/htv145_calibrated_tail_terminal_retry_20260905.json).

Native semantics: [terminal/plan trace](STOCK_HUB_TERMINAL_PAIRING_TRACE.md),
[configuration builders](STOCK_HUB_PAIRING_CONFIGURATION_TRACE.md), and
[channel notifications](STOCK_HUB_CHANNEL_CHANGE_TRACE.md). Retain profile-specific
carrier, timing, wake length, byte matching and integrity rules. This comparison
does not justify merging the two valve state machines or changing proven prefixes.
