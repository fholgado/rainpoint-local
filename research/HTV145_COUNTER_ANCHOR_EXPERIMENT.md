# HTV145 counter-recovery verification

Current wire rules are in the [single-zone device reference](../protocol_documentation/htv145frf.md).
The supported recovery operation sends a fixed-zero close after new idle evidence
from the assigned owner; synchronization never requires watering.

## Acceptance boundary

The gateway persists an `idle_anchor` reservation before transmission. Its short
response window accepts only the matching association, counter marker, ordinary
trailer, and qualified idle-anchor response. The exact captured result-3 body is
valid only inside this reservation. It authenticates the counter without claiming
that physical state changed. Result 3 remains an error for ordinary commands.
Reports, session summaries, and their ACK sequences never seed the command counter.

A missing or late reply keeps the counter unknown. Each retry requires another
fresh owner idle report, within the original window and a total three-attempt
budget. Restart preserves reservations and attempt counts without retransmitting
a previously sent anchor. New watering evidence invalidates an idle attempt.

## Verify one recovery

1. Confirm the associated owner is connected and the valve is independently idle.
2. Request the normal Sync counter operation and retain its transaction and event IDs.
3. Record the owner report, anchor transmission, matched response, and resulting readiness.
4. If authorized on dry hardware, independently verify one bounded open and automatic
   stop, then a separate early-close trial with required command spacing.
5. Preserve timeout, rejection, and interruption evidence alongside successes.

[Recovery and rollover fixtures](fixtures/htv145_idle_result3_counter_recovery_20260906.json)
retain both protocol exchanges and runtime verification. [Restart evidence](fixtures/htv145_restart_recovery_20260906.json)
and [standard-firmware control evidence](fixtures/htv145_standard_firmware_control_20260906.json)
cover operational continuation. These are radio/gateway records; they do not
substitute for an independent ACK waveform capture.

Arbitrary phase overrides and assumed-open probes are retired. Use the supported
sync API. Open qualification work belongs in the [roadmap](../PROJECT_ROADMAP.md).
