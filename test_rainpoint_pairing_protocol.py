#!/usr/bin/env python3

from __future__ import annotations

import binascii
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "rainpointd_addon"))

from rainpointd.pairing_protocol import (  # noqa: E402
    AUTOMATIC_HCS026_PROFILE_ID,
    SENSOR_A_CANDIDATE_PROFILE,
    VALIDATED_HCS026_PROFILE,
    PairingPlanController,
    PairingTrigger,
    automatic_hcs026_profile_metadata,
    pairing_profile,
    pairing_profile_for_factory,
)
from rainpointd.valve_pairing_protocol import (  # noqa: E402
    AUTOMATIC_HTV405_PROFILE_ID,
    automatic_htv405_profile_metadata,
    build_htv405_profile,
    frame_for_step,
    request_matches,
)
from tools.demod_rainpoint_reply_iq import demodulate  # noqa: E402
from tools.generate_rainpoint_iq import generate_command  # noqa: E402


class HCS026PairingProtocolTest(unittest.TestCase):
    def test_automatic_profile_is_model_level_public_contract(self) -> None:
        profile = automatic_hcs026_profile_metadata()
        self.assertEqual(AUTOMATIC_HCS026_PROFILE_ID, profile["profile_id"])
        self.assertEqual("HCS026FRF", profile["model"])
        self.assertIsNone(profile["factory_endpoint"])
        self.assertIsNone(profile["paired_endpoint"])
        self.assertTrue(profile["automatic_discovery"])
        self.assertTrue(profile["transmit_enabled"])

    def test_sensor_b_profile_matches_recovered_fixture(self) -> None:
        fixture = json.loads(
            (
                ROOT
                / "research/fixtures/hcs026_gateway_pairing_replies.json"
            ).read_text()
        )
        captured = next(
            item
            for item in fixture["sequences"]
            if item["name"] == "sensor_b_repeat_enrollment_20260811"
        )
        self.assertEqual(
            captured["frames"],
            [step.frame.hex() for step in VALIDATED_HCS026_PROFILE.steps],
        )
        self.assertEqual(
            433_471_500,
            VALIDATED_HCS026_PROFILE.steps[0].channel_center_hz,
        )
        self.assertEqual(
            [433_471_500] * 2,
            [
                step.channel_center_hz
                for step in VALIDATED_HCS026_PROFILE.steps[1:]
            ],
        )
        self.assertFalse(
            VALIDATED_HCS026_PROFILE.as_dict()["transmit_enabled"]
        )

    def test_rejects_uncaptured_sensor_profile(self) -> None:
        self.assertIs(
            VALIDATED_HCS026_PROFILE,
            pairing_profile("hcs026_15a98024_v1"),
        )
        self.assertIs(
            VALIDATED_HCS026_PROFILE,
            pairing_profile_for_factory("15A98024"),
        )
        with self.assertRaises(KeyError):
            pairing_profile("hcs026_unknown")
        self.assertIs(
            SENSOR_A_CANDIDATE_PROFILE,
            pairing_profile_for_factory("1bce0024"),
        )

    def test_sensor_a_candidate_combines_only_captured_branch_replies(self) -> None:
        fixture = json.loads(
            (
                ROOT
                / "research/fixtures/hcs026_gateway_pairing_replies.json"
            ).read_text()
        )
        captured = next(
            item
            for item in fixture["sequences"]
            if item["name"] == "sensor_a_first_enrollment"
        )
        rejoin = next(
            item
            for item in fixture["sequences"]
            if item["name"] == "sensor_a_rejoin"
        )
        self.assertEqual(
            captured["frames"][:3] + [rejoin["frames"][3]],
            [step.frame.hex() for step in SENSOR_A_CANDIDATE_PROFILE.steps],
        )
        self.assertEqual(
            [433_471_484] + [434_021_457] * 3,
            [
                step.channel_center_hz
                for step in SENSOR_A_CANDIDATE_PROFILE.steps
            ],
        )
        self.assertFalse(
            SENSOR_A_CANDIDATE_PROFILE.as_dict()["transmit_enabled"]
        )
        self.assertEqual(10, SENSOR_A_CANDIDATE_PROFILE.reply_delay_ms)
        self.assertFalse(SENSOR_A_CANDIDATE_PROFILE.complete_after_final_reply)

    def test_all_replies_round_trip_through_offline_waveform(self) -> None:
        for profile in (
            VALIDATED_HCS026_PROFILE,
            SENSOR_A_CANDIDATE_PROFILE,
        ):
            for step in profile.steps:
                with self.subTest(
                    profile=profile.profile_id,
                    trigger=step.trigger.value,
                ):
                    data, metadata = generate_command(
                        step.frame,
                        wake_symbols=step.wake_symbols,
                        symbol_rate=step.symbol_rate_sps,
                        channel_center_hz=step.channel_center_hz,
                    )
                    self.assertEqual(
                        31.2, step.as_dict()["waveform_duration_ms"]
                    )
                    self.assertEqual(41.2, metadata["waveform_duration_ms"])
                    with tempfile.NamedTemporaryFile(suffix=".cu8") as capture:
                        capture.write(data)
                        capture.flush()
                        recovered = demodulate(
                            Path(capture.name),
                            sample_rate=metadata["sample_rate_sps"],
                            capture_center_hz=metadata["capture_center_hz"],
                        )
                    self.assertEqual(
                        step.frame.hex(), recovered["matches"][0]["frame_hex"]
                    )

    def test_symbolic_plan_requires_each_observation_and_dispatch(self) -> None:
        controller = PairingPlanController(VALIDATED_HCS026_PROFILE)
        for index, step in enumerate(VALIDATED_HCS026_PROFILE.steps):
            action = controller.observe(step.trigger, now_ms=index * 1_000)
            self.assertEqual(step, action)
            self.assertEqual(step.trigger.value, controller.status()["pending_trigger"])
            self.assertTrue(
                controller.mark_dispatched(
                    step.trigger, now_ms=index * 1_000 + 100
                )
            )
        self.assertFalse(controller.complete)
        self.assertTrue(controller.replies_complete)
        self.assertEqual(
            "paired_message_3", controller.status()["next_trigger"]
        )
        self.assertIsNone(
            controller.observe(PairingTrigger.PAIRED_MESSAGE_2_SHORT, now_ms=3_000)
        )
        self.assertIsNone(
            controller.observe(PairingTrigger.PAIRED_MESSAGE_3, now_ms=4_000)
        )
        self.assertTrue(controller.complete)
        self.assertFalse(controller.failed)
        self.assertTrue(controller.status()["terminal_confirmed"])

    def test_duplicate_timeout_out_of_order_and_interruption_fail_safe(self) -> None:
        controller = PairingPlanController(VALIDATED_HCS026_PROFILE)
        first = PairingTrigger.FACTORY_ANNOUNCEMENT
        self.assertIsNotNone(controller.observe(first, now_ms=0))
        self.assertIsNone(controller.observe(first, now_ms=10))
        controller.tick(now_ms=251)
        self.assertTrue(controller.failed)

        out_of_order = PairingPlanController(VALIDATED_HCS026_PROFILE)
        self.assertIsNone(
            out_of_order.observe(PairingTrigger.PAIRED_MESSAGE_1, now_ms=0)
        )
        self.assertTrue(out_of_order.failed)

        interrupted = PairingPlanController(VALIDATED_HCS026_PROFILE)
        interrupted.interrupt()
        self.assertTrue(interrupted.failed)
        self.assertEqual("interrupted", interrupted.status()["failure_reason"])
        self.assertIsNone(interrupted.observe(first, now_ms=0))

    def test_all_replies_without_terminal_message_are_not_complete(self) -> None:
        controller = PairingPlanController(VALIDATED_HCS026_PROFILE)
        for index, step in enumerate(VALIDATED_HCS026_PROFILE.steps):
            self.assertIsNotNone(controller.observe(step.trigger, now_ms=index * 100))
            self.assertTrue(
                controller.mark_dispatched(step.trigger, now_ms=index * 100 + 50)
            )
        self.assertTrue(controller.replies_complete)
        self.assertFalse(controller.complete)
        self.assertFalse(controller.failed)

    def test_sensor_a_mixed_state_requires_terminal_after_fourth_reply(self) -> None:
        controller = PairingPlanController(SENSOR_A_CANDIDATE_PROFILE)
        for index, step in enumerate(SENSOR_A_CANDIDATE_PROFILE.steps):
            self.assertIsNotNone(
                controller.observe(step.trigger, now_ms=index * 100)
            )
            self.assertTrue(
                controller.mark_dispatched(
                    step.trigger, now_ms=index * 100 + 50
                )
            )
            self.assertFalse(controller.complete)
        self.assertIsNone(
            controller.observe(PairingTrigger.PAIRED_MESSAGE_3, now_ms=450)
        )
        self.assertTrue(controller.complete)
        self.assertTrue(controller.status()["terminal_confirmed"])


