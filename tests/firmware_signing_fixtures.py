"""Ephemeral signing fixtures; private keys never leave the test process."""
from tools.sign_firmware import sign, CONSTANTS
from tests.test_firmware_signing import keys


def sign_release(release, content, private, public):
    descriptor = {"key_id": "test-only", **CONSTANTS, "source_commit": "a" * 40,
                  **{key: release[key] for key in ("version", "release_id", "size_bytes", "sha256")}}
    return sign(descriptor, private, public, content)
