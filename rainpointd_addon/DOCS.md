# RainPoint Local Gateway

This experimental app runs the read-only `rainpointd` API used by the
**RainPoint Local** Home Assistant integration.

## Current behavior

Version 0.6.6 supports captured replay, receive-only USB RTL-SDR,
receive-only ESP32/CC1101 serial mode, and authenticated inbound telemetry from
one or more Wi-Fi ESP32 nodes. It does not connect to the RainPoint
cloud. Valve-control POST requests remain rejected. Token-protected registry
requests change local names and discovery metadata only; they never transmit.

Installing this app does not make the physical irrigation system work offline.
Replay remains the default after upgrade. Select `rtl433` only after attaching
a supported RTL-SDR receiver to the Home Assistant host.

## Configuration

### Replay interval

Number of seconds between fixture observations. The default is 5 seconds.

### Transport

- `replay`: captured development fixtures; does not use USB hardware.
- `rtl433`: live receive-only RainPoint packets from the USB RTL-SDR.
- `esp32_serial`: normalized RainPoint frames from the receive-only ESP32
  bridge connected by USB.

The live defaults are 433,700,000 Hz center frequency and 2,000,000 samples per
second. This window covers both the lower data-rich sensor channel near
433.08 MHz and the previously observed RainPoint traffic above 434 MHz.

For `esp32_serial`, set `serial_device` to the ESP32 USB serial path and leave
`serial_baud` at `115200`. The stable `/dev/serial/by-id/...` path is preferable
when the host exposes one; `/dev/ttyUSB0` is the portable default. The gateway
revalidates every frame instead of trusting the bridge's diagnostic fields.

### Wi-Fi radio nodes

The Wi-Fi node listener is a sidecar to the selected transport. This means the
existing RTL-SDR can remain the primary reference receiver while one or more
ESP32 nodes send the same normalized frames over TCP port 8790. Frames carry
their authenticated node ID, and a packet heard by two different nodes within
250 ms is stored once. Repeated packets from the same node are preserved.

Set `node_tokens` to a JSON object containing one independent 64-hex-character
token per stable node ID:

```json
{"rp-001122334455":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}
```

Leave `node_tokens` empty to reject every connection. Set `node_listen_port` to
`0` to disable the listener, or leave it at `8790`. Never reuse one node's
token for another node and do not post real tokens in issues or logs. Current
node state and receive counters are available from the read-only
`/api/v1/nodes` endpoint.

This configuration is intended for trusted-LAN hardware testing. It proves
node authentication but does not yet encrypt or sign every telemetry record.
Network valve commands remain unavailable.

Firmware advertising `pairing_tx_bench` may connect only while disarmed. Its
reported pairing state, completed reply count, detail, and current armed state
appear in `/api/v1/nodes`. The app does not send pairing or valve commands;
the first physical pairing test is armed explicitly through the ESP32 serial
console.

### Broad capture duration

Set `research_capture_minutes` to a nonzero value to save every detected raw RF
signal for that many minutes while the normal RainPoint event decoder and API
remain active. The app then returns automatically to ordinary live decoding.
Raw I/Q files are written beneath `/share/rainpoint-captures`; they may include
unrelated nearby 433 MHz transmissions and must remain local. Reset the option
to `0` after starting a one-time capture so a future app restart does not begin
another capture.

### Registry write token

Leave `registry_write_token` empty to disable every registry mutation. To use
the experimental local registry, configure a long random token and send it as
`Authorization: Bearer <token>` to the registry endpoints. Telemetry and
registry reads remain available without a token on the local API.

The registry separates three concepts deliberately:

- `/api/v1/endpoints` is the automatically observed RF inventory.
- A timed `/api/v1/learning` session highlights endpoints that appear after
  the session starts.
- `/api/v1/registry` contains endpoints explicitly accepted into local
  metadata, with user-defined names, models, and areas.

Accepting or forgetting a registry record is not physical pairing or
unpairing. The separate authenticated `/api/v1/pairing` workflow discovers an
HCS026 factory identity and monitors the factory-to-paired transition. The live
RTL-SDR receiver cannot complete physical pairing: controlled testing proved
that the stock RainPoint gateway sends a short response on a second channel.
Until a transmitter is connected, Home Assistant labels this workflow as
**Discover a sensor for pairing** rather than claiming the sensor is paired.

For Test Sensor B only, the service can expose a dry-run reply profile derived
from the controlled stock-gateway capture. It describes the five frames,
frequencies, wake length, trigger order, and conservative response deadline.
It never dispatches a frame, and every connected ESP32 node is still required
to identify as receive-only.

## Home Assistant integration

The app exposes its receive-only device API on TCP port 8787. Configure the
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

`/api/v1/devices` also includes persistent report count, average report
interval, longest observed gap, and model-specific reporting freshness. The
current measured timeout is 15 minutes for HCS026 sensors and 6 hours for the
HTV145 valve.

Device snapshots also expose valid and rejected RF-frame counts plus an RF
reception-success percentage. Ordinary moisture reports with an invalid
trailer remain available in `/api/v1/events` for research but cannot update
Home Assistant state or create endpoint-discovery candidates. Confirmed
product-code reports and structurally decoded valve transactions are retained
as accepted protocol families while their distinct trailer behavior remains
under study. Valid routine traffic on the established valve endpoint pair
advances its report time without overwriting the last decoded watering state.

Validated HCS026 factory and paired report layouts also expose the factory and
paired RF identities. A newly paired sensor using this layout is discovered
without an installation-specific endpoint allowlist. Its categorical battery
field reports `100%` for normal and `10%` for low, matching the stock app's
semantics. Older companion-heartbeat battery fields remain research metadata.

## Safety

This release issues no RF transmission and has no cloud transport, valve
control entity, or control API. It may display status reported by explicitly
disarmed Sensor B pairing-bench firmware, but cannot arm it. The optional POST
surface can only mutate its own SQLite registry. USB access is used only by
`rtl_433` for receiving. Share access is used only for explicitly enabled raw
captures, and the app cannot operate the physical valve.
