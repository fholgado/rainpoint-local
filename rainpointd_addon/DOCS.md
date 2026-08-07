# RainPoint Local Gateway

This experimental app runs the read-only `rainpointd` API used by the
**RainPoint Local** Home Assistant integration.

## Current behavior

Version 0.3.5 supports captured replay and receive-only USB RTL-SDR modes. It
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

The live defaults are 433,700,000 Hz center frequency and 2,000,000 samples per
second. This window covers both the lower data-rich sensor channel near
433.08 MHz and the previously observed RainPoint traffic above 434 MHz.

### Broad capture duration

Set `research_capture_minutes` to a nonzero value to save every detected raw RF
signal for that many minutes while the normal RainPoint event decoder and API
remain active. The app then returns automatically to ordinary live decoding.
Raw I/Q files are written beneath `/share/rainpoint-captures`; they may include
unrelated nearby 433 MHz transmissions and must remain local. Reset the option
to `0` after starting a one-time capture so a future app restart does not begin
another capture.

## Home Assistant integration

The app exposes its read-only API on TCP port 8787. Configure the
**RainPoint Local** integration with:

- Host: the IP address of the Home Assistant host
- Port: `8787`

Replay mode creates simulated entities. Live mode currently creates confirmed
HCS026FRF soil-moisture entities and a receive-only HTV145 valve device with
confirmed watering state, requested duration, and last-session water usage.
Valid RainPoint frames that do not match the confirmed layouts are retained as
`rf_frame` records in `/api/v1/events` for endpoint discovery; other RF fields
remain research work.

In live RTL-SDR mode, normalized events and decoded device state are persisted
to `/data/rainpointd.sqlite3`, which survives app rebuilds and restarts. The
read-only `/api/v1/endpoints` endpoint summarizes every observed RF endpoint,
including first/last seen time, packet count, address-field roles, latest
message byte, signal level, and frame.

## Safety

This release has no RF transmitter, cloud transport, valve entity, or control
API. USB access is used only by `rtl_433` for receiving. Share access is used
only for explicitly enabled raw captures, and the app cannot operate the
physical valve.
