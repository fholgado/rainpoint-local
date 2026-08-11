# Integration evolution backlog

## Sequencing decision

Do not begin the larger Home Assistant integration abstraction yet.

The immediate priority is to finish RF verification and demonstrate a safely
bounded, end-to-end valve-control prototype using the custom local RF gateway.
The integration/provider work below is intentionally deferred until that
prototype has proven the critical protocol and hardware assumptions.

This does not change the product direction in [`PRODUCT_BRIEF.md`](PRODUCT_BRIEF.md).
It establishes the order in which the work should happen.

## Current priority: end-to-end transmit prototype

The prototype path is:

```text
bounded test request
        |
rainpointd safety controller
        |
ESP32 + CC1101 command waveform
        |
HTV145FRF valve
        |
returned RF state / acknowledgement
        |
RTL-SDR reference + rainpointd audit record
```

The existing RTL-SDR remains the independent reference receiver while the
first ESP32 and CC1101 are developed as a local radio node. `rainpointd` is the
logical custom local RF gateway and will eventually coordinate multiple nodes
placed near different coverage areas.

### Required work

1. Validate ESP32/CC1101 reception against packets observed by the RTL-SDR.
2. Reproduce the measured long alternating command wake sequence.
3. Validate carrier center, deviation, symbol timing, frame bits, and output
   power using the SDR before addressing the valve.
4. Connect the existing offline command-frame builder to a laboratory-only
   firmware transmit path.
5. Determine or safely constrain sequence, trailer-residue, and replay
   behavior sufficiently for controlled trials.
6. Transmit close first and confirm the valve's returned idle state.
7. Perform bounded open trials with the watchdog armed before transmission.
8. Decode and correlate the returned valve state, duration, and usage.
9. Record every request, transmitted frame, response, timeout, close retry,
   watchdog action, and final state.

### Multi-node constraints to preserve now

The first prototype uses one USB-connected radio node, but its data model must
not assume that only one node can exist:

- Give every radio node a stable `node_id`.
- Include `node_id` and receiver diagnostics with every observation.
- Keep RF device identity independent of the node that heard it.
- Make central event handling capable of deduplicating the same frame received
  by several nodes.
- Represent a preferred transmitter node separately from device identity.
- Require the user to select the closest transmitter node for every valve in a
  multi-node installation before enabling local control.
- Validate the assignment with a close/idle exchange and retain receive-quality
  data only as a recommendation.
- Never broadcast valve-open commands through multiple nodes.
- Require a node-local hard timeout for any node allowed to transmit.
- Authenticate each future Wi-Fi node independently so one credential can be
  revoked without rebuilding the device registry.
- Do not automatically fail an open command over to another node when the
  assigned transmitter is unavailable; reserve alternate-node attempts for
  sequential emergency close recovery.

### Radio-node commissioning gap

The current HA **Add** control configures another logical custom local RF
gateway; it does not commission a radio node. Nodes still require a manually
generated credential in the add-on configuration plus USB serial Wi-Fi
provisioning. Before the integration is publishable, add a separate **Add local
radio node** options flow backed by a persistent gateway-owned node registry,
time-limited commissioning, automatic authenticated completion, HA device
registration, credential rotation, and revocation. Adding a node must never
create another integration entry or change RainPoint device identities.

After the one-node transmit path is proven, add the Wi-Fi transport and a
second node to validate deduplication, coverage reporting, transmitter
selection, and controlled failover.

### Prototype safety boundary

Until validation is complete:

- Do not expose transmission through Home Assistant or a general network API.
- Keep the transmit path behind an explicit laboratory build or local test
  harness.
- Limit initial opens to 60 seconds.
- Arm the hard close deadline before sending an open frame.
- Do not automatically retry an open after an ambiguous result.
- Retry only the idempotent close operation.
- Keep the stock RainPoint path or another verified stop method available.
- Use the RTL-SDR to confirm what was actually transmitted and returned.

### Exit criteria

The end-to-end prototype is complete when:

- The CC1101 waveform matches the captured RainPoint command profile.
- A close request produces a correlated idle acknowledgement.
- A bounded open request produces the expected watering state and duration.
- The watchdog closes the valve when the normal completion path is withheld.
- Loss of the controlling client initiates close behavior.
- rainpointd returns to a confirmed idle state after every success or failure.
- Results are repeatable across an agreed controlled test matrix.
- No cloud data is required to determine the final valve state.

Completing these criteria proves a prototype. It does not by itself authorize
general-purpose or unattended production valve control.

## Deferred work: integration-ready architecture

Resume this backlog after the transmit-prototype exit criteria are satisfied.

### Protocol package

- Extract a pure Python RF protocol package.
- Remove Home Assistant, HTTP, SQLite, SDR, and ESP32 dependencies from the
  protocol layer.
- Keep decoding, model identifiers, frame construction, integrity handling,
  and pairing primitives transport-neutral.

### Canonical provider contract

- Define typed physical-device identities and transport aliases.
- Define timestamped observations and normalized capabilities.
- Distinguish cloud/hub RSSI in dBm from receiver-relative SDR measurements.
- Define provider capabilities for receive, control, pair, and unpair.
- Define command acknowledgements and ambiguous-control failures.

### Device authority and migration

- Assign each physical device one state/control authority: cloud or local.
- Use only authoritative observations to populate Home Assistant state.
- Retain non-authoritative cloud observations only for verification.
- Associate a cloud connection with a custom local RF gateway during migration.
- Allow unsupported local models to remain cloud-authoritative.
- Preserve existing HA devices, entities, history, and user customization.

### Registry ownership

- Store RF identity, association state, counters, and pairing material in the
  custom local RF gateway.
- Store names, areas, entity configuration, and transport authority in Home
  Assistant.
- Replace house-specific endpoint mappings with a one-time registry migration.
- Support registry export and restoration for custom local RF gateway
  replacement.

### Existing integration adoption

- Keep the existing HomGar/RainPoint entity and capability layer where
  practical.
- Add the custom local RF gateway as a local provider rather than creating a
  competing permanent entity model.
- Add migration verification without merging cloud and local state.
- Agree with the existing integration developers on field names, identity,
  unique-ID migration, and provider API versioning before freezing them.

### Generalization and release preparation

- Move house dashboards and automation examples outside the integration core.
- Replace household endpoint assumptions with arbitrary synthetic fixtures.
- Test multiple RainPoint stock gateways, custom local RF gateways, valves,
  sensors, unsupported models, and duplicate names.
- Document fresh local setup, cloud-to-local migration, mixed device authority,
  recovery, and removal of cloud credentials.

## Work to avoid before the prototype gate

- Do not build pairing or registry UI around the current temporary model.
- Do not freeze RF endpoints into public Home Assistant unique IDs.
- Do not add further house-specific endpoint behavior to the protocol core.
- Do not implement permanent cloud/local state fusion.
- Do not remove the current known-good receive deployment while it remains the
  reference for transmit validation.
