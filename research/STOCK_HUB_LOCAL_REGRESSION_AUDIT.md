# Stock-informed local regression audit

Offline audit, 2026-09-27. Scope: current source, capture-backed fixtures,
temporary SQLite databases and fake command senders. No runtime source edit,
Home Assistant access, device command, deployment, or RF transmission occurred.
This note refines the evidence behind the
[proposed improvement plan](STOCK_FIRMWARE_IMPROVEMENT_PLAN.md), not its approval
or implementation status. The [roadmap](../PROJECT_ROADMAP.md) is the only live
status checklist.

**Subsequent source repair:** the failures below describe the pre-fix baseline.
The user later approved source/tests only. Public regressions now cover the
retained-selector repair and journaled explicit sensor/HTV405 handoff/deletion;
see the [implementation record](STOCK_FIRMWARE_IMPROVEMENT_PLAN.md#approved-source-implementation-sep-27-not-deployed).
No hardware acceptance or production deployment is implied.

## Findings

| Question | Result | Evidence |
| --- | --- | --- |
| Can fresh soil ACK/nonmeasurement traffic hide an old moisture reading? | **Ruled out for the tested real ingestion paths.** The soil device remains stale; a real accepted moisture report restores freshness. | New tests in `tests/test_stock_informed_regressions.py:56`, `:78`, `:112`; `ingest.py:288`, `:341` |
| Is the saved selector preserved by storage/reconnect? | **Yes**, selectors 4 and 5 survive SQLite reopen and generate matching configure commands. | New test `tests/test_stock_informed_regressions.py:128`; `gateway.py:2428`, `:2690` |
| Does known factory rejoin carry retained selector 5? | **No; deterministic failing invariant.** The request omits `assigned_channel`; firmware starts with selector 4. | Private red test; `gateway.py:3890`; `main.cpp:2833` |
| Does HTV405 share the sensor handoff/deletion defects? | **Yes; both reproduced independently.** Failed old-owner revoke still grants the replacement; deletion loses failed cleanup after restart/reconnect. | Private red tests; `gateway.py:2331`, `:2547`, `:6704` |
| Is HTV145 a useful lifecycle precedent? | **Yes, with qualifications.** Failed revoke is durable and blocks restoration; wrong-owner/stale replies do not delete it; a matching reply does. | New test `tests/test_stock_informed_regressions.py:151`; `htv145_runtime.py:97`, `:167`, `:178` |

Paths above are repository-relative; gateway/ingest/runtime files are under
`rainpointd_addon/rainpointd/`, and firmware `main.cpp` is under
`firmware/rainpoint_bridge/src/`.

## Freshness: reachable soil behavior versus hypothetical snapshots

The decisive boundary is `FrameIngestor._consume_observations`. In the
no-moisture branch, only a valve-originated frame gets a `device_id`; soil
ACK/configuration/nonmeasurement frames are retained as raw events without
one (`ingest.py:288-344`). Reception metrics require a device identifier
(`storage.py:4208`). Therefore the gateway's generic ability to substitute
`last_valid_frame_at` for `observed_at` (`gateway.py:4600`) does not mean these
soil frames can refresh the moisture device.

The new test feeds a trailer-valid captured 56% moisture frame at 10:00 UTC,
then a trailer-valid captured stock ACK at 12:00 UTC through **the actual
decoder and ingestor**, closes/reopens SQLite and the gateway, and checks:

```text
soil_moisture_percent = 56
observed_at = 2026-09-20T10:00:00+00:00
report_age_seconds = 7200
reporting = False
```

It invokes the actual HA `RainPointReportingBinarySensor.is_on` and attribute
properties using the repository's AST callback harness with a fake device
lookup. HA still returns false and age 7200. Feeding the real moisture frame
at 12:00 then returns age 0 and reporting true. This is a property-level HA
test, not a running Home Assistant integration or browser test.

A second positive test uses an explicitly **synthetic** valid type-4
nonmeasurement frame on the captured association, with the measurement bytes
removed and its known residue recomputed. It proves accepted nonmeasurement
traffic is not assigned to the soil device; it does **not** establish an
observed sensor heartbeat serializer. A third damages the measurement CRC
and proves invalid traffic cannot refresh the old measurement.

The checked-in Front Yard dashboard's stale gauges use the reporting binary
sensor (`examples/federico-garden/garden-local-dashboard.yaml:301-363`). The
verified false/true projection therefore selects the stale/normal card for
the tested event class. The generic HA report-time sensor uses `observed_at`
(`custom_components/rainpoint_local/sensor.py:179`); the moisture entity has no
separate measurement timestamp attribute. For soil, the tested ingestion
boundary keeps that timestamp aligned with accepted measurements.

There remains a presentation distinction for valves: gateway snapshots can
contain old physical state plus newer link traffic, and `state_observed_at`
is not exposed by these generic sensor/report attributes. Existing HTV405
tests already preserve the older physical-state timestamp. This is an
observability limitation, **not demonstrated stale-moisture irrigation
failure**. An artificial call to `observe_rf_frame(device_id=<soil id>)`
would bypass the ingest guard and is not appropriate evidence of a reachable
soil regression.

The checkout does not contain the complete scheduled moisture/stale-input
decision automation. It contains dashboard/control-script adapters and
`scheduled-duration.jinja`, not the upstream decision helpers. The duration
adapter's existing tests remain relevant but cannot verify stale-data
fallback or notifications. No live configuration or secret-bearing backup
was inspected. The plan should retain this explicit verification limit,
rather than claim that deployed scheduled watering is either defective or
fully qualified.

## Retained selector: narrower location of the defect

Both supported selectors pass the new persistence/restoration test, including
the paired/controller/companion route fields. The defect is therefore not a
general selector-5 storage failure.

The private red test retains selector 5, injects a known factory announcement
through the gateway's existing automatic-rejoin seam, and confirms a bounded
`pairing_start` request is generated. Its desired field invariant fails:

```text
AssertionError: 5 != None : retained selector 5 must reach known-rejoin request
```

`gateway.py:3890-3907` copies association and RF parameters but not the saved
selector. `main.cpp:2833` initializes `pairingAssignedChannel = 4`; the known
rejoin builder receives it, and completed pairing uses it for RAM ACK
authorization (`main.cpp:3070`). Reconnect independently restores persisted
selector 5. This supports the plan's cross-path consistency repair, while
remaining distinct from physical selector-5 acceptance or causation of a
selector-4 installation's historical outage.

## HTV405 and HTV145 lifecycle comparison

The HTV405 handoff harness creates an accepted temporary valve association,
configures its old owner and a capable replacement, and fails only
`htv405_routine_ack_revoke`. The actual gateway nevertheless dispatches:

```text
[(old owner, htv405_routine_ack_revoke),
 (new owner, htv405_routine_ack_configure)]
```

Its no-replacement-before-revocation invariant fails. The deletion harness
separately fails that revoke during `forget_registry_device`, closes/reopens
the gateway, reconnects the former node and invokes the actual HTV405 restore
seam. No cleanup is replayed:

```text
AssertionError: 'htv405_routine_ack_revoke' not found in [] : failed delete cleanup must survive restart/reconnect
```

These are local lifecycle failures, not measured RF collisions or actual
valve actuation. They elevate HTV405 from an analogous source suspicion to a
separately reproduced case that should be included explicitly in ownership
acceptance coverage.

The new HTV145 positive test uses the existing capture-qualified runtime
fixture, injects revoke dispatch failure, reopens its SQLite store, changes
the node connection epoch and attempts restore. The durable reservation
blocks reconfiguration. Wrong-owner and stale-command confirmations preserve
it; a matching owner/command/association confirmation deletes it, and a
duplicate remains harmless. Unlike HTV405, its revoke reserves before
dispatch (`htv145_runtime.py:174-177`).

This precedent does **not** prove automatic retry of a lost HTV145 revoke:
restore deliberately refuses while it is pending. Nor should its callback be
described as independently matching operation generation/current session;
`observe_node` matches the supplied owner, command and association fields,
with transport authentication handled elsewhere. Reuse its durable barrier
concept, not an assumption that every proposed correlation requirement is
already implemented there.

## Tests, commands and retained evidence

The new CI-discoverable file contains five passing tests and no expected-failure
decorators or assertions that bless the known bugs:

```sh
/Users/federicoholgado/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest tests.test_stock_informed_regressions -v
```

Result: **5 tests, OK** (0.075 seconds in the focused run). The first local
draft selected a decoder-only, nonaccepted measurement example and produced
two setup errors; it was replaced with the existing valid captured frame
before recording the above results. No implementation change was used to
make the tests pass.

The deliberately failing harness and exact output are privately retained,
confirmed ignored by Git:

```text
captures/stock-hub-firmware/2026-09-27-adzoj0e3/analysis/local-consumer-regression-audit.py
captures/stock-hub-firmware/2026-09-27-adzoj0e3/analysis/local-consumer-regression-audit-output.txt
```

Invocation: the same bundled Python followed by the harness path. Result:
**3 tests, FAILED (failures=3)** (0.031 seconds), comprising retained selector,
HTV405 replacement authorization and HTV405 deletion cleanup. These should
be promoted to normal CI tests with the corresponding future implementation,
not hidden as expected failures in the current suite.

The hardware-independent native protocol check also passed (exit 0):

```sh
c++ -std=c++17 -Ifirmware/rainpoint_bridge/include \
  firmware/rainpoint_bridge/tests/protocol_test.cpp \
  -o /tmp/rainpoint-stock-regression-protocol-test
/tmp/rainpoint-stock-regression-protocol-test
```

The full command `python3 -m unittest discover -s tests -t . -v`, using the
same bundled executable above, ran **621 tests in 93.462 seconds**, reporting
**12 errors and 1 skipped test**, with no assertion failures. This is an
incompatible test environment, not a clean full-suite pass:

- Python 3.12.14 has no TLS-PSK support: six secure-transport tests, one
  reliability-TLS test, and one SDR-forwarder test error for that reason.
- Missing `jinja2` prevents importing `test_alert_blueprints` and
  `test_garden_scheduled_duration`.
- Missing `yaml` prevents importing `test_firmware_catalog` and
  `test_firmware_signing`.

The eight transport errors were reproduced in focused runs; all four import
errors were confirmed through the unittest loader's discovery-error list.
No tests were patched or skipped to conceal these errors. Tests ran with
the AGENTS.md-required localhost-binding permission. No production firmware
build or deployment is implied by a native protocol-test pass.

A fresh isolated Python 3.14.7 environment was then created at
`/private/tmp/rainpoint-audit-tests.oGxlSF` using the existing interpreter,
and `pip install -r tests/requirements.txt` installed CI's declared pinned
dependencies (PyYAML 6.0.3, Jinja2 3.1.6, aiohttp 3.14.3 and cryptography
46.0.5, plus their transitive dependencies). The stock-readout environment
and global interpreter were not modified. CI itself currently selects Python
3.13; the local 3.14 run supplies the required TLS-PSK functionality.

The full verbose rerun uses that environment's Python and the same unittest
discovery command. Complete combined output is retained mode 0600 in
`captures/stock-hub-firmware/2026-09-27-adzoj0e3/analysis/local-regression-full-suite-python314.txt`.

Final result: **650 tests in 136.778 seconds, OK (skipped=2)**, process exit
0. The two existing skips are optional NumPy-based IQ-analysis cases
(`test_classifies_a_low_tone_post_frame_tail` and
`test_reports_worst_case_wake_transition_timing`); NumPy is not in the CI
test requirements installed here. All five new regressions passed in this
full run. `git diff --check` also passed. Runtime source directories remained
unchanged by this audit.
