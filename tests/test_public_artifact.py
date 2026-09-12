from __future__ import annotations

import io
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile

from tools.check_public_artifact import check_artifact, check_members, MAX_MEMBER_BYTES


class PublicArtifactTest(unittest.TestCase):
    def test_permits_public_key_and_firmware_in_real_archives(self):
        with tempfile.TemporaryDirectory() as directory:
            for suffix in (".zip", ".tar.gz"):
                path = Path(directory) / ("release" + suffix)
                body = b"-----BEGIN PUBLIC KEY-----\npublic\n-----END PUBLIC KEY-----"
                if suffix == ".zip":
                    with zipfile.ZipFile(path, "w") as archive:
                        archive.writestr("release.pem", body)
                        archive.writestr("usb/firmware.bin", b"\x00\xff")
                else:
                    with tarfile.open(path, "w:gz") as archive:
                        member = tarfile.TarInfo("release.pem")
                        member.size = len(body)
                        archive.addfile(member, io.BytesIO(body))
                self.assertEqual([], check_artifact(path))

    def test_rejects_private_files_and_unsafe_names(self):
        for name in ("captures/a.jsonl", "secrets.yaml", "data.sqlite3", "raw.cu8",
                     "../escape", "/absolute", "._file", ".env", "folder\\escape"):
            with self.subTest(name=name):
                self.assertTrue(check_members([(name, 0, True, lambda: b"")]))

    def test_never_prints_secret_matches(self):
        for body in (b"-----BEGIN EC PRIVATE KEY-----\n" + b"A" * 64 + b"\n-----END EC PRIVATE KEY-----",
                     b"ghp_" + b"A" * 36):
            findings = check_members([("config.txt", len(body), True, lambda: body)])
            self.assertTrue(findings)
            self.assertNotIn(body.decode(), repr(findings))

    def test_crypto_library_pem_delimiter_is_not_a_private_key(self):
        body = b"\x00-----BEGIN EC PRIVATE KEY-----\x00"
        self.assertEqual([], check_members([("firmware.bin", len(body), True, lambda: body)]))

    def test_rejects_duplicates_links_and_oversize_without_reading(self):
        def forbidden_read():
            self.fail("unsafe member must not be read")
        self.assertTrue(check_members([("link", 0, False, forbidden_read)]))
        self.assertTrue(check_members([("huge", MAX_MEMBER_BYTES + 1, True, forbidden_read)]))
        self.assertTrue(check_members([("a", 0, True, lambda: b"")] * 2))
        self.assertTrue(check_members([]))


if __name__ == "__main__":
    unittest.main()
