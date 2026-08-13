# Integration evolution backlog

## Current milestone

RainPoint Local has crossed the receive-only proof-of-concept boundary. It now
has a persistent logical gateway, multiple receiver support, authenticated
Wi-Fi radio nodes, Home Assistant-managed node adoption and diagnostics, and a
physically proven local HCS026 pairing exchange. The current source versions
are:

- `rainpointd` add-on 0.18.2;
- `rainpoint_local` integration 0.8.2;
- ESP32 production firmware 0.6.0; and
- ESP32 pairing-generalization test firmware 0.7.0-test.3.

The next product milestone is not more carrier-board optimization. It is an
end-to-end local software stack whose sensor lifecycle is reliable enough for
unattended use, followed by a physically validated and fail-closed valve path.

## Working functionality

The following behavior is implemented and regression-tested unless a physical
qualification is explicitly noted:

- transport-neutral RF ingestion shared by RTL-SDR, serial, and Wi-Fi nodes;
- stable gateway and radio-node identities, authenticated node sessions,
  receiver attribution, cross-receiver deduplication, and coverage metrics;
- persistent managed-node records, Home Assistant diagnostic devices, bounded
  **Identify**, zeroconf discovery, and gateway-controlled adoption sessions;
- persistent device, observation, enrollment, suppression, event, and
  receiver state in a versioned SQLite store;
- transactional local forget behavior that transmits no RF reset and prevents
  an ignored endpoint from silently recreating an HA device;
- evidence-based product-family and capability inference without claiming an
  exact retail model from frame shape alone;
- physically proven local HCS026 pairing for both test identities using an
  explicitly selected ESP32/CC1101 node and terminal RF confirmation;
- a model-level `hcs026_auto_v1` workflow that passed end to end on Sensor A
  without a user-supplied RF identity or transcript;
- dynamic Home Assistant entities, report activity, last-report time, battery
  state where decoded, and radio-node diagnostics; and
- production firmware boundaries that exclude research tuning and unrestricted
  transmit commands.

Valve telemetry decoding and offline frame generation exist. Physical valve
pairing and control do not.

## Software work that can proceed without RF hardware

These items improve real functionality and publication readiness without
requiring a sensor, valve, SDR, or attached ESP32 during implementation.

### P0 — Home Assistant lifecycle correctness

- Add HA-native config-flow and entity/device-registry tests for discovery,
  adoption, pairing, rename, forget, re-pair, reload, and restart.
- Preserve user-disabled entities while allowing integration-owned disabled
  entities to return after intentional reassociation.
- Define when a forgotten device remains in the HA device registry and when it
  may be removed, without conflating HA removal with an RF reset.
- Replace one-off setup-time entity repairs with versioned config-entry and
  entity migrations.

### P0 — gateway and node credential lifecycle

- Add a one-time claim flow for standalone gateways that cannot use Supervisor
  discovery.
- Implement gateway and per-node credential rotation, revocation, expiry, and
  repair flows.
- Make node removal and reprovisioning explicit operations in Home Assistant.
- Keep node credentials private and independently revocable.

### P0 — versioned, typed local API

- Introduce typed identities, observations, capabilities, commands,
  acknowledgements, and structured errors at the gateway boundary.
- Add explicit capability and protocol-version negotiation between HA,
  `rainpointd`, and radio nodes.
- Bound request sizes, connections, threads, event cursors, and malformed
  message handling.
- Preserve the current API while migrating clients through an additive version
  boundary.

### P1 — push-driven Home Assistant updates

- Replace unconditional five-second full polling with an event cursor or push
  subscription.
- Retain a low-frequency reconciliation poll for restart and missed-event
  recovery.
- Trigger immediate refresh after management commands and expose connection
  health separately from device report cadence.

### P1 — production/development packaging split

- Publish a production add-on path containing network radio-node operation and
  supported local functionality only.
- Keep replay, broad IQ capture, fixed research profiles, USB permissions, and
  writable share access in an explicit developer/research profile.
- Pin base images and dependencies and add add-on schema/build validation.

### P1 — transport-neutral protocol package

- Extract the decoder and identity/capability catalog into an installable
  package that neither imports Home Assistant nor owns installation names.
- Make replay, SDR, serial, and Wi-Fi adapters emit the same typed observation.
- Keep captured RF evidence and provisional decoders clearly separated from
  the supported public contract.

### P1 — OTA and fleet management

- Define signed firmware metadata, compatibility checks, staged rollout,
  rollback, and recovery behavior.
- Expose available/current firmware and update health through HA without
  allowing an incompatible gateway/node combination.
- Keep USB recovery documented even after OTA exists.

OTA can be designed and tested largely offline, but it is not complete until a
real node passes update, rollback, power-loss, and recovery tests.

## Physical evidence gates

The following work must not be declared complete from simulated or offline
tests alone.

### Sensor release qualification

- Repeat `hcs026_auto_v1` on Sensor B.
- Complete power-cycle/rejoin, gateway restart, and radio-node restart tests
  without creating a second HA device.
- Complete the unattended reporting, overlapping-receiver, interruption, and
  forget/reassociation matrix in
  [`research/DEVICE_PAIRING_VALIDATION_PLAN.md`](research/DEVICE_PAIRING_VALIDATION_PLAN.md).
- Determine whether the P1–P6 soil profile is transmitted, display-local, or
  cloud-only before exposing it as writable functionality.

### Valve association and bounded control

Use only the dedicated test valve. The required order is:

1. Capture stock pairing and identify association-specific fields.
2. Reconstruct and compare the association exchange offline.
3. Pair the test valve locally without connecting it to pressurized water.
4. Parameterize valve and controller identity outside the protocol core.
5. Join the hardware-independent safety controller to an experimental command
   transport.
6. Transmit an idempotent close first and require an idle response.
7. Run a maximum 60-second open trial with the node-local watchdog armed before
   transmission.
8. Audit request, RF frame, response, timeout, retry, watchdog, and final state.

Until this passes repeatedly, valve TX remains absent from the normal Home
Assistant UI and production node command vocabulary. Open is never retried
after an ambiguous result; close may be retried. Each valve has exactly one
user-selected preferred transmitter node and fails closed when that node is
unavailable.

## Deferred until the valve gate

- The active cloud-to-local migration wizard.
- Local watering schedules intended to replace vendor automation.
- General claims of cloud-independent irrigation control.
- Enabling valve commands in the public gateway API or production firmware.

Architecture and identity coordination with the existing HomGar/RainPoint
integration can continue now. Migration code should wait until repeatable
sensor/valve association and bounded valve control establish the physical
identity and authority contract.

## Recommended implementation order

1. HA-native lifecycle tests and formal migrations.
2. Standalone claim plus credential rotation/revocation.
3. Typed API models, capability negotiation, and structured errors.
4. Push-driven HA updates with reconciliation fallback.
5. Production/development add-on separation.
6. Transport-neutral protocol-package extraction.
7. OTA design and offline compatibility tooling.
8. Finish sensor physical qualification.
9. Pair and safely control the dedicated test valve.
10. Coordinate and implement cloud-to-local migration upstream.

This order lets unattended software hardening continue without turning
unverified RF behavior into a public promise.
