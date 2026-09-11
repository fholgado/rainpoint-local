# Alpha watering notifications

The draft integration enables HA notification-panel messages automatically.
No blueprint or phone setup is required for basic watering visibility.

## Default messages

- **Watering:** the valve reports an open state. For a confirmed requested run,
  include its requested duration (for example, 21 minutes) and zone when known.
- **Stopped:** a previously watering valve reports idle. This does not claim
  the full requested duration elapsed or any particular volume was delivered.
- **Command failed:** a command failed/interrupted at the gateway, or an HA valve
  request was refused/could not reach the gateway. Inspect the valve before retrying.
- **Needs attention:** the single-zone valve's expected stop has not been confirmed.

There is one latest-run message and one problem message per physical valve,
scoped to the integration entry. Repeated telemetry does not repeatedly notify.
Recovery does not dismiss a problem; users can dismiss it themselves.
Unknown/unavailable state never counts as a confirmed stop. These notices are
observation-only: they do not water, retry, synchronize or reboot anything.

The notification panel is not a permanent watering-history archive. HA restarts
can clear panel messages; on integration setup a currently reported watering
state or outstanding problem may be shown again, but past idle runs are not
reconstructed. Short runs occurring entirely between snapshots may be missed.
For automation decisions, use the valve entities and transaction diagnostics,
not notification delivery as proof of irrigation.

## Optional mobile forwarding

Each new/updated default message also fires
`rainpoint_local_watering_notification` with `title`, `message`,
`notification_id` and `entry_id`. A user can forward it to their own mobile
notification action. For example, create an HA automation and replace the
placeholder service below with their phone's actual notification service:

```yaml
alias: RainPoint watering messages to my phone
triggers:
  - trigger: event
    event_type: rainpoint_local_watering_notification
actions:
  - action: notify.mobile_app_your_phone
    data:
      title: "{{ trigger.event.data.title }}"
      message: "{{ trigger.event.data.message }}"
      data:
        tag: "{{ trigger.event.data.notification_id }}"
mode: queued
```

The integration never selects a phone, enables critical alerts or sends mobile
messages itself. Users with multiple gateways can filter on `entry_id`.

## Optional stale-report monitoring

The **Stale device report** blueprint under
`blueprints/automation/rainpoint_local/` remains optional. Install it under the
same path in HA's configuration directory, then create an automation selecting
the device's **Device report time**. Its default is eight hours plus ten minutes
of grace; configure this for the device's reporting cadence.

The existing **Reported valve problem** blueprint is retained for older
integration versions or customized alert routing. On this version its failure
coverage overlaps the built-in notices, so normally use the event-forwarding
automation above instead of enabling both.

Blueprints are not installed by HACS. Each offers optional mobile actions after
creating its HA notice; see the blueprint's inputs for setup.

## Status and limits

Default notifications are implemented in the local review draft and covered by
snapshot/callback tests. Clean HA rendering, notification dismissal and actual
phone forwarding still need validation before rollout. Nothing has been deployed
to the household by this change.

The integration does not install watering schedules, garden dashboards or a
household watchdog. Examples under `examples/federico-garden/` are not a portable
automation package. Before relying on irrigation, test a valve dry or visually
confirm its opening and closing. Remaining work belongs in the
[project roadmap](../PROJECT_ROADMAP.md).
