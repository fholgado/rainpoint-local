# RainPoint Local Gateway

This experimental app runs the local `rainpointd` API used by the
**RainPoint Local** Home Assistant integration.

New independent installations should begin with the
[alpha getting-started guide](../GETTING_STARTED.md). HACS installs the
integration separately from this app; no cloud integration is required.

## Current behavior

Version 0.39.0 supports authenticated network radio nodes, receive-only USB
RTL-SDR, receive-only ESP32/CC1101 serial mode, and authenticated inbound
telemetry from one or more Wi-Fi ESP32 nodes. It does not connect to the
RainPoint cloud. A protocol-v2 node can perform bounded automatic HCS026 pairing through
`hcs026_auto_v1`; automatic identity adoption and known-sensor recovery have
completed physical end-to-end validation across independent identities.
The staged coexistence release persists one custom RF controller identity for
the local gateway and supplies it to every radio node. Existing associations
retain the identity under which they were paired. A node must advertise
`configurable_rf_controller_identity` before it may pair or acknowledge a
device. Older nodes must be upgraded before owning an ACK association. Physical custom-identity sensor enrollment is confirmed; sustained
stock/custom cohort coexistence remains a release gate. Completion requires a
terminal sensor frame addressed to the requested controller identity; a known
sensor's retained-association recovery traffic cannot transfer ACK ownership
during a custom-identity attempt.
Verified HTV145 associations expose a single HA valve and a 1–60 minute watering
duration. The public device-control API uses the saved owner, RF recipe and
counter; it accepts no caller-supplied RF addresses. Counter sync and morning
scheduling remain available. An open stays pending until valve-owned evidence
confirms it; missing replies invalidate the counter and block further opens.
The separate dry-valve research harness is not exposed as an app option.

HTV405 valve-control POST requests require an accepted association and a selected
radio node advertising its control capability; no research enable switch is needed.
Completing HTV405 naming in HA leaves the radio node's bounded association
session running so it can finish every modeled protocol reply. Strict
selector-`0x07` paired-link reports refresh device availability without
overwriting the last definitive zone or watering state.

### Optional morning synchronization

HA exposes a per-valve **Morning sync and direct watering** switch,
**Morning sync starts** local time, and a **Morning sync window** of 15–120 minutes.
Four-zone enabling requires `htv405_bounded_sync_wait`; the switch is
initially off. The HA controls supply Home Assistant's configured timezone.
Choose a window before the first scheduled watering, long enough to include a
routine valve report. Physical daytime reception must be validated before
using this option for unattended garden watering.

During the window the gateway queues one close-0 synchronization. The radio
uses the gateway's known-idle authorization and transmits at a fresh link report;
it independently expires the wait. Any watering report cancels the attempt. A
matching idle response makes **Watering readiness** Ready and records **Last
successful sync**. Run Now then sends the bounded open immediately with the
retained counter. An unanswered open is never automatically retried.

**Resynchronize command counter** acts as Sync now when this option is enabled.
It performs the same close-only bounded wait. A missed window, uncertain command,
association change, or competing controller traffic requires synchronization;
competing traffic requires explicit recovery. Cancel a queued transaction before
changing its owner or forgetting the valve. Restart does not replay commands.

Authenticated API clients configure the policy with
`POST /api/v1/devices/{device_id}/valve/morning-sync` using `enabled`, `start_time`
(`HH:MM`), `timezone` (IANA), and `window_minutes`. Partial updates are supported.
`POST /api/v1/devices/{device_id}/valve/sync-now` requests close-only maintenance.
The existing `/valve/open` endpoint selects direct dispatch when the option is
on and readiness is confirmed; otherwise the default transaction below applies.

### Default synchronized watering

For HTV405 control, one start request is one durable, observable transaction.
The gateway first transmits a non-actuating close at fixed counter `0`. Only an
authenticated closed response advances the transaction; the gateway then waits
the valve's 15-second command interval, transmits the requested open at counter
`0`, and requires the matching authenticated watering response. Telemetry report
time and last command-transmission time are stored independently so routine
reports do not delay user commands.

The transaction fails closed on silence, strict rejection, node or transport
loss, unexpected watering, or gateway restart. It never replays a queued open
after restart. Duplicate starts are rejected while the transaction is active.
Home Assistant keeps the last confirmed valve state visible, removes actuation
controls while work is active, and exposes a status sensor for synchronization,
the hardware interval, watering confirmation, success, cancellation, and
failure. A cancellation button is enabled only before the open has been sent.

The gateway publishes a continuous HTV405 duration capability to Home
Assistant: every whole minute from 1 through 60. Duration is a two-second
counter whose low-byte bit 7 is reserved as a mandatory marker; the displaced
data bit is carried by the adjacent extension byte. The integration validates
the range before dispatch and does not maintain a duration preset list.

