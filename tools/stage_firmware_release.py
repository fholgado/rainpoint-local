#!/usr/bin/env python3
"""Stage one immutable experimental radio-node release for rainpointd."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def stage_release(
    artifact: Path,
    destination: Path,
    *,
    release_id: str,
    version: str,
    summary: str,
    notes: str,
    firmware_variant: str,
    compatible_variants: list[str] | None = None,
    release_url: str | None = None,
) -> dict:
    """Copy an artifact and atomically replace its catalog entry."""
    content = artifact.read_bytes()
    if not 64 * 1024 <= len(content) <= 2 * 1024 * 1024:
        raise ValueError("firmware artifact size is outside OTA limits")
    destination.mkdir(parents=True, exist_ok=True)
    filename = f"{release_id}.bin"
    staged = destination / filename
    temporary_artifact = destination / f".{filename}.tmp"
    temporary_artifact.write_bytes(content)
    temporary_artifact.replace(staged)
    catalog_path = destination / "catalog.json"
    if catalog_path.exists():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    else:
        catalog = {"schema_version": 1, "releases": []}
    releases = [
        item
        for item in catalog.get("releases", [])
        if item.get("release_id") != release_id
    ]
    release = {
        "release_id": release_id,
        "version": version,
        "channel": "experimental",
        "hardware_profile": "esp32dev-cc1101-v1",
        "firmware_variant": firmware_variant,
        "compatible_variants": compatible_variants or [firmware_variant],
        "required_capability": "firmware_update_trial",
        "artifact": filename,
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "release_summary": summary,
        "release_notes": notes,
        "release_url": release_url,
    }
    releases.append(release)
    catalog = {
        "schema_version": 1,
        "releases": sorted(releases, key=lambda item: item["release_id"]),
    }
    temporary_catalog = destination / ".catalog.json.tmp"
    temporary_catalog.write_text(
        json.dumps(catalog, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_catalog.replace(catalog_path)
    return release


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--notes", required=True)
    parser.add_argument("--firmware-variant", required=True)
    parser.add_argument(
        "--compatible-variant",
        action="append",
        dest="compatible_variants",
        help="source firmware variant that may install this release",
    )
    parser.add_argument("--release-url")
    args = parser.parse_args()
    release = stage_release(
        args.artifact,
        args.destination,
        release_id=args.release_id,
        version=args.version,
        summary=args.summary,
        notes=args.notes,
        firmware_variant=args.firmware_variant,
        compatible_variants=args.compatible_variants,
        release_url=args.release_url,
    )
    print(json.dumps(release, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
