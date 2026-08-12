# RainPoint Local

An experimental local RainPoint irrigation integration for Home Assistant,
built around the devices' 433 MHz RF protocol.

The goal is an open gateway that receives sensor and valve telemetry, manages
device enrollment, and controls irrigation with independent local safety
limits. The target system has no internet-service or vendor-app dependency.

## Current status

This project has a working receive-only SDR deployment, a physically validated
two-identity ESP32/CC1101 enrollment prototype, and a physically validated
automatic HCS026 pairing path. The RF frame format, soil
moisture, HCS026 enrollment identities, one HCS026 battery layout, valve
duration, and last-session water usage are confirmed. Test Sensor B has been
paired entirely through the local transmitter and subsequently reported an
independently verified 11% moisture reading with the stock RainPoint gateway
disconnected. Valve transmission remains protocol work.

Working now:

- decoding live and captured HCS026FRF soil-moisture RF frames,
- discovering HCS026FRF sensors from validated paired telemetry rather than a
  household-specific endpoint list,
- identifying newly paired soil sensors first by their HCS02x RF protocol
  family, using product code `0x48` to select the shared HCS02x capability
  family, and promoting the exact `HCS026FRF` model only when model code
  `0x013d` or trusted migration metadata supplies variant-level evidence,
- reporting the confirmed full/low battery flag used by newly tested HCS026
  sensors,
- persisting an HCS026 factory-to-paired identity only after a complete
  transition inside an explicit pairing window,
- physically enrolling both test sensors through evidence-backed reply
  sequences on a single ESP32/CC1101 radio node and requiring terminal message
  `03` before declaring success,
- deriving a newly announced HCS026 sensor's paired identity locally through
  the model-level `hcs026_auto_v1` candidate, without user-supplied RF IDs,
- starting that bounded pairing exchange from Home Assistant through an
  authenticated, explicitly selected Wi-Fi radio node,
- receiving post-enrollment moisture telemetry from that locally paired sensor
  without the stock RainPoint gateway or cloud service,
- naming and assigning the terminal-confirmed sensor through the integration's
  authenticated **Configure** flow,
- forgetting any known local HCS026 sensor through a confirmed **Configure**
  flow without sending an RF reset, while retaining its HA identity for later
  reassociation,
- decoding HTV145FRF valve command, state, duration, and usage fields,
- receiving live RainPoint 2-FSK packets through `rtl_433`,
- reporting confirmed HCS026FRF soil moisture through the local `rainpointd`
  API,
- dynamically creating Home Assistant sensor entities for newly observed RF
  endpoints,
- retaining normalized RF events and endpoint inventory across app restarts,
- replaying captured observations through a local `rainpointd` API,
- running live RTL-SDR or replay transport persistently as a protected Home
  Assistant app on `aarch64` or `amd64`,
- building a single-CC1101 firmware prototype, with an optional dual-radio
  diagnostic build, using the measured RainPoint radio profiles, serial frame
  diagnostics, and a validated profile-driven pairing TX path,
- accepting radio-node frames through serial or authenticated Wi-Fi transport,
- simulating fail-closed startup, bounded runs, acknowledgement timeouts,
  client loss, watchdog expiry, close retries, and persistent fault retries
  without connecting those actions to a transmitter,
- reporting local soil, signal, usage, and valve state to Home Assistant, and
- rejecting every valve-control request at the gateway boundary.

Still provisional or not working yet:

- decoding the older installed sensors' separate companion-heartbeat battery
  status, whose meaning remains provisional,
- guaranteeing reliable reception at the final antenna location,
- repeating the physically validated automatic model-level pairing workflow
  on a second independent identity before claiming broad HCS026 support,
- implementing and validating routine post-enrollment sensor acknowledgements,
- avoiding interference from a still-powered stock RainPoint gateway during
  migration enrollment,
- locally opening or closing the physical valve.

The packaged gateway reports all four installed soil endpoints from local RF
and retains unknown RainPoint frames for discovery. The receive path is fully
local. Home Assistant now starts one automatic HCS026 workflow; the selected
node adopts the first strict factory announcement and locks the pairing window
to that identity. Physical validation of this new automatic path and valve
control remain outstanding.

