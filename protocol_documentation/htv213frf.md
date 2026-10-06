# HTV213FRF two-zone valve protocol

**Stock reference plus locally verified dry pairing, both-outlet control,
explicit stop, battery rejoin and missing-response/restart recovery.
Shared-radio HA setup is available with unified firmware 0.21.0 / gateway 0.39.19
(firmware alpha), or qualified control.12 test firmware. Alpha 1
firmware does not include this model.**
The HTV213FRF is one RF device with ports `1` and `2`. Follow
[common framing](common.md) and the
[capture evidence](../research/HTV213_STOCK_CAPTURE_FINDINGS_20260928.md).
Do not reuse another model's association identities, selectors or fixed stages.

## Local dry-test candidate

The isolated `rainpoint_htv213_pairing.h` session implements fresh long-press
`01/81`, both-port `02/82`, one revision-2 `20/a0`, and requested `05/85` and
empty `06/86` replies. It echoes all six phase bits; it does not wait for a
particular sweep counter or reuse the four-zone fixed transcript. Only the
two captured explicit-pairing announcement bodies are admitted:
`0c ff 20 05 01 04 3e 05` (stock enrollment) and
`0b ff 20 05 01 04 3e 07` (repeat local trial). Retained battery rejoin ending
in `03` remains excluded from fresh enrollment. These are exact experimental allowlist entries,
not a general pairing-flag interpretation. The repeat variant received a
locally accepted assignment in two dry trials, followed by addressed reports
and acknowledgements for both ports. Preserve that proven prefix.
These bytes alone do not distinguish long-press pairing from a boot announcement.

### Retained reply owner

The control runtime adds a retained owner, separate from
fresh enrollment. Its saved association supplies address, routine selector,
timing, configuration revision, fourteen-byte settings for each port and known
empty plans. `01/81` returns that association; `02/82`, `05/85` and page-zero
`06/86` answer incoming requests with their full six-bit phase. Unknown settings,
plans, time context or announcement selectors do not receive guessed replies.
The retained assignment filter admits the exact prefix `ff 20 05 01 04 3e`
followed by captured suffix `03` or `07`, only for the saved factory endpoint.
Battery-only startup also produced `07`; it does not establish a button press
or a counter reset. Local known-owner `07` recovery is RF-verified: assignment
is followed by both-port `02/82`, `05/85` and `06/86`, with idle reports.
One subsequent port-1 60-second command at retained phase 2 received positive
`a1`, active/automatic-idle reports and an elapsed-60 summary. No command phase
was reset; the gateway advanced its next phase from 2 to 3.

Assignment uses the incoming announcement selector's carrier, not the saved
routine selector's carrier. Replies retain the corrected native CRC tail and
restore the report receiver afterward. Configuration restoration transmits no
unsolicited RF and never allocates/resets a master command phase.

Authenticated POST `/api/v1/experiments/htv213/recovery` accepts an existing
`association_key`, explicit `configuration` (schema in `valve_recovery.py`) and
boolean `enabled`. It installs configuration through the existing reply owner;
it does not enroll or water. Nodes require `htv213_retained_rejoin_v1`. Normal
enrollment saves the same qualified configuration. Battery-only rejoin is physically verified;
repeat/lifecycle qualification remains tracked in the roadmap.

Both signing workflows have an unpublished `htv213-recovery` profile. Release
signing requires approval; separate development signing is automatic and only
development-trust radios accept its key. Neither workflow deploys. The binary
checker excludes research command entry points from ordinary firmware; unified
0.20.0 includes the qualified runtime. See [signing boundaries](../docs/FIRMWARE_SIGNING_DESIGN.md).
Idle retained ownership permits signed OTA without clearing the association;
an active two-zone control transaction still blocks the update.

The gateway supplies its generated local identity and an exact target factory
endpoint. Carrier, selector, address, reply delay, power and the independent
notification phase are explicit experiment inputs. Notification transmission
uses the stock long wake and listens on its command carrier for matching `a0`
for up to 750 ms, then resumes lower-carrier reporting. This receive window is
a bounded implementation choice, not a newly established protocol constant.
Restoring the lower carrier requires the full receive configuration: selecting
channel index 0 alone leaves the notification's synthesizer base in place.
Pairing.5 corrects this handoff; it does not change assignment or ACK admission.

