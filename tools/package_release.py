#!/usr/bin/env python3
"""Build a deterministic source release and smoke-test its isolated gateway."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ROOTS = {"rainpointd_addon": "addons/rainpointd",
         "custom_components/rainpoint_local": "custom_components/rainpoint_local"}


def package(destination: Path) -> str:
    files = subprocess.check_output(["git", "ls-files", "-z", "--", *ROOTS], cwd=ROOT).split(b"\0")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for encoded in sorted(filter(None, files)):
            source = Path(encoded.decode())
            if not (ROOT / source).is_file():  # Deleted tracked files during review.
                continue
            root = next(root for root in ROOTS if source.is_relative_to(root))
            name = str(Path(ROOTS[root]) / source.relative_to(root))
            content = (ROOT / source).read_bytes()
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = 0o755 if source.suffix == ".sh" else 0o644
            archive.addfile(info, io.BytesIO(content))
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb", filename="", mtime=0) as stream:
        stream.write(buffer.getvalue())
    body = compressed.getvalue()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(body)
    return hashlib.sha256(body).hexdigest()


def smoke_test(artifact: Path) -> None:
    # This is a disposable installation artifact, never a development checkout.
    with tempfile.TemporaryDirectory(prefix="rainpoint-install-") as directory:
        with tarfile.open(artifact) as archive:
            archive.extractall(directory, filter="data")
        addon = Path(directory) / "addons/rainpointd"
        script = '''
import json, pathlib, sys, threading, urllib.request
sys.path.insert(0, sys.argv[1])
from rainpointd.gateway import Gateway
from rainpointd.http import create_server
from rainpointd.ingest import FrameIngestor
root=pathlib.Path(sys.argv[1])
assert not (root/'fixtures.json').exists()
assert not (root/'rainpointd/valve_control_bench.py').exists()
for _ in range(2):
    gateway=Gateway(storage_path=str(root/'smoke.sqlite3'),registry_token='test-only')
    FrameIngestor(gateway).seed()
    assert gateway.devices()==[] and gateway.registry()==[]
    server=create_server(gateway,port=0)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/api/v1/devices') as response:
            assert json.load(response)=={'devices':[]}
        assert not gateway.registry_authorized(None)
    finally:
        server.shutdown();server.server_close();thread.join();gateway.close()
'''
        subprocess.run([sys.executable, "-I", "-c", script, str(addon)], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    digest = package(args.output)
    if args.smoke_test:
        smoke_test(args.output)
    print(digest)


if __name__ == "__main__":
    main()
