#!/usr/bin/env python3
"""Sign/verify an unpublished firmware descriptor; never provision keys or flash.

The private PEM is read from the signing step's environment, not CLI arguments.
Runtime OTA enforcement is separate; see docs/FIRMWARE_SIGNING_DESIGN.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

CONSTANTS = {
    "product": "rainpoint-radio-node", "board": "esp32dev",
    "hardware_profile": "esp32dev-cc1101-v1", "environment": "rainpoint_bridge",
    "firmware_variant": "unified", "channel": "experimental",
    "network_protocol_version": 2,
}
FIELDS = ("key_id", *CONSTANTS, "version", "source_commit", "release_id", "size_bytes", "sha256")
PATTERNS = {
    "key_id": r"[a-z0-9-]{1,32}",
    "version": r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?",
    "source_commit": r"[0-9a-f]{40}", "release_id": r"[a-z0-9.-]{1,96}",
    "sha256": r"[0-9a-f]{64}",
}
ALGORITHM = "ecdsa-p256-sha256"


def descriptor_bytes(value: dict) -> bytes:
    if not isinstance(value, dict) or set(value) != set(FIELDS):
        raise ValueError("unexpected descriptor fields")
    for field, literal in CONSTANTS.items():
        if type(value[field]) is not type(literal) or value[field] != literal:
            raise ValueError(f"incompatible {field}")
    for field, pattern in PATTERNS.items():
        item = value[field]
        if not isinstance(item, str) or not re.fullmatch(pattern, item, re.ASCII):
            raise ValueError(f"invalid {field}")
    if len(value["version"]) > 48:
        raise ValueError("version too long")
    size = value["size_bytes"]
    if type(size) is not int or not 65536 <= size <= 2 * 1024 * 1024:
        raise ValueError("invalid image size")
    data = ("rainpoint-firmware-signature-v1\n" + "".join(
        f"{key}={value[key]}\n" for key in FIELDS)).encode("ascii")
    if len(data) > 768:
        raise ValueError("descriptor too long")
    return data


def load_json(path: Path) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    if path.stat().st_size > 16384:
        raise ValueError("metadata too large")
    value = json.loads(path.read_text(encoding="ascii"), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("metadata must be an object")
    return value


def public_key(pem: bytes):
    key = serialization.load_pem_public_key(pem)
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("expected P-256 public key")
    return key


def verify(envelope: dict, trusted_keys: dict[str, bytes], image: bytes) -> None:
    if not isinstance(envelope, dict) or set(envelope) != {
            "descriptor", "signature_algorithm", "signature_der_hex"}:
        raise ValueError("unexpected signature envelope")
    data = descriptor_bytes(envelope["descriptor"])
    if envelope["signature_algorithm"] != ALGORITHM:
        raise ValueError("unsupported signature algorithm")
    encoded = envelope["signature_der_hex"]
    if not isinstance(encoded, str) or not re.fullmatch(r"[0-9a-f]{16,144}", encoded):
        raise ValueError("invalid signature encoding")
    signature = bytes.fromhex(encoded)
    # The library rejects malformed DER/trailing bytes; re-encoding also requires
    # the canonical integer representation rather than permissive BER.
    r, s = utils.decode_dss_signature(signature)
    if utils.encode_dss_signature(r, s) != signature:
        raise ValueError("noncanonical signature")
    descriptor = envelope["descriptor"]
    pem = trusted_keys.get(descriptor["key_id"])
    if pem is None:
        raise ValueError("unknown signing key")
    try:
        public_key(pem).verify(signature, data, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as error:
        raise ValueError("invalid publisher signature") from error
    if len(image) != descriptor["size_bytes"] or hashlib.sha256(image).hexdigest() != descriptor["sha256"]:
        raise ValueError("image differs from signed descriptor")


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
