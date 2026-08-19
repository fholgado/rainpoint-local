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


class ValveSafetyControllerTest(unittest.TestCase):
    def controller(self, **overrides):
        settings = {
            "user_max_seconds": 1_800,
            "absolute_max_seconds": 3_600,
            "acknowledgement_timeout_seconds": 1.5,
            "close_retry_seconds": 1.5,
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


if __name__ == "__main__":
    unittest.main()
