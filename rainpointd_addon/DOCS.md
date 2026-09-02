# RainPoint Local Gateway

This experimental app runs the local `rainpointd` API used by the
**RainPoint Local** Home Assistant integration.

## Current behavior

Version 0.33.32 supports authenticated network radio nodes, receive-only USB
RTL-SDR, receive-only ESP32/CC1101 serial mode, and authenticated inbound
telemetry from one or more Wi-Fi ESP32 nodes. It does not connect to the
RainPoint cloud. A protocol-v2 node can perform bounded automatic HCS026 pairing through
`hcs026_auto_v1`; automatic identity adoption and known-sensor recovery have
completed physical end-to-end validation across independent identities.
The staged coexistence release persists one custom RF controller identity for
the local gateway and supplies it to every radio node. Existing associations
retain the identity under which they were paired. A node must advertise
`configurable_rf_controller_identity` before it may pair or acknowledge a
custom-identity device; older nodes remain usable for retained stock-identity
associations. Physical custom-identity sensor enrollment is confirmed; sustained
stock/custom cohort coexistence remains a release gate. Completion requires a
terminal sensor frame addressed to the requested controller identity; a known
sensor's retained-association recovery traffic cannot transfer ACK ownership
during a custom-identity attempt.
HTV405 valve-control POST requests remain rejected unless the explicit
`supervised_htv405_control` beta option is enabled and the selected
association-specific radio node advertises its candidate control capability.
Completing HTV405 naming in HA leaves the radio node's bounded association
session running so it can finish every modeled protocol reply. Strict
selector-`0x07` paired-link reports refresh device availability without
overwriting the last definitive zone or watering state.

For HTV405 control, a command remains provisional until the valve supplies the
matching authenticated response. A silent first attempt may repeat the same
counter after the 15-second hardware interval. A strict negative response may
advance to the next counter candidate; two silent attempts require a fresh
independent idle report before any candidate advance. Telemetry report time and
last command-transmission time are stored independently so routine reports do
not delay user commands.

When an independently confirmed-idle HTV405 loses command synchronization,
Home Assistant exposes a configuration action that starts a bounded close-only
search. It sends no duration and cannot construct an open. The deterministic
candidate order is the successor of the last authenticated command, the
observed reset candidates `1`, `2`, and `0`, then every remaining five-bit
value exactly once. One silent candidate is repeated once before advancing;
strict rejection advances immediately, and every logical command observes the
15-second valve interval. The explicitly started search is durable across
gateway and radio-node restarts.

Ordinary control is restored only by a matching authenticated closed response,
whose sequence remains current for the next open. Silence, successful node
dispatch, and ordinary valve telemetry do not establish synchronization. An
unexpected watering report aborts the search and leaves the counter
unsynchronized. Home Assistant shows the current candidate, position, attempt,
and terminal exhaustion state; a fresh strict idle report is required before a
new exhausted search can start.

An independently authenticated operator endpoint can begin a counter-recovery
open, but it is deliberately fixed to Zone 1 for 60 seconds. A supervised
caller may select only one of the first three consecutive candidates. The
candidate remains provisional and ordinary control stays unavailable until the
valve returns the matching authenticated watering response. This endpoint is
also excluded from the end-user HA control surface.

The generalized HCS026 workflow completed isolated local enrollment on both
test sensors and on installed bed sensors using generated replies, terminal
confirmation, and subsequent telemetry. Product-family and hardware-revision
claims remain evidence-bounded.

Accepted HCS026 endpoints now provide the live decoder identity, friendly name,
and area. Known endpoints retain their established Home Assistant device IDs
during migration. Forgetting a registered sensor persistently suppresses its
automatic rediscovery; accepting or pairing that endpoint again restores it.
Physical HCS026 enrollment mappings are stored in the same SQLite database as
the registry and removal policy. Existing pairing JSON is validated, imported
once, and retained with a `.migrated` suffix for rollback inspection.
Observation-only valves and durable HTV405 associations expose the same
authenticated, local-only forget operation. Legacy trailer-invalid HTV405
snapshots are removed from derived device state while their raw events remain
available as protocol evidence.

