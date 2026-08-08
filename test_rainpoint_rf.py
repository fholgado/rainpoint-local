#!/usr/bin/env python3

from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "rainpointd_addon"))

from rainpointd.esp32 import ESP32SerialTransport  # noqa: E402
from rainpointd.gateway import Gateway  # noqa: E402
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


class RainPointRFTest(unittest.TestCase):
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

        data = (
            "aa" * 150
            + "bcfa4417945a168047ce72c01205c2418380c002a20f8"
            + "000000000000000000000000000010780"
        )
        event = {
            "time": "2026-08-06T11:35:33.325850",
            "rows": [{"len": 1508, "data": data}],
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
        self.assertEqual(62, device["state"]["soil_moisture_percent"])
        self.assertEqual("9ce58024", device["state"]["rf_endpoint"])

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
            json.dumps({"type": "radio_ready", "radio": "upper"})
        )
        self.assertEqual("ok", gateway.health()["status"])


if __name__ == "__main__":
    unittest.main()