`initial_center_hz` is the programmed **selector-12 reference**,
including an explicitly measured per-node correction when needed. The accepted
announcement's selector chooses the assignment reply: 12 uses that reference;
11 uses reference minus 110 kHz. This is independent of the new selector in
the `81` reply body. Both derived carriers must be within 433–435 MHz before
arming; unsupported announcement selectors still fail closed. `routine_center_hz`
remains a separate programmed carrier. The radio caches both assignment
carriers in its two slots; a distinct routine carrier uses normal on-demand
calibration. Do not infer a universal hardware offset from one test node.

Gateway 0.39.2 source exposes authenticated POST endpoints
`/api/v1/pairing/htv213/start` and `/cancel`; the request schema and bounds are
defined in `rainpointd/htv213_pairing.py`. Start requires a dry valve and an
unassigned, managed canary node. Status remains `operational: false`, including
after both configuration exchanges and a later device report (`observed`).
Nothing registers a valve or enables watering. Cancel uses the original command
ID; disconnect, transmit failure and the maximum five-minute deadline stop TX.
An indeterminate dispatch/cancel failure retains its bounded admission lease.

Build in the existing `rainpoint_bridge` environment with
`RAINPOINT_HTV213_PAIRING_EXPERIMENT=1` and an explicit prerelease version such
as `RAINPOINT_FIRMWARE_VERSION=0.19.0-htv213-pairing.5`. Normal builds omit the
commands and capability; release-boundary checks reject an experimental image.
Gateway 0.39.1 does not accept this new capability: deploy the matching gateway
before the canary, not to installed irrigation nodes. The isolated gateway
0.39.2/canary deployment is recorded in
[validation notes](../docs/STOCK_INFORMED_VALIDATION.md). Pairing.5 has one
SDR-verified local exchange containing assignment, both-port reports/ACKs,
positive `20/a0`, and both-port `05/85` and `06/86`, including repeated plan
requests. Preserve this working path. Subsequent dry trials qualify addressed
reports, both-outlet control and explicit stop as described below; transmitted
plan replies alone are not the acceptance evidence. General enrollment and
repeat/lifecycle recovery remain separate qualification gates.

Capture-backed tests verify the normalized bytes, not the physical final CRC
bit, oscillator calibration or valve acceptance. The candidate currently
listens on the proven lower factory/report leg rather than every sweep carrier.
Do not restart the gateway during an armed experiment: its admission lease is
in memory, while the node independently cancels on connection loss. Keep stock
hub TX out of the trial and ask the user before arming. Qualification and
promotion gates remain in [the roadmap](../PROJECT_ROADMAP.md).

## Enrollment

Standard firmware supports authenticated `htv213_enrollment_start`, advertised
by `htv213_auto_identity_pairing`. The gateway recipe supplies an available
address, local identities and default or optionally overridden
carriers; it does not require a known factory ID. During an explicitly armed
window, firmware binds the first checksum-valid broadcast with either captured
body `0cff200501043e05` or `0bff200501043e07`. The identity then stays fixed for
that window. Assignment bytes, carrier selection, phase echo and configuration
replies are unchanged from targeted pairing.

Completion receipts contain the actual positive full-phase `a0` and a later
post-configuration `02`, after both ports' settings and plans were sent. The
normal enrollment module validates those receipts and atomically saves the
enrollment proof, retained reply ownership and control seed from the acknowledged
hub phase, not the device-report phase. Re-pair requires prior acknowledged
owner revocation; the new epoch archives old control history before seeding its
counter. Duplicate naming requests, ordinary reconnects and battery reports
do not reseed counters or replay enrollment.

The flow uses HA's existing model/radio selection, review, progress, cancellation
and naming screens. Pending completion proof survives a gateway restart;
retained configuration is sent only after the association commits. Gateway
0.39.19 / integration 0.18.6 expose the model and select only authenticated,
managed radios with all enrollment, control, retained-rejoin and control.12
idle-recovery capabilities. Firmware advertising `htv213_shared_radio_v1`
supports sensors, other valve families and eight independent HTV213 associations
on one radio. Older firmware must be updated before sharing. Visiting the menu
never revokes an owner. A saved working
valve needs no re-pairing. Explicit re-pair still requires acknowledged old-owner
revocation before enrollment.

