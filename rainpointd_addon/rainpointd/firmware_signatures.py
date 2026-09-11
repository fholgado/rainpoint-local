"""Strict publisher signature contract shared by release tooling and gateway."""
from __future__ import annotations

import hashlib
import json
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


def verify(envelope: dict, trusted_keys: dict[str, bytes], image: bytes | None = None) -> None:
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
    if image is not None and (len(image) != descriptor["size_bytes"] or hashlib.sha256(image).hexdigest() != descriptor["sha256"]):
        raise ValueError("image differs from signed descriptor")



def trusted_keys() -> dict[str, bytes]:
    """Only package-pinned public keys; never trust a key from an offer."""
    return {path.stem: path.read_bytes() for path in
            (Path(__file__).parent / "firmware_keys").glob("*.pem")}


def wire_signature(envelope: dict) -> dict[str, str]:
    return {"signed_descriptor_hex": descriptor_bytes(envelope["descriptor"]).hex(),
            "signature_der_hex": envelope["signature_der_hex"]}
