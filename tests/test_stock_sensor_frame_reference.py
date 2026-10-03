"""Public capture checks connecting native sensor frames to stock field grammar.

Research-only interpretation: no radio access or runtime codec changes.
"""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rainpointd_addon"))
from rainpoint_protocol import parse_tlv


def native_payload(frame_hex):
    frame = bytes.fromhex(frame_hex)
    if len(frame) != 38 or frame[:5] != bytes.fromhex("79f4882f28"):
        raise ValueError("expected normalized RainPoint frame")
    return bytes(((frame[i + 4] << 1) | (frame[i + 5] >> 7)) & 255
                 for i in range(32))


class StockSensorFrameReferenceTest(unittest.TestCase):
    def test_captured_moisture_is_native_compact_field_type_10(self):
        fixture = json.loads((ROOT / "research/fixtures/hcs026_pairing_battery.json").read_text())
        checked = 0
        for row in fixture["observations"]:
            if "soil_moisture_percent" not in row:
                continue
            with self.subTest(name=row["name"]):
                payload = native_payload(row["frame"])
                self.assertEqual(3, payload[10])
                self.assertEqual(4, payload[11] & 31)
                # These captured command-3 reports have two status bytes before
                # the compact fields. They are not themselves TLV headers.
                field, = parse_tlv("10#" + payload[14:16].hex())
                self.assertEqual(10, field["type_code"])
                self.assertEqual([row["soil_moisture_percent"]], field["value_bytes"])
                checked += 1
        self.assertEqual(5, checked)

    def test_stock_sensor_replies_echo_full_sequence_and_command_family(self):
        fixture = json.loads((ROOT / "research/fixtures/hcs026_gateway_pairing_replies.json").read_text())
        # Explicit stock transcripts, not later locally generated exchanges.
        names = {"sensor_a_first_enrollment", "sensor_b_first_enrollment"}
        checked = 0
        for row in fixture["sequences"]:
            if row["name"] not in names:
                continue
            pairs = zip(row["request_frames"], row["frames"], strict=True)
            for request_hex, reply_hex in pairs:
                request, reply = native_payload(request_hex), native_payload(reply_hex)
                with self.subTest(name=row["name"], sequence=request[9] & 63):
                    self.assertEqual(request[9] & 63, reply[9] & 63)
                    self.assertEqual(request[10] | 128, reply[10])
                    # An unpaired broadcast receives an assigned identity;
                    # require reversed route only after the factory exchange.
                    if request[10] != 1:
                        self.assertEqual(request[5:9], reply[1:5])
                        self.assertEqual(request[1:5], reply[5:9])
                checked += 1
        self.assertEqual(10, checked)
