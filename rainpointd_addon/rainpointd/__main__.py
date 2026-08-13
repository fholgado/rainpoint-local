"""Run the local RainPoint gateway."""

from __future__ import annotations

import argparse
import os

from .device_catalog import LEGACY_HOME_CATALOG, load_catalog
from .esp32 import ESP32SerialTransport
from .esp32_network import ESP32NetworkServer, load_node_tokens
from .gateway import Gateway
from .http import create_server
from .network import NetworkTransport
from .replay import ReplayTransport
from .rtl433 import RTL433Transport
from .storage import DEFAULT_EVENT_RETENTION_LIMIT


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--transport",
        choices=("network", "replay", "rtl433", "esp32_serial"),
        default="network",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="seconds between replayed observations",
    )
    parser.add_argument("--frequency", type=int, default=433_700_000)
    parser.add_argument("--sample-rate", type=int, default=2_000_000)
    parser.add_argument("--signal-capture-seconds", type=int, default=0)
    parser.add_argument("--signal-directory")
    parser.add_argument("--serial-device", default="/dev/ttyUSB0")
    parser.add_argument("--serial-baud", type=int, default=115_200)
    parser.add_argument("--node-listen-host", default="0.0.0.0")
    parser.add_argument(
        "--node-listen-port",
        type=int,
        default=0,
        help="authenticated Wi-Fi node listener; 0 disables it",
    )
    parser.add_argument(
        "--gateway-id",
        help="stable gateway identifier; defaults to a transport-derived dev ID",
    )
    parser.add_argument(
        "--storage",
        help="SQLite path for persistent events and endpoint inventory",
    )
    parser.add_argument(
        "--event-retention-limit",
        type=int,
        default=DEFAULT_EVENT_RETENTION_LIMIT,
        help="maximum number of journal events retained in SQLite",
    )
    parser.add_argument(
        "--registry-token-file",
        help="path used to persist management credential rotation",
    )
    parser.add_argument(
        "--device-catalog",
        help=(
            "installation catalog JSON; omitted only for legacy prototype "
            "identity compatibility"
        ),
    )
    args = parser.parse_args()

    catalog = (
        load_catalog(args.device_catalog)
        if args.device_catalog
        else LEGACY_HOME_CATALOG
    )

    gateway = Gateway(
        gateway_id=args.gateway_id or f"rainpoint-{args.transport}",
        transport=args.transport,
        storage_path=args.storage,
        event_retention_limit=args.event_retention_limit,
        registry_token=os.environ.get("RAINPOINT_REGISTRY_TOKEN"),
        registry_token_path=args.registry_token_file,
        claim_code=os.environ.get("RAINPOINT_CLAIM_CODE"),
        catalog=catalog,
    )
    if args.transport == "rtl433":
        transport = RTL433Transport(
            gateway,
            frequency=args.frequency,
            sample_rate=args.sample_rate,
            signal_capture_seconds=args.signal_capture_seconds,
            signal_directory=args.signal_directory,
        )
    elif args.transport == "esp32_serial":
        transport = ESP32SerialTransport(
            gateway,
            device=args.serial_device,
            baud=args.serial_baud,
        )
    elif args.transport == "replay":
        transport = ReplayTransport(gateway, interval=args.interval)
    else:
        transport = NetworkTransport()
    transport.seed()
    transport.start()
    node_server = None
    if args.node_listen_port:
        node_server = ESP32NetworkServer(
            gateway,
            host=args.node_listen_host,
            port=args.node_listen_port,
            node_tokens=load_node_tokens(os.environ.get("RAINPOINT_NODE_TOKENS")),
        )
        node_server.start()
        print(
            "rainpointd authenticated node listener on "
            f"{args.node_listen_host}:{node_server.server_port}"
        )
    server = create_server(gateway, args.host, args.port)
    print(
        f"rainpointd {args.transport} API listening on "
        f"http://{args.host}:{server.server_port}/api/v1"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        if node_server is not None:
            node_server.stop()
        transport.stop()
        gateway.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
