# Integration evolution backlog

## Current baseline

The supported sensor path is now one coherent stack:

- one standard ESP32/CC1101 firmware image;
- authenticated multi-node reception and deduplication;
- HA-managed node adoption, naming, areas, Identify, diagnostics, and OTA;
- generalized HCS026 pairing across independent identities;
- identity-preserving reassociation of existing HA sensors;
- button-only recovery of known dormant sensors;
- persistent single-owner acknowledgements restored after reconnect/reboot; and
- local sensor entities, activity, freshness, cadence, battery, and dashboards;
- durable event-cursor long polling with slow full-snapshot reconciliation;
- standalone gateway claim, management-token rotation, radio-node adoption,
  per-node credentials, and immediate revocation; and
- timezone-aware transport timestamps plus legacy local-SDR normalization with
  UTC, offset, half-hour, and DST regression coverage.

HTV405 telemetry, local enrollment, all-zone bounded control, per-zone duration
entities, authenticated responses, valve-owned automatic stop, and Zone 1
early stop are available behind the disabled-by-default supervised beta. Local
HTV145 transmit remains compile-gated and physically unaccepted.

Per project direction, do not begin upstream HomGar integration-merger work
until the dedicated test valve completes local pairing and bounded-control
validation.

## Immediate qualification

1. Physically enroll a disposable sensor under the staged persistent custom RF
   controller identity while the stock gateway remains powered. Verify both
   stock-owned and locally owned cohorts continue reporting and receiving ACKs.
2. Accumulate a 72-hour sensor cadence and ACK baseline across the installed
   radio-node layout.
3. Reassign one test sensor between nodes and prove the old owner is revoked
   before the new owner transmits.
4. Measure stock-gateway coexistence after migration pairing and retain any
   competing acknowledgement frames.
5. Improve final Wi-Fi/RF placement for nodes with weak margins.
6. Verify reload/restart and HA identity retention after the consolidated
   firmware and gateway release.

## HTV405 beta qualification

Completed evidence covers the exact HTV405 model, association-specific 18-step
enrollment, parameterized offline reconstruction, passive per-zone telemetry,
one- and two-minute dry opens on all four zones, authenticated command
responses, independent active/idle reports, single-zone exclusivity, durable
counter state, valve-owned automatic stop, and Zone 1 early stop. Open is never
retried after an ambiguous result; close is limited to explicit early stop or a
fresh report proving an overdue run.

Remaining qualification:

1. Retain the installed Zone 1 longer-duration field result across RF,
   gateway, HA completion notification, usage, and watchdog layers.
2. Prove retained association and command-counter recovery after battery
   removal without changing the validated new-enrollment path.
3. Correlate a controlled HTV405 normal-to-low battery transition.
4. Physically exercise local early stop on Zones 2--4 and positively observed
   overdue-run recovery.
5. Repeat association and control acceptance on another specimen/profile.

## Publication hardening after the valve prototype

- Coordinate the provider/identity contract with the existing HomGar
  integration and implement cloud-to-local migration there.
- Add HA-native integration lifecycle coverage and formal entity/config-entry
  migrations.
- Extract typed protocol/API models and structured errors from gateway
  dictionaries.
- Add encrypted node sessions and replay protection on top of the existing
  claim, rotation, adoption, and revocation lifecycle.
- Sign OTA releases and test interrupted download, power loss, and forced
  rollback.
- Separate network-only publishable app packaging from SDR/replay developer
  dependencies and pin build inputs.

See [CLOUD_TO_LOCAL_MIGRATION.md](CLOUD_TO_LOCAL_MIGRATION.md) for the deferred
authority handoff and [research/DEVICE_PAIRING_VALIDATION_PLAN.md](research/DEVICE_PAIRING_VALIDATION_PLAN.md)
for retained physical evidence.
