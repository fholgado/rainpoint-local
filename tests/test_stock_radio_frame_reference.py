"""Offline capture oracle for the stock CMT/native versus normalized boundary.

Research only: no runtime codecs, device access, or proprietary image needed.
See research/STOCK_HUB_RADIO_PATH_TRACE.md for the independent register evidence.
"""

import binascii
import json
from pathlib import Path
import random
import re
import unittest


FIXTURES = Path(__file__).resolve().parents[1] / "research" / "fixtures"
FRAME = re.compile(r"(?<![0-9a-f])79f4882f28[0-9a-f]{66}(?![0-9a-f])", re.I)


def recovered_payload_and_crc_prefix(normalized):
    """Return all 32 payload bytes and the 15 observed hardware CRC bits."""
    shifted = (int.from_bytes(normalized, "big") << 1).to_bytes(39, "big")[-38:]
    return shifted[4:36], int.from_bytes(shifted[36:], "big") >> 1


def normalize_hardware_payload(payload):
    checksum = binascii.crc_hqx(payload, 0xA8A8)
    wire = bytes.fromhex("f3e9105e") + payload + checksum.to_bytes(2, "big")
    return (int.from_bytes(wire, "big") >> 1).to_bytes(38, "big"), checksum


class StockRadioFrameReferenceTests(unittest.TestCase):
    def test_public_fixture_crc_prefixes_with_explicit_negative_controls(self):
        # One fixture intentionally contains a corrupted reception. Another is
        # an arbitrary-address transmitter calibration, not a stock-valid frame.
        corrupt = json.loads((FIXTURES / "htv145_stock_command_counter_20260824.json").read_text())
        corrupt_frame = next(
            frame["raw"]
            for transaction in corrupt["transactions"]
            for frame in transaction["frames"]
            if frame["role"] == "corrupted_response_candidate"
            and frame["accepted"] is False
        )
        bench = json.loads((FIXTURES / "htv145_hardware_clocked_configuration_calibration_20260904.json").read_text())
        negatives = {corrupt_frame.lower(), bench["fifo"]["frame_hex"].lower()}
        frames = {
            match.lower()
            for path in FIXTURES.glob("*.json")
            for match in FRAME.findall(path.read_text())
        }
        self.assertGreaterEqual(len(frames), 500)
        self.assertTrue(negatives <= frames)
        failed = set()
        for frame in frames:
            payload, observed = recovered_payload_and_crc_prefix(bytes.fromhex(frame))
            expected = binascii.crc_hqx(payload, 0xA8A8) >> 1
            if observed != expected:
                failed.add(frame)
        self.assertEqual(failed, negatives)

    def test_both_legacy_residues_follow_from_one_hardware_crc_seed(self):
        rng = random.Random(0)
        observed_cases = set()
        for _ in range(100):
            payload = bytes([0x51]) + bytes(rng.randrange(256) for _ in range(31))
            normalized, checksum = normalize_hardware_payload(payload)
            recovered, prefix = recovered_payload_and_crc_prefix(normalized)
            self.assertEqual(recovered, payload)
            self.assertEqual(prefix, checksum >> 1)
            self.assertEqual(normalized[:5], bytes.fromhex("79f4882f28"))
            legacy_residue = (
                binascii.crc_hqx(normalized[:36], 0)
                ^ int.from_bytes(normalized[36:], "big")
            )
            self.assertEqual(legacy_residue, 0xC713 if checksum & 1 else 0x4F03)
            observed_cases.add(checksum & 1)
        self.assertEqual(observed_cases, {0, 1})

    def test_legacy_residue_choice_can_change_last_payload_bit(self):
        payload = bytes([0x51]) + bytes(range(31))
        normalized, _ = normalize_hardware_payload(payload)
        data = normalized[:36]
        checksum = binascii.crc_hqx(data, 0)
        recovered_variants = []
        for residue in (0x4F03, 0xC713):
            candidate = data + (checksum ^ residue).to_bytes(2, "big")
            recovered, observed = recovered_payload_and_crc_prefix(candidate)
            self.assertEqual(observed, binascii.crc_hqx(recovered, 0xA8A8) >> 1)
            self.assertEqual(recovered[-1] & 1, candidate[36] >> 7)
            recovered_variants.append(recovered)
        self.assertEqual(recovered_variants[0][:-1], recovered_variants[1][:-1])
        self.assertEqual(recovered_variants[0][-1] ^ recovered_variants[1][-1], 1)
