# RainPoint Local architecture

## Data and authority flow

```text
RainPoint sensors and valves
          | 433/434 MHz
ESP32/CC1101 radio nodes     optional receive-only SDR
          | authenticated network frames |
          +---------------+--------------+
                      rainpointd
              protocol, registry, persistence
              ACK/control ownership and safety
                          | local API
              Home Assistant integration
```

The gateway owns associations and command authority. HA requests operations and
renders confirmed state; firmware owns timing-critical RF. The SDR is research
infrastructure and must not be required for production telemetry or control.

## Protocol core

`rainpointd_addon/rainpointd/rf.py`, `pairing_protocol.py`, `valve_protocol.py`,
and `valve_pairing_protocol.py` define frame validation, identity derivation,
field codecs, enrollment, and reply shapes. Captured regression fixtures preserve
byte evidence. Device references under [protocol_documentation/](protocol_documentation/)
describe current rules without reproducing experiment chronology.

Pairing, report, and command counters are separate state machines. Endpoint
positions are protocol roles, not universal source/destination addresses.
Installation identities must come from a catalog or accepted association.

## Gateway service

`rainpointd` owns durable device identity, suppression, metadata, radio credentials,
ACK assignments, control profiles/counters, pending operations, morning schedules,
and event history. Its API is versioned independently of the RF protocol.

Multiple nodes can receive a frame. The gateway deduplicates observations while
retaining receiver provenance. Exactly one assigned owner transmits routine ACKs
or ordinary valve commands for each device. Reassignment revokes the old owner
before a replacement may transmit. Unavailable owners block control; normal opens
never fail over automatically to another radio.

Valve control reserves one logical operation durably before dispatch. The HTV405
coordinator supports supervised HA operation. The HTV145 coordinator remains
behind the explicit dry-qualification gate. They share safety principles but
have distinct response, counter, and synchronization rules.

## Radio firmware

The sole PlatformIO environment is `rainpoint_bridge`, using one CC1101 per node.
The radio scans association channels, receives normalized frames, records RF
health, and executes only authorized bounded operations. Node sessions connect
outbound to the gateway with node-specific credentials.

Pairing and ACK timing run locally. Command bursts contain identical repetitions
of one logical command and stop on a qualified response. The radio enforces
command spacing and bounded waits independently of HA. Receive-only maintenance
blocks all RF transmit paths while retaining diagnostics and reconnect support.

OTA verifies size and SHA-256, confirms a healthy candidate boot, and supports
rollback. Asymmetric signatures and encrypted node sessions remain hardening
gates; do not describe the existing shared-secret session as encrypted.

One extra compile option enables HTV145 qualification on an explicitly selected
dry-test radio. Standard firmware excludes that transmitter. There are no
separate development checkouts or identity-specific PlatformIO environments.

## Home Assistant adapter

The integration maps gateway capabilities to HA devices/entities, runs pairing
and naming flows, submits authenticated actions, and displays their outcomes.
It preserves entity identity across supported migrations and omits unsupported
fields. A canonical valve is one physical HA device with one or four zones.

The adapter does not implement RF timing, guess counters, infer watering from an
outbound command, or substitute cloud values for undecoded local telemetry.
Control availability depends on the owner, association, physical state, and any
active maintenance/command reservation.

## Safety and persistence contract

- Bound run duration and require independently known physical state.
- Accept state/counters only from the relevant qualified response or telemetry.
- Keep one logical operation per valve and preserve its reservation across failure.
- Do not replay an open after gateway/node restart or client loss.
- Never transmit a speculative startup close or close solely for missing telemetry.
- Treat an overdue run as an observable anomaly; preserve uncertainty honestly.
- Keep explicit counter sync distinct from status reads and normal startup.
- Preserve ACK ownership and association identity across ordinary reconnects.

Morning scheduling belongs to the gateway so HA downtime cannot erase its policy.
HA may schedule irrigation, but gateway/radio safety continues independently.
A missed maintenance window is not replayed arbitrarily later.

## Research and release boundaries

Raw captures, copied databases, build output, and installation secrets remain
untracked. Redacted fixtures and reusable analyzers live in the repository.
Cloud investigation stays under `research/cloud` and is not a runtime dependency.

[PROJECT_ROADMAP.md](PROJECT_ROADMAP.md) owns all qualification and hardening
status. [The research index](research/README.md) separates procedures from evidence.
