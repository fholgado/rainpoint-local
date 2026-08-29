#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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
from rainpointd.htv145_control import (  # noqa: E402
    Htv145ControlCoordinator,
    Htv145ControlProfile,
)
from rainpointd.htv145_acceptance import Htv145DryValveAcceptance  # noqa: E402
from rainpointd.htv405_control import (  # noqa: E402
    Htv405ControlCoordinator,
    Htv405ControlProfile,
)
from rainpointd.storage import SQLiteEventStore  # noqa: E402
from rainpointd.valve_protocol import (  # noqa: E402
    ValveLink,
    build_open_frame,
)
from tools.run_htv145_acceptance import _preflight  # noqa: E402


class Htv145AcceptanceRunnerPreflightTest(unittest.TestCase):
    LINK = ValveLink(
        bytes.fromhex("b42d008f"), bytes.fromhex("b9840280")
    )
    RESPONSE = (
        "79f4882f28b9840280b42d008f8150868010cf8702000040d80256d802"
        "000000000000004bfa"
    )
    IDLE = (
        "79f4882f28b9840280b42d008f9f8107858580804f938200004080005680"
        "0000000000002aff"
    )

    def events(self, *, battery_low: bool) -> list[dict]:
        now = datetime.now(timezone.utc)
        stock_at = now - timedelta(minutes=20)
        command = build_open_frame(self.LINK, 0x81, 1200, 0xC713)
        unconfirmed_local = build_open_frame(
            self.LINK, 0x82, 60, 0xC713
        )
        return [
            {
                "event_id": 1,
                "observed_at": stock_at.isoformat(),
                "raw": command.hex(),
                "state": {"rf_channel": 11},
            },
            {
                "event_id": 2,
                "observed_at": (stock_at + timedelta(seconds=2)).isoformat(),
                "raw": self.RESPONSE,
                "state": {"rf_channel": 11},
            },
            {
                "event_id": 3,
                "observed_at": (now - timedelta(minutes=11)).isoformat(),
                "raw": unconfirmed_local.hex(),
                "state": {"rf_channel": 11},
            },
            {
                "event_id": 4,
                "observed_at": (now - timedelta(minutes=1)).isoformat(),
                "raw": self.IDLE,
                "state": {"battery_low": battery_low, "rf_channel": 0},
            },
        ]

    def test_derives_channel_and_ignores_unconfirmed_local_command(self) -> None:
        result = _preflight(
            self.events(battery_low=False),
            link=self.LINK,
            isolation_seconds=600,
            maximum_command_age_seconds=86_400,
            maximum_idle_age_seconds=1_800,
        )
        self.assertEqual(11, result["command_rf_channel"])
        self.assertEqual(434_239_594, result["command_center_hz"])
        self.assertEqual(0x82, result["next_command_sequence"])

    def test_rejects_confirmed_low_battery(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "battery is confirmed low"):
            _preflight(
                self.events(battery_low=True),
                link=self.LINK,
                isolation_seconds=600,
                maximum_command_age_seconds=86_400,
                maximum_idle_age_seconds=1_800,
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
        self.assertEqual([ActionKind.SEND_CLOSE], [a.kind for a in close])
        self.assertEqual(2, close[0].zone)
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
        controller.request_close(5, zone=3)
        second = controller.tick(6.5)
        self.assertEqual(2, second[0].attempt)
        third = controller.tick(8.0)
        self.assertEqual(
            [ActionKind.SEND_CLOSE, ActionKind.REPORT_FAULT],
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

        opened = session.request_open(60, 0, zone=3)
        self.assertEqual("valve_control_open", opened[0]["type"])
        self.assertEqual(3, opened[0]["zone"])
        self.assertEqual(7, opened[0]["expected_sequence"])
        session.observe_response(sequence=7, zone=3, watering=True, now=0.4)
        self.assertEqual(SafetyState.WATERING, session.state)

        self.assertEqual((), session.request_close(5))
        closed = session.tick(15)
        self.assertEqual("valve_control_close", closed[0]["type"])
        self.assertEqual(8, closed[0]["expected_sequence"])
        session.observe_response(sequence=8, zone=3, watering=False, now=15.4)
        self.assertEqual(SafetyState.IDLE, session.state)
        self.assertEqual(9, session.next_sequence)
        self.assertEqual(len(sent), 4)

    def test_missing_open_response_blocks_without_counter_guessing(self) -> None:
        session, _sent = self.session()
        session.start(0)
        session.request_open(60, 0, zone=1)

        self.assertEqual((), session.tick(1.5))
        self.assertFalse(session.counter_synchronized)
        self.assertEqual(
            "open_confirmation_missing_bounded_run", session.last_fault
        )
        self.assertEqual((), session.tick(75))
        with self.assertRaisesRegex(RuntimeError, "not synchronized"):
            session.request_close(80)
        with self.assertRaisesRegex(RuntimeError, "still pending"):
            session.request_open(60, 80, zone=1)

        # A late authenticated response restores the exact counter without a
        # speculative sync or close transmission.
        session.observe_response(sequence=7, zone=1, watering=False, now=80.4)
        self.assertTrue(session.counter_synchronized)
        self.assertEqual(SafetyState.IDLE, session.state)
        self.assertEqual(8, session.next_sequence)

    def test_overdue_telemetry_closes_only_with_synchronized_counter(self) -> None:
        session, _sent = self.session()
        session.start(0)
        session.request_open(60, 0, zone=4)
        session.observe_response(sequence=7, zone=4, watering=True, now=0.4)
        self.assertEqual((), session.tick(75))
        close = session.observe_telemetry(watering=True, now=75.1)
        self.assertEqual("valve_control_close", close[0]["type"])
        self.assertEqual(8, close[0]["expected_sequence"])

    def test_explicit_close_retry_reuses_exact_pending_counter(self) -> None:
        session, _sent = self.session()
        session.start(0)
        session.request_open(60, 0, zone=2)
        session.observe_response(sequence=7, zone=2, watering=True, now=0.4)
        session.request_close(15)
        retry = session.tick(30)
        self.assertEqual(
            ["valve_control_close"], [item["type"] for item in retry]
        )
        self.assertEqual(8, retry[0]["expected_sequence"])
        self.assertNotEqual("valve_control_sync", retry[0]["type"])


class Htv405ControlCoordinatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = SQLiteEventStore(
            Path(self.temporary_directory.name) / "rainpoint.sqlite3"
        )
        self.profile = Htv405ControlProfile(
            node_id="rp-001122334455",
            controller_endpoint="b9840280",
            valve_endpoint="94a98013",
            companion_endpoint="39840280",
            selector=0x05,
            frequency_offset_hz=97_154,
        )
        self.store.upsert_valve_link(
            controller_endpoint=self.profile.controller_endpoint,
            valve_endpoint=self.profile.valve_endpoint,
            device_id="htv405-94a98013",
            name="Test valve",
            model="HTV405FRF",
            area=None,
            accepted_at="2026-08-24T20:00:00+00:00",
        )
        self.store.update_valve_control_profile(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            companion_endpoint=self.profile.companion_endpoint,
            selector=self.profile.selector,
            frequency_offset_hz=self.profile.frequency_offset_hz,
            observed_at="2026-08-24T20:00:01+00:00",
        )
        # This simulates a previously authenticated idle command response. It
        # is the only supported source of the next control counter.
        self.store.confirm_valve_control_response(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            sequence=6,
            next_sequence=6,
            zone=1,
            watering=False,
            center_hz=433_518_527,
            observed_at="2026-08-24T20:00:02+00:00",
            frame="00",
        )
        self.sent: list[tuple[str, dict]] = []
        self.coordinator = Htv405ControlCoordinator(
            store=self.store,
            sender=lambda node_id, command: self.sent.append(
                (node_id, command)
            ),
            enabled=True,
        )

    def tearDown(self) -> None:
        self.store.close()
        self.temporary_directory.cleanup()

    def test_reservation_is_durable_and_close_reuses_session_counter(self) -> None:
        pending = self.coordinator.request_open(
            self.profile,
            zone=4,
            duration_seconds=60,
            started_at="2026-08-24T20:00:20+00:00",
        )
        self.assertEqual("pending_authenticated_response", pending["state"])
        self.assertEqual(
            [
                "valve_control_configure",
                "valve_control_sync",
                "valve_control_open",
            ],
            [command["type"] for _node, command in self.sent],
        )
        self.assertEqual(
            1,
            len({command["command_id"] for _node, command in self.sent}),
            "the configure/sync/action transaction must share one audit id",
        )
        self.assertEqual(6, self.sent[-1][1]["expected_sequence"])
        with self.assertRaisesRegex(RuntimeError, "already pending"):
            self.coordinator.request_open(
                self.profile,
                zone=1,
                duration_seconds=60,
                started_at="2026-08-24T20:00:21+00:00",
            )

        self.store.confirm_valve_control_response(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            sequence=6,
            next_sequence=7,
            zone=4,
            watering=True,
            center_hz=433_518_527,
            observed_at="2026-08-24T20:00:21+00:00",
            frame="00",
            run_started_at="2026-08-24T20:00:20+00:00",
            run_duration_seconds=60,
            expected_idle_at="2026-08-24T20:01:20+00:00",
        )
        self.coordinator.request_close(
            self.profile,
            zone=4,
            started_at="2026-08-24T20:00:36+00:00",
        )
        self.assertEqual(7, self.sent[-1][1]["expected_sequence"])
        self.store.confirm_valve_control_response(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            sequence=7,
            next_sequence=7,
            zone=4,
            watering=False,
            center_hz=433_518_527,
            observed_at="2026-08-24T20:00:37+00:00",
            frame="00",
        )
        self.coordinator.request_open(
            self.profile,
            zone=2,
            duration_seconds=60,
            started_at="2026-08-24T20:00:52+00:00",
        )
        self.assertEqual(7, self.sent[-1][1]["expected_sequence"])

    def test_dispatch_failure_invalidates_counter_without_retry(self) -> None:
        coordinator = Htv405ControlCoordinator(
            store=self.store,
            sender=lambda _node, _command: (_ for _ in ()).throw(
                ConnectionError("offline")
            ),
            enabled=True,
        )
        with self.assertRaises(ConnectionError):
            coordinator.request_open(
                self.profile,
                zone=1,
                duration_seconds=60,
                started_at="2026-08-24T20:00:20+00:00",
            )
        state = self.store.valve_registry()[0]
        self.assertIsNone(state["control_next_sequence"])
        self.assertIsNone(state["control_pending_command_id"])

    def test_unvalidated_duration_is_never_reserved_or_transmitted(self) -> None:
        with self.assertRaisesRegex(ValueError, "not physically validated"):
            self.coordinator.request_open(
                self.profile,
                zone=1,
                duration_seconds=900,
                started_at="2026-08-24T20:00:20+00:00",
            )

        state = self.store.valve_registry()[0]
        self.assertEqual(6, state["control_next_sequence"])
        self.assertIsNone(state["control_pending_command_id"])
        self.assertEqual([], self.sent)

    def test_bounded_timeout_recovers_two_smallest_counter_candidates(self) -> None:
        first = self.coordinator.request_open(
            self.profile,
            zone=1,
            duration_seconds=60,
            started_at="2026-08-24T20:00:20+00:00",
        )
        failed = self.store.fail_htv405_command(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            command_id=first["command_id"],
            reason=(
                "gateway_command_response_timeout_counter_unsynchronized"
            ),
            observed_at="2026-08-24T20:00:22+00:00",
        )
        self.assertIsNone(failed["control_next_sequence"])
        self.assertEqual(6, failed["control_recovery_sequence"])
        self.assertEqual(1, failed["control_recovery_attempt"])
        self.assertEqual(
            "2026-08-24T20:01:35+00:00",
            failed["control_recovery_not_before"],
        )
        self.assertIsNone(
            self.store.recover_htv405_timeout_counter(
                valve_endpoint=self.profile.valve_endpoint,
                node_id=self.profile.node_id,
                observed_at="2026-08-24T20:01:34+00:00",
            )
        )
        recovered = self.store.recover_htv405_timeout_counter(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            observed_at="2026-08-24T20:01:35+00:00",
        )
        self.assertEqual(6, recovered["control_next_sequence"])

        second = self.coordinator.request_open(
            self.profile,
            zone=1,
            duration_seconds=60,
            started_at="2026-08-24T20:01:36+00:00",
        )
        failed_again = self.store.fail_htv405_command(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            command_id=second["command_id"],
            reason=(
                "gateway_command_response_timeout_counter_unsynchronized"
            ),
            observed_at="2026-08-24T20:01:38+00:00",
        )
        self.assertEqual(7, failed_again["control_recovery_sequence"])
        self.assertEqual(2, failed_again["control_recovery_attempt"])
        recovered_again = self.store.recover_htv405_timeout_counter(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            observed_at="2026-08-24T20:02:51+00:00",
        )
        self.assertEqual(7, recovered_again["control_next_sequence"])

        self.coordinator.request_open(
            self.profile,
            zone=1,
            duration_seconds=60,
            started_at="2026-08-24T20:02:52+00:00",
        )
        self.store.confirm_valve_control_response(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            sequence=7,
            next_sequence=8,
            zone=1,
            watering=True,
            center_hz=433_518_527,
            observed_at="2026-08-24T20:02:53+00:00",
            frame="00",
            run_started_at="2026-08-24T20:02:52+00:00",
            run_duration_seconds=60,
            expected_idle_at="2026-08-24T20:03:52+00:00",
        )
        state = self.store.valve_registry()[0]
        self.assertEqual(8, state["control_next_sequence"])
        self.assertIsNone(state["control_recovery_sequence"])
        self.assertEqual(0, state["control_recovery_attempt"])

    def test_explicit_rejection_uses_only_command_spacing_guard(self) -> None:
        pending = self.coordinator.request_open(
            self.profile,
            zone=1,
            duration_seconds=1_200,
            started_at="2026-08-24T20:00:20+00:00",
        )
        failed = self.store.fail_htv405_command(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            command_id=pending["command_id"],
            reason="gateway_command_rejected_counter_unsynchronized",
            observed_at="2026-08-24T20:00:22+00:00",
        )
        self.assertEqual(6, failed["control_recovery_sequence"])
        self.assertEqual(1, failed["control_recovery_attempt"])
        self.assertEqual(
            "2026-08-24T20:00:37+00:00",
            failed["control_recovery_not_before"],
        )
        self.assertIsNone(
            self.store.recover_htv405_timeout_counter(
                valve_endpoint=self.profile.valve_endpoint,
                node_id=self.profile.node_id,
                observed_at="2026-08-24T20:00:36+00:00",
            )
        )
        recovered = self.store.recover_htv405_timeout_counter(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            observed_at="2026-08-24T20:00:37+00:00",
        )
        self.assertEqual(6, recovered["control_next_sequence"])

    def test_automatic_idle_preserves_the_authenticated_next_counter(self) -> None:
        self.coordinator.request_open(
            self.profile,
            zone=3,
            duration_seconds=60,
            started_at="2026-08-24T20:00:20+00:00",
        )
        self.store.confirm_valve_control_response(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            sequence=6,
            next_sequence=7,
            zone=3,
            watering=True,
            center_hz=433_518_527,
            observed_at="2026-08-24T20:00:21+00:00",
            frame="00",
            run_started_at="2026-08-24T20:00:20+00:00",
            run_duration_seconds=60,
            expected_idle_at="2026-08-24T20:01:20+00:00",
        )
        idle = self.store.observe_htv405_state_report(
            valve_endpoint=self.profile.valve_endpoint,
            watering=False,
            zone=None,
            observed_at="2026-08-24T20:01:21+00:00",
        )
        self.assertFalse(idle["control_confirmed_watering"])
        self.assertEqual(7, idle["control_next_sequence"])
        self.assertEqual(
            "automatic_idle_confirmed_from_telemetry",
            idle["control_last_result"],
        )
        self.coordinator.request_open(
            self.profile,
            zone=1,
            duration_seconds=60,
            started_at="2026-08-24T20:01:36+00:00",
        )
        self.assertEqual(7, self.sent[-1][1]["expected_sequence"])

    def test_unexpected_watering_invalidates_the_controller_counter(self) -> None:
        state = self.store.observe_htv405_state_report(
            valve_endpoint=self.profile.valve_endpoint,
            watering=True,
            zone=2,
            observed_at="2026-08-24T20:00:20+00:00",
        )
        self.assertTrue(state["control_confirmed_watering"])
        self.assertEqual(2, state["control_active_zone"])
        self.assertIsNone(state["control_next_sequence"])
        self.assertEqual(
            "unexpected_watering_counter_unsynchronized",
            state["control_last_result"],
        )

    def test_unexpected_watering_cancels_bounded_timeout_recovery(self) -> None:
        first = self.coordinator.request_open(
            self.profile,
            zone=1,
            duration_seconds=60,
            started_at="2026-08-24T20:00:20+00:00",
        )
        failed = self.store.fail_htv405_command(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            command_id=first["command_id"],
            reason=(
                "gateway_command_response_timeout_counter_unsynchronized"
            ),
            observed_at="2026-08-24T20:00:22+00:00",
        )
        self.assertEqual(6, failed["control_recovery_sequence"])

        state = self.store.observe_htv405_state_report(
            valve_endpoint=self.profile.valve_endpoint,
            watering=True,
            zone=1,
            observed_at="2026-08-24T20:00:30+00:00",
        )
        self.assertTrue(state["control_confirmed_watering"])
        self.assertIsNone(state["control_recovery_sequence"])
        self.assertIsNone(state["control_next_sequence"])
        self.assertEqual(
            "unexpected_watering_counter_unsynchronized",
            state["control_last_result"],
        )


class Htv145ControlCoordinatorTest(unittest.TestCase):
    IDLE = bytes.fromhex(
        "79f4882f28b9840280b42d008f970107858b00804f998180004080005680"
        "00000000000049ef"
    )
    OPEN_RESPONSE = bytes.fromhex(
        "79f4882f28b9840280b42d008f8150868010cf8702000040d80256d802"
        "000000000000004bfa"
    )
    ACTIVE_REPORT = bytes.fromhex(
        "79f4882f28b9840280b42d008f9b810785898090cf9981800040a90156ac"
        "0100000000003431"
    )
    TERMINAL_IDLE = bytes.fromhex(
        "79f4882f28b9840280b42d008f908207858080d0e1930d08d18180002c01"
        "00000000000063b1"
    )

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = SQLiteEventStore(
            Path(self.temporary_directory.name) / "events.sqlite3"
        )
        self.sent = []
        self.profile = Htv145ControlProfile(
            node_id="rp-001122334455",
            controller_endpoint="b42d008f",
            valve_endpoint="b9840280",
            center_hz=433_920_000,
            power_dbm=10,
            invert=False,
            trailer_residual=0xC713,
        )

        def sender(node_id, command):
            self.sent.append((node_id, command))

        self.sender = sender
        self.coordinator = Htv145ControlCoordinator(
            store=self.store, sender=sender, enabled=True
        )
        self.coordinator.configure(
            self.profile, observed_at="2026-08-24T12:00:00+00:00"
        )
        self.coordinator.observe_frame(
            self.profile,
            self.IDLE,
            observed_at="2026-08-24T12:00:01+00:00",
        )
        passive = build_open_frame(
            self.profile.link, 0x80, 1_200, 0xC713
        )
        self.coordinator.synchronize_from_passive_command(
            self.profile,
            passive,
            observed_at="2026-08-24T12:00:02+00:00",
        )

    def tearDown(self) -> None:
        self.store.close()
        self.temporary_directory.cleanup()

    def test_disabled_by_default_sends_nothing(self) -> None:
        disabled = Htv145ControlCoordinator(
            store=self.store, sender=self.sender
        )
        with self.assertRaisesRegex(PermissionError, "disabled"):
            disabled.start(
                self.profile, observed_at="2026-08-24T12:00:03+00:00"
            )
        with self.assertRaisesRegex(PermissionError, "disabled"):
            disabled.request_open(
                self.profile,
                duration_seconds=60,
                started_at="2026-08-24T12:00:20+00:00",
            )
        self.assertEqual([], self.sent)

    def test_start_restores_configuration_without_actuating(self) -> None:
        commands = self.coordinator.start(
            self.profile, observed_at="2026-08-24T12:00:03+00:00"
        )
        self.assertEqual(
            ["htv145_control_configure", "htv145_control_sync"],
            [item["type"] for item in commands],
        )
        self.assertEqual(0x81, commands[1]["next_sequence"])
        self.assertFalse(
            any(item[1]["type"].endswith(("open", "close")) for item in self.sent)
        )

    def test_reservation_survives_restart_without_replay(self) -> None:
        self.coordinator.start(
            self.profile, observed_at="2026-08-24T12:00:03+00:00"
        )
        command = self.coordinator.request_open(
            self.profile,
            duration_seconds=1_200,
            started_at="2026-08-24T12:00:20+00:00",
        )
        self.assertEqual("htv145_control_open", command["type"])
        self.assertEqual(0x81, command["expected_sequence"])
        sent_count = len(self.sent)

        restarted = Htv145ControlCoordinator(
            store=self.store, sender=self.sender, enabled=True
        )
        with self.assertRaisesRegex(RuntimeError, "will not replay"):
            restarted.start(
                self.profile, observed_at="2026-08-24T12:00:21+00:00"
            )
        self.assertEqual(sent_count, len(self.sent))

        confirmed = restarted.observe_frame(
            self.profile,
            self.OPEN_RESPONSE,
            observed_at="2026-08-24T12:00:22+00:00",
        )
        self.assertEqual(0x82, confirmed["next_sequence"])
        self.assertTrue(confirmed["confirmed_watering"])
        self.assertEqual(
            "2026-08-24T12:20:20+00:00", confirmed["expected_idle_at"]
        )

    def test_independent_telemetry_confirms_without_counter_substitution(self) -> None:
        self.coordinator.start(
            self.profile, observed_at="2026-08-24T12:00:03+00:00"
        )
        self.coordinator.request_open(
            self.profile,
            duration_seconds=600,
            started_at="2026-08-24T12:00:20+00:00",
        )
        confirmed = self.coordinator.observe_frame(
            self.profile,
            self.ACTIVE_REPORT,
            observed_at="2026-08-24T12:00:27+00:00",
        )
        self.assertEqual(0x9B, self.ACTIVE_REPORT[13])
        self.assertEqual(0x82, confirmed["next_sequence"])
        self.assertEqual(
            "matching_independent_state_report",
            confirmed["counter_source"],
        )

    def test_dispatch_failure_unsynchronizes_and_does_not_retry(self) -> None:
        def failing_sender(_node_id, _command):
            raise ConnectionError("offline")

        coordinator = Htv145ControlCoordinator(
            store=self.store, sender=failing_sender, enabled=True
        )
        with self.assertRaises(ConnectionError):
            coordinator.request_open(
                self.profile,
                duration_seconds=600,
                started_at="2026-08-24T12:00:20+00:00",
            )
        state = self.store.htv145_control_states(
            self.profile.valve_endpoint
        )[0]
        self.assertFalse(state["counter_synchronized"])
        self.assertIsNone(state["pending_command_id"])
        self.assertEqual(
            "2026-08-24T12:10:20+00:00", state["expected_idle_at"]
        )
        with self.assertRaisesRegex(RuntimeError, "unsynchronized"):
            coordinator.request_open(
                self.profile,
                duration_seconds=600,
                started_at="2026-08-24T12:00:40+00:00",
            )

    def test_node_rejection_unsynchronizes_durable_reservation(self) -> None:
        command = self.coordinator.request_open(
            self.profile,
            duration_seconds=600,
            started_at="2026-08-24T12:00:20+00:00",
        )
        failed = self.coordinator.observe_candidate_status(
            self.profile,
            {
                "type": "command_error",
                "node_id": self.profile.node_id,
                "command_id": command["command_id"],
                "error": "invalid_htv145_control_open",
            },
            observed_at="2026-08-24T12:00:21+00:00",
        )
        self.assertIsNotNone(failed)
        self.assertFalse(failed["counter_synchronized"])
        self.assertIsNone(failed["pending_command_id"])
        self.assertIn("node_rejected", failed["last_result"])

    def test_candidate_failure_class_is_retained_in_durable_audit(self) -> None:
        command = self.coordinator.request_open(
            self.profile,
            duration_seconds=600,
            started_at="2026-08-24T12:00:20+00:00",
        )
        failed = self.coordinator.observe_candidate_status(
            self.profile,
            {
                "type": "htv145_control_candidate",
                "node_id": self.profile.node_id,
                "command_id": command["command_id"],
                "state": "confirmation_timeout_counter_unsynchronized",
                "failure_class": (
                    "state_confirmation_missed_after_no_immediate_response"
                ),
                "attempts_sent": 3,
                "matching_route_frames": 0,
            },
            observed_at="2026-08-24T12:00:35+00:00",
        )

        self.assertIsNotNone(failed)
        self.assertEqual(
            "confirmation_timeout_counter_unsynchronized:"
            "state_confirmation_missed_after_no_immediate_response",
            failed["last_result"],
        )
        self.assertFalse(failed["counter_synchronized"])

    def test_command_interval_and_single_pending_are_enforced(self) -> None:
        self.coordinator.request_open(
            self.profile,
            duration_seconds=1_200,
            started_at="2026-08-24T12:00:20+00:00",
        )
        with self.assertRaisesRegex(RuntimeError, "already pending"):
            self.coordinator.request_close(
                self.profile, started_at="2026-08-24T12:00:25+00:00"
            )
        self.coordinator.observe_frame(
            self.profile,
            self.OPEN_RESPONSE,
            observed_at="2026-08-24T12:00:26+00:00",
        )
        with self.assertRaisesRegex(RuntimeError, "15-second"):
            self.coordinator.request_close(
                self.profile, started_at="2026-08-24T12:00:30+00:00"
            )

    def test_dry_acceptance_requires_one_open_and_observed_automatic_idle(self) -> None:
        harness = Htv145DryValveAcceptance(
            coordinator=self.coordinator,
            profile=self.profile,
            enabled=True,
        )
        passive = build_open_frame(
            self.profile.link, 0x80, 1_200, 0xC713
        )
        harness.prepare(
            idle_frame=self.IDLE,
            passive_command_frame=passive,
            observed_at="2026-08-24T12:00:00+00:00",
        )
        command = harness.open_once(
            duration_seconds=600,
            started_at="2026-08-24T12:00:20+00:00",
        )
        with self.assertRaisesRegex(RuntimeError, "exactly one"):
            harness.open_once(
                duration_seconds=600,
                started_at="2026-08-24T12:00:40+00:00",
            )
        harness.observe_frame(
            self.OPEN_RESPONSE,
            observed_at="2026-08-24T12:00:22+00:00",
        )
        harness.observe_frame(
            self.IDLE,
            observed_at="2026-08-24T12:10:20+00:00",
        )
        report = harness.report(finished_at="2026-08-24T12:10:21+00:00")
        self.assertTrue(report["passed"])
        self.assertEqual(command["command_id"], report["command_id"])
        self.assertEqual(
            [
                "prepared",
                "open_dispatched",
                "open_confirmed",
                "automatic_idle_confirmed",
            ],
            [item["event"] for item in report["audit"]],
        )

    def test_terminal_summary_is_independent_automatic_idle_evidence(self) -> None:
        self.coordinator.request_open(
            self.profile,
            duration_seconds=600,
            started_at="2026-08-24T12:00:20+00:00",
        )
        self.coordinator.observe_frame(
            self.profile,
            self.OPEN_RESPONSE,
            observed_at="2026-08-24T12:00:22+00:00",
        )
        state = self.coordinator.observe_frame(
            self.profile,
            self.TERMINAL_IDLE,
            observed_at="2026-08-24T12:10:20+00:00",
        )
        self.assertFalse(state["confirmed_watering"])
        self.assertEqual(0x82, state["next_sequence"])

    def test_candidate_response_updates_the_acceptance_verdict(self) -> None:
        harness = Htv145DryValveAcceptance(
            coordinator=self.coordinator,
            profile=self.profile,
            enabled=True,
        )
        passive = build_open_frame(
            self.profile.link, 0x80, 1_200, 0xC713
        )
        harness.prepare(
            idle_frame=self.IDLE,
            passive_command_frame=passive,
            observed_at="2026-08-24T12:00:00+00:00",
        )
        command = harness.open_once(
            duration_seconds=600,
            started_at="2026-08-24T12:00:20+00:00",
        )
        harness.observe_candidate_status(
            {
                "type": "htv145_control_candidate",
                "node_id": self.profile.node_id,
                "state": "confirmed",
                "command_id": command["command_id"],
                "frame": self.OPEN_RESPONSE.hex(),
            },
            observed_at="2026-08-24T12:00:22+00:00",
        )
        report = harness.report(finished_at="2026-08-24T12:00:23+00:00")
        self.assertTrue(report["checks"]["open_confirmed_by_valve_evidence"])

    def test_dry_acceptance_is_disabled_and_dispatch_is_not_success(self) -> None:
        disabled = Htv145DryValveAcceptance(
            coordinator=self.coordinator,
            profile=self.profile,
        )
        with self.assertRaisesRegex(PermissionError, "disabled"):
            disabled.prepare(
                idle_frame=self.IDLE,
                passive_command_frame=build_open_frame(
                    self.profile.link, 0x80, 600, 0xC713
                ),
                observed_at="2026-08-24T12:00:00+00:00",
            )

        harness = Htv145DryValveAcceptance(
            coordinator=self.coordinator,
            profile=self.profile,
            enabled=True,
        )
        harness.prepare(
            idle_frame=self.IDLE,
            passive_command_frame=build_open_frame(
                self.profile.link, 0x80, 600, 0xC713
            ),
            observed_at="2026-08-24T12:00:00+00:00",
        )
        harness.open_once(
            duration_seconds=600,
            started_at="2026-08-24T12:00:20+00:00",
        )
        report = harness.report(finished_at="2026-08-24T12:00:21+00:00")
        self.assertFalse(report["passed"])
        self.assertFalse(report["checks"]["open_confirmed_by_valve_evidence"])


if __name__ == "__main__":
    unittest.main()
