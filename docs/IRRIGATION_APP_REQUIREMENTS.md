# Irrigation app requirements

Status: **Draft for product review; implementation has not started.**
Updated: 2026-09-28. Working product name: **Irrigation**.

This document defines the proposed product and its acceptance criteria. It is
not an implementation checklist. The [project roadmap](../PROJECT_ROADMAP.md)
remains the live status record. Terms are defined in the
[irrigation glossary](../CONTEXT.md).

Initial [UI concepts](irrigation-ui/README.md) illustrate the daily overview,
zone dashboard, and schedule editor with advisory overlap warnings.

## 1. Product goal and confirmed requirements

Make the existing Garden experience installable by other Home Assistant users,
independent of valve manufacturer, sensor manufacturer, household entity names,
weather provider, or notification destination.

The user has explicitly requested:

- **U-01:** Each irrigation zone has its own dashboard.
- **U-02:** Users can create zones; every zone requires at least one valve.
- **U-03:** Moisture sensors are optional, and associated sensors can influence
  watering decisions.
- **U-04:** Existing timing, moisture, and rain-probability logic is reusable per zone.
- **U-05:** Each zone supports multiple watering opportunities per day.
- **U-06:** An overview shows all irrigation scheduled for the selected day.
- **U-07:** The schedule editor shows other irrigations so users can see and avoid
  simultaneous watering.
- **U-08:** Overlaps produce warnings, but users can still save them. This supersedes
  the earlier suggestion to block overlapping schedules.
- **U-09:** Review and refine requirements before starting implementation.

Everything beyond these requirements is a proposed first-release behavior for
review. An advisory schedule overlap is different from a device constraint that
physically prevents simultaneous operation.

## 2. Product scope and packaging

**PKG-01 — Installation.** Distribute a standalone HACS integration with its
dashboard bundled in the same release. Users install it, add the integration,
create a zone, select existing HA entities, and configure schedules without
editing YAML. Release it from a dedicated repository when implementation begins;
this repository currently holds the draft and the source experience.

**PKG-02 — Independent operation.** Scheduling and execution run inside HA and
continue with the dashboard closed. RainPoint Local is an optional hardware
integration, not a required dependency. The product works on HA OS and HA
Container. Device and weather integrations retain their own connectivity needs.

**PKG-03 — HA participation.** Expose zone status, automatic-watering enablement,
next scheduled check, decision reason, and last-run information through HA
entities. Expose run, stop, and skip-next actions for other HA automations.
Use HA authentication; configuration changes require administrator access.

**PKG-04 — Schedule coverage.** “All irrigation” means all schedules managed by
this app across every configured zone. Arbitrary external automations and
device-native schedules cannot be assumed discoverable. The overview and editor
must make this coverage clear. Observed activity on a bound valve is displayed
even when an outside controller initiated it.

## 3. Zones, valves, and inputs

**ZONE-01 — Lifecycle.** Create, rename, edit, and remove zones through the UI.
Require a name and at least one valid valve binding to save a zone; zero
schedules and zero moisture sensors are valid. Renaming retains history and
dashboard links. Editing cannot remove the last valve. A missing entity after
setup leaves the zone visible with a repair prompt. Removal or rebinding must
not discard ownership or stop deadlines for an active or unconfirmed run;
resolve that run first. Retained history remains readable after zone removal.

**ZONE-02 — Membership.** A valve binding represents one controllable outlet,
not an entire multi-outlet controller. An outlet belongs to at most one zone
in the first release. A zone can contain multiple outlets from different
integrations. Sensors may be shared between zones.

**ZONE-03 — Multiple valves.** A zone shares one decision policy and schedule
list. Default to sequential valve operation; allow explicit parallel operation
where device capabilities permit. Set a zone default duration, with optional
per-valve overrides. Show the full resulting zone window in the schedule editor.
Different independently scheduled watering policies should use separate zones.

**BIND-01 — Supported controls.** Support standard HA `valve.*` open/close
entities and irrigation `switch.*` on/off entities. Validate that the required
control actions exist. Gas valves and incompatible entities are not eligible.
Binding a generic switch requires the user to identify it as irrigation control.

