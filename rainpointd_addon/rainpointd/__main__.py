"""Run the local RainPoint gateway."""

from __future__ import annotations

import argparse

from .gateway import Gateway
from .http import create_server
from .replay import ReplayTransport
from .rtl433 import RTL433Transport


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--transport", choices=("replay", "rtl433"), default="replay"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="seconds between replayed observations",
    )
    parser.add_argument("--frequency", type=int, default=434_000_000)
    parser.add_argument("--sample-rate", type=int, default=1_024_000)
    parser.add_argument(
        "--storage",
        help="SQLite path for persistent events and endpoint inventory",
    )
    args = parser.parse_args()

    gateway = Gateway(
        gateway_id=f"rainpoint-{args.transport}",
        transport=args.transport,
        storage_path=args.storage,
    )
    if args.transport == "rtl433":
        transport = RTL433Transport(
            gateway,
            frequency=args.frequency,
            sample_rate=args.sample_rate,
        )
    else:
        transport = ReplayTransport(gateway, interval=args.interval)
    transport.seed()
    transport.start()
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
        transport.stop()
        gateway.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
