"""Stock-derived compact-state grammar; not an RF-frame or device-mode decoder.

Independent evidence: retained 1.1.1040, bd_dp_protocal_get_dp_sta_size at
0x42027CC0. See research/STOCK_HUB_SENSOR_RECOVERY_TRACE.md. Synthetic vectors
contain no device identifiers or proprietary firmware bytes.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rainpointd_addon"))

from rainpoint_protocol import parse_tlv  # noqa: E402


class StockCompactFieldReferenceTest(unittest.TestCase):
    def test_every_inline_type_and_nibble(self) -> None:
        # The short form carries type 0..7 and a value 0..15 in one byte.
        for field_type in range(8):
            for value in range(16):
                with self.subTest(field_type=field_type, value=value):
                    entry, = parse_tlv(f"10#{field_type * 16 + value:02x}")
                    self.assertEqual(field_type, entry["type_code"])
                    self.assertEqual([value], entry["value_bytes"])
                    self.assertEqual(0, entry["offset"])

    def test_every_direct_type_and_payload_length(self) -> None:
        # Direct long-form types 8..38 use one header plus 1..4 payload bytes.
        for field_type in range(8, 39):
            for size in range(1, 5):
                header = 0x80 + 4 * (field_type - 8) + size - 1
                payload = bytes([0x80, 0x01, 0xFE, 0x7F][:size])
                with self.subTest(field_type=field_type, size=size):
                    entry, = parse_tlv("10#" + bytes([header]).hex() + payload.hex())
                    self.assertEqual(field_type, entry["type_code"])
                    self.assertEqual(list(payload), entry["value_bytes"])

    def test_every_extended_type_and_payload_length(self) -> None:
        # Escape 31 adds an extension byte: type = 39 + extension, not 31 + it.
        for extension in range(256):
            for size in range(1, 5):
                encoded = bytes([0xFC + size - 1, extension]) + bytes(range(size))
                with self.subTest(extension=extension, size=size):
                    entry, = parse_tlv("10#" + encoded.hex())
                    self.assertEqual(39 + extension, entry["type_code"])
                    self.assertEqual(list(range(size)), entry["value_bytes"])

    def test_mixed_stream_preserves_field_boundaries(self) -> None:
        entries = parse_tlv("10#21882ADC03E0B2FC0F12FF0001020304")
        self.assertEqual([0, 1, 3, 5, 7, 10], [row["offset"] for row in entries])
        self.assertEqual([2, 10, 31, 32, 54, 39],
                         [row["type_code"] for row in entries])
        self.assertEqual([[1], [42], [3], [178], [18], [1, 2, 3, 4]],
                         [row["value_bytes"] for row in entries])

    def test_all_long_headers_reject_missing_payload(self) -> None:
        # A safe local parser rejects truncation; this is not a claim that
        # the stock pointer-based helper itself performs a bounds check.
        for header in range(0x80, 0x100):
            prefix = bytes([header]) + (b"\x00" if header >= 0xFC else b"")
            size = (header & 3) + 1
            for available in range(size):
                with self.subTest(header=header, available=available):
                    with self.assertRaisesRegex(ValueError, "truncated TLV payload"):
                        parse_tlv("10#" + (prefix + bytes(available)).hex())
        for header in range(0xFC, 0x100):
            with self.subTest(missing_extension=header):
                with self.assertRaisesRegex(ValueError, "truncated extended TLV type"):
                    parse_tlv(f"10#{header:02x}")


if __name__ == "__main__":
    unittest.main()