**BIND-02 — Capabilities.** Bind optional duration controls, readiness, reported
state, measurement timestamps, battery, signal, and water volume explicitly or
through a known adapter. Never infer relationships solely from similar names.
Validate duration units, minimum, maximum, and increments per valve. Do not
generalize the reference installation's 1–60-minute range to all hardware.

**BIND-03 — Timer and feedback.** Show whether shutdown is device-managed or
HA-managed. Prefer device-managed timed runs when available. HA-managed switches
require HA to remain operational to issue their stop action. Distinguish
command acceptance, reported valve state, and measured flow; none implies the
next. A generic optimistic state must not be labelled physical confirmation.

**INPUT-01 — Moisture.** Support zero or more numeric moisture sensors. First
release accepts percentages and explicit normalization of other numeric scales
to a percentage. Validate units and range. Show individual readings and which
valid reading or aggregate drives the decision. Default aggregation is the
driest valid sensor; more aggregation strategies can follow later.

**INPUT-02 — Freshness.** Each input has a configurable age limit. Prefer a
source measurement timestamp; otherwise identify the available freshness evidence
and its limits. Unchanged measurements can still be fresh. Unrelated attribute
updates and restored values must not falsely establish a new measurement.
Exclude invalid or stale readings and list them in the decision explanation.

**INPUT-03 — Weather.** Select a shared HA weather entity or explicit forecast
sensors, with per-zone overrides. Preserve probability, meaningful-rain amount,
and forecast-window settings. Normalize precipitation units. Missing probability
or rainfall amount is unknown, not zero. Weather rules are optional and require
compatible input capabilities.

## 4. Daily overview

**DAY-01 — Whole-system view.** The landing page defaults to Today in HA's local
timezone, with previous-day, next-day, and date selection. Show a timeline and a
chronological list of every occurrence touching the selected day, including
overnight windows, across all zones. Include an empty state and Add schedule.

**DAY-02 — Useful details.** Every occurrence shows zone, planned start and end,
requested durations, valves involved, automatic/manual origin where applicable,
and status. Clicking it opens the zone or schedule. Show a current-time marker,
active watering, next scheduled check, and a count of overlap warnings.

**DAY-03 — Plans and outcomes.** Future entries are “scheduled checks,” not
promises that watering will occur. Preserve the original planned window and
separately show actual start/end, delay, skip reason, cancellation, or failure.
Show manual and externally observed runs in actual activity. A skipped entry
remains visible for that day. Paused or season-disabled occurrences appear dimmed
and do not count as active reservations.

**DAY-04 — Overlaps.** Place simultaneous windows in readable lanes, label the
zones and overlap interval, and distinguish planned overlaps from actual
concurrent watering. Explain when a controller constraint is expected to delay
one run. Do not remove a future reservation because a current moisture or rain
preview suggests it might be skipped.

**DAY-05 — Mobile and accessibility.** Provide a usable list alternative on
small screens, keyboard-accessible controls, readable labels, and status text
that does not rely on color alone.

## 5. Schedule editor and overlap policy

**SCH-01 — Recurrence.** Each zone supports multiple independently enabled
schedules with local start time, selected weekdays, and duration settings.
Daily watering is all weekdays. No one-run-per-zone-per-day restriction applies.
Provide edit, duplicate, and delete. A same-zone cooldown, if configured, must
be visible when it affects another scheduled occurrence.
Resolve each valve's duration in this order: schedule-specific valve override,
schedule-wide duration, valve default, then zone default. Show the effective
value before saving. Reject unsupported values instead of silently rounding.

**SCH-02 — Context while editing.** Show the proposed occurrence alongside
every other app-managed irrigation on the preview day, including schedules for
the same zone. Highlight the edited window and keep other zones visible by
default. Recompute the preview immediately when time, duration, weekdays, valve
membership, or valve execution order changes. Do not compare an edited schedule
against its own obsolete saved version.

**SCH-03 — Advisory overlap warnings.** On overlap, show the affected zones,
dates/days, and shared time window. Saving remains available; there is no second
approval step solely because of the warning. Do not silently shift a start,
shorten a duration, disable a schedule, or impose global serialization. Distinct
eligible valves can water concurrently when their controller limits permit it.

**SCH-04 — Calculate full windows.** Compare full intervals, not just equal
start times. A sequential zone's window includes every valve duration and its
declared handoff allowance; a parallel zone uses the longest valve duration plus
applicable allowance. Show this calculation. End times are estimates, not proof
of closure. Adjacent intervals are not overlapping unless a configured allowance
extends the earlier reservation into the later one.

