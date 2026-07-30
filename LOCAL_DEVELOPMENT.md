# Local gateway and Home Assistant development

This milestone is a read-only replay environment. It never connects to the
RainPoint hub, HomGar services, or RF hardware, and it rejects all HTTP POST
requests.

## Components

- `rainpointd_addon/rainpointd/`: state/event store and versioned HTTP API
- `rainpointd_addon/rainpointd/replay.py`: captured-fixture transport
- `rainpointd_addon/`: installable Home Assistant app package
- `custom_components/rainpoint_local/`: Home Assistant integration
- `test_rainpointd.py`: gateway and HTTP contract tests

## Run the replay gateway

From `rainpoint-research`:

```sh
PYTHONPATH=rainpointd_addon python3 -m rainpointd
```

The default listener is loopback-only:

```text
http://127.0.0.1:8787/api/v1
```

Inspect it:

```sh
curl http://127.0.0.1:8787/api/v1/info
curl http://127.0.0.1:8787/api/v1/devices
curl 'http://127.0.0.1:8787/api/v1/events?since=0'
```

To let a separate Home Assistant host reach a development Mac, bind the replay
server to the Mac's LAN interface only while testing:

```sh
PYTHONPATH=rainpointd_addon python3 -m rainpointd --host 0.0.0.0
```

This is a development convenience. For persistent replay testing on HAOS, use
the app package in `rainpointd_addon`. The eventual live gateway should run
there or on the machine that owns the RF receiver.

## API contract

Read-only endpoints:

- `GET /health`
- `GET /api/v1/info`
- `GET /api/v1/devices`
- `GET /api/v1/events?since=<event_id>`

Each observation includes:

- monotonic gateway event ID,
- gateway observation timestamp in UTC,
- stable local device ID and friendly name,
- model,
- original raw frame, and
- decoded typed state.

The event cursor allows a future push adapter or recorder to resume without
requiring Home Assistant to interpret RF framing. The in-memory history is
bounded and is not yet a durable event log.

## Install the development integration

Do not install it until `rainpointd` is running at an address reachable from
Home Assistant.

Copy the integration directory into the HA configuration:

```text
custom_components/rainpoint_local/
```

Restart Home Assistant, then use:

```text
Settings → Devices & services → Add integration → RainPoint Local
```

Enter the gateway host and port. The integration verifies `/api/v1/info` and
uses the gateway ID as its unique identity.

It currently creates:

- soil moisture,
- battery,
- RF signal,
- device report time,
- valve state,
- reported duration,
- last water usage, and
- read-only watering status.

There is intentionally no valve entity or control service in this milestone.

## Run tests

```sh
python3 -m unittest -v test_rainpoint_protocol.py test_rainpointd.py
```

The HTTP tests bind only an ephemeral loopback port.

## Run persistently on Home Assistant OS

For local development, copy `rainpointd_addon` into the HAOS local-app
directory as `/addons/rainpointd`, then reload the app catalog:

```sh
ha store reload
ha apps info local_rainpointd
ha apps install local_rainpointd
ha apps start local_rainpointd
```

The installed app is intentionally protected and requests no host privileges,
HA or Supervisor API tokens, device mappings, USB, UART, or writable HA
configuration directories. It publishes the read-only API on host TCP port
8787.

Verify it from another LAN machine:

```sh
curl http://HOME_ASSISTANT_IP:8787/health
curl http://HOME_ASSISTANT_IP:8787/api/v1/info
```

The response from `/api/v1/info` must report `"read_only": true` and
`"transport": "replay"`.

## Next transport

The next adapter should accept decoded messages from an RTL-SDR/`rtl_433`
receiver and call `Gateway.observe(...)`. It must not add control endpoints.
The replay and RF transports should emit the same event schema so the Home
Assistant integration does not change when live receive-only data arrives.

Open questions that RF capture must answer:

- where the stable device identity appears in the over-the-air frame,
- checksum or CRC coverage,
- exact modulation and bit timing,
- whether valve status and sensor reports share framing,
- duplicate/retry semantics, and
- whether rolling counters affect passive decoding.
