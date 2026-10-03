# Stock-hub findings versus the local implementation

Offline source/fixture comparison, 2026-09-27. This note compares the retained
[stock analysis](STOCK_HUB_FIRMWARE_ANALYSIS_20260927.md) with current source;
it does not infer undocumented wire formats from diagnostic names. No live
system changes, RF transmissions, or deployment were performed. Private dump
analysis remained local; no credentials or raw firmware are published here.
Runtime source remains unchanged. Status belongs only in
[PROJECT_ROADMAP.md](../PROJECT_ROADMAP.md).

Follow-up: the [expanded regression audit](STOCK_HUB_LOCAL_REGRESSION_AUDIT.md)
reproduces HTV405 lifecycle and retained-selector defects, rules out a reachable
soil-freshness regression on tested ingestion paths, and records the full-suite
result. The [review plan](STOCK_FIRMWARE_IMPROVEMENT_PLAN.md) incorporates those
results and the later native-frame findings; this note preserves the initial audit.

## Findings

References below use repository-relative `file:line` locations. Confidence is
about the stated finding, not a claim of observed field failure.

| Comparison | Confidence / classification | Local evidence | Impact and next validation |
| --- | --- | --- | --- |
| Sensor ACK owner handoff fails open if old-owner revocation cannot be delivered. | **High; reproduced local reliability bug**, independent of stock ACK internals. | `rainpointd_addon/rainpointd/gateway.py:2655` sends revoke, catches its delivery errors at `:2669`, then persists/configures the replacement at `:2671`. `firmware/rainpoint_bridge/src/main.cpp:3504` and `:3552` answer authorized reports without a connection predicate; RAM authorization changes through explicit authorize/revoke (`firmware/rainpoint_bridge/include/rainpoint_ack.h:49`, `:103`). | A network-disconnected but powered former owner can continue ACKing while its replacement is enabled. A single database owner does not guarantee one on-air owner. The offline harness below reproduces the handoff defect; actual RF collision was **not** measured. A fix needs confirmed revocation or independently established old-node shutdown, not only successful enqueue. Regress failure, missing completion, delayed completion, restart mid-transfer, and successful transfer. |
| Sensor removal loses failed revocation work. | **High; reproduced lifecycle defect.** | `_delete_ack_assignment_locked` (`gateway.py:2703`) deletes the row before dispatch and ignores failure. `esp32_network.py:373` restores only surviving assignments after reconnect. | A removed sensor can remain authorized in the powered node's RAM. The private removal harness shows no retry after gateway restart/reconnect. Preserve durable revocation work even if the HA record is hidden; prevent re-addition from granting a conflicting owner. No actual orphan ACK transmission was measured. |
| Retained sensor factory rejoin does not carry the saved selector. | **High code mismatch; medium deployment relevance**, not proof that current selector-4 installations fail. | ACK assignment explicitly accepts selectors 4 and 5 (`gateway.py:2591`). Rejoin copies IDs, offset and power, but omits `assigned_channel` (`gateway.py:3895`). Firmware sets selector 4 even for known rejoin (`main.cpp:2833`, `:2843`), then replaces its RAM ACK authorization from that profile (`main.cpp:3068`). | New automatic enrollment is intentionally selector 4 (`protocol_documentation/hcs026frf.md:32`); the concern is an existing selector-5 assignment. A deliberate migration to 4 also needs durable agreement, or reconnect restores selector 5 (`gateway.py:2697`). Parameterize the known-rejoin test with stored selectors 4/5 and inspect assignment reply, RAM owner config and reconnect restoration together. Obtain controlled selector-5 retained-rejoin evidence before changing wire behavior. |
| Stock heartbeat/offline defaults versus local reporting status. | **High; intentional policy distinction**, not a wake/recovery bug. | Stock analysis establishes fallback heartbeat 480 seconds and offline 60 minutes with overrides. Local HCS02x reporting threshold is 900 seconds (`gateway.py:94`); `_add_reporting_status` explicitly does not change availability (`gateway.py:7200`). HTV145 threshold is six hours. | Do not replace local values mechanically with stock defaults. They describe different policies. First resolve stock report-mode/configuration serialization and compare actual report cadence; any UI alignment should preserve separate availability and reporting meanings. |
| Silent-sensor recovery still requires device-originated traffic and the existing owner. | **High; intentional evidence/safety boundary.** | Known factory announcement is required, with enrollment, owner, capability and connection checks (`gateway.py:3810`); automatic request is 60 seconds with a 90-second cooldown (`:3857`, `:3903`). Paired recovery matches an authorized route (`rainpoint_ack.h:268`). | Stock offline timing does not establish a remote wake command. Preserve bounded recovery; trace a proven report-mode serializer and correlate controlled outages before claiming a missing wake operation. Native fixtures already lock the paired recovery replies and unknown-route rejection (`firmware/rainpoint_bridge/tests/protocol_test.cpp:669`). |
| ACK timing/CRC behavior should remain capture-backed. | **High; intentional validated implementation.** | Sensor ACK delay is 150 ms after receive, 320-symbol wake, 250-ms deadline (`rainpoint_ack.h:14`); routine replies preserve the received residue (`:395`). Recovery reply residue is phase-specific (`:347`). | Stock ACK function names and its unmapped structure-byte checks do not supersede these on-air fixtures. Trace sender/serializer into normalized frame offsets, then compare complete frames and RX-to-TX timing before revising them. |
| Valve command counters, physical state, and historical summaries are already separated. | **High; existing safety boundary.** | HTV145 controller requests publish intent only (`rainpointd_addon/rainpointd/rf.py:307`). Responses require durable reservation and association marker (`rainpointd_addon/rainpointd/htv145_control.py:332`); historical summaries return without changing current physical state (`:348`). Independent state confirmation cannot authenticate the reserved counter (`:365`). Fixed-zero result-3 exception is narrow (`rainpointd_addon/rainpointd/valve_protocol.py:584`). | Neither stock `ser` nor `MCU restart` diagnostics prove counter reset/rejoin semantics. Keep current rules. Any replacement needs request/response pairs through rollover, rejection, power-cycle and repeated summary during a later run; no startup close or counter search is justified. |
| Packet liveness is not necessarily measurement freshness. | **High; explicit existing distinction**, scope for presentation audit rather than proven bug. | `gateway.py:4600` exposes most recent valid RF reception as `observed_at` while preserving `state_observed_at` when different; reporting age uses `observed_at` (`:7211`). HTV405 state-less reports retain prior state timestamp (`:3390`). | A recovered RF link can be reporting while its displayed physical measurement is older. Before changing freshness UI, regress a fresh non-state packet with an old measurement and verify consumers display the intended timestamp. Do not infer a new moisture measurement from stock heartbeat receipt alone. |
| Product capabilities and raw battery/configuration fields are not generally implemented from the stock vocabulary. | **High local scope boundary; stock wire mapping unresolved.** | Product families enumerate soil sensors and irrigation valves (`rainpointd_addon/rainpointd/product_identity.py:43`). HCS02x battery is categorical 100/10 from the validated status bit (`rainpointd_addon/rainpointd/rf.py:251`). HTV405 water usage is explicitly removed (`gateway.py:4580`). | Stock rain-gauge/flow-meter, soil threshold, timezone/DST or dynamic-capability identifiers are research leads, not proof that those fields exist in routine frames or apply to tested hardware. Require model-qualified captures and decoded field provenance before adding entities or changing battery semantics. |

