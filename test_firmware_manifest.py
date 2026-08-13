#!/usr/bin/env python3

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.firmware_manifest import build_manifest, verify_manifest


class FirmwareManifestTest(unittest.TestCase):
    def test_production_artifact_round_trip_and_tamper_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifact = Path(temporary_directory) / "firmware.bin"
            artifact.write_bytes(b"production firmware")
            manifest = build_manifest(
                artifact,
                version="0.7.0",
                environment="esp32dev_single",
            )
            verify_manifest(artifact, manifest)
            artifact.write_bytes(b"modified firmware")
            with self.assertRaisesRegex(ValueError, "size_bytes|sha256"):
                verify_manifest(artifact, manifest)

    def test_research_target_is_rejected_for_production(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifact = Path(temporary_directory) / "firmware.bin"
            artifact.write_bytes(b"research firmware")
            with self.assertRaisesRegex(ValueError, "research firmware"):
                build_manifest(
                    artifact,
                    version="0.7.0-test.3",
                    environment="esp32dev_pairing_generalization",
                )


if __name__ == "__main__":
    unittest.main()
