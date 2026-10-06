# Stock-informed changes: short validation procedure

The original procedure describes the September 29 source checkpoint; dated
sections retain later deployments and trial evidence. Current acceptance is
in [PROJECT_ROADMAP.md](../PROJECT_ROADMAP.md), not another backlog here.
Implementation and offline evidence: [improvement plan](../research/STOCK_FIRMWARE_IMPROVEMENT_PLAN.md).

## Next valve session: keep the questions separate

The shared configuration responder now reproduces the captured native reply
bodies for all three valves, including two-zone battery rejoin. It is an offline
firmware module, **not an enabled local HTV213 pairing path or automatic valve
rejoin service**. Durable recovery settings/progress and authenticated-owner
checks are now connected to gateway observations. The source-only command seam
is tested with a fake transport; no production profile enables it and no node
handler advertises its capability. Explicit configuration population and
model-specific radio handlers/qualification remain. The proven one-/four-zone
prefix is unchanged.

The retained HTV213 `81` body builder now uses a saved device address (not zone
count), saved routine selector/revision/timing, and current native-format time.
The assignment reply selector comes from the announcement, not the saved routine
selector. This body evidence does not qualify an HTV145/HTV405 RF profile.
See the [primary trace](../research/STOCK_HUB_ASSOCIATION_PERSISTENCE.md).

For the next 10–15-minute session, begin with the already implemented single-zone
retry/full-phase fixes on the idle OTA node after rollout approval. Ask before
arming, verify the node's armed response, then give the user five minutes for
one long press. Freeze the successful prefix; classify association, per-port
configuration requests, terminal response and control separately. If authorized,
one dry 60-second run must show matching valve acknowledgement, countdown and
automatic idle. Do not disturb either installed garden valve.

Keep the dry two-zone valve stock-paired as the reference for now. Its stock
hub-restart and battery-rejoin captures are already complete; repeating those
alone will not prove notification causality. A later isolated `20` kind-1 trial
needs a tested transport and explicit bounded-command authorization. Compare
otherwise identical notification/no-notification conditions, retain the entire
exchange and actual phases, and require valve responses. Never reset a persisted
master counter merely because device reports restarted or wrapped.

Once local retained recovery is connected, its separate acceptance trial is:
idle dry valve → battery removal/reinsertion without HA pairing mode → same
association/selector/revision → addressed state/settings/plan progress → one
authorized short command and automatic idle. Save the master phase before and
after; a report/ACK must not reseed it. A white flash or sent final reply alone
does not pass this trial. Status remains in the roadmap, not this procedure.

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
- Prepare the [offline trace analyzer](../research/PAIRING_TRACE_ANALYZER.md)
  for existing logs. Record report flags, advertised configuration revision,
  per-port reads and `20/A0` notifications separately from command phases.
  Missing capture coverage must remain explicit; no extra user action needed.

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
Configuration revision 1/2 is not command phase 1/2. Stock configuration arrival
is asynchronous, so do not change the proven delayed reply timing merely to
imitate an inferred cloud event. Hub parameter-download completion, durable
association storage, RF reply and successful control are separate observations.
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

## Sep 29 adoption compatibility gate

The new test radio used `0.19.0-stock-research` while the live gateway was
`0.39.0`. TLS reached the application challenge, but the old gateway rejected
the hello's `correlated_ack_ownership` and `retained_sensor_rejoin_channel`
capabilities. The native HA flow consequently expired before adoption.
An offline differential check held identity, HMAC proof and other fields fixed:
either new capability caused old-source rejection and matched-source acceptance.
Weak Wi-Fi was not the cause of that reproduced authentication failure.

The approved gateway-only update is `0.39.1`: runtime frozen at `adf4687`, with
new package metadata. Its package passed 664 tests (two optional skips), including
real-socket pending adoption with both the existing and full research hello.
An initial packaging test run lacked canonical replay fixtures; after restoring
test fixture access and correcting release metadata, the complete run passed.
HA configuration, gateway data/image and deployed source were backed up first.
Integration/UI files, garden radio firmware and unfinished valve-recovery code
are excluded. Authentication validation is retained, not relaxed generically.

Deployment completed Sep 29 at approximately 20:28 UTC. Both garden nodes
reauthenticated on unchanged firmware `0.19.0`, with healthy radios and ACK
ownership `ready`. Front Yard confirmed two sensor assignments; Vegetable
Garden confirmed four sensors and one HTV405 assignment. No irrigation or
pairing commands were issued. Fresh native adoption succeeded at 20:31:58 UTC
after the user repeated setup. By 20:33 UTC the research node passed all read-only
acceptance checks: authenticated/managed v2 connection, fresh heartbeat, 196,120
bytes free heap, valid CC1101 configuration, 14 received packets with zero FIFO
overflows, and one accepted device frame also heard by a production receiver.
Wi-Fi RSSI was -81 dBm: connectivity is confirmed, but placement remains marginal.
The node had no ACK assignments and its pairing transmitter remained disarmed.

A failed attempt leaves the new node holding an expired temporary credential.
Do not treat that as a fresh network failure or reuse the expired credential:
retry native adoption with a new physical confirmation after the gateway update.
No watering or valve pairing is authorized by this adoption check.

## Sep 29 HTV213 candidate deployment

Gateway `0.39.2` is deployed with only the HTV213 pairing delta over the
previously deployed `adf4687` runtime. The frozen package passed 682 tests
(two optional skips); all 43 deployed source hashes matched its manifest.
HA configuration, gateway data/image and app source were backed up before the
update. Unfinished valve-recovery code, integration/UI changes and garden-radio
firmware are excluded. Both garden nodes reauthenticated on `0.19.0` with their
existing ACK assignments restored and ownership `ready`.

The test-node USB link completed a small settings/layout read but failed longer
streaming reads, including a 64-KiB-chunk trial. No cause was established. The
user explicitly waived further node backups; application-only flashing uses
115200 baud and verification, without overwriting provisioning or partition
data. This does not establish general USB-link reliability.

Test Node B now runs `0.19.0-htv213-pairing.1`; the 1,107,984-byte application
write passed device hash verification. Candidate SHA-256:
`a61f2fcb05add4b5b739935bcc45daf98dcb1a989b69ad320bef7381de0d8400`.
Post-flash checks confirmed the experimental capability, authenticated/managed
connection, preserved adoption, valid CC1101 configuration, eight received
packets with zero overflows, no ACK assignments and `tx_armed: false`.
All read-only node acceptance checks passed. Wi-Fi remained marginal at -80 dBm.
No pairing or watering command was issued. The user confirmed a dry valve and
connected SDR, but the stock gateway was still on; unplug it and obtain explicit
arming readiness before the first trial.

The first authorized arm request exposed an ingress-filter omission in
`pairing.1`: the gateway accepted the request, but `WifiTransport` did not admit
`htv213_pairing_start` or `htv213_pairing_cancel` into the firmware command
queue. The node remained connected; gateway status stayed `requested`, with no
authoritative `armed` acknowledgement. The user was told not to press the valve.
This is not evidence of a failed RF association.

A regression compiles the actual firmware ingress predicate in both default
and experimental modes. It failed before the correction and passed afterward,
checking start/cancel admission, authentication, unknown commands and default
build exclusion. All 41 targeted protocol/gateway/boundary tests passed.
`0.19.0-htv213-pairing.2` adds only the missing experimental ingress entries;
no RF timings, packet shapes or sequence changes. Candidate SHA-256:
`f98689ce9b7a87d6f282a624c475a3131fb4263c412f9fe97495cf4b2f0426d4`.
No automatic retry of arming is permitted after the correction; obtain fresh
user readiness. The six-minute receive-only recording is private under
`captures/htv213-local-pairing-20260929/20260929-172500/`.

The correction's first USB write at 115200 baud was interrupted. A bounded
retry at 57600 baud completed and verified the application hash; the node
reconnected authenticated on `0.19.0-htv213-pairing.2` with TX disarmed and all
read-only acceptance checks passing. Cancellation of the exact old request
received a correlated rejection (expected: no matching session after reboot),
demonstrating that the repaired inbound command path reaches the node handler
and returns status. It did not arm or transmit RF. Fresh arming remains an
assisted next step, not a completed pairing qualification.

The receive-only capture completed at 1,440,000,000 bytes with SHA-256
`596ba55f82b96fa3a9adf92ab02df15790a6852c8e215e7123df537462b5c8e8`.

## Sep 29 repeat-announcement rejection

The next five-minute trial had an authoritative node `armed` acknowledgement.
Private capture `htv213-local-pairing-20260929/20260929-210852` contains the
exact target's native `01` requests at 58.546901, 64.607767 and 70.510250 seconds
on the lower sweep leg (phases 1, 4, 7); phases 2, 5, 8 were also decoded on
the upper leg. The body was `0b ff 20 05 01 04 3e 07`, not the original
`0c ff 20 05 01 04 3e 05`. Node status recorded zero replies and reports.
Cancellation was acknowledged with TX disarmed. The 1,440,000,000-byte capture
has SHA-256 `dbb71395557415343e94b52bcda041460e776e73c8ba26e6280f3ab2e8587ae1`.

Offline replay through the real C++ session deterministically rejected this
request. Accepting the exact second body fixes that software rejection;
changing only either differing byte does not match either observed shape.
Redacted regression tests cover all 64 phases, byte-identical assignment and
later continuation, unrelated routes, malformed bodies, unobserved variants
and retained rejoin ending `03`. No universal meaning is assigned to `07`.
This proves a software blocker, not that every SDR-decoded frame reached the
node, or that a subsequent physical reply will be accepted by the valve.

Candidate `0.19.0-htv213-pairing.3` changes only announcement admission; carrier,
reply delay, power, response body and later states remain unchanged.
Its SHA-256 is `04c5567be2ce594d7065b0e7a2741c78b847c879b0b304284a156060dfdd7164`.
RF acceptance still requires an explicitly authorized fresh pairing window.

Validation: the original private capture replay now passes; 26 focused tests
and the final full 765-test suite pass (two optional skips), as does the native
protocol test. Canary and normal builds succeed; the normal image passes the
experimental-command exclusion check. The new test initially used a legacy-CRC
mutation as an expected native-CRC reply; its oracle was corrected to compare
the original and repeat paths byte-for-byte at each phase, with decoded
assignment data and phase also checked. No transmitter CRC code was changed.