## Reproduced ACK handoff defect

The temporary diagnostic `/tmp/rainpoint_stock_comparison_regression.py` uses
`tests.support.CapturedInstallationGateway`, `observe_captured_sensor_route`,
a temporary SQLite database, and a fake command sender. It enrolls one fixture
sensor, assigns owner A, connects owner B, injects `ConnectionError` only for
`routine_ack_revoke`, then requests owner B. Its invariant is that failed
revocation must retain owner A and must not send owner B a configure command.
There are no network listeners or hardware actions.
The reproducer is also retained privately under
`captures/stock-hub-firmware/2026-09-27-adzoj0e3/analysis/ownership-handoff-regression.py`.

Invocation used (bundled Python has the required `cryptography` dependency):

```text
/Users/federicoholgado/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 /tmp/rainpoint_stock_comparison_regression.py
```

Observed result, with test-fixture node labels shortened:

```text
persisted_owner: B
attempted_commands: [(A, routine_ack_revoke), (B, routine_ack_configure)]
AssertionError: failed revocation must preserve old owner
Ran 1 test in 0.012s
FAILED (failures=1)
```

The existing owner-persistence test checks successful command dispatch and one
database row, but not a failed revoke or confirmed completion
(`tests/test_rainpointd.py:1474`). The existing known-rejoin test uses only
selector 4 (`tests/test_rainpointd.py:1282`, `:1324`). These are the appropriate
regression seams; extending these tests does not require live RF.