Default carrier settings are 434397000 Hz (selector-12 reference) and 434287000 Hz
(selector-11/routine), empirically verified on two radios. Manual tuning is
optional, not a pairing prerequisite. Authenticated
`POST /api/v1/nodes/{node_id}/htv213-calibration` saves explicit integer
`initial_center_hz` and `routine_center_hz`; it sends no RF and changes no counter.
The node/model setup flow preserves overrides without exposing RF fields.
Saving enrollment retains the actual completion outlet report with its original
observation time; it does not invent freshness for the other outlet. Shared
firmware routes packets by association, serializes RF transmissions and resumes
bounded response listeners after another device's ACK. Reconnect configuration
bursts apply TCP backpressure rather than dropping commands at queue capacity.
Slot allocation avoids the frozen legacy slots 1 (HTV145) and 6 (HCS026/HTV405),
retained same-controller configurations, tombstones and prior assignment attempts.
It does not modify the other models' proven pairing bytes. Committed,
RF-confirmed associations use normal controls independently of menu visibility;
confirmed reply ownership and fresh idle reports for both outlets are required
before starting. All HTV213 transmit paths append the native CRC's final symbol.
After a positive
configuration ACK and both ports' settings/plans, automatic discovery closes
and a separate ten-minute confirmation wait begins for the bound identity.
Repeated progress does not extend it. HA displays its existing confirmation
stage; only a real subsequent valve report permits association/phase commit.
This wait is an observation budget, not a decoded unit for `timing_raw`.
Disconnect, cancellation and TX failure still end the session. The older
explicit research API retains its original overall deadline. Initial and repeat
full enrollment, same-device naming/save and ACK-derived next phase 3 have been
verified. Historical timing/failure evidence remains in the
[validation record](../docs/STOCK_INFORMED_VALIDATION.md)
and [the roadmap](../PROJECT_ROADMAP.md).

The observed successful stock association consists of:

| Native exchange | Meaning |
| --- | --- |
| `01 / 81` | Factory announcement and assignment |
| `02 / 82`, per port | Addressed state report and acknowledgement |
| Hub `20 / a0` | Configuration-version notification and result; independent hub phase |
| `05 / 85`, per port | Settings read; result plus fourteen configuration bytes |
| `06 / 86`, per port | Plan-page read; result `00` for the captured empty page |

Direct replies echo the request's full six-bit phase. Configuration revisions
and RF phases are distinct. Each captured port's initial settings decode to
work-time raw 600, mist-open raw 10, interval raw 30, with the other fields zero;
see the qualified [settings layout](../research/STOCK_HUB_CONFIGURATION_LIFECYCLE.md).
There is no proven universal fixed row count or terminal authorization packet.
No `59 / d9` exchange was recovered in this association; absence in these
recordings is not proof that it can never occur.

An `81` reply alone does not establish pairing. Require addressed reports and
configuration progression. A boot announcement alone is not proof that a previous
association was erased or retained.

### Retained association after a battery change

One stock-owned valve recovered automatically with the hub left running and
pairing mode not armed. Boot `01` announcements used phases 1–4; `81` replies
retained the existing selector/address. Both ports then repeated `02 / 82`
(phases 5–6), `05 / 85` (7–8), and `06 / 86` (9–10).
State ACK data was `00 02`, retaining configuration revision 2; no intervening
`20 / a0` notification was decoded. The retained assignment reply used the
paired hub carrier, not the initial new-association reply carrier.

This is a recognized-device rejoin exchange, not merely one idle report.
The hub continued its independent command sequence from 3 to 4, with a
positive `a1`, port-2 countdown/idle and 60-second session summary after the
device's report sequence restarted.
Do not reset the hub's next command from a battery-start announcement or copy
the captured selector/phase into a generic implementation. These observations
qualify one stock rejoin, not every reset branch.

Local known-owner recovery is also verified once for an announcement ending
`07`: result-`00` assignment retains saved address, selector, timing and revision;
both ports complete the same state/settings/empty-plan request sequence without
fresh pairing or an unsolicited configuration notification. The local gateway
counter remained 2 through recovery. A subsequent 60-second port-1 open at
that phase was accepted and stopped automatically, with full-phase positive
`a1`, independent active/idle reports and elapsed-60 summary; next phase became
3. This qualifies one local recovery/control path, not universal reset behavior.

The opt-in retained-owner builder now replays `81/82/85/86` independently of
fresh pairing. Assignment TX uses the announcement's qualified selector (11 or
12), while the payload retains the saved address/selector. Unknown selectors
stay silent. Recovery must be explicitly enabled on the existing owner; these
replies allocate no master command phase. Local battery qualification is tracked
in [the roadmap](../PROJECT_ROADMAP.md).

## Commands and reported state

