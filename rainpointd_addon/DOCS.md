# RainPoint Local Gateway

This experimental app runs the local `rainpointd` API used by the
**RainPoint Local** Home Assistant integration.

## Current behavior

Version 0.16.0 supports authenticated network radio nodes, captured replay,
receive-only USB RTL-SDR,
receive-only ESP32/CC1101 serial mode, and authenticated inbound telemetry from
one or more Wi-Fi ESP32 nodes. It does not connect to the RainPoint
cloud. A protocol-v2 node can perform the one physically validated, bounded
HCS026 profile `hcs026_15a98024_v1`. Valve-control POST requests remain
rejected.

Accepted HCS026 endpoints now provide the live decoder identity, friendly name,
and area. Known endpoints retain their established Home Assistant device IDs
during migration. Forgetting a registered sensor persistently suppresses its
automatic rediscovery; accepting or pairing that endpoint again restores it.
Physical HCS026 enrollment mappings are stored in the same SQLite database as
the registry and removal policy. Existing pairing JSON is validated, imported
once, and retained with a `.migrated` suffix for rollback inspection.

Installing this app does not make the physical irrigation system work offline.
New installations default to `network` mode. Select `rtl433` only after
attaching a supported RTL-SDR receiver to the Home Assistant host; select
`replay` only for explicit development work.

## Configuration

### Replay interval

Number of seconds between fixture observations. The default is 5 seconds.

### Transport

- `network`: production mode for one or more authenticated Wi-Fi radio nodes;
  no local receiver or synthetic devices.
- `replay`: captured development fixtures; does not use USB hardware.
- `rtl433`: live receive-only RainPoint packets from the USB RTL-SDR.
- `esp32_serial`: normalized RainPoint frames from the receive-only ESP32
  bridge connected by USB.

The live defaults are 433,700,000 Hz center frequency and 2,000,000 samples per
second. This window covers both the lower data-rich sensor channel near
433.08 MHz and the previously observed RainPoint traffic above 434 MHz.

### Installation device catalog

The old prototype installation retains a compatibility catalog so upgrades do
not fork its established Home Assistant device IDs. Other installations can
set `device_catalog_path` to a JSON file available inside the app, such as a
file beneath `/share`. The schema is demonstrated by
`examples/device-catalog.example.json` and supports arbitrary sensor endpoints,
valve endpoint pairs, stable device IDs, names, models, and pairing peers.

This file is an interim valve-identity boundary. Newly paired sensors are
already persisted in the managed registry. Valve links will move into that
registry through a versioned migration before the legacy compatibility catalog
is removed.

For `esp32_serial`, set `serial_device` to the ESP32 USB serial path and leave
`serial_baud` at `115200`. The stable `/dev/serial/by-id/...` path is preferable
when the host exposes one; `/dev/ttyUSB0` is the portable default. The gateway
revalidates every frame instead of trusting the bridge's diagnostic fields.

### Wi-Fi radio nodes

The Wi-Fi node listener is the only receiver in `network` mode and supplements
the local receiver in `rtl433` or `esp32_serial` mode. This lets the existing
RTL-SDR remain a reference receiver while one or more ESP32 nodes send the same
normalized frames over TCP port 8790. Frames carry their authenticated node ID,
and a packet heard by two different nodes within 250 ms is stored once.
Repeated packets from the same node are preserved.

Every receiver now has a stable source identity. The local USB SDR is
`local-sdr`; Wi-Fi receivers use their authenticated node ID. If two different
receivers hear the same frame within 250 ms, the gateway retains coverage for
both while publishing only one logical device report. Persistent per-receiver
and per-device counts, integrity decisions, duplicates, RSSI averages, and last
reception times are available from `/api/v1/receivers`.

Existing `node_tokens` entries are imported once into the private persistent
radio-node registry. New provisioned nodes can be registered from Home
Assistant with one independent 64-hex-character setup token per stable node ID.
The legacy option remains a migration fallback and does not overwrite a token,
name, or area subsequently managed through Home Assistant:

```json
{"rp-001122334455":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}
```

