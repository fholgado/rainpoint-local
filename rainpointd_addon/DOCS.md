# RainPoint Local Gateway

This experimental app runs the read-only `rainpointd` API used by the
**RainPoint Local** Home Assistant integration.

## Current behavior

Version 0.2.0 supports captured replay and receive-only USB RTL-SDR modes. It
does not connect to the RainPoint cloud, and every HTTP POST request is
rejected.

Installing this app does not make the physical irrigation system work offline.
Replay remains the default after upgrade. Select `rtl433` only after attaching
a supported RTL-SDR receiver to the Home Assistant host.

## Configuration

### Replay interval

Number of seconds between fixture observations. The default is 5 seconds.

### Transport

- `replay`: captured development fixtures; does not use USB hardware.
- `rtl433`: live receive-only RainPoint packets from the USB RTL-SDR.

The live defaults are 434,000,000 Hz center frequency and 1,024,000 samples per
second. These settings cover the locally observed RainPoint carriers.

## Home Assistant integration

The app exposes its read-only API on TCP port 8787. Configure the
**RainPoint Local** integration with:

- Host: the IP address of the Home Assistant host
- Port: `8787`

Replay mode creates simulated entities. Live mode currently creates confirmed
HCS026FRF soil-moisture entities. Valid RainPoint frames that do not match the
confirmed moisture layout are retained as `rf_frame` records in `/api/v1/events`
for endpoint discovery; other RF fields remain research work.

In live RTL-SDR mode, normalized events and decoded device state are persisted
to `/data/rainpointd.sqlite3`, which survives app rebuilds and restarts. The
read-only `/api/v1/endpoints` endpoint summarizes every observed RF endpoint,
including first/last seen time, packet count, address-field roles, latest
message byte, signal level, and frame.

## Safety

This release has no RF transmitter, cloud transport, valve entity, or control
API. USB access is used only by `rtl_433` for receiving, and the app cannot
operate the physical valve.
