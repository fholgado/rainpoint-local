"""The phase trial is explicit, versioned and excluded from production images."""
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class PhaseTrialBuildTest(unittest.TestCase):
    def build_profile(self, settings):
        with tempfile.TemporaryDirectory() as directory:
            class Environment(dict):
                defines = []

                def subst(self, value):
                    return str(ROOT / "firmware/rainpoint_bridge") if value == "$PROJECT_DIR" else directory

                def Append(self, **kwargs):
                    self.defines = self.defines + kwargs.get("CPPDEFINES", [])

            env = Environment()
            with patch.dict(os.environ, settings, clear=True):
                runpy.run_path(str(ROOT / "firmware/rainpoint_bridge/tools/build_profile.py"),
                              init_globals={"env": env, "Import": lambda _: None})
            return env.defines

    def test_phase_commands_require_explicit_versioned_build(self):
        self.assertNotIn("RAINPOINT_VALVE_PHASE_EXPERIMENT", self.build_profile({}))
        settings = {"RAINPOINT_VALVE_PHASE_EXPERIMENT": "1",
                    "RAINPOINT_FIRMWARE_VERSION": "0.19.0-phase-trial.1"}
        self.assertIn("RAINPOINT_VALVE_PHASE_EXPERIMENT", self.build_profile(settings))
        for changed in ({"RAINPOINT_FIRMWARE_VERSION": "0.19.0"},
                        {"RAINPOINT_VALVE_PHASE_EXPERIMENT": "yes"},
                        {"RAINPOINT_HTV213_PAIRING_EXPERIMENT": "1"},
                        {"RAINPOINT_HTV213_CONTROL_EXPERIMENT": "1"}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.build_profile({**settings, **changed})

    def test_binary_checker_rejects_wrong_profile_and_missing_trial_commands(self):
        from tools import check_firmware_boundaries as boundary
        common = b"\0".join(boundary.REQUIRED_CAPABILITIES + boundary.VALVE_CONTROL_COMMANDS
                            + boundary.HTV145_PAIRING_CAPABILITIES + boundary.HTV145_CONTROL_COMMANDS)
        canary = common + b"\0-phase-trial.1\0" + b"\0".join(boundary.PHASE_TRIAL_COMMANDS)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "firmware.bin"
            for image, trial, expected in ((common, False, 0), (common, True, 1),
                                           (canary, False, 1), (canary, True, 0),
                                           (canary + b"htv145_dry_open_probe", True, 1)):
                with self.subTest(trial=trial, expected=expected):
                    path.write_bytes(image)
                    result = subprocess.run([sys.executable, str(ROOT / "tools/check_firmware_boundaries.py"),
                                             *(["--phase-trial"] if trial else []), str(path)],
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, expected, result.stdout + result.stderr)

    def test_retained_recovery_profile_builds_only_the_two_zone_candidate(self):
        settings = {'RAINPOINT_HTV213_PAIRING_EXPERIMENT': '1',
                    'RAINPOINT_HTV213_CONTROL_EXPERIMENT': '1',
                    'RAINPOINT_FIRMWARE_VERSION': '0.19.0-htv213-control.5'}
        defines = self.build_profile(settings)
        self.assertIn('RAINPOINT_HTV213_CONTROL_EXPERIMENT', defines)
        self.assertNotIn('RAINPOINT_VALVE_PHASE_EXPERIMENT', defines)
        with self.assertRaises(ValueError):
            self.build_profile({**settings, 'RAINPOINT_VALVE_PHASE_EXPERIMENT': '1'})

    def test_recovery_checker_rejects_production_and_cross_profile_leaks(self):
        from tools import check_firmware_boundaries as boundary
        common = b'\0'.join(boundary.REQUIRED_CAPABILITIES + boundary.VALVE_CONTROL_COMMANDS
                            + boundary.HTV145_PAIRING_CAPABILITIES + boundary.HTV145_CONTROL_COMMANDS)
        candidate = common + b'\0-htv213-control.5\0' + b'\0'.join(boundary.HTV213_RECOVERY_COMMANDS)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'firmware.bin'
            for image, option, expected in (
                    (candidate, '--htv213-recovery', 0), (candidate, '', 1),
                    (candidate, '--phase-trial', 1), (common, '--htv213-recovery', 1),
                    (candidate.replace(b'htv213_retained_rejoin_v1', b''), '--htv213-recovery', 1),
                    (candidate + b'valve_native_command', '--htv213-recovery', 1),
                    (candidate + b'htv145_dry_open_probe', '--htv213-recovery', 1)):
                with self.subTest(option=option, expected=expected):
                    path.write_bytes(image)
                    result = subprocess.run([sys.executable, str(ROOT / 'tools/check_firmware_boundaries.py'),
                                             *([option] if option else []), str(path)],
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
