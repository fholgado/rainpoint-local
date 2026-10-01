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

The validated stock transcript contains 18 observed valve rows and 17
gateway transmissions, not 18 distinct authorization commands. Its native
command structure is:

| Exchange | Captured shape |
| --- | --- |
| `01 / 81` | Factory announcement and assignment |
| `02 / 82` | Five addressed report rows covering ports 1–4; one row has no reply |
| `05 / 85` | Four per-port parameter reads, ports 1–4 |
| `06 / 86` | Four plan-parameter reads, ports 1–4; replies contain `00` |
| `59 / d9` | Four device-parameter reads, IDs `32..35`; each reply contains result, ID, length 12 and twelve `64` bytes |

Numbers in this table are hexadecimal native commands, not normalized byte
prefixes. Direct replies echo the full six-bit phase. The parameter arrays'
application meaning is not established by their repeated `64` values; do not
label them percentages or authorization tokens. See the
[cross-device comparison](../research/PAIRING_NATIVE_COMPARISON.md).

Each captured `85` contains status plus fourteen per-port settings bytes, not
watering telemetry. The [field layout](../research/STOCK_HUB_CONFIGURATION_LIFECYCLE.md#fourteen-byte-valve-configuration-layout)
separates default work time, mist timing, soil link, threshold, flags, delay,
calibration and pressure-labelled fields; units/effects remain qualified there.
Native `02` request flags mask `0x02` controls a configuration revision in `82`.
That revision is separate from device software version and the RF command phase.

The custom profile uses a
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
sequence at `1`. Pairing or routine telemetry phases must not reseed that local
control state; the stock hub's shared generator is a separate implementation fact.

## Routine link report and acknowledgement

The paired valve emits periodic link/status reports; cadence varies by state
and profile. Its
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

Native durations are **little-endian seconds**. The normalized frame starts one
bit before the native payload, splitting each value across three bytes. For the
fields below, reconstruct the two native bytes as follows:

```text
native_low  = ((field_low << 1) | (field_high >> 7)) & 0xff
native_high = ((field_high << 1) | (extension >> 7)) & 0xff
seconds = native_low | (native_high << 8)
```

The locations are:

| Frame family | Field | Extension bit |
|---|---|---|
| Gateway open command | `frame[19..20]` | `frame[21] & 0x80` |
| Requested duration in valve state | `frame[29..30]` | `frame[31] & 0x80` |
| Remaining duration in valve state | `frame[26..27]` | `frame[28] & 0x80` |

Bit 7 of the normalized high byte is the low seconds bit, **not a status flag**.
Keep it for odd remaining times: the captured 900-second run reports 895,
not 894. The source decoder covers remaining values 0–3,600. The public control
range remains every whole minute from 1 through 60; its existing even-seconds
builder is unchanged. The same native units appear in retained HTV145 commands.
The non-inverted 17-minute command's extension `0x80` is duration data, not
selector polarity. See the [stock/capture trace](../research/STOCK_HUB_VALVE_STATE_TRACE.md).

## Control request

Native command `21` carries `[port, 02, 01, seconds_low, seconds_high]` for
open and `[port, 02, 00]` for close. Native offsets and six-bit phase are defined
in [common.md](common.md). The physically accepted alternating-control recipe
has this normalized envelope:

Generated local associations use `[01, port << 1, 01, seconds_low, seconds_high]`
for open with the same existing normalized builder below. Their positive `a1`
state byte is `(port << 5) | 01` (Zone 2: `41`); local `02` active reports pack
the outlet into that state byte and clear it to zero when all outlets are idle.
Use the qualified state decoder rather than treating native payload byte 2 as
the outlet for every association. The experimental verifier follows both
layouts. Two guarded 60-second opens at adjacent native phases 4 then 5 were
physically accepted on a generated local association's Zone 2, with matching
positive replies and active/automatic-idle reports. Command phase parity does
not itself select open versus close; the body carries that action. The public
production builder still uses the alternating-control recipe below. See the
[qualified trial evidence](../docs/VALVE_PHASE_TRIAL.md#october-1-four-zone-adjacent-phase-confirmation).

```text
frame[13] = 0x80 | five-bit command sequence
frame[14] = 0x90 open, 0x10 close
frame[15] = 0x82 open, 0x81 close
frame[16] = 0x80
frame[17] = 0x80 | one-based zone
frame[19..20] = encoded duration for open; zero for close
frame[21] bit 7 = displaced duration bit for open; zero for close
```

The `90/10` polarity contains the sixth phase bit; `82/81` encodes declared
data length, not separate open/close opcodes. Do not generalize this recipe
to arbitrary action order by ignoring the phase's low bit.

Stock captures also contain **even-phase opens and odd-phase closes** (ports
3 and 4, phases 20/21 and 22/23). The fixed parity above is the current local
recipe, not a receiver requirement. Source-only full-phase adapters preserve
this recipe's body packing; they are not enabled in the runtime. See the
[cross-model phase audit](../research/VALVE_FULL_PHASE_CROSS_MODEL_AUDIT.md).

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

## Command response and sequence

The following is the **legacy local decoder contract**, not a general stock
reply definition. Stock `a1` data byte 1 carries control/work mode; its old
normalized "zone" nibble does not reliably identify the requested port. A
generalized matcher must obtain that port from the pending command and verify
its independent state report. See the
[reply-context correction](../research/VALVE_FULL_PHASE_CROSS_MODEL_AUDIT.md#reply-context-correction).

The current decoder recognizes this envelope:

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

The stored logical counter is `frame[13] & 0x1f`, but response matching requires
the full phase `((frame[13] & 31) << 1) | (frame[14] >> 7)` as well as action,
identity and result. Under the current local allocation policy, a watering response advances the
durable next command sequence by one; an idle/close response retains the same
sequence. The stored sequence wraps in its five-bit field. This policy is not
the stock hub's general six-bit allocation rule.

## Counter synchronization and scheduling

All four zones share one command counter. A fresh generated association starts
at 1. A same-route repair preserves an authenticated counter when controller,
companion, selector, and valve identities are unchanged. Restart restores the
stored value; routine report sequences never overwrite it.

An authenticated idle close assigns its submitted five-bit counter. Recovery
therefore uses a fixed Zone 1 close at counter 0, not a counter search:

1. Independently confirm the valve is idle.
2. Send close 0 with no duration and require a matching authenticated idle reply.
3. Store next counter 0 only after that reply.
4. Wait the 15-second hardware interval before sending an open.

An idle sync response may identify the last watered zone. That exception is
restricted to an already-idle synchronization reservation; ordinary watering
responses must still match the requested zone.

The standalone diagnostic may repeat one silent anchor once at the same value.
A second silence or strict negative response fails. Restart does not replay a
transmitted command or establish synchronization.

Without morning mode, a requested open is an observable transaction: reserve the
zone and duration, synchronize at fixed zero, wait the command interval, and
send one bounded open. Completion requires the authenticated watering response.
Duplicate starts are rejected; cancellation is allowed before open dispatch.

Optional morning mode persists an enabled flag, local start time, timezone, and
window. It waits for an eligible owner report and confirms the idle anchor, then
uses the retained counter for direct daytime requests. Unknown counters block
direct starts. The complete 1/4/8/12-hour retention matrix is still a qualification
limit; a successful immediate sync is not proof of indefinite counter validity.

Startup, missing telemetry, and client loss never send a speculative close.
Reports reconcile physical state; command intent alone cannot set HA watering.

## Battery and unsupported water usage

Battery is a declared HTV405 capability but remains unavailable locally. The
offset-`17` bit `0x08` is a research candidate and
has not been correlated to a controlled normal-to-low transition.

Routine gateway ACKs have fixed bytes 15–17 `01 00 01` and zeros through byte
35. Pairing ACKs can instead contain `01 00 00 80 ...`; this is a different
protocol stage, not battery evidence. Control-response byte 17 is the zone field
and does not have status-report battery semantics.

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
