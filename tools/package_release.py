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
import json, os, pathlib, secrets, socket, subprocess, sys, time, urllib.request
sys.path.insert(0, sys.argv[1])
from rainpointd.secure_transport import client_context
root=pathlib.Path(sys.argv[1])
assert not (root/'fixtures.json').exists()
assert not (root/'rainpointd/valve_control_bench.py').exists()
token=secrets.token_urlsafe(32)
context=client_context(token)
identity=None
for _ in range(2):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0)); port=listener.getsockname()[1]
    launch="import runpy,sys;sys.path.insert(0,sys.argv.pop(1));runpy.run_module('rainpointd',run_name='__main__')"
    environment=dict(os.environ, RAINPOINT_REGISTRY_TOKEN=token)
    environment.pop('RAINPOINT_NODE_TOKENS',None)
    environment.pop('RAINPOINT_CLAIM_CODE',None)
    process=subprocess.Popen([sys.executable,'-I','-c',launch,str(root),
        '--transport','network','--host','127.0.0.1','--port',str(port),
        '--node-listen-port','0','--storage',str(root/'smoke.sqlite3')],
        env=environment,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        origin=f'https://127.0.0.1:{port}'
        for attempt in range(100):
            if process.poll() is not None:
                raise RuntimeError('packaged gateway failed to start: '+process.stderr.read().decode())
            try:
                with urllib.request.urlopen(origin+'/health',context=context,timeout=1) as response:
                    assert json.load(response)['status']=='ok'
                break
            except OSError:
                time.sleep(.05)
        else:
            raise RuntimeError('packaged TLS gateway did not become ready')
        for path,key in (('/api/v1/devices','devices'),('/api/v1/nodes','nodes')):
            with urllib.request.urlopen(origin+path,context=context,timeout=2) as response:
                assert json.load(response)[key]==[]
        with urllib.request.urlopen(origin+'/api/v1/info',context=context,timeout=2) as response:
            info=json.load(response)
        assert info['valve_control_enabled'] is True
        assert info['htv145_acceptance_enabled'] is False
        if identity is not None:
            assert info['rf_controller_identity']==identity
        identity=info['rf_controller_identity']
        for url,ctx in ((f'http://127.0.0.1:{port}/health',None),
                        (origin+'/health',client_context(secrets.token_urlsafe(32)))):
            try:
                urllib.request.urlopen(url,context=ctx,timeout=2)
            except OSError:
                pass
            else:
                raise AssertionError('plaintext or invalid credential accepted')
    finally:
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill();process.wait()
        process.stderr.close()
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
