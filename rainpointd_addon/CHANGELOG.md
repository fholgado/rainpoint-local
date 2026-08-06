# Changelog

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