Exact product names are evidence-based. A newly paired device begins as an
`HCS02x-compatible soil sensor`; RF product code `0x48` confirms the shared
HCS02x soil-sensor capability family, while model code `0x013d` or trusted
migration metadata identifies the exact `HCS026FRF` variant. The registry
retains the protocol family and identification source so lifecycle operations
do not depend on a display-model string.

Installing this app does not make the physical irrigation system work offline.
New installations default to `network` mode. Select `rtl433` only after
attaching a supported RTL-SDR receiver to the Home Assistant host. Replay and
raw-capture tooling remain available through the development CLI, not this app.

## Configuration

### Transport

- `network`: production mode for one or more authenticated Wi-Fi radio nodes;
  no local receiver or synthetic devices.
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

Firmware 0.5 and later add a bounded 30-second diagnostic heartbeat with uptime, reset
reason, heap pressure, internal temperature, maximum loop gap, Wi-Fi address
and signal, reconnect/authentication counters, and network byte counters. The
integration exposes supported fields beneath the custom local radio-node HA
device. The current unified firmware includes receive, generalized sensor
pairing, bounded routine acknowledgements, managed OTA updates, and the bounded
HTV405 enrollment implementation in one source tree. A compatible supervised
build advertises association and control capabilities to the gateway; Home
Assistant exposes them only while the explicit HTV405 beta option is enabled.
The same firmware answers the captured paired-state recovery sequence only for
sensors already assigned to the node as ACK owner.
ACK-owning nodes remain on the validated HCS026 telemetry channel so the
500 ms broad-scan cadence cannot repeatedly alias with a sensor's retry burst.
Known factory identities may enter a bounded automatic rejoin through their
existing assignment; unknown identities still require an explicit HA pairing
window. Automatic rejoin accepts the validated factory retry counters 1, 2,
and 4 so a node armed by the first announcement can answer a later retry.
Known-sensor recovery completes after that reply, immediately restoring normal
receive and acknowledgement service. The authenticated command inbox holds up
to eight commands so every persisted ACK assignment can be restored after a
reconnect or OTA reboot.
After the first OTA-capable image is installed by USB, compatible releases can
be installed from the radio node's Home Assistant firmware Update entity.
An authenticated reconnect atomically replaces a stale session for the same
managed node, so a software reboot or power loss does not require restarting
the custom local gateway.

This configuration is intended for trusted-LAN hardware testing. Protocol v2
uses separate nonce/HMAC proofs to authenticate both the node and gateway
before accepting a command. Protocol-v1 nodes remain receive-only. Protocol-v2
firmware advertises `rx`, `sensor_pairing_tx`, routine-acknowledgement, and the
non-RF `identify` capability. Supervised builds additionally advertise narrowly
scoped HTV405 pairing/control capabilities; there is no generic RF-transmit
API. The app sends a time-limited pairing or valve command only after an
authenticated Home Assistant request selects the assigned node. Its state,
command ID, completed reply count, and armed state appear in `/api/v1/nodes`.

Each protocol-v2 node also exposes authenticated maintenance controls in Home
Assistant. Turning off its **RF transmissions** switch requests a bounded
30-minute receive-only interval; turning it on restores normal mode. A firmware
guard rejects all pairing, acknowledgement, and valve-control transmissions
while reception, Wi-Fi, diagnostics, Identify, and maintenance remain active.
The interval automatically expires, and the node's Reboot button returns it to
normal mode. Requested/effective mode, remaining time, last change, blocked
transmissions, rejected commands, and reboot status are visible on the node
device. `/api/v1/nodes/rf-capture-readiness` declares a stock-gateway capture
ready only when every adopted node is authenticated and effectively
receive-only for the requested minimum time.

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
gateways print a one-time six-digit setup code when started without an existing
management token; enter it once in the integration's Configure flow.
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

Home Assistant loads the gateway's pairing catalog and presents supported
models beneath broad **Sensors** and **Valves** categories. The UI contains no
installation-specific device IDs and filters radio-node choices by the
selected model's required capability. Automatic HTV405 identity discovery has
its own `htv405_auto_identity_pairing` capability, so older firmware that
supports only explicit valve pairing is not offered by this flow.
`hcs026_auto_v1` and
`htv405_auto_candidate_v1` are currently user-pairable; the unaccepted HTV145
transmitter remains hidden behind its research build.

