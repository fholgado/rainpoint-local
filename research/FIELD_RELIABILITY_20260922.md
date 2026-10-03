# Reference-installation field reliability — September 22, 2026

Historical evidence, not a second checklist. Acceptance status belongs in the
[roadmap](../PROJECT_ROADMAP.md). This review did not change the live system,
issue watering commands, or restart the paused reliability collector.

## Scope and evidence

- Gateway 0.39.0; both production radios report unified firmware 0.19.0.
- Read-only gateway snapshots, 100,000 consecutive retained events, and HA saved
  automation/script traces. Initial event IDs: 582112–682111, spanning September
  17 01:48 through September 22 06:57 Eastern. A subsequent 38-event read checked
  recovery through approximately 07:00 Eastern.
- The event retention cap prevents claims about earlier days. Consecutive stored
  IDs do not prove that every over-air packet was received; outages can hide RF.
- Private raw snapshots/events/traces remain outside published documentation in
  the local `/tmp/rainpoint-health-20260922` evidence directory. This report
  preserves the conclusions without credentials, household RF IDs, or HA traces.
- The dedicated fixed-window soak collector remained paused. This is a passive
  field review, not a new completed instrumented 72-hour qualification.

## Reporting and recovery

All six sensors and both valves reported again after the September 22 host
restart at 06:50:56 Eastern. The two production radios reconnected around
06:52:15 without a corresponding radio reboot. At approximately 07:00, all
devices were reporting; their latest accepted reports/frames were under six
minutes old. The non-production OTA test node remained offline during PCB work.

| Reference device | Longest observed sensor/state-report gap |
| --- | ---: |
| Test Sensor A | 8.9 minutes |
| Test Sensor B | 15.6 minutes, including Sep 22 restart recovery |
| Left Bed | 5.6 minutes |
| Right Bed | 8.7 minutes, including restart recovery |
| Front Right | 5.8 minutes |
| Front Left | 5.5 minutes |
| Single-zone valve | 11.7 minutes |

Before the final post-restart read, every sensor's completed reporting gap was
under nine minutes. Test Sensor B subsequently completed a 934.3-second gap,
exceeding its 900-second freshness threshold by 34.3 seconds. It recovered
without pairing intervention; this is not evidence of zero stale-state events.

The four-zone valve's longest accepted RF-frame gap was 22.8 minutes, below its
one-hour reporting timeout. Full state observations can be about ten hours apart;
routine RF traffic and state-changing telemetry are distinct evidence streams.

The garden radio had 10.9 days uptime. The front radio had 2.7 days uptime after
a September 19 15:06 power-on reset; the reason for that power interruption was
not established. Both reported about 193 KB free heap and valid radio
configuration. Front Wi-Fi was approximately -87 dBm; garden Wi-Fi was -32 dBm.
These snapshots do not establish a complete memory or connectivity time series.

There were 23,447 sensor ACK-transmitted events and 2,433 four-zone ACK-transmitted
events in the initial window, with no recorded ACK-transmit failures. Transmit
success alone does not prove device receipt; continued reports provide the
separate operational evidence. Current inventory contained eight expected
devices and six unique sensor ACK owners, not an audit of historical HA registry
duplicates.

## Watering and synchronization

All times below are Eastern. Durations refer to decoded requests and observed
valve responses, not physical water-flow measurements.

| Valve | Date/start | Run | Evidence |
| --- | --- | --- | --- |
| Four-zone, Zone 1 | Sep 17 06:30 | Scheduled, 21 minutes | Authenticated open response; watering telemetry; idle around 06:51 |
| Four-zone, Zone 1 | Sep 20 06:30 | Scheduled, 21 minutes | Authenticated response, HA scheduled-run trace, idle around 06:51 |
| Four-zone, Zone 1 | Sep 21 10:30 | Manual, 21 minutes | HA manual-run trace, authenticated response, idle around 10:51 |
| Single-zone | Sep 17 07:00 | Scheduled, 35 minutes | Valve watering/idle reports around 07:00/07:35 |
| Single-zone | Sep 18 07:00 | Scheduled, 35 minutes | Valve watering/idle reports around 07:00/07:35 |
| Single-zone | Sep 19 07:00 | Scheduled, 35 minutes | Valve watering/idle reports around 07:00/07:35 |
| Single-zone | Sep 21 07:00 | Scheduled, 35 minutes | HA scheduled/script traces and valve watering/idle reports |

The four-zone initial watering telemetry arrived about six seconds after its
authenticated response; measuring only telemetry-to-idle undercounts duration.
Single-zone observed watering-to-idle intervals were approximately 2,102 seconds.
Seven starts had corresponding reported stops; six runs were scheduled.

All six four-zone morning-sync attempts, Sep 17–22, reached authenticated anchor
confirmation. This proves the bounded daily recovery path, not indefinite retained
counter validity or the cause of any counter reset.

Saved HA traces additionally confirm:

- Sep 20 front-yard watering was skipped with fresh readings of 70%/71% against
  a 70% threshold.
- Sep 21 garden watering was skipped with fresh readings of 66%/65% against 65%.
- Sep 22 garden watering was skipped with fresh readings of 71%/69% against 65%.
- The Sep 21 single-zone script completed after the valve-reported stop.
- Retained watchdog traces ended at a false condition, not a script error;
  their limited retention does not audit every watering run's watchdog outcome.

## Limits on acceptance credit

This supports sustained reference-device associations, repeated report/ACK
cycles, six scheduled watering successes, daily synchronization and spontaneous
host-restart recovery. It does not prove stock/custom coexistence, battery rejoin,
new wizard pairing/removal, arbitrary command ordering, controlled long outages,
no command replay under every restart case, rendered UI/push delivery, or physical
OTA rollback. Those gates remain open. A fresh generic 72-hour run is not required
solely to repeat this evidence.
