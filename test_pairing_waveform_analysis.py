"""Tests for decoder-independent pairing waveform analysis helpers."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parent / "tools" / "analyze_pairing_waveform.py"
FIXTURE_PATH = (
    Path(__file__).parent
    / "research"
    / "fixtures"
    / "htv145_balanced_wake_phy_discriminator_20260901.json"
)
SPEC = importlib.util.spec_from_file_location("analyze_pairing_waveform", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PairingWaveformAnalysisTests(unittest.TestCase):
    def test_groups_short_fades_into_one_burst(self) -> None:
        groups = MODULE.group_active_indexes(
            [1, 2, 3, 6, 7, 20],
            maximum_gap_samples=2,
            minimum_active_samples=2,
        )
        self.assertEqual(
            [{"start_index": 1, "end_index": 7, "active_samples": 5}],
            groups,
        )

    def test_rejects_unsorted_active_indexes(self) -> None:
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            MODULE.group_active_indexes(
                [1, 3, 3],
                maximum_gap_samples=1,
                minimum_active_samples=1,
            )

    def test_normalizes_reply_against_device_request(self) -> None:
        comparison = MODULE.normalized_phy_comparison(
            reference_request_center_hz=433_146_300,
            reference_reply_center_hz=433_581_704,
            candidate_request_center_hz=433_142_134,
            candidate_reply_center_hz=433_541_676,
        )
        self.assertEqual(435_404, comparison["reference_reply_minus_request_hz"])
        self.assertEqual(399_542, comparison["candidate_reply_minus_request_hz"])
        self.assertEqual(-35_862, comparison["candidate_minus_reference_hz"])

    def test_maps_measured_deviation_to_cc1101_profile(self) -> None:
        local = MODULE.closest_deviation_register(34_666)
        stock = MODULE.closest_deviation_register(40_294)
        self.assertEqual("0x43", local["register_hex"])
        self.assertEqual("0x45", stock["register_hex"])
        self.assertAlmostEqual(34_912.109, local["expected_hz"], places=3)
        self.assertAlmostEqual(41_259.766, stock["expected_hz"], places=3)

    def test_deviation_register_bounds_are_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside"):
            MODULE.cc1101_deviation_hz(0x80)

    def test_probe_23_correction_is_derived_from_capture_fixture(self) -> None:
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        stock = fixture["accepted_stock"]
        local = fixture["rejected_local_probe_22"]
        comparison = MODULE.normalized_phy_comparison(
            reference_request_center_hz=stock["factory_request"][
                "channel_center_hz"
            ],
            reference_reply_center_hz=stock["assignment"][
                "channel_center_hz"
            ],
            candidate_request_center_hz=local["factory_request"][
                "channel_center_hz"
            ],
            candidate_reply_center_hz=local["assignment"][
                "channel_center_hz"
            ],
        )
        expected = fixture["normalized_comparison"]
        self.assertEqual(
            expected["local_minus_stock_hz"],
            comparison["candidate_minus_reference_hz"],
        )
        self.assertEqual(
            -expected["local_minus_stock_hz"],
            expected["probe_23_frequency_offset_hz"] - 87_389,
        )
        self.assertEqual(
            expected["probe_23_initial_deviation_register"],
            MODULE.closest_deviation_register(
                stock["assignment"]["deviation_hz"]
            )["register_hex"],
        )


if __name__ == "__main__":
    unittest.main()
