# Two-zone stock-hub capture procedure

Planned September 28, 2026. Use the arriving two-zone valve as a new stock-hub
reference, not as an assumed HTV145/HTV405-compatible device. Execution results
and open gates belong only in [the roadmap](../PROJECT_ROADMAP.md).
This is the experiment procedure, not its execution log. The September 28
[HTV213 results](HTV213_STOCK_CAPTURE_FINDINGS_20260928.md) preserve observations
and capture limitations.

## Questions this experiment should answer

- Which startup, pairing and configuration messages consume the hub's RF phase?
- Do retries retain it, and which replies actually acknowledge each command?
- Can the stock hub control this valve immediately, after quiet periods and
  after a hub restart without new pairing or waiting for a valve status report?
- Which enrollment exchanges repeat per port, and which are device-wide?
- How do advertised configuration revisions relate to settings reads and `20`
  notifications? Do not confuse these revisions with command phases.

Evidence on this new model is not proof of the existing valves' acceptance rules.
Use it to test shared-protocol hypotheses, then qualify model-specific differences.

## Setup and first-use preservation

The user supplies the exact model/label, fresh batteries, and confirmation that
the valve is disconnected from water. Until dry operation is confirmed, plan
passive capture only; water-connected runs need agreed durations and supervision.
Check model-specific operating instructions before choosing actuation intervals.
If possible, leave batteries out until capture is ready so first boot is retained.
If already powered, record that fact rather than factory-resetting automatically.

Before inviting a button press, the agent should:

1. Check Mac SDR availability, disk budget, gain/clipping, timestamp origin and
   frequency coverage. Record sample rate, center frequency, gain, gaps and
   retunes. Cover both request and reply carriers; if one receiver cannot cover
   all relevant channels concurrently, explicitly qualify the blind spots.
2. Start recording before stock-hub power-on. Record its firmware/app version
   and RF-channel setting without changing them. Leave enough physical antenna
   separation for unclipped captures and verify it from actual signal levels.
3. Confirm stock schedules/cloud automations cannot unexpectedly actuate existing
   water-connected devices. Do not assume plugging in the hub affects only the
   new valve. Preserve production custom-node ownership and monitor normal garden
   telemetry; no production reassignment or disabling radios for convenience.
4. Keep custom nodes out of pairing mode. Do not provision this stock-owned valve
   on them or send speculative ACKs/controls. Any optional test-node maintenance
   change must be scoped and checked, not a global shutdown of the garden radios.
5. Prepare an event journal using UTC plus monotonic elapsed time. Keep raw RF,
   original timestamps, cloud action IDs/results where available, and device
   reports distinct. Check cloud visibility/control support before promising
   unattended commands; missing support means the initial commands use the app.

Use continuous decoded/event logging during the experiment, with contiguous raw
IQ during startup, pairing and each selected command window. Size raw IQ as
sample rate × bytes per complex sample × time, plus headroom. For long idle
periods, retain bounded raw segments around detected events where tooling permits;
otherwise document precisely what raw evidence is absent. No unlimited overnight
IQ recording, deletion of existing captures, or claim of complete RF coverage
from decoded logs alone. Preserve private captures outside Git.

## Experiment order

| Phase | Action | Evidence to retain |
| --- | --- | --- |
| Startup baseline | Record stock-hub boot and several minutes of idle traffic before valve pairing. | Startup notifications and other consumers; initial observed phase is not necessarily the first generated phase. |
| First stock enrollment | Confirm capture running; arm stock pairing first, then invite valve pairing according to its instructions. | Whole exchange through stable reporting, both ports, settings/plan/parameter reads and configuration revisions. White flash alone is not completion. |
| Zone 1 automatic stop | Request a 60-second run through the stock app/cloud path. | Actual RF duration, matched response, valve-originated open state, countdown if present, final idle and timestamps. |
| Zone 2 automatic stop | Once idle and after at least 30 seconds of rest, request 120 seconds on zone 2. | Same fields; distinguish zone selector from counter changes. Do not assume concurrent zones are supported. |
| Explicit close | After another rest, request 120 seconds on one zone, then stop after at least 30 seconds. | Open/close sequence relationship, response to each, actual final state. A cloud success response is not RF success. |
| Quiet-period control | Leave paired and idle for about 30 minutes, then later a multi-hour or overnight quiet interval. After each selected interval, request one bounded 60-second dry run. | All intervening observed hub traffic; first command and any recovery exchange without intentionally waiting for a new valve report. No periodic actuation during the quiet interval. |
| Hub-only restart | Once baseline is captured and valve confirmed idle, obtain readiness for a controlled stock-hub restart; leave valve powered. | Pre/post-boot traffic, sequence changes and first bounded dry command, without re-pairing. Separate this from elapsed-time effects. |

Keep at least 30 seconds between confirmed idle and the next run, and respect
any stricter model constraint. No counter guessing, injected packets, deliberately
lost replies or rapid on/off stress. Longer *observation* is useful; a valve need
not remain open for hours. Stop on unexpected actuation, unclear valve state,
production telemetry disruption, capture failure or depleted storage. Preserve
the failed exchange rather than repeatedly issuing commands.

## Later discriminating trials

Analyze the first results before requesting more user work. A single stock-app
default-duration edit on one port, with no run, can test the raw settings field
and configuration-revision/notifier path; record the original value and restore
it afterward with both changes captured. This is a proposed follow-up, not an
automatic change to watering schedules or a dependency on cloud at runtime.

A valve-only battery cycle is a separate later trial requiring the user. Keep
the stock hub running and out of pairing mode; capture boot announcement,
retained assignment or new enrollment, then qualify controls. Never combine hub
and valve restart when trying to identify which side resets state. Repeating
full pairing is only useful if the first trace leaves a specific ambiguity.

## Analysis and acceptance

Use the [offline analyzer](PAIRING_TRACE_ANALYZER.md) with verified directions,
routes, commands and full six-bit phases. Extend unknown two-zone shapes only
after capture validation; do not force them through an existing model profile.
Keep separate device-reported software version, configuration revision, and each
sender's RF phase. Decode native duration/remaining fields independently.

For every attempted action, report observed request, retry pattern, matched
response, valve state transition, and missing-coverage intervals. Classify a
phase change as explained consumption, modulo wrap, restart-associated change,
or unexplained; a gap alone is not a reset. RF observation cannot reveal every
internal generator call that failed before transmission. Unanswered commands
are not proof of rejection, and a matched ACK alone is not proof of watering.

The useful result is a timestamped startup/enrollment/control transcript for
both zones, a counter ledger through quiet periods and a separately qualified
hub restart. Promote minimal redacted fixtures and update the protocol docs.
Do not mark local two-zone pairing/control supported or existing overnight
counter failures solved by a successful stock-only test. Local implementation
and deployment require their own review and dry-device qualification.