**SCH-05 — Recurrence and dates.** Check every weekday in the repeating pattern,
including previous/next-day spillover and the week boundary. The warning summary
must not depend only on the selected preview day. Show actual dates when a
timezone transition changes the preview. Ignore disabled schedules and paused
occurrences for collision counts while keeping them inspectable.

**SCH-06 — Resolution aids.** Offer the next available gap as an optional
suggestion and a link to edit the other schedule. Suggestions never change a
schedule automatically. Revalidate on save using current saved schedules so a
second browser's edits cannot leave a stale preview presented as current.

**SCH-07 — Hard validation.** Invalid or unsupported durations and missing
required fields block saving. An overlap alone does not. Warnings about shared
controller capacity explain the runtime queue policy instead of claiming both
valves will start together.

Example with no handoff allowance:

| Scheduled check | Planned window | Editor behavior |
| --- | --- | --- |
| Garden: 20 minutes | 06:00–06:20 | Existing window remains visible. |
| Front Yard: 15 minutes | 06:10–06:25 | Warn about Garden overlap from 06:10–06:20; allow saving. |
| Patio: 10 minutes | 06:20–06:30 | No overlap with Garden; warn about Front Yard until 06:25. |
| Beds: two sequential valves, 10 + 15 minutes | 07:00–07:25 | Reserve the whole 25-minute window. |

## 6. Decisions, manual controls, and runtime coordination

**DEC-01 — Per-occurrence decisions.** At each scheduled opportunity, evaluate
zone enablement, pause/season settings, input policy, moisture, weather, and
runtime limits. Reevaluate immediately before starting after any queue delay.
Record the inputs and reason. The dashboard's “What would happen now?” preview
uses the same rules without operating hardware.

**DEC-02 — Input policy.** Without configured moisture sensors, use timed
watering with any enabled weather checks. With sensors, use valid readings.
If none are valid, default to skip-and-notify; allow an explicitly configured
timed fallback. Missing required weather inputs likewise require a visible
skip-or-fallback choice. Never silently convert missing data to a permissive
value. Preserve the exact existing rain/moisture rule combinations after their
deployed definitions are inventoried.

**DEC-03 — Duration meaning.** For the first release, moisture and weather
decide whether a bounded run starts; they do not continuously water until a
target moisture level is reached. Changing moisture during a run does not
silently extend its duration.

**RUN-01 — Manual operation.** Run Now uses an explicit duration and clearly
states that it bypasses season, moisture, and rain checks. It does not bypass
duration limits, valve ownership, readiness, or device capacity. Provide Stop
zone and Stop all managed runs, including cancellation of pending starts.
Distinguish disabling future automatic runs from stopping a current run.

**RUN-02 — Resource coordination.** Hold exclusive ownership of each outlet
during a run and respect known shared-controller limits across zones. Do not
start a duplicate run on a busy outlet or assume unknown state means idle.
Queue only for actual resource contention; a visual overlap is not itself a
reason to queue. Queued runs show the blocking resource and expected delay.

**RUN-03 — Queue expiration.** Scheduled runs may wait up to a configurable
maximum lateness, proposed default 15 minutes. On expiry, record a skipped
occurrence rather than water indefinitely late. Do not replay missed schedules
after downtime. Manual requests disclose when they are queued. Equal-priority
requests are processed in scheduled-time/request order with a stable tie-break.

**RUN-04 — Failure and confirmation.** Track each valve's requested start,
observed start, stop request, observed stop, and uncertainty. A multi-valve run
can partially fail. Default to stop advancing to further valves after a failure;
for active peers, apply their adapter's documented safe stop behavior. Surface
unconfirmed operation as needs attention; do not report a successful full run.
Do not blindly retry an open that might already have succeeded.

**RUN-05 — Limits and recovery.** Enforce configured maximum runtime, optional
daily allowance, and optional cooldown for automatic watering. Persist occurrence
identity, run ownership, requested durations, and deadlines before actuation.
After restart, reconcile with available device feedback without replaying opens
or issuing speculative closes. Restore HA-managed stop handling only for a
persisted owned run and an adapter with an explicitly validated recovery policy;
otherwise retain uncertainty and alert. A device-managed stop is not inferred
from elapsed time alone.

