# Federico garden Home Assistant example

This directory is an installation-specific example, not a default dashboard
or a source of canonical device identities.

`garden-local-dashboard.yaml` is an installation-specific reliability and
control dashboard for the `rainpoint_local` integration. It mirrors the
production Garden dashboard while using local RF entities for RainPoint
moisture, HTV405 Zone 1 state/control, signal, and last-report data. Its Run
Now control follows the gateway-owned transaction state: it is disabled while
synchronizing or watering, and a status tile reports confirmation or failure.
HTV405 battery is intentionally shown as unavailable until its RF field is
independently validated, and the dashboard exposes no water-usage entity
because this model has no water-volume capability.

`garden-local-scripts.yaml` contains the matching manual-run script fragment.
The valve path submits one request, waits for a new transaction ID, and returns
as soon as that transaction confirms watering or fails. The generic switch
path remains available for other installations.

The front garden now uses the HTV145 single-zone control. Merge
`single-valve-scripts.yaml` into scripts and include
`front-irrigation-package.yaml` as a Home Assistant package. Both manual and
scheduled calls use `confirmation_mode: single_valve`, the valve control and
its watering-duration number. The scheduled adapter is selected **after** the
existing season, local-moisture freshness and rain checks, without changing the
schedule or decision helpers. The single-valve helper requires a fresh confirmed
open within 40 seconds, retains push failures in HA notifications, then waits for
confirmed idle. It never infers success from transmission or retries an
unconfirmed open. Run Now is unavailable while starting, watering, or not ready.

Point the front watchdog at the same local valve, using `open`/`closed` and its
report-time entity. Retire the old switch's meter-start, session-total and daily
reset automations. Old meter helpers/history may remain for historical reference,
but are not used by this dashboard. The single-zone reported volume is in liters;
do not sum it as a cumulative meter or present old Sonoff totals as RainPoint data.
Enable the single-zone morning sync before the scheduled run, using the local
timezone. This installation uses 06:15 America/New_York with a 30-minute window
before its unchanged 07:00 schedule (30-minute watering duration).

The installation's watering scripts and watchdog target the locally paired
HTV405 Zone 1. This file is installed as the primary Garden YAML dashboard;
the superseded cloud comparison dashboard has been decommissioned.
