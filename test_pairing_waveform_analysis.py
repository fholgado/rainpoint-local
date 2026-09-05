"""Tests for decoder-independent pairing waveform analysis helpers."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from tools.generate_rainpoint_iq import command_symbols, generate_cu8
from tools.analyze_htv145_pairing_iq import terminal_exchange_evidence
from tools.analyze_htv145_control_iq import summarize_matches
from rainpointd.valve_protocol import ValveLink


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
    def test_partial_association_close_replies_are_errors_not_acceptance(self):
        fixture = json.loads((Path(__file__).parent / "research/fixtures/htv145_partial_pairing_control_replies_20260905.json").read_text())
        link = ValveLink(bytes.fromhex(fixture["identity"]["controller_endpoint"]),
                         bytes.fromhex(fixture["identity"]["valve_endpoint"]))
        for trial in fixture["trials"][1:]:
            response = trial["valid_valve_frames"][0]
            match = {"frame_hex": response["frame"], "phase_count": response["phase_count"],
                     "alternating_wake_symbols": [], "alternating_wake_symbol_histogram": {}}
            result = summarize_matches([match], link)
            self.assertEqual([], result["responses"])
            self.assertEqual({"sequence": trial["sequence"], "result_code": 3},
                             result["errors"][0]["decoded"])
            corrupt = {**match, "frame_hex": response["frame"][:-4] + "0000"}
            self.assertEqual([], summarize_matches([corrupt], link)["errors"])
            wrong_route = ValveLink(link.valve_endpoint, link.controller_endpoint)
            self.assertEqual([], summarize_matches([match], wrong_route)["errors"])

    def test_stock_terminal_exchange_is_required_not_assignment_or_retry(self):
        fixture = json.loads((Path(__file__).parent / "research/fixtures/htv145_counter2_stock_enrollment_20260901.json").read_text())
        exchange = fixture["exchanges"][-1]
        kwargs = {key: bytes.fromhex(fixture["association"][key])
                  for key in ("controller_endpoint", "paired_endpoint")}
        request = {"frame": exchange["request_frame"], "end_seconds": exchange["request_end_seconds"]}
        reply = {"frame": exchange["reply_frame"], "start_seconds": exchange["reply_start_seconds"]}
        self.assertEqual({"terminal_request_observed": True, "terminal_exchange_observed": True},
                         terminal_exchange_evidence([request], [reply], **kwargs))
        self.assertFalse(terminal_exchange_evidence([request], [], **kwargs)["terminal_exchange_observed"])
        self.assertFalse(terminal_exchange_evidence([request], [{**reply, "start_seconds": request["end_seconds"] + 1}], **kwargs)["terminal_exchange_observed"])
        retry = {**request, "frame": fixture["exchanges"][-2]["request_frame"]}
        self.assertFalse(terminal_exchange_evidence([retry], [reply], **kwargs)["terminal_request_observed"])
        corrupted = {**request, "frame": request["frame"][:-4] + "0000"}
        self.assertFalse(terminal_exchange_evidence([corrupted], [reply], **kwargs)["terminal_request_observed"])

    def test_control_analysis_distinguishes_stock_wake_and_unconfirmed_intent(self):
        fixture = json.loads((Path(__file__).parent / "research/fixtures/htv145_stock_control_shape_20260905.json").read_text())
        link = ValveLink(bytes.fromhex(fixture["identity"]["controller_endpoint"]),
                         bytes.fromhex(fixture["identity"]["valve_endpoint"]))
        for window in fixture["windows"]:
            matches = [{"frame_hex": c["frame"], "phase_count": c["phase_count"],
                        "alternating_wake_symbols": c["observed_wake_symbols"],
                        "alternating_wake_symbol_histogram": c["wake_symbol_histogram"]}
                       for c in window["commands"] + window["responses"]]
            result = summarize_matches(matches, link)
            command = result["commands"][0]
            dominant_wake = int(max(command["wake_symbol_histogram"], key=command["wake_symbol_histogram"].get))
            self.assertEqual(1200 if window["role"] == "local-open" else 2400, dominant_wake)
            self.assertEqual(0 if window["role"] == "local-open" else 1, len(result["responses"]))

    @unittest.skipUnless(
        MODULE.np is not None,
        "NumPy is an optional dependency used only for IQ analysis",
    )
    def test_classifies_a_low_tone_post_frame_tail(self) -> None:
        frame = bytes.fromhex(
            "79f4882f28b42d008fb9840280824085850086700098e1a10d"
            "01008000000000000000001133"
        )
        wake_symbols = 320
        symbols = command_symbols(
            frame, wake_symbols=wake_symbols, wake_first_bit=0
        ) + [0, 0, 0]
        sample_rate = 2_000_000
        symbol_rate = 20_000
        leading_ms = 5.0
        data = generate_cu8(
            symbols,
            sample_rate=sample_rate,
            capture_center_hz=433_700_000,
            channel_center_hz=433_580_000,
            symbol_rate=symbol_rate,
            deviation_hz=40_000,
            leading_silence_ms=leading_ms,
            trailing_silence_ms=5.0,
        )
        sync_start_sample = (
            round(sample_rate * leading_ms / 1_000)
            + wake_symbols * (sample_rate // symbol_rate)
        )
        with tempfile.NamedTemporaryFile(suffix=".cu8") as capture:
            capture.write(data)
            capture.flush()
            edge = MODULE.analyze_post_frame_edge(
                Path(capture.name),
                sample_rate=sample_rate,
                capture_center_hz=433_700_000,
                decision_center_hz=433_580_000,
                sync_start_sample=sync_start_sample,
            )
        self.assertEqual(150.0, edge["post_frame_active_us"])
        self.assertEqual("low", edge["post_frame_tone"])
        self.assertLess(edge["post_frame_relative_to_decision_hz"], 0)

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

    @unittest.skipUnless(
        MODULE.np is not None,
        "NumPy is an optional dependency used only for IQ analysis",
    )
    def test_reports_worst_case_wake_transition_timing(self) -> None:
        transitions = MODULE.np.asarray([100, 200, 300, 401, 502])
        timing = MODULE.transition_fit_statistics(transitions)
        self.assertEqual(100, timing["interval_min_samples"])
        self.assertEqual(101, timing["interval_max_samples"])
        self.assertGreater(timing["fit_max_abs_samples"], 0)
        self.assertGreaterEqual(
            timing["fit_max_abs_samples"], timing["fit_p99_abs_samples"]
        )

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
