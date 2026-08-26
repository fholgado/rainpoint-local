#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "rainpointd_addon"))

from rainpointd.gateway import Gateway, _observed_utc
from rainpointd.http import create_server
from rainpointd.ingest import FrameIngestor
from rainpointd.pairing import HCS026EnrollmentManager
from rainpointd.product_identity import (
    GENERIC_HCS02X_MODEL,
    HCS02X_PROTOCOL,
)
from rainpointd.replay import ReplayTransport, load_fixtures
from rainpointd.valve_protocol import ValveLink, build_open_frame


class GatewayTest(unittest.TestCase):
    HTV405_OPEN_RESPONSE_SEQUENCE_6 = (
        "79f4882f28b984028094a9801306d0868010cf80000000409e00569e"
        "00000000000000005878"
    )

    def test_local_rf_controller_identity_is_unique_persistent_and_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(storage_path=str(path))
            first = gateway.info()["rf_controller_identity"]
            self.assertTrue(first["persistent"])
            self.assertEqual(0x80, bytes.fromhex(first["companion_endpoint"])[-1])
            self.assertFalse(bytes.fromhex(first["companion_endpoint"])[0] & 0x80)
            self.assertTrue(bytes.fromhex(first["controller_endpoint"])[0] & 0x80)
            self.assertEqual(
                bytes.fromhex(first["companion_endpoint"])[1:],
                bytes.fromhex(first["controller_endpoint"])[1:],
            )
            self.assertNotEqual("39840280", first["companion_endpoint"])
            gateway.close()

            restored = Gateway(storage_path=str(path))
            second = restored.info()["rf_controller_identity"]
            self.assertEqual(first["companion_endpoint"], second["companion_endpoint"])
            self.assertEqual(first["controller_endpoint"], second["controller_endpoint"])
            self.assertIn(
                second["controller_endpoint"],
                restored.catalog.hcs026_pairing_peers,
            )
            restored.close()

    def test_timestamp_normalization_portability_matrix(self) -> None:
        explicit = {
            "2026-01-15T12:00:00Z": "2026-01-15T12:00:00+00:00",
            "2026-01-15T12:00:00+05:30": "2026-01-15T06:30:00+00:00",
            "2026-01-15T12:00:00-08:00": "2026-01-15T20:00:00+00:00",
            # Both occurrences of the North American repeated fall-back hour.
            "2026-11-01T01:30:00-04:00": "2026-11-01T05:30:00+00:00",
            "2026-11-01T01:30:00-05:00": "2026-11-01T06:30:00+00:00",
            # Both occurrences of the European repeated fall-back hour.
            "2026-10-25T02:30:00+02:00": "2026-10-25T00:30:00+00:00",
            "2026-10-25T02:30:00+01:00": "2026-10-25T01:30:00+00:00",
        }
        for observed, expected in explicit.items():
            with self.subTest(observed=observed):
                self.assertEqual(
                    datetime.fromisoformat(expected), _observed_utc(observed)
                )

        previous_timezone = os.environ.get("TZ")
        try:
            legacy_local = {
                ("UTC", "2026-01-15T12:00:00"): "2026-01-15T12:00:00+00:00",
                ("Asia/Kolkata", "2026-01-15T12:00:00"): "2026-01-15T06:30:00+00:00",
                ("America/New_York", "2026-01-15T12:00:00"): "2026-01-15T17:00:00+00:00",
                ("America/New_York", "2026-07-15T12:00:00"): "2026-07-15T16:00:00+00:00",
                ("Europe/Berlin", "2026-01-15T12:00:00"): "2026-01-15T11:00:00+00:00",
                ("Europe/Berlin", "2026-07-15T12:00:00"): "2026-07-15T10:00:00+00:00",
            }
            for (zone, observed), expected in legacy_local.items():
                with self.subTest(zone=zone, observed=observed):
                    os.environ["TZ"] = zone
                    time.tzset()
                    self.assertEqual(
                        datetime.fromisoformat(expected),
                        _observed_utc(observed),
                    )
        finally:
            if previous_timezone is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous_timezone
            time.tzset()

    @staticmethod
    def _gateway_with_pending_htv405_open(path: Path) -> Gateway:
        gateway = Gateway(
            storage_path=str(path),
            valve_control_enabled=True,
        )
        assert gateway._store is not None
        gateway._store.upsert_valve_link(
            controller_endpoint="b9c40280",
            valve_endpoint="94a98013",
            device_id="htv405-94a98013",
            name="Test four-zone valve",
            model="HTV405FRF",
            area="Garden",
            accepted_at="2026-08-24T20:00:00+00:00",
        )
        gateway._store.update_valve_control_profile(
            valve_endpoint="94a98013",
            node_id="rp-001122334455",
            companion_endpoint="39840280",
            selector=0x05,
            frequency_offset_hz=97_154,
            observed_at="2026-08-24T20:00:01+00:00",
        )
        gateway._store.synchronize_htv405_control_counter(
            valve_endpoint="94a98013",
            node_id="rp-001122334455",
            next_sequence=6,
            source="retained_association_capture",
            observed_at="2026-08-24T20:00:02+00:00",
        )
        gateway._refresh_registry_catalog()
        gateway._ensure_registered_valve_devices()
        gateway.update_node(
            "rp-001122334455",
            connected=True,
            authenticated=True,
            tx_armed=False,
            capabilities=["rx", "valve_control_tx_candidate"],
        )
        gateway.set_node_command_sender(lambda _node_id, _command: None)
        gateway.request_htv405_control(
            device_id="htv405-94a98013",
            action="open",
            zone=1,
            duration_seconds=60,
            now=datetime.fromisoformat("2026-08-24T20:00:20+00:00"),
        )
        return gateway

    def test_authenticated_node_air_response_confirms_pending_open(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            gateway = self._gateway_with_pending_htv405_open(
                Path(temporary_directory) / "rainpoint.sqlite3"
            )
            self.assertIsNone(
                gateway.observe_valve_control_air_response(
                    "rp-aabbccddeeff",
                    self.HTV405_OPEN_RESPONSE_SEQUENCE_6,
                    observed_at="2026-08-24T20:00:20.900000+00:00",
                )
            )
            pending = gateway._store.valve_registry()[0]
            self.assertIsNotNone(pending["control_pending_command_id"])

            accepted = gateway.observe_valve_control_air_response(
                "rp-001122334455",
                self.HTV405_OPEN_RESPONSE_SEQUENCE_6,
                observed_at="2026-08-24T20:00:20.900000+00:00",
            )

            self.assertIsNotNone(accepted)
            assert accepted is not None
            self.assertIsNone(accepted["control_pending_command_id"])
            self.assertEqual(7, accepted["control_next_sequence"])
            self.assertTrue(accepted["control_confirmed_watering"])
            self.assertEqual(1, accepted["control_active_zone"])
            self.assertEqual(433_518_527, accepted["control_center_hz"])
            self.assertEqual(
                "valve_control_confirmed", gateway.events()[-1]["event_type"]
            )
            gateway.close()

    def test_restart_recovers_journaled_response_then_later_idle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = self._gateway_with_pending_htv405_open(path)
            gateway.observe_rf_frame(
                frame=self.HTV405_OPEN_RESPONSE_SEQUENCE_6,
                state={
                    "rf_receiver_id": "rp-001122334455",
                    "rf_frame_accepted": True,
                },
                observed_at="2026-08-24T20:00:20.900000+00:00",
                device_id="htv405-94a98013",
            )
            gateway.observe_decoded(
                device_id="htv405-94a98013",
                name="Test four-zone valve",
                model="HTV405FRF",
                frame="idle-after-bounded-run",
                state={
                    "rf_endpoint_b": "94a98013",
                    "rf_frame_accepted": True,
                    "is_watering": False,
                    "active_zone": None,
                    "valve_state": "idle",
                },
                observed_at="2026-08-24T20:01:21+00:00",
            )
            gateway.observe_decoded(
                device_id="htv405-94a98013",
                name="Test four-zone valve",
                model="HTV405FRF",
                frame="later-ambiguous-heartbeat",
                state={
                    "rf_endpoint_b": "94a98013",
                    "rf_frame_accepted": True,
                    "is_watering": None,
                    "active_zone": None,
                    "valve_state": "idle",
                },
                observed_at="2026-08-24T20:02:21+00:00",
            )
            gateway.close()

            restored = Gateway(
                storage_path=str(path),
                valve_control_enabled=True,
            )
            assert restored._store is not None
            registration = restored._store.valve_registry()[0]
            self.assertIsNone(registration["control_pending_command_id"])
            self.assertEqual(7, registration["control_next_sequence"])
            self.assertFalse(registration["control_confirmed_watering"])
            self.assertIsNone(registration["control_active_zone"])
            self.assertEqual(
                "automatic_idle_confirmed_from_telemetry",
                registration["control_last_result"],
            )
            restored_device = next(
                item
                for item in restored.devices()
                if item["device_id"] == "htv405-94a98013"
            )
            self.assertFalse(restored_device["state"]["is_watering"])
            self.assertEqual(
                "2026-08-24T20:01:21+00:00",
                restored_device["state_observed_at"],
            )
            restored.close()

    def test_phase_only_htv405_report_preserves_definitive_state(self) -> None:
        gateway = Gateway()
        gateway.observe_decoded(
            device_id="htv405-94a98013",
            name="Test four-zone valve",
            model="HTV405FRF",
            frame="definitive-idle",
            state={
                "rf_endpoint_b": "94a98013",
                "rf_frame_accepted": True,
                "is_watering": False,
                "active_zone": None,
                "valve_state": "idle",
            },
            observed_at="2026-08-24T20:01:21+00:00",
        )
        gateway.observe_decoded(
            device_id="htv405-94a98013",
            name="Test four-zone valve",
            model="HTV405FRF",
            frame="phase-only-heartbeat",
            state={
                "rf_endpoint_b": "94a98013",
                "rf_frame_accepted": True,
                "is_watering": None,
                "active_zone": None,
                "valve_state": "idle",
            },
            observed_at="2026-08-24T20:02:21+00:00",
        )

        device = gateway.devices(
            now=datetime.fromisoformat("2026-08-24T20:02:21+00:00")
        )[0]
        self.assertFalse(device["state"]["is_watering"])
        self.assertEqual(
            "2026-08-24T20:01:21+00:00", device["state_observed_at"]
        )
        self.assertEqual(
            "2026-08-24T20:02:21+00:00", device["observed_at"]
        )
        gateway.close()

    def test_authenticated_network_ingest_confirms_air_response(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            gateway = self._gateway_with_pending_htv405_open(
                Path(temporary_directory) / "rainpoint.sqlite3"
            )
            ingestor = FrameIngestor(
                gateway,
                receiver_id="rp-001122334455",
            )

            published = ingestor.consume_event(
                {
                    "time": "2026-08-24T20:00:20.900000+00:00",
                    "rows": [
                        {
                            "len": len(
                                self.HTV405_OPEN_RESPONSE_SEQUENCE_6
                            )
                            * 4,
                            "data": self.HTV405_OPEN_RESPONSE_SEQUENCE_6,
                        }
                    ],
                }
            )

            self.assertEqual(1, published)
            registration = gateway._store.valve_registry()[0]
            self.assertIsNone(registration["control_pending_command_id"])
            self.assertEqual(7, registration["control_next_sequence"])
            self.assertTrue(registration["control_confirmed_watering"])
            gateway.close()

    def test_invalid_trailer_cannot_discover_a_phantom_htv405_link(self) -> None:
        corrupted = (
            "79f4882f28b984068094a98013108107820580804f80000000408000568"
            "00000000000000043ed"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            gateway = Gateway(
                storage_path=str(
                    Path(temporary_directory) / "rainpoint.sqlite3"
                )
            )
            ingestor = FrameIngestor(gateway, receiver_id="rp-001122334455")

            published = ingestor.consume_event(
                {
                    "time": "2026-08-25T16:34:29.137286+00:00",
                    "rows": [
                        {
                            "len": len(corrupted) * 4,
                            "data": corrupted,
                        }
                    ],
                }
            )

            self.assertEqual(1, published)
            assert gateway._store is not None
            self.assertEqual([], gateway._store.valve_registry())
            self.assertEqual([], gateway.devices())
            event = gateway.events()[-1]
            self.assertFalse(event["state"]["rf_frame_accepted"])
            gateway.close()

    def test_legacy_invalid_htv405_snapshot_is_removed_by_migration(self) -> None:
        device_id = "htv405-95a98013"
        endpoint = "95a98013"
        event = {
            "event_id": 1,
            "event_type": "device_observation",
            "observed_at": "2026-08-25T09:20:53.097242+00:00",
            "device_id": device_id,
            "name": "Legacy phantom valve",
            "model": "HTV405FRF",
            "raw": "legacy-corrupted-frame",
            "state": {
                "rf_endpoint_a": "b9840280",
                "rf_endpoint_b": endpoint,
                "rf_trailer_valid": False,
                "rf_frame_accepted": True,
            },
        }
        payload = json.dumps(event)
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(storage_path=str(path))
            assert gateway._store is not None
            connection = gateway._store._connection
            connection.execute(
                "INSERT INTO events(event_id, observed_at, event_type, payload) "
                "VALUES (?, ?, ?, ?)",
                (1, event["observed_at"], event["event_type"], payload),
            )
            connection.execute(
                "INSERT INTO device_snapshots(device_id, event_id, payload) "
                "VALUES (?, ?, ?)",
                (device_id, 1, payload),
            )
            connection.execute(
                "INSERT INTO endpoints(endpoint, first_seen, last_seen, "
                "frame_count, last_frame) VALUES (?, ?, ?, 1, ?)",
                (endpoint, event["observed_at"], event["observed_at"], event["raw"]),
            )
            connection.execute("PRAGMA user_version = 15")
            connection.commit()
            gateway.close()

            restored = Gateway(storage_path=str(path))
            assert restored._store is not None
            self.assertEqual(16, restored._store.schema_version())
            self.assertEqual([], restored.devices())
            self.assertTrue(restored.endpoint_suppressed(endpoint))
            self.assertNotIn(
                endpoint,
                {item["endpoint"] for item in restored.endpoints()},
            )
            self.assertEqual(1, len(restored.events()))
            restored.close()

    def test_observation_only_valve_can_be_forgotten_and_suppressed(self) -> None:
        device_id = "htv405-94a9a013"
        endpoint = "94a9a013"
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(storage_path=str(path))
            gateway.observe_decoded(
                device_id=device_id,
                name="Observation-only valve",
                model="HTV405FRF",
                frame="accepted-evidence",
                observed_at="2026-08-25T12:00:00+00:00",
                state={
                    "rf_endpoint_a": "b9840280",
                    "rf_endpoint_b": endpoint,
                    "rf_trailer_valid": True,
                    "rf_frame_accepted": True,
                },
            )

            self.assertIn("forget", gateway.devices()[0]["capabilities"])
            forgotten = gateway.forget_registry_device(device_id)

            self.assertEqual(endpoint, forgotten["endpoint"])
            self.assertEqual([], gateway.devices())
            self.assertTrue(gateway.endpoint_suppressed(endpoint))
            self.assertEqual(1, len(gateway.events()))
            gateway.close()

            restored = Gateway(storage_path=str(path))
            self.assertEqual([], restored.devices())
            self.assertTrue(restored.endpoint_suppressed(endpoint))
            self.assertEqual(1, len(restored.events()))
            restored.close()

    def test_forgotten_htv405_link_is_removed_and_suppressed(self) -> None:
        valid = (
            "79f4882f28b984028094a98013108107820580804f80000000408000568"
            "00000000000000043a1"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            gateway = Gateway(
                storage_path=str(
                    Path(temporary_directory) / "rainpoint.sqlite3"
                )
            )
            gateway._store.upsert_valve_link(
                controller_endpoint="b9840280",
                valve_endpoint="94a98013",
                device_id="htv405-94a98013",
                name="Test four-zone valve",
                model="HTV405FRF",
                area="Garden",
                accepted_at="2026-08-25T18:00:00+00:00",
            )
            gateway._refresh_registry_catalog()
            gateway._ensure_registered_valve_devices()

            self.assertIn("forget", gateway.devices()[0]["capabilities"])

            forgotten = gateway.forget_registry_device("htv405-94a98013")

            self.assertEqual("94a98013", forgotten["endpoint"])
            self.assertEqual([], gateway._store.valve_registry())
            self.assertEqual([], gateway.devices())
            self.assertTrue(gateway.endpoint_suppressed("94a98013"))
            self.assertIsNone(
                gateway.register_observed_htv405_link(
                    controller_endpoint="b9840280",
                    valve_endpoint="94a98013",
                    frame=valid,
                    observed_at="2026-08-25T18:01:00+00:00",
                )
            )
            self.assertEqual([], gateway._store.valve_registry())
            gateway.close()

    def test_forgotten_htv145_link_clears_private_control_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            gateway = Gateway(
                storage_path=str(
                    Path(temporary_directory) / "rainpoint.sqlite3"
                )
            )
            assert gateway._store is not None
            gateway._store.upsert_valve_link(
                controller_endpoint="b9840280",
                valve_endpoint="b42d008f",
                device_id="htv145-b42d008f",
                name="Test one-zone valve",
                model="HTV145FRF",
                area="Garden",
                accepted_at="2026-08-25T18:00:00+00:00",
            )
            gateway._store.configure_htv145_control(
                valve_endpoint="b42d008f",
                controller_endpoint="b9840280",
                node_id="rp-001122334455",
                center_hz=433_920_000,
                power_dbm=10,
                invert=False,
                trailer_residual=0xC713,
                updated_at="2026-08-25T18:00:01+00:00",
            )
            gateway._refresh_registry_catalog()
            gateway._ensure_registered_valve_devices()

            forgotten = gateway.forget_registry_device("htv145-b42d008f")

            self.assertEqual("b42d008f", forgotten["endpoint"])
            self.assertEqual([], gateway._store.valve_registry())
            self.assertEqual([], gateway._store.htv145_control_states())
            self.assertTrue(gateway.endpoint_suppressed("b42d008f"))
            gateway.close()

    def test_valve_counter_sync_interprets_naive_rtl433_time_as_local(self) -> None:
        previous_timezone = os.environ.get("TZ")
        try:
            os.environ["TZ"] = "America/New_York"
            time.tzset()
            with tempfile.TemporaryDirectory() as temporary_directory:
                gateway = Gateway(
                    storage_path=str(
                        Path(temporary_directory) / "rainpoint.sqlite3"
                    ),
                    valve_control_enabled=True,
                )
                assert gateway._store is not None
                gateway._store.upsert_valve_link(
                    controller_endpoint="b9840280",
                    valve_endpoint="94a98013",
                    device_id="htv405-94a98013",
                    name="Test four-zone valve",
                    model="HTV405FRF",
                    area="Garden",
                    accepted_at="2026-08-24T20:00:00+00:00",
                )
                gateway._store.update_valve_control_profile(
                    valve_endpoint="94a98013",
                    node_id="rp-001122334455",
                    companion_endpoint="39840280",
                    selector=0x05,
                    frequency_offset_hz=97_154,
                    observed_at="2026-08-24T20:00:01+00:00",
                )
                gateway._refresh_registry_catalog()
                gateway._ensure_registered_valve_devices()
                gateway.observe_decoded(
                    device_id="htv405-94a98013",
                    name="Test four-zone valve",
                    model="HTV405FRF",
                    frame="idle",
                    state={
                        "rf_endpoint_b": "94a98013",
                        "is_watering": False,
                        "valve_state": "idle",
                    },
                    observed_at="2026-08-24T16:00:00",
                )

                synchronized = gateway.synchronize_htv405_control_counter(
                    device_id="htv405-94a98013",
                    next_sequence=6,
                    evidence_source="retained_association_capture",
                    now=datetime.fromisoformat("2026-08-24T20:00:30+00:00"),
                )

                self.assertEqual(6, synchronized["control_next_sequence"])
                self.assertFalse(synchronized["control_confirmed_watering"])
                self.assertEqual(
                    "2026-08-24T20:00:30+00:00",
                    synchronized["control_confirmed_at"],
                )
                gateway.close()
        finally:
            if previous_timezone is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous_timezone
            time.tzset()

    def test_sensor_link_diagnostics_attach_to_endpoint_device(self) -> None:
        gateway = Gateway(transport="rtl433")
        gateway.observe_decoded(
            device_id="soil-test-a",
            name="Test Sensor A",
            model="HCS02x-compatible soil sensor",
            frame="79f4882f28" + "00" * 33,
            state={
                "rf_endpoint": "9bce0024",
                "rf_protocol_family": "rainpoint_hcs02x",
                "rf_frame_accepted": True,
                "soil_moisture_percent": 51,
            },
        )
        gateway.observe_sensor_link_status(
            "rp-001122334455",
            "9bce0024",
            rf_recovery_state="reply_transmitted",
            rf_recovery_phase="paired_message_1",
            rf_recovery_transmissions=1,
            rf_ack_confirmation="pending_observation",
        )
        ack_event = gateway.observe_rf_frame(
            frame="79f4882f28" + "11" * 33,
            state={
                "routine_ack_endpoint": "9bce0024",
                "rf_receiver_id": "local-sdr",
                "rf_frame_accepted": True,
            },
        )
        device = gateway.devices()[0]
        self.assertEqual(
            "rp-001122334455", device["state"]["rf_ack_owner_node_id"]
        )
        self.assertEqual(
            "reply_transmitted", device["state"]["rf_recovery_state"]
        )
        self.assertEqual(
            "paired_message_1", device["state"]["rf_recovery_phase"]
        )
        self.assertIn("rf_link_status_at", device["state"])
        self.assertEqual(
            "observed_over_air", device["state"]["rf_ack_confirmation"]
        )
        self.assertEqual("local-sdr", device["state"]["rf_ack_observer"])
        self.assertEqual(
            "observed_over_air",
            ack_event["state"]["local_ack_confirmation"],
        )
        self.assertEqual("soil-test-a", gateway.events()[-2]["device_id"])
        gateway.close()

    def test_radio_node_metadata_updates_without_rotating_credential(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            gateway = Gateway(
                transport="rtl433",
                storage_path=str(Path(temporary_directory) / "rainpoint.sqlite3"),
            )
            gateway.register_radio_node(
                node_id="rp-001122334455",
                token="ab" * 32,
                name="rp-001122334455",
                area=None,
            )
            updated = gateway.update_radio_node_metadata(
                node_id="rp-001122334455",
                name="Front Yard Radio Node",
                area="Front Yard",
            )
            self.assertEqual("Front Yard Radio Node", updated["name"])
            self.assertEqual("Front Yard", updated["area"])
            self.assertEqual(
                "ab" * 32,
                gateway.radio_node_credential("rp-001122334455"),
            )
            gateway.close()

    def test_known_factory_announcement_requests_bounded_automatic_rejoin(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            gateway = Gateway(
                transport="rtl433",
                storage_path=str(Path(temporary_directory) / "rainpoint.sqlite3"),
            )
            assert gateway._store is not None
            gateway._store.upsert_enrollment_record(
                {
                    "factory_endpoint": "1bce0024",
                    "paired_endpoint": "9bce0024",
                    "enrolled_at": "2026-08-14T00:00:00+00:00",
                    "last_seen_at": "2026-08-14T00:00:00+00:00",
                }
            )
            gateway.register_radio_node(
                node_id="rp-001122334455",
                token="ab" * 32,
                name="Vegetable Garden Radio",
                area="Vegetable Garden",
            )
            commands: list[tuple[str, dict]] = []
            gateway.set_node_command_sender(
                lambda node_id, command: commands.append((node_id, command))
            )
            gateway.update_node(
                "rp-001122334455",
                connected=True,
                authenticated=True,
                protocol_version=2,
                capabilities=[
                    "rx",
                    "sensor_pairing_tx",
                    "routine_sensor_ack_tx",
                ],
            )
            gateway.assign_radio_node_ack(
                node_id="rp-001122334455",
                paired_endpoint="9bce0024",
                assigned_channel=4,
            )
            commands.clear()
            event = gateway.observe_rf_frame(
                frame="79f4882f28" + "00" * 33,
                state={
                    "hcs026_pairing_state": "factory",
                    "hcs026_factory_endpoint": "1bce0024",
                    "rf_receiver_id": "rp-001122334455",
                    "rf_rssi_db": -42.0,
                    "rf_lqi": 12,
                },
            )
            self.assertEqual(1, len(commands))
            node_id, command = commands[0]
            self.assertEqual("rp-001122334455", node_id)
            self.assertEqual("pairing_start", command["type"])
            self.assertEqual("hcs026_auto_v1", command["profile"])
            self.assertEqual("1bce0024", command["factory_endpoint"])
            self.assertEqual(60, command["duration_seconds"])
            self.assertTrue(event["state"]["automatic_rejoin"]["requested"])
            self.assertTrue(commands[-1][1]["known_rejoin"])

            gateway.observe_rf_frame(
                frame="79f4882f29" + "00" * 33,
                state={
                    "hcs026_pairing_state": "factory",
                    "hcs026_factory_endpoint": "1bce0024",
                },
            )
            self.assertEqual(1, len(commands), "rejoin requests are rate limited")
            gateway.close()

    def test_pairing_nodes_include_managed_name_and_area(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            gateway = Gateway(
                transport="rtl433",
                storage_path=str(
                    Path(temporary_directory) / "rainpoint.sqlite3"
                ),
            )
            gateway.register_radio_node(
                node_id="rp-001122334455",
                token="ab" * 32,
                name="Vegetable Garden Radio",
                area="Vegetable Garden",
            )
            gateway.set_node_command_sender(lambda _node_id, _command: None)
            gateway.update_node(
                "rp-001122334455",
                connected=True,
                authenticated=True,
                protocol_version=2,
                capabilities=["rx", "sensor_pairing_tx"],
            )

            pairing_node = gateway.pairing()["pairing_nodes"][0]
            self.assertEqual("Vegetable Garden Radio", pairing_node["name"])
            self.assertEqual("Vegetable Garden", pairing_node["area"])
            self.assertTrue(pairing_node["managed"])
            gateway.close()

    def test_ack_assignment_is_single_owner_and_survives_gateway_restart(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(path))
            assert gateway._store is not None
            gateway._store.upsert_enrollment_record(
                {
                    "factory_endpoint": "1bce0024",
                    "paired_endpoint": "9bce0024",
                    "enrolled_at": "2026-08-14T00:00:00+00:00",
                    "last_seen_at": "2026-08-14T00:00:00+00:00",
                }
            )
            for node_id in ("rp-001122334455", "rp-aabbccddeeff"):
                gateway.register_radio_node(
                    node_id=node_id,
                    token="ab" * 32,
                    name=node_id,
                    area=None,
                )
            commands: list[tuple[str, dict]] = []
            gateway.set_node_command_sender(
                lambda node_id, command: commands.append((node_id, command))
            )
            gateway.update_node(
                "rp-001122334455",
                connected=True,
                capabilities=["rx", "routine_sensor_ack_tx"],
            )
            assignment = gateway.assign_radio_node_ack(
                node_id="rp-001122334455",
                paired_endpoint="9bce0024",
                assigned_channel=4,
            )
            self.assertEqual("rp-001122334455", assignment["node_id"])
            self.assertEqual("routine_ack_configure", commands[-1][1]["type"])
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(path))
            restored_commands: list[tuple[str, dict]] = []
            restored.set_node_command_sender(
                lambda node_id, command: restored_commands.append(
                    (node_id, command)
                )
            )
            restored.update_node(
                "rp-001122334455",
                connected=True,
                capabilities=["rx", "routine_sensor_ack_tx"],
            )
            self.assertEqual(
                1,
                restored.restore_radio_node_ack_assignments(
                    "rp-001122334455"
                ),
            )
            self.assertEqual(
                "9bce0024", restored_commands[-1][1]["paired_endpoint"]
            )
            restored.assign_radio_node_ack(
                node_id="rp-aabbccddeeff",
                paired_endpoint="9bce0024",
                assigned_channel=5,
            )
            self.assertEqual(1, len(restored.ack_assignments()))
            self.assertEqual(
                "rp-aabbccddeeff", restored.ack_assignments()[0]["node_id"]
            )
            self.assertEqual("routine_ack_revoke", restored_commands[-1][1]["type"])
            restored.observe_decoded(
                device_id="hcs026-9bce0024",
                name="Test Sensor A",
                model=GENERIC_HCS02X_MODEL,
                frame="routine",
                state={
                    "rf_endpoint": "9bce0024",
                    "rf_protocol_family": HCS02X_PROTOCOL,
                    "rf_frame_accepted": True,
                    "soil_moisture_percent": 20,
                },
            )
            restored.forget_sensor("hcs026-9bce0024")
            self.assertEqual([], restored.ack_assignments())
            self.assertEqual(
                ("rp-aabbccddeeff", "routine_ack_revoke"),
                (restored_commands[-1][0], restored_commands[-1][1]["type"]),
            )
            restored.close()

    def test_claim_and_rotation_persist_and_revoke_old_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            token_path = Path(temporary_directory) / "management-token"
            gateway = Gateway(
                claim_code="123456",
                registry_token_path=str(token_path),
            )
            self.assertTrue(gateway.info()["claim_available"])
            with self.assertRaises(PermissionError):
                gateway.claim_registry("wrong")
            claimed = gateway.claim_registry("123456")
            self.assertTrue(gateway.registry_authorized(claimed))
            self.assertFalse(gateway.info()["claim_available"])
            self.assertEqual(claimed, token_path.read_text(encoding="utf-8"))

            rotated = gateway.rotate_registry_token()
            self.assertFalse(gateway.registry_authorized(claimed))
            self.assertTrue(gateway.registry_authorized(rotated))
            self.assertEqual(rotated, token_path.read_text(encoding="utf-8"))
            self.assertEqual(0o600, token_path.stat().st_mode & 0o777)

    def test_storage_v4_registry_migrates_identity_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(path))
            gateway.close()

            connection = sqlite3.connect(path)
            connection.execute("DROP TABLE device_registry")
            connection.execute(
                """
                CREATE TABLE device_registry (
                    endpoint TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    model TEXT NOT NULL,
                    area TEXT,
                    accepted_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO device_registry VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "95a98024",
                    "hcs026-95a98024",
                    "Test Sensor B",
                    "HCS026FRF",
                    "Garden",
                    "2026-08-12T12:00:00+00:00",
                    "2026-08-12T12:00:00+00:00",
                ),
            )
            connection.execute(
                "INSERT INTO device_registry VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "9bce0024",
                    "hcs026-9bce0024",
                    "Test Sensor A",
                    "HCS026FRF",
                    "Garden",
                    "2026-08-12T12:00:00+00:00",
                    "2026-08-12T12:00:00+00:00",
                ),
            )
            evidence = {
                "event_id": 1,
                "event_type": "device_observation",
                "observed_at": "2026-08-12T12:01:00+00:00",
                "device_id": "hcs026-95a98024",
                "model": "HCS026FRF",
                "state": {
                    "rf_endpoint": "95a98024",
                    "rf_product_code": 0x48,
                },
            }
            connection.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?)",
                (
                    evidence["event_id"],
                    evidence["observed_at"],
                    evidence["event_type"],
                    json.dumps(evidence),
                ),
            )
            connection.execute("PRAGMA user_version = 4")
            connection.commit()
            connection.close()

            migrated = Gateway(transport="rtl433", storage_path=str(path))
            registrations = {
                item["endpoint"]: item for item in migrated.registry()
            }
            inferred = registrations["95a98024"]
            self.assertEqual(GENERIC_HCS02X_MODEL, inferred["model"])
            self.assertEqual(HCS02X_PROTOCOL, inferred["protocol"])
            self.assertEqual(
                "rf_product_code_family", inferred["model_source"]
            )
            self.assertEqual(0x48, inferred["product_code"])
            self.assertIsNone(inferred["model_code"])
            provisional = registrations["9bce0024"]
            self.assertEqual(GENERIC_HCS02X_MODEL, provisional["model"])
            self.assertEqual(
                "legacy_model_unverified", provisional["model_source"]
            )
            provisional_device = next(
                item
                for item in migrated.devices()
                if item["device_id"] == "hcs026-9bce0024"
            )
            self.assertFalse(
                provisional_device["state"]["product_model_exact"]
            )
            migrated.close()

    def test_storage_schema_migrates_latest_device_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(path))
            gateway.observe_decoded(
                device_id="soil-test",
                name="Test Soil",
                model="HCS026FRF",
                frame="accepted",
                state={
                    "soil_moisture_percent": 44,
                    "rf_frame_accepted": True,
                },
            )
            self.assertEqual(16, gateway.info()["storage_schema_version"])
            gateway.close()

            # Recreate the last released schema while retaining its event log.
            connection = sqlite3.connect(path)
            connection.execute("DROP TABLE device_snapshots")
            connection.execute("PRAGMA user_version = 1")
            connection.commit()
            connection.close()

            migrated = Gateway(transport="rtl433", storage_path=str(path))
            self.assertEqual(16, migrated.info()["storage_schema_version"])
            connection = sqlite3.connect(path)
            registration_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(device_registry)"
                )
            }
            connection.close()
            self.assertTrue(
                {"protocol", "model_source", "product_code", "model_code"}
                <= registration_columns
            )
            connection = sqlite3.connect(path)
            valve_tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            connection.close()
            self.assertIn("valve_registry", valve_tables)
            connection = sqlite3.connect(path)
            ack_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(hcs026_ack_assignments)"
                )
            }
            connection.close()
            self.assertTrue(
                {"controller_endpoint", "companion_endpoint"} <= ack_columns
            )
            connection = sqlite3.connect(path)
            valve_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(valve_registry)"
                )
            }
            connection.close()
            self.assertTrue(
                {
                    "last_sequence",
                    "last_repeat",
                    "next_sequence",
                    "next_repeat",
                    "last_phase_at",
                    "last_phase_frame",
                    "control_node_id",
                    "control_companion_endpoint",
                    "control_selector",
                    "control_frequency_offset_hz",
                    "control_center_hz",
                    "control_last_sequence",
                    "control_next_sequence",
                    "control_confirmed_watering",
                    "control_confirmed_at",
                    "control_response_frame",
                    "control_active_zone",
                    "control_run_started_at",
                    "control_run_duration_seconds",
                    "control_expected_idle_at",
                    "control_pending_command_id",
                    "control_pending_action",
                    "control_pending_sequence",
                    "control_pending_zone",
                    "control_pending_duration_seconds",
                    "control_pending_started_at",
                    "control_last_result",
                }
                <= valve_columns
            )
            self.assertEqual(
                44,
                migrated.devices()[0]["state"]["soil_moisture_percent"],
            )
            migrated.close()

    def test_restore_redecodes_accepted_htv145_snapshot(self) -> None:
        low_battery_idle = (
            "79f4882f28b9840280b42d008f970107858b00804f998180"
            "00408000568000000000000049ef"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(path))
            gateway.observe_decoded(
                device_id="valve-1",
                name="Garden Valve",
                model="HTV145FRF",
                frame=low_battery_idle,
                state={
                    "rf_frame_accepted": True,
                    "is_watering": True,
                    "valve_state": "watering",
                    "last_usage_liters": 0.0,
                },
            )
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(path))
            valve = next(
                device
                for device in restored.devices()
                if device["device_id"] == "valve-1"
            )
            self.assertFalse(valve["state"]["is_watering"])
            self.assertEqual("idle", valve["state"]["valve_state"])
            self.assertEqual(81.9, valve["state"]["last_usage_liters"])
            self.assertEqual(10, valve["state"]["battery_percent"])
            self.assertEqual(2, valve["state"]["battery_status"])
            restored.close()

    def test_restore_ignores_persisted_htv145_controller_request_state(
        self,
    ) -> None:
        idle = (
            "79f4882f28b9840280b42d008f970107858b00804f998180"
            "00408000568000000000000049ef"
        )
        request = (
            "79f4882f28b42d008fb98402808d10828081009e00000000"
            "000000000000000000000000da7f"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(path))
            gateway.observe_decoded(
                device_id="valve-1",
                name="Garden Valve",
                model="HTV145FRF",
                frame=idle,
                state={
                    "rf_frame_accepted": True,
                    "is_watering": False,
                    "valve_state": "idle",
                    "battery_low": True,
                },
                observed_at="2026-08-25T00:14:55+00:00",
            )
            # Freeze the projection produced by the old decoder when it heard
            # a controller request from our own transmitter.
            gateway.observe_decoded(
                device_id="valve-1",
                name="Garden Valve",
                model="HTV145FRF",
                frame=request,
                state={
                    "rf_frame_accepted": True,
                    "is_watering": True,
                    "valve_state": "watering",
                    "duration_seconds": 60,
                },
                observed_at="2026-08-25T00:20:57+00:00",
            )
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(path))
            valve = next(
                device
                for device in restored.devices()
                if device["device_id"] == "valve-1"
            )
            self.assertFalse(valve["state"]["is_watering"])
            self.assertEqual("idle", valve["state"]["valve_state"])
            self.assertEqual(idle, valve["state"]["raw"])
            # Reception cadence remains a separate metric, but device state
            # must point back to the last valve-originated observation.
            self.assertEqual(
                "2026-08-25T00:14:55+00:00",
                valve["state_observed_at"],
            )
            restored.close()

    def test_storage_rejects_newer_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute("PRAGMA user_version = 999")
            connection.close()

            with self.assertRaisesRegex(RuntimeError, "newer than supported"):
                Gateway(transport="rtl433", storage_path=str(path))

    def test_cross_receiver_duplicate_preserves_coverage_not_device_cadence(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(path))
            common = {
                "device_id": "soil-test",
                "name": "Test Soil",
                "model": "HCS026FRF",
                "frame": "same-air-transmission",
                "observed_at": "2026-08-12T00:00:00+00:00",
            }
            first = gateway.observe_decoded(
                **common,
                state={
                    "rf_receiver_id": "local-sdr",
                    "rf_frame_accepted": True,
                    "soil_moisture_percent": 44,
                    "rf_rssi_db": -40.0,
                },
            )
            duplicate = gateway.observe_decoded(
                **common,
                state={
                    "rf_receiver_id": "rp-001122334455",
                    "rf_node_id": "rp-001122334455",
                    "rf_frame_accepted": True,
                    "soil_moisture_percent": 44,
                    "rf_rssi_db": -70.0,
                },
            )

            self.assertEqual(1, first["event_id"])
            self.assertTrue(duplicate["deduplicated"])
            self.assertEqual(1, gateway.info()["stored_event_count"])
            self.assertEqual(1, gateway.devices()[0]["report_count"])
            metrics = {
                (item["receiver_id"], item["device_id"]): item
                for item in gateway.receivers()
            }
            self.assertEqual(
                1, metrics[("local-sdr", "soil-test")]["frame_count"]
            )
            self.assertEqual(
                1,
                metrics[("rp-001122334455", "soil-test")][
                    "duplicate_frame_count"
                ],
            )
            self.assertEqual(
                -70.0,
                metrics[("rp-001122334455", "soil-test")][
                    "average_rssi_db"
                ],
            )
            gateway.close()

    def test_legacy_pairing_json_migrates_once_into_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = Path(temporary_directory) / "rainpoint.sqlite3"
            legacy = storage.with_suffix(".hcs026-pairing.json")
            now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
            manager = HCS026EnrollmentManager(legacy)
            manager.start(now=now)
            manager.observe(
                {
                    "hcs026_pairing_state": "factory",
                    "hcs026_factory_endpoint": "15a98024",
                    "message_type": 1,
                },
                now=now,
            )
            manager.observe(
                {
                    "hcs026_pairing_state": "paired",
                    "hcs026_factory_endpoint": "15a98024",
                    "hcs026_paired_endpoint": "95a98024",
                    "message_type": 3,
                },
                now=now + timedelta(seconds=3),
            )
            self.assertTrue(legacy.exists())

            gateway = Gateway(transport="rtl433", storage_path=str(storage))
            records = gateway.pairing(now=now)["records"]
            self.assertEqual("95a98024", records[0]["paired_endpoint"])
            self.assertEqual(1, len(gateway._store.enrollment_records()))
            self.assertFalse(legacy.exists())
            self.assertTrue(
                legacy.with_suffix(legacy.suffix + ".migrated").exists()
            )
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(storage))
            self.assertEqual(
                "95a98024",
                restored.pairing(now=now)["records"][0]["paired_endpoint"],
            )
            restored.close()

    def test_replay_seeds_five_devices(self) -> None:
        gateway = Gateway()
        ReplayTransport(gateway, fixtures=load_fixtures()).seed()

        devices = gateway.devices()
        self.assertEqual(5, len(devices))
        valve = next(item for item in devices if item["device_id"] == "valve-1")
        self.assertEqual("idle", valve["state"]["valve_state"])
        right = next(
            item for item in devices if item["device_id"] == "soil-right-bed"
        )
        self.assertEqual(58, right["state"]["soil_moisture_percent"])
        self.assertEqual(6, len(gateway.events()))

    def test_events_support_cursor(self) -> None:
        gateway = Gateway()
        ReplayTransport(gateway).seed()
        self.assertEqual([5, 6], [e["event_id"] for e in gateway.events(since=4)])

    def test_transport_health(self) -> None:
        gateway = Gateway(transport="rtl433")
        self.assertEqual("ok", gateway.health()["status"])
        gateway.set_transport_status(False, "receiver disconnected")
        self.assertEqual(
            {
                "status": "error",
                "transport": "rtl433",
                "detail": "receiver disconnected",
            },
            gateway.health(),
        )

    def test_persistent_events_devices_and_endpoint_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(path))
            gateway.observe_rf_frame(
                frame="aa",
                observed_at="2026-08-06T12:35:44",
                state={
                    "rf_endpoint_a": "hub00001",
                    "rf_endpoint_b": "valve001",
                    "rf_message_type": 0x98,
                    "rf_rssi_db": -1.5,
                },
            )
            gateway.observe_decoded(
                device_id="soil-test",
                name="Test Soil",
                model="HCS026FRF",
                frame="bb",
                observed_at="2026-08-06T12:36:00",
                state={
                    "rf_endpoint": "sensor01",
                    "rf_endpoint_a": "hub00001",
                    "rf_endpoint_b": "sensor01",
                    "soil_moisture_percent": 44,
                },
            )
            self.assertEqual(2, gateway.info()["stored_event_count"])
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(path))
            self.assertEqual([1, 2], [e["event_id"] for e in restored.events()])
            self.assertEqual(44, restored.devices()[0]["state"]["soil_moisture_percent"])
            inventory = {item["endpoint"]: item for item in restored.endpoints()}
            self.assertEqual(2, inventory["hub00001"]["frame_count"])
            self.assertEqual(1, inventory["valve001"]["as_b_count"])
            self.assertEqual(1, inventory["sensor01"]["as_sensor_count"])
            event = restored.observe_rf_frame(frame="cc", state={})
            self.assertEqual(3, event["event_id"])
            restored.close()

    def test_restore_ignores_obsolete_auto_discovered_hcs026_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(path))
            gateway.observe_decoded(
                device_id="hcs026-b42d008f",
                name="RainPoint HCS026 b42d008f",
                model="HCS026FRF",
                frame="valve-response",
                state={
                    "rf_endpoint": "b42d008f",
                    "soil_moisture_percent": 60,
                },
            )
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(path))
            self.assertEqual([], restored.devices())
            self.assertEqual(1, len(restored.events()))
            restored.close()

    def test_persistent_report_metrics_and_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(path))
            for minute in (0, 2, 7):
                gateway.observe_decoded(
                    device_id="soil-test",
                    name="Test Soil",
                    model="HCS026FRF",
                    frame=f"frame-{minute}",
                    observed_at=f"2026-08-08T12:{minute:02d}:00",
                    state={"soil_moisture_percent": 44},
                )

            device = gateway.devices(now=datetime(2026, 8, 8, 12, 20))[0]
            self.assertEqual(3, device["report_count"])
            self.assertEqual(210, device["average_report_interval_seconds"])
            self.assertEqual(300, device["last_report_interval_seconds"])
            self.assertEqual(300, device["longest_report_gap_seconds"])
            self.assertEqual(780, device["report_age_seconds"])
            self.assertEqual(900, device["reporting_timeout_seconds"])
            self.assertTrue(device["reporting"])
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(path))
            stale = restored.devices(now=datetime(2026, 8, 8, 12, 23))[0]
            self.assertEqual(3, stale["report_count"])
            self.assertFalse(stale["reporting"])
            restored.close()

    def test_retention_preserves_quiet_devices_and_derived_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(
                transport="rtl433",
                storage_path=str(path),
                event_retention_limit=3,
            )
            gateway.observe_decoded(
                device_id="quiet-soil",
                name="Quiet Soil",
                model="HCS026FRF",
                frame="quiet",
                observed_at="2026-08-08T12:00:00",
                state={
                    "soil_moisture_percent": 21,
                    "rf_endpoint": "quiet001",
                    "rf_frame_accepted": True,
                },
            )
            for minute in range(1, 5):
                gateway.observe_decoded(
                    device_id="active-soil",
                    name="Active Soil",
                    model="HCS026FRF",
                    frame=f"active-{minute}",
                    observed_at=f"2026-08-08T12:0{minute}:00",
                    state={
                        "soil_moisture_percent": 40 + minute,
                        "rf_endpoint": "active01",
                        "rf_frame_accepted": True,
                    },
                )

            self.assertEqual([3, 4, 5], [item["event_id"] for item in gateway.events()])
            self.assertEqual(3, gateway.info()["stored_event_count"])
            self.assertEqual(3, gateway.info()["oldest_retained_event_id"])
            gateway.close()

            restored = Gateway(
                transport="rtl433",
                storage_path=str(path),
                event_retention_limit=3,
            )
            devices = {item["device_id"]: item for item in restored.devices()}
            self.assertEqual(21, devices["quiet-soil"]["state"]["soil_moisture_percent"])
            self.assertEqual(1, devices["quiet-soil"]["report_count"])
            self.assertEqual(4, devices["active-soil"]["report_count"])
            inventory = {item["endpoint"]: item for item in restored.endpoints()}
            self.assertEqual(1, inventory["quiet001"]["frame_count"])
            self.assertEqual(4, inventory["active01"]["frame_count"])
            restored.close()

    def test_reception_quality_persists_and_invalid_endpoint_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(path))
            gateway.register(
                device_id="soil-test",
                name="Test Soil",
                model="HCS026FRF",
                state={"soil_moisture_percent": None},
            )
            gateway.observe_decoded(
                device_id="soil-test",
                name="Test Soil",
                model="HCS026FRF",
                frame="valid",
                observed_at="2026-08-08T12:00:00",
                state={
                    "soil_moisture_percent": 44,
                    "rf_endpoint": "aabbcc01",
                    "rf_endpoint_a": "11223344",
                    "rf_endpoint_b": "aabbcc01",
                    "rf_trailer_valid": True,
                    "rf_frame_accepted": True,
                },
            )
            gateway.observe_rf_frame(
                device_id="soil-test",
                frame="invalid",
                observed_at="2026-08-08T12:01:00",
                state={
                    "soil_moisture_percent": 4,
                    "rf_endpoint": "aabbcc00",
                    "rf_endpoint_a": "11223340",
                    "rf_endpoint_b": "aabbcc00",
                    "rf_trailer_valid": False,
                    "rf_frame_accepted": False,
                },
            )

            device = gateway.devices(now=datetime(2026, 8, 8, 12, 2))[0]
            self.assertEqual(44, device["state"]["soil_moisture_percent"])
            self.assertEqual("2026-08-08T12:00:00", device["observed_at"])
            self.assertEqual(50.0, device["rf_frame_success_percent"])
            self.assertEqual(1, device["valid_rf_frame_count"])
            self.assertEqual(1, device["invalid_rf_frame_count"])
            endpoints = {item["endpoint"] for item in gateway.endpoints()}
            self.assertIn("aabbcc01", endpoints)
            self.assertNotIn("aabbcc00", endpoints)
            self.assertNotIn("11223340", endpoints)
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(path))
            restored_device = restored.devices(
                now=datetime(2026, 8, 8, 12, 2)
            )[0]
            self.assertEqual(44, restored_device["state"]["soil_moisture_percent"])
            self.assertEqual(50.0, restored_device["rf_frame_success_percent"])
            restored.close()

    def test_legacy_rejected_observation_is_not_restored_or_counted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(path))
            gateway.observe_decoded(
                device_id="soil-test",
                name="Test Soil",
                model="HCS026FRF",
                frame="valid",
                observed_at="2026-08-08T12:00:00",
                state={
                    "soil_moisture_percent": 78,
                    "rf_endpoint": "aabbcc01",
                    "rf_trailer_valid": True,
                },
            )
            gateway.observe_decoded(
                device_id="soil-test",
                name="Test Soil",
                model="HCS026FRF",
                frame="corrupted",
                observed_at="2026-08-08T12:01:00",
                state={
                    "soil_moisture_percent": 14,
                    "rf_endpoint": "aabbcc00",
                    "rf_trailer_valid": False,
                },
            )
            gateway._store._connection.execute(
                "UPDATE device_metrics SET report_count = 2 "
                "WHERE device_id = 'soil-test'"
            )
            gateway._store._connection.execute(
                """
                INSERT INTO endpoints(
                    endpoint, first_seen, last_seen, frame_count,
                    last_frame
                ) VALUES ('aabbcc00', '2026-08-08T12:01:00',
                          '2026-08-08T12:01:00', 1, 'corrupted')
                """
            )
            gateway._store._connection.execute(
                "DELETE FROM storage_metadata WHERE key IN "
                "('device_metrics_version', 'endpoint_inventory_version')"
            )
            gateway._store._connection.commit()
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(path))
            device = restored.devices(now=datetime(2026, 8, 8, 12, 2))[0]
            self.assertEqual(78, device["state"]["soil_moisture_percent"])
            self.assertEqual("2026-08-08T12:00:00", device["observed_at"])
            self.assertEqual(1, device["report_count"])
            self.assertEqual(50.0, device["rf_frame_success_percent"])
            self.assertNotIn(
                "aabbcc00", {item["endpoint"] for item in restored.endpoints()}
            )
            restored.close()

    def test_existing_database_metrics_are_backfilled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(path))
            gateway.observe_decoded(
                device_id="valve-1",
                name="Valve",
                model="HTV145FRF",
                frame="first",
                observed_at="2026-08-08T01:00:00",
                state={"is_watering": False},
            )
            gateway.observe_decoded(
                device_id="valve-1",
                name="Valve",
                model="HTV145FRF",
                frame="second",
                observed_at="2026-08-08T02:00:00",
                state={"is_watering": False},
            )
            gateway._store._connection.execute("DELETE FROM device_metrics")
            gateway._store._connection.commit()
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(path))
            device = restored.devices(now=datetime(2026, 8, 8, 7, 0))[0]
            self.assertEqual(2, device["report_count"])
            self.assertEqual(3600, device["average_report_interval_seconds"])
            self.assertEqual(3600, device["last_report_interval_seconds"])
            self.assertEqual(21600, device["reporting_timeout_seconds"])
            self.assertTrue(device["reporting"])
            restored.close()

    def test_receive_only_learning_and_registry_persist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(
                transport="rtl433",
                storage_path=str(path),
                registry_token="test-token",
            )
            gateway.observe_rf_frame(
                frame="first",
                observed_at="2026-08-08T12:00:00+00:00",
                state={"rf_endpoint": "aabbcc01"},
            )
            session = gateway.start_learning(
                120, now=datetime.fromisoformat("2026-08-08T12:01:00+00:00")
            )
            self.assertTrue(session["active"])
            self.assertFalse(session["rf_pairing"])
            self.assertEqual([], session["new_endpoints"])

            gateway.observe_rf_frame(
                frame="second",
                observed_at="2026-08-08T12:01:30+00:00",
                state={"rf_endpoint": "aabbcc02"},
            )
            learning = gateway.learning(
                now=datetime.fromisoformat("2026-08-08T12:02:00+00:00")
            )
            self.assertEqual(
                ["aabbcc02"],
                [item["endpoint"] for item in learning["new_endpoints"]],
            )
            gateway.observe_rf_frame(
                frame="too-late",
                observed_at="2026-08-08T12:04:00+00:00",
                state={"rf_endpoint": "aabbccff"},
            )
            expired = gateway.learning(
                now=datetime.fromisoformat("2026-08-08T12:05:00+00:00")
            )
            self.assertFalse(expired["active"])
            self.assertEqual(
                ["aabbcc02"],
                [item["endpoint"] for item in expired["new_endpoints"]],
            )
            accepted = gateway.accept_endpoint(
                endpoint="AABBCC02",
                name="Test Moisture",
                model="HCS026FRF",
                area="Bench",
                now=datetime.fromisoformat("2026-08-08T12:02:00+00:00"),
            )
            self.assertEqual("local-aabbcc02", accepted["device_id"])
            self.assertTrue(gateway.registry_authorized("test-token"))
            self.assertFalse(gateway.registry_authorized("wrong"))
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(path))
            self.assertEqual("Test Moisture", restored.registry()[0]["name"])
            renamed = restored.update_registry_device(
                "local-aabbcc02", name="Patio Sensor"
            )
            self.assertEqual("Patio Sensor", renamed["name"])
            self.assertEqual("Bench", renamed["area"])
            forgotten = restored.forget_registry_device("local-aabbcc02")
            self.assertEqual("aabbcc02", forgotten["endpoint"])
            self.assertEqual([], restored.registry())
            self.assertTrue(restored.endpoint_suppressed("aabbcc02"))
            restored.close()

    def test_legacy_registry_id_migrates_to_existing_device_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(path))
            gateway._store.accept_endpoint(
                endpoint="9ce58024",
                device_id="local-9ce58024",
                name="Right Bed Override",
                model="HCS026FRF",
                area="Garden",
                accepted_at="2026-08-11T12:00:00+00:00",
            )
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(path))
            registration = restored.registry()[0]
            self.assertEqual("soil-right-bed", registration["device_id"])
            self.assertEqual("Right Bed Override", registration["name"])
            restored.close()


class HTTPAPITest(unittest.TestCase):
    def setUp(self) -> None:
        gateway = Gateway(claim_code="123456")
        ReplayTransport(gateway).seed()
        self.server = create_server(gateway, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def get_json(self, path: str) -> dict:
        with urlopen(f"{self.base}{path}", timeout=2) as response:
            return json.load(response)

    def test_info_and_devices(self) -> None:
        info = self.get_json("/api/v1/info")
        self.assertEqual("v1", info["api_version"])
        self.assertEqual(["v1"], info["api_versions"])
        self.assertIn("event_long_poll", info["capabilities"])
        self.assertEqual("long_poll", info["event_delivery"]["mode"])
        self.assertTrue(info["read_only"])
        self.assertEqual(5, info["device_count"])
        self.assertEqual(5, len(self.get_json("/api/v1/devices")["devices"]))
        self.assertEqual([], self.get_json("/api/v1/endpoints")["endpoints"])
        self.assertEqual(0, info["node_count"])
        self.assertEqual([], self.get_json("/api/v1/nodes")["nodes"])
        self.assertEqual([], self.get_json("/api/v1/receivers")["receivers"])

    def test_event_cursor(self) -> None:
        result = self.get_json("/api/v1/events?since=5")
        self.assertEqual([6], [event["event_id"] for event in result["events"]])
        self.assertEqual(6, result["next_since"])

    def test_event_long_poll_times_out_with_stable_cursor(self) -> None:
        started = time.monotonic()
        result = self.get_json("/api/v1/events?since=6&wait=0.05")
        self.assertGreaterEqual(time.monotonic() - started, 0.04)
        self.assertEqual([], result["events"])
        self.assertEqual(6, result["next_since"])

    def test_post_is_rejected(self) -> None:
        request = Request(
            f"{self.base}/api/v1/devices/valve-1/open",
            data=b"{}",
            method="POST",
        )
        with self.assertRaises(HTTPError) as raised:
            urlopen(request, timeout=2)
        self.assertEqual(405, raised.exception.code)

    def test_unhealthy_transport_returns_503(self) -> None:
        self.server.gateway.set_transport_status(False, "receiver disconnected")
        with self.assertRaises(HTTPError) as raised:
            urlopen(f"{self.base}/health", timeout=2)
        self.assertEqual(503, raised.exception.code)

    def test_registry_writes_are_disabled_without_token(self) -> None:
        request = Request(
            f"{self.base}/api/v1/learning",
            data=b'{"duration_seconds":60}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as raised:
            urlopen(request, timeout=2)
        self.assertEqual(403, raised.exception.code)

    def test_one_time_setup_code_claims_gateway(self) -> None:
        request = Request(
            f"{self.base}/api/v1/auth/claim",
            data=b'{"setup_code":"123456"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            token = json.load(response)["registry_write_token"]
        self.assertTrue(self.server.gateway.registry_authorized(token))
        with self.assertRaises(HTTPError) as raised:
            urlopen(request, timeout=2)
        self.assertEqual(401, raised.exception.code)


class RegistryHTTPAPITest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        path = Path(self.temporary_directory.name) / "rainpoint.sqlite3"
        gateway = Gateway(storage_path=str(path), registry_token="test-token")
        gateway.observe_rf_frame(
            frame="observed",
            state={"rf_endpoint": "aabbcc03"},
        )
        self.server = create_server(gateway, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.server.gateway.close()
        self.thread.join(timeout=2)
        self.temporary_directory.cleanup()

    def post_json(
        self, path: str, payload: dict, *, token: str | None = "test-token"
    ) -> dict:
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            f"{self.base}{path}",
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            return json.load(response)

    def test_authenticated_registry_lifecycle_never_claims_rf_pairing(self) -> None:
        with self.assertRaises(HTTPError) as raised:
            self.post_json(
                "/api/v1/registry/accept",
                {
                    "endpoint": "aabbcc03",
                    "name": "Bench Sensor",
                    "model": "HCS026FRF",
                },
                token=None,
            )
        self.assertEqual(401, raised.exception.code)

        accepted = self.post_json(
            "/api/v1/registry/accept",
            {
                "endpoint": "aabbcc03",
                "name": "Bench Sensor",
                "model": "HCS026FRF",
            },
        )
        self.assertFalse(accepted["rf_paired"])
        device_id = accepted["device"]["device_id"]
        renamed = self.post_json(
            f"/api/v1/registry/{device_id}/rename", {"area": "Garden"}
        )
        self.assertEqual("Garden", renamed["device"]["area"])
        forgotten = self.post_json(
            f"/api/v1/registry/{device_id}/forget", {}
        )
        self.assertFalse(forgotten["rf_unpaired"])

    def test_htv405_control_route_is_disabled_by_default(self) -> None:
        with self.assertRaises(HTTPError) as raised:
            self.post_json(
                "/api/v1/devices/htv405-test/valve/open",
                {"zone": 1, "duration_seconds": 60},
            )
        self.assertEqual(403, raised.exception.code)

    def test_management_token_rotation_revokes_previous_token(self) -> None:
        result = self.post_json("/api/v1/auth/rotate", {})
        replacement = result["registry_write_token"]
        with self.assertRaises(HTTPError) as raised:
            self.post_json("/api/v1/auth/check", {})
        self.assertEqual(401, raised.exception.code)
        authorized = self.post_json(
            "/api/v1/auth/check", {}, token=replacement
        )
        self.assertTrue(authorized["authorized"])

    def test_radio_node_revocation_retains_device_registry(self) -> None:
        node_id = "rp-001122334455"
        self.server.gateway.register_radio_node(
            node_id=node_id,
            token="ab" * 32,
            name="Bench node",
            area="Garden",
        )
        result = self.post_json(f"/api/v1/nodes/{node_id}/revoke", {})
        self.assertTrue(result["revoked"])
        self.assertIsNone(self.server.gateway.radio_node_credential(node_id))
        self.assertEqual(1, len(self.server.gateway.endpoints()))

    def test_authenticated_forget_covers_unregistered_paired_sensor(self) -> None:
        self.server.gateway.observe_decoded(
            device_id="hcs026-9bce0024",
            name="RainPoint HCS026 9bce0024",
            model="HCS026FRF",
            frame="paired",
            state={
                "rf_endpoint": "9bce0024",
                "rf_factory_endpoint": "1bce0024",
                "rf_paired_endpoint": "9bce0024",
                "rf_frame_accepted": True,
                "soil_moisture_percent": 12,
            },
        )
        forgotten = self.post_json(
            "/api/v1/devices/hcs026-9bce0024/forget", {}
        )
        self.assertFalse(forgotten["rf_unpaired"])
        self.assertEqual("9bce0024", forgotten["forgotten"]["endpoint"])
        self.assertEqual([], self.server.gateway.devices())
        self.assertTrue(self.server.gateway.endpoint_suppressed("9bce0024"))

    def test_auth_check_validates_without_mutating_gateway(self) -> None:
        before = self.server.gateway.info()["stored_event_count"]
        self.assertEqual(
            {"authorized": True}, self.post_json("/api/v1/auth/check", {})
        )
        self.assertEqual(before, self.server.gateway.info()["stored_event_count"])
        with self.assertRaises(HTTPError) as raised:
            self.post_json("/api/v1/auth/check", {}, token="wrong")
        self.assertEqual(401, raised.exception.code)

    def test_authenticated_radio_node_registration_hides_credential(self) -> None:
        token = "ab" * 32
        registered = self.post_json(
            "/api/v1/nodes/register",
            {
                "node_id": "rp-001122334455",
                "token": token,
                "name": "Back Garden Radio",
                "area": "Garden",
            },
        )["node"]
        self.assertEqual("Back Garden Radio", registered["name"])
        self.assertNotIn("token", registered)
        self.assertEqual(
            token,
            self.server.gateway.radio_node_credential("rp-001122334455"),
        )
        node = self.server.gateway.nodes()[0]
        self.assertFalse(node["connected"])
        self.assertTrue(node["managed"])
        self.assertEqual("Garden", node["area"])

    def test_authenticated_ack_assignment_has_one_persistent_owner(self) -> None:
        node_id = "rp-001122334455"
        self.server.gateway.register_radio_node(
            node_id=node_id,
            token="ab" * 32,
            name="Back Garden Radio",
            area="Garden",
        )
        assert self.server.gateway._store is not None
        self.server.gateway._store.upsert_enrollment_record(
            {
                "factory_endpoint": "1bce0024",
                "paired_endpoint": "9bce0024",
                "enrolled_at": "2026-08-14T00:00:00+00:00",
                "last_seen_at": "2026-08-14T00:00:00+00:00",
            }
        )
        assigned = self.post_json(
            f"/api/v1/nodes/{node_id}/ack-assignment",
            {
                "paired_endpoint": "9bce0024",
                "assigned_channel": 4,
            },
        )["ack_assignment"]
        self.assertEqual(node_id, assigned["node_id"])
        with urlopen(f"{self.base}/api/v1/ack-assignments", timeout=2) as response:
            assignments = json.load(response)["ack_assignments"]
        self.assertEqual([assigned], assignments)

    def test_identify_api_uses_bounded_non_rf_node_command(self) -> None:
        commands: list[tuple[str, dict]] = []
        self.server.gateway.update_node(
            "rp-001122334455",
            connected=True,
            authenticated=True,
            capabilities=["rx", "sensor_pairing_tx", "identify"],
        )
        self.server.gateway.set_node_command_sender(
            lambda node_id, message: commands.append((node_id, message))
        )
        identified = self.post_json(
            "/api/v1/nodes/rp-001122334455/identify",
            {"duration_seconds": 12},
        )
        self.assertTrue(identified["identify_active"])
        self.assertEqual(12, identified["duration_seconds"])
        self.assertEqual("rp-001122334455", commands[0][0])
        self.assertEqual("identify_start", commands[0][1]["type"])
        self.assertNotIn("valve", json.dumps(commands[0][1]))

    def test_ota_trial_api_requires_candidate_node_capability(self) -> None:
        commands: list[tuple[str, dict]] = []
        node_id = "rp-001122334455"
        self.server.gateway.update_node(
            node_id,
            connected=True,
            authenticated=True,
            capabilities=[
                "rx",
                "sensor_pairing_tx",
                "firmware_update_trial",
            ],
            tx_armed=False,
        )
        self.server.gateway.set_node_command_sender(
            lambda target, message: commands.append((target, message))
        )
        result = self.post_json(
            f"/api/v1/nodes/{node_id}/firmware-update",
            {
                "url": "http://192.0.2.1:8787/firmware/test.bin",
                "version": "0.9.0-test.2",
                "size_bytes": 900_000,
                "sha256": "AB" * 32,
            },
        )
        self.assertEqual("requested", result["state"])
        self.assertEqual(node_id, commands[0][0])
        self.assertEqual("firmware_update_start", commands[0][1]["type"])
        self.assertEqual("ab" * 32, commands[0][1]["sha256"])

        self.server.gateway.update_node(
            node_id,
            capabilities=["rx", "sensor_pairing_tx"],
        )
        with self.assertRaises(HTTPError) as raised:
            self.post_json(
                f"/api/v1/nodes/{node_id}/firmware-update",
                {
                    "url": "http://192.0.2.1:8787/firmware/test.bin",
                    "version": "0.9.0-test.2",
                    "size_bytes": 900_000,
                    "sha256": "ab" * 32,
                },
            )
        self.assertEqual(400, raised.exception.code)

    def test_adoption_api_issues_temporary_secret_without_public_exposure(self) -> None:
        started = self.post_json(
            "/api/v1/nodes/adoptions/start",
            {
                "node_id": "rp-102030405060",
                "name": "Side Garden Radio",
                "area": "Side Garden",
                "duration_seconds": 300,
            },
        )
        self.assertEqual(64, len(started["node_token"]))
        status = self.post_json(
            "/api/v1/nodes/adoptions/status",
            {"node_id": "rp-102030405060"},
        )
        self.assertEqual("waiting_for_node", status["state"])
        self.assertNotIn("token", json.dumps(status))
        with urlopen(f"{self.base}/api/v1/nodes", timeout=2) as response:
            public_nodes = json.load(response)
        self.assertNotIn(started["node_token"], json.dumps(public_nodes))
        cancelled = self.post_json(
            "/api/v1/nodes/adoptions/cancel",
            {"node_id": "rp-102030405060"},
        )
        self.assertTrue(cancelled["cancelled"])
        self.assertEqual(
            "not_found",
            self.post_json(
                "/api/v1/nodes/adoptions/status",
                {"node_id": "rp-102030405060"},
            )["state"],
        )

    def test_learning_api_is_receive_only(self) -> None:
        result = self.post_json(
            "/api/v1/learning", {"duration_seconds": 60}
        )
        self.assertTrue(result["active"])
        self.assertFalse(result["rf_pairing"])

    def test_authenticated_sensor_pairing_monitor_lifecycle(self) -> None:
        started = self.post_json(
            "/api/v1/pairing/start", {"duration_seconds": 120}
        )
        self.assertTrue(started["active"])
        self.assertTrue(started["transmitter_required"])
        self.assertFalse(started["transmitter_available"])

        gateway = self.server.gateway
        gateway.observe_rf_frame(
            frame="factory",
            state={
                "rf_endpoint_a": "80000000",
                "rf_endpoint_b": "15a98024",
                "rf_frame_accepted": True,
                "hcs026_pairing_state": "factory",
                "hcs026_factory_endpoint": "15a98024",
            },
        )
        with urlopen(f"{self.base}/api/v1/pairing", timeout=2) as response:
            candidate = json.load(response)
        self.assertEqual(
            "factory_detected_transmitter_required", candidate["stage"]
        )
        self.assertEqual(
            "95a98024", candidate["dry_run_profile"]["paired_endpoint"]
        )
        self.assertTrue(candidate["dry_run_profile"]["transmit_enabled"])
        gateway.observe_decoded(
            device_id="hcs026-95a98024",
            name="RainPoint HCS026 95a98024",
            model="HCS026FRF",
            frame="paired",
            state={
                "rf_endpoint": "95a98024",
                "rf_endpoint_a": "b9840280",
                "rf_endpoint_b": "95a98024",
                "rf_frame_accepted": True,
                "rf_pairing_state": "paired",
                "rf_factory_endpoint": "15a98024",
                "rf_paired_endpoint": "95a98024",
                "rf_message_type": 3,
                "soil_moisture_percent": 10,
            },
        )
        with urlopen(f"{self.base}/api/v1/pairing", timeout=2) as response:
            progress = json.load(response)
        self.assertEqual("95a98024", progress["new_records"][0]["paired_endpoint"])
        self.assertEqual("paired_identity_observed", progress["stage"])

        completed = self.post_json(
            "/api/v1/pairing/complete",
            {
                "endpoint": "95a98024",
                "name": "Test Sensor B",
                "area": "Garden",
            },
        )
        self.assertTrue(completed["rf_paired"])
        self.assertFalse(completed["transmit_performed"])
        device = next(
            item
            for item in gateway.devices()
            if item["device_id"] == "hcs026-95a98024"
        )
        self.assertEqual("Test Sensor B", device["name"])
        self.assertEqual("Garden", device["area"])
        self.assertEqual(GENERIC_HCS02X_MODEL, device["model"])
        self.assertEqual(
            HCS02X_PROTOCOL, device["state"]["rf_protocol_family"]
        )
        self.assertIn("forget", device["capabilities"])

        forgotten = self.post_json(
            "/api/v1/registry/hcs026-95a98024/forget", {}
        )
        self.assertFalse(forgotten["rf_unpaired"])
        self.assertEqual([], gateway._store.enrollment_records())
        self.assertTrue(gateway.endpoint_suppressed("95a98024"))
        with urlopen(f"{self.base}/api/v1/pairing", timeout=2) as response:
            reset_progress = json.load(response)
        self.assertEqual([], reset_progress["records"])


class Htv145AcceptanceHTTPAPITest(unittest.TestCase):
    """Exercise the private, one-shot HTV145 dry-valve boundary."""

    NODE_ID = "rp-001122334455"
    CONTROLLER_ENDPOINT = "b42d008f"
    VALVE_ENDPOINT = "b9840280"
    IDLE = (
        "79f4882f28b9840280b42d008f970107858b00804f998180004080005680"
        "00000000000049ef"
    )
    OPEN_RESPONSE = (
        "79f4882f28b9840280b42d008f8150868010cf8702000040d80256d802"
        "000000000000004bfa"
    )

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        path = Path(self.temporary_directory.name) / "rainpoint.sqlite3"
        gateway = Gateway(
            storage_path=str(path),
            registry_token="test-token",
            htv145_acceptance_enabled=True,
        )
        gateway.update_node(
            self.NODE_ID,
            connected=True,
            authenticated=True,
            tx_armed=False,
            capabilities=["rx", "htv145_control_tx_candidate"],
        )
        self.commands: list[tuple[str, dict]] = []
        gateway.set_node_command_sender(
            lambda node_id, command: self.commands.append((node_id, command))
        )
        self.server = create_server(gateway, port=0)
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.server.gateway.close()
        self.thread.join(timeout=2)
        self.temporary_directory.cleanup()

    def post_json(
        self, path: str, payload: dict, *, token: str | None = "test-token"
    ) -> dict:
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            f"{self.base}{path}",
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            return json.load(response)

    def test_one_shot_open_requires_auth_and_positive_valve_evidence(self) -> None:
        link = ValveLink(
            bytes.fromhex(self.CONTROLLER_ENDPOINT),
            bytes.fromhex(self.VALVE_ENDPOINT),
        )
        passive = build_open_frame(link, 0x80, 1_200, 0xC713).hex()
        payload = {
            "node_id": self.NODE_ID,
            "controller_endpoint": self.CONTROLLER_ENDPOINT,
            "valve_endpoint": self.VALVE_ENDPOINT,
            "center_hz": 434_239_594,
            "power_dbm": 10,
            "invert": False,
            "trailer_residual": 0xC713,
            "idle_frame": self.IDLE,
            "passive_command_frame": passive,
            "idle_observed_at": "2026-08-25T00:00:00+00:00",
            "passive_command_observed_at": "2026-08-25T00:00:00+00:00",
        }
        with self.assertRaises(HTTPError) as raised:
            self.post_json(
                "/api/v1/research/htv145-acceptance/prepare",
                payload,
                token=None,
            )
        self.assertEqual(401, raised.exception.code)

        prepared = self.post_json(
            "/api/v1/research/htv145-acceptance/prepare", payload
        )
        self.assertEqual("prepared_no_actuation", prepared["state"])
        self.assertEqual(
            ["htv145_control_configure", "htv145_control_sync"],
            [command["type"] for _node, command in self.commands],
        )

        opened = self.post_json(
            "/api/v1/research/htv145-acceptance/open",
            {"duration_seconds": 60},
        )
        command = opened["command"]
        self.assertEqual("htv145_control_open", command["type"])
        self.server.gateway.observe_htv145_acceptance_candidate(
            self.NODE_ID,
            {
                "type": "htv145_control_candidate",
                "node_id": self.NODE_ID,
                "state": "confirmed",
                "command_id": command["command_id"],
                "frame": self.OPEN_RESPONSE,
            },
        )
        expected_idle_at = datetime.fromisoformat(
            opened["acceptance"]["expected_idle_at"]
        )
        self.server.gateway.observe_decoded(
            device_id="valve-1",
            name="Dry one-zone valve",
            model="HTV145FRF",
            frame=self.IDLE,
            state={"model": "HTV145FRF", "is_watering": False},
            observed_at=expected_idle_at.isoformat(),
        )
        status = self.post_json(
            "/api/v1/research/htv145-acceptance/status", {}
        )
        self.assertTrue(status["passed"])
        self.assertTrue(status["checks"]["one_logical_open_dispatched"])
        with self.assertRaises(HTTPError) as stale:
            self.post_json(
                "/api/v1/research/htv145-acceptance/prepare", payload
            )
        self.assertEqual(400, stale.exception.code)


class ValveControlHTTPAPITest(unittest.TestCase):
    """Exercise the authenticated, disabled-by-default HTV405 boundary."""

    NODE_ID = "rp-001122334455"
    SECOND_NODE_ID = "rp-aabbccddeeff"
    DEVICE_ID = "htv405-94a98013"
    VALVE_ENDPOINT = "94a98013"

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        path = Path(self.temporary_directory.name) / "rainpoint.sqlite3"
        gateway = Gateway(
            storage_path=str(path),
            registry_token="test-token",
            valve_control_enabled=True,
        )
        assert gateway._store is not None
        gateway._store.upsert_valve_link(
            controller_endpoint="b9840280",
            valve_endpoint=self.VALVE_ENDPOINT,
            device_id=self.DEVICE_ID,
            name="Test four-zone valve",
            model="HTV405FRF",
            area="Garden",
            accepted_at="2026-08-24T20:00:00+00:00",
        )
        gateway._store.update_valve_control_profile(
            valve_endpoint=self.VALVE_ENDPOINT,
            node_id=self.NODE_ID,
            companion_endpoint="39840280",
            selector=0x05,
            frequency_offset_hz=97_154,
            observed_at="2026-08-24T20:00:01+00:00",
        )
        gateway._store.synchronize_htv405_control_counter(
            valve_endpoint=self.VALVE_ENDPOINT,
            node_id=self.NODE_ID,
            next_sequence=6,
            source="retained_association_capture",
            observed_at="2026-08-24T20:00:02+00:00",
        )
        gateway._refresh_registry_catalog()
        gateway._ensure_registered_valve_devices()
        gateway.update_node(
            self.NODE_ID,
            connected=True,
            authenticated=True,
            tx_armed=False,
            capabilities=["rx", "valve_control_tx_candidate"],
        )
        gateway.update_node(
            self.SECOND_NODE_ID,
            connected=True,
            authenticated=True,
            tx_armed=False,
            capabilities=["rx", "valve_control_tx_candidate"],
        )
        self.commands: list[tuple[str, dict]] = []
        gateway.set_node_command_sender(
            lambda node_id, command: self.commands.append((node_id, command))
        )
        self.server = create_server(gateway, port=0)
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.server.gateway.close()
        self.thread.join(timeout=2)
        self.temporary_directory.cleanup()

    def post_json(
        self, path: str, payload: dict, *, token: str | None = "test-token"
    ) -> dict:
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            f"{self.base}{path}",
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            return json.load(response)

    def test_authenticated_registry_forget_removes_valve_link(self) -> None:
        renamed = self.post_json(
            f"/api/v1/registry/{self.DEVICE_ID}/rename",
            {"name": "Renamed four-zone valve", "area": "Back Garden"},
        )
        self.assertEqual("Renamed four-zone valve", renamed["device"]["name"])
        self.assertEqual("Back Garden", renamed["device"]["area"])
        self.assertEqual(
            self.NODE_ID, renamed["device"]["control_node_id"]
        )

        result = self.post_json(
            f"/api/v1/registry/{self.DEVICE_ID}/forget", {}
        )

        self.assertFalse(result["rf_unpaired"])
        self.assertEqual(
            self.VALVE_ENDPOINT, result["forgotten"]["endpoint"]
        )
        self.assertEqual([], self.server.gateway._store.valve_registry())
        self.assertFalse(
            any(
                device["device_id"] == self.DEVICE_ID
                for device in self.server.gateway.devices()
            )
        )
        self.assertTrue(
            self.server.gateway.endpoint_suppressed(self.VALVE_ENDPOINT)
        )

    def test_open_is_bounded_reserved_and_node_rejection_is_terminal(self) -> None:
        with self.assertRaises(HTTPError) as raised:
            self.post_json(
                f"/api/v1/devices/{self.DEVICE_ID}/valve/open",
                {"zone": 2, "duration_seconds": 60},
                token=None,
            )
        self.assertEqual(401, raised.exception.code)

        result = self.post_json(
            f"/api/v1/devices/{self.DEVICE_ID}/valve/open",
            {"zone": 2, "duration_seconds": 60},
        )["control"]
        self.assertEqual("pending_authenticated_response", result["state"])
        self.assertEqual(
            [
                "valve_control_configure",
                "valve_control_sync",
                "valve_control_open",
            ],
            [command["type"] for _node, command in self.commands],
        )
        self.assertEqual(
            {result["command_id"]},
            {command["command_id"] for _node, command in self.commands},
        )
        with self.assertRaises(HTTPError) as raised:
            self.post_json(
                f"/api/v1/devices/{self.DEVICE_ID}/valve/open",
                {"zone": 1, "duration_seconds": 60},
            )
        self.assertEqual(400, raised.exception.code)

        self.assertTrue(
            self.server.gateway.observe_valve_control_error(
                self.NODE_ID,
                {
                    "type": "command_error",
                    "command_id": result["command_id"],
                    "error": "invalid_valve_control_open",
                },
                observed_at="2026-08-24T20:00:21+00:00",
            )
        )
        registration = self.server.gateway._store.valve_registry()[0]
        self.assertIsNone(registration["control_pending_command_id"])
        self.assertIsNone(registration["control_next_sequence"])
        event = self.server.gateway.events()[-1]
        self.assertEqual("valve_control_failed", event["event_type"])
        self.assertEqual("open", event["state"]["action"])

    def test_twenty_minute_open_is_reserved_for_production_schedule(self) -> None:
        result = self.post_json(
            f"/api/v1/devices/{self.DEVICE_ID}/valve/open",
            {"zone": 1, "duration_seconds": 1_200},
        )["control"]

        self.assertEqual(1_200, result["duration_seconds"])
        self.assertEqual(
            1_200,
            self.commands[-1][1]["duration_seconds"],
        )
        registration = self.server.gateway._store.valve_registry()[0]
        self.assertEqual(
            1_200, registration["control_pending_duration_seconds"]
        )

    def test_device_poll_expires_a_stale_node_command_reservation(self) -> None:
        result = self.server.gateway.request_htv405_control(
            device_id=self.DEVICE_ID,
            action="open",
            zone=1,
            duration_seconds=60,
            now=datetime.fromisoformat("2026-08-24T20:00:20+00:00"),
        )

        before_deadline = self.server.gateway.devices(
            now=datetime.fromisoformat("2026-08-24T20:00:30+00:00")
        )
        self.assertTrue(
            next(
                item
                for item in before_deadline
                if item["device_id"] == self.DEVICE_ID
            )["state"]["rf_control_command_pending"]
        )

        after_deadline = self.server.gateway.devices(
            now=datetime.fromisoformat("2026-08-24T20:00:30.001000+00:00")
        )
        state = next(
            item
            for item in after_deadline
            if item["device_id"] == self.DEVICE_ID
        )["state"]
        self.assertFalse(state["rf_control_command_pending"])
        self.assertEqual(
            "gateway_command_response_timeout_counter_unsynchronized",
            state["rf_control_last_result"],
        )
        self.assertEqual(6, state["rf_control_recovery_sequence"])
        self.assertEqual(1, state["rf_control_recovery_attempt"])
        events = [
            event
            for event in self.server.gateway.events()
            if event["event_type"] == "valve_control_failed"
        ]
        self.assertEqual(1, len(events))
        self.assertEqual("open", events[0]["state"]["action"])
        registration = self.server.gateway._store.valve_registry()[0]
        self.assertNotEqual(
            result["command_id"],
            registration["control_pending_command_id"],
        )

    def test_next_open_recovers_a_matured_bounded_timeout(self) -> None:
        gateway = self.server.gateway
        first = gateway.request_htv405_control(
            device_id=self.DEVICE_ID,
            action="open",
            zone=1,
            duration_seconds=60,
            now=datetime.fromisoformat("2026-08-24T20:00:20+00:00"),
        )
        assert gateway._store is not None
        gateway._store.fail_htv405_command(
            valve_endpoint=self.VALVE_ENDPOINT,
            node_id=self.NODE_ID,
            command_id=first["command_id"],
            reason=(
                "gateway_command_response_timeout_counter_unsynchronized"
            ),
            observed_at="2026-08-24T20:00:22+00:00",
        )
        with self.assertRaisesRegex(RuntimeError, "not synchronized"):
            gateway.request_htv405_control(
                device_id=self.DEVICE_ID,
                action="open",
                zone=1,
                duration_seconds=60,
                now=datetime.fromisoformat("2026-08-24T20:01:34+00:00"),
            )

        retry = gateway.request_htv405_control(
            device_id=self.DEVICE_ID,
            action="open",
            zone=1,
            duration_seconds=60,
            now=datetime.fromisoformat("2026-08-24T20:01:35+00:00"),
        )
        self.assertEqual("pending_authenticated_response", retry["state"])
        registration = gateway._store.valve_registry()[0]
        self.assertEqual(6, registration["control_pending_sequence"])
        self.assertEqual(1, registration["control_recovery_attempt"])

    def test_control_node_can_move_without_changing_association(self) -> None:
        before = self.server.gateway._store.valve_registry()[0]
        result = self.post_json(
            f"/api/v1/devices/{self.DEVICE_ID}/valve/node",
            {"node_id": self.SECOND_NODE_ID},
        )["control"]

        self.assertEqual(self.SECOND_NODE_ID, result["control_node_id"])
        self.assertEqual(
            before["controller_endpoint"], result["controller_endpoint"]
        )
        self.assertEqual(
            before["control_companion_endpoint"],
            result["control_companion_endpoint"],
        )
        self.assertEqual(before["control_selector"], result["control_selector"])
        self.assertEqual(
            before["control_frequency_offset_hz"],
            result["control_frequency_offset_hz"],
        )
        self.assertIsNone(result["control_next_sequence"])
        self.assertEqual(
            "control_node_updated_counter_required",
            result["control_last_result"],
        )

    def test_armed_node_is_never_control_available(self) -> None:
        self.server.gateway.update_node(self.NODE_ID, tx_armed=True)
        device = next(
            item
            for item in self.server.gateway.devices()
            if item["device_id"] == self.DEVICE_ID
        )
        self.assertFalse(device["state"]["rf_control_available"])
        self.assertEqual(
            "radio_node_unavailable",
            device["state"]["rf_control_unavailable_reason"],
        )
        with self.assertRaises(HTTPError) as raised:
            self.post_json(
                f"/api/v1/devices/{self.DEVICE_ID}/valve/open",
                {"zone": 1, "duration_seconds": 60},
            )
        self.assertEqual(400, raised.exception.code)
        self.assertEqual([], self.commands)


if __name__ == "__main__":
    unittest.main()
