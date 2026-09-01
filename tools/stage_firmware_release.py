#!/usr/bin/env python3
"""Stage one immutable experimental radio-node release for rainpointd."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


MAXIMUM_CATALOG_RELEASES = 32
HARDWARE_PROFILE = "esp32dev-cc1101-v1"


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
    supersede_release_ids: list[str] | None = None,
) -> dict:
    """Copy an artifact and atomically replace its bounded catalog entry."""
    content = artifact.read_bytes()
    if not 64 * 1024 <= len(content) <= 2 * 1024 * 1024:
        raise ValueError("firmware artifact size is outside OTA limits")
    catalog_path = destination / "catalog.json"
    if catalog_path.exists():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    else:
        catalog = {"schema_version": 1, "releases": []}
    if (
        not isinstance(catalog, dict)
        or catalog.get("schema_version") != 1
        or not isinstance(catalog.get("releases"), list)
    ):
        raise ValueError("unsupported firmware catalog schema")
    raw_releases = catalog["releases"]
    superseded = set(supersede_release_ids or [])
    if release_id in superseded:
        raise ValueError("new release cannot supersede itself")
    known_release_ids = {
        str(item.get("release_id", ""))
        for item in raw_releases
        if isinstance(item, dict)
    }
    missing = sorted(superseded - known_release_ids)
    if missing:
        raise ValueError(
            "superseded firmware release is not present: " + ", ".join(missing)
        )
    for item in raw_releases:
        if not isinstance(item, dict) or item.get("release_id") not in superseded:
            continue
        if (
            item.get("firmware_variant") != firmware_variant
            or item.get("hardware_profile") != HARDWARE_PROFILE
            or item.get("channel") != "experimental"
        ):
            raise ValueError(
                "superseded release must share the new release boundary"
            )
    releases = [
        item
        for item in raw_releases
        if isinstance(item, dict)
        and item.get("release_id") != release_id
        and item.get("release_id") not in superseded
    ]
    if len(releases) + 1 > MAXIMUM_CATALOG_RELEASES:
        raise ValueError(
            "firmware catalog would exceed 32 releases; explicitly "
            "supersede an older release"
        )
    destination.mkdir(parents=True, exist_ok=True)
    filename = f"{release_id}.bin"
    staged = destination / filename
    temporary_artifact = destination / f".{filename}.tmp"
    temporary_artifact.write_bytes(content)
    temporary_artifact.replace(staged)
    release = {
        "release_id": release_id,
        "version": version,
        "channel": "experimental",
        "hardware_profile": HARDWARE_PROFILE,
        "firmware_variant": firmware_variant,
        "compatible_variants": compatible_variants or [firmware_variant],
        "required_capability": "firmware_update_trial",
        "artifact": filename,
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "release_summary": summary,
        "release_notes": notes,
        "release_url": release_url,
        "supersedes": sorted(superseded),
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
    parser.add_argument(
        "--supersede-release-id",
        action="append",
        dest="supersede_release_ids",
        help=(
            "existing same-variant experimental release to remove from the "
            "bounded catalog"
        ),
    )
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
        supersede_release_ids=args.supersede_release_ids,
    )
    print(json.dumps(release, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
