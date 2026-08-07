# Changelog

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