Leave `node_tokens` empty to reject every connection. Set `node_listen_port` to
`0` to disable the listener, or leave it at `8790`. Never reuse one node's
token for another node and do not post real tokens in issues or logs. Current
node state and receive counters are available from the read-only
`/api/v1/nodes` endpoint.

Firmware 0.5 adds a bounded 30-second diagnostic heartbeat with uptime, reset
reason, heap pressure, internal temperature, maximum loop gap, Wi-Fi address
and signal, reconnect/authentication counters, and network byte counters. The
integration exposes supported fields beneath the custom local radio-node HA
device. Firmware remains USB-flashed; OTA updates are not implemented.

This configuration is intended for trusted-LAN hardware testing. Protocol v2
uses separate nonce/HMAC proofs to authenticate both the node and gateway
before accepting a command. Protocol-v1 nodes remain receive-only. Protocol-v2
firmware advertises `rx`, `sensor_pairing_tx`, and, beginning with firmware
0.6, the non-RF `identify` capability; no generic or valve TX capability
exists. The app sends a
time-limited pairing command only after an authenticated Home Assistant request
selects that node. Its state, command ID, completed reply count, and armed state
appear in `/api/v1/nodes`.

### Broad capture duration

Set `research_capture_minutes` to a nonzero value to save every detected raw RF
signal for that many minutes while the normal RainPoint event decoder and API
remain active. The app then returns automatically to ordinary live decoding.
Raw I/Q files are written beneath `/share/rainpoint-captures`; they may include
unrelated nearby 433 MHz transmissions and must remain local. Reset the option
to `0` after starting a one-time capture so a future app restart does not begin
another capture.

### Event retention

`event_retention_limit` bounds the raw SQLite event journal and defaults to
100,000 events. Latest accepted device state, endpoint inventory, lifetime
report and reception metrics, registry records, suppressions, and physical
enrollments are stored separately and survive journal pruning. The gateway API
reports the active limit and oldest retained event ID for cursor consumers.

### Gateway authorization

The app generates a persistent management credential in its private data and
passes it to the RainPoint Local integration through supported Supervisor
discovery. Users do not copy or paste this credential during sensor pairing.
The legacy `registry_write_token` option is retained temporarily as an advanced
migration override; leave it empty for normal managed setup. Standalone
gateways can still be authenticated once from the integration's Configure flow.
Telemetry and registry reads remain available without authentication on the
local API during this prototype phase.

The registry separates three concepts deliberately:

- `/api/v1/endpoints` is the automatically observed RF inventory.
- A timed `/api/v1/learning` session highlights endpoints that appear after
  the session starts.
- `/api/v1/registry` contains endpoints explicitly accepted into local
  metadata, with user-defined names, models, and areas.

Accepting or forgetting an ordinary registry record is not physical pairing or
unpairing. The separate authenticated `/api/v1/pairing` workflow can select a
protocol-v2 radio node and arm the validated HCS026 protocol profile. The original
RainPoint gateway must be powered off during this exchange because it was
observed sending a competing reply even after the sensor was removed from the
vendor app. The workflow requires the selected node's matching command ID and
terminal sensor message `03` before Home Assistant may name the device.

Only profile `hcs026_15a98024_v1` (factory identity `15a98024`, paired identity
`95a98024`) is currently supported for physical TX. Users are not asked to
identify RF endpoints; the integration selects the profile internally. The
command applies the capture-derived 240-second
pairing clock lead, 45 kHz radio correction, 10 dBm power, three replies, and a
strict timeout. Additional sensors require evidence-backed profiles rather
than guessing these fields. A second identity must be physically validated
before the implementation can claim model-wide enrollment support.

## Home Assistant integration

The app exposes its local device and pairing API on TCP port 8787. Configure the
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

This release has no cloud transport, valve control entity, valve command API,
or valve frame in its network vocabulary. Its sole RF mutation is the
evidence-backed, time-limited `hcs026_15a98024_v1` enrollment profile on a
user-selected authenticated node.
It starts disarmed, cancels on coordinator loss, and requires terminal RF
confirmation. USB access is used only by `rtl_433` for receiving. Share access
is used only for explicitly enabled raw captures.
