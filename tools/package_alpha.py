#!/usr/bin/env python3
"""Prepare an unpublished, revision-bound alpha bundle; never flash or publish."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import zipfile

try:
    from .firmware_manifest import build_manifest, verify_manifest, VERSION
    from .package_release import package, smoke_test
    from .stage_firmware_release import stage_release
except ImportError:
    from firmware_manifest import build_manifest, verify_manifest, VERSION
    from package_release import package, smoke_test
    from stage_firmware_release import stage_release

ROOT = Path(__file__).resolve().parents[1]
OFFSETS = {"bootloader.bin": 0x1000, "partitions.bin": 0x8000,
           "boot_app0.bin": 0xE000, "firmware.bin": 0x10000}


def collect_firmware(build: Path, *, revision: str, version: str,
                     allow_dirty: bool = False) -> tuple[dict, dict[str, bytes]]:
    """Reject stale/mixed builds and layouts outside the one supported board."""
    receipt = json.loads((build / "release-input.json").read_text())
    if (receipt.get("schema_version") != 1 or receipt.get("board") != "esp32dev"
            or receipt.get("environment") != "rainpoint_bridge"
            or receipt.get("variant") != "unified"):
        raise ValueError("unsupported build receipt/profile")
    if receipt.get("source_commit") != revision:
        raise ValueError("build receipt is from a different commit; rebuild")
    if not isinstance(receipt.get("source_dirty"), bool):
        raise ValueError("build receipt must record source cleanliness")
    if receipt["source_dirty"] and not allow_dirty:
        raise ValueError("dirty-source build is not distributable")
    if not VERSION.fullmatch(version) or receipt.get("version") != version:
        raise ValueError("source and compiled firmware versions differ")
    parts = receipt.get("parts", [])
    if not isinstance(parts, list) or len(parts) != len(OFFSETS):
        raise ValueError("incomplete USB flash layout")
    files = {}
    for part in parts:
        name = part.get("path")
        if name not in OFFSETS or name in files or part.get("offset") != OFFSETS[name]:
            raise ValueError("unexpected USB flash file/offset")
        path = build / name
        if path.is_symlink():
            raise ValueError("symlinked flash input")
        data = path.read_bytes()
        if (not data or part.get("size_bytes") != len(data)
                or part.get("sha256") != hashlib.sha256(data).hexdigest()):
            raise ValueError("flash input does not match build receipt")
        files[name] = data
    ordered = sorted(OFFSETS, key=OFFSETS.get)
    for index, name in enumerate(ordered):
        end = OFFSETS[ordered[index + 1]] if index + 1 < len(ordered) else 4 * 1024 * 1024
        if OFFSETS[name] + len(files[name]) > end:
            raise ValueError("overlapping or oversized flash inputs")
    # Validate the actual partition table, not just upload addresses. Both OTA
    # slots must hold this image; boot_app0 initializes the OTA data partition.
    partitions = []
    table = files["partitions.bin"]
    for start in range(0, len(table) - 31, 32):
        magic, kind, subtype, offset, size = struct.unpack_from("<HBBII", table, start)
        if magic == 0x50AA:
            partitions.append((kind, subtype, offset, size))
    partition_end = 0x9000
    for _, _, offset, size in sorted(partitions, key=lambda p: p[2]):
        if size <= 0 or offset < partition_end or offset + size > 4 * 1024 * 1024:
            raise ValueError("overlapping or oversized partition table")
        partition_end = offset + size
    for subtype in (0x10, 0x11):
        slots = [p for p in partitions if p[:2] == (0, subtype)]
        if len(slots) != 1 or slots[0][3] < len(files["firmware.bin"]):
            raise ValueError("firmware does not fit both OTA partitions")
        if subtype == 0x10 and slots[0][2] != OFFSETS["firmware.bin"]:
            raise ValueError("application upload offset disagrees with partition table")
    if not any(p[:3] == (1, 0, OFFSETS["boot_app0.bin"])
               and p[3] >= len(files["boot_app0.bin"]) for p in partitions):
        raise ValueError("OTA initialization offset disagrees with partition table")
    if (files["firmware.bin"][0] != 0xE9 or files["bootloader.bin"][0] != 0xE9
            or version.encode() + b"\0" not in files["firmware.bin"]):
        raise ValueError("invalid ESP32 image or missing compiled version")
    return receipt, files


def write_archive(destination: Path, files: dict[str, bytes]) -> None:
    """Stable archive metadata; source/build identity is recorded inside."""
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in sorted(files.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, body)


def json_bytes(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def bundle(destination: Path, *, allow_dirty: bool = False) -> dict:
    if destination.exists():
        raise ValueError("output already exists; use a new artifact path")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT))
    if dirty and not allow_dirty:
        raise ValueError("commit source changes before preparing a distributable bundle")
    version = (ROOT / "firmware/rainpoint_bridge/version.txt").read_text().strip()
    build = ROOT / "firmware/rainpoint_bridge/.pio/build/rainpoint_bridge"
    receipt, images = collect_firmware(build, revision=revision, version=version,
                                      allow_dirty=allow_dirty)
    subprocess.run([sys.executable, str(ROOT / "tools/check_firmware_boundaries.py"),
                    "--supervised", "--htv145-pairing", "--htv145-control",
                    str(build / "firmware.bin")], check=True)
    manifest = build_manifest(build / "firmware.bin", version=version, environment="rainpoint_bridge")
    verify_manifest(build / "firmware.bin", manifest)
    gateway_version = re.search(r"^version: (\S+)$",
        (ROOT / "rainpointd_addon/config.yaml").read_text(), re.M).group(1)
    integration_version = json.loads((ROOT / "custom_components/rainpoint_local/manifest.json").read_text())["version"]
    # Short commit suffix avoids silently replacing a different binary with the
    # same semver in the immutable local firmware catalog.
    image_digest = hashlib.sha256(images["firmware.bin"]).hexdigest()
    release_id = f"unified-{version.lower()}-{revision[:8]}-{image_digest[:8]}"
    metadata = {"schema_version": 1, "status": "unpublished-alpha-candidate",
                "source_commit": revision, "source_dirty": dirty or receipt["source_dirty"],
                "gateway_version": gateway_version, "integration_version": integration_version,
                "firmware_version": version, "firmware_release_id": release_id,
                "security": "trusted LAN; unencrypted; SHA-256 is not a publisher signature"}
    files = {f"usb/{name}": body for name, body in images.items()}
    files["usb/build-receipt.json"] = json_bytes(receipt)
    files["usb/manifest.json"] = json_bytes({"name": "RainPoint Local", "version": version,
        "builds": [{"chipFamily": "ESP32", "parts": [
            {"path": p["path"], "offset": p["offset"]} for p in receipt["parts"]]}]})
    files["firmware-manifest.json"] = json_bytes(manifest)
    files["compatibility.json"] = json_bytes(metadata)
    for name in ("GETTING_STARTED.md", "SECURITY.md", "LICENSE", "NODE_ONBOARDING.md",
                 "PROJECT_ROADMAP.md", "firmware/rainpoint_bridge/README.md",
                 "rainpointd_addon/DOCS.md", "docs/ALPHA_BUNDLE.md"):
        files[name] = (ROOT / name).read_bytes()
    files["FLASH_AND_UPDATE.md"] = (ROOT / "docs/ALPHA_BUNDLE.md").read_bytes()
    with tempfile.TemporaryDirectory(prefix="rainpoint-alpha-") as temporary:
        staging = Path(temporary)
        archive = staging / "rainpoint-source.tar.gz"
        package(archive)
        smoke_test(archive)
        files[archive.name] = archive.read_bytes()
        stage_release(build / "firmware.bin", staging / "ota", release_id=release_id,
            version=version, summary=f"Unified {version} alpha candidate",
            notes="Sensors and both valve families. See bundled limitations and compatibility.json.",
            firmware_variant="unified")
        for item in (staging / "ota").iterdir():
            files[f"ota/{item.name}"] = item.read_bytes()
    files["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(body).hexdigest()}  {name}\n" for name, body in sorted(files.items())
    ).encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_archive(destination, files)
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--allow-dirty", action="store_true",
                        help="local verification only; marks the bundle as dirty")
    args = parser.parse_args()
    print(json.dumps(bundle(args.output, allow_dirty=args.allow_dirty), indent=2))


if __name__ == "__main__":
    main()
