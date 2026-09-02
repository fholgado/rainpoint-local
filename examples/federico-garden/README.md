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
path retains its timed shutdown behavior for the non-RainPoint front-yard
valve.

The installation's watering scripts and watchdog target the locally paired
HTV405 Zone 1. This file is installed as the primary Garden YAML dashboard;
the superseded cloud comparison dashboard has been decommissioned.
