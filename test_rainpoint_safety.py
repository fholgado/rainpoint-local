#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "rainpointd_addon"))

from rainpointd.safety import (  # noqa: E402
    ActionKind,
    SafetyState,
    ValveSafetyController,
)
from rainpointd.valve_control_bench import (  # noqa: E402
    BenchValveControlProfile,
    BenchValveControlSession,
)


class ValveSafetyControllerTest(unittest.TestCase):
    def controller(self, **overrides):
        settings = {
            "user_max_seconds": 1_800,
            "absolute_max_seconds": 3_600,
            "acknowledgement_timeout_seconds": 1.5,
            "close_retry_seconds": 1.5,
            "minimum_command_interval_seconds": 0,
            "max_fast_close_attempts": 3,
            "fault_retry_seconds": 10,
            "zone_count": 4,
        }
        settings.update(overrides)
        return ValveSafetyController(**settings)

    def start_idle(self):
        controller = self.controller()
        actions = controller.start(0)
        self.assertEqual((), actions)
        self.assertEqual(SafetyState.IDLE, controller.state)
        return controller

    def test_startup_is_observation_only(self) -> None:
        controller = self.controller()
        self.assertEqual((), controller.start(10))
        self.assertEqual(SafetyState.IDLE, controller.state)
        self.assertEqual(
            ActionKind.SEND_OPEN,
            controller.request_open(60, 10.1)[0].kind,
        )

    def test_open_records_bounded_completion_before_symbolic_action(self) -> None:
        controller = self.start_idle()
        actions = controller.request_open(240, 10, zone=3)
        self.assertEqual(SafetyState.OPEN_PENDING, controller.state)
        self.assertEqual(250, controller.run_deadline)
        self.assertEqual(265, controller.completion_deadline)
        self.assertEqual(11.5, controller.acknowledgement_deadline)
        self.assertEqual(ActionKind.SEND_OPEN, actions[0].kind)
        self.assertEqual(240, actions[0].duration_seconds)
        self.assertEqual(3, actions[0].zone)
        with self.assertRaisesRegex(RuntimeError, "cannot open"):
            controller.request_open(60, 10.1, zone=2)
        with self.assertRaisesRegex(ValueError, "zone"):
            self.start_idle().request_open(60, 0, zone=5)
        with self.assertRaisesRegex(ValueError, "whole minute"):
            self.start_idle().request_open(61, 0)
        with self.assertRaisesRegex(ValueError, "safety limit"):
            self.start_idle().request_open(1_860, 0)

    def test_missing_open_acknowledgement_never_transmits_recovery(self) -> None:
        controller = self.start_idle()
        controller.request_open(60, 10)
        self.assertEqual((), controller.tick(11.49))
        actions = controller.tick(11.5)
        self.assertEqual([ActionKind.REPORT_FAULT], [a.kind for a in actions])
        self.assertEqual(
            "open_confirmation_missing_bounded_run", actions[0].reason
        )
        self.assertEqual(SafetyState.RUN_UNCONFIRMED, controller.state)
        self.assertEqual(70, controller.run_deadline)
        self.assertEqual(85, controller.completion_deadline)
        self.assertEqual((), controller.tick(84.99))
        completion = controller.tick(85)
        self.assertEqual([ActionKind.REPORT_FAULT], [a.kind for a in completion])
        self.assertEqual(
            "bounded_run_completion_unobserved", completion[0].reason
        )
        self.assertEqual(SafetyState.UNKNOWN, controller.state)

    def test_close_waits_for_minimum_hardware_command_interval(self) -> None:
        controller = self.controller(minimum_command_interval_seconds=15)
        controller.start(0)
        controller.request_open(60, 0, zone=2)
        controller.observe_valve(watering=True, now=0.4)

        self.assertEqual((), controller.request_close(5))
        self.assertEqual(SafetyState.CLOSE_PENDING, controller.state)
        self.assertEqual((), controller.tick(14.99))
        close = controller.tick(15)
        self.assertEqual([ActionKind.SEND_CLOSE] * 4, [a.kind for a in close])
        self.assertEqual("user_request", close[0].reason)
        self.assertEqual(1, close[0].attempt)

        self.assertEqual((), controller.tick(29.99))
        retry = controller.tick(30)
        self.assertEqual(2, retry[0].attempt)
        self.assertEqual("close_not_confirmed", retry[0].reason)

    def test_silence_at_completion_is_unknown_not_a_close(self) -> None:
        controller = self.start_idle()
        controller.request_open(60, 10)
        controller.observe_valve(watering=True, now=10.4)
        self.assertEqual(SafetyState.WATERING, controller.state)
        self.assertEqual((), controller.tick(84.99))
        actions = controller.tick(85)
        self.assertEqual(ActionKind.REPORT_FAULT, actions[0].kind)
        self.assertEqual("bounded_run_completion_unobserved", actions[0].reason)
        self.assertEqual(SafetyState.UNKNOWN, controller.state)

    def test_positive_overdue_report_triggers_anomaly_close(self) -> None:
        controller = self.start_idle()
        controller.request_open(60, 10)
        controller.observe_valve(watering=True, now=10.4)
        controller.tick(85)
        actions = controller.observe_valve(watering=True, now=85.1)
        self.assertEqual(ActionKind.SEND_CLOSE, actions[0].kind)
        self.assertEqual("overdue_watering_observed", actions[0].reason)

    def test_client_loss_and_context_free_watering_do_not_transmit(self) -> None:
        controller = self.start_idle()
        controller.request_open(60, 10)
        self.assertEqual((), controller.client_lost(10.2))
        self.assertEqual(SafetyState.OPEN_PENDING, controller.state)

        controller.observe_valve(watering=False, now=10.5)
        actions = controller.observe_valve(watering=True, now=20)
        self.assertEqual(ActionKind.REPORT_FAULT, actions[0].kind)
        self.assertEqual(
            "watering_observed_without_bounded_run_context", actions[0].reason
        )
        self.assertEqual(SafetyState.UNKNOWN, controller.state)

    def test_close_retries_faults_and_continues_slow_retries(self) -> None:
        controller = self.start_idle()
        controller.request_close(5)
        second = controller.tick(6.5)
        self.assertEqual(2, second[0].attempt)
        third = controller.tick(8.0)
        self.assertEqual(
            [ActionKind.SEND_CLOSE] * 4 + [ActionKind.REPORT_FAULT],
            [action.kind for action in third],
        )
        self.assertEqual(SafetyState.FAULT, controller.state)
        self.assertEqual((), controller.tick(17.99))
        fourth = controller.tick(18.0)
        self.assertEqual(ActionKind.SEND_CLOSE, fourth[0].kind)
        self.assertEqual(4, fourth[0].attempt)
        controller.observe_valve(watering=False, now=18.2)
        self.assertEqual(SafetyState.IDLE, controller.state)
        self.assertEqual(0, controller.close_attempts)


