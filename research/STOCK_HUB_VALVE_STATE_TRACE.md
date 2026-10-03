# Stock valve framing, command state and acknowledgements

Research date: 2026-09-27. Reference: privately retained stock **1.1.1040**,
offline ESP32-S3 disassembly plus existing RF fixtures. No device connection,
transmission, flashing, firmware modification or runtime-code change was used.
Status remains in [the roadmap](../PROJECT_ROADMAP.md); implementation requires
review of the [improvement plan](STOCK_FIRMWARE_IMPROVEMENT_PLAN.md).

## Result

The stock implementation and captured packets now agree at a much cleaner
boundary: our historical normalized frames start **one bit before the hardware
sync**, so their byte fields are shifted relative to the stock payload.
Undoing that shift reveals an ordinary six-bit sequence, command/ACK byte,
payload length, port, mode and little-endian duration in seconds.

This explains several formerly separate-looking bits without new RF guesses.
It does **not** establish the valve's receive acceptance window, its own
battery-reset state, or why a particular historical night lost control. Those
are valve-side questions, while this dump is gateway firmware.

Evidence classes below are **Static** (bounded code/constant), **Capture**
(retained packet), **Corroborated** (both), and **Inference** (not yet proven).
Tool qualification and alignment rules are in
[decoder tooling](STOCK_HUB_DECODER_TOOLING.md).

## 1. The normalized/raw boundary

**Corroborated.** Let `N` be an existing normalized 38-byte frame and `P` the
32-byte hardware payload:

```text
P[i] = ((N[i + 4] << 1) | (N[i + 5] >> 7)) & 0xff, i = 0..31
```

The radio investigation independently recovered hardware sync `f3 e9 10 5e`.
One preceding zero bit, that 32-bit sync, and the first seven bits of payload
header `51` produce our normalized prefix `79 f4 88 2f 28`. This is a change
of representation, not a different radio protocol. The hardware frame-length
and CRC boundary are covered by the [radio trace](STOCK_HUB_RADIO_PATH_TRACE.md); do not rewrite
trailers merely by shifting a 38-byte capture, since its last hardware CRC bit
is outside that historical window.

The internal header builder `_bd_sdev_comm_pack_master_intern_header`, entry
`0x4203A344`, supplies this layout. Offsets below are **payload offsets**, not
the old normalized offsets:

| Payload location | Stock construction | Interpretation established here |
| --- | --- | --- |
| `P[0]` | `0x4203A3CF..0x4203A3E8` | Header byte `51` |
| `P[1..4]` | `0x4203A3EB..0x4203A408` | Device identity from the selected record |
| `P[5..8]` | `0x4203A40B..0x4203A420` | Gateway-context identity |
| `P[9] & 0x3f` | `0x4203A435..0x4203A447` | Six-bit generated sequence |
| `P[10] & 0x7f` | `0x4203A423..0x4203A432` | Command family |
| `P[10] & 0x80` | `0x4203A44A..0x4203A459` | Separately carried command high bit; replies below set it |
| `P[11] & 0x1f` | `0x4203A45C..0x4203A46D` | Following data length |

Identity roles can reverse in replies. They must not be assigned universal
source/destination names solely from their positions. The upper bits of
`P[9]` and `P[11]` are not fully generalized here.

The radio adapter `0x42016A28` independently reads `P[9] & 63`, `P[10]` bit 7,
and validates caller length against `(P[11] & 31) + 12`. This agrees with the
serializer rather than only fitting captured bytes.

## 2. Actual valve command construction and duration

**Static.** The relevant actuator builder is
`bd_sdev_comm_snd_control_cmd`, entry **`0x4204FCAC`**, not the similarly named
generic DP-control function `0x42052920` (which uses command `0x5c`). Its
diagnostic at `0x3C155288` labels its arguments `addr`, `port`, `ctl_mode`,
`workmode`, `worktime`, and parameter length.

In the ordinary, non-extended command path:

- `0x4204FFC8..0x4204FFCE` stores port, control mode and work mode at stack
  `+54..56`.
- A nonzero worktime is stored low byte then high byte at stack `+57..58`,
  `0x4204FFDB..0x4204FFE1`. There is no division by two in that serializer.
- Header destination is stack `+42`; command **`0x21`** is passed at
  `0x420500E2`, and the master-header builder is called at `0x420500E7`.
- It then wraps the transport metadata and inserts the request into the
  wait-for-reply list at `0x42050125`.

**Capture + Static.** Stock HTV145 and HTV405 control fixtures yield:

| Field | Open | Close |
| --- | --- | --- |
| `P[10] & 0x7f` | `0x21` | `0x21` |
| `P[11] & 31` | `5` | `3` |
| `P[12]` | One-based port | One-based port |
| `P[13]` | `2` in these stock captures | `2` |
| `P[14]` | `1` | `0` |
| `P[15..16]` | Unsigned little-endian seconds | Absent from declared data; zero padding in fixtures |

