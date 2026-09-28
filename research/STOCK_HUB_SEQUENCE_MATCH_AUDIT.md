# Stock-informed sequence and response-correlation audit

Date: 2026-09-27. Offline source, public-fixture, temporary-SQLite and native
fake-I/O tests only. The initial audit made no runtime edit; the subsequent
approved source repair is noted below. No RF transmission, device command,
deployment or live Home Assistant access. This is evidence, not a second roadmap.

## Result

Three desired correlation invariants failed against the pre-repair production paths:

| Production path | Deterministic input | Observed effect |
| --- | --- | --- |
| HTV145 coordinator negative reply | Pending native phase **5** OPEN; valid synthetic phase **4** result-3 reply, same route and upper five bits | Clears durable pending ID and invalidates counter |
| HTV405 gateway negative reply | Pending native phase **14** CLOSE; valid synthetic phase **15** rejection, same route and upper five bits | Clears durable pending ID and enters failure/recovery handling |
| HTV405 firmware positive handler | Pending native phase **13** OPEN; valid synthetic phase **12** CLOSE response, same upper five bits and zone | Clears node pending and marks counter authenticated/confirmed idle |

The HTV405 **gateway positive** path correctly rejects that opposite-action
response; this is a node/gateway divergence, not proof of a falsely confirmed
gateway OPEN. The two negative failures are also not false watering confirmation:
they consume the wrong reservation and affect retry/recovery. All three inputs
are explicit mutations of checked-in RF fixtures, not claims that these exact
out-of-order exchanges occurred on hardware. Ordinary trailer validation is not
cryptographic sender authentication.

## Native phase versus the local representation

**Source repair, Sep 27:** the approved follow-up fixes these three defects and
the stale-positive HTV145 node behavior below. Native handlers compare the full
phase with the retained command; Python negative matchers include the sixth bit.
The fixed phase-zero idle-anchor exception remains unchanged. Nine passing
regressions in [test_command_response_correlation.py](../tests/test_command_response_correlation.py)
exercise Python durable state and actual extracted native handler branches with
real decoders/fake I/O. The causal descriptions and original red results below
are historical, not claims about the repaired checkout. Nothing is deployed;
counter generation and ordinary command payloads are unchanged.

The independently traced stock payload mapping is
`P[i] = ((N[i+4] << 1) | (N[i+5] >> 7)) & 255`, for normalized 38-byte `N`.
Thus the six-bit command sequence is
`P[9] & 63 = ((N[13] & 31) << 1) | (N[14] >> 7)`.
Native command `0x21` becomes `0xA1` in its ACK; request and ACK echo all six bits.
Stock function `0x42037920` advances a global six-bit generator. Stock waiting-ACK
matcher `0x4204A550` checks both identities, command including ACK bit, and all six
sequence bits. Stock retransmission `0x420443F8` / `0x42044552..0x420445F7` reuses
the queued packet rather than generating a new sequence. These are hub-side
facts, **not** evidence of valve acceptance windows, deduplication, or reset
behavior. Sources: [valve trace](STOCK_HUB_VALVE_STATE_TRACE.md),
[radio trace](STOCK_HUB_RADIO_PATH_TRACE.md), and independently retained captures
in [stock frame tests](../tests/test_stock_valve_frame_reference.py).

Local HTV145 retains normalized `0x80..0x9f` sequence plus a profile marker policy.
Local HTV405 retains a five-bit sequence and assigns normalized marker `0x90` to
OPEN and `0x10` to CLOSE. Both advance the retained sequence after OPEN, not after
CLOSE. For the inverted HTV145 profile and HTV405, that can represent alternating
odd OPEN / even CLOSE phases, but is not a general representation of stock's
six-bit progression. The public selector-2 HTV145 capture has two positive OPENs
at phases 3 and 4 before a CLOSE at 5: action alone cannot determine the phase
low bit. Local duplicate-open guards intentionally prohibit a pending second
open, so this capture is **not** itself a reason to permit repeated actuation.
Sources: `valve_protocol.py::next_htv145_command_sequence` (line 444),
`rainpoint_valve_control.h::buildHtv405GatewayOpenFrame` (105),
`::buildHtv405GatewayCloseFrame` (154), `::nextHtv405GatewayCommandSequence` (312),
and `htv145_selector2_stock_pairing_control_20260905.json`.

## Why the negative cases consume the wrong reservation

HTV145 `decode_htv145_command_error` accepts both normalized `0x50` and `0xD0`
but returns only `sequence=N[13]` and result code. `Htv145ControlCoordinator`
matches only this sequence and a non-null pending ID before
`fail_htv145_command`. The native decoder/handler has the same omission.
Sources: [Python decoder](../rainpointd_addon/rainpointd/valve_protocol.py),
`decode_htv145_command_error` (554);
[coordinator](../rainpointd_addon/rainpointd/htv145_control.py), `observe_frame`
(301); [native decoder](../firmware/rainpoint_bridge/include/rainpoint_htv145_control.h),
`Htv145CommandError` (42), `decodeHtv145CommandError` (219);
[firmware](../firmware/rainpoint_bridge/src/main.cpp), `observeHtv145CandidateFrame`
(1955), negative branch (1992).

