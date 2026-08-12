# Changelog

## 0.18.1

- Report explicit family-level device kind and exact-model confidence after a
  legacy registry row migrates to provisional identity metadata.

## 0.18.0

- Centralize RainPoint product codes, model codes, device kinds, and protocol
  families in an evidence-based product identity catalog.
- Register newly paired sensors provisionally as HCS02x-compatible instead of
  asserting an exact retail model from frame shape alone.
- Promote and persist `HCS026FRF` only after a validated RF product-code or
  model-code observation, while rejecting contradictory identifiers.
- Persist protocol, model-source, product-code, and model-code provenance in
  additive storage schema version 5.
- Reclassify exact HCS026 names written by older hardcoded pairing releases as
  provisional during migration unless retained RF evidence confirms them.
- Advertise lifecycle capabilities independently of retail model labels so
  provisional devices can be managed safely from Home Assistant.
- Include product-identity provenance in Home Assistant report diagnostics.

## 0.17.1

- Expose a newly named HCS026 sensor immediately after pairing even when its
  final telemetry arrived while a prior forget suppression was still active.
- Restore registered sensors as unavailable placeholders after gateway restart
  until their next accepted RF report populates live entities.

## 0.17.0

- Add model-level `hcs026_auto_v1` pairing orchestration: the selected radio
  node adopts the first strict HCS026 factory announcement and derives its
  paired identity without the user or Home Assistant supplying an RF ID.
- Replace public identity-specific profile selection with one automatic HCS026
  workflow while retaining captured profiles as offline regression evidence.
- Use the common four-reply first-enrollment branch and shared selector 4;
  physical validation of automatic adoption remains required before release.

## 0.16.4

- Add the physically validated four-reply Sensor A pairing profile while
  retaining endpoint and firmware-target boundaries.
- Accept both observed HCS026 short-message pairing subtypes and require the
  terminal message before completing enrollment.
- Make sensor removal idempotent and move it to the Home Assistant device menu.
- Correct RF trial isolation analysis so installed valve traffic is not
  misidentified as stock RainPoint gateway traffic.

## 0.16.2

- Decode the controlled marker-relative HCS026 battery flag across both known
  moisture-report layouts so all locally received sensors expose categorical
  normal/low battery status.
- Require a validated ordinary trailer before battery state can update, while
  continuing to retain moisture from corrupt reports only as rejected evidence.

## 0.16.1

- Add an authenticated local-forget operation for any currently known HCS026
  sensor, including automatically discovered paired sensors without a registry
  row.
- Remove enrollment state and suppress automatic rediscovery atomically while
  explicitly transmitting no RF unpair or reset command.

## 0.16.0

- Replace Sensor-B-specific pairing orchestration with an evidence-labelled
  protocol-profile registry shared by the gateway and firmware.
- Support arbitrary installation catalogs from JSON while retaining the old
  prototype catalog only as an explicit identity-compatibility fallback.
- Add gateway-managed adoption sessions: temporary per-node credentials are
  issued through the authenticated API, remain absent from public status, can
  be cancelled, and persist only after the node's first successful mutual-
  authentication handshake.
- Support the firmware 0.6 captive-portal, zeroconf, physical-confirmation, and
  zero-copy Home Assistant adoption contract.

## 0.15.0

- Add a bounded, authenticated Identify command that can blink a capable
  custom local radio node without enabling or configuring its RF transmitter.
- Accept the optional protocol-v2 `identify` capability while preserving
  compatibility with firmware 0.5 nodes.
- Expose node identification through the authenticated management API for the
  Home Assistant device button and future discovery/adoption flow.

## 0.14.0

- Migrate legacy node-option credentials into a private persistent radio-node
  registry without overwriting later managed credentials or metadata.
- Keep registered nodes visible while offline and accept authenticated node
  registration through the management API.
- Validate node health heartbeats for Wi-Fi, memory, temperature, uptime,
  network, loop-latency, reset, and reconnect diagnostics.

## 0.13.0

- Assign a stable identity to the local SDR and every serial or Wi-Fi receiver.
- Deduplicate the same air transmission across receivers before it can inflate
  logical device report counts or Home Assistant activity.
- Persist per-receiver and per-device frame, integrity, duplicate, and RSSI
  coverage metrics and expose them at `/api/v1/receivers`.

## 0.12.0

- Version the SQLite schema and migrate existing databases transactionally.
- Persist the latest accepted observation for every device independently of the
  event journal.
- Bound retained event history without discarding device state, endpoint
  inventory, lifetime reporting metrics, registry records, or enrollments.

## 0.11.0

