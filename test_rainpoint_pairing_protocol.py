#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "rainpointd_addon"))

from rainpointd.pairing_protocol import (  # noqa: E402
    SENSOR_A_CANDIDATE_PROFILE,
    VALIDATED_HCS026_PROFILE,
    PairingPlanController,
    PairingTrigger,
    pairing_profile,
    pairing_profile_for_factory,
)
from tools.demod_rainpoint_reply_iq import demodulate  # noqa: E402
from tools.generate_rainpoint_iq import generate_command  # noqa: E402


class HCS026PairingProtocolTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
