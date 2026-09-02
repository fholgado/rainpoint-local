# HTV405FRF four-zone valve protocol

The `HTV405FRF` is one RF device with four mutually exclusive watering zones.
The custom gateway supports local enrollment, telemetry, routine
acknowledgements, and supervised control.

## Identity and association

| Property | Definition |
|---|---|
| Factory endpoint suffix | `13` |
| Paired endpoint | Factory endpoint with `0x80` set in its first byte |
| Logical zones | `1..4`, one active at a time |
| Supported local profile | `htv405_auto_candidate_v1` |

All four zones share one endpoint and one Home Assistant device. A generated
custom-gateway association preserves the valve endpoint when migrating an
existing record, so a new enrollment must not create one device per radio node
or per zone.

## New enrollment

The validated stock transcript contains 18 observed valve stages and 17
gateway transmissions. The custom profile reproduces that transcript using a
generated controller/companion identity and association-specific clock,
carrier, selector branch, and integrity residue.

The exchange is implemented as a table-driven state machine in
`valve_pairing_protocol.py`. The key invariants are:

- the initial assignment is sent approximately 50.656 ms after the factory
  request ends;
- the assignment carrier is approximately 433.556430 MHz with about 35 kHz
  deviation for the validated selector-2 profile;
- paired routine traffic is near 433.471408 MHz with ordinary deviation around
  41.26 kHz;
- selector-2 and selector-6 transcripts are coherent association profiles and
  cannot be mixed field by field;
- `paired_message_2_repeat` is observed without a gateway reply;
- completion requires a strict paired-link frame during the active session
  after the selected node has transmitted assignment reply 1;
- the stock transcript's final `9a` tail is not required for a successful
  generated-identity association.

The exact 18-stage matcher and reply bytes are the executable definition. The
fixture `research/fixtures/htv405_gateway_pairing_replies.json` preserves the
captured reference transcript.

A fresh generated association initializes the independent valve command
sequence at `1`. Pairing sequence bytes, routine telemetry sequence bytes, and
the command sequence are unrelated.

## Routine link report and acknowledgement

The paired valve emits link/status reports at roughly 40-second intervals. Its
persistent ACK owner answers on the negotiated association channel.

For a report sequence `SS`, the acknowledgement routes from the valve endpoint
to its companion endpoint and uses:

```text
body[0] = 0x80 | (SS & 0x1f)
body[1] = 0x41, with the captured repeat flag preserved when required
body[2..4] = 01 00 01
body[5..22] = 00
```

The association's valid integrity residue is retained. Other radio nodes may
forward the same report but must not send duplicate ACKs. The firmware
schedules this reply 49.5 ms after receive completion, matching the captured
ordinary-response slot.

## State telemetry

A strict HTV405 state report satisfies these normalized-frame checks:

```text
frame[15] == 0x07
frame[16] has its high bit set and carries the logical address
frame[17] low 7 bits is 0x05 or 0x07
frame[20] low 7 bits is 0x4f
frame[25] == 0x40
frame[28] low 7 bits == 0x56
```

Watering state is `bool(frame[20] & 0x80)`.

Zone packing depends on the association profile:

```text
selector-6 / stock:
    zone = (frame[18] & 0x7f) * 2 + bool(frame[19] & 0x80)

selector-2 / generated local:
    zone = (frame[19] & 0x70) >> 4
```

An idle report with zero zone clears all four zone states. State changes in
Home Assistant must come from an authenticated command response or an
independent strict state report, never from a transmitted command.

## Duration

HTV405 duration is a packed counter in two-second units. Bit 7 of the low wire
byte is always the protocol marker, so the data bit that would occupy that
position is carried in bit 7 of an adjacent extension byte:

```text
units = seconds / 2

encode:
    field_low = 0x80 | (units & 0x7f)
    field_high = (units >> 8) & 0xff
    extension = units & 0x80

decode:
    units = (field_high << 8) | (field_low & 0x7f) |
            (extension & 0x80)
    seconds = units * 2
```

The locations are:

| Frame family | Field | Extension bit |
|---|---|---|
| Gateway open command | `frame[19..20]` | `frame[21] & 0x80` |
| Requested duration in valve state | `frame[29..30]` | `frame[31] & 0x80` |
| Remaining duration in valve state | `frame[26..27]` | `frame[28] & 0x80` |

The remaining-duration high byte also carries an unrelated status bit which is
cleared before reconstruction. The supported product range is every whole
minute from 1 through 60. The same scalar layout appears in retained HTV145
stock commands; notably, a non-inverted 17-minute command carries extension
`0x80`, proving that the extension is duration data rather than selector
polarity.

## Control request

The physically accepted gateway-command envelope is:

```text
frame[13] = 0x80 | five-bit command sequence
frame[14] = 0x90 open, 0x10 close
frame[15] = 0x82 open, 0x81 close
frame[16] = 0x80
frame[17] = 0x80 | one-based zone
frame[19..20] = encoded duration for open; zero for close
frame[21] bit 7 = displaced duration bit for open; zero for close
```

The controller route is the paired valve endpoint and the destination is its
association companion endpoint. The current local transmitter uses residue
`0x4f03` and accepts every whole-minute duration from 60 through 3,600 seconds.
The complete carrier, bounded repeated-attempt envelope, and timing are built
from the valve's stored association profile by the supervised firmware and
`htv405_control.py`.

Representative encodings are:

| Requested | Field | Extension |
| ---: | --- | ---: |
| 60 seconds | `9e 00` | `00` |
| 240 seconds | `f8 00` | `00` |
| 300 seconds | `96 00` | `80` |
| 540 seconds | `8e 01` | `00` |
| 900 seconds | `c2 01` | `80` |
| 1,200 seconds | `d8 02` | `00` |
| 3,600 seconds | `88 07` | `00` |

