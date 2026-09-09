#!/usr/bin/env python3

from __future__ import annotations

import json
import binascii
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rainpointd_addon"))

from rainpointd.safety import (  # noqa: E402
    ActionKind,
    SafetyState,
    ValveSafetyController,
)
from research.valve_control_bench import (  # noqa: E402
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
from rainpointd.storage import (  # noqa: E402
    SQLiteEventStore,
    htv405_idle_close_sync_candidates,
)
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
    def test_idle_close_sync_uses_only_the_physically_validated_anchor(
        self,
    ) -> None:
        for last_sequence in range(32):
            self.assertEqual(
                (0,), htv405_idle_close_sync_candidates(last_sequence)
            )

    def test_idle_close_sync_normalizes_legacy_scan_candidate_to_anchor(
        self,
    ) -> None:
        pending = self.coordinator.request_open(
            self.profile,
            zone=1,
            duration_seconds=60,
            started_at="2026-08-24T20:00:20+00:00",
        )
        self.store.fail_htv405_command(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            command_id=pending["command_id"],
            reason="gateway_command_response_timeout_counter_unsynchronized",
            observed_at="2026-08-24T20:00:22+00:00",
        )
        self.store._connection.execute(
            """
            UPDATE valve_registry SET
                control_recovery_sequence = 7,
                control_recovery_attempt = 1,
                control_recovery_not_before = '2026-08-24T20:00:37+00:00',
                control_last_result = 'idle_close_probe_timeout_retry'
            WHERE valve_endpoint = ?
            """,
            (self.profile.valve_endpoint,),
        )
        self.store._connection.commit()
        self.sent.clear()

        normalized = self.coordinator.request_idle_close_probe(
            self.profile,
            zone=1,
            started_at="2026-08-24T20:00:37+00:00",
        )

        self.assertEqual(0, normalized["expected_sequence"])
        self.assertEqual(0, self.sent[-1][1]["expected_sequence"])

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

    def test_idle_close_probe_synchronizes_without_an_open_command(self) -> None:
        pending = self.coordinator.request_open(
            self.profile,
            zone=1,
            duration_seconds=60,
            started_at="2026-08-24T20:00:20+00:00",
        )
        self.store.fail_htv405_command(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            command_id=pending["command_id"],
            reason="gateway_command_response_timeout_counter_unsynchronized",
            observed_at="2026-08-24T20:00:22+00:00",
        )
        self.sent.clear()

        probe = self.coordinator.request_idle_close_probe(
            self.profile,
            zone=1,
            started_at="2026-08-24T20:00:37+00:00",
        )

        self.assertEqual("idle_close_probe", probe["action"])
        self.assertEqual(
            [
                "valve_control_configure",
                "valve_control_sync",
                "valve_control_close",
            ],
            [command["type"] for _node, command in self.sent],
        )
        self.assertNotIn(
            "duration_seconds",
            self.sent[-1][1],
        )
        self.assertEqual(0, self.sent[-1][1]["expected_sequence"])
        confirmed = self.store.confirm_valve_control_response(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            sequence=0,
            next_sequence=0,
            zone=1,
            watering=False,
            center_hz=433_518_527,
            observed_at="2026-08-24T20:00:38+00:00",
            frame="00",
        )
        self.assertEqual(0, confirmed["control_next_sequence"])
        self.assertEqual(
            "idle_close_probe_authenticated",
            confirmed["control_last_result"],
        )

    def test_close_discriminator_rejection_preserves_known_counter(self) -> None:
        wrong = self.coordinator.request_close_discriminator(
            self.profile,
            candidate_sequence=8,
            started_at="2026-08-24T20:00:20+00:00",
        )

        self.assertEqual(8, wrong["expected_sequence"])
        self.assertEqual("valve_control_close", self.sent[-1][1]["type"])
        rejected = self.store.fail_htv405_command(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            command_id=wrong["command_id"],
            reason="gateway_command_rejected_counter_unsynchronized",
            observed_at="2026-08-24T20:00:21+00:00",
        )
        self.assertEqual(6, rejected["control_next_sequence"])
        self.assertEqual(
            "close_discriminator_rejected_counter_preserved",
            rejected["control_last_result"],
        )

        correct = self.coordinator.request_close_discriminator(
            self.profile,
            candidate_sequence=6,
            started_at="2026-08-24T20:00:36+00:00",
        )
        confirmed = self.store.confirm_valve_control_response(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            sequence=6,
            next_sequence=6,
            zone=1,
            watering=False,
            center_hz=433_518_527,
            observed_at="2026-08-24T20:00:37+00:00",
            frame="00",
        )

        self.assertEqual(6, correct["expected_sequence"])
        self.assertEqual(6, confirmed["control_next_sequence"])
        self.assertEqual(
            "close_discriminator_authenticated",
            confirmed["control_last_result"],
        )

    def test_silent_close_discriminator_invalidates_local_certainty(self) -> None:
        wrong = self.coordinator.request_close_discriminator(
            self.profile,
            candidate_sequence=8,
            started_at="2026-08-24T20:00:20+00:00",
        )

        timed_out = self.store.fail_htv405_command(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            command_id=wrong["command_id"],
            reason="gateway_command_response_timeout_counter_unsynchronized",
            observed_at="2026-08-24T20:00:22+00:00",
        )

        self.assertIsNone(timed_out["control_next_sequence"])
        self.assertEqual(
            "close_discriminator_timeout_counter_unsynchronized",
            timed_out["control_last_result"],
        )
        self.assertEqual(6, timed_out["control_recovery_sequence"])

        baseline = self.coordinator.request_close_discriminator(
            self.profile,
            candidate_sequence=6,
            started_at="2026-08-24T20:00:37+00:00",
        )
        self.assertEqual(6, baseline["expected_sequence"])
        pending = next(
            item
            for item in self.store.valve_registry()
            if item["valve_endpoint"] == self.profile.valve_endpoint
        )
        self.assertIsNone(pending["control_next_sequence"])
        confirmed = self.store.confirm_valve_control_response(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            sequence=6,
            next_sequence=6,
            zone=1,
            watering=False,
            center_hz=433_518_527,
            observed_at="2026-08-24T20:00:38+00:00",
            frame="00",
        )
        self.assertEqual(6, confirmed["control_next_sequence"])
        self.assertEqual(
            "close_discriminator_authenticated",
            confirmed["control_last_result"],
        )

    def test_rejected_frozen_discriminator_baseline_stays_unsynchronized(
        self,
    ) -> None:
        wrong = self.coordinator.request_close_discriminator(
            self.profile,
            candidate_sequence=8,
            started_at="2026-08-24T20:00:20+00:00",
        )
        self.store.fail_htv405_command(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            command_id=wrong["command_id"],
            reason="gateway_command_response_timeout_counter_unsynchronized",
            observed_at="2026-08-24T20:00:22+00:00",
        )
        baseline = self.coordinator.request_close_discriminator(
            self.profile,
            candidate_sequence=6,
            started_at="2026-08-24T20:00:37+00:00",
        )
        rejected = self.store.fail_htv405_command(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            command_id=baseline["command_id"],
            reason="gateway_command_rejected_counter_unsynchronized",
            observed_at="2026-08-24T20:00:38+00:00",
        )

        self.assertIsNone(rejected["control_next_sequence"])
        self.assertIsNone(rejected["control_recovery_sequence"])
        self.assertEqual(
            "close_discriminator_baseline_rejected_counter_unsynchronized",
            rejected["control_last_result"],
        )

    def test_guarded_open_probe_stays_provisional_until_valve_response(self) -> None:
        first = self.coordinator.request_open(
            self.profile,
            zone=1,
            duration_seconds=60,
            started_at="2026-08-24T20:00:20+00:00",
        )
        self.store.confirm_valve_control_response(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            sequence=6,
            next_sequence=7,
            zone=1,
            watering=True,
            center_hz=433_518_527,
            observed_at="2026-08-24T20:00:21+00:00",
            frame="00",
            run_started_at="2026-08-24T20:00:20+00:00",
            run_duration_seconds=60,
            expected_idle_at="2026-08-24T20:01:20+00:00",
        )
        self.store.observe_htv405_state_report(
            valve_endpoint=self.profile.valve_endpoint,
            watering=False,
            zone=None,
            observed_at="2026-08-24T20:01:21+00:00",
        )
        failed = self.coordinator.request_open(
            self.profile,
            zone=1,
            duration_seconds=60,
            started_at="2026-08-24T20:01:36+00:00",
        )
        self.store.fail_htv405_command(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            command_id=failed["command_id"],
            reason="gateway_command_response_timeout_counter_unsynchronized",
            observed_at="2026-08-24T20:01:42+00:00",
        )
        # Begin a fresh experiment rather than consuming the ordinary retry
        # reservation created by that artificial timeout.
        self.store._connection.execute(
            """
            UPDATE valve_registry SET
                control_recovery_sequence = NULL,
                control_recovery_attempt = 0,
                control_recovery_not_before = NULL,
                control_recovery_zone = NULL,
                control_recovery_duration_seconds = NULL,
                control_last_result = 'idle_confirmed_counter_unsynchronized'
            WHERE valve_endpoint = ?
            """,
            (self.profile.valve_endpoint,),
        )
        self.store._connection.commit()
        self.sent.clear()

        probe = self.coordinator.request_guarded_open_probe(
            self.profile,
            started_at="2026-08-24T20:01:57+00:00",
        )

        self.assertEqual("guarded_open_probe", probe["action"])
        self.assertEqual(60, probe["duration_seconds"])
        self.assertEqual(
            [
                "valve_control_configure",
                "valve_control_sync",
                "valve_control_open",
            ],
            [command["type"] for _node, command in self.sent],
        )
        self.assertEqual(7, self.sent[-1][1]["expected_sequence"])
        provisional = self.store.valve_registry()[0]
        self.assertIsNone(provisional["control_next_sequence"])
        confirmed = self.store.confirm_valve_control_response(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            sequence=7,
            next_sequence=8,
            zone=1,
            watering=True,
            center_hz=433_518_527,
            observed_at="2026-08-24T20:01:58+00:00",
            frame="00",
            run_started_at="2026-08-24T20:01:57+00:00",
            run_duration_seconds=60,
            expected_idle_at="2026-08-24T20:02:57+00:00",
        )
        self.assertEqual(8, confirmed["control_next_sequence"])
        self.assertTrue(confirmed["control_confirmed_watering"])

    def test_guarded_open_probe_can_select_only_first_three_candidates(self) -> None:
        first = self.coordinator.request_open(
            self.profile,
            zone=1,
            duration_seconds=60,
            started_at="2026-08-24T20:00:20+00:00",
        )
        self.store.confirm_valve_control_response(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            sequence=6,
            next_sequence=7,
            zone=1,
            watering=True,
            center_hz=433_518_527,
            observed_at="2026-08-24T20:00:21+00:00",
            frame="00",
            run_started_at="2026-08-24T20:00:20+00:00",
            run_duration_seconds=60,
            expected_idle_at="2026-08-24T20:01:20+00:00",
        )
        self.store.observe_htv405_state_report(
            valve_endpoint=self.profile.valve_endpoint,
            watering=False,
            zone=None,
            observed_at="2026-08-24T20:01:21+00:00",
        )
        failed = self.coordinator.request_open(
            self.profile,
            zone=1,
            duration_seconds=60,
            started_at="2026-08-24T20:01:36+00:00",
        )
        self.store.fail_htv405_command(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            command_id=failed["command_id"],
            reason="gateway_command_response_timeout_counter_unsynchronized",
            observed_at="2026-08-24T20:01:42+00:00",
        )
        self.store._connection.execute(
            """
            UPDATE valve_registry SET
                control_recovery_sequence = NULL,
                control_recovery_attempt = 0,
                control_recovery_not_before = NULL,
                control_recovery_zone = NULL,
                control_recovery_duration_seconds = NULL,
                control_last_result = 'idle_confirmed_counter_unsynchronized'
            WHERE valve_endpoint = ?
            """,
            (self.profile.valve_endpoint,),
        )
        self.store._connection.commit()
        self.sent.clear()

        probe = self.coordinator.request_guarded_open_probe(
            self.profile,
            started_at="2026-08-24T20:01:57+00:00",
            candidate_sequence=9,
        )
        self.assertEqual(9, probe["expected_sequence"])
        self.assertEqual(9, self.sent[-1][1]["expected_sequence"])
        failed_probe = self.store.fail_htv405_command(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            command_id=probe["command_id"],
            reason="gateway_command_response_timeout_counter_unsynchronized",
            observed_at="2026-08-24T20:02:03+00:00",
        )
        self.assertEqual(
            "guarded_open_probe_timeout",
            failed_probe["control_last_result"],
        )
        self.assertIsNone(failed_probe["control_recovery_sequence"])
        self.store._connection.execute(
            """
            UPDATE valve_registry SET
                control_recovery_sequence = NULL,
                control_recovery_attempt = 0,
                control_recovery_not_before = NULL,
                control_recovery_zone = NULL,
                control_recovery_duration_seconds = NULL,
                control_last_result = 'idle_confirmed_counter_unsynchronized'
            WHERE valve_endpoint = ?
            """,
            (self.profile.valve_endpoint,),
        )
        self.store._connection.commit()
        with self.assertRaisesRegex(ValueError, "three-counter probe budget"):
            self.coordinator.request_guarded_open_probe(
                self.profile,
                started_at="2026-08-24T20:02:18+00:00",
                candidate_sequence=10,
            )

    def test_idle_close_anchor_retries_once_without_treating_silence_as_sync(
        self,
    ) -> None:
        pending = self.coordinator.request_open(
            self.profile,
            zone=1,
            duration_seconds=60,
            started_at="2026-08-24T20:00:20+00:00",
        )
        self.store.fail_htv405_command(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            command_id=pending["command_id"],
            reason="gateway_command_response_timeout_counter_unsynchronized",
            observed_at="2026-08-24T20:00:22+00:00",
        )
        self.sent.clear()
        first = self.coordinator.request_idle_close_probe(
            self.profile,
            zone=1,
            started_at="2026-08-24T20:00:37+00:00",
        )
        silent = self.store.fail_htv405_command(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            command_id=first["command_id"],
            reason="gateway_command_response_timeout_counter_unsynchronized",
            observed_at="2026-08-24T20:00:39+00:00",
        )
        self.assertEqual(0, silent["control_recovery_sequence"])
        self.assertEqual(
            "idle_close_probe_timeout_retry", silent["control_last_result"]
        )

        second = self.coordinator.request_idle_close_probe(
            self.profile,
            zone=1,
            started_at="2026-08-24T20:00:54+00:00",
        )
        self.assertEqual(0, self.sent[-1][1]["expected_sequence"])
        exhausted = self.store.fail_htv405_command(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            command_id=second["command_id"],
            reason="gateway_command_response_timeout_counter_unsynchronized",
            observed_at="2026-08-24T20:00:56+00:00",
        )
        self.assertIsNone(exhausted["control_recovery_sequence"])
        self.assertEqual(
            "idle_close_probe_search_exhausted",
            exhausted["control_last_result"],
        )
        with self.assertRaisesRegex(RuntimeError, "terminal"):
            self.coordinator.request_idle_close_probe(
                self.profile,
                zone=1,
                started_at="2026-08-24T20:01:11+00:00",
            )
        self.assertTrue(
            all(
                command["type"] != "valve_control_open"
                for _node, command in self.sent
            )
        )

    def test_idle_close_anchor_rejection_stops_without_another_candidate(
        self,
    ) -> None:
        pending = self.coordinator.request_open(
            self.profile,
            zone=1,
            duration_seconds=60,
            started_at="2026-08-24T20:00:20+00:00",
        )
        self.store.fail_htv405_command(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            command_id=pending["command_id"],
            reason="gateway_command_response_timeout_counter_unsynchronized",
            observed_at="2026-08-24T20:00:22+00:00",
        )
        self.sent.clear()
        anchor = self.coordinator.request_idle_close_probe(
            self.profile,
            zone=1,
            started_at="2026-08-24T20:00:37+00:00",
        )

        rejected = self.store.fail_htv405_command(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            command_id=anchor["command_id"],
            reason="gateway_command_rejected_counter_unsynchronized",
            observed_at="2026-08-24T20:00:39+00:00",
        )

        self.assertIsNone(rejected["control_next_sequence"])
        self.assertIsNone(rejected["control_recovery_sequence"])
        self.assertEqual(
            "idle_close_probe_search_exhausted",
            rejected["control_last_result"],
        )
        self.assertNotIn(
            "valve_control_open",
            [command["type"] for _node, command in self.sent],
        )

    def test_idle_close_scan_aborts_on_unexpected_watering(self) -> None:
        pending = self.coordinator.request_open(
            self.profile,
            zone=1,
            duration_seconds=60,
            started_at="2026-08-24T20:00:20+00:00",
        )
        self.store.fail_htv405_command(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            command_id=pending["command_id"],
            reason="gateway_command_response_timeout_counter_unsynchronized",
            observed_at="2026-08-24T20:00:22+00:00",
        )
        self.coordinator.request_idle_close_probe(
            self.profile,
            zone=1,
            started_at="2026-08-24T20:00:37+00:00",
        )

        aborted = self.store.observe_htv405_state_report(
            valve_endpoint=self.profile.valve_endpoint,
            watering=True,
            zone=2,
            observed_at="2026-08-24T20:00:38+00:00",
        )

        self.assertIsNone(aborted["control_pending_command_id"])
        self.assertIsNone(aborted["control_recovery_sequence"])
        self.assertIsNone(aborted["control_next_sequence"])
        self.assertTrue(aborted["control_confirmed_watering"])
        self.assertEqual(2, aborted["control_active_zone"])
        self.assertEqual(
            "unexpected_watering_aborted_idle_close_resync",
            aborted["control_last_result"],
        )

    def test_non_whole_minute_duration_is_never_reserved_or_transmitted(self) -> None:
        with self.assertRaisesRegex(ValueError, "whole minute"):
            self.coordinator.request_open(
                self.profile,
                zone=1,
                duration_seconds=30,
                started_at="2026-08-24T20:00:20+00:00",
            )

        state = self.store.valve_registry()[0]
        self.assertEqual(6, state["control_next_sequence"])
        self.assertIsNone(state["control_pending_command_id"])
        self.assertEqual([], self.sent)

    def test_fifteen_minute_duration_uses_continuous_range(self) -> None:
        pending = self.coordinator.request_synchronized_open(
            self.profile,
            zone=1,
            duration_seconds=900,
            started_at="2026-09-02T20:00:20+00:00",
        )

        self.assertEqual("waiting_for_valve_report", pending["state"])
        self.assertEqual(900, self.sent[-1][1]["duration_seconds"])

    def test_nine_minute_duration_can_enter_physical_validation(self) -> None:
        pending = self.coordinator.request_synchronized_open(
            self.profile,
            zone=1,
            duration_seconds=540,
            started_at="2026-09-02T20:00:20+00:00",
        )

        self.assertEqual("waiting_for_valve_report", pending["state"])
        self.assertEqual(540, self.sent[-1][1]["duration_seconds"])

    def test_sixty_minute_duration_can_enter_physical_validation(self) -> None:
        pending = self.coordinator.request_synchronized_open(
            self.profile,
            zone=1,
            duration_seconds=3_600,
            started_at="2026-09-02T20:01:20+00:00",
        )

        self.assertEqual("waiting_for_valve_report", pending["state"])
        self.assertEqual(3_600, self.sent[-1][1]["duration_seconds"])

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

        second = self.coordinator.request_open(
            self.profile,
            zone=1,
            duration_seconds=60,
            started_at="2026-08-24T20:00:38+00:00",
        )
        failed_again = self.store.fail_htv405_command(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            command_id=second["command_id"],
            reason=(
                "gateway_command_response_timeout_counter_unsynchronized"
            ),
            observed_at="2026-08-24T20:00:40+00:00",
        )
        self.assertEqual(7, failed_again["control_recovery_sequence"])
        self.assertEqual(2, failed_again["control_recovery_attempt"])
        self.assertIsNone(
            self.store.recover_htv405_timeout_counter(
                valve_endpoint=self.profile.valve_endpoint,
                node_id=self.profile.node_id,
                observed_at="2026-08-24T20:00:55+00:00",
            )
        )
        idle = self.store.observe_htv405_state_report(
            valve_endpoint=self.profile.valve_endpoint,
            watering=False,
            zone=None,
            observed_at="2026-08-24T20:00:56+00:00",
        )
        self.assertEqual(
            "gateway_command_response_timeout_counter_unsynchronized",
            idle["control_last_result"],
        )
        recovered_again = self.store.recover_htv405_timeout_counter(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            observed_at="2026-08-24T20:00:56+00:00",
        )
        self.assertEqual(7, recovered_again["control_next_sequence"])

        self.coordinator.request_open(
            self.profile,
            zone=1,
            duration_seconds=60,
            started_at="2026-08-24T20:00:57+00:00",
        )
        self.store.confirm_valve_control_response(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            sequence=7,
            next_sequence=8,
            zone=1,
            watering=True,
            center_hz=433_518_527,
            observed_at="2026-08-24T20:00:58+00:00",
            frame="00",
            run_started_at="2026-08-24T20:00:57+00:00",
            run_duration_seconds=60,
            expected_idle_at="2026-08-24T20:01:57+00:00",
        )
        state = self.store.valve_registry()[0]
        self.assertEqual(8, state["control_next_sequence"])
        self.assertIsNone(state["control_recovery_sequence"])
        self.assertEqual(0, state["control_recovery_attempt"])

    def test_operator_can_cancel_idle_recovery_without_transmitting(self) -> None:
        pending = self.coordinator.request_open(
            self.profile,
            zone=1,
            duration_seconds=60,
            started_at="2026-08-24T20:00:20+00:00",
        )
        failed = self.store.fail_htv405_command(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            command_id=pending["command_id"],
            reason="gateway_command_response_timeout_counter_unsynchronized",
            observed_at="2026-08-24T20:00:22+00:00",
        )
        self.assertEqual(6, failed["control_recovery_sequence"])
        recovered = self.store.recover_htv405_timeout_counter(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            observed_at="2026-08-24T20:00:37+00:00",
        )
        self.assertEqual(6, recovered["control_next_sequence"])
        sent_before_cancel = len(self.sent)

        cancelled = self.store.cancel_htv405_control_recovery(
            valve_endpoint=self.profile.valve_endpoint,
            node_id=self.profile.node_id,
            observed_at="2026-08-24T20:00:38+00:00",
        )

        self.assertIsNone(cancelled["control_recovery_sequence"])
        self.assertIsNone(cancelled["control_next_sequence"])
        self.assertEqual(0, cancelled["control_recovery_attempt"])
        self.assertEqual(
            "counter_recovery_cancelled_by_operator",
            cancelled["control_last_result"],
        )
        self.assertEqual(sent_before_cancel, len(self.sent))

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
        self.assertEqual(7, failed["control_recovery_sequence"])
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
        self.assertEqual(7, recovered["control_next_sequence"])

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
    def test_schema_upgrade_invalidates_old_counter_without_replaying(self):
        import sqlite3

        command = self.coordinator.request_open(
            self.profile, duration_seconds=60,
            started_at="2026-08-24T12:00:20+00:00",
        )
        path = Path(self.temporary_directory.name) / "events.sqlite3"
        self.store.close()
        with sqlite3.connect(path) as connection:
            connection.execute("ALTER TABLE htv145_control_state DROP COLUMN command_marker_inverted")
            connection.execute("PRAGMA user_version = 18")
        self.store = SQLiteEventStore(path)
        self.coordinator = Htv145ControlCoordinator(
            store=self.store, sender=self.sender, enabled=True
        )
        state = self.store.htv145_control_states(self.profile.valve_endpoint)[0]
        self.assertFalse(state["counter_synchronized"])
        self.assertIsNone(state["next_sequence"])
        self.assertEqual(command["command_id"], state["pending_command_id"])
        self.assertFalse(state["command_marker_inverted"])
        self.sent.clear()
        with self.assertRaisesRegex(RuntimeError, "startup will not replay"):
            self.coordinator.start(
                self.profile, observed_at="2026-08-24T12:00:25+00:00"
            )
        self.assertEqual([], self.sent)

    def recorded_error(self, sequence=0x81):
        fixture = json.loads((ROOT / "research/fixtures/htv145_partial_pairing_control_replies_20260905.json").read_text())
        frame = bytearray.fromhex(fixture["trials"][1]["valid_valve_frames"][0]["frame"])
        frame[5:9] = self.profile.link.valve_endpoint
        frame[9:13] = self.profile.link.controller_endpoint
        frame[13] = sequence
        frame[-2:] = (binascii.crc_hqx(frame[:-2], 0) ^ 0xC713).to_bytes(2, "big")
        return bytes(frame)

    def test_negative_result_clears_counter_without_confirming_state(self):
        command = self.coordinator.request_close(
            self.profile, started_at="2026-08-24T12:00:20+00:00"
        )
        before = self.store.htv145_control_states(self.profile.valve_endpoint)[0]
        error = self.recorded_error()
        state = self.coordinator.observe_candidate_status(
            self.profile,
            {"type": "htv145_control_candidate", "node_id": self.profile.node_id,
             "command_id": command["command_id"], "state": "negative_command_response",
             "frame": error.hex()},
            observed_at="2026-08-24T12:00:21+00:00",
        )
        self.assertFalse(state["counter_synchronized"])
        self.assertIsNone(state["pending_command_id"])
        self.assertEqual("negative_command_result_3", state["last_result"])
        self.assertEqual(error.hex(), state["last_response_frame"])
        self.assertEqual(before["confirmed_at"], state["confirmed_at"])
        self.assertEqual(before["confirmed_watering"], state["confirmed_watering"])
        with self.assertRaisesRegex(RuntimeError, "counter"):
            self.coordinator.request_open(
                self.profile, duration_seconds=60,
                started_at="2026-08-24T12:01:00+00:00",
            )

    def test_wrong_counter_error_preserves_pending_command(self):
        command = self.coordinator.request_close(
            self.profile, started_at="2026-08-24T12:00:20+00:00"
        )
        with self.assertRaisesRegex(ValueError, "no matching durable reservation"):
            self.coordinator.observe_frame(
                self.profile, self.recorded_error(0x80),
                observed_at="2026-08-24T12:00:21+00:00",
            )
        state = self.store.htv145_control_states(self.profile.valve_endpoint)[0]
        self.assertEqual(command["command_id"], state["pending_command_id"])

    def test_stock_open_close_open_continuity_survives_restart(self):
        fixture = json.loads((ROOT / "research/fixtures/htv145_selector6_stock_duration_commands_20260828.json").read_text())
        self.profile = replace(self.profile, command_marker_inverted=True)
        self.coordinator.configure(self.profile, observed_at="2026-08-24T12:00:00+00:00")
        self.coordinator.observe_frame(self.profile, self.IDLE, observed_at="2026-08-24T12:00:01+00:00")
        self.coordinator.synchronize_from_passive_command(
            self.profile, build_open_frame(self.profile.link, 0x80, 300, 0xc713, command_marker_inverted=True),
            observed_at="2026-08-24T12:00:02+00:00",
        )
        self.coordinator.start(self.profile, observed_at="2026-08-24T12:00:03+00:00")
        for index, transaction in enumerate(fixture["transactions"]):
            started_at = f"2026-08-24T12:0{index + 1}:00+00:00"
            if transaction["action"] == "open":
                command = self.coordinator.request_open(
                    self.profile, duration_seconds=transaction["duration_seconds"], started_at=started_at
                )
            else:
                command = self.coordinator.request_close(self.profile, started_at=started_at)
            self.assertEqual(int(transaction["command_sequence"], 16), command["expected_sequence"])
            state = self.coordinator.observe_frame(
                self.profile, bytes.fromhex(transaction["response_frame"]),
                observed_at=f"2026-08-24T12:0{index + 1}:01+00:00",
            )
            self.assertTrue(state["counter_synchronized"])
            self.coordinator = Htv145ControlCoordinator(store=self.store, sender=self.sender, enabled=True)
            restored = self.coordinator.start(self.profile, observed_at=f"2026-08-24T12:0{index + 1}:02+00:00")
            self.assertEqual(state["next_sequence"], restored[1]["next_sequence"])
            self.assertTrue(restored[0]["command_marker_inverted"])

    def test_branch_mismatch_cannot_authenticate_counter(self):
        wrong_branch = build_open_frame(self.profile.link, 0x80, 300, 0xc713, command_marker_inverted=True)
        with self.assertRaisesRegex(ValueError, "marker differs"):
            self.coordinator.synchronize_from_passive_command(self.profile, wrong_branch, observed_at="2026-08-24T12:00:03+00:00")


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
        self.assertIsNone(confirmed["next_sequence"])
        self.assertFalse(confirmed["counter_synchronized"])
        self.assertTrue(confirmed["confirmed_watering"])
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

    def test_terminal_summary_never_overwrites_current_watering(self) -> None:
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
        self.assertTrue(state["confirmed_watering"])
        self.assertIsNotNone(state["expected_idle_at"])
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


class Htv145QualificationTest(unittest.TestCase):
    def setUp(self):
        Htv145RuntimeTest.setUp(self)
        self.node["capabilities"].append("htv145_idle_anchor")
        self.q = self.runtime.qualification
        self.anchor = bytes.fromhex(json.loads((ROOT / "research/fixtures/htv145_idle_result3_counter_recovery_20260906.json").read_text())["transactions"][0]["response_frame"])
        self.closed = bytes.fromhex("79f4882f28a1b2c380b1c2d38f82508680104f80000000408000569e00000000000000003da3")

    def at(self, seconds=0):
        return (datetime(2026, 9, 7, 12, tzinfo=timezone.utc) + timedelta(seconds=seconds)).isoformat()

    def frame_counter(self, frame, counter):
        value = bytearray(frame)
        value[13] = counter
        value[-2:] = (binascii.crc_hqx(value[:-2], 0) ^ 0x4f03).to_bytes(2, "big")
        return bytes(value)

    def prepare(self):
        self.q.prepare(self.profile, now=self.at())

    def synchronized(self):
        self.prepare()
        self.runtime.observe_counter_sync_report(self.idle, self.profile.node_id, now=self.at(1))
        self.runtime.observe_frame(self.anchor, now=self.at(2))

    def automatic_stop(self):
        self.synchronized()
        self.q.action(self.profile, "open", now=self.at(17))
        self.runtime.observe_frame(self.frame_counter(self.response, 0x80), now=self.at(18))
        self.runtime.observe_frame(self.idle, now=self.at(79))

    def test_two_bounded_runs_qualify_only_after_positive_close_and_independent_idle(self):
        self.automatic_stop()
        self.assertEqual("ready_for_early_stop_test", self.q.status(self.profile, now=self.at(80))["state"])
        self.assertFalse(self.runtime.status(self.profile, now=self.at(80))["ready"])
        with self.assertRaisesRegex(RuntimeError, "qualification"):
            self.runtime.request(self.profile, "open", duration_seconds=60, now=self.at(80))
        self.q.action(self.profile, "open", now=self.at(95))
        self.runtime.observe_frame(self.response, now=self.at(96))
        with self.assertRaises(RuntimeError):
            self.q.action(self.profile, "close", now=self.at(100))
        self.q.action(self.profile, "close", now=self.at(115))
        self.runtime.observe_frame(self.closed, now=self.at(116))
        self.assertFalse(self.q.qualified(self.profile))
        self.runtime.observe_frame(self.summary, now=self.at(120))
        self.assertFalse(self.q.qualified(self.profile))
        self.runtime.observe_frame(self.idle, now=self.at(122))
        self.assertTrue(self.q.qualified(self.profile))
        self.assertTrue(self.runtime.status(self.profile, now=self.at(123))["ready"])
        opens = [c for _, c in self.sent if c["type"] == "htv145_control_open"]
        self.assertEqual([60, 60], [c["duration_seconds"] for c in opens])
        self.assertEqual([128, 129], [c["expected_sequence"] for c in opens])
        with self.assertRaises(RuntimeError):
            self.q.action(self.profile, "open", now=self.at(130))

    def test_prepare_never_copies_counter_and_requires_new_owner_report(self):
        self.prepare()
        self.assertEqual(["htv145_control_configure"], [c["type"] for _, c in self.sent])
        self.assertFalse(self.store.htv145_control_states()[0]["counter_synchronized"])
        self.runtime.observe_counter_sync_report(self.idle, "rp-aabbccddeeff", now=self.at(1))
        self.runtime.observe_frame(self.anchor, now=self.at(2))
        self.assertEqual(1, len(self.sent))
        self.assertFalse(self.q.qualified(self.profile))
        with self.assertRaises(RuntimeError):
            self.q.action(self.profile, "open", now=self.at(3))

    def test_restart_interrupts_qualification_and_cancels_anchor_without_rf_replay(self):
        from rainpointd.htv145_runtime import Htv145Runtime
        self.prepare()
        self.sent.clear()
        restarted = Htv145Runtime(self.coordinator, lambda _: self.node)
        restarted.tick(now=self.at(5))
        restarted.observe_counter_sync_report(self.idle, self.profile.node_id, now=self.at(6))
        self.assertEqual("interrupted", restarted.qualification.status(self.profile, now=self.at(6))["state"])
        self.assertFalse(restarted.qualification.qualified(self.profile))
        self.assertTrue(all(c["type"] == "htv145_control_configure" for _, c in self.sent))

    def test_timeout_and_duplicate_open_do_not_authorize_retry(self):
        self.synchronized()
        self.q.action(self.profile, "open", now=self.at(17))
        with self.assertRaises(RuntimeError):
            self.q.action(self.profile, "open", now=self.at(18))
        self.runtime.observe_frame(self.frame_counter(self.response, 0x85), now=self.at(18))
        self.assertEqual("failed", self.q.status(self.profile, now=self.at(34))["state"])
        self.assertFalse(self.q.qualified(self.profile))
        self.assertEqual(1, sum(c["type"] == "htv145_control_open" for _, c in self.sent))

    def test_ownership_and_node_epoch_are_not_silently_replaced(self):
        old = replace(self.profile, node_id="rp-aabbccddeeff", valve_endpoint="aabbcc80")
        self.coordinator.configure(old, observed_at=self.at())
        with self.assertRaisesRegex(RuntimeError, "revoke"):
            self.prepare()
        self.assertEqual([], self.sent)
        self.store.delete_htv145_control(old.valve_endpoint)
        self.prepare()
        self.node["connected_at"] = "connection-2"
        self.assertEqual("failed", self.q.status(self.profile, now=self.at(1))["state"])
        self.runtime.observe_counter_sync_report(self.idle, self.profile.node_id, now=self.at(2))
        self.assertEqual(1, len(self.sent))

    def test_custom_identity_unqualified_anchor_stops_before_any_open(self):
        fixture = json.loads((ROOT / "research/fixtures/htv145_custom_identity_idle_anchor_20260907.json").read_text())
        self.prepare()
        self.runtime.observe_counter_sync_report(bytes.fromhex(fixture["idle_frame"]),
                                                 self.profile.node_id, now=self.at(1))
        self.runtime.observe_frame(bytes.fromhex(fixture["response_frame"]), now=self.at(2))
        status = self.runtime.status(self.profile, now=self.at(3))
        self.assertEqual(fixture["qualification_state"], status["dry_qualification"]["state"])
        self.assertEqual(fixture["qualification_reason"], status["dry_qualification"]["reason"])
        self.assertEqual(fixture["result"], status["state"]["last_result"])
        self.assertFalse(status["public_control_qualified"])
        self.assertFalse(status["counter_synchronized"])
        self.assertIsNone(status["next_sequence"])
        with self.assertRaises(RuntimeError):
            self.q.action(self.profile, "open", now=self.at(20))
        self.runtime.observe_counter_sync_report(self.idle, self.profile.node_id, now=self.at(21))
        self.assertEqual(["htv145_control_configure", "htv145_control_idle_anchor"],
                         [c["type"] for _, c in self.sent])

    def test_corrupt_and_wrong_duration_replies_do_not_qualify(self):
        self.synchronized()
        self.q.action(self.profile, "open", now=self.at(17))
        corrupt = bytearray(self.frame_counter(self.response, 0x80))
        corrupt[-1] ^= 1
        self.runtime.observe_frame(bytes(corrupt), now=self.at(18))
        self.assertEqual("opening", self.store.htv145_qualification(self.profile.valve_endpoint)["state"])
        wrong_duration = bytearray(self.frame_counter(self.response, 0x80))
        wrong_duration[27] = 0xbc
        wrong_duration[-2:] = (binascii.crc_hqx(wrong_duration[:-2], 0) ^ 0x4f03).to_bytes(2, "big")
        self.runtime.observe_frame(bytes(wrong_duration), now=self.at(19))
        self.assertEqual("failed", self.q.status(self.profile, now=self.at(20))["state"])
        self.assertFalse(self.q.qualified(self.profile))

    def test_custom_identity_anchor_preserves_nonzero_usage_as_data(self):
        from rainpointd.valve_protocol import decode_htv145_idle_anchor_response, decode_htv145_command_response
        captured = bytes.fromhex("79f4882f28a1b2c380b1c2d38f80508683104fe700000040800056800000000000000000bf41")
        self.assertEqual({"sequence": 128, "result_code": 3},
                         decode_htv145_idle_anchor_response(captured, self.profile.link))
        self.assertIsNone(decode_htv145_command_response(captured, self.profile.link))
        for offset, value in ((17, 0), (21, 1), (18, 0xcf), (13, 0x81)):
            frame = bytearray(captured)
            frame[offset] = value
            frame[-2:] = (binascii.crc_hqx(frame[:-2], 0) ^ 0x4f03).to_bytes(2, "big")
            self.assertIsNone(decode_htv145_idle_anchor_response(bytes(frame), self.profile.link))

    def test_explicit_bootstrap_does_not_authenticate_candidate_before_positive_reply(self):
        self.prepare()
        self.runtime.observe_counter_sync_report(self.idle, self.profile.node_id, now=self.at(1))
        fixture = json.loads((ROOT / "research/fixtures/htv145_custom_identity_idle_anchor_20260907.json").read_text())
        self.runtime.observe_frame(bytes.fromhex(fixture["response_frame"]), now=self.at(2))
        self.runtime.status(self.profile, now=self.at(3))
        with self.assertRaisesRegex(RuntimeError, "firmware"):
            self.q.bootstrap(self.profile, now=self.at(20))
        self.node["capabilities"].append("htv145_bootstrap_trial")
        self.q.bootstrap(self.profile, now=self.at(20))
        state = self.store.htv145_control_states()[0]
        self.assertFalse(state["counter_synchronized"])
        self.assertIsNone(state["next_sequence"])
        self.assertEqual(0x81, state["pending_sequence"])
        self.assertEqual("htv145_control_bootstrap_open", self.sent[-1][1]["type"])
        self.assertFalse(self.q.qualified(self.profile))
        with self.assertRaises(RuntimeError):
            self.q.bootstrap(self.profile, now=self.at(21))
        self.runtime.observe_frame(self.response, now=self.at(21))
        self.assertTrue(self.store.htv145_control_states()[0]["counter_synchronized"])
        self.assertEqual("watering", self.q.status(self.profile, now=self.at(22))["state"])
        self.assertEqual("positive_first_open_response", self.store.htv145_counter_sync(self.profile.valve_endpoint)["reason"])
        self.runtime.observe_frame(self.idle, now=self.at(82))
        self.assertEqual("ready_for_early_stop_test", self.q.status(self.profile, now=self.at(83))["state"])
        self.assertFalse(self.q.qualified(self.profile))

    def test_captured_custom_identity_first_open_completes_qualification(self):
        fixture = json.loads((ROOT / "research/fixtures/htv145_custom_identity_first_open_20260908.json").read_text())
        negative = json.loads((ROOT / "research/fixtures/htv145_custom_identity_idle_anchor_20260907.json").read_text())
        self.prepare()
        self.runtime.observe_counter_sync_report(self.idle, self.profile.node_id, now=self.at(1))
        self.runtime.observe_frame(bytes.fromhex(negative["response_frame"]), now=self.at(2))
        self.runtime.status(self.profile, now=self.at(3))
        self.node["capabilities"].append("htv145_bootstrap_trial")
        self.q.bootstrap(self.profile, now=self.at(20))
        self.assertFalse(self.store.htv145_control_states()[0]["counter_synchronized"])
        self.runtime.observe_frame(bytes.fromhex(fixture["first_open"]["response_frame"]), now=self.at(21))
        self.assertEqual(130, self.runtime.status(self.profile, now=self.at(22))["next_sequence"])
        self.runtime.observe_frame(bytes.fromhex(fixture["first_open"]["idle_frame"]), now=self.at(83))
        self.assertFalse(self.q.qualified(self.profile))
        self.q.action(self.profile, "open", now=self.at(179))
        self.runtime.observe_frame(bytes.fromhex(fixture["second_open"]["response_frame"]), now=self.at(180))
        self.q.action(self.profile, "close", now=self.at(199))
        self.runtime.observe_frame(bytes.fromhex(fixture["early_close"]["response_frame"]), now=self.at(200))
        self.assertFalse(self.q.qualified(self.profile))
        self.runtime.observe_frame(bytes.fromhex(fixture["early_close"]["idle_frame"]), now=self.at(206))
        status = self.runtime.status(self.profile, now=self.at(207))
        self.assertTrue(status["ready"])
        self.assertEqual(131, status["next_sequence"])
        self.assertEqual(fixture["qualification_state"], status["dry_qualification"]["state"])
        self.assertEqual([129, 130, 131], [command["expected_sequence"] for _, command in self.sent
            if command["type"] in {"htv145_control_bootstrap_open", "htv145_control_open", "htv145_control_close"}])

    def test_bootstrap_negative_and_restart_never_replay_or_enable_public_control(self):
        from rainpointd.htv145_runtime import Htv145Runtime
        self.prepare()
        self.q._fail(self.store.htv145_qualification(self.profile.valve_endpoint), "idle_anchor_failed")
        self.runtime.observe_frame(self.idle, now=self.at(1))
        self.node["capabilities"].append("htv145_bootstrap_trial")
        self.q.bootstrap(self.profile, now=self.at(20))
        self.sent.clear()
        restarted = Htv145Runtime(self.coordinator, lambda _: self.node)
        self.assertFalse(restarted.qualification.qualified(self.profile))
        self.assertEqual("interrupted", self.store.htv145_qualification(self.profile.valve_endpoint)["state"])
        self.assertEqual([], self.sent)

    def test_negative_bootstrap_reply_leaves_counter_unknown_and_consumes_trial(self):
        self.prepare()
        self.q._fail(self.store.htv145_qualification(self.profile.valve_endpoint), "idle_anchor_failed")
        self.runtime.observe_frame(self.idle, now=self.at(1))
        self.node["capabilities"].append("htv145_bootstrap_trial")
        self.q.bootstrap(self.profile, now=self.at(20))
        fixture = json.loads((ROOT / "research/fixtures/htv145_custom_identity_idle_anchor_20260907.json").read_text())
        negative = bytearray.fromhex(fixture["response_frame"])
        negative[13] = 0x81
        negative[14] = 0xd0
        negative[-2:] = (binascii.crc_hqx(negative[:-2], 0) ^ 0x4f03).to_bytes(2, "big")
        self.runtime.observe_frame(bytes(negative), now=self.at(21))
        self.assertFalse(self.store.htv145_control_states()[0]["counter_synchronized"])
        self.assertEqual("failed", self.q.status(self.profile, now=self.at(22))["state"])
        with self.assertRaises(RuntimeError):
            self.q.bootstrap(self.profile, now=self.at(40))

    def test_completed_qualification_survives_database_reopen_without_actuation(self):
        from rainpointd.htv145_runtime import Htv145Runtime
        self.automatic_stop()
        self.q.action(self.profile, "open", now=self.at(95))
        self.runtime.observe_frame(self.response, now=self.at(96))
        self.q.action(self.profile, "close", now=self.at(115))
        self.runtime.observe_frame(self.closed, now=self.at(116))
        self.runtime.observe_frame(self.idle, now=self.at(122))
        self.store.close()
        self.store = SQLiteEventStore(Path(self.temp.name) / "events.sqlite3")
        self.sent.clear()
        coordinator = Htv145ControlCoordinator(store=self.store,
            sender=lambda node, command: self.sent.append((node, command)), enabled=True)
        restored = Htv145Runtime(coordinator, lambda _: self.node)
        restored.tick(now=self.at(125))
        self.assertTrue(restored.qualification.qualified(self.profile))
        self.assertEqual(["htv145_control_configure", "htv145_control_sync"], [c["type"] for _, c in self.sent])


class Htv145CommissioningTest(unittest.TestCase):
    at = Htv145QualificationTest.at

    def setUp(self):
        from rainpointd.htv145_commissioning import Htv145Commissioning
        Htv145RuntimeTest.setUp(self)
        self.node["capabilities"] += ["htv145_idle_anchor", "htv145_commissioning"]
        self.commissioning = Htv145Commissioning(self.runtime)
        self.registration = {"device_id": "test-valve", "model": "HTV145FRF",
            "valve_endpoint": self.profile.controller_endpoint,
            "controller_endpoint": self.profile.valve_endpoint}
        self.commissioning.record_pairing(self.registration, self.profile.node_id, "pairing-1")

    def act(self, action, seconds=0, consent=False):
        return self.commissioning.act(self.registration, action, now=self.at(seconds), consent=consent)

    def test_pairing_and_status_do_not_actuate_or_grant_authority(self):
        self.assertEqual("awaiting_consent", self.act("status")["state"])
        self.assertFalse(self.runtime.qualification.qualified(self.profile))
        self.act("advance")
        with self.assertRaises(ValueError): self.act("begin")
        self.assertEqual([], self.sent)

    def test_captured_first_open_and_stops_complete_device_based_onboarding(self):
        self.act("begin", consent=True)
        self.assertEqual(["htv145_control_configure"], [c["type"] for _, c in self.sent])
        with self.assertRaises(RuntimeError): self.act("begin", consent=True)
        negative = json.loads((ROOT / "research/fixtures/htv145_custom_identity_idle_anchor_20260907.json").read_text())
        fixture = json.loads((ROOT / "research/fixtures/htv145_custom_identity_first_open_20260908.json").read_text())
        self.runtime.observe_counter_sync_report(self.idle, self.profile.node_id, now=self.at(1))
        self.runtime.observe_frame(bytes.fromhex(negative["response_frame"]), now=self.at(2))
        self.act("advance", 3)
        self.assertFalse(any(c["type"].endswith("open") for _, c in self.sent))
        self.act("advance", 22)
        self.assertEqual("htv145_control_commission_open", self.sent[-1][1]["type"])
        sent = len(self.sent)
        self.act("advance", 22)
        self.assertEqual(sent, len(self.sent))
        self.assertFalse(self.runtime.qualification.qualified(self.profile))
        self.runtime.observe_frame(bytes.fromhex(fixture["first_open"]["response_frame"]), now=self.at(23))
        self.runtime.observe_frame(bytes.fromhex(fixture["first_open"]["idle_frame"]), now=self.at(85))
        self.act("advance", 86)
        self.runtime.observe_frame(bytes.fromhex(fixture["second_open"]["response_frame"]), now=self.at(87))
        self.act("advance", 105)
        self.assertEqual("htv145_control_open", self.sent[-1][1]["type"])
        self.act("advance", 106)
        self.assertEqual("htv145_control_close", self.sent[-1][1]["type"])
        self.runtime.observe_frame(bytes.fromhex(fixture["early_close"]["response_frame"]), now=self.at(107))
        self.runtime.observe_frame(bytes.fromhex(fixture["early_close"]["idle_frame"]), now=self.at(113))
        self.assertEqual("complete", self.act("advance", 114)["state"])
        self.assertTrue(self.runtime.qualification.qualified(self.profile))
        self.assertEqual(2, len([c for _, c in self.sent if c["type"].endswith("open")]))

    def test_cancel_restart_and_reconnection_never_replay(self):
        from rainpointd.htv145_commissioning import Htv145Commissioning
        for mode in ("cancel", "restart", "reconnect"):
            with self.subTest(mode=mode):
                self.commissioning.record_pairing(self.registration, self.profile.node_id, mode)
                self.act("begin", consent=True)
                count = len(self.sent)
                if mode == "cancel": self.act("cancel")
                elif mode == "restart": self.commissioning = Htv145Commissioning(self.runtime)
                else: self.node["connected_at"] = "new-connection"
                self.assertEqual("interrupted", self.act("advance", 1)["state"])
                self.assertEqual(count, len(self.sent))

    def test_owner_revoke_is_confirmed_before_replacement(self):
        self.coordinator.configure(self.profile, observed_at=self.at())
        self.act("begin", consent=True)
        self.assertEqual("htv145_control_revoke", self.sent[-1][1]["type"])
        count = len(self.sent)
        self.act("advance", 1)
        self.assertEqual(count, len(self.sent))
        command = self.sent[-1][1]
        self.runtime.observe_node(self.profile.node_id, {**command, "state": "revoked"}, now=self.at(2))
        self.act("advance", 3)
        self.assertEqual("htv145_control_configure", self.sent[-1][1]["type"])

    def test_association_change_and_expiry_fail_closed(self):
        self.act("begin", consent=True)
        count = len(self.sent)
        self.assertEqual("failed", self.act("advance", 901)["state"])
        self.assertEqual(count, len(self.sent))
        self.registration["controller_endpoint"] = "d1b2c380"
        self.assertEqual("association_changed", self.act("status", 902)["reason"])


class Htv145RuntimeTest(unittest.TestCase):
    def setUp(self):
        from rainpointd.htv145_runtime import Htv145Runtime
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = SQLiteEventStore(Path(self.temp.name) / "events.sqlite3")
        self.addCleanup(lambda: self.store.close())
        self.sent = []
        self.coordinator = Htv145ControlCoordinator(store=self.store,
            sender=lambda node, command: self.sent.append((node, command)), enabled=True)
        self.node = {"connected": True, "authenticated": True, "tx_armed": False,
            "connected_at": "connection-1", "firmware_version": "test",
            "capabilities": ["htv145_control_tx_candidate", "htv145_report_ack_tx"]}
        self.runtime = Htv145Runtime(self.coordinator, lambda _: self.node)
        self.profile = Htv145ControlProfile(node_id="rp-001122334455",
            controller_endpoint="b1c2d38f", valve_endpoint="a1b2c380",
            center_hz=434398811, power_dbm=10, invert=False,
            trailer_residual=0x4f03, close_trailer_residual=0x4f03,
            command_marker_inverted=True, report_ack_center_hz=433518905)
        self.fixture = json.loads((ROOT / "research/fixtures/htv145_partial_pairing_control_acceptance_20260905.json").read_text())
        self.open_frame = bytes.fromhex("79f4882f28b1c2d38fa1b2c3808190828081009e00000000000000000000000000000000db9b")
        self.response = bytes.fromhex("79f4882f28a1b2c380b1c2d38f81d0868010cf80000000409e00569e000000000000000060e2")
        reports = self.fixture["control_trials"][0]["reports"]
        self.watering = bytes.fromhex(reports[0]["frame"])
        self.idle = bytes.fromhex(reports[4]["frame"])
        self.summary = bytes.fromhex(reports[7]["frame"])

    def enroll(self):
        return self.runtime.enroll(self.profile, command=self.open_frame, response=self.response,
            idle=self.idle, exchange_at="2026-09-05T12:00:00+00:00",
            idle_at="2026-09-05T12:01:03+00:00", now="2026-09-05T12:01:05+00:00")

    def test_pending_reboot_blocks_control_before_old_connection_disappears(self):
        self.enroll()
        self.sent.clear()
        self.node["node_reboot_pending"] = True
        now = "2026-09-05T12:02:00+00:00"
        before = self.store.htv145_control_states()
        self.assertFalse(self.runtime.status(self.profile, now=now)["owner_available"])
        for action in ("open", "close"):
            with self.assertRaises(RuntimeError):
                self.runtime.request(self.profile, action, duration_seconds=60, now=now)
        self.runtime.tick(now=now)
        self.assertEqual([], self.sent)
        self.assertEqual(before, self.store.htv145_control_states())
        self.node.update(node_reboot_pending=False, connected_at="connection-2")
        self.runtime.tick(now=now)
        self.assertEqual(["htv145_control_configure", "htv145_control_sync"],
                         [c["type"] for _, c in self.sent])
        self.assertTrue(self.runtime.status(self.profile, now=now)["ready"])

    def test_positive_exchange_enrollment_restores_only_configuration_and_counter(self):
        result = self.enroll()
        self.assertTrue(result["ready"])
        self.assertEqual(0x82, result["next_sequence"])
        self.assertEqual(["htv145_control_configure", "htv145_control_sync"], [c["type"] for _, c in self.sent])
        self.assertEqual(0x4f03, self.sent[0][1]["close_trailer_residual"])
        self.assertEqual(433518905, self.sent[0][1]["report_ack_center_hz"])
        self.sent.clear()
        self.node["connected_at"] = "connection-2"
        self.runtime.tick(now="2026-09-05T12:02:00+00:00")
        self.assertEqual(["htv145_control_configure", "htv145_control_sync"], [c["type"] for _, c in self.sent])
        self.assertEqual(0x82, self.sent[-1][1]["next_sequence"])

    def test_enrollment_upgrades_same_radio_legacy_profile_without_actuation(self):
        from dataclasses import replace
        legacy = replace(self.profile, report_ack_center_hz=None)
        self.coordinator.configure(legacy, observed_at="2026-09-05T11:00:00+00:00")
        result = self.enroll()
        self.assertTrue(result["ready"])
        self.assertEqual(self.profile.report_ack_center_hz, result["state"]["report_ack_center_hz"])
        self.assertEqual(["htv145_control_configure", "htv145_control_sync"],
                         [command["type"] for _, command in self.sent])

    def test_legacy_upgrade_rejects_changed_owner_pending_and_stale_evidence(self):
        from dataclasses import replace
        legacy = replace(self.profile, report_ack_center_hz=None)
        original = self.coordinator.configure(legacy, observed_at="2026-09-05T11:00:00+00:00")
        # A prior trial must not disappear or change owner during enrollment.
        cases = {
            "node_id": "rp-665544332211",
            "controller_endpoint": "aabbcc8f",
            "pending_command_id": "old-trial-command",
            "revocation_command_id": "old-revocation",
            "last_command_started_at": "2026-09-05T12:00:00+00:00",
            "report_ack_center_hz": self.profile.report_ack_center_hz,
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                with self.store._connection:
                    self.store._connection.execute(
                        f"UPDATE htv145_control_state SET {field} = ?", (value,))
                before = self.store.htv145_control_states()
                with self.assertRaises((ValueError, RuntimeError)):
                    self.enroll()
                self.assertEqual(before, self.store.htv145_control_states())
                self.assertEqual([], self.sent)
                with self.store._connection:
                    self.store._connection.execute(
                        f"UPDATE htv145_control_state SET {field} = ?", (original[field],))

    def test_legacy_radio_replacement_requires_verified_removal_of_htv145_support(self):
        from dataclasses import replace
        old_node_id = "rp-665544332211"
        legacy = replace(self.profile, node_id=old_node_id, report_ack_center_hz=None)
        self.coordinator.configure(legacy, observed_at="2026-09-05T11:00:00+00:00")
        retired = {**self.node, "capabilities": ["rx", "routine_sensor_ack_tx"]}
        self.runtime.node = lambda node_id: retired if node_id == old_node_id else self.node
        for changes in ({"connected": False}, {"authenticated": False},
                        {"capabilities": None}, {"capabilities": ["htv145_control_tx_candidate"]},
                        {"capabilities": ["htv145_report_ack_tx"]}):
            with self.subTest(changes=changes):
                original = dict(retired)
                retired.update(changes)
                with self.assertRaises(RuntimeError):
                    self.enroll()
                self.assertEqual(old_node_id, self.store.htv145_control_states()[0]["node_id"])
                self.assertEqual([], self.sent)
                retired.clear(); retired.update(original)
        result = self.enroll()
        self.assertTrue(result["ready"])
        self.assertEqual(self.profile.node_id, result["state"]["node_id"])
        self.assertEqual(["htv145_control_configure", "htv145_control_sync"],
                         [command["type"] for _, command in self.sent])

    def test_direct_command_and_summary_retry_leave_counter_and_current_state_intact(self):
        self.enroll(); self.sent.clear()
        command = self.runtime.request(self.profile, "open", duration_seconds=60, now="2026-09-05T12:02:00+00:00")
        self.assertEqual(["htv145_control_open"], [c["type"] for _, c in self.sent])
        self.assertEqual(0x82, command["expected_sequence"])
        # A repeated previous session summary is not evidence for this command.
        self.runtime.observe_frame(self.summary, now="2026-09-05T12:02:01+00:00")
        self.assertEqual(command["command_id"], self.store.htv145_control_states()[0]["pending_command_id"])
        response = bytearray(self.response); response[13] = 0x82
        response[-2:] = (binascii.crc_hqx(response[:-2], 0) ^ 0xc713).to_bytes(2, "big")
        self.runtime.observe_frame(bytes(response), now="2026-09-05T12:02:02+00:00")
        self.runtime.observe_frame(self.summary, now="2026-09-05T12:02:03+00:00")
        state = self.store.htv145_control_states()[0]
        self.assertTrue(state["confirmed_watering"])
        self.assertEqual(0x83, state["next_sequence"])
        self.runtime.observe_frame(self.idle, now="2026-09-05T12:03:03+00:00")
        self.assertEqual(0x83, self.store.htv145_control_states()[0]["next_sequence"])

    def test_restart_timeout_and_overdue_watchdog_are_observation_only(self):
        from rainpointd.htv145_runtime import Htv145Runtime
        self.enroll()
        self.runtime.request(self.profile, "open", duration_seconds=60, now="2026-09-05T12:02:00+00:00")
        self.sent.clear()
        self.store.close()
        self.store = SQLiteEventStore(Path(self.temp.name) / "events.sqlite3")
        self.coordinator = Htv145ControlCoordinator(store=self.store,
            sender=lambda n, c: self.sent.append((n, c)), enabled=True)
        self.runtime = Htv145Runtime(self.coordinator, lambda _: self.node)
        self.runtime.tick(now="2026-09-05T12:02:05+00:00")
        self.assertEqual([], self.sent)
        self.runtime.tick(now="2026-09-05T12:03:31+00:00")
        result = self.runtime.status(self.profile, now="2026-09-05T12:03:31+00:00")
        self.assertFalse(result["ready"])
        self.assertTrue(result["recovery_required"])
        self.assertEqual("expected_idle_not_observed", result["anomaly"])
        self.assertEqual(["htv145_control_configure"], [c["type"] for _, c in self.sent])

    def test_explicit_retained_restore_rejects_stale_idle_and_unavailable_owner(self):
        self.enroll(); self.sent.clear()
        with self.assertRaises(RuntimeError):
            self.runtime.restore_retained_counter(self.profile, now="2026-09-06T09:30:00+00:00")
        self.runtime.observe_frame(self.idle, now="2026-09-06T09:30:01+00:00")
        self.node["connected"] = False
        with self.assertRaises(RuntimeError):
            self.runtime.restore_retained_counter(self.profile, now="2026-09-06T09:30:02+00:00")
        self.assertEqual([], self.sent)
        self.node["connected"] = True
        self.runtime.request(self.profile, "open", now="2026-09-06T09:30:03+00:00", duration_seconds=60)
        self.sent.clear()
        with self.assertRaises(RuntimeError):
            self.runtime.restore_retained_counter(self.profile, now="2026-09-06T09:30:04+00:00")
        self.runtime.status(self.profile, now="2026-09-06T09:30:30+00:00")
        self.runtime.observe_frame(self.idle, now="2026-09-06T09:32:00+00:00")
        with self.assertRaises(RuntimeError):
            self.runtime.restore_retained_counter(self.profile, now="2026-09-06T09:32:01+00:00")
        self.assertEqual([], self.sent)

    def test_morning_check_preserves_known_counter_without_an_idle_close_probe(self):
        self.enroll(); self.sent.clear()
        status = self.runtime.status(self.profile, now="2026-09-06T09:30:00+00:00")
        self.assertFalse(status["ready"])
        self.assertTrue(status["counter_synchronized"])
        self.assertFalse(status["fresh_state"])
        self.assertEqual([], self.sent)
        self.runtime.observe_frame(self.idle, now="2026-09-06T09:30:01+00:00")
        self.assertTrue(self.runtime.status(self.profile, now="2026-09-06T09:30:02+00:00")["ready"])
        self.assertEqual([], self.sent)

    def test_revoke_requires_correlated_owner_confirmation_before_reassignment(self):
        self.enroll(); self.sent.clear()
        self.runtime.revoke(self.profile)
        message = {"type": "htv145_control_candidate", "node_id": self.profile.node_id,
            "state": "revoked", "controller_endpoint": self.profile.controller_endpoint,
            "valve_endpoint": self.profile.valve_endpoint, "command_id": "old-revocation"}
        self.runtime.observe_node(self.profile.node_id, message, now="2026-09-05T12:02:00+00:00")
        self.assertEqual(1, len(self.runtime.profiles()))
        with self.assertRaisesRegex(RuntimeError, "revocation"):
            self.runtime.request(self.profile, "open", duration_seconds=60, now="2026-09-05T12:02:01+00:00")
        message["command_id"] = self.sent[-1][1]["command_id"]
        self.runtime.observe_node(self.profile.node_id, message, now="2026-09-05T12:02:02+00:00")
        self.assertEqual([], self.runtime.profiles())

    def test_invalid_exchange_or_foreign_idle_cannot_persist_an_owner(self):
        for response, idle in [(self.summary, self.idle), (self.response, self.watering)]:
            with self.assertRaises(ValueError):
                self.runtime.enroll(self.profile, command=self.open_frame, response=response,
                    idle=idle, exchange_at="2026-09-05T12:00:00+00:00",
                    idle_at="2026-09-05T12:01:03+00:00", now="2026-09-05T12:01:05+00:00")
            self.assertEqual([], self.store.htv145_control_states())
        self.assertEqual([], self.sent)

    def test_all_stock_acknowledgments_match_without_using_command_sequence(self):
        from rainpointd.valve_protocol import build_htv145_report_ack
        stock = json.loads((ROOT / "research/fixtures/htv145_selector2_stock_pairing_control_20260905.json").read_text())
        for report in stock["valve_reports"]:
            ack = min(stock["gateway_report_acknowledgments"], key=lambda a: abs(a["sync_seconds"] - report["sync_seconds"]))
            self.assertEqual(bytes.fromhex(ack["frame"]), build_htv145_report_ack(
                bytes.fromhex(report["frame"]), self.profile.link, int(ack["residue"], 16)))
        for frame in [self.open_frame, self.response, bytes(38)]:
            with self.assertRaises(ValueError):
                build_htv145_report_ack(frame, self.profile.link, 0x4f03)

    def test_new_flag10_result3_does_not_confirm_idle_or_a_counter(self):
        self.enroll()
        self.coordinator.request_close(self.profile, started_at="2026-09-05T12:02:00+00:00")
        body = bytes.fromhex("508683104f8000000040800056800000000000000000")
        frame = bytearray(self.response); frame[13] = 0x82; frame[14:36] = body
        frame[-2:] = (binascii.crc_hqx(frame[:-2], 0) ^ 0xc713).to_bytes(2, "big")
        self.runtime.observe_frame(bytes(frame), now="2026-09-05T12:02:01+00:00")
        state = self.store.htv145_control_states()[0]
        self.assertFalse(state["counter_synchronized"])
        self.assertEqual("2026-09-05T12:01:03+00:00", state["confirmed_at"])
        self.assertEqual("negative_command_result_3", state["last_result"])


    def test_close_when_freshly_idle_preserves_counter_without_transmitting(self):
        self.enroll(); self.sent.clear()
        result = self.runtime.request(self.profile, "close", now="2026-09-05T12:02:00+00:00")
        self.assertEqual("already_idle", result["reason"])
        self.assertEqual([], self.sent)
        self.assertTrue(self.store.htv145_control_states()[0]["counter_synchronized"])

    def test_legacy_acceptance_cannot_replace_a_persistent_ack_owner(self):
        self.enroll(); self.sent.clear()
        with self.assertRaisesRegex(RuntimeError, "revoke"):
            self.coordinator.configure(replace(self.profile, report_ack_center_hz=None),
                observed_at="2026-09-05T12:02:00+00:00")
        self.assertEqual(433518905, self.store.htv145_control_states()[0]["report_ack_center_hz"])
        self.assertEqual([], self.sent)


class Htv145IdleCounterSyncTest(unittest.TestCase):
    def setUp(self):
        Htv145RuntimeTest.setUp(self)
        self.node["capabilities"].append("htv145_idle_anchor")
        self.coordinator.configure(self.profile, observed_at="2026-09-06T09:00:00+00:00")
        self.fixture = json.loads((ROOT / "research/fixtures/htv145_idle_result3_counter_recovery_20260906.json").read_text())
        self.idle = bytes.fromhex(self.fixture["initial_idle_frame"])
        self.anchor = bytes.fromhex(self.fixture["transactions"][0]["response_frame"])
        self.sync = self.runtime.counter_sync
        self.at = lambda seconds=0: (datetime(2026, 9, 6, 9, 30, tzinfo=timezone.utc) + timedelta(seconds=seconds)).isoformat()

    def queue(self):
        return self.sync.request(self.profile, now=self.at())

    def report(self, seconds=1, node=None, frame=None):
        self.runtime.observe_counter_sync_report(frame or self.idle,
            node or self.profile.node_id, now=self.at(seconds))

    def test_unknown_counter_waits_for_new_owner_idle_and_result3_anchors_only_counter(self):
        self.assertEqual("waiting_for_report", self.queue()["state"])
        self.assertEqual([], self.sent)
        self.report(0)
        self.report(1, node="rp-665544332211")
        self.report(1, frame=self.watering)
        self.assertEqual([], self.sent)
        self.report()
        self.assertEqual(["htv145_control_idle_anchor"], [c["type"] for _, c in self.sent])
        before = self.store.htv145_control_states()[0]
        self.assertEqual("idle_anchor", before["pending_action"])
        self.assertFalse(before["counter_synchronized"])
        self.runtime.observe_frame(self.idle, now=self.at(1.1))
        self.assertEqual(before["pending_command_id"], self.store.htv145_control_states()[0]["pending_command_id"])
        physical = self.store.htv145_control_states()[0]
        self.runtime.observe_frame(self.anchor, now=self.at(2))
        state = self.store.htv145_control_states()[0]
        self.assertTrue(state["counter_synchronized"])
        self.assertEqual(128, state["next_sequence"])
        self.assertEqual(physical["confirmed_at"], state["confirmed_at"])
        self.assertEqual(physical["last_response_frame"], state["last_response_frame"])
        self.assertEqual(3, self.sync.status(self.profile, now=self.at(2))["result_code"])
        self.assertEqual("Ready", self.sync.status(self.profile, now=self.at(2))["status"])
        self.runtime.observe_frame(self.anchor, now=self.at(3))
        self.assertEqual(1, len(self.sent))
        self.runtime.restored[self.profile.valve_endpoint] = ("connection-1", "test")
        request = self.runtime.request(self.profile, "open", duration_seconds=60, now=self.at(17))
        self.assertEqual(128, request["expected_sequence"])
        self.runtime.observe_frame(bytes.fromhex(self.fixture["transactions"][1]["response_frame"]), now=self.at(18))
        self.assertTrue(self.store.htv145_control_states()[0]["counter_synchronized"])
        self.assertEqual(129, self.store.htv145_control_states()[0]["next_sequence"])

    def test_captured_nonzero_usage_anchor_leads_to_positive_control_and_owner_idle(self):
        trial = json.loads((ROOT / "research/fixtures/htv145_custom_identity_first_open_20260908.json").read_text())["corrected_standard_firmware_trial"]
        self.queue()
        self.report()
        self.runtime.observe_frame(bytes.fromhex(trial["anchor_frame"]), now=self.at(2))
        self.assertEqual(128, self.store.htv145_control_states()[0]["next_sequence"])
        self.runtime.restored[self.profile.valve_endpoint] = ("connection-1", "test")
        command = self.runtime.request(self.profile, "open", duration_seconds=60, now=self.at(17))
        self.assertEqual(128, command["expected_sequence"])
        self.runtime.observe_frame(bytes.fromhex(trial["open_response_frame"]), now=self.at(18))
        self.assertEqual(129, self.store.htv145_control_states()[0]["next_sequence"])
        self.runtime.observe_counter_sync_report(bytes.fromhex(trial["idle_frame"]), self.profile.node_id, now=self.at(80))
        self.runtime.observe_frame(bytes.fromhex(trial["idle_frame"]), now=self.at(80))
        self.assertFalse(self.store.htv145_control_states()[0]["confirmed_watering"])
        self.assertTrue(self.runtime.status(self.profile, now=self.at(81))["ready"])

    def test_fixture_qualifies_two_idle_anchors_with_successful_controls_and_rollover(self):
        from rainpointd.valve_protocol import decode_htv145_command_response, decode_htv145_command_error, decode_htv145_idle_anchor_response, decode_htv145_state_report
        transactions = self.fixture["transactions"]
        self.assertEqual([0,1,2,62,63,0], [t["phase"] for t in transactions])
        runtime = self.fixture["runtime_verification"]
        self.assertFalse(runtime["initial_counter_synchronized"])
        self.assertEqual(128,runtime["confirmed_next_sequence"])
        self.assertEqual(transactions[0]["response_frame"],runtime["anchor_response_frame"])
        self.assertEqual([128,129],[c["expected_sequence"] for c in runtime["normal_commands"]])
        self.assertTrue(runtime["final_counter_synchronized"])
        self.assertEqual(129,runtime["final_next_sequence"])
        self.assertFalse(runtime["final_watering"])

        for index, transaction in enumerate(transactions):
            frame = bytes.fromhex(transaction["response_frame"])
            if index in (0,3):
                self.assertEqual(3, decode_htv145_command_error(frame, self.profile.link)["result_code"])
                self.assertIsNone(decode_htv145_command_response(frame, self.profile.link))
            else:
                self.assertEqual(transaction["watering"], decode_htv145_command_response(frame, self.profile.link)["watering"])
                self.assertEqual(transaction["watering"], decode_htv145_state_report(bytes.fromhex(transaction["independent_frame"]), self.profile.link)["watering"])
        self.assertEqual({"sequence":128, "result_code":3}, decode_htv145_idle_anchor_response(self.anchor, self.profile.link))
        for offset, value in ((13,129), (14,0xd0), (17,0), (5,0xff)):
            frame = bytearray(self.anchor); frame[offset] = value
            frame[-2:] = (binascii.crc_hqx(frame[:-2], 0) ^ 0x4f03).to_bytes(2,"big")
            self.assertIsNone(decode_htv145_idle_anchor_response(bytes(frame), self.profile.link))

    def test_result3_without_anchor_reservation_never_authenticates(self):
        self.runtime.observe_frame(self.anchor, now=self.at())
        self.assertFalse(self.store.htv145_control_states()[0]["counter_synchronized"])
        self.queue(); self.report()
        self.runtime.observe_frame(self.anchor, now=self.at(6))
        self.assertFalse(self.store.htv145_control_states()[0]["counter_synchronized"])
        self.coordinator.readiness(self.profile, observed_at=self.at(20))
        self.assertEqual("waiting_for_report", self.sync.status(self.profile, now=self.at(20))["state"])
        self.assertEqual(1, len(self.sent))

    def test_watering_report_aborts_anchor_and_cannot_authenticate(self):
        self.queue(); self.report()
        self.runtime.observe_frame(self.watering, now=self.at(2))
        self.runtime.observe_frame(self.anchor, now=self.at(3))
        state = self.store.htv145_control_states()[0]
        self.assertTrue(state["confirmed_watering"])
        self.assertFalse(state["counter_synchronized"])
        self.assertIsNone(state["pending_command_id"])
        self.assertEqual("failed", self.sync.status(self.profile, now=self.at(3))["state"])

    def test_disabled_or_old_owner_cannot_queue_and_cancel_expiry_never_transmit(self):
        self.node["capabilities"].remove("htv145_idle_anchor")
        with self.assertRaises(RuntimeError): self.queue()
        self.node["capabilities"].append("htv145_idle_anchor")
        self.queue()
        self.sync.configure(self.profile, {"enabled":False}, now=self.at(1))
        self.report(2)
        self.assertEqual([], self.sent)
        self.sync.request(self.profile, now=self.at(3), wait_seconds=15)
        self.sync.tick(self.profile, now=self.at(19))
        self.report(20)
        self.assertEqual([], self.sent)
        self.assertEqual("failed", self.sync.status(self.profile, now=self.at(20))["state"])

    def test_restart_preserves_queue_and_never_replays_pending_anchor(self):
        from rainpointd.htv145_runtime import Htv145Runtime
        self.queue()
        self.store.close()
        self.store = SQLiteEventStore(Path(self.temp.name) / "events.sqlite3")
        self.coordinator = Htv145ControlCoordinator(store=self.store, sender=lambda n,c:self.sent.append((n,c)), enabled=True)
        self.runtime = Htv145Runtime(self.coordinator, lambda _:self.node)
        self.runtime.tick(now=self.at(1))
        self.assertEqual(["htv145_control_configure"], [c["type"] for _,c in self.sent])
        self.sent.clear(); self.report(2)
        self.assertEqual(1,len(self.sent))
        self.runtime = Htv145Runtime(self.coordinator, lambda _:self.node)
        self.runtime.tick(now=self.at(3))
        self.runtime.tick(now=self.at(30))
        self.assertEqual(1, len([c for _,c in self.sent if c["type"]=="htv145_control_idle_anchor"]))
        self.assertFalse(self.store.htv145_control_states()[0]["counter_synchronized"])

    def test_daily_window_once_per_date_waits_for_report_and_never_catches_up(self):
        self.sync.configure(self.profile, {"enabled":True, "timezone":"America/New_York"}, now=self.at(-60))
        self.sync.tick(self.profile, now=self.at(-1))
        self.assertEqual([], self.sent)
        self.sync.tick(self.profile, now=self.at())
        self.assertEqual("waiting_for_report", self.sync.status(self.profile, now=self.at())["state"])
        self.assertEqual([], self.sent)
        self.report(); self.runtime.observe_frame(self.anchor, now=self.at(2))
        self.sync.tick(self.profile, now=self.at(60))
        self.assertEqual(1,len(self.sent))
        self.sync.tick(self.profile, now=self.at(86400+3600))
        self.assertEqual(1,len(self.sent))
        self.store.delete_htv145_control(self.profile.valve_endpoint)
        self.assertEqual({},self.store.htv145_counter_sync(self.profile.valve_endpoint))


    def test_schema21_migration_preserves_owner_and_counter(self):
        before = self.store.htv145_control_states()[0]
        self.store._connection.execute("DROP TABLE htv145_counter_sync")
        self.store._connection.execute("PRAGMA user_version=21")
        self.store._connection.commit(); self.store.close()
        self.store = SQLiteEventStore(Path(self.temp.name) / "events.sqlite3")
        self.assertEqual(23,self.store.schema_version())
        self.assertEqual(before,self.store.htv145_control_states()[0])
        self.assertEqual({},self.store.htv145_counter_sync(self.profile.valve_endpoint))

    def test_anchor_dispatch_failure_retries_only_on_fresh_report_within_budget(self):
        self.queue()
        def fail(node, command):
            self.sent.append((node,command))
            raise ConnectionError("radio disconnected")
        self.coordinator.sender = fail
        self.report()
        self.report(20)
        state = self.store.htv145_control_states()[0]
        self.assertFalse(state["counter_synchronized"])
        self.assertIsNone(state["pending_command_id"])
        self.assertEqual("waiting_for_report",self.sync.status(self.profile,now=self.at(20))["state"])
        self.assertEqual(2,len(self.sent))
        self.report(40)
        self.report(60)
        self.assertEqual(3,len(self.sent))
        self.assertEqual("failed",self.sync.status(self.profile,now=self.at(60))["state"])

    def test_anchor_respects_last_command_spacing(self):
        self.queue()
        with self.store._connection:
            self.store._connection.execute("UPDATE htv145_control_state SET last_command_started_at=?",(self.at(-10),))
        self.report(1)
        self.assertEqual([],self.sent)
        self.report(6)
        self.assertEqual(1,len(self.sent))


    def fail_anchor(self, seconds, reason="idle_anchor_response_timeout"):
        state = self.store.htv145_control_states()[0]
        self.store.fail_htv145_command(valve_endpoint=self.profile.valve_endpoint,
            command_id=state["pending_command_id"], reason=reason, observed_at=self.at(seconds))

    def test_three_total_attempts_require_new_reports_and_preserve_deadline(self):
        initial = self.queue()
        for attempt, second in enumerate((1, 21, 41), 1):
            self.report(second)
            pending = self.sync.status(self.profile, now=self.at(second))
            self.assertEqual(attempt, pending["attempt_count"])
            self.assertEqual(initial["deadline"], pending["deadline"])
            self.fail_anchor(second + 3)
            status = self.sync.status(self.profile, now=self.at(second + 3))
            self.assertFalse(status["ready"])
            self.assertEqual("failed" if attempt == 3 else "waiting_for_report", status["state"])
            # Neither a timer tick, the old report, nor an early duplicate can transmit.
            self.sync.tick(self.profile, now=self.at(second + 4))
            self.report(second)
            self.report(second + 5)
            self.assertEqual(attempt, len(self.sent))
            # A repeated button press while waiting cannot reset the budget/window.
            if attempt < 3:
                repeated = self.sync.request(self.profile, now=self.at(second + 6))
                self.assertEqual(attempt, repeated["attempt_count"])
                self.assertEqual(initial["deadline"], repeated["deadline"])
        self.report(80)
        self.assertEqual(3, len(self.sent))
        self.assertEqual(3, len({c["command_id"] for _, c in self.sent}))
        self.assertTrue(status["reason"].startswith("attempt_limit_reached:"))

    def test_retry_succeeds_on_second_report_and_late_old_status_cannot_finish_it(self):
        self.queue(); self.report(1)
        old_command = self.sent[-1][1]["command_id"]
        self.fail_anchor(4)
        self.runtime.observe_frame(self.anchor, now=self.at(5))
        self.assertFalse(self.store.htv145_control_states()[0]["counter_synchronized"])
        self.report(20)
        self.runtime.observe_node(self.profile.node_id, {"type":"htv145_control_candidate",
            "node_id":self.profile.node_id, "command_id":old_command, "state":"confirmed", "frame":self.anchor.hex()}, now=self.at(21))
        self.assertIsNotNone(self.store.htv145_control_states()[0]["pending_command_id"])
        self.runtime.observe_frame(self.anchor, now=self.at(21))
        status = self.sync.status(self.profile, now=self.at(22))
        self.assertTrue(status["ready"])
        self.assertEqual(2, status["attempt_count"])
        self.report(40)
        self.assertEqual(2,len(self.sent))

    def test_retry_budget_survives_restart_without_replaying_a_command(self):
        from rainpointd.htv145_runtime import Htv145Runtime
        self.queue(); self.report(1); self.fail_anchor(4)
        self.store.close()
        self.store = SQLiteEventStore(Path(self.temp.name) / "events.sqlite3")
        self.coordinator = Htv145ControlCoordinator(store=self.store,
            sender=lambda n,c:self.sent.append((n,c)), enabled=True)
        self.runtime = Htv145Runtime(self.coordinator, lambda _:self.node)
        self.runtime.tick(now=self.at(18))
        self.assertEqual(1,len([c for _,c in self.sent if c["type"]=="htv145_control_idle_anchor"]))
        self.report(20)
        self.assertEqual(2,self.runtime.counter_sync.status(self.profile,now=self.at(20))["attempt_count"])

    def test_retry_window_expiry_and_cancel_stop_without_rf(self):
        self.sync.request(self.profile, now=self.at(), wait_seconds=30)
        self.report(1); self.fail_anchor(4)
        self.sync.tick(self.profile, now=self.at(31))
        self.report(32)
        self.assertEqual(1,len(self.sent))
        self.assertEqual("failed",self.sync.status(self.profile,now=self.at(32))["state"])
        self.sync.request(self.profile, now=self.at(40))
        self.report(41); self.fail_anchor(44)
        self.sync.configure(self.profile,{"enabled":False},now=self.at(45))
        self.report(60)
        self.assertEqual(2,len(self.sent))
        self.assertEqual("cancelled",self.sync.status(self.profile,now=self.at(60))["state"])

    def test_protocol_rejection_is_terminal_and_legacy_pending_request_is_not_retried(self):
        self.queue(); self.report(1)
        self.fail_anchor(2, "negative_command_result_3")
        self.report(20)
        self.assertEqual(1,len(self.sent))
        self.assertEqual("failed",self.sync.status(self.profile,now=self.at(20))["state"])
        self.sync.request(self.profile,now=self.at(30)); self.report(31)
        data=self.store.htv145_counter_sync(self.profile.valve_endpoint)
        data.pop("max_attempts"); data.pop("attempt_count")
        self.store.save_htv145_counter_sync(self.profile.valve_endpoint,data)
        self.fail_anchor(34)
        self.report(50)
        self.assertEqual(2,len(self.sent))
        self.assertEqual("failed",self.sync.status(self.profile,now=self.at(50))["state"])


    def test_daily_exhaustion_does_not_start_another_batch_in_same_window(self):
        self.sync.configure(self.profile, {"enabled":True,"timezone":"America/New_York"}, now=self.at(-1))
        self.sync.tick(self.profile,now=self.at())
        for second in (1,21,41):
            self.report(second); self.fail_anchor(second+3)
        self.sync.tick(self.profile,now=self.at(100))
        self.report(101)
        self.assertEqual(3,len(self.sent))
        self.assertEqual("failed",self.sync.status(self.profile,now=self.at(101))["state"])
        self.sync.tick(self.profile,now=self.at(86400))
        status=self.sync.status(self.profile,now=self.at(86400))
        self.assertEqual("waiting_for_report",status["state"])
        self.assertEqual(0,status["attempt_count"])
        self.assertEqual(3,len(self.sent))

    def test_failure_at_window_end_and_status_timeout_do_not_extend_deadline(self):
        self.sync.request(self.profile,now=self.at(),wait_seconds=3)
        self.report(1); self.fail_anchor(4)
        self.assertEqual("failed",self.sync.status(self.profile,now=self.at(4))["state"])
        self.report(20)
        self.assertEqual(1,len(self.sent))
        self.sync.request(self.profile,now=self.at(30),wait_seconds=60)
        self.report(31)
        status=self.sync.status(self.profile,now=self.at(50))
        self.assertEqual("waiting_for_report",status["state"])
        self.assertEqual(self.at(90),status["deadline"])
        self.assertEqual(self.at(50),status["report_after"])
        self.assertEqual("Waiting for idle report (attempt 2/3)",status["status"])
