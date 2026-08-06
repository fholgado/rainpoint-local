#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "rainpointd_addon"))

from rainpointd.gateway import Gateway  # noqa: E402
from rainpointd.rf import normalize_row  # noqa: E402
from rainpointd.rtl433 import RTL433Transport, rtl_433_command  # noqa: E402


class RainPointRFTest(unittest.TestCase):
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

    def test_does_not_treat_valve_payload_as_moisture(self) -> None:
        # This valve response contains a marker-like byte sequence by chance.
        frame = bytes.fromhex(
            "79f4882f28b9840280b42d008f9d05040581800544"
            "1e7058000000000000000000000000007be3"
        )
        decoded = normalize_row({"len": len(frame) * 8, "data": frame.hex()})
        self.assertNotIn("soil_moisture_percent", decoded)

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


if __name__ == "__main__":
    unittest.main()
