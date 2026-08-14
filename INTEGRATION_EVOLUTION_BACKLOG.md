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
- local sensor entities, activity, freshness, cadence, battery, and dashboards.

Valve telemetry is local. Valve pairing and physical control are not.

Per project direction, do not begin upstream HomGar integration-merger work
until the dedicated test valve completes local pairing and bounded-control
validation.

## Immediate qualification

1. Accumulate a 72-hour sensor cadence and ACK baseline across the installed
   radio-node layout.
2. Reassign one test sensor between nodes and prove the old owner is revoked
   before the new owner transmits.
3. Measure stock-gateway coexistence after migration pairing and retain any
   competing acknowledgement frames.
4. Improve final Wi-Fi/RF placement for nodes with weak margins.
5. Verify reload/restart and HA identity retention after the consolidated
   firmware and gateway release.

## Test-valve gate

Use only the isolated, unpressurized test valve:

1. Record the exact four-zone model and determine whether it uses the known
   HTV145 RF family before sharing any decoder or command body.
2. Capture stock valve pairing and identify every association-specific field,
   including chassis-versus-zone identities and port selection.
3. Reconstruct the exchange offline using parameterized endpoint identities.
4. Pair the valve locally and confirm passive per-zone state telemetry.
5. Join the existing fail-closed safety controller to an experimental command
   transport that targets one user-selected nearest radio node.
6. Transmit an idempotent zone-specific close first and require an idle
   response without changing the other zones.
7. Run a maximum 60-second open trial on one dry zone with the node-local
   watchdog armed before transmission.
8. Audit command, RF frame, response, timeout, retry, watchdog, and final state.

Open is never retried after an ambiguous result. Close may be retried until idle
is observed or a persistent fault is raised.

## Publication hardening after the valve prototype

- Coordinate the provider/identity contract with the existing HomGar
  integration and implement cloud-to-local migration there.
- Add HA-native integration lifecycle coverage and formal entity/config-entry
  migrations.
- Extract typed protocol/API models and structured errors from gateway
  dictionaries.
- Replace five-second full polling with event-driven updates plus slow
  reconciliation.
- Add standalone gateway claim, credential rotation/revocation, encrypted node
  sessions, and replay protection.
- Sign OTA releases and test interrupted download, power loss, and forced
  rollback.
- Separate network-only publishable app packaging from SDR/replay developer
  dependencies and pin build inputs.

See [CLOUD_TO_LOCAL_MIGRATION.md](CLOUD_TO_LOCAL_MIGRATION.md) for the deferred
authority handoff and [research/DEVICE_PAIRING_VALIDATION_PLAN.md](research/DEVICE_PAIRING_VALIDATION_PLAN.md)
for retained physical evidence.
