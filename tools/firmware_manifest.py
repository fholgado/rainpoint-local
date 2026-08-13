#!/usr/bin/env python3
"""Build and verify deterministic RainPoint radio-node OTA manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
PRODUCTION_ENVIRONMENTS = frozenset({"esp32dev_single", "esp32dev_dual"})
VERSION = re.compile(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?\Z")


def build_manifest(
    artifact: Path,
    *,
    version: str,
    environment: str,
    allow_research: bool = False,
) -> dict[str, Any]:
    """Describe one immutable firmware artifact for later signed delivery."""
    if not VERSION.fullmatch(version):
        raise ValueError("version must be semantic-version compatible")
    if environment not in PRODUCTION_ENVIRONMENTS and not allow_research:
        raise ValueError("research firmware cannot enter a production manifest")
    content = artifact.read_bytes()
    if not content:
        raise ValueError("firmware artifact is empty")
    return {
        "schema_version": SCHEMA_VERSION,
        "product": "rainpoint-radio-node",
        "board": "esp32dev",
        "environment": environment,
        "version": version,
        "network_protocol_version": 2,
        "size_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "rollback": {
            "required": True,
            "confirmation": "authenticated_gateway_session",
            "maximum_unconfirmed_boots": 3,
        },
    }


def verify_manifest(artifact: Path, manifest: dict[str, Any]) -> None:
    """Reject incompatible, truncated, modified, or research artifacts."""
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported manifest schema")
    if manifest.get("product") != "rainpoint-radio-node":
        raise ValueError("manifest product mismatch")
    if manifest.get("environment") not in PRODUCTION_ENVIRONMENTS:
        raise ValueError("manifest is not a production firmware target")
    expected = build_manifest(
        artifact,
        version=str(manifest.get("version", "")),
        environment=str(manifest["environment"]),
    )
    for key in ("board", "size_bytes", "sha256", "network_protocol_version"):
        if manifest.get(key) != expected[key]:
            raise ValueError(f"firmware {key} mismatch")
    if manifest.get("rollback") != expected["rollback"]:
        raise ValueError("rollback policy mismatch")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--environment", default="esp32dev_single")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        verify_manifest(args.artifact, json.loads(args.manifest.read_text()))
        return 0
    if not args.version:
        parser.error("--version is required when creating a manifest")
    manifest = build_manifest(
        args.artifact,
        version=args.version,
        environment=args.environment,
    )
    args.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
