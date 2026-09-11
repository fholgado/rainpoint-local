#!/usr/bin/env python3

from __future__ import annotations

import tempfile
import unittest
import subprocess
from pathlib import Path

from tools.firmware_manifest import build_manifest, verify_manifest


class FirmwareManifestTest(unittest.TestCase):
    def test_htv145_command_completion_restores_telemetry_base_frequency(self):
        # Compile the actual Arduino call-site body against a small radio fake.
        # Channel selection changes CHANNR, not the base FREQ registers. Hardware
        # acceptance still requires post-command reports from the assigned owner.
        source = (Path(__file__).resolve().parents[1] / "firmware/rainpoint_bridge/src/main.cpp").read_text()
        start = source.index("void restoreHtv145CandidateReceive() {")
        end = source.index("\nconst char* htv145CandidateFailureClass", start)
        function = source[start:end]
        harness = r'''
constexpr int kHcs026TelemetryChannel = 0;
struct Radio {
    int frequency = 434398811;
    bool setChannel(int) { return true; }
    bool restoreReceiveChannel(int) { frequency = 433031500; return true; }
} primaryRadio;
struct Candidate { bool listeningOnCommandCarrier = true; } htv145ControlCandidate;
Candidate& htv145Owner() { return htv145ControlCandidate; }
bool scanChannels = false;
void selectChannel(int channel) { primaryRadio.setChannel(channel); }
void reportHtv145CandidateStatus(const char*) {}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp = Path(directory) / "receive_restore.cpp"
            binary = Path(directory) / "receive_restore"
            cpp.write_text(harness + function + r'''
int main() {
    restoreHtv145CandidateReceive();
    return primaryRadio.frequency != 433031500 ||
        htv145ControlCandidate.listeningOnCommandCarrier || !scanChannels;
}
''')
            subprocess.run(["c++", "-std=c++17", str(cpp), "-o", str(binary)], check=True, capture_output=True)
            result = subprocess.run([str(binary)], capture_output=True)
            self.assertEqual(0, result.returncode, result.stderr.decode())

    def test_production_artifact_round_trip_and_tamper_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifact = Path(temporary_directory) / "firmware.bin"
            artifact.write_bytes(b"production firmware")
            manifest = build_manifest(
                artifact,
                version="0.7.0",
                environment="rainpoint_bridge",
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
                    environment="obsolete_pairing_candidate",
                )


if __name__ == "__main__":
    unittest.main()
