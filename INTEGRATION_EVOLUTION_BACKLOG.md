# Integration evolution backlog

## Current sequencing decision

Finish physical validation of the custom radio node and bounded valve control
before merging this prototype into the broader HomGar/RainPoint integration.
The local gateway API and Home Assistant UI may be hardened in the meantime,
but they must not imply that unverified valve control or model-wide sensor
pairing is supported.

## Completed foundation

The following architecture work is implemented and covered by regression
tests:

- transport-neutral RF ingestion shared by RTL-SDR, serial, and Wi-Fi nodes;
- stable per-node identity, authenticated node sessions, receiver attribution,
  cross-receiver deduplication, and per-receiver coverage metrics;
- managed node registry, Home Assistant diagnostic devices, bounded Identify,
  and gateway-controlled adoption sessions;
- a first-boot commissioning candidate with temporary AP provisioning, mDNS
  discovery, physical confirmation, and Home Assistant adoption;
- persistent device/enrollment state, transactional forget behavior, and
  Home Assistant entity reconciliation;
- an evidence-backed pairing-profile registry shared by gateway and firmware;
- production firmware boundaries that exclude research serial TX controls.

The deployed gateway/UI reference is add-on 0.16.1 and integration 0.6.2. The
existing radio node remains on firmware 0.5.0. Firmware 0.6.0 and the dormant
zero-copy commissioning path await physical validation with the second node.

## Next physical milestone: second radio node

The second node should validate the distributed-node assumptions end to end:

1. Boot without a serial tether and advertise itself for adoption.
2. Appear automatically in Home Assistant without copying a node ID or token.
3. Require physical confirmation before receiving its managed credential.
4. Blink through **Identify** so the user can distinguish nearby nodes.
5. Receive the same RF frame as the existing node/RTL-SDR without duplicating
   device cadence or Home Assistant activity.
6. Retain receiver-specific packet and coverage metrics for placement choices.
7. Reconnect after power loss without repeating commissioning.

Do not promote firmware 0.6.0 or describe zero-copy commissioning as validated
until these checks pass or a narrow fix is physically retested. The deployed
gateway and integration contain the inactive commissioning contract so the
second node can exercise it without another HA-side upgrade.

## Sensor-pairing boundary

Local HCS026 pairing is real but intentionally narrow. Protocol profile
`hcs026_15a98024_v1` represents the one factory/paired identity and reply
sequence physically proven on 2026-08-11. The orchestration is profile-driven;
the captured bytes are not presented as a generic HCS026 formula.

The next test sensor should be paired in isolation and compared field by field.
Only evidence common to multiple identities may become model-wide behavior.
Differences become validated profile parameters, never household conditionals.
The complete remaining sensor matrix and the staged stock-to-local valve
association procedure are maintained in
[`research/DEVICE_PAIRING_VALIDATION_PLAN.md`](research/DEVICE_PAIRING_VALIDATION_PLAN.md).

## Valve-control gate

The RTL-SDR remains an independent reference receiver while the first bounded
valve prototype is validated:

1. Compare ESP32/CC1101 receive timing and frames with the RTL-SDR.
2. Verify wake sequence, carrier, deviation, symbol timing, frame bits, and
   output power with the SDR before addressing a valve.
3. Parameterize controller and valve identities outside the protocol core.
4. Transmit an idempotent close first and require a correlated idle response.
5. Run a maximum 60-second open trial with the node-local watchdog armed before
   transmission.
6. Audit request, frame, response, timeout, retry, watchdog, and final state.
7. Repeat until every success and failure returns to confirmed idle without
   cloud data.

Until that gate passes, valve TX stays out of the Home Assistant UI and general
network API. Opens are never retried after ambiguous results; only close may be
retried. A valve has exactly one user-selected preferred transmitter node, and
an unavailable preferred node fails closed rather than broadcasting through
several nodes.

## Production boundaries still to finish

- Split published add-on operation from replay, broad capture, and other
  research-only startup modes.
- Replace trusted-LAN plaintext node/API transport before enabling valve
  control outside controlled testing.
- Add credential rotation, revocation, OTA compatibility checks, and rollback.
- Move remaining installation compatibility identities into a versioned
  registry migration; keep this house's dashboard under `examples/` only.
- Extract typed protocol identities, observations, capabilities, commands, and
  acknowledgements into an installable transport-neutral package.
- Add Home Assistant-native config-flow/entity lifecycle tests and add-on
  schema/build validation.

## Integration direction after the valve gate

The existing integration can expose cloud and custom-local providers while
assigning every physical device exactly one state/control authority. Migrating
users should retain their Home Assistant devices, entities, history, and
customization. Cloud observations may remain available for verification, or
for models not supported locally, but must not overwrite locally authoritative
state. Fresh local setup remains supported so the system survives loss of the
vendor cloud.

Before freezing a public provider contract, coordinate identity fields,
unique-ID migration, capability names, and API versioning with the existing
integration maintainers.

The proposed authority handoff, identity aliasing, verification period,
rollback limits, and upstream coordination schedule are specified in
[`CLOUD_TO_LOCAL_MIGRATION.md`](CLOUD_TO_LOCAL_MIGRATION.md). Provider and
identity review can begin before the RF gates pass; the active migration wizard
must wait for repeatable sensor/valve association and bounded valve control.
