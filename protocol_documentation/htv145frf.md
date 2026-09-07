# HTV145FRF single-zone valve protocol

HTV145FRF is one valve with one watering zone. Local decoding covers state,
duration, water usage, and categorical battery status. The selector-6 local
association supports bounded dry-test controls, report ACKs, persistent counters,
and idle counter synchronization. Full six-stage enrollment and arbitrary
command ordering remain unqualified. These are separate protocol boundaries:
operational command acceptance does not imply a complete pairing transcript.

Read [common.md](common.md) for radio framing, offsets, and integrity rules.
All offsets below include the five-byte sync word.

## Association and radio profile

| Property | Meaning |
|---|---|
| Factory endpoint suffix | `8f` |
| Factory-derived route | Factory endpoint with the first-byte high bit set |
| Association identities | Controller, valve route, and companion; retain all three |
| Reply subchannel | `2 * selector + high_flag` |
| Nominal subchannel carrier | `433031500 + subchannel * 110000` Hz |
| Qualified local branch | Factory counter 2, selector 6, subchannel 12 |
| Command carrier for that branch | 434.3515 MHz nominal; calibrate the radio separately |

Endpoint positions are protocol roles, not universal source/destination fields.
Command builders use the controller and valve endpoints stored in the accepted
association. Do not derive those roles solely from endpoint suffixes. The
companion commonly clears the first-byte high bit of the valve route.
App Device Address is not an RF selector.

## Enrollment

Factory reset, ordinary long-press re-pairing, and battery rejoin are distinct
lifecycle operations. A reset removes batteries for at least ten seconds, then
holds the timer button while reinstalling four fresh alkaline cells until the
red LED flashes rapidly. New local enrollment requires the stock gateway off.

The stock protocol has six numbered stages plus a delayed configuration:

| Stage | Valve request | Gateway action |
|---|---|---|
| 0 | Factory announcement | Assign a coherent association profile |
| 1 | Addressed `01 07 82 25` family | Ordinary short reply |
| 1a | No new request | Delayed configuration with a 2,400-symbol wake |
| 2 | Configuration response `50 00 80` family | Observe only |
| 3 | Addressed `82 81 02` family | Configuration continuation reply |
| 4 | Addressed `03 01 82` family | Short continuation reply |
| 5 | Terminal `2c 80 99` family | Terminal `6c 81 80 19` reply |

Prefixes omit changing sequence/repeat bits. Complete matchers and reply bytes
are defined in `valve_pairing_protocol.py`; branch fields cannot be mixed.
Short replies use a 320-symbol wake. For the local counter-2 branch, delayed
configuration is scheduled 2,952.55 ms after the normalized stage-1 request end.
The configuration response uses the assigned response carrier; other valve
requests in that branch use the lower request carrier.

The supported local candidate sends one counter-2 assignment and preserves the
accepted prefix through the stage-4 request. It reaches 5/6; the final terminal
request remains unproven. A white LED supports initial association acceptance,
but only addressed valve traffic proves progress. The accepted partial
association can produce routine telemetry and positively acknowledged controls.

## Routine state and session summaries

For a structurally valid status report:

```text
frame[20] == 0xcf -> watering
frame[20] == 0x4f -> idle
```

The decoder validates the complete family and association before using these
markers. Accepted report families include address/profile bytes `82`, `85`, and
`86`; a single marker byte is insufficient to identify a report.

Session summaries carry final duration and usage. They can repeat during a later
run, so they update historical session values only. They must not clear current
watering, confirm a pending close, or replace a valid battery reading.

## Duration and water usage

Duration is a packed scalar in two-second units:

```text
units = seconds / 2
low = 0x80 | (units & 0x7f)
high = (units >> 8) & 0xff
extension = units & 0x80
seconds = ((high << 8) | (low & 0x7f) | (extension & 0x80)) * 2
```

Open-command duration occupies bytes 19–20; its extension is byte 21 bit 7.
The marker bit is mandatory and is separate from command-phase polarity.
Examples are 60 seconds `9e 00 / 00`, 300 seconds `96 00 / 80`, and 900 seconds
`c2 01 / 80`. Runtime controls accept whole minutes from 60 to 3,600 seconds.

Usage is encoded in a three-byte field:

```text
half_tenths = ((second & 0x7f) << 8) | (first & 0x7f) | (third & 0x80)
tenths_liter = half_tenths * 2 + bool(second & 0x80)
liters = tenths_liter / 10
```

Routine reports place usage after the status region. Session summaries use
bytes 24–26 for usage and bytes 28–29 for final duration. The complete family
matcher determines which layout applies.