## Checks performed

Follow-up removal test: `/tmp/rainpoint_ack_removal_regression.py` uses the same
fixture gateway and temporary database. It configures owner A, injects a revoke
delivery failure during `forget_sensor`, closes/reopens the gateway, then calls
the real reconnect restoration seam. Result: **one failing test in 0.018 s**;
the assignment is gone and reconnect sends no revoke. A private copy is retained
beside the handoff harness as `analysis/ack-removal-regression.py`.

For this follow-up the ranked explanations were lost revocation work, a
reconnect-time authorization clear, or an independent cleanup path. Source
inspection of `esp32_network.py`'s authenticated reconnect and all accesses to
`routineAckAuthorizations` in `main.cpp` finds restoration but no reconnect clear;
the RAM authorization is modified by explicit configuration/revocation or local
pairing. This supports the first explanation. A node reboot would clear RAM,
but a network reconnect is not a reboot. A durable tombstone is a proposed fix,
not something the current test assumes exists.

An additional focused run of the owner-persistence, known-rejoin and sensor-link
diagnostic tests, plus `tests.test_rainpoint_pairing_protocol` and
`tests.test_rainpoint_rf`, passed **117 tests**. The main audit independently
reran the failure-injection harness and reproduced the failed invariant.

The existing owner persistence test, known factory-rejoin test, and complete
`tests.test_rainpoint_protocol` module pass: **17 tests**, using the bundled
Python with the repository-required localhost-binding permission. The native
protocol test also compiles and exits successfully:

```sh
c++ -std=c++17 -Ifirmware/rainpoint_bridge/include \
  firmware/rainpoint_bridge/tests/protocol_test.cpp \
  -o /tmp/rainpoint-stock-comparison-protocol-test
/tmp/rainpoint-stock-comparison-protocol-test
```

This was a focused audit, not the complete CI suite or a hardware qualification.
No fix was applied. The ACK handoff reproduction establishes a local failure
mode; it does not establish that it caused any particular historical sensor
outage. The selector finding remains a cross-path consistency question until
the supported recovery contract and controlled selector-5 evidence agree.

## Repair approach

Priority and completion stay in the roadmap. These are proposed contracts and
acceptance evidence, not authorization to deploy.

### ACK ownership and deletion

Use a durable operation identified by sensor/association, old owner, requested
owner and an operation generation. Persist the request before dispatch. Keep
the old confirmed owner until a matching authenticated node response establishes
revocation; only then configure the new owner, and publish completion only after
its matching configuration response. Timeouts leave a visible pending/failed
operation, not a silent ownership change. A successful socket write establishes
neither node execution nor RF behavior (`esp32_network.py:132`).

The current `reportRoutineAckStatus` (`main.cpp:2966`) includes endpoint/state
but **not command ID or generation**. Extend the node contract and publisher
before relying on it as a completion barrier. Match node, association, command,
generation and current session; ignore duplicate, delayed and previous-session
responses. Treat an authenticated, correlated `authorization_not_found` as an
idempotent absence result, not as proof inferred from a disconnected node.
Do not synchronously wait under the gateway lock or in the pre-receive reconnect
hook: the same receive path must remain able to process completion events.

For deletion, retain a private revocation tombstone after hiding the HA device.
Show remote cleanup as pending if its owner is offline. Drain/reconcile pending
revocations before restoring grants on reconnect. Re-addition must not bypass a
pending revoke by configuring another owner. Review equivalent HTV405 removal
and owner paths (`_revoke_htv405_ack_locked` also catches delivery errors); the
sensor test does not qualify valves automatically.