## Architecture

```text
HCS026 sensors / HTV145 valve
             |
          433 MHz
             |
      local radio transport
   - replay fixtures (implemented)
   - receive-only SDR (implemented in the HA app)
   - ESP32 + CC1101 node (receive plus bounded HCS026 pairing TX)
             |
         rainpointd
   protocol + registry + safety
             |
       versioned local API
             |
 Home Assistant rainpoint_local
```

The Home Assistant integration is intentionally independent of the radio
backend. New installations default to a network-only gateway fed by
authenticated Wi-Fi radio nodes; replay remains an explicit development mode.

See [FULL_STACK_ARCHITECTURE.md](FULL_STACK_ARCHITECTURE.md) for the complete
migration and safety design.

Physical validation procedures are tracked in
[`research/DEVICE_PAIRING_VALIDATION_PLAN.md`](research/DEVICE_PAIRING_VALIDATION_PLAN.md),
including the remaining multi-identity sensor tests and the staged test-valve
stock capture, offline reconstruction, and isolated local enrollment sequence.

The future handoff for existing cloud-connected users is designed in
[`CLOUD_TO_LOCAL_MIGRATION.md`](CLOUD_TO_LOCAL_MIGRATION.md). It preserves HA
identity and history while switching each supported device to exactly one
authoritative provider; active migration remains gated on sensor/valve pairing
and bounded valve-control proof.

## Home Assistant installation

There are two pieces:

1. `rainpoint_local`, the Home Assistant custom integration.
2. `rainpointd`, the service that owns radio decoding, device state, and later
   valve safety. It is now packaged in `rainpointd_addon` as an experimental
   Home Assistant app.

HACS can install the custom integration, but it cannot run `rainpointd`.
The local gateway is packaged as a Home Assistant app/add-on and can
eventually be replaced by a service on a dedicated RF gateway.

### Home Assistant app

The `rainpointd_addon` directory is a Supervisor-compatible app package. For
local development, copy it to `/addons/rainpointd`, reload the app store, and
install **RainPoint Local Gateway** from the Local apps repository.

The app exposes local telemetry and authenticated sensor pairing on TCP port
8787, maps raw USB for the SDR,
and has no HA API access, Supervisor API access, privileged mode, or full host
access. Live events are stored in the app's persistent data volume. The device
API also reports persistent check-in counts and cadence, plus a current
`reporting` status based on the measured intervals of each device class.

An authenticated local registry can accept, rename, assign, or forget observed
endpoints. The Home Assistant app provisions its management credential through
Supervisor discovery, so it never appears in the normal pairing UI. The
pairing workflow can arm one authenticated
protocol-v2 node for automatic HCS026 discovery and persists the identity only
after terminal RF confirmation. Valve-control POST requests remain unavailable.

### Development installation

Run the replay gateway:

```sh
PYTHONPATH=rainpointd_addon python3 -m rainpointd
```

Run the live, receive-only SDR gateway on the machine containing the USB
receiver:

```sh
PYTHONPATH=rainpointd_addon python3 -m rainpointd \
  --transport rtl433 --host 0.0.0.0
```

This requires `rtl_433`. It starts no transmitter and publishes only RF frames
matching the confirmed RainPoint sync word.

The ESP32/CC1101 firmware, wiring, and build instructions are under
[`firmware/rainpoint_bridge`](firmware/rainpoint_bridge/README.md). It is
receive-capable and exposes only bounded HCS026 pairing TX over its
authenticated network protocol. It contains no valve TX path.

The passive socketed carrier-PCB design is under
[`hardware/rainpoint_carrier`](hardware/rainpoint_carrier/README.md). Revision
A deliberately reuses the ESP32's USB-C power, onboard GPIO2 status LED, and
GPIO0 BOOT button; the carrier adds no duplicate user-interface hardware.

Copy `custom_components/rainpoint_local` into the Home Assistant configuration
directory, restart Home Assistant, and add **RainPoint Local** from
**Settings → Devices & services**.

