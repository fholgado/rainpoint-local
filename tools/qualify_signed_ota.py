#!/usr/bin/env python3
"""Compile actual OTA code with real Mbed TLS and assert instrumented flash calls.

Requires a host build of Mbed TLS 2.28.7 (include/ and library/libmbedcrypto.a).
All signing keys are generated in memory for this temporary test only.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.test_firmware_signing import keys
from tools.sign_firmware import prepare, sign
from rainpointd.firmware_signatures import wire_signature


def qualify(mbedtls: Path):
    with tempfile.TemporaryDirectory(prefix="rainpoint-signed-ota-") as folder:
        root = Path(folder)
        private, public = keys()
        _, wrong_public = keys()
        image = b"\xe9" * 65536
        digest = hashlib.sha256(image).hexdigest()
        receipt = {"schema_version": 1, "source_dirty": False, "source_commit": "a" * 40,
                   "version": "0.19.0", "board": "esp32dev", "variant": "unified",
                   "environment": "rainpoint_bridge", "parts": [{"path": "firmware.bin",
                   "size_bytes": len(image), "sha256": digest}]}
        descriptor = prepare(image, receipt, expected_commit="a" * 40, key_id="temporary-test")
        envelope = sign(descriptor, private, public, image)
        command = {"type": "firmware_update_start", "command_id": "b" * 32,
                   "url": "https://127.0.0.1:8787/firmware/test.bin", "version": "0.19.0",
                   "sha256": digest, "size_bytes": len(image), **wire_signature(envelope)}
        header = '#pragma once\n#include "firmware_signature.h"\nnamespace rainpoint {\n'
        header += 'inline const std::array<FirmwareSigningKey,2> kFirmwareSigningKeys = {{{"temporary-test", R"KEY('
        header += public.decode() + ')KEY"}, {"wrong-test", R"KEY(' + wrong_public.decode() + ')KEY"}}};\n}\n'
        (root / "firmware_trust.h").write_text(header)
        binary = root / "signed-ota-test"
        subprocess.run(["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Wno-sign-compare",
            "-I" + str(ROOT / "tests/firmware_stubs"), "-I" + str(root),
            "-I" + str(ROOT / "firmware/rainpoint_bridge/include"),
            "-I" + str(ROOT / "firmware/rainpoint_bridge/src"), "-I" + str(mbedtls / "include"),
            str(ROOT / "firmware/rainpoint_bridge/tests/signed_ota_test.cpp"),
            str(ROOT / "firmware/rainpoint_bridge/src/ota_trial.cpp"),
            str(mbedtls / "library/libmbedcrypto.a"), "-o", str(binary)], check=True)
        def run(value, body=image):
            (root / "command.json").write_text(value if isinstance(value, str) else json.dumps(value))
            (root / "image.bin").write_bytes(body)
            return json.loads(subprocess.check_output([str(binary), str(root / "command.json"), str(root / "image.bin")]))
        result = run(command)
        assert result["success"] == result["begins"] == result["ends"] == result["pending"] == result["restart_pending"] == 1, result
        cases = [dict(command, signature_der_hex="00"), dict(command, signature_der_hex=command["signature_der_hex"] + "00"),
                 dict(command, version="0.19.1"), dict(command, sha256="c" * 64), dict(command, size_bytes=65537),
                 dict(command, extra="ignored"), {k: v for k, v in command.items() if k != "signature_der_hex"},
                 json.dumps(command)[:-1] + ',"size_bytes":65536}', json.dumps(command) + '{}',
                 dict(command, size_bytes=True), dict(command, signed_descriptor_hex="aa" * 769)]
        for key in descriptor:
            changed = copy.deepcopy(descriptor)
            changed[key] = changed[key] + 1 if type(changed[key]) is int else changed[key] + "x"
            # Encode exact altered bytes even where the strict Python builder rejects them.
            from rainpointd.firmware_signatures import FIELDS
            raw = "rainpoint-firmware-signature-v1\n" + ''.join(f'{field}={changed[field]}\n' for field in FIELDS)
            cases.append(dict(command, signed_descriptor_hex=raw.encode().hex()))
        for key_id in ("wrong-test", "unknown-test"):
            altered = dict(descriptor, key_id=key_id)
            # Sign with the original private key, but select a different trust anchor.
            forged = sign(altered, private, public, image)
            cases.append(dict(command, **wire_signature(forged)))
        for index, case in enumerate(cases):
            result = run(case)
            assert all(result[field] == 0 for field in ("success", "downloads", "begins", "writes", "ends", "pending", "restart_pending")), (index, result)
        result = run(command, b"x" + image[1:])
        assert result["begins"] == result["aborts"] == 1 and result["writes"] > 0, result
        assert all(result[field] == 0 for field in ("success", "ends", "pending", "restart_pending")), result
        print(f"PASS: real OTA/Mbed TLS valid vector, {len(cases)} pre-flash rejections and tampered-download abort")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mbedtls", type=Path)
    qualify(parser.parse_args().mbedtls)
