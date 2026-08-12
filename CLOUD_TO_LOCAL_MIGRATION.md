# Cloud-to-local migration design

## Product outcome

An existing RainPoint/HomGar Home Assistant user should be able to attach a
custom local RF gateway and migrate supported devices without recreating Home
Assistant devices, entities, history, dashboards, automations, names, areas, or
customizations.

Migration belongs in the existing RainPoint/HomGar integration. The custom
local gateway is a second provider for the same physical-device model, not a
second permanent integration competing for ownership of the devices.

## Readiness gates

Active migration must not ship until all of these are physically proven:

1. Model-wide sensor pairing across at least two identities.
2. Repeatable test-valve association without the vendor app.
3. Close-first valve control with returned-state acknowledgement.
4. Bounded open, node-local watchdog, client-loss recovery, and repeated close.
5. Stable local identity and registry restoration across gateway, node, HA, and
   device restarts.
6. A documented recovery path for every destructive association transition.

Provider and identity design can be reviewed with the existing integration
developers before these gates pass. The user-facing handoff remains disabled.

## Authority model

Every physical device has exactly one authoritative provider at a time:

| Authority | HA state | HA commands | Other provider |
| --- | --- | --- | --- |
| Cloud | Cloud | Cloud | Local may observe for matching only |
| Local | Local | Local | Cloud may poll for verification only |
| Cloud fallback | Cloud | Cloud | Used for a model not supported locally |

Cloud and local observations are never merged by last-write-wins. Once a
device becomes local-authoritative, cloud data must not update its HA state,
availability, activity, or command result. It may be retained in diagnostics
as a timestamped verification observation.

A single integration entry may therefore contain a mixed installation: locally
supported devices use the custom local gateway, while unsupported models remain
cloud-authoritative. “Mixed” describes per-device authority, not two providers
simultaneously controlling one device.

## Provider contract

The existing integration should place its entity/capability layer above a
provider interface with at least:

- provider identity and version;
- supported models and capabilities;
- device inventory and transport aliases;
- timestamped observations with evidence/source metadata;
- pair, rejoin, forget, and control capabilities;
- command acknowledgement, ambiguity, timeout, and safety-fault results;
- diagnostics and availability independent of device availability.

Cloud and local implementations return the same canonical physical-device
records. Home Assistant entities consume canonical records rather than cloud
API dictionaries or `rainpointd` dictionaries directly.

## Identity contract

The existing cloud integration's device and entity unique IDs are the migration
anchor. A provider switch must not change them.

Each canonical device record should contain:

- immutable HA integration device key;
- model/product identifier;
- cloud aliases such as vendor device ID, hub ID, and serial number when known;
- local aliases such as paired RF endpoint and association/controller identity;
- confidence and evidence for every alias link;
- current authoritative provider;
- supported capabilities under each provider.

An RF endpoint alone must not become the public HA unique ID. It can change
during association and may not be visible to the cloud API. The integration
must maintain an alias mapping from the established cloud identity to the
validated local identity.

## Migration workflow

### 1. Preflight

The migration wizard:

1. Selects an existing cloud connection.
2. Selects or commissions one custom local RF gateway.
3. Captures a versioned cloud inventory snapshot.
4. Reads local gateway capabilities, nodes, supported protocol profiles, and
   receiver health.
5. Classifies devices as locally supported, cloud-only, ambiguous, or offline.
6. Makes no association or authority changes.

The user sees exactly which devices can migrate and which will remain cloud.

### 2. Identity verification

The wizard must prove each cloud-to-local alias before changing authority.
Suitable non-destructive evidence includes:

- sensor button report correlated by time and moisture value;
- deliberate sensor moisture change correlated in both providers;
- valve close/idle exchange on an already-associated testable device;
- product/model metadata and a unique association sequence.

A valve must never be identified by sending open. Name, room, order, or signal
strength alone is insufficient. Ambiguous matches require user action and
remain cloud-authoritative.

### 3. Association transfer

For devices that require physical re-pairing:

1. Record the cloud identity and current HA registry links.
2. Explain whether rollback will require re-pairing to the stock RainPoint
   gateway.
3. Quiesce cloud commands and automations for that device.
4. Ask the user to power off the stock RainPoint gateway when it could race the
   custom local gateway.
5. Perform the validated local pair/rejoin flow through one selected radio
   node.
6. Require terminal RF evidence and ordinary post-pair telemetry.
7. Persist the local alias while authority is still cloud/frozen.

Removing a device from the vendor app and factory-resetting it are explicit
physical steps. The integration must never imply that local “forget” performs
either operation when no RF unpair command exists.

### 4. Atomic authority handoff

After validation, one transaction:

1. Persists the cloud-to-local identity alias.
2. Migrates the existing HA device/entity registry records if necessary.
3. Selects local state and control authority.
4. Rebinds coordinator/entity data to the local provider.
5. Preserves unique IDs, names, areas, disabled state, history, and references.
6. Records an audit event and the rollback conditions.

If any registry or provider step fails, authority remains cloud/frozen. The
system must not expose duplicate devices or an entity with uncertain control
authority.

### 5. Verification period

For a configurable period, cloud polling may continue without populating HA
state. Diagnostics compare:

- observation timestamps and freshness;
- moisture, battery, valve state, duration, and usage where both exist;
- local command acknowledgement versus later cloud observation;
- missing fields and model capabilities.

Differences produce diagnostics, not last-write-wins state fusion. Users may
disable or remove cloud credentials after confidence is established.

## Rollback

Two rollback classes must be shown distinctly:

- **Provider-only rollback:** the physical device remains associated with the
  stock RainPoint gateway, so authority can return to cloud without touching
  RF association.
- **Association rollback:** the device was re-paired to the custom local
  gateway, so returning to cloud requires the stock gateway/app pairing
  procedure. This cannot be advertised as one-click rollback.

On local gateway or node failure, a locally authoritative valve fails closed.
The integration must not automatically send the same command through cloud,
because the local result may be ambiguous. Restoring cloud authority is an
explicit repair operation after physical state is known.

## Home Assistant migration mechanics

The upstream implementation needs tests for:

- config-entry version migration;
- entity unique-ID migration without recorder-history loss;
- device-registry identifier and connection updates;
- user-disabled and integration-disabled entity preservation;
- names, areas, icons, dashboards, automations, scripts, and scenes;
- partial/mixed device authority;
- reload, restart, credential removal, and provider failure;
- rollback before and after RF association transfer;
- no duplicate entities during discovery or reassociation.

Migration state should be journaled as a resumable state machine rather than a
single config-flow callback. Home Assistant restart, browser closure, or node
disconnect must leave the last committed authority intact.

## Coordination with existing integration developers

### Decide now

These decisions do not depend on unfinished RF work:

- canonical device and capability model;
- provider interface and authority semantics;
- existing unique IDs that must be preserved;
- cloud identity fields available for alias matching;
- config-entry relationship between cloud connection and local gateway;
- diagnostics vocabulary and API version negotiation;
- ownership boundaries between integration, `rainpointd`, and radio nodes.

### Decide after sensor and valve pairing proof

- final local pairing capability shape;
- association material and identity aliases for each model;
- recovery and factory-reset UX;
- which models qualify as migration-supported.

### Implement after bounded valve-control proof

- active migration wizard and authority transaction;
- valve entity rebinding and command routing;
- cloud verification comparison;
- rollback/repair flows;
- staged beta migration on a disposable/test installation, then this house.

This sequencing lets upstream architecture work start early without freezing
unproven RF assumptions into the public integration.