**RUN-06 — Local time.** Use HA's configured timezone for schedules and display;
retain unambiguous timestamps for history. Proposed DST policy: skip nonexistent
spring-forward times, and run a repeated fall-back local occurrence at most once.
Show the policy in schedule previews. A timezone change recomputes future
occurrences without rewriting history or duplicating prior runs.

## 7. Zone dashboard, history, and notifications

**VIEW-01 — Zone page.** Automatically create a stable page for each zone with
current activity, Run Now/Stop, automatic/season toggle, pause-until and skip-next
controls, schedules, next scheduled check, decision settings, latest decision,
moisture readings/trends, and valve health. Unsupported optional capabilities
are omitted; configured-but-unavailable capabilities show an explanatory state.
Skip next identifies exactly one dated occurrence, even when the zone has
several schedules that day. Editing policy applies to future runs; an active
run keeps its captured duration and bindings unless explicitly stopped.

**HIST-01 — Decision and run history.** Persist scheduled, skipped, manual,
completed, stopped-early, partially failed, and unconfirmed outcomes across HA
restarts. Record planned versus actual times, requested versus observed duration,
input snapshots and freshness, decision reason, and per-valve outcomes. Make
retention configurable with a proposed 90-day default. A notification is not
the history archive. Counts must not equate a confirmed open with water delivered.

**HIST-02 — Water and telemetry.** Preserve moisture trends and watering activity.
Show water volume only when supported, with source units and session/cumulative
meaning. Do not sum repeated session readings as a cumulative meter. Battery,
signal, freshness, and reporting cadence are optional diagnostics.

**NOTIFY-01 — Outcomes and problems.** Provide HA notifications for confirmed
start/stop where evidence supports them, failed starts, overdue/unconfirmed
stops, and unusable required inputs. Optional phone routing and critical-alert
preferences are user-selected. Deduplicate repeated reports. Notification
failure must not prevent a required stop or erase the run outcome. Avoid
duplicate app/device notices where the underlying integration permits control.

## 8. Existing behavior to preserve and evidence limits

| Source experience | First-release destination |
| --- | --- |
| Garden and Front Yard views | Automatically generated zone dashboards. |
| Moisture gauges, driest sensor, 48-hour trends, stale labels | Moisture input display, freshness, and decision history. |
| Season, start time, moisture threshold, duration | Zone policy and multiple schedules. |
| Rain probability and meaningful amount, separate forecast windows | Provider-independent optional weather rules. |
| Last checked/ran, forecast snapshot, decision text | Durable occurrence and run records. |
| Run Now, Stop, readiness, confirmed transaction feedback | Manual controls and capability-aware execution. |
| Duration validation and missing-stop notices | Per-valve constraints and watchdog behavior. |
| Battery, signal, last report, report cadence | Optional health diagnostics. |
| Session duration and supported reported volume | Activity history with correct measurement semantics. |

Sources: [dashboard](../examples/federico-garden/garden-local-dashboard.yaml),
[manual scripts](../examples/federico-garden/garden-local-scripts.yaml),
[single-valve confirmation](../examples/federico-garden/single-valve-scripts.yaml),
[example notes](../examples/federico-garden/README.md), and
[notification behavior](ALPHA_NOTIFICATIONS.md).

The repository examples do not include the complete deployed scheduled decision
automations and household watchdog. Capture their definitions before claiming
behavioral parity. Existing field evidence does not establish generic multi-zone
coordination, all stale-input fallbacks, or every timezone/restart scenario.
RainPoint pairing, RF synchronization, and protocol-specific recovery remain
responsibilities of the hardware integration.

## 9. Acceptance scenarios

These scenarios define expected behavior, not claims that tests have passed.

