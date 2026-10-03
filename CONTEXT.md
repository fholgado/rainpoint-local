# Irrigation product language

This glossary describes the planned irrigation product: how watering is grouped,
scheduled, and observed. It does not redefine physical device terminology.

## Language

**Irrigation system**:
The collection of managed zones, shared preferences, and their watering activity.
_Avoid_: Hub, gateway

**Zone**:
A named watering area with at least one valve outlet and one shared watering
policy. It may have several schedules and optional moisture sensors.
_Avoid_: Physical valve, geographic zone

**Valve outlet**:
One independently controllable water path; a physical controller can have
multiple valve outlets.
_Avoid_: Zone when referring only to a hardware channel

**Valve binding**:
The association between a zone and the control, feedback, and capabilities of
one valve outlet.
_Avoid_: Device when only one outlet is meant

**Schedule**:
A recurring rule specifying when a zone should be considered for watering and
the requested duration settings.
_Avoid_: Run, occurrence, guaranteed watering

**Occurrence**:
One dated watering opportunity produced by a schedule. It can be skipped
without producing a run.
_Avoid_: Schedule, completed watering

**Reservation**:
The estimated time window occupied by a planned occurrence, including all its
valves and any declared handoff allowance.
_Avoid_: Actual runtime, guaranteed occupancy

**Run**:
One requested watering attempt for a zone, with outcomes for its participating
valves. It may be scheduled or manual and may fail before any water starts.
_Avoid_: Schedule, successful irrigation without outcome evidence

**Overlap**:
An intersection between planned reservation windows. It is advisory and does
not alone mean that the participating devices cannot operate concurrently.
_Avoid_: Invalid schedule, resource contention

**Resource contention**:
Two requests needing the same valve outlet or more simultaneous operation than
a shared controller supports.
_Avoid_: Overlap when only the planned times intersect

**Watering decision**:
An evaluation of policy and current inputs that explains whether an occurrence
should proceed or be skipped.
_Avoid_: Watering confirmation

**Reported state**:
The valve state supplied by its controlling integration, with the available
evidence of freshness and confirmation.
_Avoid_: Measured flow, water delivered

**Measurement freshness**:
How recently an actual sensor measurement was obtained, distinct from unrelated
communication or display updates.
_Avoid_: Connectivity, last changed value
