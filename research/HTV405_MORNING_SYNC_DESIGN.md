# HTV405 morning synchronization

The gateway synchronizes during a configurable local-calendar window and retains
one association-wide command counter for direct daytime commands. Zone selection
does not select a different counter. Telemetry and ACK sequences are independent.
Wire rules are in the [device reference](../protocol_documentation/htv405frf.md).

## Runtime behavior

| Situation | Behavior |
|---|---|
| Enabled morning window, known idle valve, owner online | Queue one fixed-zero close at the next fresh owner link report. |
| Matched idle response | Persist readiness, association, owner, counter and confirmation time. |
| Ready daytime request | Reserve the retained counter and send one bounded open immediately. |
| Positive open response | Advance the shared counter and observe the bounded run. |
| Positive close response | Retain the accepted counter. |
| Missing open response | Keep the run unresolved and clear readiness; never replay a logical open as recovery. |
| Missed or failed sync | Show the reason and permit explicit Sync now recovery. |
| Watering, uncertain state or pending command | Do not perform maintenance. |
| Restart | Restore durable state without speculative RF replay. |

A fresh link report provides a transmit opportunity; it does not establish idle
state. Any independent watering observation invalidates the idle authorization.
The radio and gateway enforce the original deadline and command spacing.
A successful zero-anchor idle reply may name the last watered zone. That narrow
exception requires the matching association, counter zero, valid zone and idle
state; ordinary command responses must still match the requested zone.

Morning scheduling is owned by the gateway, not a Codex monitor. Choose a window
long enough to include a normal report interval and command-spacing margin.
No daily watering or RF keepalive is introduced by synchronization.

## Counter retention and receive reachability

An accepted counter and a reachable valve are different facts. A timeout alone
cannot distinguish counter rejection, a sleeping receiver, interference, a missed
reply or a received command. Never infer counter advancement from silence.

The [overnight corpus](fixtures/htv405_overnight_counter_drift_20260902.json) has
21.93 hours between the last accepted command and first timeout, but also 33
owner connection events, an uptime-confirmed reboot and three aggregate ACK
failures without individual timestamps. This evidence cannot identify an expiry
period or isolate elapsed time as the cause. The [morning smoke exchange](fixtures/htv405_morning_sync_smoke_20260905.json)
proves an anchor followed by immediate direct control, not hours-long retention.

## Controlled retention procedure

1. Record one authenticated counter, owner connection epoch, uptime and ACK baseline.
2. Keep the owner and gateway stable. Record every ACK outcome and intervening command.
3. At an authorized checkpoint, send only the currently authenticated counter
   with a bounded duration. Require a positive reply and independent automatic idle.
4. Label intervals containing a command, reboot, ownership change or missing
   observations as interrupted; do not treat them as clean idle holds.
5. Stop on a failed open. Recover separately at the next qualified idle opportunity;
   never sweep open counters or replay missed checkpoints.
6. Compare stock maintenance traffic only with a separately authorized capture.

The [roadmap](../PROJECT_ROADMAP.md) owns physical qualification gates. The current
72-hour collector is passive and cannot substitute for authorized retention probes.
