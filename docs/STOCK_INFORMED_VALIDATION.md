# Stock-informed changes: short validation procedure

Source/test work completed September 27; **not deployed**. This procedure is
not another backlog: record acceptance in [PROJECT_ROADMAP.md](../PROJECT_ROADMAP.md).
Implementation and offline evidence: [improvement plan](../research/STOCK_FIRMWARE_IMPROVEMENT_PLAN.md).

## Goal and time budget

Use the idle OTA test node and spare devices first. Aim for one 10–15-minute
assisted session, then unattended observation. No extra garden watering, mass
re-pairing, battery cycling or new 72-hour gate. If no spare dry valve is
available, defer its RF tests instead of disturbing the installed irrigation.

Passing means the relevant device responses were observed—not merely a socket
write, radio transmission or white LED. Offline tests already cover malformed
packets, wrong-phase replies, lost delivery, stale sessions and restarts; there
is no need to reproduce every fault manually.

## Before asking the user to test

After separate deployment approval, the agent should:

- Review the source diff separately from the unrelated PCB work; retain the
  current gateway database/configuration backup and known-good signed image.
- Coordinate gateway/integration and idle-node versions. New firmware rejects
  old field-less known-sensor recovery requests; new ownership operations need
  correlated-capability nodes. Do not attempt an owner transfer through an
  incompatible production node. Leave garden radios and associations unchanged.
- Verify the idle node's version, connection and new capabilities; confirm
  normal garden telemetry continues. Install a test image through the existing
  signed release process, not a signing bypass.
- Prepare timestamped packet/status logging and, if available, passive SDR
  capture before inviting the user. Do not delay the session to require an SDR
  unless an actual failure needs waveform evidence.

## One short assisted session

| Test | User action | Agent checks / pass condition |
| --- | --- | --- |
| Dry single-zone pairing | Confirm the spare valve is dry, then long-press once **after** the agent confirms an armed five-minute window. | Proven prefix unchanged; record actual native requests/replies. If plan retries occur, each answered phase is echoed, retry count is bounded, and logical progress stays at 5 until terminal arrives. |
| Dry control | No additional action unless physical confirmation is needed. | With separate command approval, run 60 seconds and observe matching OPEN, decreasing remaining time and observed automatic idle. Sample an odd remaining-second value when available. Optionally run once more and close after at least 15 seconds to check explicit CLOSE. |
| Spare moisture sensor | One short press if already paired to the test owner; otherwise one approved long-press pairing. | Correct retained identity/channel and exactly the authorized owner respond; measurement freshness advances only with a new measurement. No duplicate HA device. |

Do not infer terminal acceptance from the first white flash. Record initial
association, addressed telemetry, terminal exchange and successful control as
separate outcomes. A captured next-stage request demonstrates acceptance of the
preceding reply; sending the final response alone does not prove its acceptance.
If no retries occur, unchanged pairing is validated, but physical retry recovery
remains unexercised. Do not deliberately interfere with RF just to force it.

If the pairing attempt fails, inspect its trace first. At most one immediate
repeat, only when it answers a specific question; do not start another long
series of timing tweaks. A user-assisted factory reset is a separate decision.

## Agent-only checks after the session

Keep raw attempt timestamps, full six-bit phases and device replies for the
ordinary dry command. Separate radio enqueue failure, missing reply, matched
negative reply and confirmed state; none is interchangeable. The stock
[retry trace](../research/STOCK_HUB_ACK_RETRY_LIFECYCLE.md) does not justify
adding attempts or changing counters in this session. Counting visible control
commands alone cannot reconstruct the stock global generator.

With the same approved canary scope, restart the gateway/add-on and reconnect
the **idle** test node while its valve is idle. Check association/counter and
ACK-authorization restoration; use one additional approved dry short command
only if needed to establish post-restart control. This is not a valve battery
rejoin test, nor proof of recovery after sensor firmware stops transmitting.

For ownership cleanup, use a disposable spare association on capable idle
nodes. Delete or explicitly transfer it and verify matched revoke precedes any
grant, the HA diagnostic reaches `ready`, and restart does not resurrect the
old assignment. If a second idle node is unavailable, defer live transfer;
offline failure/restart tests already cover the state machine. Do not transfer
the garden devices merely to complete this test. Pairing-time cross-node grants
are a separate unresolved qualification, not covered by this explicit transfer.

Selector 5 needs a device already retaining selector 5 to qualify that recovery
path. An ordinary new selector-4 pairing cannot substitute for it; do not force
a channel migration for this session. If a spare remains silent, inspect RF
first and ask for one short press later—no claim of an implemented remote wake.
Classify the observed result as ordinary report, known connection announcement,
or no packet observed; check reception/capture coverage before calling the last
case sensor silence. The stock HCS026 expiry path does not supply a demonstrated
wake command. Sensor-board inspection is optional research, not a prerequisite
for this short canary session.

## Promotion and stop conditions

Promote garden radios only after canary results and rollout approval. Avoid the
scheduled watering window. Observe the next already-planned irrigation for a
matched command response, correct duration, final idle and normal notifications;
do not add water solely for qualification. Recheck normal sensor reporting
against each sensor's established cadence.

Stop on changed prefix behavior, unexpected actuation, lost production
telemetry, duplicate ownership, unresolved cleanup or mismatched response
acceptance. Preserve logs and restore the tested compatible release set where
safe. Never downgrade across a pending ownership journal: resolve it or review
the recovery path first.

Stock result-9 acceptance, silent-device wake, battery rejoin, RF channel
migration and the cause of historical overnight counter resets remain separate
roadmap items. They are not prerequisites for gathering this small canary result
and are not claimed solved by it.
