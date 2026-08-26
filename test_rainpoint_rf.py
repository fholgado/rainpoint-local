#!/usr/bin/env python3

from __future__ import annotations

import binascii
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "rainpointd_addon"))

from rainpointd.esp32 import ESP32SerialTransport  # noqa: E402
from rainpointd.device_catalog import (  # noqa: E402
    DeviceCatalog,
    LEGACY_HOME_CATALOG,
    SensorDefinition,
    ValveDefinition,
    load_catalog,
)
from rainpointd.gateway import Gateway  # noqa: E402
from rainpointd.product_identity import (  # noqa: E402
    GENERIC_HCS02X_MODEL,
    HCS02X_PROTOCOL,
    hcs02x_identity,
    product_from_codes,
)
from rainpointd.protocol import decode_receiver_event  # noqa: E402
from rainpointd.rf import normalize_row  # noqa: E402
from rainpointd.rtl433 import RTL433Transport, rtl_433_command  # noqa: E402
from rainpointd.valve_protocol import (  # noqa: E402
    ValveLink,
    build_close_frame,
    build_htv405_close_frame,
    build_open_frame,
    close_candidates,
    decode_duration,
    decode_htv405_control_frame,
    decode_htv405_gateway_command_response,
    encode_duration,
    next_sequence,
    open_candidates,
    is_htv405_link_frame,
    htv405_close_candidates,
    htv405_phase_state,
    next_htv405_phase,
)
from tools.characterize_rainpoint_iq import characterize  # noqa: E402
from tools.compare_rainpoint_iq import compare_waveforms  # noqa: E402
from tools.demod_rainpoint_reply_iq import demodulate  # noqa: E402
from tools.generate_rainpoint_iq import (  # noqa: E402
    command_symbols,
    generate_command,
)


