"""Packaging boundaries; real firmware/build smoke runs separately in CI."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

from tools.package_alpha import collect_firmware, OFFSETS, write_archive


class AlphaPackageTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.build = Path(self.temporary.name)
        app = b"\xe9" + b"\0" * 100 + b"0.17.0\0" + b"\0" * 65536
        def partition(kind, subtype, offset, size):
            return struct.pack("<HBBII16sI", 0x50AA, kind, subtype, offset, size, b"test", 0)
        table = (partition(1, 0, 0xE000, 0x2000)
                 + partition(0, 0x10, 0x10000, 0x140000)
                 + partition(0, 0x11, 0x150000, 0x140000))
        self.images = {"bootloader.bin": b"\xe9" + b"b" * 512,
                       "partitions.bin": table, "boot_app0.bin": b"i" * 8192,
                       "firmware.bin": app}
        self.receipt = {"schema_version": 1, "source_commit": "a" * 40,
            "source_dirty": False, "version": "0.17.0", "variant": "unified",
            "board": "esp32dev", "environment": "rainpoint_bridge", "parts": []}
        for name, body in self.images.items():
            (self.build / name).write_bytes(body)
            self.receipt["parts"].append({"path": name, "offset": OFFSETS[name],
                "size_bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
        self.save()

    def save(self):
        (self.build / "release-input.json").write_text(json.dumps(self.receipt))

    def collect(self, **kwargs):
        return collect_firmware(self.build, revision="a" * 40, version="0.17.0", **kwargs)

    def test_valid_images_preserve_actual_upload_layout_and_contents(self):
        receipt, files = self.collect()
        self.assertEqual(self.images, files)
        self.assertEqual(self.receipt, receipt)

    def test_stale_version_revision_variant_and_dirty_source_rejected(self):
        for field, value in (("version", "0.16.1"), ("source_commit", "b" * 40),
                             ("variant", "research"), ("board", "esp32c3"),
                             ("source_dirty", True), ("source_dirty", None)):
            with self.subTest(field=field):
                old = self.receipt[field]
                self.receipt[field] = value
                self.save()
                with self.assertRaises(ValueError):
                    self.collect()
                self.receipt[field] = old
        self.save()

    def test_explicit_dirty_preview_keeps_dirty_marker(self):
        self.receipt["source_dirty"] = True
        self.save()
        receipt, _ = self.collect(allow_dirty=True)
        self.assertIs(True, receipt["source_dirty"])

    def test_changed_image_missing_file_unsafe_name_and_wrong_offset_rejected(self):
        for mode in ("modified", "missing", "path", "offset", "duplicate"):
            with self.subTest(mode=mode):
                original = json.loads(json.dumps(self.receipt))
                part = self.receipt["parts"][0]
                path = self.build / "bootloader.bin"
                if mode == "modified": path.write_bytes(b"bad image")
                if mode == "missing": path.unlink()
                if mode == "path": part["path"] = "../secret"
                if mode == "offset": part["offset"] = 0
                if mode == "duplicate": self.receipt["parts"][1] = part.copy()
                self.save()
                with self.assertRaises((ValueError, FileNotFoundError)):
                    self.collect()
                self.receipt = original
                path.write_bytes(self.images["bootloader.bin"])
                self.save()

    def test_actual_partition_layout_must_support_both_ota_slots(self):
        table = self.images["partitions.bin"][:64]  # Omit the second OTA slot.
        (self.build / "partitions.bin").write_bytes(table)
        part = next(p for p in self.receipt["parts"] if p["path"] == "partitions.bin")
        part.update(size_bytes=len(table), sha256=hashlib.sha256(table).hexdigest())
        self.save()
        with self.assertRaisesRegex(ValueError, "both OTA"):
            self.collect()

    def test_archive_is_deterministic_and_contains_only_explicit_files(self):
        first, second = self.build / "first.zip", self.build / "second.zip"
        write_archive(first, {"usb/firmware.bin": b"image", "LICENSE": b"license"})
        write_archive(second, {"LICENSE": b"license", "usb/firmware.bin": b"image"})
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with zipfile.ZipFile(first) as archive:
            self.assertEqual(["LICENSE", "usb/firmware.bin"], archive.namelist())


if __name__ == "__main__":
    unittest.main()
