# Completed reliability collection review

The fixed September 7 00:53:50.839739 UTC–September 10 00:53:50.839739 UTC
window completed automatically. The final scheduler sample was September 10
00:55:00.527875 UTC, about 70 seconds after the boundary. Totals below include
that closing sample and its event drain; they are not an exact 72-hour RF cut.

## Source integrity and method

The completed installation-private SQLite database was copied read-only for
analysis. Source SHA-256 before and after transfer and the local copy all matched
`c131aec2765a97ceddd59e18ffbb81225a6b6b196c3c6561eed06a2565a345b8`.
SQLite `quick_check` returned `ok`. Original database and private captures remain
preserved; no database, raw frame, RF endpoint, credential or node ID is included
here. Analysis used read-only SQLite access to snapshots, events and observations.

The collection contains **874 snapshots and 66,569 events**, with no recorded
collection errors or event-cursor gaps. Maximum snapshot separation was
300.073 seconds. Device gaps combine distinct accepted observation timestamps
with snapshot last-valid-frame timestamps; these measure observed reporting,
not every on-air transmission. Snapshot freshness is measured against the last
valid frame at each snapshot.

## Sensor and ownership observations

Every snapshot contained the same eight device identities. All six sensors were
available and had valid-frame ages below eight minutes at every snapshot. The
maximum sensor observation gap was 563.479 seconds. Each sensor retained one
configured ACK owner across the window. Per-node assigned and authorized sensor
counts agreed in every snapshot; reported sensor ACK failure counters stayed
zero. These establish configured ownership and node diagnostics, not independent
on-air proof that every ACK was accepted.

| Sensor alias | Maximum snapshot age (seconds) | Maximum observed gap (seconds) |
|---|---:|---:|
| Test sensor A | 432.117 | 516.635 |
| Test sensor B | 453.881 | 531.064 |
| Front sensor 1 | 224.931 | 337.811 |
| Front sensor 2 | 414.301 | 563.479 |
| Left Bed | 276.571 | 336.817 |
| Right Bed | 420.417 | 520.254 |

Aliases omit hardware identities. No phantom or missing device appeared in the
snapshot inventory. This does not independently audit every HA entity or prove
absence of overlapping on-air ACKs between snapshots.

## Valves, synchronization and interventions

The four-zone valve recorded morning sync success September 7 at 05:33:11,
September 8 at 05:36:48, and September 9 at 05:33:49 Eastern. The single-zone
valve recorded morning success September 7 at 05:33:46 on its earlier association
and September 9 at 06:17:25 on the qualified custom association. September 8
recovery results belong to active qualification work, not a scheduled morning
success. Association changes and the rejected bootstrap anchor remain part of
the evidence; later success does not erase them.

The single-zone longest observed report gap was 4,019.817 seconds, September 7
17:48:12–18:55:12 UTC, overlapping the documented pairing/handoff work. Its
availability flag remained true, so availability alone would hide this gap.
The four-zone maximum observed gap was 976.037 seconds. Both valves were idle
and sync Ready at the closing snapshot.

The already-reported September 9 front-garden run has accepted valve observations
from 07:00:01 watering to 07:35:03 idle Eastern. The user confirmed configuring
35 minutes. Saved HA helpers corroborate the 07:00 check and 07:00:01 start;
the original decision text and actual push delivery remain unverified after HA
restart. See [scheduled run evidence](fixtures/htv145_scheduled_watering_20260909.json).

There were 83 connected events, two disconnected events and 11 reboot-observed
events. Multiple gateway deployments, pairing/control trials and firmware
versions occurred. All three radios reached 0.17.0 only on September 9; thus
this is **completed observation and recovery evidence, not an uninterrupted
72-hour final-release qualification**. No new RF experiment or live-system
change was performed for this review.

Physical ACK waveform acceptance, unchanged-release stability, battery recovery,
coexistence and the remaining irrigation matrix cannot be closed by this passive
collection. Current gates remain solely in [the roadmap](../PROJECT_ROADMAP.md).