| ID | Scenario | Required outcome |
| --- | --- | --- |
| A-01 | Create a zone with no valve, then one valve and no sensors. | First save is rejected; second produces a usable timed-watering zone page. |
| A-02 | Schedule one zone at 06:00 and 18:00. | Both appear on the daily overview; each evaluates fresh inputs separately. |
| A-03 | Edit Front Yard to 06:10 while Garden reserves 06:00–06:20. | Garden stays visible, overlap interval is named, and Save succeeds without shifting either schedule. |
| A-04 | Execute overlapping schedules on distinct ready controllers. | Both may run concurrently; no automatic global queue is introduced. |
| A-05 | Two overlapping runs need the same constrained controller. | Editor explains the constraint; runtime queues visibly and expires late requests according to policy. |
| A-06 | Change a sequential zone from one 10-minute valve to two. | The full new reservation is recalculated and all newly affected overlaps are shown. |
| A-07 | A Sunday 23:50 run lasts 30 minutes; another starts Monday 00:05. | Both days show the spillover and the 00:05–00:20 overlap is detected. |
| A-08 | A Tue/Thu schedule is edited while Monday is the preview day. | Conflicts on Tue/Thu are still surfaced in the recurrence summary. |
| A-09 | A planned run is skipped for moisture or rain. | Its planned entry remains visible with the reason and input snapshot; no successful run is invented. |
| A-10 | One sensor is stale; later all configured sensors are stale. | Valid readings alone drive the first decision; the configured fallback controls the second and is explained. |
| A-11 | Weather provider lacks precipitation probability. | Setup identifies the unsupported rule; missing probability is never treated as zero. |
| A-12 | A stop is unconfirmed, or only one valve in a zone starts. | Per-valve outcomes and needs-attention/partial-failure status remain visible; dependent starts are held. |
| A-13 | HA restarts during watering or a DST hour repeats. | No duplicate open; persisted run state is reconciled and each scheduled occurrence is attempted at most once. |
| A-14 | Start watering manually while a scheduled run owns the outlet. | Show resource contention; do not issue a second independent open. |
| A-15 | View the daily overview on a phone or by keyboard. | Every occurrence, overlap warning, status, and edit action remains accessible. |
| A-16 | Rename a zone, rename/remove an entity, or install an update. | Preserve stable zone identity/history; repair broken bindings; do not silently rebind or start watering. |
| A-17 | Install on clean HA with RainPoint, a generic valve, and a switch. | Create zones without copied household helpers; run bounded operations with truthful capability/feedback labels. |
| A-18 | Request Stop all while starts are queued. | Cancel queued starts and stop owned active runs through supported controls; retain any unconfirmed outcomes. |

## 10. Proposed defaults for review

The overlap policy is already confirmed: **warn and allow**. These other defaults
remain proposals, so approval of this draft can change them before implementation.

| Decision | Proposed default |
| --- | --- |
| Packaging | Separate HACS integration with bundled sidebar panel. |
| Multi-valve zone | Sequential; explicit parallel mode where supported. |
| Across zones | Parallel allowed, subject to actual outlet/controller constraints. |
| Moisture aggregation | Driest valid normalized reading. |
| No usable required inputs | Skip and notify; explicit timed fallback option. |
| Queued scheduled run | Expire after 15 minutes of lateness; reevaluate before start. |
| Missed occurrence during downtime | Skip, with no automatic catch-up watering. |
| DST | Skip missing local times; attempt repeated local times only once. |
| History retention | 90 days, configurable. |

Exact imported rain-rule combinations, supported HA minimum version, and
adapter-specific timing/confirmation allowances require source inventory or
compatibility validation before implementation is considered ready to release.

## 11. Outside the first release

Cycle-and-soak watering, evapotranspiration/seasonal optimization, master-pump
or master-valve orchestration, pressure/supply-group modeling, flow-based leak
detection, automatic frost rules, advanced moisture aggregation, arbitrary
start/stop script bindings, and importing arbitrary external schedules are
outside this draft's first-release scope. Existing device protections still
apply. This is a scope statement; delivery status belongs in the roadmap.

## 12. Packaging references

- [HA custom panels](https://developers.home-assistant.io/docs/frontend/custom-ui/creating-custom-panels/)
- [HA configuration entries and subentries](https://developers.home-assistant.io/docs/config_entries_index/)
- [HA valve capabilities](https://developers.home-assistant.io/docs/core/entity/valve/)
- [HA weather capabilities](https://developers.home-assistant.io/docs/core/entity/weather/)
- [HACS integration distribution](https://hacs.dev/docs/publish/integration/)

These references support packaging and entity contracts; product policies above
are proposals or user requirements, not guarantees supplied by HA or HACS.
