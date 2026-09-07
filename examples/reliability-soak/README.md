# Durable reliability collection example

This read-only collector runs in Home Assistant, independently of a Mac or agent
session. It does not send RF commands, change schedules, or automatically declare
a qualification gate passed.

1. Back up HA configuration.
2. Copy `tools/reliability_soak.py` into `/config/rainpoint-local/`.
3. Include [package.yaml](package.yaml) through HA packages and set its gateway URL.
4. Check HA configuration and restart/reload the affected integrations.
5. Verify `/config/rainpoint-local/reliability-status.json` advances every five
   minutes. Database and status output are private installation artifacts.

The first successful initialization fixes a 72-hour window. Restart/repeated
collection cannot extend it. The automation runs at HA startup and every five
minutes, then disables itself after a final snapshot at or after the deadline.
HA downtime is an observation gap, not a successful interval. The collector
records API failures and missing event IDs, and preserves its cursor on failure.

The SQLite database contains `snapshots`, deduplicated `events`, collection
`observations`, and fixed-window `metadata`. Review report gaps, receiver/ACK
ownership, reboot/connection events, valve readiness/counters, and morning outcomes.
A completed collection is not a passed 72-hour physical qualification: battery
cycles, controlled coexistence, and scheduled watering need their own evidence.

The call uses bounded API pages and five-second request timeouts to fit HA's
[shell command execution limit](https://www.home-assistant.io/integrations/shell_command/).
No API write credential is needed. To start a separate trial, preserve the old
database and deliberately choose a new path; never reset an ongoing window.
