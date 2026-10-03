"""Cross-device pairing shapes from independent public stock captures."""
import binascii
import unittest

from research.pairing_native_transcripts import decode, exchanges, markdown
from tests.test_stock_valve_frame_reference import load_fixture


class PairingNativeTranscriptsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = exchanges()

    def profile(self, name):
        return [row for row in self.rows if row.profile == name]

    def test_complete_selected_corpus_and_distinct_exchange_directions(self):
        self.assertEqual(len(self.rows), 42)
        self.assertEqual(sum(row.device is not None for row in self.rows), 40)
        self.assertEqual(sum(row.gateway is not None for row in self.rows), 39)
        self.assertEqual(sum(row.device is not None and row.gateway is not None
                             for row in self.rows), 37)
        for row in self.rows:
            if row.device is not None and row.gateway is not None:
                with self.subTest(profile=row.profile, row=row.row):
                    self.assertEqual(row.gateway.command, row.device.command | 0x80)
                    self.assertEqual(row.gateway.phase, row.device.phase)

    def test_sensor_five_reply_capture_is_not_replaced_by_local_three_reply_profile(self):
        for profile in ("HCS026 sensor_a_first_enrollment", "HCS026 sensor_b_first_enrollment"):
            rows = self.profile(profile)
            self.assertEqual([r.device.command for r in rows], [1, 3, 3, 5, 3])
            self.assertEqual([r.device.length for r in rows], [7, 4, 4, 2, 4])
            self.assertEqual([r.gateway.length for r in rows], [16, 4, 2, 2, 2])
            self.assertEqual([r.device.phase for r in rows], [2, 3, 4, 5, 6])
            self.assertEqual(rows[3].gateway.data, bytes.fromhex("0001"))
        fixture = load_fixture("hcs026_gateway_pairing_replies.json")
        repeat = next(row for row in fixture["sequences"]
                      if row["name"] == "sensor_b_repeat_enrollment_20260811")
        self.assertEqual([decode(f).command for f in repeat["frames"]], [0x81, 0x83, 0x83])
        self.assertNotIn("request_frames", repeat)  # no invented missing counterpart

    def test_two_single_zone_profiles_share_bodies_not_phase_allocation(self):
        first, second = self.profile("HTV145 counter-2"), self.profile("HTV145 Aug-25")
        self.assertEqual([r.device.command if r.device else None for r in first],
                         [1, 2, None, 0xA0, 5, 6, 0x59])
        self.assertEqual([r.gateway.command if r.gateway else None for r in first],
                         [0x81, 0x82, 0x20, None, 0x85, 0x86, 0xD9])
        for rows, phases in ((first, [4, 5, None, 2, 6, 7, 8]),
                             (second, [1, 2, None, 3, 3, 4, 5])):
            self.assertEqual([r.device.phase if r.device else None for r in rows], phases)
            self.assertEqual(rows[0].device.length, 8)
            self.assertEqual(rows[0].gateway.length, 11)
            self.assertEqual(rows[1].device.length, 15)
            self.assertEqual(rows[2].gateway.data, bytes.fromhex("0200"))
            self.assertEqual(rows[2].gateway.phase, rows[3].device.phase)
            self.assertEqual(rows[3].device.data, b"\0")
            self.assertEqual(rows[5].gateway.data, b"\0")
            self.assertEqual(rows[6].gateway.data, bytes.fromhex("003200"))

    def test_four_zone_repeats_port_reads_not_eighteen_distinct_opcodes(self):
        rows = self.profile("HTV405 Aug-17")
        self.assertEqual([r.device.command for r in rows],
                         [1] + [2] * 5 + [5] * 4 + [6] * 4 + [0x59] * 4)
        self.assertEqual([r.device.phase for r in rows], list(range(1, 19)))
        self.assertIsNone(rows[4].gateway)
        self.assertEqual([r.device.data[2] for r in rows[1:6]], [1, 2, 3, 4, 4])
        for command, suffix in ((5, b""), (6, b"\0")):
            requests = [r.device.data for r in rows if r.device.command == command]
            self.assertEqual(requests, [bytes((12, port)) + suffix for port in range(1, 5)])
        self.assertEqual([r.device.data for r in rows if r.device.command == 0x59],
                         [bytes((value,)) for value in range(0x32, 0x36)])

    def test_shared_valve_parameter_bytes_do_not_generalize_sensor_reply(self):
        valves = [r for r in self.rows if r.profile.startswith("HTV") and r.device
                  and r.device.command == 5]
        self.assertEqual(len(valves), 6)
        self.assertEqual({r.gateway.data for r in valves},
                         {bytes.fromhex("0058020a001e000000000000000000")})
        sensors = [r for r in self.rows if r.profile.startswith("HCS") and r.device.command == 5]
        self.assertEqual({r.gateway.data for r in sensors}, {bytes.fromhex("0001")})

    def test_bad_integrity_short_frames_and_impossible_length_rejected(self):
        original = load_fixture("htv145_gateway_pairing_replies.json")["exchanges"][0]["request_frame"]
        invalid_crc = bytearray.fromhex(original)
        invalid_crc[20] ^= 1
        invalid_length = bytearray.fromhex(original)
        # Native P[11] is normalized N[15]<<1 | N[16]>>7: set length=31.
        invalid_length[15] = (invalid_length[15] & 0xF0) | 15
        invalid_length[16] |= 128
        invalid_length[36:] = (binascii.crc_hqx(invalid_length[:36], 0) ^ 0x4F03).to_bytes(2, "big")
        for value in ("", original[:-2], invalid_crc.hex(), invalid_length.hex()):
            with self.subTest(value=value[:10]):
                with self.assertRaises(ValueError):
                    decode(value)

    def test_report_omits_endpoint_identifiers_and_raw_frames(self):
        fixture = load_fixture("htv405_gateway_pairing_replies.json")
        report = markdown(self.rows)
        for field in ("factory_endpoint", "paired_endpoint", "companion_endpoint"):
            self.assertNotIn(fixture[field], report)
        self.assertNotIn("79f4882f28", report)
        self.assertIn("Directions follow the fixture", report)


if __name__ == "__main__":
    unittest.main()