class HTV405PairingEvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(
            (ROOT / "research/fixtures/htv405_gateway_pairing_replies.json").read_text()
        )

    def test_fixture_is_a_complete_valid_exchange(self) -> None:
        self.assertEqual("HTV405FRF", self.fixture["model"])
        self.assertEqual(18, len(self.fixture["exchanges"]))
        for exchange in self.fixture["exchanges"]:
            directions = ["request_frame"]
            if "reply_frame" in exchange:
                directions.append("reply_frame")
            if "observed_followup_frame" in exchange:
                directions.append("observed_followup_frame")
            for direction in directions:
                with self.subTest(
                    request_kind=exchange["request_kind"], direction=direction
                ):
                    frame = bytes.fromhex(exchange[direction])
                    self.assertEqual(38, len(frame))
                    self.assertEqual(bytes.fromhex("79f4882f28"), frame[:5])
                    residual = binascii.crc_hqx(frame[:-2], 0) ^ int.from_bytes(
                        frame[-2:], "big"
                    )
                    self.assertIn(residual, (0xC713, 0x4F03))

    def test_factory_identity_is_promoted_to_paired_identity(self) -> None:
        factory = bytes.fromhex(self.fixture["factory_endpoint"])
        paired = bytes.fromhex(self.fixture["paired_endpoint"])
        self.assertEqual(bytes([factory[0] | 0x80]) + factory[1:], paired)

        initial = self.fixture["exchanges"][0]
        request = bytes.fromhex(initial["request_frame"])
        reply = bytes.fromhex(initial["reply_frame"])
        self.assertEqual(bytes.fromhex("80000000"), request[5:9])
        self.assertEqual(factory, request[9:13])
        self.assertEqual(paired, reply[5:9])
        self.assertEqual(
            bytes.fromhex(self.fixture["companion_endpoint"]), reply[9:13]
        )

    def test_assignment_and_routine_replies_use_distinct_rf_profiles(self) -> None:
        channels = self.fixture["channels"]
        exchanges = self.fixture["exchanges"]
        self.assertEqual(
            channels["initial_assignment_hz"], exchanges[0]["reply_channel_hz"]
        )
        self.assertTrue(
            all(
                exchange.get("reply_channel_hz") == channels["routine_reply_hz"]
                for exchange in exchanges[1:]
                if exchange.get("reply_expected", True)
            )
        )
        modulation = self.fixture["initial_assignment_modulation"]
        self.assertEqual(
            modulation["upper_tone_hz"] - modulation["lower_tone_hz"],
            modulation["tone_separation_hz"],
        )
        self.assertEqual(70_007, modulation["tone_separation_hz"])
        self.assertEqual(
            channels["initial_assignment_hz"],
            channels["corrected_initial_requested_hz"]
            + channels["measured_test_node_tx_error_hz"],
        )
        self.assertEqual(
            channels["corrected_initial_requested_hz"],
            channels["candidate_initial_command_hz"]
            + channels["candidate_frequency_offset_hz"],
        )

    def test_candidate_uses_measured_stock_reply_cadence(self) -> None:
        timing = self.fixture["timing"]
        self.assertAlmostEqual(
            timing["factory_request_start_to_reply_start_ms"]
            - timing["request_waveform_ms"],
            timing["receive_complete_to_reply_start_ms"],
            places=3,
        )
        profile = build_htv405_profile(
            factory_endpoint=self.fixture["factory_endpoint"],
            valve_route="b9840280",
            companion_endpoint=self.fixture["companion_endpoint"],
        )
        self.assertEqual(timing["candidate_reply_delay_ms"], profile.reply_delay_ms)

    def test_initial_routine_acknowledgements_mirror_message_counter(self) -> None:
        for exchange in self.fixture["exchanges"][1:4]:
            with self.subTest(request_kind=exchange["request_kind"]):
                request = bytes.fromhex(exchange["request_frame"])
                reply = bytes.fromhex(exchange["reply_frame"])
                self.assertEqual(request[13] & 0x7F, reply[13] & 0x7F)
                self.assertEqual(0x41, reply[14] & 0x7F)
                self.assertEqual(0x01, reply[15])

    def test_runtime_profile_reconstructs_the_captured_association(self) -> None:
        profile = build_htv405_profile(
            factory_endpoint=self.fixture["factory_endpoint"],
            valve_route="b9840280",
            companion_endpoint=self.fixture["companion_endpoint"],
        )
        self.assertEqual(AUTOMATIC_HTV405_PROFILE_ID, profile.profile_id)
        self.assertEqual(self.fixture["paired_endpoint"], profile.paired_endpoint)
        for index, exchange in enumerate(self.fixture["exchanges"]):
            with self.subTest(index=index, kind=exchange["request_kind"]):
                request = bytes.fromhex(exchange["request_frame"])
                self.assertTrue(request_matches(profile, index, request))
                if exchange.get("reply_expected", True):
                    reply = bytes.fromhex(exchange["reply_frame"])
                    self.assertEqual(reply, frame_for_step(profile, index))
                else:
                    self.assertIsNone(frame_for_step(profile, index))

    def test_profile_requires_association_specific_identifiers(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTV405"):
            build_htv405_profile(
                factory_endpoint="14a98024",
                valve_route="b9840280",
                companion_endpoint="39840280",
            )
        with self.assertRaisesRegex(ValueError, "cannot be zero"):
            build_htv405_profile(
                factory_endpoint="14a98013",
                valve_route="00000000",
                companion_endpoint="39840280",
            )
        metadata = automatic_htv405_profile_metadata()
        self.assertTrue(metadata["experimental"])
        self.assertTrue(metadata["transmit_enabled"])
        self.assertFalse(metadata["valve_control_enabled"])
        self.assertEqual(18, metadata["step_count"])

    def test_valve_clock_keeps_the_captured_marker_bits(self) -> None:
        profile = build_htv405_profile(
            factory_endpoint="14a98013",
            valve_route="b9840280",
            companion_endpoint="39840280",
        )
        frame = frame_for_step(
            profile,
            0,
            local_clock=datetime(2026, 8, 17, 18, 56, 58),
        )
        self.assertEqual(bytes.fromhex("9d97118d"), frame[21:25])
        residual = binascii.crc_hqx(frame[:-2], 0) ^ int.from_bytes(
            frame[-2:], "big"
        )
        self.assertEqual(0xC713, residual)


if __name__ == "__main__":
    unittest.main()
