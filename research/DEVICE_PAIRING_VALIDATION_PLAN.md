# Device lifecycle validation procedure

Use this procedure for one authorized hardware trial. Current completion and
ordering are in [the roadmap](../PROJECT_ROADMAP.md); packet rules are in
[the device references](../protocol_documentation/). Dated trials and exact frames
belong in [fixtures](fixtures/) and [capture notes](RF_CAPTURE_NOTES.md).

## Prepare

1. Identify the physical specimen, accepted association, assigned radio, firmware
   hash, controller/companion routes, and whether it is a new or retained device.
2. Record battery condition and isolate a test valve from pressurized watering.
   Confirm the permitted duration and scope before testing an installed zone.
3. Keep stock gateway power under explicit control. For stock captures, verify
   every custom node is effectively receive-only before the gesture; for local
   enrollment, keep stock replies absent.
4. Start a bounded lossless capture before arming. Save metadata, hashes, exact
   command IDs, timestamp timezone, and pre-trial HA device/entity inventory.
5. Check fresh radio authentication, disarmed state, and no pending reboot,
   control, revocation, or competing ownership operation.

## New enrollment

Use the HA profile for the actual model and select one nearby radio. Follow the
manufacturer's exact gesture and retain its LED/app result. Never substitute a
battery cycle for a documented reset or merge opposite arming orders into one trial.

Require addressed device-owned continuation and terminal evidence. Distinguish
an accepted prefix from full completion. Keep optional protocol tails visibly
armed until they end; user naming must not prematurely cancel them. A tail timeout
after authoritative acceptance must not erase that acceptance.

Verify HA creates one physical device with only supported capabilities, saved
name/area, and no duplicate per receiver. For valves, qualify bounded control
separately from pairing using the [pairing playbook](PAIRING_REVERSE_ENGINEERING_PLAYBOOK.md).

## Retained lifecycle matrix

Run each operation independently against a recorded baseline:

| Operation | Required evidence |
|---|---|
| HA restart | Same device/entity IDs and history; no actuator replay |
| Gateway restart | Same association, ACK owner, counters and reservations; no speculative close |
| Owner reboot/OTA | New connection/boot evidence, restored assignments, continued reports and control |
| Device battery cycle | Same identity and normal reporting without opening new enrollment |
| Retained re-pair | Same physical identity; preserve an authenticated counter only for an unchanged qualified route |
| ACK reassignment | Correlated revocation on old owner before new owner may transmit |
| Remove and re-add | No stale controls/routing or duplicate entities; explicit re-enrollment clears suppression correctly |
| Stock/custom coexistence | Distinct authority for each cohort with normal reporting and no conflicting ACKs |

Do not forget a duplicate registry alias if that operation would delete the live
physical association or revoke its working ACK owner. Resolve canonical identity
first and remove only the obsolete HA representation.

## Reliability and counter proof

For sensors, record direct radio provenance, accepted moisture reports, report
gaps, ACK send/failure counters, and recovery frames. An ACK-success log alone
cannot prove the sensor accepted it. A snapshot with a high report count cannot
prove continuous health; retain the event window.

For valves, record command/reply correlation, independent watering/idle, duration,
command-counter progression, owner continuity, and summary retransmissions.
Never use a telemetry sequence as the command counter. A synchronized idle
anchor and a later accepted open are separate pieces of evidence.

Use [durable collection](../examples/reliability-soak/README.md) for extended
observations. Restart, missing samples, overdue telemetry, and intervening commands
must remain visible in the result. No test may turn silence into acceptance by
replaying an unbounded open or resetting its retry budget.

## Finish

Disarm pairing and end temporary receive-only/capture modes. Confirm independent
idle, normal node connectivity, single ACK ownership, and expected HA identity.
Restore the original schedule unless a policy change was authorized. Remove
one-off probe code only after retaining useful redacted fixtures and rollback
artifacts. Update the roadmap only for the gates whose full evidence exists.
