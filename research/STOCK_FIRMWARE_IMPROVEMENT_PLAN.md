# Local firmware improvement plan — approved source subset

Prepared 2026-09-27 from the [stock firmware reference](STOCK_HUB_FIRMWARE_REFERENCE.md)
and the [local implementation audit](STOCK_HUB_IMPLEMENTATION_COMPARISON_20260927.md).
The user approved ownership cleanup, retained-channel recovery and remaining-time
decoding **in source with tests only** on Sep 27. Those changes are implemented
below. The subsequent unattended-work approval adds full-phase correlation and
bounded HTV145 plan retries with tests; this is **not deployment authorization**.
Other protocol proposals still require review. The
[roadmap](../PROJECT_ROADMAP.md) remains the only live status checklist.

## Basis and boundaries

The approved off-device lookup for this hub's model 289/current version
1.1.1040 returned HTTP 200, `result: 0`, and an empty `data` string on
2026-09-27. No newer image was offered and no firmware was downloaded or
installed. This identifies the offering for this unit/region at that time,
not the latest version for every retail variant or rollout cohort.
[Acquisition evidence](STOCK_HUB_UPDATE_DISCOVERY.md#live-lookup-result--2026-09-27).

Use the retained, integrity-checked **1.1.1040** image as the working baseline;
retain 1.1.1032 for comparison. Stock diagnostic names and defaults do not
justify changing RF packets. The first repairs below are demonstrated defects
in our code, not features copied from speculative stock disassembly. Later RF
changes require an exact stock serializer/capture correspondence.

The follow-up [radio trace](STOCK_HUB_RADIO_PATH_TRACE.md),
[valve trace](STOCK_HUB_VALVE_STATE_TRACE.md),
[sensor trace](STOCK_HUB_SENSOR_RECOVERY_TRACE.md) and
[regression audit](STOCK_HUB_LOCAL_REGRESSION_AUDIT.md) materially narrow this
plan. They add documentation and offline tests only. In particular, they do
not authorize replacing working packet builders or altering live counters.

Preserve throughout:

- Successful pairing prefixes, association-bound transmit authorization and
  generated gateway identities.
- One ACK owner, including during HA/network outages; no incidental expiring
  leases that disable autonomous node ACK service.
- Response-confirmed valve state, bounded watering, duplicate-open protection,
  command spacing and signed OTA/rollback boundaries.
- No experimental stock-firmware replacement, live channel change, speculative
  wake command, unattended re-pairing or production deployment in this plan's
  implementation step.

## A. Confirmed ownership and deletion defects

**Why first.** Two deterministic failure classes are reproduced separately for
sensors and HTV405: a failed old-owner revoke nevertheless configures a replacement;
deletion loses a failed revoke across gateway restart/reconnect. Those failures
can leave a powered radio answering after ownership has moved or a device has
been removed. They do not prove any particular historical RF collision.

**Proposed contract.** Persist an ownership operation before dispatch, with
association, old/requested owners, operation generation and per-step command
IDs. Use an event-driven state machine:

```text
request persisted -> revoke old owner -> matched revoke result
                  -> configure new owner -> matched configure result -> complete
```

No response, a failed write or an error leaves a visible incomplete operation.
It does not authorize the replacement. A socket write is not node execution.
During the interval after confirmed revocation and before confirmed replacement
configuration, distinguish historical owner, desired owner and confirmed active
owner; do not report the historical owner as still actively authorized.

Extend firmware status responses with correlation fields and advertise a new
capability. The gateway accepts results only from the authenticated owner,
for the matching association, generation, command and current connection.
Handle duplicate/stale results idempotently. A matched `authorization_not_found`
can confirm absence; silence cannot. Capability-incompatible nodes must not
silently pass the completion barrier.

Deletion retains a private revocation tombstone even after hiding the HA device.
Reconcile revokes before grants on reconnect. Re-addition cannot bypass pending
revocation. Do not block the receive thread or hold a gateway lock while waiting
for the response needed to complete the operation. If the old radio cannot be
reached, surface blocked handoff rather than choosing a second transmitter.

**Implementation seams.** Gateway `assign_radio_node_ack`,
`_delete_ack_assignment_locked`, reconnect restoration and persistent storage;
`esp32.py` status parsing; `esp32_network.py` session/dispatch correlation;
firmware `routine_ack_configure`, `routine_ack_revoke` and
`reportRoutineAckStatus`. Include the now-reproduced HTV405 revocation defects.
The existing HTV145 durable barrier passes new restart/wrong-owner/stale-result
tests, but does not establish all proposed generation/session or automatic-retry
requirements. Reuse that precedent carefully before sharing helpers. Sensor success
must not be claimed as valve qualification.

**Acceptance.** Promote the existing private red harnesses into `tests/` first.
Cover dispatch failure, lost response, stale/duplicate response, reconnect
without radio reboot, gateway restart at every boundary, overlapping requests,
delete/re-add, replacement configuration failure and normal completion. Native
tests prove correlation/authorization transitions without changing RF replies.
HA exposes pending/failed cleanup or handoff, disables duplicate actions and
never equates queued work with completion. Separate approved RF observation
must ultimately demonstrate at most one on-air owner.

## B. Retained channel consistency

**Evidence.** The gateway accepts persisted sensor selectors 4 and 5, but known
rejoin currently omits the saved selector and firmware initializes the pairing
selector to 4. This is a cross-path inconsistency, not proof that a reference
selector-4 sensor failed for this reason. The private failing request-field test
now reproduces it; separate passing tests prove selectors 4/5 survive storage
and ordinary reconnect. Fix the rejoin seam, not working persistence.

**Proposal.** Carry and validate the association's retained selector through
gateway request, firmware profile construction, RAM ACK authorization and
reconnect restoration. Keep new enrollment's proven selector-4 prefix unchanged.
If a retained selector is unsupported, return an explicit unsupported recovery
state rather than silently changing it. Do not implement automatic channel
allocation or the stock app's channel-switch feature in this repair.

**Acceptance.** For each supported selector, test persistence, request fields,
reply construction and authorization/restoration consistency. Reject malformed
or unsupported selectors before transmit. Existing selector-4 pairing fixtures
remain byte-identical. Selector-5 physical acceptance remains a separate gate.

## C. Measurement freshness versus link liveness

**Evidence.** The real decoder/ingestor, SQLite restart and HA reporting-property
tests pass: fresh soil ACKs, accepted nonmeasurement traffic and invalid frames
do not refresh old moisture. A real measurement does. **No reachable soil
freshness defect was found on these paths; no runtime repair is proposed.**

**Remaining verification.** The checked-in checkout does not include the complete
deployed scheduled moisture-decision automation. Its stale-input fallback and
notification behavior are therefore not qualified by these tests. Review that
configuration separately when authorized. Valve state versus link timestamps
remain a presentation distinction, not evidence of a soil watering defect.
Preserve the passing regressions and the user's stale-input irrigation policy.

**Acceptance.** Fresh heartbeat/ACK/configuration traffic never refreshes an old
moisture measurement. Real measurement refresh clears the warning. Scheduled
watering applies the configured stale-data fallback, with visible reasons and
notifications. A 60-minute stock offline default is not automatically the local
watering freshness threshold.

## D. Evidence-gated recovery and channel behavior

**Question.** What does the stock hub configure or acknowledge that keeps
devices reporting, and how does retained recovery differ from enrollment?

**Established limit.** `ControlReportMode` reaches a local mode-byte update and
server acknowledgement; that direct path is not a soil wake transmitter. The
[downstream trace](STOCK_HUB_REPORT_MODE_CONSUMERS.md) connects it to class-0x50
report replies; captured HCS026 class 0x48 is excluded. It requires an incoming
report, so it cannot wake a radio-silent device. Heartbeat selector 31 uses a descriptor
lookup, so it is not automatically wire type 31. The compact-state grammar is
corroborated in both retained versions and passes exhaustive local-parser tests.

**Offline investigation.** Continue model-qualified heartbeat descriptor
mapping and remaining reconnect triggers. The reconnect-result-9 header,
gateway-identity migration setter and stored flag are now traced, but device
acceptance has no matching RF capture. `ReciCH` is traced to native command
`20`; channel-change acceptance and absolute RF mapping remain unqualified.
Separate internal channel indices, app addresses, factory sweep counters and
valve command counters. Compare code/data across retained versions without
assuming that a missing diagnostic means a missing feature.

**Promotion rule.** A behavior becomes an implementation proposal only with a
version/model-scoped request/reply mapping and a matching captured exchange.
Freeze the accepted boundary as a regression fixture, then change only the next
unproven boundary. Neither an offline timer nor a reconnect function name proves
a remote wake command for a radio-silent sensor. Do not add periodic speculative
transmissions while this remains unresolved.

**Acceptance.** After separate hardware approval, exercise device-originated
rejoin, ordinary network reconnect and battery change independently. Verify the
same association/HA identity and no duplicate owner. Channel migration requires
its own coherent before/after and failure/rollback evidence; it is not bundled
with the retained-selector repair.

## E. Remaining valve and RF protocol boundaries

**Established representation.** Stock sync is `f3e9105e`, native payload is
32 bytes, and hardware CRC uses seed `a8a8`. The legacy normalized frame starts
one bit earlier. All observable CRC bits match for 516/518 unique public frames;
the exceptions are explicit corrupted/synthetic controls. Both legacy residues
can be valid and differ in the final native payload bit. Preserve the legacy
API and fixture format while introducing any separately reviewed native-byte
research codec; do not globally change residues or live RF settings.

**Established control path.** The traced stock generator has a six-bit sequence;
retries reuse a built packet; pending replies match command, sequence and both
identities. Native command `21` carries port/control-mode/work-mode and a
little-endian seconds value. Normalized `82`/`81` in byte 15 encode payload
length, not separate open/close opcodes. This explains marker alternation without
proving what unexpected sequences a valve accepts or when its state resets.

**Concrete decoder repair proposal.** A captured HTV405 900-second run reports
895 remaining seconds in native bytes; our decoder masks the low seconds bit
and returns 894. Add the captured failing case to the production decoder tests,
then preserve the entire value using the proven byte boundary. Cover odd/even,
zero, field limits and both valve families. Do not rewrite existing capture
annotations to manufacture a pass or alter command generation in this fix.

**Remaining investigation.** Map model/port capabilities, retry/expiry limits,
post-boot sequence restoration/advancement, and the HTV145 terminal continuation
(native command `59`, reply `D9`). The early boot clear now demonstrably zeros
the stock shared sequence byte; that is not a valve-side counter-reset rule.
A per-port, length-prefixed parameter fallback fits the captured terminal replies.
The [retained HTV145 descriptor](STOCK_HUB_POSTBOOT_TRACE.md) now qualifies that
branch for fresh initialization with this configuration: its terminal value is
an empty array. HTV405 and historical runtime configurations remain unqualified.
The source retry repair below preserves the first reply and terminal payload.
Physical mode selection,
absolute channel mapping and complete on-air CRC-bit observation still require
separate evidence. Never copy CMT-specific register bytes into CC1101 settings.

**Acceptance.** Preserve operational pairing prefixes and known open/close,
duration and summary fixtures. Any proposed change needs a failing fixture,
an exact explanation of the stock behavior, and model-qualified response
evidence. Expand tests for action ordering, stale/duplicate responses and
pending-command recovery. Do not change fields such as battery, usage or CRC
residue from shared-image vocabulary alone. Live valve trials remain separately
authorized; production irrigation is not an automatic research test fixture.

## Delivery and qualification

### Approved source implementation (Sep 27; not deployed)

`ack_ownership.py` stores a versioned journal in SQLite metadata before dispatch.
Explicit sensor/HTV405 owner changes keep their previous durable assignment until
both old-owner revoke and new-owner configure are confirmed. Deletion retains a
revocation tombstone independently of the hidden registry row. During cleanup,
ordinary restore, known sensor rejoin, reassignment and HTV405 control cannot
bypass the barrier. Pairing is blocked while any cleanup is pending; removing a
radio still owning RF devices is rejected. Existing autonomous ACK tables have
no new leases or expiry.

Firmware capability `correlated_ack_ownership` adds a separate
`ack_ownership_status` response carrying kind, endpoint, command ID, operation
generation and connection token. A successful revoke includes an already-absent
authorization. Ordinary ACK telemetry cannot finish cleanup. The gateway requires
the current authenticated owner/session and exact correlation fields. Reconnect
reissues only the pending step with a fresh command ID; repeated restore calls
in the same connection do not flood the node. Silence stays pending, not success.
Delivery errors and rejected configuration remain blocked until retry on reconnect.
Do not downgrade to gateway code that ignores this journal while operations are
pending: complete cleanup first. An empty journal leaves ordinary existing
assignment storage compatible; no live database migration was performed here.

The gateway API exposes compact `ack_ownership_operations`; each HA radio gains
an **ACK ownership cleanup** diagnostic (`ready`, `pending`, `blocked`) with
operation details. It remains readable when the radio is offline. Historical
owner is not presented as a confirmed active owner during the transition.

Known sensor recovery includes `assigned_channel`. Firmware validates 4/5 before
constructing a reply; a missing field fails explicitly. New enrollment still
uses selector 4. Capability `retained_sensor_rejoin_channel` prevents a newer
gateway from sending selector-5 recovery to older firmware that ignores the field.
Coordinate gateway/node rollout; an old gateway's field-less rejoin is rejected
by the new firmware, not silently guessed.

Remaining seconds now reconstruct native little-endian bytes without discarding
the low bit. Command encoding is unchanged. Captures retain their historical
decoder annotations; runtime regression expectations use the actual native value.

Qualification uses `test_ack_ownership.py`, `test_stock_informed_regressions.py`,
`test_remaining_time_regression.py`, the real RF/HTTP tests and native C++ profile
tests. Faults include disk-write failure, failed/lost delivery, stale session,
wrong owner/endpoint/generation, duplicate results, restart after deletion,
rejected replacement configuration and synchronous response delivery. The latter
exposed a callback deadlock; the gateway now uses a reentrant lock while still
never waiting for a response inside the dispatch path.

Initial offline validation: **678 Python tests run, 676 passed, two optional
NumPy-dependent tests skipped**; native C++ protocol tests passed; the unified
`rainpoint_bridge` PlatformIO build passed (83.4% flash, 16.5% RAM).
The real loopback transport authenticates both new capability names and forwards
correlation metadata. HA property tests verify cleanup remains visible while a
radio is offline. No rendered live-HA or physical-radio test was performed.

This change does not redesign firmware's automatic ACK grant at pairing
completion. Re-pairing a known endpoint through a different radio requires a
separate pre-grant ownership audit/test; it must not be mistaken for qualification
of the explicit reassignment API. The successful RF pairing prefixes are unchanged.
Stock channel migration, reconnect result 9 and terminal-payload changes remain
research proposals. The follow-up source repairs below are also not deployed.

### Follow-up source repairs and evidence (Sep 27)

**Response correlation.** Both node handlers compare all six native phase bits
against the retained command frame. Gateway negative-response paths validate the
sixth bit using their current command/profile policy as well as the existing
route/reservation checks. Unmatched HTV145 positive responses leave the pending
command intact instead of invalidating it. The separately qualified phase-zero
idle-anchor exception is preserved. This does not change counter generation,
duration encoding, retry spacing or the accepted negative-reply grammar.

**Single-zone pairing retry recovery.** While awaiting terminal stage 5, the
native session can answer the preceding plan request up to four more times
within ten seconds of its first reply. It accepts only the same association,
command, port, length and body with a valid trailer. Observed phases may repeat
or advance by at most four from the original, never move backward. Each reply
echoes the observed six-bit phase; retries do not advance logical progress or
extend the window. Following a retry, the terminal request must use the next
phase. The original first replies remain byte-for-byte identical. Receive-edge
capture stays enabled while awaiting this seam, and status exposes
`htv145_plan_reply_retries` / `plan_reply_retransmitted`.

Four replies/ten seconds are bounded local policy covering the captured retries,
not universal valve limits. The initial RF rejection and full 6/6 hardware
completion remain unproven. No new terminal value or early pairing-stage change
is introduced.

`tests/test_command_response_correlation.py` covers real Python durable-state
paths and actual native handler branches compiled with real decoders and fake
I/O. `tests/test_htv145_pairing_retries.py` compiles the native session tests:
frozen replies, phase progression, malformed inputs, retry cap/window, stale
terminal, expiry, cancellation and reply deadlines. Authenticated loopback
transport verifies retry diagnostics. Historical red evidence is retained, not
rewritten. The full suite now runs **688 tests: 686 passed, two optional
NumPy-dependent skips** on the final rerun; native protocol checks pass. The
unified firmware build passes at **1,093,277 bytes flash (83.4%) and 54,144 bytes
RAM (16.5%)**. The full compiler caught a status callback argument-order error;
it was repaired and the handler test now imports the actual callback signature.
Firmware command-boundary checks pass. Two local unsigned preview packages are
byte-identical, pass the public-artifact check and start/restart an isolated TLS
gateway successfully. A temporary Git index includes the new ownership module
for this check without changing the real index or making a release. Hardware
timing and reception are not simulated by these tests.

The additional research rules out the class-0x50 report-mode path for HCS026 and
qualifies HTV145's retained terminal descriptor. Stock startup notifications can
consume sequence values before device acceptance; neither that fact nor boot
zero-fill establishes an overnight reset rule. See the
[post-boot trace](STOCK_HUB_POSTBOOT_TRACE.md) and
[report consumers](STOCK_HUB_REPORT_MODE_CONSUMERS.md).

The [short validation procedure](../docs/STOCK_INFORMED_VALIDATION.md) stages
source review, coordinated canary deployment, dry-valve testing and later normal
irrigation observation. No physical actions have been performed by this work.

### Subsequent offline lifecycle research

The [ACK/timeout trace](STOCK_HUB_ACK_RETRY_LIFECYCLE.md) establishes four stock
retransmissions on a 700-ms periodic timer, retaining the complete command and
phase. Queue expiry reports local failure; a matched negative reply consumes its
own transaction. Neither path establishes counter reset or a corrective RF
exchange. Conditional result forwarding can consume a generated phase before
replacing the on-air value with an echoed phase, so visible commands are not a
complete generator ledger. The
[two-version comparison](STOCK_HUB_VERSION_COMPARISON.md) finds the same generator
instructions and full-phase ACK matching in both retained images.

These results reinforce exact retransmission/correlation and explicit failure
categories. They do not justify copying stock retry counts into our live nodes,
changing the successful prefix, or adding a counter sweep. Keep the short canary
unchanged; preserve its command/reply trace. Model-qualified sensor lifecycle
findings are linked from the roadmap. No further runtime change was made in this
research pass.

Implement after review in small, independently tested changes: correlated node
contract, durable gateway lifecycle, HA feedback, retained-selector consistency,
and the independently reviewed remaining-seconds decoder repair. No soil
freshness correction is currently justified. Keep later RF research changes separate
from these lifecycle fixes and from PCB work. Coordinate capability rollout so
older nodes cannot falsely acknowledge the new contract.

For each implementation change, run the relevant real-seam Python regressions,
the native C++ protocol tests and the production `rainpoint_bridge` build, then
the full CI Python suite with required localhost/cache permissions. Preserve
source, data-migration and rollback evidence. Use the idle OTA test node first
only after deployment approval. Do not migrate live storage or update garden
radios during source validation.

The review decision is approval of the proposed contracts and sequence, not a
claim that all stock behavior has been decoded. The reference's unresolved
coverage map remains explicit. New findings should refine this design and the
single roadmap before changing proven RF behavior.

## Stock hardware port: deliberately later

After local reliability and relevant protocol gaps are qualified, reassess
ESP32-S3/CMT2300A support as a separate radio backend sharing the protocol and
association state machines. It needs physically verified pins/interrupts,
board-specific signed images, a preserved stock reference, and an approved
restore/RX-first validation procedure. No binary patch, vendor-key reuse,
replacement firmware or new hardware abstraction is authorized by this review
draft. See [the feasibility assessment](STOCK_HUB_CUSTOM_FIRMWARE_FEASIBILITY.md).
## Native pairing comparison follow-up — Sep 28

The [cross-device comparison](PAIRING_NATIVE_COMPARISON.md) and
[configuration trace](STOCK_HUB_PAIRING_CONFIGURATION_TRACE.md) now separate
shared command envelopes from per-model stored settings. Native `20` carries a
configuration version, not an RF channel in its first data byte; no transmitter
was changed on the basis of this correction. Existing capture-derived reply
bytes and model-specific state machines remain frozen.

Three recorded failures replay through the actual HTV145 C++ session with four
bounded plan retries and no false terminal completion. Wrong route/command,
length, phase and time-window cases remain rejected. The complete offline suite
ran 698 tests (696 passed, two optional-dependency skips), and the standalone
native protocol test passed. Only research helpers, tests and documentation
changed in this pass. Earlier approved runtime repairs remain undeployed.

The short [canary procedure](../docs/STOCK_INFORMED_VALIDATION.md) remains the
next physical discriminator: ask before arming, capture the valve's requests
and responses, preserve the prefix, and count completion only if the valve
actually progresses. No extra stock pairing or battery cycle is implied.