Therefore normalized `N[15] == 82` versus `81` is principally the shifted
**length**, not an independent open/close opcode. Normalized marker polarity
in `N[14]` includes a sequence bit, not simply an action flag. Both distinctions
matter when generalizing beyond alternating open/close tests.

Sources: [HTV405 stock matrix](fixtures/htv405_stock_cloud_control_matrix_20260824.json),
[HTV145 300/900-second commands](fixtures/htv145_selector6_stock_duration_commands_20260828.json),
[HTV145 consecutive opens](fixtures/htv145_selector2_stock_pairing_control_20260905.json).
Tests compare requested durations and observed actions, not merely an encoder
round trip. The existing normalized whole-minute codec can still be correct:
its two-second units and extension bit are an artifact of that representation.

### A one-second precision discrepancy

**Capture.** Undoing the shift on the two active reports in
[the HTV405 duration-boundary fixture](fixtures/htv405_packed_duration_boundary_20260902.json)
gives requested durations `300` and `900` at `P[25..26]`, and remaining durations
`294` and **`895`** at `P[22..23]`. The existing fixture preserves prior decoder
outputs `294` and **`894`**. The second result is not silently rewritten in the
new test: both the raw value and the historical even-rounded value are asserted.

The bit formerly treated as unrelated status (`N[27]` bit 7) falls exactly in
the native seconds field's least significant position. This is strong evidence
for a one-second precision bug in the current remaining-time decoder, not a
failure of the previously qualified requested minute durations. A reviewed fix
should add odd/even fixtures and check both valve report families before
changing runtime decoding.

## 3. Counter generation: a global six-bit header field

**Static.** `0x42037920` loads the byte at **`0x3FCA710F`**, increments it,
stores it, and replaces it with 1 if its *previous* value exceeded 63. Callers
mask the result to six bits. Starting from zero this produces wire values
`1..63, 0, 1..`; the transient stored value 64 becomes wire zero. This is not a
timer-triggered reset to 1.

The actual `0x21` control builder reaches it through the master-header builder.
Other observed callers include the gateway-sensor product-test path near
`0x4204DE68` and the OOK time-data path near `0x4204FC03`. This is a shared hub
sequence source, not an independently indexed per-valve counter in this path.

**Corroborated.** The full sequence is:

```text
phase = P[9] & 0x3f
      = ((N[13] & 0x1f) << 1) | ((N[14] >> 7) & 1)
```

The stock HTV145 consecutive-action fixture progresses `3,4,5,6,7` across
**open, open, close, open, close**. The HTV405 stock four-zone matrix progresses
`3..10` across its eight commands. The previously separated five-bit counter
and inverted marker together form one six-bit field in these examples.

### Persistence and reset limits

**Initial bounded search.** The retained app has no load segment covering
`0x3FCA710F`. The loaded DRAM segment is `0x3FC9EC00` with length `0x56D0`;
the candidate byte lies beyond it. A direct-literal reference search found the
qualified sequence-generator loads and no qualified additional setter. Two
byte-pattern candidates elsewhere decoded as unrelated instruction interiors
and were discarded.

**Subsequently established:** decompilation of entry `0x4037589C` recovered a
ROM `memset` call at `0x403758C9` clearing `[0x3FCA42D0, 0x3FCACF20)`, including
the sequence byte. The constants and call were independently checked against
the original image and S3 objdump; Espressif's pinned ROM map identifies the
target. Thus the byte is zero at that startup stage, not merely hypothesized
to be BSS. See [boot-state evidence](STOCK_HUB_BOOT_STATE_REFERENCE.md).

Later restoration/advancement is not excluded. No sequence NVS save/restore,
periodic reset, pairing-triggered reset, or valve battery-reset rule has been
demonstrated. The stock startup notification already consumes this shared
sequence, so zero at early boot does not guarantee the first valve command
uses 1. No independent reboot evidence ties this clear to the historical
overnight failures. A negative direct-reference search still cannot prove
that another path cannot modify the byte.

Most importantly, **gateway generation is not valve acceptance**. These findings
do not prove that a valve requires the exact next global value, accepts any new
value, rejects only duplicates, or keeps its counter across batteries. A global
source shared by commands to different devices makes a universal per-valve
strict-next hypothesis especially worth testing, but not replacing production
recovery with speculation.

## 4. Retries reuse the packet; ACKs match a tuple

The [follow-up lifecycle trace](STOCK_HUB_ACK_RETRY_LIFECYCLE.md) qualifies
ordinary retry budget four, a 700-ms periodic timer, result/expiry handling and
the distinction between local timeout and RF rejection. A conditional result
forwarding path consumes a generated phase before replacing it with an echoed
one. None establishes a valve-side reset or acceptance rule. The
[version comparison](STOCK_HUB_VERSION_COMPARISON.md) finds the same generator
instruction body and six-bit ACK matching in both retained versions.

