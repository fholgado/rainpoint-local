"""Regression tests for offline HCS026 pairing-profile comparison."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
MODULE_PATH = ROOT / "tools" / "analyze_pairing_profiles.py"
SPEC = importlib.util.spec_from_file_location("analyze_pairing_profiles", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PairingProfileAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = json.loads(
            (ROOT / "research/fixtures/hcs026_gateway_pairing_replies.json").read_text()
        )

    def test_sensor_a_is_not_endpoint_substitution(self) -> None:
        report = MODULE.analyze(self.payload)
        self.assertFalse(report["findings"]["identity_substitution_alone_is_safe"])
        self.assertEqual([18, 19], report["findings"]["semantic_difference_offsets"])
        self.assertTrue(
            report["findings"]["later_steps_match_after_identity_and_trailer"]
        )

    def test_sensor_a_profile_records_successful_local_validation(self) -> None:
        candidate = MODULE.sensor_a_candidate(self.payload)
        self.assertTrue(candidate["transmit_enabled"])
        self.assertTrue(candidate["gateway_selectable"])
        self.assertTrue(candidate["firmware_compiled"])
        self.assertEqual(433_471_484, candidate["initial_channel_hz"])
        self.assertEqual(434_021_457, candidate["followup_channel_hz"])
        self.assertEqual(5, candidate["first_enrollment_reply_count"])
        self.assertEqual(4, candidate["rejoin_reply_count"])

    def test_pairing_subchannel_is_assigned_then_echoed(self) -> None:
        findings = MODULE.analyze(self.payload)["findings"]
        self.assertTrue(findings["channel_assignment_echoes_match"])
        self.assertTrue(findings["channel_frequency_formula_matches"])
        assignments = {
            item["sequence"]: item
            for item in findings["channel_assignments"]
        }
        self.assertEqual(
            9,
            assignments["sensor_a_first_enrollment"]["assigned_channel"],
        )
        self.assertEqual(
            8,
            assignments["sensor_b_first_enrollment"]["assigned_channel"],
        )
        self.assertEqual(
            4,
            assignments[
                "sensor_b_local_enrollment_isolated_success_20260811"
            ]["assigned_channel"],
        )
        self.assertEqual(434_021_500, MODULE.expected_pairing_channel_hz(9))


if __name__ == "__main__":
    unittest.main()
