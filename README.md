# RainPoint Local

An experimental, local-first RainPoint irrigation integration for Home
Assistant.

The goal is to replace the HomGar/RainPoint cloud software stack with an open
local gateway that can receive sensor data, manage device enrollment, and
eventually control irrigation with independent safety limits.

## Current status

This project is in the protocol-research and simulator phase.

Working now:

- decoding captured HCS026FRF soil-moisture status payloads,
- decoding captured HTV145FRF valve status payloads,
- replaying captured observations through a local `rainpointd` API,
- reporting replayed soil, battery, signal, usage, and valve state to Home
  Assistant, and
- rejecting every control request at the gateway boundary.

Not working yet:

- receiving live 433 MHz data directly,
- operating without the stock hub's cloud connection,
- locally pairing or forgetting physical devices, and
- locally opening or closing the physical valve.

Installing the current code does **not** make the existing RainPoint system
offline-capable. It reports replay fixtures until a real receive-only RF adapter
or a stock-hub local transport is implemented.

## Architecture

```text
HCS026 sensors / HTV145 valve
             |
          433 MHz
             |
   interchangeable transport
   - replay fixtures (implemented)
   - receive-only SDR (next)
   - open CC1101 gateway
   - original-hub emulator
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
   valve safety.

HACS can install the custom integration, but it cannot run `rainpointd`.
`rainpointd` will ultimately be distributed as a Home Assistant app/add-on or
run on the replacement RF gateway.

### Development installation

Run the replay gateway:

```sh
python3 -m rainpointd
```

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

Decode a captured frame:

```sh
python3 rainpoint_protocol.py HCS026FRF \
  '10#E1BA00DC01883AFF0F6C9CFC19'
```

Run the regression and API tests:

```sh
python3 -m unittest -v test_rainpoint_protocol.py test_rainpointd.py
```

The HTTP tests bind only an ephemeral loopback port. They do not contact the
hub, cloud services, or RF hardware.

## Project documents

- [PROTOCOL.md](PROTOCOL.md): decoded fields and current evidence
- [FULL_STACK_ARCHITECTURE.md](FULL_STACK_ARCHITECTURE.md): end-to-end design
- [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md): replay gateway and HA setup
- [RF_CAPTURE_PLAN.md](RF_CAPTURE_PLAN.md): receive-only RF capture procedure
- [HUB_EMULATION_PLAN.md](HUB_EMULATION_PLAN.md): retaining the original hub
- [PASSIVE_MONITORING.md](PASSIVE_MONITORING.md): passive observations

## Safety

Physical valve control will not be added until the gateway can enforce a local
maximum duration, start an independent close watchdog, confirm state from RF
feedback, and make close commands idempotent. The installed garden system
should remain on its known-working path during receive-only development.

## License

[MIT](LICENSE)
