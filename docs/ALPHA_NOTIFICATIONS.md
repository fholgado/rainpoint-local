# Alpha notifications and failure coverage

The integration supplies device entities and reports failed service calls to HA.
It does **not** automatically create a garden dashboard, scheduled irrigation,
push notifications or a household watchdog. The examples for the original
installation are not a portable safety package.

## What is currently observable

| Signal | Available evidence | Limit |
|---|---|---|
| Sensor/valve freshness | Device report time; accepted telemetry | HA availability alone can hide a long report gap |
| HTV405 control failure | Valve `transaction_state`, `transaction_id`, `transaction_error`; Control request status | A failure does not prove no water flowed |
| HTV145 overdue run | Valve `overdue`, `expected_idle_at`, `confirmed_at` | Missing idle evidence is an anomaly, not proof it is still open |
| HTV145 command failure | Service-call error, retained-counter/radio status | Not every failure has a persistent transaction error entity yet |
| Both families' morning sync | Status, reason and last-success time | A successful sync is not a watering confirmation |

The HTV145 persistent-failure gap remains in the roadmap. Do not advertise
universal failed-irrigation alerts until that state and actual delivery have
been verified. Automation traces are also not a permanent notification log.

## Optional observation-only blueprints

Copy the YAML files from `blueprints/automation/rainpoint_local/` into the same
directory under HA's `/config/blueprints/automation/rainpoint_local/`. Reload
automations/blueprints and create an automation from each desired blueprint.
They are not installed by HACS and are not enabled automatically.

- **Stale device report:** select that device's **Device report time**, not a
  morning-sync or other timestamp. Default threshold is eight hours, plus a
  ten-minute grace period for short disconnects. Unknown/unavailable timestamps
  or timestamps over five minutes in the future also alert after grace. Create
  one automation per device. This threshold does not change watering decisions.
- **Reported valve problem:** select the physical valve's entity. For HTV405,
  choose one zone entity per physical valve because transaction attributes are
  shared. It alerts on failed/interrupted transactions or an HTV145 overdue
  transition, not on every unavailable state or every rejected HA service call.

Each creates or updates a stable persistent notification in HA **before** any
optional phone action. The message remains until manually dismissed; recovery
does not erase the evidence. A new failure transaction can alert again;
unrelated attribute changes do not repeatedly push the same failure.
Stale-report alerts trigger when the condition becomes true, not periodically
while it stays true. If dismissed while still stale, they are not reminders.
Grace timers reset after HA restart/automation reload.

In **Additional notification actions**, choose your own mobile notification
action and set its title to `{{ notify_title }}` and message to
`{{ notify_message }}`. Leave it empty for HA notifications only. Do not put
watering, automatic retries, re-pairing or reboot actions in that input.
Critical push permissions and delivery depend on your phone; the blueprint does
not enable them or confirm delivery.

YAML and template decision logic are tested locally. Import, actual trigger
scheduling and phone delivery still need verification on a clean HA installation.
Use a temporary timestamp/helper on a test instance to exercise a stale case;
do not unplug production nodes or deliberately water a garden to test an alert.

## Before enabling a tester's irrigation automation

Observe physical start, automatic stop and early stop, then check the matching
HA state and notification. Retain a fallback water plan. A command being sent,
a failed request, or stale sensor data must not be interpreted as definitive
valve state. Do not add automatic open retries without the protocol's confirmed
command/counter safeguards. If physical state is uncertain, inspect the valve
or shut off its supply.

See HA's [blueprint schema](https://www.home-assistant.io/docs/blueprint/schema/)
and [template trigger semantics](https://www.home-assistant.io/docs/automation/trigger/#template-trigger).
The project acceptance checklist remains in [the roadmap](../PROJECT_ROADMAP.md).
