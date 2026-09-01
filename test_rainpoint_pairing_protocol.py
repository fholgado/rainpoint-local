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
    AUTOMATIC_HTV145_PROFILE_ID,
    AUTOMATIC_HTV405_PROFILE_ID,
    automatic_htv145_profile_metadata,
    automatic_htv405_profile_metadata,
    build_htv145_profile,
    build_htv405_profile,
    frame_for_step,
    htv145_configuration_frame,
    request_matches,
)
from tools.demod_rainpoint_reply_iq import demodulate  # noqa: E402
from tools.analyze_htv405_pairing_iq import (  # noqa: E402
    DEFAULT_ASSIGNMENT_CENTER_HZ,
    DEFAULT_REQUEST_CENTER_HZ,
    DEFAULT_ROUTINE_CENTER_HZ,
    analyze_pairing_capture,
)
from tools.analyze_htv145_pairing_iq import (  # noqa: E402
    DEFAULT_ASSIGNMENT_CENTER_HZ as HTV145_ASSIGNMENT_CENTER_HZ,
    DEFAULT_REQUEST_CENTER_HZ as HTV145_REQUEST_CENTER_HZ,
    DEFAULT_RESPONSE_CENTER_HZ as HTV145_RESPONSE_CENTER_HZ,
    analyze as analyze_htv145_pairing_capture,
)
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
        self.assertEqual("sensor", profile["device_category"])
        self.assertTrue(profile["user_pairing_supported"])
        self.assertEqual(
            "sensor_pairing_tx", profile["required_node_capability"]
        )

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

    def test_htv405_iq_analyzer_correlates_assignment_acceptance(self) -> None:
        factory_request = bytes.fromhex(
            "79f4882f288000000014a9801300808402ff93130000bd8480"
            "00000000000000000000004795"
        )
        local_assignment = bytes.fromhex(
            "79f4882f2894a980133984028080c0858503027000cfa9970d"
            "01008000000000000000006942"
        )
        paired_request = bytes.fromhex(
            "79f4882f28b984028094a98013028107822580804f80000000"
            "40800056800000000000005127"
        )
        request_iq, _ = generate_command(
            factory_request,
            wake_symbols=320,
            channel_center_hz=DEFAULT_REQUEST_CENTER_HZ,
            leading_silence_ms=5,
            trailing_silence_ms=50,
        )
        assignment_iq, _ = generate_command(
            local_assignment,
            wake_symbols=320,
            channel_center_hz=DEFAULT_ASSIGNMENT_CENTER_HZ,
            leading_silence_ms=0,
            trailing_silence_ms=500,
        )
        paired_iq, _ = generate_command(
            paired_request,
            wake_symbols=320,
            channel_center_hz=DEFAULT_ROUTINE_CENTER_HZ,
            leading_silence_ms=0,
            trailing_silence_ms=5,
        )
        with tempfile.NamedTemporaryFile(suffix=".cu8") as capture:
            capture.write(request_iq + assignment_iq + paired_iq)
            capture.flush()
            result = analyze_pairing_capture(
                Path(capture.name),
                factory_endpoint=bytes.fromhex("14a98013"),
                paired_endpoint=bytes.fromhex("94a98013"),
                companion_endpoint=bytes.fromhex("39840280"),
                controller_endpoint=bytes.fromhex("b9840280"),
            )

        self.assertEqual(1, result["factory_request_count"])
        self.assertEqual(1, result["assignment_count"])
        self.assertEqual(1, len(result["trials"]))
        trial = result["trials"][0]
        self.assertEqual(50.0, trial["request_end_to_assignment_start_ms"])
        self.assertTrue(
            trial["paired_link_observed_before_next_factory_request"]
        )

    def test_htv145_iq_analyzer_keeps_request_and_response_legs_distinct(
        self,
    ) -> None:
        factory_request = bytes.fromhex(
            "79f4882f2880000000342d008f80808402ff8f970080bf060000"
            "000000000000000000007ccf"
        )
        assignment = bytes.fromhex(
            "79f4882f28b42d008f3984028080c0858503057000929e990d"
            "01008000000000000000005767"
        )
        stage_1_request = bytes.fromhex(
            "79f4882f28b9840280b42d008f810107822580804f8000000040"
            "800056800000000000000855"
        )
        configuration_response = bytes.fromhex(
            "79f4882f28b9840280b42d008f81d000800000000000000000"
            "00000000000000000000005dc8"
        )
        request_iq, _ = generate_command(
            factory_request,
            wake_symbols=320,
            channel_center_hz=HTV145_REQUEST_CENTER_HZ,
            leading_silence_ms=5,
            trailing_silence_ms=50,
        )
        assignment_iq, _ = generate_command(
            assignment,
            wake_symbols=320,
            channel_center_hz=HTV145_ASSIGNMENT_CENTER_HZ,
            leading_silence_ms=0,
            trailing_silence_ms=500,
        )
        stage_1_iq, _ = generate_command(
            stage_1_request,
            wake_symbols=320,
            channel_center_hz=HTV145_REQUEST_CENTER_HZ,
            leading_silence_ms=0,
            trailing_silence_ms=500,
        )
        configuration_iq, _ = generate_command(
            configuration_response,
            wake_symbols=320,
            channel_center_hz=HTV145_RESPONSE_CENTER_HZ,
            leading_silence_ms=0,
            trailing_silence_ms=5,
        )
        with tempfile.NamedTemporaryFile(suffix=".cu8") as capture:
            capture.write(
                request_iq + assignment_iq + stage_1_iq + configuration_iq
            )
            capture.flush()
            result = analyze_htv145_pairing_capture(
                Path(capture.name),
                factory_endpoint=bytes.fromhex("342d008f"),
                paired_endpoint=bytes.fromhex("b42d008f"),
                companion_endpoint=bytes.fromhex("39840280"),
                controller_endpoint=bytes.fromhex("b9840280"),
                origin_seconds=0,
                sample_rate=2_000_000,
                capture_center_hz=433_700_000,
                request_center_hz=HTV145_REQUEST_CENTER_HZ,
                assignment_center_hz=HTV145_ASSIGNMENT_CENTER_HZ,
                response_center_hz=HTV145_RESPONSE_CENTER_HZ,
            )

        self.assertEqual(1, result["request_count"])
        self.assertEqual(1, result["assignment_count"])
        self.assertEqual(1, result["lower_paired_request_count"])
        self.assertEqual(1, result["stage_1_request_count"])
        self.assertEqual(1, result["configuration_response_count"])
        trial = result["trials"][0]
        self.assertEqual(5, trial["assignment_selector"])
        self.assertEqual(0, trial["assignment_counter"])
        self.assertFalse(trial["assignment_to_controller_route"])
        self.assertTrue(trial["counter_echoed"])
        self.assertEqual(50.0, trial["request_end_to_assignment_start_ms"])
        self.assertTrue(trial["stage_1_observed"])

    def test_htv145_iq_analyzer_accepts_counter_3_selector_6_branch(
        self,
    ) -> None:
        factory_request = bytes.fromhex(
            "79f4882f2880000000342d008f83808402ff8f970080bf060000"
            "000000000000000000005bc2"
        )
        assignment = bytes.fromhex(
            "79f4882f28b42d008fb984028083c085850086f0008c741c0d"
            "02808000000000000000002de6"
        )
        stage_1_request = bytes.fromhex(
            "79f4882f28b9840280b42d008f84010786a580804f8000000040"
            "800056800000000000002546"
        )
        configuration_response = bytes.fromhex(
            "79f4882f28b9840280b42d008f815000800000000000000000"
            "00000000000000000000006f4d"
        )
        upper_response_center_hz = 434_461_993
        request_iq, _ = generate_command(
            factory_request,
            wake_symbols=320,
            channel_center_hz=HTV145_REQUEST_CENTER_HZ,
            leading_silence_ms=5,
            trailing_silence_ms=54,
        )
        assignment_iq, _ = generate_command(
            assignment,
            wake_symbols=320,
            channel_center_hz=HTV145_ASSIGNMENT_CENTER_HZ,
            leading_silence_ms=0,
            trailing_silence_ms=500,
        )
        stage_1_iq, _ = generate_command(
            stage_1_request,
            wake_symbols=320,
            channel_center_hz=HTV145_REQUEST_CENTER_HZ,
            leading_silence_ms=0,
            trailing_silence_ms=500,
        )
        configuration_iq, _ = generate_command(
            configuration_response,
            wake_symbols=320,
            channel_center_hz=upper_response_center_hz,
            leading_silence_ms=0,
            trailing_silence_ms=5,
        )
        with tempfile.NamedTemporaryFile(suffix=".cu8") as capture:
            capture.write(
                request_iq + assignment_iq + stage_1_iq + configuration_iq
            )
            capture.flush()
            result = analyze_htv145_pairing_capture(
                Path(capture.name),
                factory_endpoint=bytes.fromhex("342d008f"),
                paired_endpoint=bytes.fromhex("b42d008f"),
                companion_endpoint=bytes.fromhex("39840280"),
                controller_endpoint=bytes.fromhex("b9840280"),
                origin_seconds=0,
                sample_rate=2_000_000,
                capture_center_hz=433_700_000,
                request_center_hz=HTV145_REQUEST_CENTER_HZ,
                assignment_center_hz=HTV145_ASSIGNMENT_CENTER_HZ,
                response_center_hz=upper_response_center_hz,
            )

        self.assertEqual(1, result["request_count"])
        self.assertEqual(1, result["assignment_count"])
        self.assertEqual(1, result["stage_1_request_count"])
        self.assertEqual(1, result["configuration_response_count"])
        trial = result["trials"][0]
        self.assertEqual(3, trial["factory_sweep_counter"])
        self.assertEqual(3, trial["assignment_counter"])
        self.assertEqual(6, trial["assignment_selector"])
        self.assertTrue(trial["assignment_to_controller_route"])
        self.assertTrue(trial["counter_echoed"])
        self.assertTrue(trial["stage_1_observed"])
        self.assertEqual("accepted", trial["stage_0_verdict"])
        self.assertEqual("accepted", result["stage_0_verdict"])
        self.assertEqual(0, result["stage_0_failure_count"])

    def test_htv145_iq_analyzer_rejects_assignment_without_stage_1(
        self,
    ) -> None:
        factory_request = bytes.fromhex(
            "79f4882f2880000000342d008f80808402ff8f970080bf060000"
            "000000000000000000007ccf"
        )
        assignment = bytes.fromhex(
            "79f4882f28b42d008fb984028080c0858500867000f865210d"
            "010080000000000000000041c6"
        )
        factory_fallback = bytes.fromhex(
            "79f4882f2880000000342d008f83808402ff8f970080bf060000"
            "000000000000000000005bc2"
        )
        chunks = []
        for frame, trailing_silence_ms in (
            (factory_request, 54),
            (assignment, 500),
            (factory_fallback, 5),
        ):
            command, _ = generate_command(
                frame,
                wake_symbols=320,
                channel_center_hz=(
                    HTV145_ASSIGNMENT_CENTER_HZ
                    if frame == assignment
                    else HTV145_REQUEST_CENTER_HZ
                ),
                leading_silence_ms=5 if not chunks else 0,
                trailing_silence_ms=trailing_silence_ms,
            )
            chunks.append(command)

        with tempfile.NamedTemporaryFile(suffix=".cu8") as capture:
            capture.write(b"".join(chunks))
            capture.flush()
            result = analyze_htv145_pairing_capture(
                Path(capture.name),
                factory_endpoint=bytes.fromhex("342d008f"),
                paired_endpoint=bytes.fromhex("b42d008f"),
                companion_endpoint=bytes.fromhex("39840280"),
                controller_endpoint=bytes.fromhex("b9840280"),
                origin_seconds=0,
                sample_rate=2_000_000,
                capture_center_hz=433_700_000,
                request_center_hz=HTV145_REQUEST_CENTER_HZ,
                assignment_center_hz=HTV145_ASSIGNMENT_CENTER_HZ,
                response_center_hz=HTV145_RESPONSE_CENTER_HZ,
            )

        self.assertEqual(1, len(result["trials"]))
        self.assertEqual(0, result["stage_1_request_count"])
        self.assertEqual(
            "rejected_assignment_without_stage_1",
            result["stage_0_verdict"],
        )
        self.assertEqual(1, result["stage_0_failure_count"])

    def test_htv145_iq_analyzer_derives_counter_2_response_channel(
        self,
    ) -> None:
        upper_factory_request = bytes.fromhex(
            "79f4882f2880000000342d008f81008402ff8f970080bf060000"
            "000000000000000000002b41"
        )
        factory_request = bytes.fromhex(
            "79f4882f2880000000342d008f82008402ff8f970080bf060000"
            "000000000000000000000c4c"
        )
        assignment = bytes.fromhex(
            "79f4882f28b42d008fb9840280824085850086700098e1a10d"
            "01008000000000000000001133"
        )
        stage_1_request = bytes.fromhex(
            "79f4882f28b9840280b42d008f828107862580804f8000000040"
            "800056800000000000004301"
        )
        stage_1_reply = bytes.fromhex(
            "79f4882f28b42d008fb984028082c101000080000000000000"
            "00000000000000000000004ca5"
        )
        configuration_response = bytes.fromhex(
            "79f4882f28b9840280b42d008f815000800000000000000000"
            "00000000000000000000006f4d"
        )
        assigned_response_center_hz = 434_351_500
        chunks = []
        for frame, center, wake_symbols, trailing_silence_ms in (
            (
                upper_factory_request,
                434_306_001,
                320,
                500,
            ),
            (factory_request, HTV145_REQUEST_CENTER_HZ, 320, 54),
            (assignment, HTV145_ASSIGNMENT_CENTER_HZ, 320, 500),
            (stage_1_request, HTV145_REQUEST_CENTER_HZ, 320, 50),
            (stage_1_reply, assigned_response_center_hz, 320, 500),
            (
                configuration_response,
                assigned_response_center_hz,
                320,
                5,
            ),
        ):
            command, _ = generate_command(
                frame,
                wake_symbols=wake_symbols,
                channel_center_hz=center,
                leading_silence_ms=5 if not chunks else 0,
                trailing_silence_ms=trailing_silence_ms,
            )
            chunks.append(command)

        with tempfile.NamedTemporaryFile(suffix=".cu8") as capture:
            capture.write(b"".join(chunks))
            capture.flush()
            result = analyze_htv145_pairing_capture(
                Path(capture.name),
                factory_endpoint=bytes.fromhex("342d008f"),
                paired_endpoint=bytes.fromhex("b42d008f"),
                companion_endpoint=bytes.fromhex("39840280"),
                controller_endpoint=bytes.fromhex("b9840280"),
                origin_seconds=0,
                sample_rate=2_000_000,
                capture_center_hz=433_700_000,
                request_center_hz=HTV145_REQUEST_CENTER_HZ,
                assignment_center_hz=HTV145_ASSIGNMENT_CENTER_HZ,
                response_center_hz=HTV145_RESPONSE_CENTER_HZ,
            )

        self.assertEqual(2, result["request_count"])
        self.assertEqual(
            [1, 2],
            [
                bytes.fromhex(request["frame"])[13] & 0x7F
                for request in result["factory_requests"]
            ],
        )
        self.assertEqual(
            [434_306_001, HTV145_REQUEST_CENTER_HZ],
            [request["center_hz"] for request in result["factory_requests"]],
        )
        self.assertEqual(1, result["assignment_count"])
        self.assertEqual(1, result["stage_1_request_count"])
        self.assertEqual(1, result["configuration_response_count"])
        self.assertEqual(
            [assigned_response_center_hz],
            result["assigned_response_centers_hz"],
        )
        trial = result["trials"][0]
        self.assertEqual(2, trial["factory_sweep_counter"])
        self.assertEqual(2, trial["assignment_counter"])
        self.assertEqual(6, trial["assignment_selector"])
        self.assertEqual(12, trial["assigned_response_channel"])
        self.assertEqual(
            assigned_response_center_hz,
            trial["assigned_response_center_hz"],
        )
        self.assertTrue(trial["stage_1_observed"])

    def test_htv145_iq_analyzer_accepts_app_first_counter_0_branch(
        self,
    ) -> None:
        factory_request = bytes.fromhex(
            "79f4882f2880000000342d008f80808402ff8f970080bf060000"
            "000000000000000000007ccf"
        )
        assignment = bytes.fromhex(
            "79f4882f28b42d008fb984028080c0858500867000f865210d"
            "010080000000000000000041c6"
        )
        stage_1_request = bytes.fromhex(
            "79f4882f28b9840280b42d008f810107862580804f800000004080005680"
            "0000000000005689"
        )
        stage_1_reply = bytes.fromhex(
            "79f4882f28b42d008fb98402808141010000800000000000000000000000"
            "000000000000592d"
        )
        configuration_response = bytes.fromhex(
            "79f4882f28b9840280b42d008f815000800000000000000000"
            "00000000000000000000006f4d"
        )
        assigned_response_center_hz = 434_351_500
        chunks = []
        for frame, center, trailing_silence_ms in (
            (factory_request, HTV145_REQUEST_CENTER_HZ, 54),
            (assignment, HTV145_ASSIGNMENT_CENTER_HZ, 500),
            (stage_1_request, HTV145_REQUEST_CENTER_HZ, 50),
            (stage_1_reply, assigned_response_center_hz, 500),
            (configuration_response, assigned_response_center_hz, 5),
        ):
            command, _ = generate_command(
                frame,
                wake_symbols=320,
                channel_center_hz=center,
                leading_silence_ms=5 if not chunks else 0,
                trailing_silence_ms=trailing_silence_ms,
            )
            chunks.append(command)

        with tempfile.NamedTemporaryFile(suffix=".cu8") as capture:
            capture.write(b"".join(chunks))
            capture.flush()
            result = analyze_htv145_pairing_capture(
                Path(capture.name),
                factory_endpoint=bytes.fromhex("342d008f"),
                paired_endpoint=bytes.fromhex("b42d008f"),
                companion_endpoint=bytes.fromhex("39840280"),
                controller_endpoint=bytes.fromhex("b9840280"),
                origin_seconds=0,
                sample_rate=2_000_000,
                capture_center_hz=433_700_000,
                request_center_hz=HTV145_REQUEST_CENTER_HZ,
                assignment_center_hz=HTV145_ASSIGNMENT_CENTER_HZ,
                response_center_hz=HTV145_RESPONSE_CENTER_HZ,
            )

        self.assertEqual(1, result["request_count"])
        self.assertEqual(1, result["assignment_count"])
        self.assertEqual(1, result["stage_1_request_count"])
        self.assertEqual(1, result["configuration_response_count"])
        self.assertEqual(
            [assigned_response_center_hz],
            result["assigned_response_centers_hz"],
        )
        trial = result["trials"][0]
        self.assertEqual(0, trial["factory_sweep_counter"])
        self.assertEqual(0, trial["assignment_counter"])
        self.assertEqual(6, trial["assignment_selector"])
        self.assertEqual(12, trial["assigned_response_channel"])
        self.assertTrue(trial["assignment_to_controller_route"])
        self.assertTrue(trial["counter_echoed"])
        self.assertTrue(trial["stage_1_observed"])

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
        self.assertEqual(
            channels["continuous_selector_2_initial_observed_hz"],
            channels["selector_2_candidate_initial_command_hz"]
            + channels["selector_2_measured_test_node_tx_error_hz"],
        )

    def test_candidate_uses_measured_stock_reply_cadence(self) -> None:
        timing = self.fixture["timing"]
        self.assertAlmostEqual(
            (timing["stock_reply_start_s"] - timing["factory_request_start_s"])
            * 1_000,
            timing["factory_request_start_to_reply_start_ms"],
            places=3,
        )
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
        self.assertAlmostEqual(4.2, timing["firmware_0_12_2_turnaround_gap_ms"])
        self.assertLess(
            abs(
                self.fixture["channels"]["firmware_0_12_2_observed_reply_hz"]
                - self.fixture["channels"]["initial_assignment_hz"]
            ),
            2_000,
        )
        self.assertAlmostEqual(1.1, timing["firmware_0_12_3_turnaround_gap_ms"])
        self.assertLess(
            abs(
                self.fixture["channels"]["firmware_0_12_3_observed_reply_hz"]
                - self.fixture["channels"]["initial_assignment_hz"]
            ),
            500,
        )
        observation = self.fixture["candidate_observations"]
        self.assertTrue(observation["firmware_0_12_3_reply_decoded"])
        self.assertFalse(observation["firmware_0_12_3_valve_accepted"])
        self.assertEqual(
            38,
            len(bytes.fromhex(observation["firmware_0_12_3_reply_frame"])),
        )
        self.assertAlmostEqual(0.8, timing["firmware_0_12_4_turnaround_gap_ms"])
        self.assertFalse(observation["firmware_0_12_4_valve_accepted"])
        self.assertEqual(49, profile.reply_delay_ms)

    def test_continuous_capture_preserves_selector_branches(self) -> None:
        assignments = self.fixture["successful_stock_assignments"]
        self.assertEqual([6, 2, 2], [item["selector"] for item in assignments])
        latest = bytes.fromhex(assignments[-1]["reply_frame"])
        residual = binascii.crc_hqx(latest[:-2], 0) ^ int.from_bytes(
            latest[-2:], "big"
        )
        self.assertEqual(0x4F03, residual)
        self.assertEqual(bytes.fromhex("027000e0ce920d010080"), latest[18:28])

    def test_initial_routine_acknowledgements_mirror_message_counter(self) -> None:
        for exchange in self.fixture["exchanges"][1:4]:
            with self.subTest(request_kind=exchange["request_kind"]):
                request = bytes.fromhex(exchange["request_frame"])
                reply = bytes.fromhex(exchange["reply_frame"])
                self.assertEqual(request[13] & 0x7F, reply[13] & 0x7F)
                self.assertEqual(0x41, reply[14] & 0x7F)
                self.assertEqual(0x01, reply[15])

    def test_runtime_profile_reconstructs_the_selector_2_association(self) -> None:
        profile = build_htv405_profile(
            factory_endpoint=self.fixture["factory_endpoint"],
            valve_route="b9840280",
            companion_endpoint=self.fixture["companion_endpoint"],
        )
        self.assertEqual(AUTOMATIC_HTV405_PROFILE_ID, profile.profile_id)
        self.assertEqual(self.fixture["paired_endpoint"], profile.paired_endpoint)
        for index, exchange in enumerate(self.fixture["exchanges"]):
            with self.subTest(index=index, kind=exchange["request_kind"]):
                captured_request = bytes.fromhex(exchange["request_frame"])
                request = bytearray(captured_request)
                if 1 <= index <= 5:
                    request[16] = 0x82
                elif 6 <= index <= 9:
                    request[16] = 0x02
                elif 10 <= index <= 13:
                    request[16] = 0x82
                if 1 <= index <= 13:
                    residual = binascii.crc_hqx(
                        captured_request[:-2], 0
                    ) ^ int.from_bytes(
                        captured_request[-2:], "big"
                    )
                    trailer = binascii.crc_hqx(request[:-2], 0) ^ residual
                    request[-2:] = trailer.to_bytes(2, "big")
                self.assertTrue(request_matches(profile, index, request))
                if exchange.get("reply_expected", True):
                    if index > 0:
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
        with self.assertRaisesRegex(ValueError, "does not match"):
            build_htv405_profile(
                factory_endpoint="14a98013",
                valve_route="c1234580",
                companion_endpoint="39840280",
            )
        metadata = automatic_htv405_profile_metadata()
        self.assertTrue(metadata["experimental"])
        self.assertTrue(metadata["transmit_enabled"])
        self.assertFalse(metadata["valve_control_enabled"])
        self.assertEqual("valve", metadata["device_category"])
        self.assertTrue(metadata["user_pairing_supported"])
        self.assertTrue(metadata["automatic_discovery"])
        self.assertEqual([], metadata["association_inputs_required"])
        self.assertEqual(
            "htv405_auto_identity_pairing",
            metadata["required_node_capability"],
        )
        self.assertEqual(
            "persistent_local_gateway", metadata["controller_identity_default"]
        )
        self.assertEqual(18, metadata["step_count"])

        htv145_metadata = automatic_htv145_profile_metadata()
        self.assertEqual("valve", htv145_metadata["device_category"])
        self.assertFalse(htv145_metadata["user_pairing_supported"])

    def test_htv145_probe_matches_both_captured_factory_sweep_frames(self) -> None:
        profile = build_htv145_profile(
            factory_endpoint="342d008f",
            valve_route="b9840280",
            companion_endpoint="39840280",
        )
        self.assertEqual(AUTOMATIC_HTV145_PROFILE_ID, profile.profile_id)
        self.assertEqual("b42d008f", profile.paired_endpoint)
        self.assertEqual(6, len(profile.steps))
        self.assertEqual(0x06, profile.steps[0].reply_body[5] & 0x7F)
        for captured in (
            "79f4882f2880000000342d008f80808402ff8f970080bf060000000000000000000000007ccf",
            "79f4882f2880000000342d008f83808402ff8f970080bf060000000000000000000000005bc2",
        ):
            self.assertTrue(request_matches(profile, 0, bytes.fromhex(captured)))
        cold_boot = bytearray.fromhex(
            "79f4882f2880000000342d008f80808402ff8f970080bf060000000000000000000000007ccf"
        )
        cold_boot[17] = 0x7F
        residual = binascii.crc_hqx(cold_boot[:-2], 0) ^ 0xC713
        cold_boot[-2:] = residual.to_bytes(2, "big")
        self.assertFalse(request_matches(profile, 0, cold_boot))
        assignment = frame_for_step(
            profile,
            0,
            local_clock=datetime(2026, 9, 1, 12, 43, 48),
        )
        self.assertEqual(
            "79f4882f28b42d008fb984028080c0858500867000f865210d"
            "010080000000000000000041c6",
            assignment.hex(),
        )
        self.assertEqual(
            "79f4882f28b42d008fb9840280811001010000000000000000"
            "00000000000000000000000655",
            htv145_configuration_frame(profile).hex(),
        )
        expected_replies = {
            1: (
                "79f4882f28b42d008fb9840280814101000080000000000000"
                "0000000000000000000000592d"
            ),
            3: (
                "79f4882f28b42d008fb984028081c287802c0105000f000000"
                "000000000000000000000076bc"
            ),
            4: (
                "79f4882f28b42d008fb9840280824300800000000000000000"
                "00000000000000000000007592"
            ),
            5: (
                "79f4882f28b42d008fb984028082ec81801900000000000000"
                "00000000000000000000007746"
            ),
        }
        for index, expected in expected_replies.items():
            self.assertEqual(expected, frame_for_step(profile, index).hex())
        metadata = automatic_htv145_profile_metadata()
        self.assertTrue(metadata["experimental"])
        self.assertFalse(metadata["valve_control_enabled"])
        self.assertEqual(6, metadata["step_count"])
        self.assertEqual(2_400, metadata["configuration_wake_symbols"])
        self.assertEqual("retained_association", metadata["controller_identity_default"])

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
        self.assertEqual(bytes.fromhex("9d97910d"), frame[21:25])
        residual = binascii.crc_hqx(frame[:-2], 0) ^ int.from_bytes(
            frame[-2:], "big"
        )
        self.assertEqual(0x4F03, residual)


if __name__ == "__main__":
    unittest.main()
