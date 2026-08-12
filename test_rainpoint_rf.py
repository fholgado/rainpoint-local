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
from rainpointd.rf import normalize_row  # noqa: E402
from rainpointd.rtl433 import RTL433Transport, rtl_433_command  # noqa: E402
from rainpointd.valve_protocol import (  # noqa: E402
    build_close_frame,
    build_open_frame,
    close_candidates,
    decode_duration,
    encode_duration,
    next_sequence,
    open_candidates,
)
from tools.characterize_rainpoint_iq import characterize  # noqa: E402
from tools.compare_rainpoint_iq import compare_waveforms  # noqa: E402
from tools.demod_rainpoint_reply_iq import demodulate  # noqa: E402
from tools.generate_rainpoint_iq import (  # noqa: E402
    command_symbols,
    generate_command,
)


class RainPointRFTest(unittest.TestCase):
    @staticmethod
    def _frame_with_endpoint(frame_hex: str, endpoint: str) -> str:
        """Rewrite endpoint B and retain a supported trailer residue."""
        frame = bytearray.fromhex(frame_hex)
        frame[9:13] = bytes.fromhex(endpoint)
        trailer = binascii.crc_hqx(frame[:-2], 0) ^ 0xC713
        frame[-2:] = trailer.to_bytes(2, "big")
        return frame.hex()

    def test_product_identity_requires_catalogued_packet_evidence(self) -> None:
        provisional = hcs02x_identity({})
        self.assertEqual(GENERIC_HCS02X_MODEL, provisional.model)
        self.assertFalse(provisional.exact_model)

        by_product = hcs02x_identity({"product_code": 0x48})
        self.assertEqual("HCS026FRF", by_product.model)
        self.assertEqual("rf_product_code", by_product.source)

        by_model = hcs02x_identity({"model_code": 0x013D})
        self.assertEqual("HCS026FRF", by_model.model)
        self.assertEqual("rf_model_code", by_model.source)

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
            "79f4882f28b42d008fb98402808110828081009e0000"
            "000000000000000000000000000000003824"
        )
        valve_b_open[5:9] = bytes.fromhex("11223344")
        valve_b_open[9:13] = bytes.fromhex("55667788")
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
        open_frame = build_open_frame(0x97, 60, 0xC713)
        self.assertEqual(
            "79f4882f28b42d008fb98402809710828081009e000000000000000000000000000000003824",
            open_frame.hex(),
        )
        close_frame = build_close_frame(0x97, 0x4F03)
        self.assertEqual(
            "79f4882f28b42d008fb984028097908180810000000000000000000000000000000000006fcf",
            close_frame.hex(),
        )
        self.assertEqual(2, len(open_candidates(0x97, 60)))
        self.assertEqual(2, len(close_candidates(0x97)))
        self.assertEqual(0x80, next_sequence(0x9F))

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
        frame = build_open_frame(0x97, 60, 0xC713)
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
        frame = build_close_frame(0x97, 0x4F03)
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

    def test_retains_provisional_battery_status_from_companion_heartbeat(self) -> None:
        # Every one of 358 retained companion heartbeats used status 1 while
        # the stock battery entities independently remained normal/100%.
        frame = bytes.fromhex(
            "79f4882f28c4e500243984028088c181000100000000"
            "000000000000000000000000000022e3"
        )
        decoded = normalize_row({"len": len(frame) * 8, "data": frame.hex()})
        self.assertEqual("c4e50024", decoded["battery_endpoint"])
        self.assertEqual(1, decoded["battery_status_candidate"])
        self.assertEqual(100, decoded["battery_percent_candidate"])
        self.assertEqual("c713", decoded["trailer_residual"])
        self.assertTrue(decoded["trailer_valid"])

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
        # This valve response contains a marker-like byte sequence by chance.
        frame = bytes.fromhex(
            "79f4882f28b9840280b42d008f9d05040581800544"
            "1e7058000000000000000000000000007be3"
        )
        decoded = normalize_row({"len": len(frame) * 8, "data": frame.hex()})
        self.assertNotIn("soil_moisture_percent", decoded)

    def test_decodes_valve_duration_and_close_state(self) -> None:
        open_frame = bytes.fromhex(
            "79f4882f28b42d008fb9840280811082808100fe0180"
            "0000000000000000000000000000007669"
        )
        decoded = normalize_row(
            {"len": len(open_frame) * 8, "data": open_frame.hex()}
        )
        self.assertTrue(decoded["is_watering"])
        self.assertEqual("watering", decoded["valve_state"])
        self.assertEqual(1020, decoded["duration_seconds"])

        four_minute_frame = build_open_frame(0x9B, 240, 0x4F03)
        decoded = normalize_row(
            {"len": len(four_minute_frame) * 8, "data": four_minute_frame.hex()}
        )
        self.assertEqual(240, decoded["duration_seconds"])

        close_frame = bytes.fromhex(
            "79f4882f28b42d008fb9840280819081808100000000"
            "00000000000000000000000000000011a2"
        )
        decoded = normalize_row(
            {"len": len(close_frame) * 8, "data": close_frame.hex()}
        )
        self.assertFalse(decoded["is_watering"])
        self.assertEqual("idle", decoded["valve_state"])
        self.assertNotIn("duration_seconds", decoded)

    def test_decodes_packed_valve_last_usage(self) -> None:
        cases = (
            # Historical short sessions independently reported by HA.
            ("8500", 1.0),
            ("8480", 0.9),
            ("8e00", 2.8),
            ("d300", 16.6),
            ("b300", 10.2),
            # Today's 17-minute run: 175.2 L = 46.2829435731476 gal.
            ("ec03", 175.2),
        )
        for packed, liters in cases:
            with self.subTest(packed=packed):
                frame = bytes.fromhex(
                    "79f4882f28b9840280b42d008f810107858700904f"
                    + packed
                    + "000040858056fe0180000000002739"
                )
                decoded = normalize_row(
                    {"len": len(frame) * 8, "data": frame.hex()}
                )
                self.assertEqual(liters, decoded["last_usage_liters"])

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
        frame = "79f4882f28b42d008fb98402808845010001000000000000000000000000000000000000324c"
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
            "rf_product_code", device["state"]["product_model_source"]
        )
        self.assertEqual(
            HCS02X_PROTOCOL, device["state"]["rf_protocol_family"]
        )

    def test_product_code_promotes_provisional_sensor_model_persistently(
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
            promoted = gateway.registry()[0]
            self.assertEqual("HCS026FRF", promoted["model"])
            self.assertEqual("rf_product_code", promoted["model_source"])
            self.assertEqual(0x48, promoted["product_code"])
            reaccepted = gateway.accept_endpoint(
                endpoint="d1e28024",
                name="Still Confirmed",
                model=GENERIC_HCS02X_MODEL,
            )
            self.assertEqual("HCS026FRF", reaccepted["model"])
            self.assertEqual("rf_product_code", reaccepted["model_source"])
            self.assertEqual(0x48, reaccepted["product_code"])
            gateway.close()

            restored = Gateway(transport="rtl433", storage_path=str(storage))
            device = next(
                item
                for item in restored.devices()
                if item["device_id"] == "soil-front-2"
            )
            self.assertEqual("HCS026FRF", device["model"])
            self.assertTrue(device["state"]["product_model_exact"])
            self.assertIn("forget", device["capabilities"])
            restored.close()

    def test_live_transport_merges_valve_duration_and_usage(self) -> None:
        gateway = Gateway(transport="rtl433")
        transport = RTL433Transport(gateway, command=["unused"])
        transport.seed()
        open_frame = (
            "79f4882f28b42d008fb9840280811082808100fe0180"
            "0000000000000000000000000000007669"
        )
        usage_frame = (
            "79f4882f28b9840280b42d008f810107858700904f"
            "ec03000040858056fe0180000000002739"
        )
        for frame in (open_frame, usage_frame):
            event = {"rows": [{"len": len(frame) * 4, "data": frame}]}
            self.assertEqual(1, transport.consume_line(json.dumps(event)))

        valve = next(
            device for device in gateway.devices() if device["device_id"] == "valve-1"
        )
        self.assertTrue(valve["state"]["is_watering"])
        self.assertEqual(1020, valve["state"]["duration_seconds"])
        self.assertEqual(175.2, valve["state"]["last_usage_liters"])

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

    def test_live_transport_retains_battery_candidate_as_raw_research_data(self) -> None:
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
        self.assertEqual(1, raw_event["state"]["battery_status_candidate"])
        self.assertEqual(100, raw_event["state"]["battery_percent_candidate"])
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
