# Local development

The repository has three runtime layers and one standard firmware build:

- `rainpointd_addon/rainpointd` — local gateway and API;
- `custom_components/rainpoint_local` — Home Assistant adapter;
- `firmware/rainpoint_bridge` — ESP32/CC1101 radio node; and
- `research/fixtures` — immutable captured protocol evidence used by tests.

No development command contacts HomGar services. Valve-control requests remain
rejected.

## Gateway transports

Replay captured fixtures on loopback:

```sh
PYTHONPATH=rainpointd_addon python3 -m rainpointd
```

Run a receive-only RTL-SDR gateway:

```sh
PYTHONPATH=rainpointd_addon python3 -m rainpointd \
  --transport rtl433 --host 0.0.0.0
```

The live SDR path uses `rtl_433` with a 433.7 MHz / 2.0 Msps FSK pulse-decoder
pipeline and accepts only the confirmed RainPoint sync family. Network radio
nodes connect outbound to TCP 8790 using protocol v2.

## API

The default development API is `http://127.0.0.1:8787/api/v1`.

Useful read-only endpoints:

- `GET /health`
- `GET /api/v1/info`
- `GET /api/v1/devices`
- `GET /api/v1/nodes`
- `GET /api/v1/endpoints`
- `GET /api/v1/events?since=<event_id>`

Registry, pairing, node, ACK-owner, and OTA mutations require the management
credential. Supervisor discovery provisions it automatically on HAOS. Never
place real credentials in issues, fixtures, or logs.

Pass `--storage <path>` for SQLite persistence. The packaged app uses its
private `/data` volume.

## Home Assistant development install

1. Copy `rainpointd_addon` to `/addons/rainpointd`.
2. Reload the app store and rebuild/install `local_rainpointd`.
3. Copy `custom_components/rainpoint_local` to the HA configuration directory.
4. Restart HA and add **RainPoint Local**.

The app requests no HA/Supervisor API token or privileged/full-host mode. USB
access supports the optional SDR; Wi-Fi radio nodes do not require USB.

## Verification

Run the full command listed in the root README or use unittest discovery:

```sh
python3 -m unittest -v
```

Build and inspect the sole firmware image:

```sh
pio run --project-dir firmware/rainpoint_bridge
python tools/check_firmware_boundaries.py \
  firmware/rainpoint_bridge/.pio/build/rainpoint_bridge/firmware.bin
```

Compile the hardware-independent C++ protocol regression:

```sh
c++ -std=c++17 -Ifirmware/rainpoint_bridge/include \
  firmware/rainpoint_bridge/tests/protocol_test.cpp \
  -o /tmp/rainpoint-protocol-test
/tmp/rainpoint-protocol-test
```

Research capture and analysis tools remain under `tools`, but there are no
alternative bench/candidate firmware environments. New RF behavior must first
be represented as captured evidence and offline tests, then added to the one
standard firmware behind the existing bounded command authority.