When an independently confirmed-idle HTV405 loses command synchronization,
Home Assistant exposes a configuration action that sends a close-only fixed
anchor at counter `0`. It sends no duration and cannot construct an open.
Physical testing proved that every five-bit idle-close value is accepted and
becomes the next counter, so a scan is neither useful nor required. The
standalone diagnostic action may repeat one silent anchor once after the
15-second valve interval; a second silence or strict rejection stops
fail-closed. Its retry is durable across gateway and radio-node restarts. The
end-user watering transaction is stricter: it attempts one anchor and never
restores its queued open across a restart.

Ordinary control is restored only by a matching authenticated closed response,
whose sequence remains current for the next open. Silence, successful node
dispatch, and ordinary valve telemetry do not establish synchronization. An
unexpected watering report aborts synchronization and leaves the counter
unsynchronized. Home Assistant shows the anchor, attempt, and terminal state;
a fresh strict idle report is required before a new failed synchronization can
start.

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
Firmware 0.15.8 also accepts the captured repeat marker on counter 2, which
previously delayed the response until counter 4. The one-reply transaction
completes after transmission, immediately restoring normal receive and
acknowledgement service; fresh sensor telemetry is required to verify recovery.
The authenticated command inbox holds up
to eight commands so every persisted ACK assignment can be restored after a
reconnect or OTA reboot.
After the first OTA-capable image is installed by USB, compatible releases can
be installed from the radio node's Home Assistant firmware Update entity.
Firmware delivery permits slow flash-write readers with 16 KiB socket writes,
a ten-second per-write timeout, and a 120-second total transfer deadline. At
most two firmware downloads run concurrently; additional requests receive 503
without consuming the ordinary API's full worker capacity. These transport
limits do not replace the node's byte-count, SHA-256 or healthy-boot checks.
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
`hcs026_auto_v1`, `htv405_auto_candidate_v1` and `htv145_auto_candidate_v1`
are user-pairable. HTV145 discovery requires `htv145_auto_identity_pairing`;
control verification additionally requires `htv145_commissioning`. Pairing
does not authorize watering. The [onboarding guide](../NODE_ONBOARDING.md)
describes the separately consented bounded tests and current capacity limits.

Normal single-zone verification uses authenticated POST requests to
`/api/v1/commissioning/{status,begin,advance,cancel}` with `device_id` and, for
mutating actions, the current `pairing_command_id` returned by status. Begin
also requires `test_watering_confirmed: true`. RF identities, frequencies and
counters are derived on the gateway and are not client inputs. This flow does
not require the research setting. Its fixed first-open uses the separate
`htv145_control_commission_open` command; the old research bootstrap route and
`htv145_bootstrap_trial` remain gated. These source changes are staged; see the
roadmap for deployment and end-to-end acceptance status.

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

The supported transports create HCS026FRF soil-moisture entities, an HTV145
single-zone device with controls after qualification, and an association-backed HTV405
four-zone device. HTV405 exposes one bounded-duration control and one duration
setting per zone only when supervised control is explicitly enabled; state is
accepted only from authenticated responses or subsequent valve telemetry.
Starting a zone automatically synchronizes with a fixed close-`0` anchor before
the requested open. That non-actuating anchor is held until the valve's next
radio check-in so a sleeping battery valve cannot miss it. The valve control is
disabled while this transaction is in progress, and the **Control request
status** entity explains whether the gateway is waiting for that check-in,
synchronizing, waiting for the 15-second interval, waiting for the valve's
watering response, confirmed, cancelled, or failed. **Cancel watering request**
is available only until the open is transmitted. A later valve-originated idle
report advances a successful request to **Watering completed** and returns the
controls to ready.
HTV405 enrollment completes when a trailer-valid paired-link report for the
expected endpoint is observed after the selected node transmits at least one
session-scoped reply. The retained 18-row stock exchange describes later
initialization traffic but is not a required minimum: physical acceptance and
control have been validated from shorter exchanges. Trailer-invalid frames
cannot create valve links, and phase-only reports advance reception/phase
diagnostics without erasing the latest definitive watering state.
An exact in-window valve response received by any authenticated radio node can
confirm the command, while only the association owner may transmit it. If an
authenticated anchor or open response does not arrive before the gateway
deadline, the transaction fails, clears its queued work, and reports the reason
instead of leaving control stuck pending or guessing a counter.
Open commands accept every whole-minute duration from 1 through 60. The packed
wire codec preserves the counter bit displaced by the mandatory low-byte
marker in the adjacent extension byte; values outside that continuous range
are rejected before counter reservation or RF dispatch.
The selected HTV405 RF egress node is routing metadata, not part of the valve's
controller identity. It may be moved to another connected, capable node while
idle; doing so preserves the association parameters but deliberately clears the
command counter until it is synchronized again.
HTV145 exposes confirmed watering, duration, usage, categorical battery, and
per-association control state. Multi-valve firmware supports eight single-zone
associations per radio; older firmware remains limited to one per radio.
It also exposes
counter/morning-sync controls for its enrolled qualification owner. It does not
expose four-zone actuators. Qualified associations support ordinary HA actuation;
the revised draft replaces mandatory test runs with radio-owner setup and a
recommendation to test dry or visually confirm operation. Confirmed fresh pairing
initializes counter 1 (`0x81`) once; matching responses confirm/advance it.
Pairing-derived versus response-confirmed authority is exposed in device state.
End-to-end acceptance remains pending for this undeployed draft; see the roadmap.
The dry-qualification API below remains separate developer tooling.

