# Local development

Optional Mac research listening: [managed SDR receiver](docs/MAC_SDR_RECEIVER.md).
It remains receive-only and independent of HA's production radio nodes.

The repository has three runtime layers and one standard firmware build:

- `rainpointd_addon/rainpointd` — local gateway and API;
- `custom_components/rainpoint_local` — Home Assistant adapter;
- `firmware/rainpoint_bridge` — ESP32/CC1101 radio node; and
- `research/fixtures` — immutable captured protocol evidence used by tests.

The replay development configuration does not contact HomGar or authorize live
RF actuation. Live valve paths require explicit gates and an accepted association.

## Gateway transports

Replay captured fixtures on loopback:

```sh
PYTHONPATH=rainpointd_addon python3 -m rainpointd --transport replay \
  --replay-fixtures examples/captured-replay/fixtures.json
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

The installed API is `https://HOST:8787/api/v1`, authenticated with TLS-PSK.
Use `rainpointd.secure_transport.client_context` for research clients. Plain HTTP
is only for explicitly unencrypted, isolated development listeners.

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

Before a live update, check free space and back up only the affected app (for
example `ha backups new --app local_rainpointd --name <purpose>`). An unqualified
`ha backups new` creates a full backup, including shared research captures; this
can exhaust storage. Do not delete source captures to make a deployment fit.
Use `ha apps update local_rainpointd` when the source version changes; `rebuild`
is only for the currently installed version. Verify the backup and update
results, not just their command exit codes.

1. Copy `rainpointd_addon` to `/addons/rainpointd`.
2. Reload the app store and rebuild/install `local_rainpointd`.
3. Copy `custom_components/rainpoint_local` to the HA configuration directory.
4. Clear generated integration `__pycache__` directories after copying a source
   archive, then restart HA and add **RainPoint Local**. Deterministic archives
   retain fixed timestamps; clearing bytecode prevents equal-size edits from
   reusing a stale cache.

The app requests no HA/Supervisor API token or privileged/full-host mode. USB
access supports the optional SDR; Wi-Fi radio nodes do not require USB.

## Verification

From the repository root, run the Python tests in `tests/` using discovery
(with the permission preflight in [AGENTS.md](AGENTS.md)):

```sh
python3 -m pip install -r tests/requirements.txt
python3 -m unittest discover -s tests -t . -v
```

For a focused run: `python3 -m unittest tests.test_rainpointd -v`.
Shared captured-installation fixtures live in `tests/support.py`; native C++
tests remain with their firmware under `firmware/rainpoint_bridge/tests/`.

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

## Release source package

`python3 tools/package_release.py /tmp/rainpoint-release.tar.gz --smoke-test`
creates a deterministic archive from tracked runtime files and checks a fresh,
isolated installation plus restart. It excludes research, captures, credentials,
replay examples, and firmware build output. CI compares two generated archives.
The app base image and PlatformIO version are pinned; OS package repositories
still determine APK revisions, so source reproducibility is not a claim of
byte-identical container images or signed firmware.