The initial deployment did not complete: the application-only write stopped at the
first reported 2% at 57600 baud; one recovery attempt at 38400 baud also
reported that the chip stopped responding. Neither image write was verified.
The application may be incomplete; do not treat the node as ready or re-arm it.
Both attempts targeted only `0x10000`, preserving provisioning and partitions.
The user was asked to reconnect USB before another recovery attempt. No cause
has been established for the serial failures; lower baud did not resolve them.

After the user reconnected USB, one 57600-baud recovery write completed:
1,108,096 application bytes at `0x10000`, with the device hash verified. The
node rebooted and reauthenticated on `0.19.0-htv213-pairing.3`; all read-only
acceptance checks passed, radio configuration was valid and TX was disarmed.
Provisioning survived and no sensor or four-zone ACK assignments were present.
Wi-Fi remained marginal at -85 dBm. USB reconnection preceded success but does
not establish the cause of earlier serial failures. No new arming or valve
command was sent; physical pairing acceptance remains unqualified.

## Sep 29 pairing.3 on-air trial

The explicitly authorized trial was genuinely armed. Node status recorded
three replies and zero addressed reports; cancellation was acknowledged with
TX disarmed. Private IQ `htv213-local-pairing-20260929/20260929-214707` completed
at 1,440,000,000 bytes with SHA-256
`5d12955ebbc403d4a945f7e09cdd40525ac490fd0597e9769ecc43e34704ade0`.

SDR recovered target `01` announcements `0b ff 20 05 01 04 3e 07` and matching
native `81` replies at phases 1, 4 and 7. Replies had normalized integrity
residue `c713`, assignment prefix `0a 02 0b e0 01`, and 320-symbol wakes.
Request-to-reply sync gaps were 81.627, 80.448 and 81.511 ms. This confirms the
admission correction and real transmissions, not valve acceptance or a fully
validated physical CRC tail. The valve continued its announcement sweep.

