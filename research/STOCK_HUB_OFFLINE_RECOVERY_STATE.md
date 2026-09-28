# Stock offline detection and known-device recovery

Offline analysis, 2026-09-27, retained ESP32-S3 application **1.1.1040**.
This extends [sensor recovery](STOCK_HUB_SENSOR_RECOVERY_TRACE.md). No live
devices, cloud requests, NVS settings, firmware or RF commands were changed.
Project status belongs only in the [roadmap](../PROJECT_ROADMAP.md).

## Result

For the captured HCS026 class `48`, the traced expiry path **marks the device
offline and reports that state; it does not send an RF wake command**. Its
registered model callback clears one metadata field per retained property,
not a radio queue. Recovery on the inspected paths begins with an incoming
device packet: an ordinary report refreshes online state, while a recognized
connection announcement can reuse the existing association and channel.

This is a bounded finding about these paths, not proof that no other recovery
mechanism exists anywhere in the hub, or proof that the sensor retries while
asleep. It does not establish what short-press, long-press or battery replacement
causes inside the sensor. Those require packet observation or sensor firmware.

## Detection is separate from recovery

Offsets below are within the **184-byte hub device record**, not RF offsets.

| Stage | Evidence | Meaning |
| --- | --- | --- |
| Periodic check | `4203FCB4`, callback `42038358`, main-task dispatch `42013234` | Registers `offline_check` using interval literal `60000000`; callback queues main-task message `16`, dispatched to `420510C4`. The timer wrapper uses microseconds: nominal one-minute checks. |
| Report refresh | `4204A0A8` -> `420400E0` | For an existing record, refreshes the deadline at `+64..71`; ordinary non-BLE path uses the helper's offline byte multiplied by **60000 milliseconds**. |
| Deadline test | `420512DE..4205136E`, `420AC028` | A nonzero deadline is compared with the monotonic clock; expiry calls `4204A804`. A separate first-record controller exception exists; this is not an unconditional rule for every product. |
| Offline transition | `4204A851..4204A889` | Clears both deadline words, sets update byte `+60 = 1`, online byte `+61 = 0`, updates the record, and invokes state/event/model callbacks. It does not erase the association or set the identity-migration field `+32`. |
| Back online | `4204A0A8`, used by header/report handlers `4204A170` and `42050690` | Accepted incoming traffic refreshes the deadline. Offline/other state `0` or `2` becomes online `1`, subject to an attribute-sync guard. An ACK transmission alone is not this incoming-traffic evidence. |

`420AC074` stores `now + interval`; `420AC028` reports expiry at `now >= deadline`.
The current clock wrapper `420AE4A0` divides the platform timer by 1000.
The nominal check interval does not establish when a sensor's receiver is awake.

### HCS026 offline callbacks resolved

The state callback `4204A050` formats an online/offline event. Its path through
`42049FEC`, `4204591C` and `42039690` queues platform/HTTP reporting; it is not
the RF transmit queue.

The model-event dispatcher `420465A0` looks up the registered class adapter and
calls its callback at adapter `+40`. Registration `42037534` installs classes
`47` and **`48`**, with literal `42002D10` resolving that callback to
`4212B07C`. When descriptor/state collections exist and online byte `+61 != 1`,
the callback clears the 32-bit field at **each property object's `+24`**, then
returns 1. It contains no calls or radio writes. Returning 1 bypasses the
dispatcher's legacy class-47/48 statistics fallback.

Do not call that field a moisture value, timestamp or validity bit yet: its
consumer semantics were not established here. The ordinary compact getter
`4202421C` reads the separate value buffer through property `+20` and length
at `+16`. Thus “offline clears all moisture readings” would overstate the evidence.

Another callback, `4203D474`, currently only accesses the record base and
returns zero. The `4201B214` branch attempts BLE-manager cleanup when a matching
BLE record exists. None of these inspected callbacks provides an HCS026 RF wake.
Periodic extra-value reporting at `42047E98` is separately class-gated and
excludes `48` from its outer predicate.

