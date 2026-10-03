# Offline pairing trace analyzer

`pairing_native_transcripts.py` reads saved frames. It has no radio interface,
encoder, cloud dependency or deployment action. Current protocol definitions
remain in [protocol_documentation](../protocol_documentation/); open work stays
in [the roadmap](../PROJECT_ROADMAP.md).

## Public reference transcripts

From the repository root:

```sh
python3 -m research.pairing_native_transcripts
```

This prints the selected HCS026, HTV145 and HTV405 stock fixture rows, including
native command, six-bit phase, declared length and data. It labels supported
operations and fields: port, plan page, parameter IDs, configuration version
and update kind. The request context determines whether an `82` reply includes
a version. `85` data `00 01` is one settings byte, not that same version field.
`86` status 1 means more plan data in the traced handler; it is not a generic
negative response. Unknown command/body shapes remain explicitly unqualified.

A successful `85` with fourteen settings bytes also shows the candidate class-1F
[valve layout](STOCK_HUB_CONFIGURATION_LIFECYCLE.md#fourteen-byte-valve-configuration-layout).
Values retain raw/unqualified units; length alone cannot establish the model.
The linked soil address is reduced to a boolean in reports. The captured work
time value 600 is neither a duration-command decoding test nor remaining time.

The [native comparison](PAIRING_NATIVE_COMPARISON.md) identifies the fixture
scope. No universal pairing state machine is inferred from these rows.

## A labelled local capture

For a new saved trace, prepare a JSON array with exactly three fields per event:

```json
[
  {"time_s": 1.25, "direction": "device", "frame": "<38-byte normalized frame as hex>"},
  {"time_s": 1.31, "direction": "gateway", "frame": "<38-byte normalized frame as hex>"}
]
```

The frames must pass the normalized sync, length, legacy integrity-residue and
native declared-length checks. Sender direction must come from independently
established capture context, not guessed from the ACK flag: a valve sends `a0`
in response to a gateway's `20`. Use a common timestamp origin/unit and document
whether each timestamp is frame start, sync or receive end. Printed deltas are
differences between supplied timestamps, not automatically RF-turnaround times.
Retain the full original capture; do not replace it with these derived rows.

```sh
python3 -m research.pairing_native_transcripts --events /absolute/private/events.json
```

Input is bounded to 16 MiB and 10,000 events. Extra metadata fields are rejected
to avoid silently including private configuration. Event-mode output omits
identities and raw packet bodies; keep derived reports private until reviewed.
The public-fixture mode above deliberately prints those already-public bodies.
Malformed input produces a generic error without echoing its contents.

## What the diagnostics mean

- **Matching response candidate:** opposite labelled sender, reversed route
  (using the captured first-byte high-bit alias), response command and full
  phase agree within the analysis window. This is not runtime authentication,
  successful actuation, enrollment completion or proof the sender accepted a reply.
- **Repeated request:** same sender, route, command and body within the window,
  with same or changed phase. This may be a retry; periodic requests can also
  repeat. Separate sessions/devices should not be mixed into one trace.
- **Unmatched response:** no eligible earlier request in the supplied trace.
  Wrong phase, missing capture coverage, out-of-order source timestamps or an
  expired analysis window can all produce this result.
- **No matching response observed:** no candidate was linked before the trace
  ended. It does not prove RF loss or that the real device stopped communicating.
- **Reused phase:** correlation is explicitly ambiguous; delta uses the latest
  request at that key. The analyzer does not pretend it knows which was answered.

The default ten-second correlation window is analysis policy, **not a discovered
protocol deadline**. Change it explicitly with `--window-seconds` when justified
by the capture. Endpoint assignment changes are not auto-correlated at factory
enrollment. The stock-fixture row view preserves independently annotated pairs
for those exchanges instead. Missing factory correlation is not failed pairing.

The final `59 observed` line reports a packet family, never a success verdict.
Repeated `06` requests with no `59` are the known single-zone failure boundary;
an empty `86` plan reply is not evidence of terminal completion.

## Regression evidence

```sh
python3 -m unittest tests.test_pairing_native_transcripts tests.test_pairing_trace_analysis -v
```

All three retained September 5 single-zone failures identify four changed-phase
plan-request repetitions and four requests without a matched response. The
gateway's delayed configuration and the valve's `a0` are linked in their actual
directions. Tests reject wrong command, phase, sender, route and malformed
inputs; flag reused-phase ambiguity; and prevent duplicate ACKs from consuming
a request twice. These analysis tests do not replace the C++ session replay or
the separately approved [physical canary](../docs/STOCK_INFORMED_VALIDATION.md).

September 28 validation: 19 focused tests passed; the full suite ran 710 tests
with 708 passes and two optional NumPy/IQ-analysis skips. The hardware-independent
C++ protocol test and Markdown report smoke test passed. No firmware was deployed.