Users are not asked to identify RF endpoints or choose a transcript. For
HCS026, the selected node adopts the first strict sensor factory announcement,
derives its paired identity, and locks the window to that sensor. For HTV405,
the node similarly adopts the first strict four-zone factory announcement and
applies the custom local gateway's generated controller identity. The HTV405
path changes identity discovery only: its physically accepted reply bodies,
carriers, timing, bounded session, and valve-originated terminal confirmation
remain unchanged. Keep the stock RainPoint gateway powered off during either
new-enrollment exchange to avoid competing replies.

## Home Assistant integration

The app exposes its local device and pairing API on TCP port 8787. Configure the
**RainPoint Local** integration with:

- Host: the IP address of the Home Assistant host
- Port: `8787`

The supported transports currently create confirmed HCS026FRF soil-moisture
entities, a receive-only HTV145 valve device, and an association-backed HTV405
four-zone device. HTV405 exposes one bounded-duration control and one duration
setting per zone only when supervised control is explicitly enabled; state is
accepted only from authenticated responses or subsequent valve telemetry.
HTV405 enrollment completes when a trailer-valid paired-link report for the
expected endpoint is observed after the selected node transmits at least one
session-scoped reply. The retained 18-row stock exchange describes later
initialization traffic but is not a required minimum: physical acceptance and
control have been validated from shorter exchanges. Trailer-invalid frames
cannot create valve links, and phase-only reports advance reception/phase
diagnostics without erasing the latest definitive watering state.
If an authenticated response times out, the app retains only the two smallest
plausible counter candidates. A candidate becomes available only after the full
requested duration plus a 15-second guard has elapsed; the app never replays
the timed-out command immediately. An exact in-window valve response received
by any authenticated radio node can confirm the command, while only the
association owner may transmit it. Unexpected watering or any explicit
node/response failure cancels this recovery path.
The gateway also applies its own response deadline. If a radio node never
returns a usable terminal status, routine device polling fails the exact
durable reservation and enters the same bounded recovery policy rather than
leaving control stuck pending.
Open commands are currently limited to the physically accepted 1-, 2-, and
20-minute payloads. Five- and fifteen-minute values cross an unresolved
duration-encoding boundary and are rejected before counter reservation or RF
dispatch; telemetry decode alone is not evidence that the inverse command
encoding is valid.
The selected HTV405 RF egress node is routing metadata, not part of the valve's
controller identity. It may be moved to another connected, capable node while
idle; doing so preserves the association parameters but deliberately clears the
command counter until it is synchronized again.
HTV145 exposes confirmed watering state, requested duration, and last-session
water usage but remains receive-only.
The temporary `htv145_dry_acceptance` option is a research-only physical-test
gate, not a Home Assistant actuator path. When explicitly enabled it adds a
token-protected one-shot endpoint for an isolated, unpressurized HTV145 valve.
The runner requires fresh valve-originated idle evidence, a retained passive
stock command for counter synchronization, and at least ten minutes without
stock-controller RF before it can transmit one bounded open. It also requires
a confirmed non-low valve battery report, derives channel 0 or 11 from the
confirmed command rather than a frequency default, and will not reuse evidence
that predates an earlier local attempt. Leave the option disabled outside a
supervised acceptance session.
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
semantics. The former companion-heartbeat battery candidate has been withdrawn:
same-file IQ identifies those reversed frames as stock-gateway acknowledgements.

The unified candidate can acknowledge routine reports only for HCS026
endpoints explicitly assigned to that node by the custom local gateway. The
gateway persists exactly one radio-node owner for each sensor, restores those
bounded assignments after reconnect or OTA reboot, and revokes them when a
sensor is removed or reassigned. Home Assistant exposes authorized-sensor,
successful-send, and failed-send counters as diagnostic entities. The normal
production target keeps this transmitter disabled while the consolidated image
completes physical migration validation.

## Safety

This release has no cloud transport and remains receive-only by default. When
`supervised_htv405_control` is explicitly enabled, the API accepts only
token-authenticated, association-specific, duration-bounded HTV405 operations.
Each command is reserved durably before RF dispatch and HA state changes only
after a matching valve response or accepted state report. Restart, missing
telemetry, and client loss never emit a speculative command. USB access is used
only by `rtl_433` or the serial bridge. The read-only share mapping supports an
optional external device catalog and cannot be used to write raw captures.