Unified firmware 0.20.0 includes `rainpoint_htv213_control.h` and advertises
`htv213_control_v1`. Normal HA controls use `htv213_control_open` and
`htv213_control_close`; older control.12 firmware keeps its deployed wire names.
Explicit research probes require `RAINPOINT_HTV213_PAIRING_EXPERIMENT=1` and
`RAINPOINT_HTV213_CONTROL_EXPERIMENT=1` and are excluded from ordinary firmware.
Authenticated `/api/v1/experiments/htv213/open` and `/close` operate an
explicitly admitted, unassigned dry-test node only.
The journal reserves each independent command phase before sending, never
replays an uncertain attempt, and never seeds counters from routine reports.
An explicit evidence reference supplies the initial acknowledged command phase.
The candidate supports 1–3600 seconds; the gateway requires the corresponding
node capability before allowing requests above the earlier 120-second limit.

The node listens for the command result on the routine carrier for up to
1,500 ms, then restores the full lower-carrier receive configuration. A
matching successful `a1` confirms acceptance; target-port idle plus a qualified
`04` summary establishes completion. A missing reply becomes uncertain, not
closed or rejected. No timeout, disconnect or restart sends an automatic close.
Ordinary state/summary acknowledgements echo the valve's phase. The successful
pairing session and its settings/plan responder are unchanged.

The normalized 304-bit frame omits the final native CRC bit. HTV213
commands and acknowledgements append that computed **305th symbol**. Local
port-1 and port-2 60-second runs and an explicit port-1 stop have matching `a1`,
idle and summary evidence. Master command phases advanced 3→4→5→6 independently
of report phases. Historical failures and waveform comparisons are retained in
the [validation record](../docs/STOCK_INFORMED_VALIDATION.md).

Retained reply ownership persists the association at the gateway and restores
configuration only on authenticated node reconnect. It acknowledges addressed
`02/04` and answers `05/06`; it never resets the command phase or replays an open.
Battery rejoin is enabled by normal committed enrollment on unified 0.20.0 and
qualified control.12 firmware. Shared multi-device
master allocation remains unqualified; the runtime owns one valve per radio.
The qualified dry-device HA adapter exposes exactly two outlets and actual
per-port report state; it must not invent battery percentage or water volume.
Both outlets have also completed HA-driven dry runs after owner restoration:
Port 2 for 300 seconds at master phase 7, then Port 1 for 60 seconds at phase 8
after an HA restart. Both had matching acceptance, idle and elapsed summaries.
The 300-second native replay is
`research/fixtures/htv213_local_ha_auto300_20260930.json`.
During that run, device reports moved from phase 63 to 1 and received matching
replies; that observation does not qualify the hub's independent command-phase
wrap. Report phases must never reseed the command journal.

Static stock firmware uses one shared master allocator with wire sequence
`1..63,0,1`; see the [independent audit](../research/HTV213_COUNTER_WRAP_AUDIT.md).
This differs from the observed report sequence. Legacy canary records stop
before wrap unless their boundary audit is complete. A once-only, explicitly authorized dry
boundary probe preserves the true starting phase and records deliberate
62→63→0→1 attempts; every next attempt requires the previous ACK, idle and
summary. An unanswered attempt blocks the sequence rather than reseeding it.

One local association has completed that boundary probe: four port-1 60-second
commands at 62, 63, 0 and 1 each received a matching positive `a1`, watering,
idle and elapsed-60 summary. This proves phase zero and the tested transition
are accepted without re-pairing for this association; the initial jump from
next phase 9 to 62 was also accepted. It does not establish every possible
out-of-order/duplicate policy, shared multi-device allocation or reset behavior.
Qualified associations persist and increment the next phase modulo 64; ordinary
report phases still cannot reseed it. See
`research/fixtures/htv213_local_counter_boundary_20260930.json`.

Source-prepared normal enrollment records model policy `htv213_modulo64_v1`:
increment modulo 64 from the real ACK-based seed, with no jump, reset or per-user
boundary experiment. This applies the stock generator and qualified local
transition to the staged model; it does not fabricate a completed trial for each
new association or prove other hardware versions. HA radio eligibility still
requires matching capabilities, not manual calibration. Old canary records and other
valve models retain their existing policy; uncertain sends remain reserved.

An attempted open supersedes pre-command idle on its target outlet: until a new
report, current state is unknown, not closed. Missing command confirmation
blocks new opens. An acknowledged run without stop evidence is overdue after
the bounded completion deadline; an observed stop with a missing summary is a
different completion error, not evidence that watering continues. Neither error
automatically transmits a retry or close. Genuine later evidence may reconcile
the original transaction without consuming another phase.

