# RainPoint Local

An experimental local RainPoint irrigation integration for Home Assistant,
built around the devices' 433 MHz RF protocol.

The goal is an open gateway that receives sensor and valve telemetry, manages
device enrollment, and controls irrigation with independent local safety
limits. The target system has no internet-service or vendor-app dependency.

## Current status

This project has a working receive-only SDR deployment. The RF frame format,
all four installed soil-sensor endpoints, soil moisture, valve duration, and
last-session water usage are confirmed. Valve transmission and local pairing
remain protocol work.

Working now:

- decoding live and captured HCS026FRF soil-moisture RF frames,
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
- reporting local soil, signal, usage, and valve state to Home Assistant, and
- rejecting every control request at the gateway boundary.

Not working yet:

- decoding the HCS026FRF battery-low flag,
- guaranteeing reliable reception at the final antenna location,
- locally pairing or forgetting physical devices, and
- locally opening or closing the physical valve.

The packaged gateway reports all four installed soil endpoints from local RF
and retains unknown RainPoint frames for discovery. The receive path is fully
local; valve control and pairing are not yet implemented.

## Architecture

```text
HCS026 sensors / HTV145 valve
             |
          433 MHz
             |
      local radio transport
   - replay fixtures (implemented)
   - receive-only SDR (implemented in the HA app)
   - ESP32 + CC1101 gateway (planned)
             |
         rainpointd
   protocol + registry + safety
             |
       versioned local API
             |
 Home Assistant rainpoint_local
```

The Home Assistant integration is intentionally independent of the radio
backend. A future hardware transport can replace replay without changing HA
entities or automations.

See [FULL_STACK_ARCHITECTURE.md](FULL_STACK_ARCHITECTURE.md) for the complete
migration and safety design.

## Home Assistant installation

There are two pieces:

1. `rainpoint_local`, the Home Assistant custom integration.
2. `rainpointd`, the service that owns radio decoding, device state, and later
   valve safety. It is now packaged in `rainpointd_addon` as an experimental
   Home Assistant app.

HACS can install the custom integration, but it cannot run `rainpointd`.
The live/replay gateway is packaged as a Home Assistant app/add-on and can
eventually be replaced by a service on a dedicated RF gateway.

### Home Assistant app

The `rainpointd_addon` directory is a Supervisor-compatible app package. For
local development, copy it to `/addons/rainpointd`, reload the app store, and
install **RainPoint Local Gateway** from the Local apps repository.

The app exposes the read-only API on TCP port 8787, maps raw USB for the SDR,
and has no HA API access, Supervisor API access, privileged mode, or full host
access. Live events are stored in the app's persistent data volume.

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
  test_rainpoint_protocol.py test_rainpointd.py test_rainpoint_rf.py
```

The HTTP tests bind only an ephemeral loopback port. They do not contact the
hub, cloud services, or RF hardware.

Prepare or run a bounded receive-only RF capture:

```sh
./tools/capture_rainpoint_rf.sh --dry-run
./tools/capture_rainpoint_rf.sh --duration 15m
```

See [RF_CAPTURE_PLAN.md](RF_CAPTURE_PLAN.md) for the receive and validation
procedure.

## Project documents

- [PROTOCOL.md](PROTOCOL.md): primary 433 MHz protocol specification
- [FULL_STACK_ARCHITECTURE.md](FULL_STACK_ARCHITECTURE.md): direct local bridge
  and safety architecture
- [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md): replay gateway and HA setup
- [RF_CAPTURE_PLAN.md](RF_CAPTURE_PLAN.md): RF capture and validation procedure
- [research/RF_CAPTURE_NOTES.md](research/RF_CAPTURE_NOTES.md): concise dated
  evidence behind the protocol conclusions
- [research/cloud/README.md](research/cloud/README.md): archived cloud-side
  observations, isolated from the local architecture

## Safety

Physical valve control will not be added until the gateway can enforce a local
maximum duration, start an independent close watchdog, confirm state from RF
feedback, and make close commands idempotent. The installed garden system
should remain on its known-working path during receive-only development.

## License

[MIT](LICENSE)