## Battery

Routine status reports use byte 17 bit `0x08`:

| Bit | Category | HA representation |
|---|---|---|
| Clear | Normal/full | 100% |
| Set | Low | 10% |

These are categories, not measured percentages. A summary or unsupported frame
without the battery field must preserve the last valid category.

## Command and response

The ordinary command envelope includes:

```text
frame[13] = 0x80 | (sequence & 0x1f)
frame[14] = command-phase marker, 0x10 or 0x90
frame[15] = 0x82 open, 0x81 close
```

Both actions require 2,400 alternating wake symbols. One logical command uses a
bounded burst of identical RF attempts and stops on a matching reply; it is not
multiple logical opens. Commands are spaced at least 15 seconds apart.

The qualified selector-6 alternating-control recipe uses open marker `90`,
close marker `10`, and residue `4f03` for both. An accepted open advances the
stored five-bit counter; an accepted close retains it. Counter rollover is
supported. Report sequence counters cannot reseed command counters.

This recipe is not a general phase model. Stock consecutive opens can change
the high marker within one association. Arbitrary action ordering requires
additional evidence; do not infer universal marker or trailer rules from a
selector number.

Positive immediate responses use family `86` and result `80`, with a matching
association, counter, action/marker, and duration. Result `83` is a non-success
reply for ordinary commands, including both `50` and `d0` byte-14 variants.
An idle-looking negative reply does not prove the valve physically closed.
Only the explicit idle-anchor reservation below has a narrower exception.

## Report and summary ACKs

One persistent radio owner acknowledges reports. Other receivers may forward
them but cannot transmit competing ACKs. The ACK reverses the association route,
echoes byte 13, and sets byte 14 to the report byte OR `0x40`.

| Input family | ACK bytes 15–17 |
|---|---|
| Routine state | `01 00 01` |
| Session summary | `00 80 00` |

Remaining ACK payload bytes are zero. The local qualification profile uses a
320-symbol wake, residue `4f03`, its calibrated report carrier, and a provisional
40 ms post-reception scheduling target. Exact on-air ACK timing and durable
summary suppression are qualification gates, not implied by a TX-success log.
Owner replacement requires the old owner's correlated revocation reply.

## Idle counter synchronization

Explicit manual or morning synchronization can recover an unknown counter
without watering:

1. Persist a bounded request and wait for a new independent idle report from
   the assigned owner. At radio dispatch that report must be no older than
   five seconds. Require no pending operation and the 15-second command gap.
2. Send only the fixed-zero `80/10` close using the enrolled selector-6 recipe.
3. Require a matching counter-`80`, marker-`50` response: either positive idle
   semantics or the exact qualified result-3/byte-17-`10` body.
4. Authenticate the next normal open as `80/90`, retaining independent physical
   state. A timeout, foreign/late frame, or report counter cannot authenticate it.

There are three total attempts per request. A missing reply or transport failure
waits for a new owner idle report after that failure before retrying the same
anchor with a new command ID. The original window and attempt budget survive
restarts and repeated button presses. Cancellation, exhaustion, expiry,
unexpected watering, conflicting replies, or unqualified negatives terminate
it. Each attempt's bounded RF burst does not consume additional queued attempts.

## Persistence and HA boundary

A requested owner reboot makes control unavailable immediately, even while its
old socket still appears connected. Reconnect must clear the pending-reboot flag.

The gateway stores the association recipe, ACK owner, counter, pending command,
physical state, and morning policy. Reconnect restores configuration and known
counter state; it never replays an unresolved actuator command. Missing idle
telemetry after the planned run plus 30 seconds raises an observation-only
anomaly. Status queries and startup do not authorize an RF sync.

HA exposes counter status, the existing Sync counter button, and morning
settings for a capable enrolled owner. Morning sync defaults disabled. Ordinary
one-zone HA actuation remains gated; the management-token-protected qualification
API is documented in [the add-on guide](../rainpointd_addon/DOCS.md).

## Implementation and evidence

- `rainpointd_addon/rainpointd/valve_protocol.py`: layouts, codecs, ACKs.
- `rainpointd_addon/rainpointd/valve_pairing_protocol.py`: enrollment transcript.
- `rainpointd_addon/rainpointd/htv145_control.py`: persistent control authority.
- [Evidence ledger](../research/VALVE_PROTOCOL_STATUS.md) and
  [fixtures](../research/fixtures/): exact exchanges and qualification results.
- [Roadmap](../PROJECT_ROADMAP.md): remaining physical qualification gates.
