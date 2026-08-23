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
        self.assertEqual(ActionKind.SEND_CLOSE, actions[0].kind)
        self.assertEqual("startup_recovery", actions[0].reason)
        self.assertEqual([1, 2, 3, 4], [action.zone for action in actions])
        controller.observe_valve(watering=False, now=0.4)
        self.assertEqual(SafetyState.IDLE, controller.state)
        return controller

    def test_startup_must_confirm_closed_before_open(self) -> None:
        controller = self.controller()
        controller.start(10)
        self.assertEqual(SafetyState.CLOSE_PENDING, controller.state)
        with self.assertRaisesRegex(RuntimeError, "cannot open"):
            controller.request_open(60, 10.1)
        controller.observe_valve(watering=False, now=10.4)
        self.assertEqual(SafetyState.IDLE, controller.state)

    def test_open_arms_watchdog_before_symbolic_action(self) -> None:
        controller = self.start_idle()
        actions = controller.request_open(240, 10, zone=3)
        self.assertEqual(SafetyState.OPEN_PENDING, controller.state)
        self.assertEqual(250, controller.run_deadline)
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

    def test_missing_open_acknowledgement_closes_without_open_retry(self) -> None:
        controller = self.start_idle()
        controller.request_open(60, 10)
        self.assertEqual((), controller.tick(11.49))
        actions = controller.tick(11.5)
        self.assertEqual(
            [ActionKind.SEND_CLOSE] * 4, [a.kind for a in actions]
        )
        self.assertEqual("open_acknowledgement_timeout", actions[0].reason)
        self.assertEqual(SafetyState.CLOSE_PENDING, controller.state)

    def test_close_waits_for_minimum_hardware_command_interval(self) -> None:
        controller = self.controller(minimum_command_interval_seconds=15)
        controller.start(0)
        controller.observe_valve(watering=False, now=0.4)
        with self.assertRaisesRegex(RuntimeError, "minimum valve command"):
            controller.request_open(60, 14.99)
        controller.request_open(60, 15, zone=2)
        controller.observe_valve(watering=True, now=15.4)

        self.assertEqual((), controller.request_close(20))
        self.assertEqual(SafetyState.CLOSE_PENDING, controller.state)
        self.assertEqual((), controller.tick(29.99))
        close = controller.tick(30)
        self.assertEqual([ActionKind.SEND_CLOSE] * 4, [a.kind for a in close])
        self.assertEqual("user_request", close[0].reason)
        self.assertEqual(1, close[0].attempt)

        self.assertEqual((), controller.tick(44.99))
        retry = controller.tick(45)
        self.assertEqual(2, retry[0].attempt)
        self.assertEqual("close_not_confirmed", retry[0].reason)

    def test_observed_watering_closes_at_hard_deadline(self) -> None:
        controller = self.start_idle()
        controller.request_open(60, 10)
        controller.observe_valve(watering=True, now=10.4)
        self.assertEqual(SafetyState.WATERING, controller.state)
        self.assertEqual((), controller.tick(69.99))
        actions = controller.tick(70)
        self.assertEqual(ActionKind.SEND_CLOSE, actions[0].kind)
        self.assertEqual("run_watchdog_expired", actions[0].reason)

    def test_client_loss_and_unexpected_watering_fail_closed(self) -> None:
        controller = self.start_idle()
        controller.request_open(60, 10)
        actions = controller.client_lost(10.2)
        self.assertEqual("controlling_client_lost", actions[0].reason)

        controller.observe_valve(watering=False, now=10.5)
        actions = controller.observe_valve(watering=True, now=20)
        self.assertEqual("unexpected_watering", actions[0].reason)
        self.assertEqual(SafetyState.CLOSE_PENDING, controller.state)

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

    def test_close_first_then_confirmed_open_and_close(self) -> None:
        session, sent = self.session()
        startup = session.start(0)
        self.assertEqual(
            [
                "valve_control_configure",
                "valve_control_sync",
                "valve_control_close",
            ],
            [command["type"] for command in startup],
        )
        self.assertEqual(7, startup[-1]["expected_sequence"])
        self.assertEqual(SafetyState.CLOSE_PENDING, session.state)
        session.observe_response(sequence=7, watering=False, now=0.4)
        self.assertEqual(SafetyState.IDLE, session.state)
        self.assertEqual(8, session.next_sequence)

        opened = session.request_open(60, 15)
        self.assertEqual("valve_control_open", opened[0]["type"])
        self.assertEqual(8, opened[0]["expected_sequence"])
        session.observe_response(sequence=8, watering=True, now=15.4)
        self.assertEqual(SafetyState.WATERING, session.state)

        self.assertEqual((), session.request_close(20))
        closed = session.tick(30)
        self.assertEqual("valve_control_close", closed[0]["type"])
        self.assertEqual(9, closed[0]["expected_sequence"])
        session.observe_response(sequence=9, watering=False, now=30.4)
        self.assertEqual(SafetyState.IDLE, session.state)
        self.assertEqual(10, session.next_sequence)
        self.assertEqual(len(sent), 5)

    def test_missing_open_response_uses_close_only_counter_recovery(self) -> None:
        session, _sent = self.session()
        session.start(0)
        session.observe_response(sequence=7, watering=False, now=0.4)
        session.request_open(60, 15)

        # The acknowledgement deadline starts the close path, but the
        # hardware interval prevents immediate chatter.
        self.assertEqual((), session.tick(16.5))
        first_recovery = session.tick(30)
        self.assertEqual(
            ["valve_control_sync", "valve_control_close"],
            [command["type"] for command in first_recovery],
        )
        self.assertEqual(9, first_recovery[0]["next_sequence"])
        self.assertEqual(9, first_recovery[1]["expected_sequence"])

        second_recovery = session.tick(45)
        self.assertEqual(
            ["valve_control_sync", "valve_control_close"],
            [command["type"] for command in second_recovery],
        )
        self.assertEqual(8, second_recovery[0]["next_sequence"])
        self.assertEqual(8, second_recovery[1]["expected_sequence"])
        with self.assertRaisesRegex(ValueError, "pending command"):
            session.observe_response(sequence=9, watering=False, now=45.4)
        session.observe_response(sequence=8, watering=False, now=45.4)
        self.assertEqual(SafetyState.IDLE, session.state)
        self.assertEqual(9, session.next_sequence)


if __name__ == "__main__":
    unittest.main()