Preserve ACK autonomy during ordinary HA/network outages. Do not introduce
automatic short-expiry leases as an incidental fix: that would change the
outage behavior we deliberately rely on. If the former owner cannot be reached,
handoff remains blocked unless shutdown/reset is independently established.
Roll out capability-aware correlated responses before enabling the new handoff
path; old firmware must not be treated as having confirmed an operation it
cannot acknowledge.

Acceptance includes failed dispatch, no response, stale/duplicate response,
node reconnect without reboot, gateway restart at each boundary, concurrent
requests, deletion/re-addition, new-owner configuration failure, and normal
successful transfer. Migrate the private red harnesses into `tests/` with the
implementation, then add protocol/parser and native node tests. Physical
single-owner RF verification remains a separate approved test.

### Retained channel and freshness

For retained rejoin, pass and validate the persisted selector end to end, or
explicitly reject unsupported retained selectors. A deliberate channel migration
must update storage and radio state together. Test selectors 4/5 through rejoin
reply construction, RAM authorization and reconnect restoration. Keep the
proven selector-4 new-enrollment prefix unchanged; selector-5 wire acceptance
still needs physical evidence.

For freshness, audit consumers of `observed_at` against `state_observed_at`.
Create deterministic cases with an old moisture/state measurement and a new
heartbeat/non-state frame. Communication health may become fresh, but moisture
warnings and stale-input irrigation fallback must not. Assert this through
gateway, HA entity attributes and the reference automation. Change timestamp
contracts only where those tests demonstrate a mismatch; current separation is
not itself a bug.

### Research-driven changes

Trace stock configuration setters through serialization to normalized RF frames,
then replay those frames through existing decoders. Use passive bus/SDR captures
to resolve any missing boundary. Do not change recovery, counter or ACK rules
from diagnostic names, modem defaults or a firmware-version comparison alone.
Promote the smallest redacted exchange into a fixture before a runtime change.

## Stock paths worth tracing next

Addresses refer to the newer OTA application's virtual address space, not flash
offsets. Diagnostic names and candidate function entries are navigation aids;
only described instruction behavior is treated as established.

| Path | Evidence and limitation | Question it could answer |
| --- | --- | --- |
| Report mode | `bd_sdev_comm_set_report_mode`, candidate entry `0x4204463c`, checks several record fields (including a byte equal to `0x50`) before a call to `0x42044170` and storing a mode byte. The record fields and transmitted serialization remain unmapped. | Does the stock gateway configure device reporting behavior, and for which models? This is not yet evidence of a soil-sensor wake command. |
| Capability and per-port parameters | `bd_sdev_comm_deal_sensor_support_function` (`0x4203f0f0` candidate), `bd_sdev_comm_parse_sensor_fun` (`0x420409ac` candidate), and `bd_sdev_comm_parse_ctl_param_by_port` (`0x4203dfd0` candidate); format strings mention default work time, soil, humidity threshold and calibration. | Which settings and entities are genuinely supported by each model, versus generic firmware features? |
| Reconnect and parameter synchronization | Diagnostics at `0x3c1527c8`, `0x3c152720`, and `0x3c154840` distinguish reconnect ACK, parameter retry and connection-confirmation ACK. Their transport layer and wire fields are not established. | Is there an additional association/readiness exchange relevant to recovery? Do not equate these names with valve counter synchronization. |
| Rain-gauge reset and calibration | Diagnostics at `0x3c150994`, `0x3c1509b0`, and `0x3c1509c4` describe restart, initial/current rain totals and coefficient changes. | How should future rain-gauge support handle resets, accumulation and calibration without false rainfall spikes? |
| Timezone/DST | `bd_common_get_tz_min_offset_relative_to_utc0` and a diagnostic at `0x3c14b59c` distinguish timezone, DST and total offset. | How are time fields serialized across offsets and DST transitions? Validate against existing timezone work rather than assuming local-time constants. |

Generic firmware contains flow-meter and battery diagnostics, but neither
establishes water-volume support on the four-zone valve nor a numeric battery
percentage. Continue model-specific decoding and retain the existing capability
restrictions until supported by packet evidence.
