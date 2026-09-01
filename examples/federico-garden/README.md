# Federico garden Home Assistant example

This directory is an installation-specific example, not a default dashboard
or a source of canonical device identities.

`garden-local-dashboard.yaml` is an installation-specific reliability and
control dashboard for the `rainpoint_local` integration. It mirrors the
production Garden dashboard while using local RF entities for RainPoint
moisture, HTV405 Zone 1 state/control, signal, and last-report data. HTV405
battery is intentionally shown as unavailable until its RF field is
independently validated, and the dashboard exposes no water-usage entity
because this model has no water-volume capability.

The installation's watering scripts and watchdog now target the locally paired
HTV405 Zone 1. The dashboard is installed as the separate
`garden-local-dashboard` YAML dashboard, so it does not modify the original
cloud comparison dashboard.
