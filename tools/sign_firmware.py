#!/usr/bin/env python3
"""Sign/verify an unpublished firmware descriptor; never provision keys or flash.

The private PEM is read from the signing step's environment, not CLI arguments.
Runtime OTA enforcement shares the strict contract below; see docs/FIRMWARE_SIGNING_DESIGN.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rainpointd_addon"))
from rainpointd.firmware_signatures import (
    CONSTANTS, ALGORITHM, descriptor_bytes, load_json, public_key, verify,
)


def sign(descriptor: dict, private_pem: bytes, trusted_public_pem: bytes, image: bytes) -> dict:
    data = descriptor_bytes(descriptor)
    key = serialization.load_pem_private_key(private_pem, password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("expected P-256 private key")
    if key.public_key().public_numbers() != public_key(trusted_public_pem).public_numbers():
        raise ValueError("signing key does not match pinned public key")
    envelope = {"descriptor": descriptor, "signature_algorithm": ALGORITHM,
                "signature_der_hex": key.sign(data, ec.ECDSA(hashes.SHA256())).hex()}
    verify(envelope, {descriptor["key_id"]: trusted_public_pem}, image)
    return envelope


def prepare(image: bytes, receipt: dict, *, expected_commit: str, key_id: str) -> dict:
    if (receipt.get("schema_version") != 1 or receipt.get("source_dirty") is not False
            or receipt.get("source_commit") != expected_commit
            or receipt.get("board") != "esp32dev" or receipt.get("variant") != "unified"
            or receipt.get("environment") != "rainpoint_bridge"):
        raise ValueError("untrusted or incompatible build receipt")
    digest = hashlib.sha256(image).hexdigest()
    parts = [p for p in receipt.get("parts", []) if p.get("path") == "firmware.bin"]
    if len(parts) != 1 or parts[0].get("sha256") != digest or parts[0].get("size_bytes") != len(image):
        raise ValueError("image differs from build receipt")
    version = receipt.get("version")
    value = {"key_id": key_id, **CONSTANTS, "version": version,
             "source_commit": expected_commit,
             "release_id": f"unified-{str(version).lower()}-{expected_commit[:8]}-{digest[:8]}",
             "size_bytes": len(image), "sha256": digest}
    descriptor_bytes(value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("sign", "verify"))
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--public-key", required=True, type=Path)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--envelope", required=True, type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--expected-commit")
    args = parser.parse_args()
    if args.image.stat().st_size > 2 * 1024 * 1024:
        parser.error("image too large")
    image = args.image.read_bytes()
    pem = args.public_key.read_bytes()
    if args.operation == "verify":
        verify(load_json(args.envelope), {args.key_id: pem}, image)
    else:
        if not args.receipt or not args.expected_commit:
            parser.error("signing requires a receipt and expected source commit")
        if pem + b"\0" not in image:
            parser.error("release image does not contain the pinned public key")
        private_pem = os.environ.pop("RAINPOINT_RELEASE_SIGNING_KEY_PEM", "")
        if not private_pem:
            parser.error("release signing secret is not configured")
        value = prepare(image, load_json(args.receipt), expected_commit=args.expected_commit, key_id=args.key_id)
        envelope = sign(value, private_pem.encode("ascii"), pem, image)
        # Exclusive creation: never silently replace a signed release descriptor.
        with args.envelope.open("x", encoding="ascii") as output:
            output.write(json.dumps(envelope, indent=2, sort_keys=True) + "\n")
    print("Firmware publisher signature verified; no publication or device changes")


if __name__ == "__main__":
    main()