- Store HCS026 physical enrollment mappings in the gateway SQLite database.
- Migrate the legacy pairing JSON once, reject conflicting state, and archive
  the imported file with a `.migrated` suffix.
- Make registry forget remove the enrollment mapping and add persistent
  rediscovery suppression in the same SQLite transaction.

## 0.10.0

- Separate installation identities and transport-neutral RF ingestion from the
  RTL-SDR process adapter.
- Make accepted HCS026 registry metadata drive live decoding, names, and areas
  without changing established Home Assistant device IDs.
- Migrate legacy registry rows for known prototype endpoints onto their
  already-exposed stable device identities.
- Persist forgotten endpoint suppression so later RF traffic remains raw
  evidence and cannot recreate a removed device until it is accepted again.

## 0.9.0

- Add a network-only production transport for authenticated Wi-Fi radio nodes.
- Make network mode the default for new app installations instead of synthetic
  replay data.
- Persist gateway identity independently of receiver transport while preserving
  the legacy identity when an existing database is first migrated.
- Migrate a legacy transport-derived Home Assistant config-entry identity when
  Supervisor discovery first publishes the persistent gateway identity.

## 0.8.0

- Generate and persist the gateway management credential inside app data.
- Publish the gateway address and credential through supported Home Assistant
  Supervisor discovery so users never copy it into an ordinary pairing flow.
- Add a side-effect-free authenticated endpoint for standalone-gateway setup.

## 0.7.1

- Make registry forget remove the corresponding local HCS026 enrollment mapping
  while explicitly sending no RF unpair command.

## 0.7.0

- Add backward-compatible, mutually authenticated radio-node protocol v2 with
  one bounded Sensor B pairing command and no valve-command vocabulary.
- Start pairing on an explicitly selected node through the Home Assistant
  Configure flow and require matching node completion plus terminal sensor
  message `03` before registry finalization.
- Decode the validated paired message `05`/`06` telemetry layout, including the
  independently observed 11% report.
- Keep protocol-v1 nodes receive-only and disconnect every active node when the
  gateway shuts down so an armed session fails closed.

## 0.6.6

- Accept explicitly disarmed `pairing_tx_bench` ESP32 firmware while keeping
  valve commands unavailable.
- Surface the node's pairing state, completed reply count, and live armed state
  in `/api/v1/nodes` for physical bench testing.

## 0.6.5

- Add a non-transmitting, capture-derived five-step Sensor B pairing profile.
- Report whether a pairing monitor is waiting, has found an unsupported
  factory identity, needs a transmitter, or observed a paired identity.
- Reject Wi-Fi radio nodes that claim transmit capability or report an armed
  transmitter while the node protocol remains receive-only.

## 0.6.4

- Correct pairing capability after a controlled factory-only test proved that
  physical HCS026 enrollment requires a stock-gateway RF reply.
- Report pairing monitoring separately from transmitter availability.
- Add offline recovery and regression fixtures for the short gateway replies.

## 0.6.3

- Add authenticated, receive-only HCS026 pairing windows and persistent
  factory-to-paired identity mappings.
- Allow a proven pairing result to be named and assigned to an area without
  transmitting an RF enrollment or reset command.
- Report pairing capability and progress through the local v1 API.

## 0.6.2

- Recognize validated HCS026 factory announcements and paired endpoint
  identities from two controlled enrollment captures.
- Discover new HCS026 sensors from the strict paired telemetry layout instead
  of requiring an installation-specific endpoint allowlist.
- Decode the controlled HCS026 full/low battery flag at frame byte 17, bit
  `0x04`, for that paired report layout.
- Preserve factory and paired identities in device state and restore dynamic
  sensors from persistent observations after app restarts.

## 0.6.1

- Retain trailer-invalid frames for research without allowing them to update
  Home Assistant device state.
- Track valid/invalid RF frame totals and reception-success percentage per
  device for antenna-placement diagnostics.
- Advance valve report freshness from valid routine frames on its established
  endpoint link without changing the last decoded valve state.
- Rebuild endpoint discovery from trailer-valid history so one-off corrupted
  addresses no longer appear as candidate devices.

## 0.6.0

- Accept telemetry from multiple outbound Wi-Fi ESP32/CC1101 connections while
  retaining the existing RTL-SDR or replay backend.
- Authenticate every node with a unique nonce/HMAC enrollment credential; the
  credential itself is never sent over the network.
- Attach authenticated node provenance to decoded RF state and expose
  connection diagnostics at `/api/v1/nodes`.
- Deduplicate the same frame heard by different nodes within 250 ms without
  suppressing ordinary retransmissions heard by one node.
