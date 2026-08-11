# Federico garden Home Assistant example

This directory is an installation-specific example, not a default dashboard
or a source of canonical device identities.

`garden-local-dashboard.yaml` is a read-only reliability dashboard for the
`rainpoint_local` integration. It mirrors the production Garden dashboard but
uses local RF entities for all RainPoint moisture, valve-state, usage, battery,
signal, and last-report data.

Valve control and watering automations deliberately remain on the production
path until local transmit support is validated. The dashboard is installed as
the separate `garden-local-dashboard` YAML dashboard, so it does not modify the
production Garden dashboard.