**Static.** `_bd_sdev_comm_insert_wait_reply_list` (`0x4204A8E0`) copies the
already built transport packet into a heap-backed record and stores expected
command with ACK bit, sequence and device identity. The request is transmitted
through `0x4203A684`; timer callback `0x42038BAC` posts message 61. The timeout
handler is `bd_sdev_comm_initiative_send_cmd_timeout_hdl` (`0x420443F8`).

The resend branch `0x42044552..0x420445F7` allocates a replacement copy, marks
the old transport metadata byte `+1` as 1 (`0x420445A6`), copies that packet and
sends it (`0x420445D7`). It then stores the replacement and repairs its internal
payload pointer. **It does not call the header generator or allocate a new
sequence on that retransmission branch.** The transport metadata byte is not
an on-air payload offset.

ACK processing first calls `0x4204A550` from `0x42051DD3`. That routine checks:

1. Reply identity `P[1..4]` equals the gateway context (`0x4204A58C..0x4204A5AD`).
2. Full command byte, including ACK flag, equals queued expected command
   (`0x4204A5E8..0x4204A5FA`).
3. **All six sequence bits** equal queued sequence
   (`0x4204A600..0x4204A609`).
4. Reply identity `P[5..8]` equals queued device identity
   (`0x4204A60F..0x4204A62F`).

Only the matched entry is unlinked and freed (`0x4204A662..0x4204A694`). Further
command-specific result processing follows; matching a reply is not by itself
proof of positive watering state. For control replies command `0xA1` dispatches
to `0x4204E320`; the separately named generic gateway-RF ACK check is used for
`0xF4`, not indiscriminately for all valve responses.

This supports correlated transactions and exact retransmission bytes. It does
not authorize replay after process restart or sending a new counter whenever
an ACK is lost. No durability guarantee for the stock pending list is claimed.

## 5. Pairing stages now have concrete command families

**Capture, corroborated by reply-header construction.** The full HTV145 stock
exchange unshifts as follows; lengths exclude the 12-byte header:

| Observed operation | Phase | Request command / length | Reply command / length |
| --- | ---: | --- | --- |
| Factory request / assignment | 1 | `01 / 8` | `81 / 11` |
| First paired request | 2 | `02 / 15` | `82 / 2` |
| Delayed gateway configuration | 2 | `20 / 2` | `A0 / 1` |
| Parameter request | 3 | `05 / 2` | `85 / 15` |
| Following request | 4 | `06 / 3` | `86 / 1` |
| Previously named `2c/99` terminal request | 5 | **`59 / 1`** | **`D9 / 3`** |

`0x4203A4FC` echoes input sequence low six bits at `0x4203A5FD..0x4203A60F`
and sets command bit 7 at `0x4203A612..0x4203A615`. All six captured request/reply
pairs match those rules. Phase numbers here belong to this fixture; they are
not universal stage ordinals or valve-control initialization values.

This creates a concrete next static target for the still-unqualified HTV145
terminal continuation: **command `0x59`**, rather than changing the successful
prefix based on normalized marker names. Its semantic payload and necessity
for long-term operation are not recovered here. The reconnect header branch
still differs in identity construction; this is not proof of battery rejoin.

## 6. Discarded leads and implementation implications

`bd_sdev_comm_inform_dev_ser` is **not established as a sequence-reset command**.
Its fallback at `0x420522D8` calls `0x42052234`, identified by its diagnostic as
`_bd_sdev_comm_check_wifi_rssi_change`. That branch formats and forwards a state
report; the other branch requests subdevice parameter update. The word `ser`
cannot be used to claim a counter synchronization mechanism.

Likewise `bd_sdev_comm_process_mcu_abnormal_restart` has an early configured
product gate comparing 78 and 85 (`0x42051FE7..0x42052002`). Its existence does
not demonstrate HTV145/HTV405 battery-rejoin handling or even a second MCU on
this particular hub.

The reviewable approach is to first add an analysis-only native-payload view
while retaining captured normalized bytes, qualify full six-bit request/reply
matching and odd-second report decoding, then use controlled multi-device and
hub/valve-restart captures to distinguish sender state from receiver acceptance.
The successful pairing prefix and fixed idle-anchor recovery remain untouched
until a narrower replacement has independent acceptance evidence.

## Reproduction

Five hardware-free tests in
[`tests/test_stock_valve_frame_reference.py`](../tests/test_stock_valve_frame_reference.py)
pass against retained fixtures. They cover both valve families, all four
ports, distinct durations, full pairing reply sequences, successive opens,
and the deliberately preserved 895-versus-894 remaining-time discrepancy.

```sh
python3 -m unittest tests.test_stock_valve_frame_reference -v
```

Private bounded listings, input hash, exact tool path, address ranges and
reproduction helpers are retained under ignored
`captures/stock-hub-firmware/2026-09-27-adzoj0e3/analysis/valve-state-20260927/`.
Directories use mode 700 and files 600. Nothing requires publishing firmware,
disassembly, device credentials or installation identities. No original
symbols/source were recovered; diagnostic names and independently checked
branch entries ground the address claims.
