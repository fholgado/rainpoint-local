"""Execute the firmware responder against stock captures, without any RF I/O."""
import binascii
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from research.pairing_native_transcripts import decode

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = "58020a001e00" + "00" * 8  # Fixture settings, not runtime defaults.


def alter(frame, *, command=None, phase=None, data=None):
    """Synthetic mutation of a captured normalized envelope, preserving routes."""
    raw = bytearray.fromhex(frame)
    native = bytearray(((raw[i + 4] << 1) | (raw[i + 5] >> 7)) & 255 for i in range(32))
    if command is not None:
        native[10] = command
    if phase is not None:
        native[9] = (native[9] & 192) | phase
    if data is not None:
        native[11] = (native[11] & 224) | len(data)
        native[12:] = data + bytes(20 - len(data))
    # Bytes 4..35 and the top bit of byte36 carry this native window;
    # legacy checksum is independently reconstructed afterwards.
    for i, value in enumerate(native):
        raw[i + 4] = (raw[i + 4] & 128) | (value >> 1)
        raw[i + 5] = (raw[i + 5] & 127) | ((value & 1) << 7)
    raw[-2:] = (binascii.crc_hqx(raw[:-2], 0) ^ 0xC713).to_bytes(2, "big")
    return raw.hex()


class ValveConfigurationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("c++")
        if not compiler:
            raise unittest.SkipTest("native C++ compiler unavailable")
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.probe = str(Path(cls.directory.name) / "configuration-probe")
        subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-I" + str(ROOT / "firmware/rainpoint_bridge/include"),
            str(ROOT / "firmware/rainpoint_bridge/tests/valve_configuration_probe.cpp"),
            "-o", cls.probe], check=True, capture_output=True, text=True)
        fixture = json.loads((ROOT / "research/fixtures/htv213_stock_pairing_controls_20260928.json").read_text())
        cls.events = fixture["trials"][0]["events"]
        cls.frames = {decode(e["frame"]).command: e["frame"] for e in cls.events if e["direction"] == "device"}

    def reply(self, frame, *, model="213", selector=None, revision=2, settings=SETTINGS,
              empty=True, route_a=None, route_b=None, time="-", units="-"):
        raw = bytes.fromhex(frame)
        packet = decode(frame) if selector is None else None
        result = subprocess.run([self.probe, model,
            str(selector if selector is not None else packet.data[0]), str(revision),
            route_a or raw[5:9].hex(), route_b or raw[9:13].hex(), settings,
            "1" if empty else "0", frame, time, units], check=True, capture_output=True, text=True)
        parts = result.stdout.strip().split()
        return tuple(map(int, parts[:4])) + (bytes.fromhex(parts[4]) if len(parts) > 4 else b"",)

    def test_three_model_captured_requests_build_exact_reply_bodies(self):
        count = 0
        fixtures = [("145", "htv145_counter2_stock_enrollment_20260901.json"),
                    ("145", "htv145_gateway_pairing_replies.json"),
                    ("405", "htv405_gateway_pairing_replies.json")]
        pairs = []
        for model, name in fixtures:
            fixture = json.loads((ROOT / "research/fixtures" / name).read_text())
            for row in fixture["exchanges"]:
                if row.get("request_frame") and row.get("reply_frame"):
                    pairs.append((model, row["request_frame"], row["reply_frame"]))
        for a, b in zip(self.events, self.events[1:]):
            if a["direction"] == "device" and b["direction"] == "gateway":
                pairs.append(("213", a["frame"], b["frame"]))
        for model, request, response in pairs:
            packet, expected = decode(request), decode(response)
            if packet.command not in (2, 5, 6):
                continue
            revision = expected.data[1] if packet.command == 2 else 2
            port = packet.data[2 if packet.command == 2 else 1]
            with self.subTest(model=model, command=packet.command, port=port):
                self.assertEqual(self.reply(request, model=model, revision=revision),
                    (0, expected.command, expected.phase, port, expected.data))
            count += 1
        self.assertEqual(count, 24)

    def test_all_phases_retries_and_out_of_order_ports_are_stateless(self):
        for command in (2, 5, 6):
            original = self.frames[command]
            for phase in range(64):
                frame = alter(original, phase=phase)
                first = self.reply(frame)
                self.assertEqual(first[:3], (0, command | 128, phase))
                self.assertEqual(self.reply(frame), first)
        # Port 2 does not require port 1 or an 18-row transcript first.
        self.assertEqual(self.reply(self.frames[5])[3], 2)

    def test_retained_lifecycle_reports_use_saved_revision_and_requested_context(self):
        fixture = json.loads((ROOT / "research/fixtures/htv213_stock_lifecycle_20260928.json").read_text())
        count = 0
        for trial in fixture["trials"]:
            for a, b in zip(trial["events"], trial["events"][1:]):
                packet, expected = decode(a["frame"]), decode(b["frame"])
                if (a["direction"] != "device" or b["direction"] != "gateway"
                        or packet.command not in (2, 5, 6)):
                    continue
                flags = packet.data[1] if packet.command == 2 else 0
                offset = 1 + bool(flags & 2)
                time = expected.data[offset:offset + 5].hex() if flags & 4 else "-"
                offset += 5 if flags & 4 else 0
                units = expected.data[offset:offset + 2].hex() if flags & 128 else "-"
                port = packet.data[2 if packet.command == 2 else 1]
                with self.subTest(trial=trial["name"], phase=packet.phase):
                    self.assertEqual(self.reply(a["frame"], revision=2, time=time, units=units),
                        (0, expected.command, expected.phase, port, expected.data))
                count += 1
        self.assertEqual(count, 20)

    def test_report_flags_determine_revision_time_and_units_not_pairing_step(self):
        packet = decode(self.frames[2])
        for flags in (0, 1, 2, 4, 128, 134, 255):
            data = bytes((packet.data[0], flags)) + packet.data[2:]
            frame = alter(self.frames[2], data=data)
            expected = b"\0" + (b"\x09" if flags & 2 else b"")
            expected += bytes.fromhex("1122334455") if flags & 4 else b""
            expected += bytes.fromhex("6677") if flags & 128 else b""
            self.assertEqual(self.reply(frame, revision=9, time="1122334455", units="6677")[-1], expected)
            if flags & 132:
                self.assertNotEqual(self.reply(frame)[0], 0)

    def test_unknown_settings_plans_pages_and_other_models_fail_closed(self):
        self.assertNotEqual(self.reply(self.frames[5], settings="-")[0], 0)
        self.assertNotEqual(self.reply(self.frames[6], empty=False)[0], 0)
        self.assertNotEqual(self.reply(self.frames[6], model="145")[0], 0)  # Port 2.
        packet = decode(self.frames[6])
        self.assertNotEqual(self.reply(alter(self.frames[6], data=packet.data[:2] + b"\x01"))[0], 0)
        for command in (1, 0x20, 0x21, 0x82, 0x85, 0x86):
            self.assertNotEqual(self.reply(alter(self.frames[5], command=command))[0], 0)

    def test_wrong_association_selector_integrity_and_lengths_fail_closed(self):
        for command, original in self.frames.items():
            if command not in (2, 5, 6):
                continue
            for kwargs in ({"route_a": "01020304"}, {"route_b": "01020304"},
                           {"route_a": "00000000"}, {"revision": 0}, {"selector": 12}):
                with self.subTest(command=command, kwargs=kwargs):
                    self.assertNotEqual(self.reply(original, **kwargs)[0], 0)
            packet = decode(original)
            for size in range(21):
                if size == len(packet.data):
                    continue
                frame = alter(original, data=(packet.data + bytes(20))[:size])
                self.assertNotEqual(self.reply(frame, selector=11)[0], 0)
            damaged = original[:-2] + ("00" if original[-2:] != "00" else "01")
            self.assertNotEqual(self.reply(damaged, selector=11)[0], 0)


if __name__ == "__main__":
    unittest.main()
