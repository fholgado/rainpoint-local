"""Temporary-key publisher contract tests; no production private key fixtures."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
import yaml

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from tools.sign_firmware import descriptor_bytes, load_json, prepare, sign, verify
from tools.check_signing_environment import validate


def keys():
    key = ec.generate_private_key(ec.SECP256R1())
    return (key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()),
            key.public_key().public_bytes(serialization.Encoding.PEM,
                                          serialization.PublicFormat.SubjectPublicKeyInfo))


class SigningTest(unittest.TestCase):
    def setUp(self):
        self.private, self.public = keys()
        self.image = b"\xe9" * 65536
        self.receipt = {"schema_version": 1, "source_dirty": False, "source_commit": "a" * 40,
                        "version": "0.18.0", "board": "esp32dev", "variant": "unified",
                        "environment": "rainpoint_bridge", "parts": [{"path": "firmware.bin",
                        "size_bytes": len(self.image), "sha256": hashlib.sha256(self.image).hexdigest()}]}
        self.descriptor = prepare(self.image, self.receipt, expected_commit="a" * 40, key_id="test-only")
        self.envelope = sign(self.descriptor, self.private, self.public, self.image)

    def test_valid_signature_and_canonical_bytes(self):
        verify(self.envelope, {"test-only": self.public}, self.image)
        expected = ("rainpoint-firmware-signature-v1\nkey_id=test-only\n"
                    "product=rainpoint-radio-node\nboard=esp32dev\n"
                    "hardware_profile=esp32dev-cc1101-v1\nenvironment=rainpoint_bridge\n"
                    "firmware_variant=unified\nchannel=experimental\nnetwork_protocol_version=2\n"
                    "version=0.18.0\nsource_commit=" + "a" * 40 + "\nrelease_id=" +
                    self.descriptor["release_id"] + "\nsize_bytes=65536\nsha256=" +
                    hashlib.sha256(self.image).hexdigest() + "\n").encode()
        self.assertEqual(descriptor_bytes(self.descriptor), expected)

    def test_every_field_is_bound(self):
        for field, value in self.descriptor.items():
            with self.subTest(field=field), self.assertRaises(ValueError):
                changed = copy.deepcopy(self.envelope)
                changed["descriptor"][field] = value + 1 if type(value) is int else value + "x"
                verify(changed, {"test-only": self.public}, self.image)

    def test_wrong_unknown_and_mismatched_signing_keys(self):
        _, other = keys()
        for trusted in ({}, {"test-only": other}):
            with self.assertRaises(ValueError):
                verify(self.envelope, trusted, self.image)
        with self.assertRaises(ValueError):
            sign(self.descriptor, self.private, other, self.image)

    def test_bad_signature_and_image(self):
        for value in ("00", "00" * 73, self.envelope["signature_der_hex"] + "00", "zz"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                verify(dict(self.envelope, signature_der_hex=value), {"test-only": self.public}, self.image)
        for image in (self.image[:-1], b"x" + self.image[1:]):
            with self.assertRaises(ValueError):
                verify(self.envelope, {"test-only": self.public}, image)

    def test_strict_fields_and_envelope(self):
        for key, value in (("key_id", "test\nkey"), ("version", "1.2.3\r"), ("size_bytes", True),
                           ("size_bytes", 2**32), ("version", "１.2.3"), ("network_protocol_version", True)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                descriptor_bytes(dict(self.descriptor, **{key: value}))
        for envelope in ({}, dict(self.envelope, extra=True),
                         dict(self.envelope, signature_algorithm="none")):
            with self.assertRaises(ValueError):
                verify(envelope, {"test-only": self.public}, self.image)

    def test_receipt_is_bound_to_reviewed_commit(self):
        for receipt in (dict(self.receipt, source_dirty=True), dict(self.receipt, source_dirty=0),
                        dict(self.receipt, source_commit="b" * 40), dict(self.receipt, parts=[])):
            with self.assertRaises(ValueError):
                prepare(self.image, receipt, expected_commit="a" * 40, key_id="test-only")

    def test_duplicate_and_oversize_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "descriptor.json"
            for content in ('{"key_id":"a","key_id":"b"}', '[' + ' ' * 20000 + ']'):
                path.write_text(content)
                with self.assertRaises(ValueError):
                    load_json(path)

    def test_release_environment_fails_closed(self):
        environment = {"protection_rules": [{"type": "required_reviewers", "reviewers": [{"id": 1}]}],
                       "can_admins_bypass": False, "deployment_branch_policy": {
                       "protected_branches": False, "custom_branch_policies": True}}
        policies = {"branch_policies": [{"name": "main", "type": "branch"}]}
        validate(environment, policies, {"protected": True})
        for changed in ({}, dict(environment, protection_rules=[]),
                        dict(environment, can_admins_bypass=True),
                        dict(environment, deployment_branch_policy=None)):
            with self.assertRaises(ValueError):
                validate(changed, policies, {"protected": True})
        for changed in ({}, {"branch_policies": [{"name": "*", "type": "branch"}]},
                        {"branch_policies": [{"name": "main", "type": "tag"}]}):
            with self.assertRaises(ValueError):
                validate(environment, changed, {"protected": True})
        with self.assertRaises(ValueError):
            validate(environment, policies, {"protected": False})

    def test_workflow_separates_key_from_build_and_publication(self):
        workflow = yaml.load((Path(__file__).resolve().parents[1] /
                              ".github/workflows/sign-firmware.yml").read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow["on"]), {"workflow_dispatch"})
        self.assertEqual(workflow["permissions"]["contents"], "read")
        prepare_job, sign_job = workflow["jobs"]["prepare"], workflow["jobs"]["sign"]
        self.assertEqual(sign_job["environment"], "firmware-signing")
        self.assertEqual(sign_job["needs"], "prepare")
        self.assertNotIn("secrets.", str(prepare_job))
        secret_steps = [step for step in sign_job["steps"] if "secrets." in str(step)]
        self.assertEqual(len(secret_steps), 1)
        self.assertIn("sign_firmware.py sign", secret_steps[0]["run"])
        for job in workflow["jobs"].values():
            for step in job["steps"]:
                if "uses" in step:
                    self.assertRegex(step["uses"], r"@[0-9a-f]{40}$")

    def test_cli_sign_verify_and_refuse_replacement(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "firmware.bin").write_bytes(self.image)
            (root / "receipt.json").write_text(json.dumps(self.receipt))
            (root / "public.pem").write_bytes(self.public)
            script = Path(__file__).resolve().parents[1] / "tools/sign_firmware.py"
            arguments = ["--image", str(root / "firmware.bin"), "--public-key", str(root / "public.pem"),
                         "--key-id", "test-only", "--envelope", str(root / "signature.json")]
            environment = dict(os.environ, RAINPOINT_RELEASE_SIGNING_KEY_PEM=self.private.decode())
            command = [sys.executable, str(script), "sign", *arguments,
                       "--receipt", str(root / "receipt.json"), "--expected-commit", "a" * 40]
            signed = subprocess.run(command, env=environment, capture_output=True)
            self.assertEqual(signed.returncode, 0, signed.stderr.decode())
            self.assertNotIn(self.private, signed.stdout + signed.stderr)
            environment.pop("RAINPOINT_RELEASE_SIGNING_KEY_PEM")
            verified = subprocess.run([sys.executable, str(script), "verify", *arguments],
                                      env=environment, capture_output=True)
            self.assertEqual(verified.returncode, 0, verified.stderr.decode())
            before = (root / "signature.json").read_bytes()
            environment["RAINPOINT_RELEASE_SIGNING_KEY_PEM"] = self.private.decode()
            self.assertNotEqual(subprocess.run(command, env=environment, capture_output=True).returncode, 0)
            self.assertEqual((root / "signature.json").read_bytes(), before)