class BenchValveControlSessionTest(unittest.TestCase):
    def profile(self) -> BenchValveControlProfile:
        return BenchValveControlProfile(
            node_id="rp-001122334455",
            controller_endpoint="b9840280",
            valve_endpoint="94a98013",
            companion_endpoint="39840280",
            selector=0x05,
            frequency_offset_hz=97_154,
        )

    def session(self, *, enabled: bool = True):
        sent = []

        def sender(node_id, command):
            sent.append((node_id, command))

        return (
            BenchValveControlSession(
                enabled=enabled,
                profile=self.profile(),
                next_sequence=7,
                sender=sender,
            ),
            sent,
        )

    def test_disabled_by_default_and_not_connected_to_public_api(self) -> None:
        session, sent = self.session(enabled=False)
        with self.assertRaisesRegex(PermissionError, "disabled"):
            session.start(0)
        self.assertEqual([], sent)

    def test_observation_first_then_confirmed_open_and_close(self) -> None:
        session, sent = self.session()
        startup = session.start(0)
        self.assertEqual(
            [
                "valve_control_configure",
                "valve_control_sync",
            ],
            [command["type"] for command in startup],
        )
        self.assertEqual(SafetyState.IDLE, session.state)
        self.assertEqual(7, session.next_sequence)

        opened = session.request_open(60, 0)
        self.assertEqual("valve_control_open", opened[0]["type"])
        self.assertEqual(7, opened[0]["expected_sequence"])
        session.observe_response(sequence=7, watering=True, now=0.4)
        self.assertEqual(SafetyState.WATERING, session.state)

        self.assertEqual((), session.request_close(5))
        closed = session.tick(15)
        self.assertEqual("valve_control_close", closed[0]["type"])
        self.assertEqual(8, closed[0]["expected_sequence"])
        session.observe_response(sequence=8, watering=False, now=15.4)
        self.assertEqual(SafetyState.IDLE, session.state)
        self.assertEqual(9, session.next_sequence)
        self.assertEqual(len(sent), 4)

    def test_missing_open_response_blocks_without_counter_guessing(self) -> None:
        session, _sent = self.session()
        session.start(0)
        session.request_open(60, 0)

        self.assertEqual((), session.tick(1.5))
        self.assertFalse(session.counter_synchronized)
        self.assertEqual(
            "open_confirmation_missing_bounded_run", session.last_fault
        )
        self.assertEqual((), session.tick(75))
        with self.assertRaisesRegex(RuntimeError, "not synchronized"):
            session.request_close(80)
        with self.assertRaisesRegex(RuntimeError, "still pending"):
            session.request_open(60, 80)

        # A late authenticated response restores the exact counter without a
        # speculative sync or close transmission.
        session.observe_response(sequence=7, watering=False, now=80.4)
        self.assertTrue(session.counter_synchronized)
        self.assertEqual(SafetyState.IDLE, session.state)
        self.assertEqual(8, session.next_sequence)

    def test_overdue_telemetry_closes_only_with_synchronized_counter(self) -> None:
        session, _sent = self.session()
        session.start(0)
        session.request_open(60, 0)
        session.observe_response(sequence=7, watering=True, now=0.4)
        self.assertEqual((), session.tick(75))
        close = session.observe_telemetry(watering=True, now=75.1)
        self.assertEqual("valve_control_close", close[0]["type"])
        self.assertEqual(8, close[0]["expected_sequence"])

    def test_explicit_close_retry_reuses_exact_pending_counter(self) -> None:
        session, _sent = self.session()
        session.start(0)
        session.request_open(60, 0)
        session.observe_response(sequence=7, watering=True, now=0.4)
        session.request_close(15)
        retry = session.tick(30)
        self.assertEqual(
            ["valve_control_close"], [item["type"] for item in retry]
        )
        self.assertEqual(8, retry[0]["expected_sequence"])
        self.assertNotEqual("valve_control_sync", retry[0]["type"])


if __name__ == "__main__":
    unittest.main()