An offline replay through the actual C++ Session reproduces a second blocker:
the request advertises selector 11 but the profile still chooses 434351500 Hz,
the selector-12 initial reply carrier. The stock handler uses incoming selector
for the reply transport, separately from the returned assignment; selector 11
maps to nominal 434241500 Hz. See the [stock transport trace](../research/STOCK_HUB_ASSOCIATION_PERSISTENCE.md#reply-carrier-is-distinct-from-the-returned-assignment).

There is also an unresolved configured-versus-measured carrier offset. Bounded
8-ms wake FFTs yielded local centers 434306000, 434306125 and 434306062.5 Hz
(about 45.5 kHz below the configured value), with about 79.75 kHz tone spacing
and no ADC-rail samples in those windows. The same recording's valve wake
center was 433143875 Hz, near the historical valve reference. Absolute values
are not calibrated against a frequency standard; do not assume a hardware
cause or blindly copy a global correction. The original narrow decoder
threshold missed replies; scanning 434.28/434.30/434.32 MHz recovered them.
Decoder thresholds are not carrier measurements.

No firmware or live parameter changes followed this trial. Request-derived
reply selection and the measured offset must be resolved before the next
assisted trial, while preserving the now-observed announcement admission,
reply body, phase echo and timing. Local pairing remains unqualified.

## Pairing.4 carrier correction

The native replay first failed with selector 11 choosing 434351500 Hz instead
of 434241500 Hz. The correction treats `initial_center_hz` as a selector-12
reference and subtracts 110 kHz for captured selector 11. The newly assigned
selector does not choose this first reply's carrier. Signed arithmetic and
both derived-frequency bounds are checked before arming; unknown request
selectors remain rejected. Assignment bytes, six-bit phase echo, power,
delay, wake and subsequent state transitions are unchanged.

Tests exercise both captured requests with different assigned selectors,
calibrated references, later routine traffic and lower/upper bounds. The actual
runtime preparation block is compiled against a two-slot radio fake: both
assignment carriers are prepared, without requiring a third cache slot.
The common radio driver is unchanged. A distinct routine carrier uses its
existing on-demand calibration path; the current selector-11 routine remains
cached. The original failure replay and 30 focused tests pass. Final validation
passed 769 Python tests (two optional skips), the native protocol executable,
canary/normal builds and the normal image's experimental-command exclusion.

Three recorded wake FFT centers span only 125 Hz. An independent aggregate
phase estimator gives 434306738–434306861 Hz, within 861 Hz of the FFT centers.
Individual-sample median phase was unsuitable for this low-amplitude CU8
recording; DC removal and complex-product averaging avoid that quantization
bias. A rounded **+45500 Hz candidate correction** is therefore prepared only
in the private helper bound to Test Node B and firmware pairing.4. It supplies
434397000 Hz as the selector-12 reference and 434287000 Hz for selector 11 and
routine traffic. This is empirical compensation, not proof of an oscillator
fault, an absolute frequency calibration or qualification at every carrier.
The September 30 trial below verifies the resulting carrier and partial acceptance.
No correction is hardcoded into public firmware or applied to garden nodes.

Candidate application SHA-256:
`214e1daaab0494d0eca45f91911c6e1e04bd1b9c25f531937296b9eac6a3f120`.

The first application-only serial deployment attempt stopped responding before
verification. The node is not ready for another pairing trial until a complete
write and authenticated reboot have been verified. The user was asked to
reconnect USB, which preceded successful recovery of pairing.3. No automatic
arming, valve control, gateway deployment or garden-node update occurred.

On September 30, the user requested a USB-controlled reboot instead of another
physical reconnect. A read-only esptool connection followed by an explicit RTS
hard reset completed; the subsequent single 57600-baud application-only retry
wrote 1,108,240 bytes at `0x10000` and passed device hash verification. The
node rebooted and authenticated on `0.19.0-htv213-pairing.4`, with TX disarmed,
valid radio configuration and all read-only acceptance checks passing. Wi-Fi
was -82 dBm. No pairing or valve command was issued. This demonstrates one
successful USB-reset recovery, not a diagnosis of the intermittent flash issue.

## September 30 pairing.4: accepted assignment, incomplete configuration

The authorized dry-valve trial used the unchanged pairing.4 application and
the node-only +45500-Hz correction above. The user reported a success indication.
Private capture `htv213-local-pairing-20260929/20260930-100716` independently
shows progression beyond the factory announcements:

| Capture time (seconds) | RF evidence |
| --- | --- |
| 57.673–69.811 | Announcements at phases 1–7; assignment replies echo 1, 4 and 7 |
| 71.665 / 71.747 | Addressed port-1 `02`, phase 8, and `82` acknowledgement |
| 73.685 / 73.767 | Addressed port-2 `02`, phase 9, and `82` acknowledgement |
| 75.201 | Positive native `a0`, phase 2, result `00`, on the routine carrier |
| 76.520 / 108.676 | Further port-2 state reports at phases 10 and 11 |
| 111.653 / 113.722 / 115.633 | Port-1 settings requests `05`, phases 12–14 |

Three assignment wake FFT windows measured tone midpoints of 434241312.5 Hz,
near the intended 434241500-Hz carrier. Their request-to-reply sync delays were
81.30–81.78 ms. These windows were unclipped; the later 104-second scan chunk
had 1.12% clipping, so do not generalize recording quality or infer packet
absence from it. The SDR is not an absolute frequency reference. This is one
node/carrier acceptance result, not a fleet-wide oscillator correction.

Node status reported six replies and `reports: 3` (a both-port bitmask), but
`settings_sent: 0` and `plans_sent: 0`. The positive `a0` is an SDR observation,
not proof the node received/accepted it; the outgoing `20` was not decoded in
the inspected windows. Subsequent `05` requests demonstrate valve-side
configuration progression, not completion. The bounded session expired with
`state: failed`, `failure: 1`, `operational: false`, and TX disarmed. No watering
command or automatic re-arm was issued.

Freeze the accepted assignment/report prefix. The next investigation is the
node's configuration continuation, without changing proven assignment timing,
bytes or carrier. Full enrollment and operation remain separate roadmap gates.
The bounded capture completed at 1,440,000,000 bytes; independently recomputed
SHA-256 matches its recorder manifest:
`c50a2b092446a56de54d750efa12c0b77b8146e9d7d6d53e13ebff65ca894e28`.

## Pairing.5 receive handoff correction

The deterministic native runtime replay uses the September 30 addressed
reports, positive `a0`, and port-1 settings request with synthetic endpoints.
It compiles the actual `finishHtv213`, `processHtv213`, `pollHtv213` functions
and the actual CC1101 tuning methods against a register-level radio fake.
Before the fix, the replay failed with `Report carrier not restored after a0:
434287000`; lost and mismatched ACK cases failed the same way. This reproduces
why even later ordinary reports could no longer be acknowledged, independently
of whether the hardware received the positive `a0` during the trial.

`setReceiveFrequency` changes the synthesizer base; `setChannel(0)` changes
only its channel offset. The pairing window exit now calls
`restoreReceiveChannel(0)`, restoring the ordinary RX configuration and base.
The fix is isolated to the experimental runtime. Assignment bytes, request
carrier selection, trim, delay, wake, phases, notification and configuration
builders are unchanged. No production driver or other model was changed.

The replay now answers the captured port-1 settings request after a matching
ACK. Missing/mismatched ACKs restore report reception but still cannot unlock
settings; a receiver-restore failure terminates the session. All 31 focused
tests and the native protocol test passed. The full suite passed 770 tests
with two optional skips. Both canary and normal firmware
builds passed, and the normal image passed experimental-command exclusion.
These are source-level results, not proof of completed physical enrollment.

Candidate `0.19.0-htv213-pairing.5` application SHA-256:
`0fd169ab113ea006a66235d20b7c4fc3497bb8ae9b9e0fc3762560591ea7e17d`.

The identified Test Node B received only this 1,108,240-byte application at
`0x10000`, after a USB RTS reset, using 57600 baud. Device hash verification
passed. Read-only gateway verification confirmed pairing.5, authenticated
connection, TX disarmed, valid radio configuration and zero RX overflows.
Bootloader, provisioning, gateway software and garden nodes were untouched.
The private arm helper now requires pairing.5 but retains all proven RF
parameters. No new pairing window or watering command was issued.

## September 30 pairing.5: both-port configuration on air

The next explicitly authorized trial preserved all pairing.4 RF parameters
and used only the pairing.5 receive-handoff fix. The user again reported a
successful pairing indication. Private capture
`htv213-local-pairing-20260929/20260930-104246` establishes:

| Capture time (seconds) | RF evidence |
| --- | --- |
| 50.629–62.766 | Factory announcements, assignment replies echoing phases 1, 4 and 7 |
| 64.621 / 64.702 | Port-1 report and revision-1 ACK, phase 8 |
| 66.631 / 66.712 | Port-2 report and revision-1 ACK, phase 9 |
| 67.851 / 68.146 | Native `20`, phase 2, data `02 00`; positive `a0`, same phase |
| 69.477 / 69.558 | Port-2 report and revision-2 ACK, phase 10 |
| 72.599 / 72.680 | Port-1 settings request/reply, phase 11 |
| 74.628 / 74.710 | Port-2 settings request/reply, phase 12 |
| 76.658–78.671 | Port-1 empty-plan requests/replies, phases 13 and 14 |
| 80.590–82.669 | Port-2 empty-plan requests/replies, phases 15 and 16 |

Both settings replies contain the candidate's existing fourteen-byte defaults;
plan replies contain result `00`. The inspected exchange chunks were unclipped.
Node status independently reached `reports: 3`, `settings_sent: 3`,
`plans_sent: 3` (both-port bitmasks) and thirteen transmissions. This confirms
that the receive-handoff correction restored the previously missing response
path. It does not establish durable enrollment, final plan acceptance or control.

Thirty redacted frames are preserved in
`research/fixtures/htv213_local_pairing_20260930.json`. Endpoints are synthetic,
assignment clocks zeroed, and normalized CRCs regenerated. Native replay checks
all thirteen response commands, phases and bodies, including plan retries;
all seventeen pairing/runtime tests passed. No firmware or pairing parameters
were changed in response to this success, and no watering command was issued.

No later packet was decoded in the 92–360-second scans at the lower report
and routine carriers. This bounded observation is not proof that the valve is
unpaired or that no other carrier carried traffic. The session's stricter
post-plan-report gate was not met before its five-minute deadline, so status
ended `failed`/timeout with TX disarmed, despite the verified configuration
exchange. Do not equate that timeout with rejection of the assignment.
The recording is 1,440,000,000 bytes; its independently recomputed SHA-256
matches the recorder manifest:
`c10c44394a201bb77249a248d9fced3301b33261beb34484f69d657c842a5ff4`.

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

## HTV213 isolated control trial — September 30

Implemented a separate compile-gated control session without changing the
successful pairing.5 assignment/configuration path. The test-only gateway
adapter admits an explicit dry association on an unassigned authenticated node;
it journals each phase before dispatch and never replays an uncertain command.
Native replay covers stock 60/120-second opens, explicit early stop, result and
per-port report correlation, timeout/disconnect, and full RX-carrier restoration.

Validation and deployment:

- Full source suite: 796 tests, two optional skips; native protocol test passed.
- Exact narrow deployment package: 716 tests, two skips; 45 deployed source
  hashes matched. Gateway 0.39.3 includes only the dry-control delta over the
  deployed pairing gateway, not unfinished recovery/UI changes.
- Both firmware builds passed; the default image excludes experimental control
  commands. Test Node B alone received `0.19.0-htv213-control.1`; application
  flash hash verified, provisioning retained, authenticated and radio healthy.
- HA configuration/app backup and source rollback copy preserved before update.
  Garden radio firmware remains 0.19.0. No HA two-zone actuator was registered.

The user confirmed the valve dry and stock gateway unplugged, and authorized
one port-1 60-second command with no automatic retry. The initial phase was
explicitly 3, a candidate following the previously recorded positive phase-2
configuration notification; routine report phase 17 was not used as a seed.

Private capture `captures/htv213-local-control-20260930/20260930-113029` contains
240 seconds / 960,000,000 bytes of IQ. Its independently verified SHA-256 is
`cc0afea645752f028edcbd6e539f5a5459e6986aa70c72c71e9e36398eafc7a1`.

| Capture time | Observation |
| --- | --- |
| 15.478080 s | One native `21`, phase 3, body `01 02 01 3c 00`; stock-matching non-identity envelope and duration |
| Command window | No matching `a1` decoded by node or SDR; no automatic retry or close sent |
| 153.281068 s | Same-association port-2 `02` idle, phase 22, selector 11, zero remaining/total |

The measured command center was 434.241375 MHz, with 80-kHz tone spacing and
no clipping in the measured wake excerpt. This agrees closely with the stock
control carrier and the successful local pairing carrier. It is not full
waveform qualification: the signal was weak at the SDR (CU8 standard deviation
about 1.22), and the unfiltered decoder's longest uninterrupted wake was 1,162
symbols. The band-limited follow-up below resolves that apparent shortening.

The complete recording was scanned in overlapping bounded chunks at
433.140/434.240/434.350 MHz. A wider 433.080–434.480-MHz response-window scan
also found no valve result. Absence of a decoded frame is not proof of radio
rejection or universal silence. The late port-2 idle establishes retained local
identity after configuration and node-only flashing, but does not establish a
port-1 opening. No port-1 watering report or session summary was decoded.

The node ended `overdue` (confirmation deadline), with TX disarmed and zero
invalid network messages. The durable transaction remains `indeterminate`:
phase 3 is attempted, not reusable; a reserved next value is not synchronized
counter proof. Do not turn the late other-port idle into a successful run or
reset the command phase from its report phase.

The two-frame negative fixture is
`research/fixtures/htv213_local_control_20260930.json`: synthetic endpoints,
zeroed report clock and regenerated native CRC window. Focused control tests
(24) pass, including whole stock-command envelopes and the rule that this late
other-port report cannot complete an unacknowledged trial.

The capture rules out a missing transmission and the earlier large carrier
error; it does not yet separate wake/tail fidelity from configuration or
command-phase acceptance. Preserve the proven pairing prefix. Any subsequent
actuation or fresh pairing is a separately approved test; do not guess counters
or reset the durable trial implicitly. Current gates remain in the roadmap.

### Missing final native CRC symbol: captured defect and unflashed fix

A bounded 180-ms IQ excerpt, mixed to the measured carrier and filtered with a
129-tap 85-kHz low-pass FIR, recovers the full long wake. The apparent short wake
was a decoding/SNR limitation, not evidence that the requested wake was truncated.
The same analysis exposes a different error at the final native CRC symbol:

| Exchange | Required final native CRC bit | Recovered bit after the 304-bit normalized window |
| --- | --- | --- |
| Failed local open, phase 3 | 1 | 0 in all 88 valid decoding phases |
| Successful local notification, phase 2 | 0 | 0 in 77/88 phases; remaining edge phases noise-sensitive |
| Successful stock open, phase 3 | 0 | 0 in all 94 valid phases |
| Successful stock open, phase 4 | 1 | 1 in all 94 valid phases |

Native framing starts 33 bits into the normalized window. Its 32-byte payload
plus 16-bit CRC therefore needs 305 symbols from normalized sync, not 304.
The existing asynchronous transmitter emits only the 38-byte/304-bit window,
then drives GDO0 low before ending RF. That accidentally supplies a low final
symbol but cannot supply a required high one. This is a concrete on-air framing
defect, independent of the counter hypothesis; successful control after fixing
it is still needed to establish that it is the only blocker.

The successful local pairing also fits this pattern: assignments at phases 1
and 4 required a high final CRC bit, while the accepted phase-7 assignment
required low. Port-1 plan reply phase 13 required high and was retried at phase
14, whose final bit was low; port-2 phase 15/high was retried at phase 16/low.
This correlation is useful evidence, not permission to change the frozen pairing
path or all production radio waveforms at once.

Added an actual-RMT-construction regression: before the fix, an explicit native
tail request failed with `Expected 2705 symbols, generated 2704`; afterward both
CRC values and both polarities pass, while the default remains exactly 2704
symbols. The control runtime now computes the omitted native CRC bit and passes
it explicitly for its command and report ACKs. This optional driver argument
exists only under the HTV213 control experiment build flag. Existing pairing
callers retain the original stream; production builds compile the extension out.

At the end of the initial analysis, `0.19.0-htv213-control.2` was built but not
flashed or RF-qualified. The original open remained indeterminate, without a
reset of its journal. The subsequently authorized validation is recorded below.
Private analysis is preserved alongside the original IQ in `tail-analysis.jsonl`.
Final validation after the tail correction: 798 Python tests passed with two
optional skips, native protocol tests passed, control.2 and default firmware
compiled, and the default image passed experimental-command exclusion checks.

### Sep 30: corrected-CRC port-1 control succeeds

With separate user approval, flashed control.2 to Test Node B only; application
hash verified and authenticated reconnect confirmed. The valve was dry, the
stock gateway off. Pairing, valve power and garden firmware were unchanged.
Gateway 0.39.4 adds one explicit corrected-CRC experimental retry admission:
same association, port, duration and attempted phase; capture digest and user
authorization reference required. The original journal transaction remains in
history, its existing next-phase reservation is unchanged, and the new attempt
has its own command ID and exclusive private marker. It cannot automatically
retry, retry a confirmed open, or recursively retry itself. This is not a
production counter-recovery policy.

The retry helper verified the entire original command profile before dispatch.
Private capture `captures/htv213-local-control-20260930/20260930-121301` records
one native `21`, phase 3, port 1, 60 seconds, followed by:

| Seconds after command sync | Valve evidence |
| --- | --- |
| 0.309 | Positive `a1`, matching phase 3, requested 60, remaining 61 |
| 6.901 | Port-1 watering report, remaining 55, requested 60 |
| 42.902 | Port-1 watering report, remaining 19, requested 60 |
| 62.941 | Port-1 idle, remaining and requested fields zero |
| 63.940 | Port-1 `04` summary, elapsed 60 |

Reports and summary received phase-echo ACKs. No explicit close or additional
open was sent. The firmware and durable gateway journal both reached complete;
the node was disarmed afterward. This is RF-reported actuation/completion, not
a water-flow measurement or proof of exact motor timing.

The 240-second capture is 960,000,000 bytes; independently verified SHA-256:
`89b9f1ecc996e57ff56334af0f0652ff33f2ca2825f71ca110914f6f492c0d35`.
After the bounded trial ended, alternating port-1/port-2 idle reports continued
at capture seconds 121–221 (phases 31–36). They were not ACKed because the
experimental owner had deliberately stopped transmitting. This is not a
qualified long-lived ACK owner or retained-availability soak; operational
promotion must provide explicit routine-report ownership.

Independent bounded IQ analysis recovered the required high final CRC symbol in
87/87 valid decoder phases, versus low in 88/88 phases of the failed control.1
command. The normalized command bytes and phase were identical between trials.
This validates the corrected command path and strongly supports the omitted CRC
bit as the prior acceptance blocker; no counter guessing or valve re-pairing was
needed. Phase 4 is reserved next, but sequential command acceptance still needs
a separate live trial. Port-2 control and explicit stop are not yet qualified.

Redacted ten-frame replay:
`research/fixtures/htv213_local_control_crc_corrected_20260930.json`.
Endpoints are synthetic, wall-clock bytes zeroed and native CRCs regenerated.
The original negative fixture remains unchanged. Replay covers the real native
state machine and the audited journal retry/completion path.

Before deployment: 801 full-suite tests and 720 exact-staged-package tests passed
(two optional skips in each); native protocol test passed. After adding the
successful local capture, all 31 focused control/journal/runtime tests passed.
The narrow deployment changed only the two experimental journal/admission
modules plus version/changelog; unfinished recovery and UI work was excluded.

## HTV213 second outlet, explicit stop and routine ownership — September 30

With the valve dry and stock hub off, control.2 accepted the next master
commands without re-pairing or counter guessing:

| Trial | RF evidence relative to open-command sync |
| --- | --- |
| Port 2, phase 4, 60 seconds | `a1` +0.309 s; countdown reports; idle +61.517 s; elapsed-60 summary +67.497 s |
| Port 1, phase 5, 120-second request | `a1` +0.309 s; explicit phase-6 close +26.619 s; close `a1` +26.928 s; idle +33.418 s; summary +38.379 s |

Each run was sent once. The early stop was sent once after confirmed opening;
no automatic retry or speculative close was used. The durable journal retained
both completions and reserved phase 7 next. Redacted replay is in
`research/fixtures/htv213_local_outlet_stop_20260930.json`.

Private raw capture integrity:

- `20260930-124845`: 720,000,000 bytes;
  SHA-256 `42e25c0c857fb4da46ba5c8de337fd2ead12c0cbf558dffd2e0a3f6cb25b788d`.
- `20260930-125211`: 960,000,000 bytes;
  SHA-256 `f6fdf9d7504d78c3ea52ea2d43298fd105bcc057e516a030462f7b3310ec9ee8`.

Gateway 0.39.5 and Test Node B control.3 then added an isolated retained reply
owner. Configuration is persisted before sending to the authenticated radio;
reconnect restores replies only, never a watering command or a counter reset.
Battery-rejoin replies remain disabled. The first USB transfer stopped at 88%;
serial identity still responded, and one identical retry completed with a
verified flash hash. No protocol parameters were changed for that retry.

Receive-only capture `20260930-131850` independently decodes port-2 report phase
36 and port-1 phase 37 with matching `82` replies, approximately 81 ms after
report sync. Subsequent reports continued for both ports outside an active
watering trial. This qualifies routine reply transmission, not an overnight
retention or battery-change test. Before deployment, 808 source tests and 727
exact-package tests passed (two optional skips each), plus the native protocol
test and default/canary builds. Default firmware excluded the experimental
owner/controls.

### September 30: UI canary staged; radio upload recovered

Gateway 0.39.6 was deployed as a narrow package, excluding unfinished recovery
changes. Its restart restored the existing reply-owner configuration without
opening a valve or resetting the command journal. Integration 0.18.4.dev1 was
deployed as a narrow delta preserving the existing live UI; HA configuration
validation and restart succeeded. This is not the complete canonical 0.18.4
integration artifact. The local two-outlet device has not yet been published.

The control.4 test-radio image built successfully, but USB transfers failed
before verification: compressed transfer at 2%, ROM/uncompressed near 99%,
then compressed transfer at 9% after a user-performed USB power cycle. Chip
identity checks succeeded, including after that power cycle. Automatic download
reset was used each time. These failures do not establish a firmware defect or
prove a cable fault; the next hardware isolation is another data cable/direct
USB port. Do not treat the partially written application as installed or healthy.
No new valve command was sent during these upload attempts. The bounded
600-second receive-only capture `20260930-133613` completed and is preserved.

The reconnect inspection also exposed an HA projection bug: real nodes can
report `htv213_control: null` after reconnect. A regression reproduced the
`AttributeError`; the source now treats missing in-memory trial status as empty
while retaining the durable journal. All 11 owner/device tests passed. This
small follow-up is not yet deployed; finish it before publishing the HA device.

At the user's subsequent retry request, the same control.4 image uploaded at
57,600 baud with the compressed RAM-stub path. All 1,115,472 bytes were written,
the flash hash verified, and automatic reset completed. The gateway confirmed
authenticated firmware `0.19.0-htv213-control.4`, restored reply ownership and a
new 30-second heartbeat with valid radio configuration, ten received packets,
zero overflows and zero invalid messages. Application SHA-256:
`4fb180adfa2aaeb34b5d3356b14aeeeab6e8885fc8c570edb27a3082ac5bc89d`.
No cable change was confirmed, so this recovery does not establish the cause of
the earlier failures or qualify USB reliability. Both valve reports were still
pre-restart cached observations; post-restart valve traffic and HA publication
remain unqualified. No valve command was sent. The full source regression suite
including the null-status fix passed: 817 tests, two optional skips.

Gateway 0.39.7 subsequently deployed that null-status fix over the exact live
0.39.6 package; 736 exact-package tests passed with two optional skips, and 27
distribution/boundary tests passed. A small source rollback archive was saved
before update; no production radio firmware changed. Receive-only capture
`20260930-141420` records the first observed post-radio-restart port-1 idle
report at 18:16:42 UTC, phase 56. Independent IQ decode recovered its `82`
reply approximately 80.6 ms after report sync. The gateway's later update also
restored the saved reply-owner configuration without an open or counter reset.
Port-2 freshness and the HA-driven extended-duration trial remain pending.

### September 30: restored two-outlet HA control qualified on dry hardware

Port 2 subsequently reported idle at 18:24:02 UTC, phase 57. Its report and
matching `82` were recorded before the first receive-only window ended. The
qualified retained association was then published as **2-zone test valve
(local)**. HA created exactly two valve controls and two duration settings;
no third/fourth outlet or guessed battery/volume measurement was created.

| HA trial | Independently decoded RF evidence after command sync |
| --- | --- |
| Port 2, 300 seconds, phase 7 | `21` data `0202012c01`; positive `a1` +0.309 s; watering +7.004 s; idle +302.068 s; elapsed-300 summary +335.019 s |
| Port 1, 60 seconds, phase 8, after HA restart | `21` data `0102013c00`; positive `a1` +0.309 s; watering +6.500 s; idle +62.433 s; elapsed-60 summary +69.433 s |

Each open was sent once through the real HA valve service, with no retry or
explicit close. The non-target outlet stayed closed. HA disabled new opens
while pending/watering, enabled only the active outlet's close control, and
returned both outlets to closed/ready after the session summary. The durable
journal advanced to phase 9; no re-pairing or counter reset was performed.
Reported durations and arrival times are not measurements of physical flow.

The first live run exposed a notifier ordering defect: a positive command ACK
arrived while the last port report was still idle, consuming the transaction's
duration before the first watering notice. A three-model regression reproduced
it. The fix consumes that transaction only with observed watering, preserving
manual-run stale-duration suppression and deduplication. After all valves were
confirmed closed, only `notifications.py` and the canary manifest were updated
to integration **0.18.4.dev2**, preserving unrelated live UI. HA validation and
restart passed. The subsequent 60-second run emitted its requested one-minute
duration and a stop notice; the latter was independently fetched from HA's
persistent-notification API. This is real entity/service/event verification,
not a rendered-browser inspection.

The redacted 34-frame 300-second replay exercises native control/ACK handling
and durable journal completion. Device report phases 63 then 1 were observed
and acknowledged, without changing the independent master command phase.
General command-phase wrap and battery-rejoin support remain unqualified.

Private capture integrity, independently rechecked against capture manifests:

- `20260930-141420`: 2,400,000,000 bytes;
  SHA-256 `270e6b5a3c16fd5e946c810533c89ca7989a4d73285cb72a1402561ef1743872`.
- `20260930-142451`: 1,920,000,000 bytes;
  SHA-256 `6cfc6cb13f34d53edd7c1af37c36363fc004ba642124a859729a6ad9491873f1`.
- `20260930-143827`: 960,000,000 bytes;
  SHA-256 `f547a469bf3ac9769a9e0496f112bf59b1913b13200a1861b63da6d0c2fb0c36`.

Final validation: 820 source tests passed with two optional skips, 736 tests
passed against the narrow gateway package, the staged notification module's
12 tests passed, and native protocol tests passed. Gateway 0.39.7 and test-radio
control.4 are deployed. Front Yard and Vegetable Garden radios remain on
firmware 0.19.0, authenticated with their reply ownership active; no installed
garden valve was actuated. All bounded capture/control observers finished.

### September 30: failure replay, retained-rejoin preparation and boundary probe

Missing-reply replay reproduced a stale-idle display after an attempted open.
The gateway now marks that outlet unknown until a post-command report, retaining
the other outlet's observed state. A matching ACK alone does not turn the valve
state into watering. Late genuine ACK/state/idle/summary evidence reconciles the
same transaction without another transmission or phase reservation.

A separate regression reproduced a confirmed idle being labelled overdue when
only its summary was missing. These are now different errors. Both block new
runs; a summary error preserves confirmed idle. An overdue snapshot also
triggered two HA events (generic failure plus overdue) for one problem. The
notifier now emits one overdue alert, and describes missing summaries accurately.
These are deterministic replay tests through the real gateway projection and
notification observer, **not induced RF-loss qualification on hardware**.

The prepared retained-owner responder independently replays stock battery boot
`01/81`, both-port `02/82`, `05/85` and `06/86`, without emitting a new master
notification or consuming a command phase. Its assignment carrier now derives
from the request selector rather than always using the saved routine carrier;
unsupported selectors and fresh-pairing variants are rejected. Runtime opt-in
remains false. No node firmware or proven fresh-pairing code was changed live.

The stock master-wrap audit verifies a shared hub generator and wire sequence
`1..63,0,1`. This is not the device-report counter. The user explicitly approved
at most four dry one-minute opens at phases 62, 63, 0 and 1, including the
unproven initial jump from the genuine next phase 9. The journal stores that
origin and every attempted phase; no fabricated successful seed, database
counter rewrite or alternate-phase search is used. Every step requires genuine
completion, and private once-only markers additionally require independent SDR
verification before the next command. Normal HA opens are blocked mid-probe.

Source validation passed 831 tests with two optional skips and the native C++
protocol executable. The narrow gateway package passed 749 tests with two
optional skips, then deployed as 0.39.8. HA config validation/restart passed with
notification-only integration 0.18.4.dev3. Remote source hashes match the tested
files. Source/config rollback archives were saved outside add-on discovery;
unrelated UI/recovery changes were not deployed. All HA valves reported closed
before the brief update. Test radio remains control.4; garden radios untouched.

The bounded boundary experiment subsequently completed all four approved opens:

| Phase | Positive `a1` | Target idle | Elapsed-60 summary |
| --- | --- | --- | --- |
| 62 | +0.309773 s | +62.428206 s | +69.427450 s |
| 63 | +0.309771 s | +62.529523 s | +66.480635 s |
| 0 | +0.308276 s | +63.038462 s | +73.086156 s |
| 1 | +0.309053 s | +62.635121 s | +66.682672 s |

Each phase had a decoded port-1 open, matching positive result, watering,
idle, summary and report ACKs; no retry or close was sent. Port 2 remained
closed. HA's real notification observer recorded watering/stopped and fetched
the retained stop notification. Final journal next phase is 2, with both
outlets closed/ready and the original jump history preserved. No re-pair was
needed. This is one qualified association, not universal duplicate-window or
battery-reset evidence; see the [counter audit](../research/HTV213_COUNTER_WRAP_AUDIT.md).

The 900-second receive-only capture `20260930-151121` completed at exactly
3,600,000,000 bytes; SHA-256 independently rechecked:
`496c3027d0441bbde0cd91ebaf956b1ac9539b58d4369e03e77caacfe0a0be69`.
Analysis uses overlapping bounded chunks. One phase-zero chunk had ~1.04%
clipped components; required frames still passed CRC and matched the trial.
Selected windows do not prove an absence of intervening traffic. All RF/control
and notification observers exited. The 34-frame redacted fixture is
`research/fixtures/htv213_local_counter_boundary_20260930.json`.

Normal modulo-64 allocation is enabled for completed boundary-qualified
associations only. Regression cases replay the four real exchanges, a complete
subsequent synthetic 64-phase cycle and persisted qualification after restart;
unqualified associations still stop before wrap. Late/uncertain attempts still
consume their reservation and cannot be retried automatically.

Gateway **0.39.9** deployed the qualified allocator after all ten HA valve
entities reported closed. The narrow package passed **753 tests**, and the full
source suite passed **834 tests**, each with two optional skips; native protocol
tests and diff whitespace checks also passed. Deployed journal/projection hashes
match the tested source. After the gateway restart, Test Node B authenticated,
reply ownership restored, both outlets remained closed/ready and next phase 2
survived without any command replay. Front Yard and Vegetable Garden remained
authenticated on firmware 0.19.0; the previously offline OTA-test node stayed
offline. No garden radio was flashed or installed garden valve actuated.

## HTV213 normal-control candidate — October 3

The user approved the matched gateway/Test Node B update and dry tests.
Gateway source at `4191a9c` was packaged, smoke-tested, copied with all hashes
verified and rebuilt under existing version `0.39.16`. Configuration backup
and private source archive preceded deployment. The new authenticated carrier
provisioning route accepted Test Node B's already measured carrier centers;
no RF or counter change occurred through that route.

[Development signing run](https://github.com/fholgado/rainpoint-local/actions/runs/37163677322)
produced `0.19.0-htv213-control.9`. Its publisher signature, source commit,
size and image hash were verified before OTA. Download verification correlated
with the dispatched command; the new authenticated connection reported the
candidate version and healthy confirmation. The previously recorded OTA
command-ID loss on reboot remains a limitation: the strict observer timed out
on that missing field, not on a failed update. Separate receipt verification
correlated the download, candidate boot and healthy connection. Retained owner,
battery-rejoin configuration, valve identity and next master phase **5** survived.

Both tests used ordinary `/devices/{device_id}/valve/open`, not an experiment
phase override. Exactly one 60-second open per dry port was sent, without retry
or close. The existing association supplied the RF profile and retained phase.
Independent bounded SDR decoding verified each positive full-phase `a1`, active
report, automatic idle, elapsed-60 summary and phase-echo report replies:

| Dry port / master phase | Positive ACK after open | Idle after open | Summary after open |
| --- | --- | --- | --- |
| 1 / 5 | 0.315 s | 62.333 s | 71.371 s |
| 2 / 6 | 0.315 s | 61.245 s | 98.283 s |

The later port-2 summary was observed, not assumed from elapsed time. Required
RF windows were unclipped and checksum-valid. Private evidence is under
`captures/htv213-control9-qualification-20261003/`; its complete 300-second IQ
recording was independently verified at **1,200,000,000 bytes** with matching
SHA-256. Final gateway state was both ports idle, ordinary start available,
reply owner ready and next master phase **7**. Registry and garden firmware
were unchanged; no installed garden valve command was sent.

The final full Python suite passed **1,034 tests** with no skips; installing
the private RF analysis dependency enabled the optional decoder checks. Native
C++ protocol tests and diff whitespace validation also passed.

This verifies the extracted normal control path on a retained canary, **not**
automatic identity discovery, a fresh enrollment epoch or physical packet-loss
handling. No association was revoked, re-paired or reseeded. General HA model
enablement remains pending the existing physical qualification gates in
[the roadmap](../PROJECT_ROADMAP.md).

### Reconnect recovery restoration — control.12 source

The matched gateway/radio change restores **observation**, not transmission,
from the durable unresolved-open journal. Only a current matching owner with
`htv213_idle_recovery_resume_v1` receives the prior command ID, attempted phase,
outlet and duration as fields on ordinary owner configuration. Acknowledged
commands, closes, completed transactions, unfinished boundary experiments and
changed identity/enrollment epochs do not qualify. No counter is seeded or
advanced during restoration.

The radio reconstructs an overdue, unacknowledged observation context without
building or transmitting an open. Both idle reports must arrive anew after
restoration; the existing independent gateway freshness and command-correlation
checks still govern release. Prior outcome stays unknown, and only a new user
request can reserve the next phase. This also works after a radio/OTA reboot
or loss of the gateway's in-memory transport correlation.

Regression coverage runs the actual owner command dispatcher and receive path
for reconnect, reboot and malformed context, plus the gateway restore → fresh
both-outlet reports → recovered-idle → new-next-phase request sequence. The
suite passed **1,050 tests**; the native protocol test and control.12 candidate
build passed. Real capability-handshake and firmware-boundary checks include
the new development-only capability. Live restoration and the next run remain
separate qualifications, not implied by these offline results.

### Control.10 source correction — October 4

New tests first reproduced the missing final symbol at the actual pairing
runtime's TX call sites, and premature expiry in the native session and durable
gateway journal. Pairing now appends the same computed CRC symbol used by
qualified HTV213 controls, including the configuration notification. Both
pairing-only and control builds exercise the actual RMT stream construction.

Automatic enrollment now enters a separate ten-minute confirmation wait once
the positive configuration ACK and both ports' settings/plans are present.
The identity remains bound, repeated progress cannot extend the wait, and the
journal preserves the wait across gateway restart without committing an owner
or counter. HA uses its existing identity-confirmation stage. The explicit
research API keeps its original total deadline.

The private replay now consumes the actual phase-17 report from the follow-up
recording at its captured relative time and reaches `Observed` with masks
3/3/3 and the positive ACK preserved. That validates the software correction;
normal enrollment and physical CRC transmission still require the next trial.

Development signing [run 37211325238](https://github.com/fholgado/rainpoint-local/actions/runs/37211325238)
passed from source `a2471bd`, including all 1,041 CI tests. Local native protocol,
production and development builds, and their command-boundary checks passed.
The matching two-file gateway delta was hash-verified against the prior live
source, preserved in a private source snapshot and deployed. Managed HA backup
availability was checked first.

Test Node B received all 1,117,776 signed bytes, reported
`verified_publisher_and_sha256`, rebooted into `0.19.0-htv213-control.10`, and
confirmed `gateway_and_radio_healthy` with no pending candidate. The observer's
post-check encountered a missing version field on an unrelated offline node;
independent read-only verification confirmed the update without repeating OTA.
Other radio firmware versions were unchanged. Pairing remained inactive and
unarmed; no watering command was issued. Private deployment/transfer receipts
are under `captures/htv213-control10-qualification-20261004/`.

The subsequent full-enrollment test exposed a gateway admission blocker before
any pairing RF: owner-clear used the 32-character owner ID plus `-revoke`, while
the actual firmware ingress validator accepts only 32 hexadecimal characters.
The old mock-only revoke test bypassed that validator. A regression compiling
the real `validCommandId` against the gateway-generated clear command failed
before the fix and passed afterward. Clear now uses a fresh UUID command ID,
with the original owner ID unchanged in `owner_id`; no RF payload or control
phase changed. All 60 ownership/enrollment tests passed. The one-file gateway
fix was hash-verified and rebuilt without reflashing nodes. Authenticated
reconnect then acknowledged revocation, and Test Node B confirmed the normal
five-minute enrollment armed. Physical enrollment completion is still pending;
the new receive-only recording is retained under the same private capture root.

## HTV213 normal-enrollment first-handoff failure — October 3

The user's subsequent attempt failed before addressed port reports, not at the
final enrollment notification. In private capture
`captures/htv213-normal-enrollment-20261003/20261003-203315`, factory `01` phase 1
was followed by a matching `81` assignment approximately **82 ms** later. The
valve continued factory announcements at later phases rather than producing
the expected addressed `02`. A deterministic offline replay of that window
asserts the missing transition and fails. This proves an assignment was emitted
and decoded by the SDR; it does not prove the valve received or accepted it.

A wider 433.08–434.48 MHz decode around the first handoff found only `01/81`.
The remaining capture was checked at the three previous analysis centers; its
decoded frames belonged to other devices. That limited coverage is not proof
of silence on every carrier. Small clipped sample fractions were present, so
this recording is not qualified as entirely unclipped. The complete 360-second
IQ file is **1,440,000,000 bytes**, independently hash-verified and preserved.
The enrollment terminated with failure and Test Node B disarmed; no second
attempt, watering command, reset or garden update was performed.

Comparing the ordinary builder with the successful explicit canary exposed two
recipe differences: address **2 → 3** and power **0 → +10 dBm**. The address
allocator reserved the revoked canary's slot, whereas the power change came
from an unqualified default. The original comparison test supplied 0 dBm
explicitly and therefore never exercised that default. A regression using the
actual no-override builder failed on power; the source default now preserves
0 dBm and the regression passes. This is a recipe-parity correction, **not a
proven physical pairing fix**, and has not been deployed.

Validation passed: **1,036 full-suite Python tests**, 60 focused
ownership/enrollment tests, native C++ protocol tests and whitespace checks.

The next assisted trial changes only power: keep address 3, calibrated carriers,
payload parameters and response timing unchanged. Success would support the
power hypothesis; failure would leave address/re-pair behavior and emitted
waveform as candidates. Do not combine those changes or promote the model from
this failure. Physical qualification remains tracked in
[the roadmap](../PROJECT_ROADMAP.md).

## HTV213 automatic discovery and CRC-tail diagnosis — October 4

The tested one-file gateway power correction was backed up, hash-verified and
rebuilt; Test Node B remained on signed `0.19.0-htv213-control.9`. The user
authorized one new five-minute pairing window. Normal allocation preserved
failed-attempt slots and selected **address 4**, not 3. This was disclosed before
arming: the trial cannot isolate power as the cause. No new firmware, watering,
valve reset or garden change was performed.

The user reported success. Bounded SDR decoding independently recovered:

- Phase-7 `01/81` assignment followed by both ports' `02/82`.
- Hub phase-2 `20`, positive matching `a0` about 295 ms later, and another `02/82`
  carrying configuration revision 2 before settings requests.
- Both-port `05/85` and empty `06/86`, including repeated plan requests.
- A later valve-originated addressed idle `02`, phase 17, after the initial
  recording and enrollment window had ended.

Private evidence is in `captures/htv213-normal-enrollment-power0-20261004/`.
The initial 360-second IQ recording is **1,440,000,000 bytes**; the subsequent
receive-only 240-second recording is **960,000,000 bytes**. Both sizes and hashes
were independently verified. There was a gap between recordings; do not infer
silence during it. The later idle report occurred about 628 seconds after the
first recording began, around 459 seconds after the last initial state report.

### Physical native-CRC defect, not a demonstrated power cure

For each bounded assignment burst, an independent frequency discriminator
checked the symbol immediately after the normalized 304-bit frame, across all
clock phases reproducing that frame. Native CRC was calculated separately with
seed `0xa8a8`; its upper fifteen bits matched the decoded frame.

| Captured reply | Required final CRC bit | Observed following symbol |
| --- | --- | --- |
| Oct 3 failed assignments, phases 1/4/7 | 1 / 1 / 1 | 0 / 0 / 0 |
| Oct 4 assignments, phases 1/4/7 | 1 / 1 / 0 | 0 / 0 / 0 |
| Oct 4 plan replies, phases 13/14/15/16 | 1 / 0 / 1 / 0 | 0 / 0 / 0 / 0 |

Each burst had 83–85 matching decoder phases, unanimously observing zero in
that position. The valve advanced after the phase-7 assignment whose required
bit was zero; earlier high-bit assignments failed at **both** power levels.
High-bit plan replies were followed by repeated requests and zero-bit replies.
This is strong capture-backed evidence that the omitted native CRC symbol is
an acceptance defect, not proof that reducing power fixed it.

The live pairing runtime's two `transmitAsync` call sites omit the explicit
final symbol. The previously qualified HTV213 control/retained-owner runtime
already supplies `nativeTailSymbol(frame)`. Do not change those working paths
or generalize this finding to another model without its wire evidence.

### Completion-window defect remains separate

An offline replay of the actual exchange through the native `Session` reaches
reports/settings/plans masks **3/3/3** with a positive notification ACK, but
remains armed. Adding a report after the plans makes it observed; adding the
same report after expiry does not. This deterministically identifies the
post-plan report/deadline dependency. It does not justify inventing an RF
completion receipt from transmitted plan replies.

The real phase-17 idle report arrived after the five-minute deadline. The radio
was disarmed and the gateway reported failed enrollment, so no normal completion
receipt was produced or association committed. RF assignment/configuration is
verified; normal HA enrollment is **not** complete. The next implementation
needed to fix the CRC tail and distinguish the user pairing/discovery window from
known-device telemetry confirmation, without forcing database proof or silently
discarding the final-report qualification. Work is tracked in
[the roadmap](../PROJECT_ROADMAP.md).

### Control.10 RF enrollment verification — October 4

One user-authorized normal discovery attempt on Test Node B completed the
radio enrollment gate. The user reported success; the gateway entered
`waiting_for_terminal_confirmation`, then accepted the later report and exposed
`valve_pairing_completed` with the selected radio disarmed and no error.

Offsets below are seconds from the continuous recording's start:

| Offset | Captured exchange |
| --- | --- |
| 105.364 / 105.446 | Phase-1 `01/81`; required final CRC bit 0 transmitted correctly; no immediate progression observed. |
| 111.424 / 111.506 | Phase-4 `01/81`; required final CRC bit 1 transmitted correctly, followed by addressed reports. |
| 113.356–115.457 | Both ports' `02/82`, phases 5 and 6. |
| 116.596 / 116.891 | Configuration `20`, phase 2, and matching positive `a0`. |
| 119.402–121.513 | Both ports' `05/85`, phases 7 and 8. |
| 123.355–125.436 | Both ports' `06/86`, phases 9 and 10, without the earlier repeated plan requests. |
| 570.443 | Addressed port-1 idle `02`, phase 11, remaining/requested seconds both zero; matched the completed endpoint and controller. |

Independent bounded IQ measurements confirmed the final symbol on every
decoded gateway reply and notification. Required high bits on assignment,
report ACK, settings and plan replies were observed as 1 across 85–86 matching
clock phases. One low-bit settings reply had 84 matching phases voting 0 and
one voting 1; this sampling-edge ambiguity does not erase the strong high-bit
evidence. The correctly formed first assignment did not advance immediately,
so the CRC correction does not establish that every first reply is accepted.

The final report arrived **445.007 seconds after the last plan reply**. Its
acceptance verifies the separate confirmation window on hardware. It does not
establish universal report timing or the units of the assignment timing field.
The normal naming/save endpoint has not yet been called: no HTV213 device is
currently projected, and durable association/owner/counter commit remains a
separate pending step. No watering was sent during this trial.

Private evidence:
`captures/htv213-control10-enrollment-20261004/20261004-120555/` contains the
correlated API receipts, `initial-rf.jsonl`, `confirmation-rf.jsonl`, independent
`crc-tail-verification.json` and `confirmation-verified.json`. The 960-second
recording finished at 16:22:07 UTC, has exactly **3,840,000,000 bytes**, and its
independently recomputed SHA-256 matches the capture manifest. Raw IQ is retained.

### Control.10 association commit and restart — October 4

The normal `/pairing/complete` naming/save request committed the accepted
enrollment as one two-outlet test device. The radio confirmed restored reply
ownership, pairing became inactive, and the next master command phase was **3**
from the positive configuration ACK at phase 2. The later device-report phase
11 was not used as a command seed. HA registered 15 entities, including exactly
two outlet controls and two duration settings. Saving sent no watering command.

The prior projection coupled normal controls to the general model-menu flag,
which prevented qualification of a newly committed association through the
normal controls. The projection now treats menu publication separately from
control of RF-confirmed, atomically committed associations. Owner acknowledgement,
fresh idle reports on both outlets, duplicate-command suppression and existing
failure handling remain required. A new real enrollment/owner/report/control
regression failed before this change and passes afterwards; all **1,042 tests**
pass. The normal model menu remains unadvertised.

The single-file gateway change was backed up, hash-verified and deployed with
no radio firmware update. A read immediately after rebuild raced gateway
startup; a subsequent read-only check verified the persisted association and
restored owner. A separate single Test Node B reboot also restored the same
association/owner and next phase 3. The legacy registry was unchanged.

Fresh port-2 idle reporting resumed, with an independently decoded phase-19
`02/82` exchange 82 ms apart. Port 1 had not yet reported since the save when
the first bounded HA check ran, so that check deferred without sending any
watering. Normal-enrollment outlet controls were subsequently verified below;
the earlier retained-canary control results are not substituted for them.

Private save receipts remain beside the enrollment capture. Deployment,
restart and HA evidence are under
`captures/htv213-control10-normal-controls-20261004/`; the receive-only capture
`20261004-131438/owner-report-rf.jsonl` contains the post-save owner exchange.

### Control.10 normal HA outlet tests — October 4

After fresh idle reports from both outlets, the ordinary HA valve entities each
received exactly one 60-second open: port 1 at master phase **3**, followed by
port 2 at phase **4**. Both produced a positive full-phase `a1`, independent
active and automatic-idle `02` reports, and a port-specific `04` summary with
elapsed duration **60 seconds**. HA showed each target open and then closed;
the other outlet remained idle. The persisted next command phase is **5**.
No forced counter, repeat open, explicit close, reset or pairing was used.

Independent SDR decoding matched each command to the saved valve/companion
routes and each response to the saved controller/valve routes. Command-to-ACK
intervals were **314.5 ms** and **313.5 ms**, respectively. Port 1's summary was
observed about 2 seconds after idle; port 2's summary was observed about
**56 seconds after idle**. The latter still completed inside the existing
completion window; this observation does not establish why its summary arrived
later or justify assuming completion from elapsed wall-clock time alone.

An earlier check briefly had both outlets eligible, but port 2's report crossed
the existing 1,200-second freshness limit before dispatch. The helper deferred
without an open or counter allocation. It waited for new telemetry rather than
changing that limit; the following check admitted the two successful runs.

Private evidence is under `captures/htv213-control10-normal-controls-20261004/`:
the per-port attempt, observation and verification receipts; `ha-tests-final.json`;
and capture `20261004-135026/` with bounded RF decodes and
`ha-rf-verification.json`. The six-minute capture exited successfully with exactly
**1,440,000,000 bytes** and an independently verified SHA-256 checksum.
Decoding used selected command/completion windows on
three carriers, not uninterrupted all-channel coverage; the maximum decoded
chunk clipping fraction was about **0.35%**. These are dry-valve protocol/HA
results, not a measurement of water flow or a general model-support claim.
Repeat enrollment and physical missing-response qualification remain separate
gates in the roadmap.

### Control.10 repeat enrollment and same-device handback — October 4

After explicit permission to arm, the completed dry test association was retired
through the normal registry-forget API. The radio acknowledged old-owner
revocation before the normal enrollment API admitted the same target. The old
command history is retained by the enrollment journal's replacement path;
there was no direct database or counter edit. An initial helper request used
the sensor-only forget route and returned 404 without changing the association;
the subsequent valve-registry request succeeded. Only one pairing window was
armed, and no garden devices were changed.

The repeat followed the earlier capture: assignment at announcement phase 1
did not produce the following exchange; a phase-4 assignment was followed by
both-port `02/82` at phases 5/6, positive configuration `20/a0` at phase 2,
both-port settings at phases 7/8, and empty plans at phases 9/10. Do not count
this as proof that the first sweep always succeeds.

A later port-1 idle `02` at phase 11 completed enrollment **435.97 seconds**
after the final plan reply. Its `82` followed about **81 ms** later. Independent
bounded SDR decoding verified exact saved routing, positive configuration ACK,
both-port reports and the final report. Test Node B disarmed normally.

The normal naming/save API then restored the **same device ID, name and area**,
one two-outlet device, ready reply ownership and next master phase **3** from
the positive phase-2 configuration ACK. Pairing became inactive and the legacy
registry remained unchanged. This is an explicit new enrollment epoch, not an
inferred counter reset from the phase-11 report. No watering, reset, flash or
automatic rearm was performed. Physical missing-response qualification remains
unfinished; this does not enable general production model support.

Private evidence is in
`captures/htv213-control10-repeat-20261004/20261004-161155/`: original and
registry-revoke baselines, arm receipts, observer/terminal receipts, bounded
RF decodes, `rf-confirmation-verified.json`, normal save receipts and
`handback-verified.json`. Decoded windows had nonzero clipping (maximum chunk
fraction about **0.73%**) and covered selected times/carriers only. The full
960-second capture subsequently exited successfully with exactly
**3,840,000,000 bytes**; an independent SHA-256 check matched `sha256.txt`.
Association handback and capture-integrity verification are both complete.

### Missing-ACK idle recovery — October 4 (source only)

Preflight for the battery-out test exposed a deterministic dead end: the
gateway journal required an ACK to accept completion, while the radio had no
idle-recovery transition. Battery rejoin alone could not release an unanswered
open. Native and gateway regressions reproduced this before the fix.

The candidate adds `recovered_idle`, distinct from successful completion:

- After its response window, the radio requires valid, fresh idle reports from
  **both** outlets. Active or stale reports do not establish recovery.
- The gateway correlates the original command, current authenticated owner and
  `htv213_idle_recovery_v1` capability, then independently checks both saved RF
  reports are newer than the attempt and at most 20 minutes old.
- The old outcome remains **unknown**, without invented ACK/summary evidence.
  Its phase stays consumed; only a new user request allocates the next phase.
- HA updates its control status and existing problem notification to explain
  recovery. No open, close, reset or automatic retry is emitted by recovery.

Replay covers recovery before/after the overdue deadline, late ACKs, retained
history, wrong identity, partial/stale/active reports, firmware compatibility,
and the actual radio runtime's receive/ACK path. Acknowledged runs missing a
summary, unanswered closes, interrupted radio/gateway sessions and unfinished
counter-boundary experiments are not released by this new path.

Validation: **1,046 Python tests passed**, native protocol test passed, and both
the default production profile and HTV213/development candidate compiled.

No live test command or deployment accompanied this change. The battery-out
failure/reinsertion/new-command experiment remains the physical qualification
gate in [the roadmap](../PROJECT_ROADMAP.md), not an already-proven result.

### Control.11 deployment and capability admission — October 4

Development signing [run 37234055141](https://github.com/fholgado/rainpoint-local/actions/runs/37234055141)
passed for firmware source `66888a1` (1,046 CI tests, two optional skips).
After a current HA/gateway backup, three gateway recovery files and the HA
notification module were hash-verified and deployed; HA restarted successfully.
The firmware catalog is loaded at startup: an initial OTA admission request
preceded its reload and was rejected without dispatch. Reloading the catalog
made the verified artifact visible.

Test Node B received **1,117,952 bytes** and verified publisher signature and
SHA-256, but initially failed authentication. The new
`htv213_idle_recovery_v1` capability was missing from the gateway allowlist.
A real TCP-handshake regression, deriving capabilities from firmware source,
reproduced rejection with valid credentials. Adding the exact capability fixed
it while preserving unknown-capability rejection; **1,047 local tests passed**.
The single-file gateway correction restored the existing candidate without a
second firmware transfer or any credential change.

Independent verification confirmed `0.19.0-htv213-control.11`, authenticated
connection, `gateway_and_radio_healthy`, no pending candidate, ready reply
owner, the same saved valve, both HA outlets closed and next phase **3**.
Pairing stayed inactive, no watering was commanded and other radio firmware
versions were unchanged. Private receipts are in
`captures/htv213-control11-qualification-20261004/`. This verifies deployment,
not physical missing-response recovery; batteries remained in the valve.

### Control.11 battery-out test and reconnect gap — October 4

With the dry test valve's batteries removed, ordinary HA admission lacked
fresh idle reports. The user explicitly authorized the existing diagnostic
admission instead. One 60-second outlet-1 request reserved phase **3** from the
unchanged saved association; no readiness flags or counters were overridden.
SDR decoding confirmed native `21`, phase 3, the target valve and companion
route. No matching ACK was observed in that bounded interval. The radio
reported uncertain, then overdue; HA showed failed and disabled new starts.
The retained next phase became **4**, with no automatic retry.

The batteries were restored roughly three hours later. Authenticated gateway
receipts at 00:42:42Z and 00:42:44Z on October 5 showed both outlets idle, and
both HA entities became closed. Recovery nevertheless remained blocked.
Between the command and rejoin, gateway authentications increased from one to
three while node uptime continued: the radio reconnected without rebooting.

An offline reproduction using the actual C++ runtime dispatch/receive code
isolated the failure: a same-owner `htv213_owner_set` restores reply ownership
but unconditionally replaces `htv213ControlTrial` with an idle object. Later
reports reach ordinary telemetry, but no pending command remains in the radio
to produce correlated `recovered_idle`. The gateway correctly retains the
unresolved durable transaction. The reproduction fails after owner restore
(trial state 0); an in-memory-only counterfactual preserving the trial passes
the same both-port idle/no-retry assertions. This is diagnostic evidence, not
a deployed fix; simply skipping every owner reset is not a sufficient policy
for changed owners, enrollment epochs, restarts or acknowledged transactions.

Private evidence: `captures/htv213-control11-missing-response-20261004/20261004-172851/`.
The original 900-second capture is **3,600,000,000 bytes** and its independent
SHA-256 check matches `sha256.txt`. It ended before battery reinsertion:
rejoin evidence is gateway RF receipts, not an independent SDR recording.
Counter 4 remains intact; no follow-up open, forced release, pairing, reset or
deployment was performed. The reconnect case was outside the earlier
uninterrupted-session recovery qualification and is now a required fix in
[the roadmap](../PROJECT_ROADMAP.md).

### Control.12 live restart recovery and normal HA run — October 4 EDT

The matched gateway correction and development-signed
`0.19.0-htv213-control.12` (source `9cd84b4`) were deployed to Test Node B.
HA backup `74b431bc` was verified before deployment. The first OTA download
stalled at 393,216 bytes without activating a candidate; one subsequent OTA
completed all 1,118,640 bytes with signature/SHA verification and
`gateway_and_radio_healthy`. Installed garden radio firmware and the saved
registry remained unchanged. The gateway rebuild and radio OTA reboot exercised
restoration from durable state, not just the uninterrupted receive path.

After restoration, fresh outlet-1 idle arrived at **01:34:05Z** and outlet-2
idle at **01:41:25Z** on October 5. The original phase-3 transaction became
`recovered_idle`, still unacknowledged with unknown original outcome; HA start
availability returned. The retained next phase stayed **4**. No watering
command was sent by restoration, and no phase was reset or forced.
Outlet 1's report and phase-echo acknowledgment were independently SDR-decoded.
Outlet 2 arrived between the two recordings, so its recovery evidence is the
authenticated gateway/radio receipt, not independent SDR coverage.

One new user-authorized normal HA request then ran dry outlet 1 for **60 seconds
at phase 4**. Independent bounded IQ decoding verified the exact command and
reply routes, native `21`, positive full-phase `a1`, outlet-1 active reports,
automatic idle and `04` summary. HA was observed open then closed; the journal
reported complete with ACK, idle and summary, and next phase **5**. Outlet 2
remained idle. There was no automatic open retry, speculative close, pairing
or valve reset.

Private evidence: `captures/htv213-control12-qualification-20261005/`, including
deployment, recovery, HA and independent RF verification receipts. The first
960-second recording is **3,840,000,000 bytes**; the following 240-second
recording is **960,000,000 bytes**. Both exact sizes and independently computed
SHA-256 hashes match their capture receipts; the evidence set is sealed.
Decoded chunks have some clipping (maximum about 0.38% in the command windows);
validated frames prove the listed exchanges, not silence outside those windows.
This qualifies one physical missing-response/restart-recovery path on the dry
HTV213 canary, not general model enablement or recovery on other valve families.

### Native HA two-zone menu rollout — October 5

Gateway **0.39.17** and integration **0.18.5** expose HTV213FRF through the
existing Configure → Add a RainPoint device → Valves flow. Radio selection and
server admission share eligibility: authenticated/managed protocol-v2 radio,
complete control.12-equivalent enrollment/control/recovery capabilities, saved
per-radio carrier calibration and no existing device ownership. HA refreshes
eligibility on display and submission; older gateways retain capability-only
selection for their existing profiles. No extra wizard, RF-parameter form or
per-user control experiments are required.

The full suite passed **1,061 tests**, including real gateway admission/catalog
checks and native HA callbacks for review, stale eligibility and withdrawn
models. The native C++ protocol test passed; no firmware source changed.
Backup `bd3c4e68` was verified to contain both `homeassistant.tar.gz` and
`local_rainpointd.tar.gz`. Deployed runtime hashes matched the tested package;
HA configuration validation passed before restart.

The previous live integration still contained the already-retired wizard.
Installing the consistent tracked package removed that sidebar entry; the old
package is recoverable under
`/share/rainpoint-local/source-backups/native-ha-20261005/` and in the backup.
The existing owner-cleanup diagnostics added four node entities; the device
count remained 13.

In-app-browser verification showed integration version 0.18.5, the HTV213FRF
model, Next navigation and the prepared-radio explanation. Test Node B is
correctly excluded from a **new** enrollment because it already owns the saved
test valve. The dialog was closed without arming. API checks independently
confirmed exactly two closed HA valve controls with 1–60-minute limits, unchanged
next phase **5**, unchanged registry/control transaction identities and all
radio firmware versions unchanged. No pairing, watering, RF calibration change
or radio update occurred during this rollout.

Private deployment/HA receipts are in `captures/htv213-native-ha-menu-20261005/`.
This verifies native UI exposure and preservation of the existing association,
not a new physical enrollment. Standard Alpha 1 firmware still excludes the
HTV213 runtime; ordinary signed-firmware integration and second-radio carrier
qualification remain explicit release gates in [the roadmap](../PROJECT_ROADMAP.md).

### Unified firmware two-zone promotion — October 5

Unified firmware **0.20.0** now includes the qualified HTV213 enrollment,
routine owner, retained battery rejoin, bounded controls and observation-only
idle recovery. Gateway **0.39.18** selects `htv213_control_open/close` when the
radio advertises `htv213_control_v1`; older control.12 radios retain their
existing command names and durable journal. Ordinary images exclude explicit
factory-identity pairing probes, control probes, phase-trial commands and
development trust. The experimental build flags enable only the additional
research entry points; ordinary enrollment/control share the proven RF builders.

The native CRC tail is available to the qualified HTV213 callers in the standard
driver. Other models retain the existing default stream. Actual dispatcher,
waveform, authenticated socket and temporary-database regressions verify normal
open/close, phase preservation, older-firmware compatibility and rejection of
research admission before a phase reservation on standard radios.

The final full suite passed **1,067 tests**. Native protocol tests and
standard, phase-trial and development-recovery PlatformIO builds passed their
respective command/trust boundary checks. Standard flash use is **1,111,145 /
1,310,720 bytes**; RAM is **54,712 / 327,680 bytes**. This is source/build
qualification, not an on-air test of a newly installed image. A read-only live
check found the existing two-zone valve idle at next phase **5**, with all three
active radios connected, authenticated and disarmed.

Second-radio carrier validation was deferred at the user's request. Saved
per-radio calibration remains required; this promotion adds no universal carrier
offset or calibration evidence. Alpha 1's published artifacts remain unchanged.
Signing and test-node rollout are tracked in [the roadmap](../PROJECT_ROADMAP.md).

### Unified candidate deployment and normal HA controls — October 5

Development signing run [37286839651](https://github.com/fholgado/rainpoint-local/actions/runs/37286839651)
produced **0.20.0-rc.1** from source **13b97c13** using the ordinary unified
profile plus explicit development trust. Both CI runs passed all checks.
The image's publisher signature, source revision, catalog copy and firmware
command boundary were independently verified before OTA.

Gateway **0.39.18** was deployed from the tested eight-file delta, with HA backup
`bd3c4e68` verified available and a recoverable source copy under
`/share/rainpoint-local/source-backups/unified-020-20261005`. Gateway restart and
signed OTA preserved the same saved two-outlet device, registry, ready reply owner
and next phase **5**. Test Node B confirmed `gateway_and_radio_healthy`, advertised
`htv213_control_v1`, and advertised neither research pairing nor research control.
Other radio firmware remained unchanged. HA integration stays at **0.18.5**.

Two **60-second dry runs** through the normal HA valve entities then completed:
port 1 at full master phase **5**, port 2 at **6**. Independent bounded SDR
decoding confirms each `21`, positive matching `a1`, target-port active and idle
`02`, elapsed-60 `04`, and phase-correlated `84`. Acceptance delays were about
**309 ms**; idle reports arrived **62.95 s** and **61.43 s** after each command.
The second summary arrived about **117.4 s** after its command, later than its
first idle; the gateway kept the command pending until actual completion evidence.
Both HA entities transitioned open → closed, the other outlet stayed idle, and
the retained next phase is **7**. No open was retried or counter forced.

The **1,440,000,000-byte** receive-only capture completed and its SHA-256 was
independently checked against the capture receipt. Private evidence is under
`captures/htv213-unified-020-20261005/`. Some bounded IQ windows contained about
0.5% clipped samples; this supports validated packets and transaction correlation,
not precision carrier calibration. Second-radio calibration validation remains
deferred. The ordinary release-key image still uses protected signing approval.

### Release-key production image handback — October 5

Protected signing run [37289662174](https://github.com/fholgado/rainpoint-local/actions/runs/37289662174)
produced unified **0.20.0** from **f1090330**. Independent verification checked
the release-key signature, build receipt, source SHA, application bytes, OTA
catalog copy and production command/trust boundaries before installation.

One OTA to Test Node B received **1,117,376 bytes**, verified publisher/hash,
rebooted and confirmed `gateway_and_radio_healthy`. Development-key trust and
research probe capabilities are absent. The same saved two-outlet HA device,
ready reply owner and retained next phase **7** survived gateway catalog reload
and radio reboot; both HA valve entities read back closed. Gateway **0.39.18**
and integration **0.18.5** remain deployed. Installed garden radio firmware is
unchanged. No watering, pairing, phase adjustment or calibration test occurred.

Private readback/OTA receipts are under
`captures/htv213-production-020-20261005/`. This qualifies production-image OTA
handback, not an additional RF control trial or second-radio calibration.
The signed artifact was subsequently published as the
[0.20.0 firmware alpha](https://github.com/fholgado/rainpoint-local/releases/tag/firmware-v0.20.0);
the original Alpha 1 artifacts are unchanged. Explicit chat approval is supported
without relaxing the protected signing environment.

### Replacement radio carrier trial October 5

A same-batch spare CC1101 on Test Node B, running release-key firmware **0.20.0**,
reproduced the original radio's frequency offset. Nominal settings produced
three correlated assignment replies at phases 1, 4 and 7, but the valve kept
announcing rather than proceeding to configuration.

| Reply frequency setting | Measured wake center | Outcome |
| --- | --- | --- |
| 434,241,500 Hz | 434,196,125–434,196,187.5 Hz | Assignment replies; no configuration progression |
| 434,287,000 Hz | 434,241,500 Hz | Assignment accepted; full configuration and later completion |

The measurements use eight-millisecond windows inside the 320-symbol wake
at 20 ksymbols/s. Those windows were not clipped; the corrected wake's tone
spacing was 80 kHz. These are relative measurements from the same SDR, not
absolute calibration against a frequency standard. The result supports reusing
the **+45.5 kHz** correction on this spare, not a universal hardware correction.

The corrected trial includes both-port `02/82`, positive configuration `a0`
at master phase **2**, settings `05/85`, empty plans `06/86`, and an independently
decoded later `02` completion. Normal naming/save restored the same gateway
device ID and name, a ready reply owner, and ACK-derived next phase **3**.
The legacy registry and installed garden devices were unchanged.

Both pairing recordings completed at **3,840,000,000 bytes** and passed independent
SHA-256 checks. Private evidence is in `captures/htv213-nominal-spare-20261005/`
and `captures/htv213-corrected-spare-20261005/`. The nominal trial's reported Mac
sleep did not prevent recovery of the three assignment exchanges; it is not
evidence that the measured carrier offset was caused by sleep. The corrected
recording used idle-sleep prevention.

Changing profiles after restoring the original owner rejected the first nominal
arm; rebooting the test node allowed it to arm. The driver has two cached TX
frequency slots, and clearing ownership does not invalidate those slots. That
is a concrete cache-refresh suspect, distinct from the on-air carrier offset.

The saved owner starts with empty per-port telemetry, discarding the known state
in the completion report. Normal HA start was initially unavailable. After both
outlets supplied fresh idle reports, three dry tests through normal HA entities
completed without a retry or forced counter:

- Outlet 1: phase **3**, 60 seconds; positive `a1`, active/idle `02`, elapsed-60
  `04` and matching `84`. Idle arrived 62.54 seconds after command sync.
- Outlet 2: phase **4**, 60 seconds; the same independent RF evidence. Idle
  arrived after 61.93 seconds.
- Outlet 1: phase **5**, 120-second request, followed by explicit close at
  phase **6**. Positive close `a1`, idle, elapsed-22 summary and matching `84`
  confirmed the early stop.

The SDR recovered exactly the four target `21` commands and positive full-phase
ACKs, with acceptance delays of about **305–315 ms**. HA reflected open/closed,
the other outlet remained idle, original duration settings were restored, and
the retained next phase is **7**. Private control evidence is under
`captures/htv213-corrected-spare-controls-20261005/`. Other nodes and installed
garden valves were not commanded or updated.

The **1,920,000,000-byte** control capture completed and passed an independent
SHA-256 check against its receipt. Final gateway readback confirmed both outlets
idle, normal start available, pairing inactive and ready authenticated ownership
on firmware **0.20.0**.

This qualifies the existing corrected recipe on a same-batch replacement radio.
It does not require a long soak or establish sensor coexistence. Manual carrier
setup, shared receive/ACK dispatch and preservation of completion telemetry are
tracked separately in [the roadmap](../PROJECT_ROADMAP.md).

### Shared radio release implementation October 5

Firmware **0.21.0**, gateway **0.39.19** and integration **0.18.6** remove manual
tuning and dedicated-radio prerequisites for normal HTV213 setup. The default
carriers use the original/spare-radio recipe; explicit overrides and existing
associations remain intact. Older firmware retains compatibility but needs
updating before it can share ownership.

Firmware keeps eight independent HTV213 runtime records. Commands resolve the
factory/controller pair or linked open/owner ID; reports resolve their exact
association. Unrelated frames continue to the established sensor and other-valve
handlers. Serialized RF transmission, short response-window admission and RX
restoration prevent another device's ACK from stranding the pending listener.
The 16-entry rotating frequency cache replaces successful calibrations without
rebooting; configuration bursts leave excess commands in TCP until queue space
is available.

The gateway retains per-association readiness and control correlation. Shared
enrollment is explicitly capability-negotiated and recorded in its epoch;
same-valve replacement still requires acknowledged revocation and archives old
commands. Adding another valve preserves existing counter records. Completion
state uses only the reported outlet and original RF observation time.

The complete **1,077-test** suite, native protocol executable and production
ESP32 build passed. Actual-source C++ replays cover eight owners, interleaved
reports, correct open/close routing, isolated revocation, response-window expiry
and command-queue backpressure. This is source/replay qualification; the earlier
spare-radio pairing/controls above remain the physical RF evidence. Mixed-device
field feedback is a separate alpha outcome, not an invented completed soak.
