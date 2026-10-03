"""Exercise the canary's actual receive/TX orchestration without hardware."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function(source, signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


class Htv213RuntimeTest(unittest.TestCase):
    def test_notification_handoff_restores_report_carrier_and_answers_settings(self):
        compiler = shutil.which("c++")
        if not compiler:
            self.skipTest("native compiler unavailable")
        runtime = (ROOT / "firmware/rainpoint_bridge/src/htv213_pairing_runtime.inc").read_text()
        driver = (ROOT / "firmware/rainpoint_bridge/src/cc1101.cpp").read_text()
        support = (ROOT / "firmware/rainpoint_bridge/tests/htv213_runtime_probe.cpp").read_text()
        methods = "\n".join(function(driver, f"bool Cc1101::{name}(") for name in
                            ("setChannel", "setReceiveFrequency", "restoreReceiveChannel"))
        orchestration = "\n".join(function(runtime, signature) for signature in
                                  ("void finishHtv213(", "void processHtv213(", "void pollHtv213("))
        source = support.replace("// ACTUAL_DRIVER_METHODS", methods).replace(
            "// ACTUAL_RUNTIME_FUNCTIONS", orchestration)
        with tempfile.TemporaryDirectory() as directory:
            exe = str(Path(directory) / "runtime")
            result = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                                     "-I" + str(ROOT / "firmware/rainpoint_bridge/include"),
                                     "-x", "c++", "-", "-o", exe], input=source,
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for mode in ("accepted", "timeout", "wrong-phase", "restore-failure"):
                with self.subTest(mode=mode):
                    result = subprocess.run([exe, mode], text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