Sensor reports expose moisture, categorical battery, freshness, and receiver
provenance. One persistent owner transmits ACKs; other nodes may forward the
same report. Unsupported protocol values remain unavailable. Device identity
comes from the accepted association, and re-registration reuses an established
catalog identity instead of creating a duplicate HA device.

## Safety

This release has no cloud transport. A fresh installation cannot control an
unassociated valve; pairing and ACK transmission require explicit ownership.
Qualified HTV145 controls are available through the normal HA flow. The API accepts only
token-authenticated, association-specific, duration-bounded HTV405 operations.
Each command is reserved durably before RF dispatch and HA state changes only
after a matching valve response or accepted state report. Restart, missing
telemetry, and client loss never emit a speculative command. USB access is used
only by `rtl_433` or the serial bridge. The read-only share mapping supports an
optional external device catalog and cannot be used to write raw captures.

## HTV145 persistent dry qualification

For a freshly paired custom-identity valve without a prior command exchange,
the gated `research/htv145-control/qualification-prepare` action accepts
`device_id`, `node_id`, `dry_valve_confirmed: true`, `center_hz`, and
`report_ack_center_hz`. It derives RF identities from the accepted registry and
requires fresh idle telemetry. Revoke the previous control/ACK owner first.
Preparation grants provisional ACK ownership and requests a fresh owner idle
report for the fixed-zero close anchor; it never copies a counter or opens.

Using the same research prefix, `qualification-status`, `qualification-open`,
and `qualification-close` take `device_id`. Two opens are permitted, each exactly
60 seconds: first verify automatic stop, then explicitly close the second after
at least 15 seconds and before its automatic timeout. Only matching positive
responses plus independent idle reports complete qualification. Public controls
and morning-sync changes remain blocked throughout. Restart interrupts the
test and cancels any unsent anchor; unresolved watering is never replayed.
After a rejected initial anchor, `qualification-bootstrap` takes `device_id`
and `dry_valve_confirmed: true`. It permits one fixed counter-`81`, 60-second
candidate open, without claiming a synchronized counter. It requires opt-in
firmware advertising `htv145_bootstrap_trial`; normal builds omit this operation.
A positive reply and independent stop must still pass the same qualification
sequence. Negative replies, missing responses and restart do not authorize a retry.
The existing pairing sequence is unchanged. The persisted qualification record uses schema 23;
restore the pre-update database backup when rolling back to an older gateway.

Requires the standalone research CLI's `--enable-htv145-dry-acceptance`,
a qualified isolated dry valve, and an owner
advertising `htv145_report_ack_tx`. All routes below require the management token
and live under `/api/v1/research/htv145-control/`.

| POST action | Input and effect |
|---|---|
| `status`, `morning-check` | `valve_endpoint`; read readiness/counter/physical state without RF |
| `open` | `valve_endpoint`, `duration_seconds`; one bounded whole-minute run, 60–3600 seconds |
| `close` | `valve_endpoint`; explicit authenticated close after command spacing; fresh idle returns without RF |
| `enroll` | `profile`, positive `command_frame`/`response_frame`, independent `idle_frame`, and `exchange_observed_at`/`idle_observed_at`; persist only recent verified evidence |
| `revoke` | `valve_endpoint`; require the existing owner's correlated revocation reply |

The profile supplies `node_id`, `controller_endpoint`, `valve_endpoint`,
`center_hz`, `power_dbm`, `invert`, `trailer_residual`, `command_marker_inverted`,
`close_trailer_residual`, and `report_ack_center_hz`. Use the accepted association,
not installation defaults. No existing ACK owner can be silently replaced.

HA Sync counter uses `/api/v1/devices/{device_id}/valve/sync-now` on an owner with
`htv145_idle_anchor`. It waits for a new owner idle report and performs fixed-zero,
close-only recovery. Three total attempts share one bounded window; each retry
requires a later owner idle report. The legacy `/valve/restore-counter` restores
an already authenticated counter to the radio without RF or new counter proof.
Morning policy uses `/valve/morning-sync` with the same fields described above.

Restart never replays an actuator command. Report sequences cannot reseed command
counters, and repeated session summaries cannot change current watering state.
See [the one-zone protocol](../protocol_documentation/htv145frf.md) for ACK and
counter rules and [the roadmap](../PROJECT_ROADMAP.md) for physical qualification.
