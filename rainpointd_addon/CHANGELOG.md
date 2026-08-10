# Changelog

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