- Keep the network surface receive-only; command and transmit messages are not
  implemented.

## 0.5.0

- Add a persistent local registry for accepting, naming, assigning, and
  forgetting endpoints already observed by the receive-only gateway.
- Add timed learning sessions that highlight endpoints first observed during
  the window without transmitting pairing traffic.
- Protect every registry mutation with an optional bearer token; writes remain
  disabled when no token is configured.
- State explicitly in every mutation response that local acceptance/forgetting
  does not pair or unpair a physical RF device.

## 0.4.3

- Persist per-device report counts, average intervals, and longest observed
  gaps, including a one-time backfill from existing event history.
- Publish model-specific reporting freshness using observed production cadence:
  15 minutes for HCS026 moisture sensors and 6 hours for the HTV145 valve.
- Correct the Home Assistant signal entity to use the receiver's `rf_rssi_db`
  field and expose reporting-health diagnostics.

## 0.4.2

- Preserve the ESP32 radio name, channel, and CC1101 LQI alongside normalized
  receive events.
- Surface bridge radio initialization errors through gateway health instead of
  silently ignoring diagnostic messages.

## 0.4.1

- Decode the repeated compact `88 VV e0 RR` moisture/RSSI form even when its
  preceding slot byte is not field code 10.
- Keep the compact values unassigned until their changing route fields can be
  mapped safely to a stable sensor identity.
- Add offline event-corpus analysis for trailer selectors and status timing.

## 0.4.0

- Add a receive-only USB serial transport for the ESP32/CC1101 bridge.
- Reuse the established RF decoder and device publisher so ESP32 and RTL-SDR
  frames create identical local state.
- Validate frame length and sync locally before accepting bridge input.

## 0.3.6

- Retain the provisional HCS026 heartbeat battery status for controlled
  transition analysis without exposing it as a supported battery entity.
- Calculate and retain the ordinary-frame CRC-CCITT residual and validation
  result using the two residues established from the capture corpus.

## 0.3.5

- Decode the HCS026 product-code/TLV moisture report and canonicalize it to the
  sensor's established endpoint.
- Retain compact moisture and stock-hub RSSI fields from unassigned status
  frames for further routing analysis without creating phantom devices.
- Add regression fixtures for both newly correlated packet layouts.

## 0.3.2

- Expand the default receive window to cover both observed RainPoint channels.
- Decode the alternate HCS026FRF moisture-field position used by lower-channel
  reports.
- Map the confirmed Left Bed, Front Yard Sensor 1, and newly identified Front
  Yard Sensor 2 RF endpoints.
- Restrict moisture decoding to confirmed sensor endpoints so valve payloads
  cannot create false sensor observations.

## 0.3.1

- Add a bounded receive-only broad-capture phase for decoder research.
- Keep the API and persistent event decoder active while saving raw detected
  signals.
- Automatically return to normal live decoding when the configured capture
  duration ends.
- Store raw captures under `/share/rainpoint-captures` for local analysis.

## 0.3.0

- Persist live normalized RF events in SQLite under the app data volume.
- Restore decoded device state after app restarts.
- Add an endpoint inventory with first/last seen times, role counts, message
  type, signal level, and most recent frame.
- Expose the inventory at the read-only `/api/v1/endpoints` endpoint.

## 0.2.1

- Retain normalized non-moisture RainPoint RF frames in the event stream for
  endpoint discovery and valve-traffic correlation.
- Keep raw-frame discovery receive-only and separate from Home Assistant device
  state.

## 0.2.0

- Add a receive-only `rtl_433` transport for USB RTL-SDR receivers.
- Decode confirmed HCS026FRF soil-moisture reports locally.
- Map raw USB into the protected app without privileged or full host access.
- Retain replay mode as the upgrade-safe default.

## 0.1.0

- Package the replay-backed `rainpointd` service as a Home Assistant app.
- Expose the read-only API on TCP port 8787.
- Add Supervisor health monitoring.
- Support `aarch64` and `amd64`.
## 0.3.3

- Ignore obsolete auto-discovered HCS026 devices whose RF endpoint is not a
  confirmed moisture sensor, preventing valve responses from returning as
  phantom sensors after a restart.
- Keep existing Home Assistant entities safely unavailable when a gateway
  device is reclassified and removed from discovery.
## 0.3.4

- Decode confirmed HTV145 open/close state and requested duration from local RF.
- Decode packed last-session water usage, including values larger than 25.5 L.
- Register the live Garden Valve device so duration, watering state, and last
  usage can populate in Home Assistant without the RainPoint cloud.
