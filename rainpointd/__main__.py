"""Run the local RainPoint replay gateway."""

from __future__ import annotations

import argparse

from .gateway import Gateway
from .http import create_server
from .replay import ReplayTransport


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="seconds between replayed observations",
    )
    args = parser.parse_args()

    gateway = Gateway()
    replay = ReplayTransport(gateway, interval=args.interval)
    replay.seed()
    replay.start()
    server = create_server(gateway, args.host, args.port)
    print(
        f"rainpointd replay API listening on "
        f"http://{args.host}:{server.server_port}/api/v1"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        replay.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