If Home Assistant runs on a different machine, follow
[LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md) to expose the development listener
on the LAN.

### HACS

The repository layout is HACS-compatible. Once the repository is public:

1. Open HACS.
2. Select **Custom repositories**.
3. Add `https://github.com/fholgado/rainpoint-local` as an **Integration**.
4. Download **RainPoint Local** and restart Home Assistant.

This installs only the HA integration. A reachable `rainpointd` instance is
still required.

## Development

Decode a captured RF recording:

```sh
python3 tools/decode_rainpoint_iq.py \
  --sample-rate 2000000 --frequency 433700000 capture.cu8
```

Run the regression and API tests:

```sh
python3 -m unittest -v \
  test_rainpoint_protocol.py test_rainpointd.py test_rainpoint_rf.py \
  test_rainpoint_analysis.py test_rainpoint_safety.py
```

Analyze one or more concatenated `rainpointd` event API pages without changing
gateway state:

```sh
python3 tools/analyze_rainpoint_events.py events.json --pretty
```

Or read every cursor page directly from a local read-only gateway:

```sh
python3 tools/analyze_rainpoint_events.py \
  --url http://homeassistant.local:8787/api/v1/events --summary --pretty
```

Pure offline HTV145 open/close frame builders now reproduce captured command
vectors and generate both unresolved trailer candidates. They are deliberately
not connected to the HTTP API, ESP32 serial transport, or any radio transmit
operation.

Generate a matching command waveform for offline inspection with the same CU8
format used by the receive tools:

```sh
python3 tools/generate_rainpoint_iq.py /tmp/rainpoint-command.cu8 \
  --frame 79f4882f28b42d008fb98402809710828081009e000000000000000000000000000000003824
python3 tools/characterize_rainpoint_iq.py /tmp/rainpoint-command.cu8
python3 tools/compare_rainpoint_iq.py captured-reference.cu8 \
  /tmp/rainpoint-command.cu8
```

The generator reproduces the measured 60 ms alternating wake sequence,
20 ksymbol/s timing, and +/-40 kHz 2-FSK deviation. It only writes a file and
contains no socket, serial, GPIO, or radio transmission path.
The comparator checks channel center, tone separation, and occupied bandwidth
without requiring the two captures to have matching sample alignment.

The target bridge uses one ESP32 and one half-duplex CC1101 transceiver. The
current SDR/Pi remains the independent receive reference during development;
the firmware's optional second CC1101 build is diagnostic only.

The HTTP tests bind only an ephemeral loopback port. They do not contact the
hub, cloud services, or RF hardware.

Prepare or run a bounded receive-only RF capture:

```sh
./tools/capture_rainpoint_rf.sh --dry-run
./tools/capture_rainpoint_rf.sh --duration 15m
```

See [research/RF_CAPTURE_PLAN.md](research/RF_CAPTURE_PLAN.md) for the receive
and validation procedure.

## Project documents

- [PROTOCOL.md](PROTOCOL.md): primary 433 MHz protocol specification
- [FULL_STACK_ARCHITECTURE.md](FULL_STACK_ARCHITECTURE.md): direct local bridge
  and safety architecture
- [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md): replay gateway and HA setup
- [hardware/rainpoint_carrier/README.md](hardware/rainpoint_carrier/README.md):
  passive ESP32/CC1101 carrier-PCB design
- [research/RF_CAPTURE_PLAN.md](research/RF_CAPTURE_PLAN.md): RF capture and
  validation procedure
- [research/RF_CAPTURE_NOTES.md](research/RF_CAPTURE_NOTES.md): concise dated
  evidence behind the protocol conclusions
- [research/cloud/README.md](research/cloud/README.md): archived cloud-side
  observations, isolated from the local architecture

## Safety

Physical valve control will not be added until the gateway can enforce a local
maximum duration, start an independent close watchdog, confirm state from RF
feedback, and make close commands idempotent. The installed valve should
remain on its known-working path while valve TX is under development. Sensor
pairing requires the original RainPoint gateway to be temporarily powered off
so it cannot send a competing enrollment reply.

## License

[MIT](LICENSE)