The earlier 300- and 900-second candidates `16 01` and `42 02` were rejected
because they omitted the mandatory low-byte marker. The earlier `c2 01 00`
900-second attempt retained the marker but lost the displaced bit and was
therefore decoded by the valve as 644 seconds. Those failures are direct
boundary evidence for the packed representation above, not special-duration
exceptions. Corrected local `96 00 80` and `c2 01 80` commands subsequently
received authenticated responses and exact independent 300/900-second state
reports; the five-minute timer also reached valve-owned automatic idle.

## Command response and sequence

A valid immediate response has this envelope:

```text
frame[14] low 7 bits == 0x50
frame[15] == 0x86
frame[17] high nibble == zone 1..4 and low nibble == 0
frame[18] low 7 bits == 0x4f
frame[23] == 0x40
frame[26] low 7 bits == 0x56
```

It routes from the association companion with its first-byte high bit set to
the paired valve endpoint.

The response sequence is `frame[13] & 0x1f`. A watering response advances the
durable next command sequence by one; an idle/close response retains the same
sequence. The sequence wraps in its five-bit field.

Validated continuity includes:

```text
fresh pairing -> next 1
open at 1     -> response advances next to 2
open at 2     -> response advances next to 3
close at 3    -> response retains next 3
open at 3     -> response advances next to 4
close at 4    -> response retains next 4
gateway and node restart -> next remains 4
open at 4     -> response advances next to 5
close at 5   -> response retains next 5
open at 5    -> response advances next to 6
close at 7 after authenticated next 6
               -> response accepts and retains next 7
close at 9 after authenticated next 7
               -> response accepts and retains next 9
open at 9     -> response advances next to 10
close at all 32 five-bit values from authenticated next 10
              -> every response accepts and retains the selected value
open at 31    -> response advances next to 0
close at 0    -> response accepts and retains next 0
open at 0     -> response advances next to 1
```

The gateway persists the next sequence only after a matching authenticated
response. It never derives it from periodic telemetry. A timed open is
valve-owned and stops automatically; startup must not issue a speculative
close.

A strict negative response has the body prefix:

```text
d0 86 83 00 4f
```

It echoes the attempted sequence and does not advance the counter. Absence of
a response is a failed attempt, not proof of rejection or acceptance.

The controlled 2026-09-02 exhaustive test began from authenticated next `10`
and visited every five-bit close value once in bit-reversed order. All 32
values returned a matching authenticated idle response and retained the value
that had just been sent. An open at `31` then authenticated and advanced to
`0`; after valve-owned automatic idle, close `0` authenticated and a 60-second
open at `0` advanced to `1` and again stopped automatically.

An authenticated idle close is therefore a non-actuating counter assignment,
not a candidate check. The synchronization procedure is deterministic:

1. Independently confirm the valve is idle.
2. Send a Zone 1 close at fixed five-bit anchor `0`, with no duration.
3. Publish next counter `0` only after the matching authenticated closed
   response.
4. Observe the 15-second hardware command interval before an open at `0`.

The standalone synchronization diagnostic may repeat one silent anchor once at
the same value to tolerate a lost RF exchange. A second silence or a strict
negative response stops fail-closed; neither dispatch nor silence establishes
synchronization. Its retry state is durable across a gateway or assigned-node
restart, while pre-0.33.36 multi-candidate recovery state is normalized to
anchor `0` before any transmission.

An end-user open is a distinct single-attempt transaction:

1. Reserve the requested zone and validated duration.
2. Send the fixed close-`0` anchor and wait for its authenticated idle response.
3. Wait until 15 seconds have elapsed from the anchor transmission.
4. Send the requested open at counter `0`.
5. Report success only after the matching authenticated watering response.

Duplicate starts are rejected. Timeout, strict rejection, node or transport
loss, unexpected watering, or gateway restart terminates the transaction and
clears the queued open. An operator may cancel only before step 4. The gateway
never restores or replays a queued open after restart.

## Battery and unsupported water usage

Battery is a declared HTV405 capability but remains unavailable locally. The
previously suspected offset-`17` bit `0x08` is only a research candidate and
has not been correlated to a controlled normal-to-low transition.

HTV405 does not expose water usage. Its cloud product definition includes
per-zone work state, alarm, event time, and duration plus chassis battery and
RSSI, but no flow or water-volume data point. The local integration must not
create or populate a water-usage entity for this model.

## Evidence and implementation

- Pairing: `rainpointd_addon/rainpointd/valve_pairing_protocol.py`
- State, duration, commands, responses, and ACKs:
  `rainpointd_addon/rainpointd/valve_protocol.py`
- Enrollment fixture: `research/fixtures/htv405_gateway_pairing_replies.json`
- Accepted local enrollment: `research/fixtures/htv405_local_pairing_success.json`
- Multi-zone control: `research/fixtures/htv405_local_multizone_control_20260823.json`
- Counter continuity:
  `research/fixtures/htv405_generated_identity_counter_continuity_20260901.json`
- Counter drift, exhaustive idle-close selection, rollover, and fixed anchor:
  `research/fixtures/htv405_overnight_counter_drift_20260902.json`
- Evidence ledger: [`../research/VALVE_PROTOCOL_STATUS.md`](../research/VALVE_PROTOCOL_STATUS.md)
- Chronology: [`../research/RF_CAPTURE_NOTES.md`](../research/RF_CAPTURE_NOTES.md)
