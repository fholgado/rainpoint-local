# HTV405 morning synchronization and immediate daytime commands

Implemented behind a disabled-by-default per-valve setting in gateway 0.34.1,
integration 0.14.0, and firmware 0.15.10. Physical acceptance is pending. Completion gates
live in [PROJECT_ROADMAP.md](../PROJECT_ROADMAP.md).

Move the existing non-actuating close-0 synchronization into a bounded morning
maintenance window. After a valve-confirmed idle response, retain the accepted
counter and send subsequent user commands directly. A user should not routinely
wait for a 15-minute valve report and another 15-second command interval before
watering starts.

The distinction is counter continuity versus radio reachability. September 2
dry testing established that all 32 close counters can become the next counter,
and that open advances it while close retains it. September 3 established that
two off-report close-0 attempts received no response, whereas the same anchor
at the next report succeeded. The default control path therefore waits for a
report before every synchronized open. Morning synchronization moves that wait
out of the normal user interaction, but does not prove that an hours-idle valve
will receive a daytime command. The latter must be measured independently.

Evidence: [protocol status](VALVE_PROTOCOL_STATUS.md),
[overnight drift fixture](fixtures/htv405_overnight_counter_drift_20260902.json),
and the physical synchronization gates in the roadmap. The HTV145 discovery of
a truncated command wake is an additional reason to measure HTV405 wake length
and repetition directly instead of calling every silence a counter failure.

## Proposed behavior

| Situation | Behavior |
| --- | --- |
| Morning window, known idle valve, owner online | Queue one close-0 anchor at the next report, using the existing owner-node mechanism. |
| Matching idle response | Persist readiness, association revision, owner, next counter, and actual transmission/confirmation times. Do not open anything. |
| Daytime request, ready, no unresolved command | Reserve the retained counter and dispatch one duration-bounded open immediately through the existing coordinator. |
| Confirmed open | Advance the counter from the matching response, record expected automatic completion, and observe valve state. |
| Confirmed early close | Retain its confirmed counter for the next open. Keep the 15-second hardware interval. |
| No response after an open | Keep the run unresolved, clear readiness, and never issue a new logical open as recovery. Continue observing the bounded run. |
| Morning sync missed or failed | Show “Needs sync” and the cause. Offer the existing cancellable report-waiting recovery as an explicit fallback. |
| Already watering, unknown physical state, pending command, or competing RF controller | Skip maintenance; never use a scheduled close as permission to interrupt an active run. |
| Gateway restart | Restore observations and reservations without RF replay. Reconcile readiness/ownership before accepting new work. |

The morning window should be configurable in local time and begin at least one
full observed report interval plus the command-spacing margin before the first
scheduled watering. An initial dry-test example is a 30-minute window, beginning
45 minutes before the first planned run; choose actual times with the operator.
Do not silently introduce an extra daily watering or an all-day radio keepalive.

## Coordination and persistence

The gateway owns the maintenance decision and the durable counter; HA displays
it and requests watering. Use one transaction lock per valve for both scheduled
maintenance and user commands. Reuse the current report-triggered anchor and
timeout behavior rather than creating a second RF sender. A user request racing
maintenance either uses its completed result or sees the existing cancellable
wait; it cannot reserve a second command concurrently.

Store the local service date, scheduled window, association revision, owner node,
last successful sync time, confirmed counter, and readiness reason. A unique
service-date/association key prevents duplicate maintenance after reload or a
daylight-saving clock change. A delayed scheduler may act only inside the window;
it must not replay a missed morning close at an arbitrary later startup. A node
reassignment revokes the old transmitter before installing the new owner.

Do not equate “synced today” with unconditional permission. Pairing or route
changes, observed stock control traffic, an unacknowledged local transmission,
and unresolved watering invalidate readiness. Keep the existing idle/state and
command-spacing safety gates. A plain report sequence never replaces the command
counter. Decide the readiness lifetime from the daytime experiment, rather than
inventing a counter expiry merely because a report is old.

HA can expose “Ready”, “Syncing”, “Watering”, or “Needs sync”, alongside last
successful sync and the command's existing transaction status. The normal Run Now
action should dispatch immediately when ready. Failure should be explicit; avoid
hiding another long wait behind a second press or an automatic open retry.

## Experiment that decides whether this works

On the isolated dry HTV405, perform one morning report-triggered close-0 sync,
then test the exact retained next counter at approximately 1, 4, 8, and 12 hours.
Keep the gateway and owner node continuously running, the stock gateway off, and
routine ACK behavior unchanged. Deliberately place requests away from the next
report boundary. Each accepted bounded run must finish with independent idle
evidence before the next test; log manual-button activity as a separate variable.

For each request record click-to-first-RF latency, click-to-matching-response
latency, time since the last report, payload, actual RF carrier/wake/repeat
timings, owner reboot/connection/ACK history, and valve-owned automatic stop.
The initial user-experience target is RF dispatch within one second when no
hardware-spacing delay applies, and a matching response within the existing
bounded response window. No test may create a second logical open to turn a
timeout into apparent success.

A silence does not diagnose counter drift. First verify the command on SDR and
compare the same counter/payload at the next report opportunity. If it works only
near a report, investigate receiver wake timing or a missing stock maintenance
exchange. If daytime delivery is reliable with the retained counter, qualify
the implemented direct-open path and morning scheduling, then
run several complete dry days including restart, DST, concurrent-click, missed
morning-window, and active-run-at-maintenance cases before enabling it for garden
watering. Rollback is the existing explicit per-request synchronized transaction.

This design intentionally does not add speculative periodic opens or active-run
maintenance closes. If a single daily sync cannot sustain daytime reachability,
the next design decision requires the stock idle/command capture evidence; it is
not automatically a reason to increase maintenance transmission frequency.