## Known connection announcements reuse retained state

Native command `01` has a separate header-admission branch in `4204A170`.
The connection handler `420473A8` first searches the sender identity. For an
already-known sender, its branch requires the incoming class to match and the
destination to be the current gateway, zero, or allowed by the existing
nonzero migration field. The selected branches are `420476A0..42047718` and
the continuation at `4204775C`.

This branch does not use the new-device admission check `4203B150` used for an
unknown sender. It reads the retained record and calls `42040410`, which
preserves its nonzero channel selector at `+27`; it allocates a selector only
when that retained value is zero. The reply is built from retained address,
selector and other association data, with ordinary current time/status fields.

This supports our architecture of owner-authorized recovery of known devices
without deleting/recreating them. It does **not** prove that every announcement
is accepted with every global pairing state, that a specific physical button
produces this packet, or that the device accepts the reply. Unknown-device
pairing and known-device rejoin must remain distinct authorization decisions.

The separate foreign-destination result-9 path still requires the migration
condition described in [sensor recovery](STOCK_HUB_SENSOR_RECOVERY_TRACE.md#foreign-destination-reconnect-a-retained-record-condition).
Expiry above does not set it. A network outage is not sufficient evidence to
respond under another gateway's identity.

## Model-specific timing clarification

For the **retained HTV145 model-302 descriptor only**, semantic selector `31`
maps to category-1 compact field ID **24 (`18` hex)**, one byte. The row's
missing/zero port defaults to 1 in `4212B0E8`, matching the lookup through
`42024168`. When a corresponding stored value exists, the heartbeat helper's
existing `80`/`03` predicate can therefore be traced through this model mapping.
Neither selector 31 nor field ID 24 is an RF byte offset.

Defaults remain heartbeat/offline 8/60, with nonzero configured overrides;
the qualified byte predicate may replace offline with `2 × (heartbeat + 1)`.
No active HCS026 descriptor exists in the saved snapshot, so its specific
override cannot be inferred from this valve table. This is a hub availability
policy, not the sensor's missing-ACK sleep duration.

## Practical implication and small physical check

Preserve the already-implemented owner routing and retained-channel recovery;
this research does not justify a new unsolicited recovery transmitter. On a
spare sensor, observe ordinary traffic during a short owner-node outage and
recovery. If it remains silent, one short press while capturing distinguishes:

- No packet observed: check capture coverage and reception before concluding
  the sensor is silent. If it genuinely sends nothing, the hub cannot reply.
- Ordinary report: verify the correct owner replies on the retained selector.
- Connection announcement: verify known-association rejoin and unchanged HA identity.

Keep long-press/battery-rejoin experiments separate if the short-press result
does not answer the question. This avoids a long forced-sleep experiment or
re-pairing all production sensors. The deployment/test procedure remains
[stock-informed validation](../docs/STOCK_INFORMED_VALIDATION.md).

## Reproduction and boundaries

Private, ignored evidence is under the retained stock bundle's
`analysis/ghidra-20260927/offline-recovery-1/` through `offline-recovery-6/`,
with selected S3 objdump listings and image/literal manifest in
`offline-recovery-verification/`. `verify_offline_recovery.py` checks eight
image literals and independently disassembles eleven bounded regions,
including aligned branch targets. The decoder's linear padding artefacts
are not treated as instructions on an executed branch.

The pass exported 54 requested routine/fragments; `42051DD3` is a dispatcher
fragment, not an independent function qualification. The full `42051BD0`
export is used for ACK research instead. Existing model-adapter exports are
reused. No vendor C, private values or firmware bytes are published here.

This does not establish the sensor's MCU, retained pairing implementation,
listen schedule or retry limit. Photographs of both PCB sides and readable chip
markings, taken with its battery disconnected, are the least invasive next
sensor-side evidence before choosing a debug interface or voltage.