class RainPointRFTest(unittest.TestCase):
    CAPTURED_VALVE_LINK = ValveLink(
        controller_endpoint=bytes.fromhex("b42d008f"),
        valve_endpoint=bytes.fromhex("b9840280"),
    )

    @staticmethod
    def _frame_with_endpoint(frame_hex: str, endpoint: str) -> str:
        """Rewrite endpoint B and retain a supported trailer residue."""
        frame = bytearray.fromhex(frame_hex)
        frame[9:13] = bytes.fromhex(endpoint)
        trailer = binascii.crc_hqx(frame[:-2], 0) ^ 0xC713
        frame[-2:] = trailer.to_bytes(2, "big")
        return frame.hex()

    def test_protocol_boundary_normalizes_transport_envelope(self) -> None:
        frame = "79f4882f28b42d008f9ce5802419048307018005c41b00000000000000000000000000007bd6"
        observations = decode_receiver_event(
            {
                "time": "2026-08-12T20:00:00+00:00",
                "rssi": -47.5,
                "rows": [{"len": len(frame) * 4, "data": frame}],
                "bridge_metadata": {
                    "node_id": "rp-001122334455",
                    "channel": 1,
                },
            },
            catalog=LEGACY_HOME_CATALOG,
        )
        self.assertEqual(1, len(observations))
        observation = observations[0]
        self.assertEqual(frame, observation.decoded["frame_hex"])
        self.assertEqual(-47.5, observation.metadata["rf_rssi_db"])
        self.assertEqual(
            "rp-001122334455", observation.metadata["rf_receiver_id"]
        )

    def test_product_identity_requires_catalogued_packet_evidence(self) -> None:
        provisional = hcs02x_identity({})
        self.assertEqual(GENERIC_HCS02X_MODEL, provisional.model)
        self.assertFalse(provisional.exact_model)

        by_product = hcs02x_identity({"product_code": 0x48})
        self.assertEqual(GENERIC_HCS02X_MODEL, by_product.model)
        self.assertEqual("rf_product_code_family", by_product.source)
        self.assertFalse(by_product.exact_model)
        self.assertEqual(
            ("soil_moisture", "battery", "signal_strength"),
            by_product.catalog_capabilities,
        )

        by_model = hcs02x_identity({"model_code": 0x013D})
        self.assertEqual("HCS026FRF", by_model.model)
        self.assertEqual("rf_model_code", by_model.source)

        by_both = hcs02x_identity(
            {"product_code": 0x48, "model_code": 0x013D}
        )
        self.assertEqual("HCS026FRF", by_both.model)
        self.assertEqual("rf_product_and_model_codes", by_both.source)

        self.assertIsNone(
            product_from_codes(
                "soil_sensor", product_code=0x48, model_code=0x012E
            )
        )

    def test_transport_identity_is_supplied_by_device_catalog(self) -> None:
        catalog = DeviceCatalog(
            sensors=(
                SensorDefinition(
                    "9ce58024", "sensor-custom", "Custom Sensor"
                ),
            ),
            valves=(
                ValveDefinition(
                    "b42d008f",
                    "b9840280",
                    "valve-custom",
                    "Custom Valve",
                ),
            ),
            hcs026_pairing_peers=frozenset(("B9840280",)),
        )
        gateway = Gateway(transport="rtl433", catalog=catalog)
        transport = RTL433Transport(gateway, command=["unused"])
        transport.seed()

        self.assertEqual(
            {"sensor-custom", "valve-custom"},
            {device["device_id"] for device in gateway.devices()},
        )
        frame = "79f4882f28b42d008f9ce5802419048307018005c41b00000000000000000000000000007bd6"
        self.assertEqual(
            1,
            transport.consume_line(
                json.dumps(
                    {"rows": [{"len": len(frame) * 4, "data": frame}]}
                )
            ),
        )
        sensor = next(
            device
            for device in gateway.devices()
            if device["device_id"] == "sensor-custom"
        )
        self.assertEqual("Custom Sensor", sensor["name"])
        self.assertEqual(54, sensor["state"]["soil_moisture_percent"])
        self.assertEqual("local-sdr", sensor["state"]["rf_receiver_id"])

    def test_device_catalog_rejects_duplicate_rf_identities(self) -> None:
        with self.assertRaisesRegex(ValueError, "sensor endpoints"):
            DeviceCatalog(
                sensors=(
                    SensorDefinition("aabbcc24", "sensor-a", "A"),
                    SensorDefinition("AABBCC24", "sensor-b", "B"),
                )
            )

    def test_device_catalog_loads_arbitrary_installation_json(self) -> None:
        value = {
            "sensors": [
                {
                    "endpoint": "aabbcc24",
                    "device_id": "soil-greenhouse",
                    "name": "Greenhouse",
                }
            ],
            "valves": [
                {
                    "controller_endpoint": "11223344",
                    "valve_endpoint": "55667788",
                    "device_id": "valve-orchard",
                    "name": "Orchard",
                }
            ],
            "hcs026_pairing_peers": ["55667788"],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            path.write_text(json.dumps(value))
            catalog = load_catalog(path)
        self.assertEqual("soil-greenhouse", catalog.sensor("aabbcc24").device_id)
        self.assertEqual(
            "valve-orchard",
            catalog.valve_link("55667788", "11223344").device_id,
        )
        self.assertEqual(frozenset(("55667788",)), catalog.hcs026_pairing_peers)

    def test_catalogued_valves_keep_independent_receive_state(self) -> None:
        catalog = DeviceCatalog(
            valves=(
                ValveDefinition(
                    "b42d008f", "b9840280", "valve-a", "Valve A"
                ),
                ValveDefinition(
                    "11223344", "55667788", "valve-b", "Valve B"
                ),
            )
        )
        gateway = Gateway(transport="rtl433", catalog=catalog)
        transport = RTL433Transport(gateway, command=["unused"])
        transport.seed()
        valve_b_open = bytearray.fromhex(
            "79f4882f28b9840280b42d008f89810785898090cf870200"
            "0040d58256d80200000000003fc6"
        )
        valve_b_open[5:9] = bytes.fromhex("55667788")
        valve_b_open[9:13] = bytes.fromhex("11223344")
        valve_b_open[29:31] = encode_duration(60)
        trailer = binascii.crc_hqx(valve_b_open[:-2], 0) ^ 0x4F03
        valve_b_open[-2:] = trailer.to_bytes(2, "big")
        self.assertEqual(
            1,
            transport.consume_line(
                json.dumps(
                    {
                        "rows": [
                            {
                                "len": len(valve_b_open) * 8,
                                "data": valve_b_open.hex(),
                            }
                        ]
                    }
                )
            ),
        )

        devices = {device["device_id"]: device for device in gateway.devices()}
        self.assertFalse(devices["valve-a"]["available"])
        self.assertIsNone(devices["valve-a"]["state"]["is_watering"])
        self.assertTrue(devices["valve-b"]["state"]["is_watering"])
        self.assertEqual(60, devices["valve-b"]["state"]["duration_seconds"])

    def test_registry_adds_dynamic_sensor_to_live_ingestion(self) -> None:
        source = "79f4882f28b42d008f9ce5802419048307018005c41b00000000000000000000000000007bd6"
        frame = self._frame_with_endpoint(source, "aabbcc24")
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(storage))
            transport = RTL433Transport(gateway, command=["unused"])

            self.assertEqual(
                1,
                transport.consume_line(
                    json.dumps(
                        {"rows": [{"len": len(frame) * 4, "data": frame}]}
                    )
                ),
            )
            self.assertEqual([], gateway.devices())
            registration = gateway.accept_endpoint(
                endpoint="aabbcc24",
                name="Registry Sensor",
                model="HCS026FRF",
                area="Test Bed",
            )
            self.assertEqual("local-aabbcc24", registration["device_id"])

            self.assertEqual(
                1,
                transport.consume_line(
                    json.dumps(
                        {"rows": [{"len": len(frame) * 4, "data": frame}]}
                    )
                ),
            )
            device = gateway.devices()[0]
            self.assertEqual("local-aabbcc24", device["device_id"])
            self.assertEqual("Registry Sensor", device["name"])
            self.assertEqual("Test Bed", device["area"])
            self.assertEqual(54, device["state"]["soil_moisture_percent"])
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(storage))
            restored_device = restored.devices()[0]
            self.assertEqual("local-aabbcc24", restored_device["device_id"])
            self.assertEqual("Registry Sensor", restored_device["name"])
            self.assertEqual("Test Bed", restored_device["area"])
            restored.close()

    def test_registry_metadata_applies_before_first_decoded_report(self) -> None:
        source = "79f4882f28b42d008f9ce5802419048307018005c41b00000000000000000000000000007bd6"
        frame = self._frame_with_endpoint(source, "aabbcc24")
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(storage))
            transport = RTL433Transport(gateway, command=["unused"])
            transport.consume_line(
                json.dumps(
                    {"rows": [{"len": len(frame) * 4, "data": frame}]}
                )
            )
            gateway.accept_endpoint(
                endpoint="aabbcc24",
                name="Waiting Sensor",
                model="HCS026FRF",
                area="Nursery",
            )
            immediate = gateway.devices()[0]
            self.assertEqual("local-aabbcc24", immediate["device_id"])
            self.assertEqual("Waiting Sensor", immediate["name"])
            self.assertEqual("Nursery", immediate["area"])
            self.assertFalse(immediate["available"])
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(storage))
            restored_transport = RTL433Transport(
                restored, command=["unused"]
            )
            restored_transport.seed()
            device = restored.devices()[0]
            self.assertEqual("local-aabbcc24", device["device_id"])
            self.assertEqual("Waiting Sensor", device["name"])
            self.assertEqual("Nursery", device["area"])
            self.assertFalse(device["available"])
            restored.close()

    def test_registry_metadata_preserves_known_home_assistant_identity(self) -> None:
        frame = "79f4882f28b42d008f9ce5802419048307018005c41b00000000000000000000000000007bd6"
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(storage))
            transport = RTL433Transport(gateway, command=["unused"])
            transport.consume_line(
                json.dumps(
                    {"rows": [{"len": len(frame) * 4, "data": frame}]}
                )
            )
            registration = gateway.accept_endpoint(
                endpoint="9ce58024",
                name="Renamed Right Bed",
                model="HCS026FRF",
                area="Vegetable Garden",
            )
            self.assertEqual("soil-right-bed", registration["device_id"])
            transport.consume_line(
                json.dumps(
                    {"rows": [{"len": len(frame) * 4, "data": frame}]}
                )
            )
            device = gateway.devices()[0]
            self.assertEqual("soil-right-bed", device["device_id"])
            self.assertEqual("Renamed Right Bed", device["name"])
            self.assertEqual("Vegetable Garden", device["area"])
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(storage))
            restored_device = restored.devices()[0]
            self.assertEqual("soil-right-bed", restored_device["device_id"])
            self.assertEqual("Renamed Right Bed", restored_device["name"])
            self.assertEqual("Vegetable Garden", restored_device["area"])
            restored.close()

    def test_forgotten_sensor_stays_hidden_until_explicitly_accepted(self) -> None:
        frame = "79f4882f28b42d008f9ce5802419048307018005c41b00000000000000000000000000007bd6"
        line = json.dumps(
            {"rows": [{"len": len(frame) * 4, "data": frame}]}
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(storage))
            transport = RTL433Transport(gateway, command=["unused"])
            transport.consume_line(line)
            gateway.accept_endpoint(
                endpoint="9ce58024",
                name="Right Bed",
                model="HCS026FRF",
            )
            gateway.forget_registry_device("soil-right-bed")
            self.assertEqual([], gateway.devices())
            self.assertTrue(gateway.endpoint_suppressed("9ce58024"))

            transport.consume_line(line)
            self.assertEqual([], gateway.devices())
            self.assertEqual("rf_frame", gateway.events()[-1]["event_type"])
            self.assertNotIn("device_id", gateway.events()[-1])
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(storage))
            restored_transport = RTL433Transport(
                restored, command=["unused"]
            )
            restored_transport.seed()
            restored_transport.consume_line(line)
            self.assertNotIn(
                "soil-right-bed",
                {device["device_id"] for device in restored.devices()},
            )

            registration = restored.accept_endpoint(
                endpoint="9ce58024",
                name="Right Bed Again",
                model="HCS026FRF",
            )
            self.assertEqual("soil-right-bed", registration["device_id"])
            self.assertFalse(restored.endpoint_suppressed("9ce58024"))
            restored_transport.consume_line(line)
            device = next(
                item
                for item in restored.devices()
                if item["device_id"] == "soil-right-bed"
            )
            self.assertEqual("soil-right-bed", device["device_id"])
            self.assertEqual("Right Bed Again", device["name"])
            restored.close()

    def test_automatically_discovered_sensor_can_be_forgotten(self) -> None:
        frame = (
            "79f4882f28b984028095a980240581820205c405800000000000000000000000000000006de1"
        )
        line = json.dumps(
            {"rows": [{"len": len(frame) * 4, "data": frame}]}
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(storage))
            transport = RTL433Transport(gateway, command=["unused"])
            transport.consume_line(line)
            self.assertIn(
                "hcs026-95a98024",
                {item["device_id"] for item in gateway.devices()},
            )

            forgotten = gateway.forget_sensor("hcs026-95a98024")
            self.assertEqual("95a98024", forgotten["endpoint"])
            self.assertEqual("15a98024", forgotten["factory_endpoint"])
            self.assertFalse(forgotten["registry_record_removed"])
            self.assertEqual([], gateway.devices())
            self.assertTrue(gateway.endpoint_suppressed("95a98024"))

            transport.consume_line(line)
            self.assertEqual([], gateway.devices())
            gateway.close()

    def test_device_catalog_normalizes_and_validates_endpoints(self) -> None:
        sensor = SensorDefinition("AABBCC24", "sensor-a", "A")
        valve = ValveDefinition("1111111A", "2222222B", "valve-a", "A")
        self.assertEqual("aabbcc24", sensor.endpoint)
        self.assertEqual("1111111a", valve.controller_endpoint)
        catalog = DeviceCatalog(
            hcs026_pairing_peers=frozenset(("AABBCCDD",))
        )
        self.assertEqual(
            frozenset(("aabbccdd",)), catalog.hcs026_pairing_peers
        )
        with self.assertRaisesRegex(ValueError, "four bytes"):
            SensorDefinition("abcd", "sensor-b", "B")
        with self.assertRaisesRegex(ValueError, "hexadecimal"):
            SensorDefinition("not-hex!", "sensor-b", "B")
        with self.assertRaisesRegex(ValueError, "device IDs"):
            DeviceCatalog(
                sensors=(SensorDefinition("aabbcc24", "same", "A"),),
                valves=(
                    ValveDefinition("11111111", "22222222", "same", "B"),
                ),
            )
        with self.assertRaisesRegex(ValueError, "valve endpoint links"):
            DeviceCatalog(
                valves=(
                    ValveDefinition("11111111", "22222222", "a", "A"),
                    ValveDefinition("22222222", "11111111", "b", "B"),
                )
            )

    def test_gateway_pairing_reply_fixture_has_valid_trailers(self) -> None:
        fixture = json.loads(
            (
                ROOT
                / "research/fixtures/hcs026_gateway_pairing_replies.json"
            ).read_text()
        )
        for sequence in fixture["sequences"]:
            for frame in sequence["frames"]:
                with self.subTest(sequence=sequence["name"], frame=frame):
                    decoded = normalize_row({"len": len(frame) * 4, "data": frame})
                    self.assertTrue(decoded["trailer_valid"])
                    self.assertEqual(
                        sequence["paired_endpoint"], decoded["endpoint_a"]
                    )
                    self.assertEqual("39840280", decoded["endpoint_b"])

    def test_successful_local_pairing_fixture_records_terminal_and_telemetry(self) -> None:
        fixture = json.loads(
            (
                ROOT
                / "research/fixtures/hcs026_gateway_pairing_replies.json"
            ).read_text()
        )
        sequence = next(
            item
            for item in fixture["sequences"]
            if item["name"] == "sensor_b_local_enrollment_isolated_success_20260811"
        )
        terminal = normalize_row(
            {
                "len": len(sequence["terminal_frame"]) * 4,
                "data": sequence["terminal_frame"],
            }
        )
        telemetry = normalize_row(
            {
                "len": len(sequence["first_telemetry_frame"]) * 4,
                "data": sequence["first_telemetry_frame"],
            }
        )
        self.assertTrue(sequence["stock_gateway_isolated"])
        self.assertTrue(terminal["trailer_valid"])
        self.assertEqual("95a98024", terminal["endpoint_b"])
        self.assertEqual(3, terminal["message_type"])
        self.assertTrue(telemetry["trailer_valid"])
        self.assertEqual("95a98024", telemetry["endpoint_b"])
        self.assertEqual(5, telemetry["message_type"])
        body = bytes.fromhex(telemetry["message_body"])
        moisture = body[6] * 2 + bool(body[7] & 0x80)
        self.assertEqual(sequence["first_telemetry_moisture_percent"], moisture)
        self.assertEqual(
            sequence["first_telemetry_moisture_percent"],
            telemetry["soil_moisture_percent"],
        )
        self.assertEqual("paired", telemetry["hcs026_pairing_state"])

    def test_demodulates_short_gateway_pairing_reply_offline(self) -> None:
        frame = bytes.fromhex(
            "79f4882f2895a98024398402808140880503847000f4730a0d008080000000000000000060a8"
        )
        data, _ = generate_command(
            frame,
            wake_symbols=320,
            channel_center_hz=433_471_500,
        )
        with tempfile.NamedTemporaryFile(suffix=".cu8") as capture:
            capture.write(data)
            capture.flush()
            recovered = demodulate(
                Path(capture.name),
                sample_rate=2_000_000,
                capture_center_hz=433_700_000,
            )
        self.assertEqual(frame.hex(), recovered["matches"][0]["frame_hex"])

    def test_decodes_controlled_hcs026_pairing_and_battery_fixtures(self) -> None:
        fixture = json.loads(
            (ROOT / "research/fixtures/hcs026_pairing_battery.json").read_text()
        )
        for observation in fixture["observations"]:
            with self.subTest(observation=observation["name"]):
                frame = observation["frame"]
                decoded = normalize_row({"len": len(frame) * 4, "data": frame})
                self.assertTrue(decoded["trailer_valid"])
                self.assertEqual(
                    observation["factory_endpoint"],
                    decoded["hcs026_factory_endpoint"],
                )
                self.assertEqual(
                    observation["pairing_state"],
                    decoded["hcs026_pairing_state"],
                )
                for key in (
                    "paired_endpoint",
                    "soil_moisture_percent",
                    "battery_percent",
                    "battery_low",
                ):
                    if key in observation:
                        decoded_key = (
                            "hcs026_paired_endpoint"
                            if key == "paired_endpoint"
                            else key
                        )
                        self.assertEqual(observation[key], decoded[decoded_key])

    def test_decodes_marker_relative_battery_for_every_sensor_layout(self) -> None:
        reports = {
            "Front Yard Sensor 1": (
                "79f4882f28b9840280ce6280241301820305c41b8000000000000000000000000000000064cc"
            ),
            "Front Yard Sensor 2": (
                "79f4882f28b9840280d1e280241b01820785c42680000000000000000000000000000000437b"
            ),
            "Left Bed": (
                "79f4882f28b9840280c4e500241081820385c41c000000000000000000000000000000003169"
            ),
            "Right Bed": (
                "79f4882f28b42d008f9ce5802410848307018005441c800000000000000000000000000013fb"
            ),
            "Test Sensor A": (
                "79f4882f28b98402809bce00240681820485c400800000000000000000000000000000000a18"
            ),
        }
        for name, frame in reports.items():
            with self.subTest(sensor=name):
                decoded = normalize_row(
                    {"len": len(frame) * 4, "data": frame}
                )
                self.assertTrue(decoded["trailer_valid"])
                self.assertEqual(100, decoded["battery_percent"])
                self.assertFalse(decoded["battery_low"])

        test_b = (
            "79f4882f28b984028095a98024098182020544008000000000000000000000000000000045a2"
        )
        test_b_catalog = DeviceCatalog(
            sensors=(
                SensorDefinition(
                    "95a98024", "hcs026-95a98024", "Test Sensor B"
                ),
            ),
            hcs026_pairing_peers=frozenset(("b9840280",)),
        )
        decoded = normalize_row(
            {"len": len(test_b) * 4, "data": test_b},
            catalog=test_b_catalog,
        )
        self.assertEqual(100, decoded["battery_percent"])

    def test_invalid_report_cannot_update_supported_battery(self) -> None:
        frame = (
            "79f4882f28b9840280ce6280240281820301441c000000000000000000000000000000000000"
        )
        decoded = normalize_row({"len": len(frame) * 4, "data": frame})
        self.assertFalse(decoded["trailer_valid"])
        self.assertEqual(56, decoded["soil_moisture_percent"])
        self.assertNotIn("battery_percent", decoded)

    def test_dynamic_paired_hcs026_becomes_a_device_and_restores(self) -> None:
        full_frame = (
            "79f4882f28b98402809bce00240301820485c40080000000000000000000000000000000518b"
        )
        low_frame = (
            "79f4882f28b98402809bce00240301820481c400800000000000000000000000000000001994"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(storage))
            transport = RTL433Transport(gateway, command=["unused"])
            for frame in (full_frame, low_frame):
                self.assertEqual(
                    1,
                    transport.consume_line(
                        json.dumps({"rows": [{"len": len(frame) * 4, "data": frame}]})
                    ),
                )
            device = gateway.devices()[0]
            self.assertEqual("hcs026-9bce0024", device["device_id"])
            self.assertEqual(1, device["state"]["soil_moisture_percent"])
            self.assertEqual(10, device["state"]["battery_percent"])
            self.assertTrue(device["state"]["battery_low"])
            self.assertEqual("1bce0024", device["state"]["rf_factory_endpoint"])
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(storage))
            restored_device = restored.devices()[0]
            self.assertEqual("hcs026-9bce0024", restored_device["device_id"])
            self.assertEqual(10, restored_device["state"]["battery_percent"])
            restored.close()

    def test_invalid_dynamic_hcs026_cannot_create_a_device(self) -> None:
        frame = bytearray.fromhex(
            "79f4882f28b98402809bce00240301820485c40080000000000000000000000000000000518b"
        )
        frame[-1] ^= 0x01
        frame_hex = frame.hex()
        gateway = Gateway(transport="rtl433")
        transport = RTL433Transport(gateway, command=["unused"])
        self.assertEqual(
            1,
            transport.consume_line(
                json.dumps({"rows": [{"len": len(frame_hex) * 4, "data": frame_hex}]})
            ),
        )
        self.assertEqual([], gateway.devices())
        event = gateway.events()[0]
        self.assertEqual("hcs026-9bce0024", event["device_id"])
        self.assertFalse(event["state"]["rf_frame_accepted"])

    def test_builds_captured_valve_commands_offline(self) -> None:
        open_frame = build_open_frame(
            self.CAPTURED_VALVE_LINK, 0x97, 60, 0xC713
        )
        self.assertEqual(
            "79f4882f28b42d008fb98402809710828081009e000000000000000000000000000000003824",
            open_frame.hex(),
        )
        close_frame = build_close_frame(
            self.CAPTURED_VALVE_LINK, 0x97, 0x4F03
        )
        self.assertEqual(
            "79f4882f28b42d008fb984028097908180810000000000000000000000000000000000006fcf",
            close_frame.hex(),
        )
        self.assertEqual(
            2, len(open_candidates(self.CAPTURED_VALVE_LINK, 0x97, 60))
        )
        self.assertEqual(
            2, len(close_candidates(self.CAPTURED_VALVE_LINK, 0x97))
        )
        self.assertEqual(0x80, next_sequence(0x9F))

    def test_valve_frame_builder_requires_association_specific_endpoints(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly four bytes"):
            ValveLink(b"short", bytes.fromhex("b9840280"))
        with self.assertRaisesRegex(ValueError, "must differ"):
            ValveLink(bytes.fromhex("01020304"), bytes.fromhex("01020304"))

    def test_encodes_confirmed_whole_minute_valve_durations(self) -> None:
        self.assertEqual(bytes.fromhex("9e00"), encode_duration(60))
        self.assertEqual(bytes.fromhex("f800"), encode_duration(240))
        self.assertEqual(bytes.fromhex("fe01"), encode_duration(1020))
        self.assertEqual(60, decode_duration(bytes.fromhex("9e00")))
        self.assertEqual(240, decode_duration(bytes.fromhex("f800")))
        self.assertEqual(1020, decode_duration(bytes.fromhex("fe01")))
        with self.assertRaisesRegex(ValueError, "whole-minute"):
            encode_duration(61)

    def test_characterizes_synthetic_two_fsk_capture(self) -> None:
        sample_rate = 2_000_000
        center = 433_700_000
        tones = (434_200_000, 434_280_000)
        phase = 0.0
        data = bytearray()
        for index in range(65_536):
            tone = tones[(index // 100) % 2]
            phase += 2 * math.pi * (tone - center) / sample_rate
            data.extend(
                (
                    round(127.5 + 80 * math.cos(phase)),
                    round(127.5 + 80 * math.sin(phase)),
                )
            )
        with tempfile.NamedTemporaryFile(suffix=".cu8") as capture:
            capture.write(data)
            capture.flush()
            measured = characterize(
                Path(capture.name),
                sample_rate=sample_rate,
                center_frequency=center,
            )
        self.assertAlmostEqual(tones[0], measured["low_tone_hz"], delta=50)
        self.assertAlmostEqual(tones[1], measured["high_tone_hz"], delta=50)
        self.assertAlmostEqual(80_000, measured["tone_separation_hz"], delta=50)

    def test_generates_measured_command_waveform_offline(self) -> None:
        frame = build_open_frame(self.CAPTURED_VALVE_LINK, 0x97, 60, 0xC713)
        symbols = command_symbols(frame)
        self.assertEqual(1_504, len(symbols))
        self.assertEqual([1, 0, 1, 0], symbols[:4])
        self.assertEqual(
            [int(bit) for bit in f"{frame[0]:08b}"], symbols[1_200:1_208]
        )

        data, metadata = generate_command(frame)
        self.assertEqual(340_800, len(data))
        self.assertEqual(60, metadata["wake_duration_ms"])
        self.assertEqual(15.2, metadata["frame_duration_ms"])
        self.assertEqual(80_000, metadata["deviation_hz"] * 2)
        self.assertEqual(
            "offline file only; no transmit path", metadata["safety"]
        )

        with tempfile.NamedTemporaryFile(suffix=".cu8") as capture:
            capture.write(data)
            capture.flush()
            measured = characterize(
                Path(capture.name),
                sample_rate=metadata["sample_rate_sps"],
                center_frequency=metadata["capture_center_hz"],
            )
        self.assertAlmostEqual(
            metadata["channel_center_hz"],
            measured["channel_center_hz"],
            delta=50,
        )
        self.assertAlmostEqual(80_000, measured["tone_separation_hz"], delta=50)

    def test_offline_waveform_rejects_invalid_frame(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly 38 bytes"):
            command_symbols(b"short")
        with self.assertRaisesRegex(ValueError, "must begin with sync"):
            command_symbols(bytes(38))

    def test_compares_offline_waveform_spectral_profile(self) -> None:
        frame = build_close_frame(self.CAPTURED_VALVE_LINK, 0x97, 0x4F03)
        reference_data, _ = generate_command(frame)
        candidate_data, _ = generate_command(
            frame,
            channel_center_hz=434_242_000,
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            reference = Path(temporary_directory) / "reference.cu8"
            candidate = Path(temporary_directory) / "candidate.cu8"
            reference.write_bytes(reference_data)
            candidate.write_bytes(candidate_data)
            result = compare_waveforms(reference, candidate)
        self.assertTrue(result["spectral_match"])
        self.assertAlmostEqual(
            2_000,
            result["comparisons"]["channel_center_hz"]["delta_hz"],
            delta=100,
        )
        self.assertAlmostEqual(
            0,
            result["comparisons"]["tone_separation_hz"]["delta_hz"],
            delta=100,
        )

    def test_normalizes_short_preamble_frame(self) -> None:
        row = {
            "len": 627,
            "data": (
                "55" * 40
                + "79f4882f28b9840280b42d008f9750868010cf92800000409e00569e"
                + "000000000000000044ce0"
            ),
        }
        decoded = normalize_row(row)
        self.assertEqual(320, decoded["preamble_bits"])
        self.assertEqual("b9840280", decoded["endpoint_a"])
        self.assertEqual("b42d008f", decoded["endpoint_b"])
        self.assertEqual(0x97, decoded["message_type"])
        self.assertEqual("44ce", decoded["trailer"])
        self.assertEqual(3, decoded["trailing_bits"])

    def test_normalizes_long_unaligned_preamble_frame(self) -> None:
        row = {
            "len": 1509,
            "data": (
                "a" * 300
                + "bcfa4417945a168047dcc201404b88414040804f"
                + "000000000000000000000000000000001c1240"
            ),
        }
        decoded = normalize_row(row)
        self.assertEqual(1201, decoded["preamble_bits"])
        self.assertEqual("79f4882f28", decoded["sync"])
        self.assertEqual("b42d008f", decoded["endpoint_a"])
        self.assertEqual("b9840280", decoded["endpoint_b"])
        self.assertEqual("3824", decoded["trailer"])
        self.assertEqual(4, decoded["trailing_bits"])

    def test_rejects_unknown_or_truncated_rows(self) -> None:
        with self.assertRaisesRegex(ValueError, "sync word"):
            normalize_row({"len": 32, "data": "aaaaaaaa"})
        with self.assertRaisesRegex(ValueError, "truncated"):
            normalize_row({"len": 48, "data": "79f4882f2800"})

    def test_decodes_correlated_hcs026_moisture(self) -> None:
        # Right Bed was 64% in HA after this packet and its short follow-up.
        frame = bytes.fromhex(
            "79f4882f28b42d008f9ce580240784830701800544200000000000000000000000000000308a"
        )
        row = {"len": len(frame) * 8, "data": frame.hex()}
        decoded = normalize_row(row)
        self.assertEqual(64, decoded["soil_moisture_percent"])

        # The high bit in the preceding packed byte varies independently.
        frame = bytes.fromhex(
            "79f4882f28b42d008f9ce580240c048307018005c41f00000000000000000000000000003114"
        )
        row = {"len": len(frame) * 8, "data": frame.hex()}
        decoded = normalize_row(row)
        self.assertEqual(62, decoded["soil_moisture_percent"])

    def test_decodes_lower_channel_hcs026_moisture_layout(self) -> None:
        # Front Yard Sensor 1: 0x1d * 2 plus the following high bit = 59%.
        frame = bytes.fromhex(
            "79f4882f28b9840280ce6280240981820305c41d80"
            "000000000000000000000000000000005e4e"
        )
        decoded = normalize_row({"len": len(frame) * 8, "data": frame.hex()})
        self.assertEqual("ce628024", decoded["endpoint_b"])
        self.assertEqual(59, decoded["soil_moisture_percent"])

        # The previously unassigned endpoint matches Front Yard Sensor 2 at 79%.
        frame = bytes.fromhex(
            "79f4882f28b9840280d1e280240081820785c42780"
            "000000000000000000000000000000006e5c"
        )
        decoded = normalize_row({"len": len(frame) * 8, "data": frame.hex()})
        self.assertEqual("d1e28024", decoded["endpoint_b"])
        self.assertEqual(79, decoded["soil_moisture_percent"])

        # Left Bed uses the same lower-channel layout without the odd flag.
        frame = bytes.fromhex(
            "79f4882f28b9840280c4e500240e01820385441d00"
            "000000000000000000000000000000001a57"
        )
        decoded = normalize_row({"len": len(frame) * 8, "data": frame.hex()})
        self.assertEqual("c4e50024", decoded["endpoint_b"])
        self.assertEqual(58, decoded["soil_moisture_percent"])

    def test_decodes_hcs026_product_code_tlv_layout(self) -> None:
        # Front Yard Sensor 2 used the full 0x48 product code in this extended
        # report. The normal d1e28024 acknowledgement followed 180 ms later,
        # and 0x88 0x4f carries its independently observed 79% moisture value.
        frame = bytes.fromhex(
            "79f4882f28b9840280d1e280482c03040f0a884f"
            "000000000000000000000000000000001b77"
        )
        decoded = normalize_row({"len": len(frame) * 8, "data": frame.hex()})
        self.assertEqual("d1e28048", decoded["endpoint_b"])
        self.assertEqual("d1e28024", decoded["canonical_endpoint_b"])
        self.assertEqual(72, decoded["product_code"])
        self.assertEqual(79, decoded["status_soil_moisture_percent"])
        self.assertEqual(79, decoded["soil_moisture_percent"])

        unknown = bytearray(frame)
        unknown[9:13] = bytes.fromhex("aabbcc48")
        decoded_unknown = normalize_row(
            {"len": len(unknown) * 8, "data": unknown.hex()}
        )
        self.assertEqual(79, decoded_unknown["status_soil_moisture_percent"])
        self.assertNotIn("canonical_endpoint_b", decoded_unknown)
        self.assertNotIn("soil_moisture_percent", decoded_unknown)

    def test_identifies_stock_gateway_routine_acknowledgement(self) -> None:
        frame = bytes.fromhex(
            "79f4882f28c4e500243984028088c181000100000000"
            "000000000000000000000000000022e3"
        )
        decoded = normalize_row({"len": len(frame) * 8, "data": frame.hex()})
        self.assertEqual("c4e50024", decoded["routine_ack_endpoint"])
        self.assertEqual(8, decoded["routine_ack_message"])
        self.assertEqual(1, decoded["routine_ack_body_code"])
        self.assertEqual("c713", decoded["trailer_residual"])
        self.assertTrue(decoded["trailer_valid"])

    def test_identifies_stock_gateway_htv405_routine_acknowledgements(
        self,
    ) -> None:
        fixture = json.loads(
            (
                ROOT
                / "research"
                / "fixtures"
                / "htv405_stock_routine_ack_20260824.json"
            ).read_text(encoding="utf-8")
        )
        for pair in fixture["pairs"]:
            decoded = normalize_row(
                {"len": 38 * 8, "data": pair["reply"]}
            )
            self.assertEqual(
                "94a98013", decoded["htv405_routine_ack_valve_endpoint"]
            )
            self.assertEqual(
                "39840280", decoded["htv405_routine_ack_companion_endpoint"]
            )
            self.assertEqual(
                "b9840280", decoded["htv405_routine_ack_controller_endpoint"]
            )
            self.assertEqual(4, decoded["htv405_routine_ack_sequence"])
            self.assertEqual(
                int(pair["repeat"]), decoded["htv405_routine_ack_repeat"]
            )
            self.assertEqual(
                pair["reply_trailer_residual"], decoded["trailer_residual"]
            )

    def test_marks_known_crc_residue_and_special_frame_separately(self) -> None:
        open_frame = bytes.fromhex(
            "79f4882f28b42d008fb9840280811082808100fe0180"
            "00000000000000000000000000007669"
        )
        decoded = normalize_row(
            {"len": len(open_frame) * 8, "data": open_frame.hex()}
        )
        self.assertEqual("4f03", decoded["trailer_residual"])
        self.assertTrue(decoded["trailer_valid"])

        # The compact product-code family has a different trailer rule. Keep
        # decoding it, but do not label it as an ordinary validated frame.
        product_frame = bytes.fromhex(
            "79f4882f28b9840280d1e280482c03040f0a884f"
            "000000000000000000000000000000001b77"
        )
        decoded = normalize_row(
            {"len": len(product_frame) * 8, "data": product_frame.hex()}
        )
        self.assertEqual("94c2", decoded["trailer_residual"])
        self.assertFalse(decoded["trailer_valid"])
        self.assertEqual(79, decoded["soil_moisture_percent"])

    def test_retains_unassigned_compact_moisture_and_hub_rssi(self) -> None:
        # This followed a normal Right Bed 57% report by 835 ms. Its compact
        # status values also matched the stock integration's -79 dBm reading,
        # but the alternate routing fields are not yet sufficient to assign it
        # to a device automatically.
        frame = bytes.fromhex(
            "79f4882f28b9000101685a011f2e0a080b03000a8839e0b1"
            "000000000000000000000000000000"
        )
        decoded = normalize_row({"len": len(frame) * 8, "data": frame.hex()})
        self.assertEqual(57, decoded["status_soil_moisture_percent"])
        self.assertEqual(-79, decoded["hub_rssi_db"])
        self.assertNotIn("soil_moisture_percent", decoded)

        # A second retained form uses a slot-like 0x0b byte before the same
        # compact type-10 and type-32 headers. It remains unassigned too.
        frame = bytes.fromhex(
            "79f4882f28b9840280b42d008f8805040703000b8839e0b1"
            "00000000000000000000000001c8"
        )
        decoded = normalize_row({"len": len(frame) * 8, "data": frame.hex()})
        self.assertEqual(57, decoded["status_soil_moisture_percent"])
        self.assertEqual(-79, decoded["hub_rssi_db"])
        self.assertNotIn("soil_moisture_percent", decoded)

    def test_does_not_treat_valve_payload_as_moisture(self) -> None:
        # This strict stock-controller relay carries an associated sensor's
        # reading, but does not identify the sensor in its RF envelope.
        frame = bytes.fromhex(
            "79f4882f28b9840280b42d008f8b050405818005c4"
            "1bf05b000000000000000000000000287a"
        )
        decoded = normalize_row({"len": len(frame) * 8, "data": frame.hex()})
        self.assertEqual(55, decoded["associated_soil_moisture_percent"])
        self.assertNotIn("soil_moisture_percent", decoded)

        corrupted = bytearray(frame)
        corrupted[-1] ^= 0x01
        decoded = normalize_row(
            {"len": len(corrupted) * 8, "data": corrupted.hex()}
        )
        self.assertNotIn("associated_soil_moisture_percent", decoded)

    def test_decodes_valve_command_intent_without_inventing_state(self) -> None:
        open_frame = bytes.fromhex(
            "79f4882f28b42d008fb9840280811082808100fe0180"
            "00000000000000000000000000007669"
        )
        decoded = normalize_row(
            {"len": len(open_frame) * 8, "data": open_frame.hex()}
        )
        self.assertEqual("open", decoded["valve_command"])
        self.assertEqual(1020, decoded["requested_duration_seconds"])
        self.assertNotIn("is_watering", decoded)
        self.assertNotIn("valve_state", decoded)

        four_minute_frame = build_open_frame(
            self.CAPTURED_VALVE_LINK, 0x9B, 240, 0x4F03
        )
        decoded = normalize_row(
            {"len": len(four_minute_frame) * 8, "data": four_minute_frame.hex()}
        )
        self.assertEqual(240, decoded["requested_duration_seconds"])

        close_frame = bytes.fromhex(
            "79f4882f28b42d008fb9840280819081808100000000"
            "000000000000000000000000000011a2"
        )
        decoded = normalize_row(
            {"len": len(close_frame) * 8, "data": close_frame.hex()}
        )
        self.assertEqual("close", decoded["valve_command"])
        self.assertNotIn("is_watering", decoded)
        self.assertNotIn("valve_state", decoded)
        self.assertNotIn("requested_duration_seconds", decoded)

    def test_htv145_state_requires_valve_originated_evidence(self) -> None:
        response = bytes.fromhex(
            "79f4882f28b9840280b42d008f8150868010cf8702000040"
            "d80256d802000000000000004bfa"
        )
        decoded = normalize_row(
            {"len": len(response) * 8, "data": response.hex()}
        )
        self.assertTrue(decoded["is_watering"])
        self.assertEqual("watering", decoded["valve_state"])
        self.assertEqual(1200, decoded["duration_seconds"])
        self.assertEqual(0x81, decoded["command_response_sequence"])

        active_report = bytes.fromhex(
            "79f4882f28b9840280b42d008f89810785898090cf870200"
            "0040d58256d80200000000003fc6"
        )
        active = normalize_row(
            {"len": len(active_report) * 8, "data": active_report.hex()}
        )
        self.assertTrue(active["is_watering"])
        self.assertEqual("watering", active["valve_state"])

    def test_decodes_crossed_htv405_zone_and_duration_matrix(self) -> None:
        frames = {
            (1, 60): "79f4882f28b984028094a980130b010782858090cf80000000409b80569e0000000000002fc2",
            (1, 120): "79f4882f28b984028094a980130e010782858090cf8000000040b98056bc0000000000002756",
            (2, 60): "79f4882f28b984028094a980130f810782858110cf80000000409b80569e0000000000001163",
            (2, 120): "79f4882f28b984028094a980130c810782858110cf8000000040b90056bc000000000000604e",
            (3, 60): "79f4882f28b984028094a9801311010782858190cf80000000409b80569e0000000000003da8",
            (3, 120): "79f4882f28b984028094a9801314010782858190cf8000000040b90056bc000000000000029e",
            (4, 60): "79f4882f28b984028094a9801312810782858210cf80000000409b00569e00000000000067e8",
            (4, 120): "79f4882f28b984028094a9801315810782858210cf8000000040b98056bc0000000000001ad8",
        }
        for (zone, duration), raw in frames.items():
            with self.subTest(zone=zone, duration=duration):
                decoded = decode_htv405_control_frame(bytes.fromhex(raw))
                self.assertIsNotNone(decoded)
                self.assertEqual(zone, decoded["zone"])
                self.assertEqual(duration, decoded["duration_seconds"])
                self.assertEqual(duration - 6, decoded["remaining_seconds"])
                self.assertTrue(decoded["is_watering"])

    def test_decodes_htv405_stop_without_stale_duration(self) -> None:
        stop = bytes.fromhex(
            "79f4882f28b984028094a98013160107828582004f80000000408000568000000000000025e1"
        )
        decoded = decode_htv405_control_frame(stop)
        self.assertEqual({"zone": 4, "is_watering": False}, decoded)

        catalog = DeviceCatalog(
            valves=(
                ValveDefinition(
                    "b9840280", "94a98013", "test-four-zone",
                    "Test Four Zone", model="HTV405FRF",
                ),
            )
        )
        normalized = normalize_row(
            {"len": len(stop) * 8, "data": stop.hex()}, catalog=catalog
        )
        self.assertEqual(4, normalized["zone"])
        self.assertFalse(normalized["is_watering"])
        self.assertEqual("idle", normalized["valve_state"])
        self.assertNotIn("duration_seconds", normalized)

    def test_decodes_locally_enrolled_htv405_selector_and_all_zones(self) -> None:
        # Locally enrolled valves clear the selector high bit (0x05 instead
        # of 0x85) while retaining the confirmed four-zone body layout.
        frames = {
            1: "79f4882f28aa110280a1b2c31308810782058088cf8000000040ac0156ac010000000000296d",
            2: "79f4882f28aa110280a1b2c3130d010782058108cf8000000040ac0156ac01000000000072c7",
            3: "79f4882f28aa110280a1b2c31311010782058188cf8000000040ac0156ac0100000000002e8f",
            4: "79f4882f28aa110280a1b2c31315010782058208cf8000000040ac0156ac0100000000005af8",
        }
        for zone, raw in frames.items():
            with self.subTest(zone=zone):
                decoded = decode_htv405_control_frame(bytes.fromhex(raw))
                self.assertEqual(zone, decoded["zone"])
                self.assertTrue(decoded["is_watering"])
                self.assertEqual(88, decoded["duration_seconds"])
                self.assertEqual(88, decoded["remaining_seconds"])

    def test_live_transport_retains_independent_htv405_zone_states(self) -> None:
        catalog = DeviceCatalog(
            valves=(
                ValveDefinition(
                    "aa110280", "a1b2c313", "test-four-zone",
                    "Test Four Zone", model="HTV405FRF",
                ),
            )
        )
        gateway = Gateway(transport="rtl433", catalog=catalog)
        transport = RTL433Transport(
            gateway, command=["unused"], catalog=catalog
        )
        transport.seed()
        frames = (
            "79f4882f28aa110280a1b2c31308810782058088cf8000000040ac0156ac010000000000296d",
            "79f4882f28aa110280a1b2c3130e8107820581004f800000004080005680000000000000a443",
        )
        for frame in frames:
            event = {"rows": [{"len": len(frame) * 4, "data": frame}]}
            self.assertEqual(1, transport.consume_line(json.dumps(event)))

        valve = gateway.devices()[0]
        self.assertTrue(valve["state"]["zone_1_is_watering"])
        self.assertFalse(valve["state"]["zone_2_is_watering"])
        self.assertEqual(88, valve["state"]["zone_1_remaining_seconds"])
        self.assertIsNone(valve["state"]["zone_2_remaining_seconds"])

    def test_htv405_new_open_clears_other_mutually_exclusive_zones(self) -> None:
        catalog = DeviceCatalog(
            valves=(
                ValveDefinition(
                    "aa110280", "a1b2c313", "test-four-zone",
                    "Test Four Zone", model="HTV405FRF",
                ),
            )
        )
        gateway = Gateway(transport="rtl433", catalog=catalog)
        transport = RTL433Transport(
            gateway, command=["unused"], catalog=catalog
        )
        transport.seed()
        for frame in (
            "79f4882f28aa110280a1b2c31308810782058088cf8000000040ac0156ac010000000000296d",
            "79f4882f28aa110280a1b2c3130d010782058108cf8000000040ac0156ac01000000000072c7",
        ):
            event = {"rows": [{"len": len(frame) * 4, "data": frame}]}
            self.assertEqual(1, transport.consume_line(json.dumps(event)))
        state = gateway.devices()[0]["state"]
        self.assertFalse(state["zone_1_is_watering"])
        self.assertTrue(state["zone_2_is_watering"])
        self.assertEqual(2, state["active_zone"])
        self.assertTrue(state["is_watering"])

    def test_structural_htv405_report_persists_unknown_valve_link(self) -> None:
        frame = (
            "79f4882f28aa110280a1b2c31308810782058088cf8000000040"
            "ac0156ac010000000000296d"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(path))
            transport = RTL433Transport(gateway, command=["unused"])
            event = {"rows": [{"len": len(frame) * 4, "data": frame}]}
            self.assertEqual(1, transport.consume_line(json.dumps(event)))

            valve = next(
                item
                for item in gateway.devices()
                if item["device_id"] == "htv405-a1b2c313"
            )
            self.assertEqual("HTV405FRF", valve["model"])
            self.assertTrue(valve["state"]["zone_1_is_watering"])
            self.assertEqual(8, valve["state"]["rf_telemetry_sequence"])
            self.assertTrue(valve["state"]["rf_telemetry_repeat"])
            self.assertEqual(
                9, valve["state"]["rf_next_telemetry_sequence"]
            )
            self.assertFalse(
                valve["state"]["rf_next_telemetry_repeat"]
            )
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(path))
            link = restored.catalog.valve_link("aa110280", "a1b2c313")
            self.assertIsNotNone(link)
            self.assertEqual("htv405-a1b2c313", link.device_id)
            restored_valve = next(
                item
                for item in restored.devices()
                if item["device_id"] == "htv405-a1b2c313"
            )
            self.assertEqual(
                8, restored_valve["state"]["rf_telemetry_sequence"]
            )
            self.assertEqual(
                9, restored_valve["state"]["rf_next_telemetry_sequence"]
            )
            self.assertNotIn(
                "rf_control_counter_authenticated", restored_valve["state"]
            )
            restored.close()

    def test_periodic_htv405_link_report_does_not_infer_zone_state(self) -> None:
        frame = bytes.fromhex(
            "79f4882f28aa110280a1b2c313028107820701804f8000000040"
            "80005680000000000000837d"
        )
        self.assertTrue(is_htv405_link_frame(frame))
        self.assertIsNone(decode_htv405_control_frame(frame))
        self.assertEqual(
            {
                "rf_telemetry_sequence": 2,
                "rf_telemetry_repeat": True,
                "rf_next_telemetry_sequence": 3,
                "rf_next_telemetry_repeat": False,
            },
            htv405_phase_state(frame),
        )

    def test_decodes_only_structural_htv405_command_responses(self) -> None:
        opened = bytes.fromhex(
            "79f4882f28b984028094a9801303d0868010cf8000000040bc"
            "0056bc000000000000000038bf"
        )
        closed = bytes.fromhex(
            "79f4882f28b984028094a9801304508683104f800000004080"
            "00568000000000000000001e6e"
        )
        self.assertEqual(
            {
                "rf_control_response_sequence": 3,
                "rf_next_control_sequence": 4,
                "rf_control_response_zone": 1,
                "rf_control_response_watering": True,
            },
            decode_htv405_gateway_command_response(opened),
        )
        self.assertEqual(
            {
                "rf_control_response_sequence": 4,
                "rf_next_control_sequence": 4,
                "rf_control_response_zone": 1,
                "rf_control_response_watering": False,
            },
            decode_htv405_gateway_command_response(closed),
        )
        corrupt = bytearray(opened)
        corrupt[18] ^= 0x80
        trailer = binascii.crc_hqx(corrupt[:-2], 0) ^ 0x4F03
        corrupt[-2:] = trailer.to_bytes(2, "big")
        self.assertIsNone(decode_htv405_gateway_command_response(bytes(corrupt)))

        for zone, frame_hex in enumerate(
            (
                "79f4882f28b984028094a980130bd0868020cf80000000409e"
                "00569e000000000000000079b2",
                "79f4882f28b984028094a980130cd0868030cf80000000409e"
                "00569e000000000000000062ff",
                "79f4882f28b984028094a980130dd0868040cf80000000409e"
                "00569e00000000000000001e77",
            ),
            start=2,
        ):
            decoded = decode_htv405_gateway_command_response(
                bytes.fromhex(frame_hex)
            )
            self.assertIsNotNone(decoded)
            self.assertEqual(zone, decoded["rf_control_response_zone"])
            self.assertTrue(decoded["rf_control_response_watering"])

    def test_decodes_locally_enrolled_htv405_zone_selector(self) -> None:
        local_reports = (
            (
                2,
                "79f4882f28b984028094a98013068107820580a0cf8000000040"
                "9d00569e00000000000010ad",
            ),
            (
                3,
                "79f4882f28b984028094a980130a0107820580b0cf8000000040"
                "9b00569e0000000000005bb0",
            ),
            (
                4,
                "79f4882f28b984028094a980130e8107820580c0cf8000000040"
                "9b00569e0000000000003f2f",
            ),
        )
        for zone, frame_hex in local_reports:
            decoded = decode_htv405_control_frame(bytes.fromhex(frame_hex))
            self.assertIsNotNone(decoded)
            self.assertEqual(zone, decoded["zone"])
            self.assertTrue(decoded["is_watering"])
            self.assertEqual(60, decoded["duration_seconds"])

    def test_local_multizone_control_fixture_is_fully_crossed(self) -> None:
        fixture = json.loads(
            (
                ROOT
                / "research"
                / "fixtures"
                / "htv405_local_multizone_control_20260823.json"
            ).read_text()
        )
        for trial in fixture["trials"]:
            with self.subTest(zone=trial["zone"]):
                response = decode_htv405_gateway_command_response(
                    bytes.fromhex(trial["response_frame"])
                )
                self.assertEqual(
                    trial["zone"], response["rf_control_response_zone"]
                )
                self.assertTrue(response["rf_control_response_watering"])

                active = decode_htv405_control_frame(
                    bytes.fromhex(trial["active_report"])
                )
                self.assertEqual(trial["zone"], active["zone"])
                self.assertTrue(active["is_watering"])
                self.assertEqual(60, active["duration_seconds"])

                phase_only = bytes.fromhex(trial["phase_only_report"])
                self.assertTrue(is_htv405_link_frame(phase_only))
                self.assertIsNone(decode_htv405_control_frame(phase_only))

                idle = decode_htv405_control_frame(
                    bytes.fromhex(trial["idle_report"])
                )
                self.assertEqual(
                    {"zone": 0, "is_watering": False}, idle
                )

    def test_local_idle_report_clears_every_zone(self) -> None:
        catalog = DeviceCatalog(
            valves=(
                ValveDefinition(
                    "b9840280", "94a98013", "test-four-zone",
                    "Test Four Zone", model="HTV405FRF",
                ),
            )
        )
        gateway = Gateway(transport="rtl433", catalog=catalog)
        transport = RTL433Transport(
            gateway, command=["unused"], catalog=catalog
        )
        transport.seed()
        frames = (
            "79f4882f28b984028094a98013088107820580c0cf80000000409b00569e0000000000007134",
            "79f4882f28b984028094a980130b0107820580804f8000000040800056800000000000007e28",
        )
        for frame in frames:
            event = {"rows": [{"len": len(frame) * 4, "data": frame}]}
            self.assertEqual(1, transport.consume_line(json.dumps(event)))

        state = gateway.devices()[0]["state"]
        self.assertIsNone(state["active_zone"])
        self.assertFalse(state["is_watering"])
        for zone in range(1, 5):
            self.assertFalse(state[f"zone_{zone}_is_watering"])
            self.assertIsNone(state[f"zone_{zone}_remaining_seconds"])

    def test_crossed_htv405_fixture_covers_every_zone_and_duration(self) -> None:
        fixture = json.loads(
            (
                ROOT
                / "research"
                / "fixtures"
                / "htv405_crossed_zone_reports_20260817.json"
            ).read_text(encoding="utf-8")
        )
        decoded_trials = []
        for trial in fixture["trials"]:
            opened = decode_htv405_control_frame(
                bytes.fromhex(trial["open_frame"])
            )
            closed = decode_htv405_control_frame(
                bytes.fromhex(trial["close_frame"])
            )
            self.assertEqual(trial["zone"], opened["zone"])
            self.assertTrue(opened["is_watering"])
            self.assertEqual(
                trial["duration_seconds"], opened["duration_seconds"]
            )
            self.assertEqual(trial["zone"], closed["zone"])
            self.assertFalse(closed["is_watering"])
            decoded_trials.append(
                (trial["zone"], trial["duration_seconds"])
            )
        self.assertEqual(
            {(zone, duration) for zone in range(1, 5) for duration in (60, 120)},
            set(decoded_trials),
        )

    def test_stock_cloud_matrix_decodes_reused_logical_address_six(self) -> None:
        fixture = json.loads(
            (
                ROOT
                / "research"
                / "fixtures"
                / "htv405_stock_cloud_control_matrix_20260824.json"
            ).read_text(encoding="utf-8")
        )
        observed_zones = set()
        for trial in fixture["trials"]:
            zone = trial["zone"]
            opened = decode_htv405_control_frame(
                bytes.fromhex(trial["active_report_frame"])
            )
            closed = decode_htv405_control_frame(
                bytes.fromhex(trial["idle_report_frame"])
            )
            self.assertIsNotNone(opened)
            self.assertIsNotNone(closed)
            self.assertEqual(
                6,
                bytes.fromhex(trial["active_report_frame"])[16] & 0x7F,
            )
            self.assertEqual(
                6,
                bytes.fromhex(trial["idle_report_frame"])[16] & 0x7F,
            )
            self.assertEqual(zone, opened["zone"])
            self.assertEqual(zone, closed["zone"])
            self.assertTrue(opened["is_watering"])
            self.assertFalse(closed["is_watering"])
            self.assertEqual(60, opened["duration_seconds"])

            for action, operation, companion in (
                ("open", 0x90, 0x82),
                ("close", 0x10, 0x81),
            ):
                command = bytes.fromhex(trial[f"{action}_command_frame"])
                residual = binascii.crc_hqx(
                    command[:-2], 0
                ) ^ int.from_bytes(command[-2:], "big")
                packed_zone = (
                    2 * (command[16] & 0x7F)
                    + int(bool(command[17] & 0x80))
                )
                self.assertIn(residual, {0xC713, 0x4F03})
                self.assertEqual(operation, command[14])
                self.assertEqual(companion, command[15])
                self.assertEqual(zone, packed_zone)
                self.assertEqual(1, command[17] & 0x7F)
            self.assertEqual(
                60,
                decode_duration(
                    bytes.fromhex(trial["open_command_frame"])[19:21]
                ),
            )
            observed_zones.add(zone)

        self.assertEqual({1, 2, 3, 4}, observed_zones)

    def test_stock_htv405_auto_stop_is_report_driven(self) -> None:
        fixture = json.loads(
            (
                ROOT
                / "research"
                / "fixtures"
                / "htv405_stock_auto_stop_20260824.json"
            ).read_text(encoding="utf-8")
        )
        active = decode_htv405_control_frame(
            bytes.fromhex(fixture["active_report"]["frame"])
        )
        idle = decode_htv405_control_frame(
            bytes.fromhex(fixture["idle_report"]["frame"])
        )
        self.assertEqual(
            {
                "zone": 1,
                "is_watering": True,
                "duration_seconds": 60,
                "remaining_seconds": 54,
            },
            active,
        )
        self.assertEqual({"zone": 1, "is_watering": False}, idle)
        self.assertGreaterEqual(
            fixture["timing_seconds"]["cloud_open_to_idle_report"], 60
        )
        self.assertLess(
            fixture["timing_seconds"]["cloud_open_to_idle_report"], 65
        )
        for run in fixture["additional_zone_runs"]:
            with self.subTest(zone=run["zone"]):
                active = decode_htv405_control_frame(
                    bytes.fromhex(run["active_report"]["frame"])
                )
                idle = decode_htv405_control_frame(
                    bytes.fromhex(run["idle_report"]["frame"])
                )
                self.assertEqual(run["zone"], active["zone"])
                self.assertTrue(active["is_watering"])
                self.assertEqual(60, active["duration_seconds"])
                self.assertFalse(idle["is_watering"])
                self.assertGreaterEqual(
                    run["cloud_open_to_idle_report_seconds"], 60
                )
                self.assertLess(
                    run["cloud_open_to_idle_report_seconds"], 65
                )

    def test_stock_htv405_early_stop_reuses_session_sequence(self) -> None:
        fixture = json.loads(
            (
                ROOT
                / "research"
                / "fixtures"
                / "htv405_stock_early_stop_20260824.json"
            ).read_text(encoding="utf-8")
        )
        for run in fixture["runs"]:
            with self.subTest(zone=run["zone"]):
                active = decode_htv405_control_frame(
                    bytes.fromhex(run["active_report"]["frame"])
                )
                idle = decode_htv405_control_frame(
                    bytes.fromhex(run["idle_report"]["frame"])
                )
                self.assertEqual(run["zone"], active["zone"])
                self.assertTrue(active["is_watering"])
                self.assertFalse(idle["is_watering"])
                self.assertGreaterEqual(
                    run["timing_seconds"]["cloud_close_to_idle_report"], 5
                )
                self.assertLess(
                    run["timing_seconds"]["cloud_close_to_idle_report"], 8
                )
                if run["open_command"] is None:
                    continue
                opened = normalize_row(
                    {
                        "len": 304,
                        "data": run["open_command"]["frame"],
                    }
                )
                closed = normalize_row(
                    {
                        "len": 304,
                        "data": run["close_command"]["frame"],
                    }
                )
                self.assertTrue(opened["trailer_valid"])
                self.assertTrue(closed["trailer_valid"])
                self.assertEqual(opened["message_type"], closed["message_type"])
                self.assertEqual(
                    run["open_command"]["sequence"],
                    opened["message_type"] & 0x1F,
                )
                self.assertEqual(0x10, bytes.fromhex(opened["frame_hex"])[14])
                self.assertEqual(0x90, bytes.fromhex(closed["frame_hex"])[14])

        advanced_open, stable_close = fixture[
            "authenticated_counter_examples"
        ]
        opened_response = decode_htv405_gateway_command_response(
            bytes.fromhex(advanced_open["open_response"]["frame"])
        )
        self.assertIsNotNone(opened_response)
        self.assertTrue(opened_response["rf_control_response_watering"])
        self.assertEqual(
            advanced_open["open_command"]["sequence"] + 1,
            advanced_open["close_command"]["sequence"],
        )

        closed_response = decode_htv405_gateway_command_response(
            bytes.fromhex(stable_close["close_response"]["frame"])
        )
        self.assertIsNotNone(closed_response)
        self.assertFalse(closed_response["rf_control_response_watering"])
        self.assertEqual(
            stable_close["close_command"]["sequence"],
            stable_close["next_open_command"]["sequence"],
        )

    def test_builds_offline_htv405_close_candidates_from_session_inputs(self) -> None:
        link = ValveLink(
            controller_endpoint=bytes.fromhex("aa110280"),
            valve_endpoint=bytes.fromhex("a1b2c313"),
        )
        frame = build_htv405_close_frame(
            link,
            sequence=0x0A,
            zone=1,
            selector=0x05,
            repeat=True,
            residue=0xC713,
        )
        self.assertEqual(
            "79f4882f28aa110280a1b2c3130a8107820580804f8000000040"
            "800056800000000000002077",
            frame.hex(),
        )
        for zone in range(1, 5):
            candidate = build_htv405_close_frame(
                link,
                sequence=0x0A,
                zone=zone,
                selector=0x05,
                repeat=False,
                residue=0x4F03,
            )
            decoded = decode_htv405_control_frame(candidate)
            self.assertFalse(decoded["is_watering"])
            self.assertEqual(0 if zone == 1 else zone, decoded["zone"])
        self.assertEqual(
            4,
            len(
                htv405_close_candidates(
                    link, sequence=0x0A, zone=1, selector=0x05
                )
            ),
        )
        with self.assertRaisesRegex(ValueError, "zone"):
            build_htv405_close_frame(
                link,
                sequence=0x0A,
                zone=5,
                selector=0x05,
                repeat=False,
                residue=0xC713,
            )

    def test_derives_next_htv405_sequence_phase_from_latest_report(self) -> None:
        primary = bytes.fromhex(
            "79f4882f28aa110280a1b2c313080107820701004f8000000040"
            "80005680000000000000a102"
        )
        # Phase extraction is independent of the trailer, so use a captured
        # structurally valid body through the ordinary-link recognizer.
        primary = bytearray(primary)
        primary[-2:] = (
            binascii.crc_hqx(primary[:-2], 0) ^ 0xC713
        ).to_bytes(2, "big")
        self.assertEqual((0x08, True), next_htv405_phase(bytes(primary)))
        primary[14] |= 0x80
        primary[-2:] = (
            binascii.crc_hqx(primary[:-2], 0) ^ 0x4F03
        ).to_bytes(2, "big")
        self.assertEqual((0x09, False), next_htv405_phase(bytes(primary)))

    def test_retained_htv405_link_report_backfills_registry_on_upgrade(self) -> None:
        frame = (
            "79f4882f28aa110280a1b2c313028107820701804f8000000040"
            "80005680000000000000837d"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(path))
            gateway.observe_rf_frame(
                frame=frame,
                state={
                    "rf_endpoint_a": "aa110280",
                    "rf_endpoint_b": "a1b2c313",
                    "rf_frame_accepted": True,
                    "rf_trailer_valid": True,
                },
            )
            self.assertIsNone(
                gateway.catalog.valve_link("aa110280", "a1b2c313")
            )
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(path))
            self.assertIsNotNone(
                restored.catalog.valve_link("aa110280", "a1b2c313")
            )
            valve = next(
                item
                for item in restored.devices()
                if item["device_id"] == "htv405-a1b2c313"
            )
            self.assertFalse(valve["available"])
            restored.close()

    def test_decodes_packed_valve_last_usage(self) -> None:
        cases = (
            # Historical short sessions independently reported by HA.
            ("8500", "00", 1.0),
            ("8480", "00", 0.9),
            ("8e00", "00", 2.8),
            ("d300", "00", 16.6),
            ("b300", "00", 10.2),
            # Today's 17-minute run: 175.2 L = 46.2829435731476 gal.
            ("ec03", "00", 175.2),
            # Bit 7 of the following byte restores value bit 7 of the first
            # packed byte. These two were independently decoded by the cloud.
            ("d181", "80", 93.1),
            ("9981", "80", 81.9),
        )
        for packed, extension, liters in cases:
            with self.subTest(packed=packed):
                captured = bytes.fromhex(
                    "79f4882f28b9840280b42d008f810107858700904f"
                    + packed
                    + extension
                    + "0040858056fe0180000000002739"
                )
                payload = captured[:-2]
                trailer = binascii.crc_hqx(payload, 0) ^ 0x4F03
                frame = payload + trailer.to_bytes(2, "big")
                decoded = normalize_row(
                    {"len": len(frame) * 8, "data": frame.hex()}
                )
                self.assertEqual(liters, decoded["last_usage_liters"])

    def test_cloud_correlated_htv145_battery_and_usage_fixture(self) -> None:
        fixture = json.loads(
            (
                ROOT
                / "research"
                / "fixtures"
                / "htv145_cloud_rf_battery_usage_correlation_20260824.json"
            ).read_text(encoding="utf-8")
        )
        for observation in fixture["observations"]:
            with self.subTest(event_id=observation["rf_event_id"]):
                decoded = normalize_row(
                    {
                        "len": len(observation["rf_frame"]) * 4,
                        "data": observation["rf_frame"],
                    }
                )
                expected = observation["expected"]
                self.assertEqual(
                    expected["last_usage_liters"],
                    decoded["last_usage_liters"],
                )
                self.assertEqual(
                    expected["battery_percent"], decoded["battery_percent"]
                )
                self.assertEqual(
                    expected["battery_status"], decoded["battery_status"]
                )
                self.assertTrue(decoded["trailer_valid"])

    def test_htv405_unknown_battery_and_usage_remain_unavailable(self) -> None:
        """Dynamic HTV405 bytes must not become invented user fields."""
        fixture = json.loads(
            (
                ROOT
                / "research"
                / "fixtures"
                / "htv405_battery_transition_20260823.json"
            ).read_text(encoding="utf-8")
        )
        for label, sample in fixture["diagnostic_examples"].items():
            with self.subTest(label=label):
                decoded = normalize_row(
                    {
                        "len": len(sample["frame"]) * 4,
                        "data": sample["frame"],
                    }
                )
                for field in (
                    "battery_low",
                    "battery_status",
                    "battery_percent",
                    "last_usage_liters",
                ):
                    self.assertNotIn(field, decoded)

        active_report = (
            "79f4882f28b984028094a9801309810786058090cf8000000040"
            "b90056bc0000000000004d64"
        )
        catalog = DeviceCatalog(
            valves=(
                ValveDefinition(
                    "b9840280",
                    "94a98013",
                    "test-four-zone",
                    "Test Four Zone",
                    model="HTV405FRF",
                ),
            )
        )
        gateway = Gateway(transport="rtl433", catalog=catalog)
        transport = RTL433Transport(
            gateway, command=["unused"], catalog=catalog
        )
        transport.seed()
        event = {"rows": [{"len": len(active_report) * 4, "data": active_report}]}
        self.assertEqual(1, transport.consume_line(json.dumps(event)))
        valve = next(
            device
            for device in gateway.devices()
            if device["model"] == "HTV405FRF"
        )
        self.assertIsNone(valve["state"]["battery_low"])
        self.assertIsNone(valve["state"]["battery_status"])
        self.assertIsNone(valve["state"]["battery_percent"])
        self.assertIsNone(valve["state"]["last_usage_liters"])
        gateway.close()

    def test_live_transport_publishes_confirmed_moisture(self) -> None:
        gateway = Gateway(transport="rtl433")
        transport = RTL433Transport(gateway, command=["unused"])
        transport.seed()
        before = next(
            device
            for device in gateway.devices()
            if device["device_id"] == "soil-right-bed"
        )
        self.assertFalse(before["available"])

        frame = "79f4882f28b42d008f9ce5802419048307018005c41b00000000000000000000000000007bd6"
        event = {
            "time": "2026-08-06T11:35:33.325850",
            "rows": [{"len": len(frame) * 4, "data": frame}],
            "rssi": -1.99,
        }
        self.assertEqual(1, transport.consume_line(json.dumps(event)))
        device = next(
            device
            for device in gateway.devices()
            if device["device_id"] == "soil-right-bed"
        )
        self.assertTrue(device["available"])
        self.assertEqual("soil-right-bed", device["device_id"])
        self.assertEqual(54, device["state"]["soil_moisture_percent"])
        self.assertEqual("9ce58024", device["state"]["rf_endpoint"])
        self.assertEqual(100.0, device["rf_frame_success_percent"])

    def test_invalid_moisture_is_retained_without_updating_state(self) -> None:
        gateway = Gateway(transport="rtl433")
        transport = RTL433Transport(gateway, command=["unused"])
        transport.seed()
        valid = "79f4882f28b9840280d1e280241e8182078544268000000000000000000000000000000077e7"
        corrupted = "79f4882f28b9840280d1e2802417018207854407000000000000000000000000000000000000"
        transport.consume_line(
            json.dumps(
                {
                    "time": "2026-08-09T18:25:27",
                    "rows": [{"len": len(valid) * 4, "data": valid}],
                }
            )
        )
        transport.consume_line(
            json.dumps(
                {
                    "time": "2026-08-09T18:26:27",
                    "rows": [
                        {"len": len(corrupted) * 4, "data": corrupted}
                    ],
                }
            )
        )

        device = next(
            item
            for item in gateway.devices()
            if item["device_id"] == "soil-front-2"
        )
        self.assertEqual(77, device["state"]["soil_moisture_percent"])
        self.assertEqual("2026-08-09T18:25:27", device["observed_at"])
        self.assertEqual(50.0, device["rf_frame_success_percent"])
        self.assertEqual(1, device["valid_rf_frame_count"])
        self.assertEqual(1, device["invalid_rf_frame_count"])
        self.assertEqual("rf_frame", gateway.events()[-1]["event_type"])
        self.assertFalse(gateway.events()[-1]["state"]["rf_frame_accepted"])

    def test_valid_routine_valve_frame_advances_report_time_only(self) -> None:
        gateway = Gateway(transport="rtl433")
        transport = RTL433Transport(gateway, command=["unused"])
        transport.seed()
        frame_bytes = bytearray.fromhex(
            "79f4882f28b42d008fb98402808845010001000000000000"
            "000000000000000000000000324c"
        )
        frame_bytes[5:9], frame_bytes[9:13] = (
            frame_bytes[9:13],
            frame_bytes[5:9],
        )
        trailer = binascii.crc_hqx(frame_bytes[:-2], 0) ^ 0x4F03
        frame_bytes[-2:] = trailer.to_bytes(2, "big")
        frame = frame_bytes.hex()
        timestamp = "2026-08-09T18:28:35"
        transport.consume_line(
            json.dumps(
                {
                    "time": timestamp,
                    "rows": [{"len": len(frame) * 4, "data": frame}],
                }
            )
        )

        valve = next(
            item for item in gateway.devices() if item["device_id"] == "valve-1"
        )
        self.assertTrue(valve["available"])
        self.assertEqual(timestamp, valve["observed_at"])
        self.assertIsNone(valve["state"]["valve_state"])
        self.assertEqual(100.0, valve["rf_frame_success_percent"])

    def test_live_transport_canonicalizes_product_code_report(self) -> None:
        gateway = Gateway(transport="rtl433")
        transport = RTL433Transport(gateway, command=["unused"])
        transport.seed()
        frame = (
            "79f4882f28b9840280d1e280482c03040f0a884f"
            "000000000000000000000000000000001b77"
        )
        event = {
            "time": "2026-08-07T10:36:56.394439",
            "rows": [{"len": len(frame) * 4, "data": frame}],
            "rssi": -1.596,
        }
        self.assertEqual(1, transport.consume_line(json.dumps(event)))
        device = next(
            device
            for device in gateway.devices()
            if device["device_id"] == "soil-front-2"
        )
        self.assertEqual(79, device["state"]["soil_moisture_percent"])
        self.assertEqual("d1e28024", device["state"]["rf_endpoint"])
        self.assertEqual("d1e28048", device["state"]["rf_endpoint_b"])
        self.assertEqual(72, device["state"]["rf_product_code"])
        self.assertEqual("HCS026FRF", device["model"])
        self.assertEqual(
            "trusted_metadata", device["state"]["product_model_source"]
        )
        self.assertEqual(
            ["soil_moisture", "battery", "signal_strength"],
            device["state"]["product_family_capabilities"],
        )
        self.assertEqual(
            HCS02X_PROTOCOL, device["state"]["rf_protocol_family"]
        )

    def test_product_code_persists_functional_family_without_exact_model(
        self,
    ) -> None:
        ordinary = "79f4882f28b9840280d1e280241e8182078544268000000000000000000000000000000077e7"
        product = (
            "79f4882f28b9840280d1e280482c03040f0a884f"
            "000000000000000000000000000000001b77"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            storage = Path(temporary_directory) / "rainpoint.sqlite3"
            gateway = Gateway(transport="rtl433", storage_path=str(storage))
            transport = RTL433Transport(gateway, command=["unused"])
            transport.consume_line(
                json.dumps(
                    {"rows": [{"len": len(ordinary) * 4, "data": ordinary}]}
                )
            )
            registration = gateway.accept_endpoint(
                endpoint="d1e28024",
                name="Provisional Sensor",
                model=GENERIC_HCS02X_MODEL,
            )
            self.assertEqual(GENERIC_HCS02X_MODEL, registration["model"])
            self.assertEqual(HCS02X_PROTOCOL, registration["protocol"])

            transport.consume_line(
                json.dumps(
                    {"rows": [{"len": len(product) * 4, "data": product}]}
                )
            )
            identified = gateway.registry()[0]
            self.assertEqual(GENERIC_HCS02X_MODEL, identified["model"])
            self.assertEqual(
                "rf_product_code_family", identified["model_source"]
            )
            self.assertEqual(0x48, identified["product_code"])
            reaccepted = gateway.accept_endpoint(
                endpoint="d1e28024",
                name="Still Confirmed",
                model=GENERIC_HCS02X_MODEL,
            )
            self.assertEqual(GENERIC_HCS02X_MODEL, reaccepted["model"])
            self.assertEqual(
                "rf_product_code_family", reaccepted["model_source"]
            )
            self.assertEqual(0x48, reaccepted["product_code"])
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(storage))
            device = next(
                item
                for item in restored.devices()
                if item["device_id"] == "soil-front-2"
            )
            self.assertEqual(GENERIC_HCS02X_MODEL, device["model"])
            self.assertFalse(device["state"]["product_model_exact"])
            self.assertIn("forget", device["capabilities"])

            restored.confirm_product_identity(
                endpoint="d1e28024",
                identity=hcs02x_identity(
                    {"product_code": 0x48, "model_code": 0x013D}
                ),
            )
            exact = restored.registry()[0]
            self.assertEqual("HCS026FRF", exact["model"])
            self.assertEqual(
                "rf_product_and_model_codes", exact["model_source"]
            )
            restored.close()

    def test_live_transport_merges_valve_duration_and_usage(self) -> None:
        gateway = Gateway(transport="rtl433")
        transport = RTL433Transport(gateway, command=["unused"])
        transport.seed()
        open_frame = (
            "79f4882f28b42d008fb9840280811082808100fe0180"
            "00000000000000000000000000007669"
        )
        usage_frame = (
            "79f4882f28b9840280b42d008f810107858700904f"
            "ec03000040858056fe018000000000853c"
        )
        for frame in (open_frame, usage_frame):
            event = {"rows": [{"len": len(frame) * 4, "data": frame}]}
            self.assertEqual(1, transport.consume_line(json.dumps(event)))

        valve = next(
            device for device in gateway.devices() if device["device_id"] == "valve-1"
        )
        self.assertFalse(valve["state"]["is_watering"])
        self.assertEqual("idle", valve["state"]["valve_state"])
        self.assertEqual(1020, valve["state"]["duration_seconds"])
        self.assertEqual(175.2, valve["state"]["last_usage_liters"])
        self.assertEqual(100, valve["state"]["battery_percent"])
        self.assertEqual(1, valve["state"]["battery_status"])
        self.assertFalse(valve["state"]["battery_low"])

    def test_controller_request_does_not_mutate_valve_device_state(self) -> None:
        gateway = Gateway(transport="rtl433")
        transport = RTL433Transport(gateway, command=["unused"])
        transport.seed()
        request = build_open_frame(
            self.CAPTURED_VALVE_LINK, 0x8D, 60, 0xC713
        )

        event = {
            "rows": [{"len": len(request) * 8, "data": request.hex()}]
        }
        self.assertEqual(1, transport.consume_line(json.dumps(event)))

        valve = next(
            device
            for device in gateway.devices()
            if device["device_id"] == "valve-1"
        )
        self.assertIsNone(valve["state"]["is_watering"])
        self.assertIsNone(valve["state"]["valve_state"])
        retained = gateway.events()
        self.assertEqual("rf_frame", retained[-1]["event_type"])
        self.assertNotIn("device_id", retained[-1])
        self.assertEqual("open", retained[-1]["state"]["valve_command"])

    def test_live_transport_terminal_summary_confirms_valve_closed(self) -> None:
        gateway = Gateway(transport="rtl433")
        transport = RTL433Transport(gateway, command=["unused"])
        transport.seed()
        open_frame = (
            "79f4882f28b42d008fb9840280811082808100fe0180"
            "0000000000000000000000000000007669"
        )
        terminal_summary = (
            "79f4882f28b9840280b42d008f9e8207858080ea62980d10"
            "908200002c01000000000000421f"
        )
        for frame in (open_frame, terminal_summary):
            event = {"rows": [{"len": len(frame) * 4, "data": frame}]}
            self.assertEqual(1, transport.consume_line(json.dumps(event)))

        valve = next(
            device
            for device in gateway.devices()
            if device["device_id"] == "valve-1"
        )
        self.assertFalse(valve["state"]["is_watering"])
        self.assertEqual("idle", valve["state"]["valve_state"])
        self.assertEqual(600, valve["state"]["duration_seconds"])
        self.assertEqual(105.7, valve["state"]["last_usage_liters"])

    def test_live_transport_publishes_confirmed_htv145_low_battery(self) -> None:
        gateway = Gateway(transport="rtl433")
        transport = RTL433Transport(gateway, command=["unused"])
        transport.seed()
        low_battery_usage = (
            "79f4882f28b9840280b42d008f970107858b00804f998180"
            "00408000568000000000000049ef"
        )
        event = {
            "rows": [
                {
                    "len": len(low_battery_usage) * 4,
                    "data": low_battery_usage,
                }
            ]
        }
        self.assertEqual(1, transport.consume_line(json.dumps(event)))

        valve = next(
            device
            for device in gateway.devices()
            if device["device_id"] == "valve-1"
        )
        self.assertEqual(10, valve["state"]["battery_percent"])
        self.assertEqual(2, valve["state"]["battery_status"])
        self.assertTrue(valve["state"]["battery_low"])
        self.assertEqual(81.9, valve["state"]["last_usage_liters"])

    def test_live_transport_retains_non_sensor_and_ignores_invalid_rows(self) -> None:
        gateway = Gateway(transport="rtl433")
        transport = RTL433Transport(gateway, command=["unused"])
        self.assertEqual(0, transport.consume_line("not json"))
        event = {
            "rows": [
                {
                    "len": 304,
                    "data": (
                        "79f4882f28b42d008fb98402809ec1010006000000000000"
                        "0000000000000000000000006bea"
                    ),
                }
            ]
        }
        self.assertEqual(1, transport.consume_line(json.dumps(event)))
        self.assertEqual([], gateway.devices())
        raw_event = gateway.events()[0]
        self.assertEqual("rf_frame", raw_event["event_type"])
        self.assertEqual("b42d008f", raw_event["state"]["rf_endpoint_a"])
        self.assertEqual("b9840280", raw_event["state"]["rf_endpoint_b"])
        self.assertEqual(0x9E, raw_event["state"]["rf_message_type"])
        self.assertIn("rf_trailer_residual", raw_event["state"])
        self.assertIn("rf_trailer_valid", raw_event["state"])

    def test_live_transport_retains_gateway_ack_as_raw_research_data(self) -> None:
        gateway = Gateway(transport="rtl433")
        transport = RTL433Transport(gateway, command=["unused"])
        frame = (
            "79f4882f28c4e500243984028088c181000100000000"
            "000000000000000000000000000022e3"
        )
        event = {"rows": [{"len": len(frame) * 4, "data": frame}]}
        self.assertEqual(1, transport.consume_line(json.dumps(event)))
        raw_event = gateway.events()[0]
        self.assertEqual("rf_frame", raw_event["event_type"])
        self.assertEqual("c4e50024", raw_event["state"]["routine_ack_endpoint"])
        self.assertEqual(8, raw_event["state"]["routine_ack_message"])
        self.assertEqual(1, raw_event["state"]["routine_ack_body_code"])
        self.assertTrue(raw_event["state"]["rf_trailer_valid"])
        self.assertEqual([], gateway.devices())

    def test_rtl_command_is_receive_only_and_filtered(self) -> None:
        command = rtl_433_command(434_000_000, 1_024_000)
        self.assertEqual("rtl_433", command[0])
        self.assertIn("match={40}79f4882f28", " ".join(command))
        self.assertNotIn("-S", command)

        capture_command = rtl_433_command(
            434_000_000,
            1_024_000,
            signal_capture_seconds=3600,
        )
        self.assertIn("-A", capture_command)
        self.assertEqual("all", capture_command[capture_command.index("-S") + 1])
        self.assertEqual("3600", capture_command[capture_command.index("-T") + 1])

    def test_raw_capture_requires_a_directory(self) -> None:
        with self.assertRaisesRegex(ValueError, "signal_directory"):
            RTL433Transport(
                Gateway(transport="rtl433"),
                signal_capture_seconds=60,
            )

    def test_esp32_serial_transport_publishes_the_same_device_state(self) -> None:
        gateway = Gateway(transport="esp32_serial")
        transport = ESP32SerialTransport(gateway, device="unused")
        transport.seed()
        frame = (
            "79f4882f28b42d008f9ce580240784830701800544200000"
            "000000000000000000000000308a"
        )
        message = {
            "type": "rainpoint_rf",
            "radio": "upper",
            "channel": 11,
            "rssi_dbm": -76.5,
            "lqi": 91,
            "frequency_offset_hz": -3175,
            "frame": frame,
        }

        self.assertEqual(1, transport.consume_line(json.dumps(message)))
        right_bed = next(
            device
            for device in gateway.devices()
            if device["device_id"] == "soil-right-bed"
        )
        self.assertEqual(64, right_bed["state"]["soil_moisture_percent"])
        self.assertEqual(-76.5, right_bed["state"]["rf_rssi_db"])
        self.assertEqual("upper", right_bed["state"]["rf_radio"])
        self.assertEqual(11, right_bed["state"]["rf_channel"])
        self.assertEqual(91, right_bed["state"]["rf_lqi"])
        self.assertEqual(-3175, right_bed["state"]["rf_frequency_offset_hz"])

    def test_esp32_serial_transport_rejects_non_frame_diagnostics(self) -> None:
        transport = ESP32SerialTransport(
            Gateway(transport="esp32_serial"), device="unused"
        )
        self.assertEqual(0, transport.consume_line(b"not json\n"))
        self.assertEqual(
            0,
            transport.consume_line(
                json.dumps({"type": "radio_ready", "channel": 0})
            ),
        )
        self.assertEqual(
            0,
            transport.consume_line(
                json.dumps({"type": "rainpoint_rf", "frame": "00" * 38})
            ),
        )

    def test_authenticated_probe_persists_separate_control_counter(self) -> None:
        node_id = "rp-001122334455"
        frame = (
            "79f4882f28b984028094a9801303d0868010cf8000000040bc"
            "0056bc000000000000000038bf"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            gateway = Gateway(
                transport="esp32_network",
                storage_path=str(Path(temporary_directory) / "rainpoint.sqlite3"),
            )
            gateway._store.upsert_valve_link(
                controller_endpoint="b9840280",
                valve_endpoint="94a98013",
                device_id="htv405-94a98013",
                name="Bench valve",
                model="HTV405FRF",
                area=None,
                accepted_at="2026-08-23T12:00:00+00:00",
            )
            gateway._store.update_valve_control_profile(
                valve_endpoint="94a98013",
                node_id=node_id,
                companion_endpoint="39840280",
                selector=0x05,
                frequency_offset_hz=97_154,
                observed_at="2026-08-23T12:00:01+00:00",
            )
            gateway._refresh_registry_catalog()
            gateway._ensure_registered_valve_devices()
            transport = ESP32SerialTransport(gateway, device="network")
            report = {
                "type": "valve_control_probe",
                "node_id": node_id,
                "state": "zone_1_open_confirmed",
                "configured": True,
                "controller_endpoint": "b9840280",
                "valve_endpoint": "94a98013",
                "companion_endpoint": "39840280",
                "selector": 0x05,
                "center_hz": 433_518_527,
                "command_phase_source": "authenticated_valve_response",
                "command_counter_valid": True,
                "confirmed_watering": True,
                "transmitted_zone": 1,
                "last_confirmed_sequence": 3,
                "next_sequence": 4,
                "open_age_ms": 2_000,
                "open_duration_seconds": 120,
                "frame": frame,
            }
            self.assertEqual(
                0,
                transport.consume_line(
                    json.dumps(report), authenticated_node_id=node_id
                ),
            )
            valve = next(
                device
                for device in gateway.devices()
                if device["device_id"] == "htv405-94a98013"
            )
            self.assertEqual(
                3, valve["state"]["rf_control_confirmed_sequence"]
            )
            self.assertEqual(4, valve["state"]["rf_next_control_sequence"])
            self.assertTrue(
                valve["state"]["rf_control_counter_authenticated"]
            )
            self.assertTrue(
                valve["state"]["rf_control_confirmed_watering"]
            )
            self.assertEqual(1, valve["state"]["rf_control_active_zone"])
            self.assertEqual(
                120,
                valve["state"]["rf_control_run_duration_seconds"],
            )
            self.assertIn(
                "rf_control_expected_idle_at", valve["state"]
            )

            rejected = dict(report, next_sequence=5)
            transport.consume_line(
                json.dumps(rejected), authenticated_node_id=node_id
            )
            unchanged = next(
                device
                for device in gateway.devices()
                if device["device_id"] == "htv405-94a98013"
            )
            self.assertEqual(4, unchanged["state"]["rf_next_control_sequence"])

            closed = dict(
                report,
                state="zone_1_closed_confirmed",
                confirmed_watering=False,
                last_confirmed_sequence=4,
                next_sequence=4,
                frame=(
                    "79f4882f28b984028094a9801304508683104f800000004080"
                    "00568000000000000000001e6e"
                ),
            )
            transport.consume_line(
                json.dumps(closed), authenticated_node_id=node_id
            )
            idle = next(
                device
                for device in gateway.devices()
                if device["device_id"] == "htv405-94a98013"
            )
            self.assertFalse(
                idle["state"]["rf_control_confirmed_watering"]
            )
            self.assertEqual(4, idle["state"]["rf_next_control_sequence"])
            self.assertNotIn("rf_control_active_zone", idle["state"])
            gateway.close()

    def test_esp32_serial_transport_reports_radio_health(self) -> None:
        gateway = Gateway(transport="esp32_serial")
        transport = ESP32SerialTransport(gateway, device="unused")

        transport.consume_line(
            json.dumps(
                {
                    "type": "radio_error",
                    "radio": "upper",
                    "error": "cc1101_not_found",
                }
            )
        )
        self.assertEqual("error", gateway.health()["status"])
        self.assertEqual(
            "upper: cc1101_not_found", gateway.health()["detail"]
        )

        transport.consume_line(
            json.dumps(
                {
                    "type": "radio_health",
                    "radio": "lower",
                    "channel": 0,
                    "configuration_valid": True,
                    "packets": 42,
                    "overflows": 1,
                    "recoveries": 43,
                }
            )
        )
        self.assertEqual(42, transport.radio_health["lower"]["packets"])
        self.assertEqual(1, transport.radio_health["lower"]["overflows"])

        transport.consume_line(
            json.dumps(
                {
                    "type": "radio_health",
                    "radio": "upper",
                    "configuration_valid": False,
                }
            )
        )
        self.assertEqual("error", gateway.health()["status"])
        self.assertIn("configuration_mismatch", gateway.health()["detail"])

        transport.consume_line(
            json.dumps({"type": "radio_ready", "radio": "upper"})
        )
        self.assertEqual("ok", gateway.health()["status"])


if __name__ == "__main__":
    unittest.main()