An unresolved, unacknowledged open survives gateway/radio reconnect by restoring
only its observation context from the durable journal. On control.12-capable
radios, fresh idle reports from **both** outlets release it as `recovered_idle`;
the original outcome remains unknown and the already-reserved phase stays used.
Neither restoration nor recovery transmits an open or close. Only a subsequent
explicit request uses the next phase. This path is qualified across a gateway
rebuild and radio reboot, followed by a successful ordinary HA run.

Native `21` open data is:

```text
port 02 01 seconds_low seconds_high
```

The duration is unsigned little-endian seconds. Stock 60- and 120-second
commands have matching `a1` responses, countdowns, final idle reports and session
summaries. Command phase belongs to the hub's request sequence; ordinary report
ACKs echo the valve's sequence and must not reseed the next command.

A stock-owned valve accepted a 60-second command after more than 30 minutes
idle without re-pairing, a restart, or deliberately waiting for a fresh report.
The captured hub phase advanced from the prior close's 6 to this open's 7;
matching reply, independent idle and elapsed summary confirmed the run.
A subsequent 60-second port-2 command after more than three hours idle also
received a matching reply, independent idle report and 60-second summary; hub phase advanced
7 to 8 without a requested restart or re-pairing. Unrecorded intervening traffic
prevents a complete counter-consumption ledger. These stock trials do not
establish overnight durability, reset behavior or local counter acceptance rules.

In one hub-only RST trial with the valve left powered, stock startup sent
`20` data `02 01` (configuration revision 2, update kind 1) at phase 2 and
received a positive `a0`. The next 60-second open used phase 3, below the
pre-restart phase 8, with matching `a1`, idle and a 60-second summary.
No new `01 / 81` enrollment was decoded. This qualifies that stock restart
path; it does not prove kind 1 resets the valve's acceptance state, or that
restarting our counter alone is sufficient. Valve-only battery recovery follows
the separately observed retained-association path above.

Native `21` close data is `port 02 00`. An early stop after approximately 35
seconds returned matching `a1`, then a port-specific idle `02` and a final
`04` duration of 34 seconds. The close response retained requested total 120
with remaining 0 and mode byte `20`; it did **not** replace every field with
ordinary idle zeros. Do not require total=0 or mode=00 to recognize that
captured successful close response.

Observed native report layouts, with offsets starting at their data body:

| Message | Fields |
| --- | --- |
| `02` | Port at byte 2; remaining seconds at 10..11; requested seconds at 13..14 |
| `a1` | Result byte 0; remaining seconds at 8..9; requested seconds at 11..12 |
| `04 / 84` | Per-port elapsed-run summary and acknowledgement; automatic-stop durations match the request, while early-stop duration is shorter |

The first `a1` remaining value was requested duration + 1. Later countdowns
include odd seconds; preserve all duration bits rather than rounding or applying
a constant correction. A successful command response/state report is evidence
of **reported valve state**, not measured hydraulic flow.

**Idle is port-specific.** A port-1 idle report occurred during a port-2 run;
it must not clear port 2. Simultaneous operation was not tested. Runtime decoding
must validate the association and model-specific shape before applying fields.

## Capabilities and limits

The [manufacturer's HTV213FRF manual](https://www.waterirrigation.co.uk/media/mageworx/downloads/attachment/file/h/t/htv213frf_-_rainpoint_smart_two_zone_wi-fi_water_tap_timer_instruction_manual.pdf)
advertises a flow meter, water-usage statistics and manual duration selection.
That establishes advertised capability, not RF volume units or calibration.
Dry zero usage must not be interpreted as absence of a flow meter. Battery
categorization and volume scaling are not established by these dry controls.
Stock observations alone do not qualify local recovery. One local battery-only
recovery and subsequent retained-phase control are now verified; repeat cycles,
other reset branches and general production support remain separate gates.

Carriers and timings are association-specific. The retained stock profile uses
different request/reply carriers. Earlier 433.7 MHz-center captures alias one
factory sweep leg; the battery-rejoin capture at 433.9 MHz / 2 Msps resolves all
three observed factory legs, including the approximately 434.684 MHz leg.
Some hub signals still clip. Do not infer absent traffic from a decoder miss.
Keep further qualification in the [roadmap](../PROJECT_ROADMAP.md).