HTV405 negative decoder requires `N[14]=0xD0`, so it recognizes an odd native
phase but returns only `N[13]&31`. Gateway rejection matching checks route,
pending ID, upper-five sequence and response age, **not** whether the pending
command's actual phase is odd. A phase-15 rejection therefore consumes a
phase-14 CLOSE. Native rejection matching likewise compares only the upper five
bits. Sources: `valve_protocol.py::decode_htv405_gateway_command_rejection`
(383), [gateway](../rainpointd_addon/rainpointd/gateway.py),
`observe_valve_control_air_rejection` (5090), `storage.py::fail_htv405_command`
(2514), and `main.cpp` rejection branch (1304).

The existing HTV145 fixed-zero idle-anchor/result-3 exception is separately
qualified by dry fixture evidence and pending anchor context; these tests use
ordinary OPEN/CLOSE reservations, not that exception. Do not erase the exception
or generalize result 3 into proof that a physical close occurred.

## Positive matching and stale replies

HTV145 coordinator validates profile marker, then the store checks reserved
sequence and action. Together these preserve all six bits for the currently
supported profile policy. It rejects evidence predating the reservation and a
second immediate confirmation without another reservation. However, the node
handler calls `failHtv145Candidate("conflicting_command_response")` for a valid
same-route positive reply with a different sequence, profile marker **or action**;
the gateway ignores/rejects that evidence without mutating pending state. This
additional stale-response availability difference is source-confirmed here, not
an executed full-node test. Sources: `htv145_control.py::observe_frame`,
`storage.py::confirm_htv145_command` (3677), `main.cpp` (2007–2015).

HTV405 gateway positive matching checks route, pending sequence, zone, action,
and bounded response age. Its decoder ties marker parity to resulting watering,
so the action check also discriminates the sixth bit for this local policy.
Firmware `observeValveProbeFrame` checks pending, upper-five sequence and zone
but never compares `response.watering` to the transmitted action/full phase
before clearing pending and authenticating the counter. The private native
harness compiles the unchanged positive branch extracted directly from
`main.cpp`, with the **real** header decoder and fake route predicate, receive
restore and status sinks. Output for the opposite-action response is exactly
`pending=0 counter_authenticated=1 confirmed_watering=0`. This exercises the
production branch, not the complete ESP32 program or actual receive timing.
Sources: `gateway.py::observe_valve_control_air_response` (4932),
`rainpoint_valve_control.h::decodeHtv405GatewayCommandResponse` (269),
`main.cpp::observeValveProbeFrame` (1231–1302).

No claim is made that timestamps prevent an old RF packet physically received
during a new reservation: these time checks reject old *recorded observation
times*, not on-air age. A phase wrap or repeated phase still needs explicit
protocol/transaction policy; stock's generator alone cannot establish it.

## Retransmission, duplicate opens and recovery

The bounded local retransmit paths preserve the stored full command frame.
HTV145 `transmitNextHtv145CandidateAttempt` sends `commandFrame` at offsets
0/730/1670 ms; `startHtv145Candidate` constructs that frame once. HTV405
`pollValveProbeResponseListener` resends `commandFrame` at 650/1450 ms after
the initial send. These paths do not increment sequence on each physical retry.
This agrees with the stock queued-packet retransmit behavior; it does not prove
how a valve deduplicates repeated opens. Sources: `main.cpp` (1398–1428,
1810–1856, 1890–1924), `rainpoint_htv145_control.h` (18–24).

New tests verify both families reject another OPEN while a durable command is
pending without dispatching another transaction, and repeated positive responses
do not dispatch commands or consume a new sequence. Existing safety tests cover
independent telemetry not authenticating a command counter, summaries not
overwriting current state, timeout invalidation, and explicit close retry policy.
HTV405 journal recovery replays the retained original observation time through
the same positive/negative matchers, so time checks remain, but the negative
phase omission also remains; recovery does not repair the matcher. Source:
`gateway.py::_recover_pending_htv405_air_responses` (5165),
[safety tests](../tests/test_rainpoint_safety.py) and
[gateway tests](../tests/test_rainpointd.py).

## Reproduction and validation

Checked-in positive suite:
[tests/test_stock_sequence_regressions.py](../tests/test_stock_sequence_regressions.py).
It reuses real coordinators, gateway/store seams, public fixtures, and temporary
databases. Synthetic field mutations preserve each fixture's known trailer
residue. No expected-failure annotation or mock replacement of the Python
production matcher is used.

```sh
/private/tmp/rainpoint-audit-tests.oGxlSF/bin/python -m unittest tests.test_stock_sequence_regressions -v
c++ -std=c++17 -Ifirmware/rainpoint_bridge/include firmware/rainpoint_bridge/tests/protocol_test.cpp -o /private/tmp/rainpoint-sequence-protocol-test
/private/tmp/rainpoint-sequence-protocol-test
```

Results: six positive tests PASS; native protocol suite PASS. Full-suite
validation is coordinated with the other parallel offline audit additions.

Known-red harness and exact output are deliberately retained only under ignored
`captures/stock-hub-firmware/2026-09-27-adzoj0e3/analysis/`:
`sequence-desired-invariants.py` and mode-0600
`sequence-desired-invariants-output.txt`. Command:

```sh
/private/tmp/rainpoint-audit-tests.oGxlSF/bin/python captures/stock-hub-firmware/2026-09-27-adzoj0e3/analysis/sequence-desired-invariants.py
```

Result: three tests, three assertion failures, no harness errors. The desired
pending-preservation assertions fail with `unexpectedly None` for both Python
paths; the native desired invariant fails with the exact node state above.
These are retained counterexamples from before the authorized source repair,
not CI failures disguised as passing tests. The historical harness/output is
not rewritten; the checked-in follow-up tests assert the corrected invariants.
