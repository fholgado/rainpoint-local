#!/usr/bin/env python3
"""Check installable archives without extracting or printing sensitive contents.

This is a release hygiene check, not a substitute for publisher verification or
a comprehensive secret scanner. Public signing certificates are intentionally
permitted; private keys, local evidence and machine configuration are not.
"""
from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import zipfile

MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
PRIVATE_KEY = re.compile(
    rb"-----BEGIN ((?:[A-Z0-9]+ )*PRIVATE KEY)-----\s+"
    rb"[A-Za-z0-9+/=\r\n]{32,}-----END \1-----"
)
TOKEN = re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b")
PRIVATE_PARTS = {".git", ".env", ".ssh", ".storage", "captures", "__pycache__"}
PRIVATE_NAMES = {"secrets.yaml", "options.json", "wifi_secrets.h", "credentials.json"}
PRIVATE_SUFFIXES = {".sqlite", ".sqlite3", ".db", ".cu8", ".cs8", ".cf32", ".pcap", ".pcapng", ".pyc"}


def check_members(members) -> list[str]:
    """Inspect (name, size, regular-file, content-loader) archive members."""
    findings = []
    seen = set()
    total = 0
    for name, size, regular, read in members:
        path = PurePosixPath(name)
        # Diagnostics name the rule and path, never matched key/token contents.
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            findings.append(f"unsafe path: {name!r}")
        if name in seen:
            findings.append(f"duplicate member: {name!r}")
        seen.add(name)
        if not regular:
            findings.append(f"non-regular member: {name!r}")
            continue
        if (set(path.parts) & PRIVATE_PARTS or path.name in PRIVATE_NAMES
                or path.suffix.lower() in PRIVATE_SUFFIXES or path.name.startswith("._")):
            findings.append(f"private/generated file: {name!r}")
        total += size
        if not 0 <= size <= MAX_MEMBER_BYTES or total > MAX_ARCHIVE_BYTES:
            findings.append(f"size limit: {name!r}")
            continue
        body = read()
        if len(body) != size:
            findings.append(f"size mismatch: {name!r}")
        if PRIVATE_KEY.search(body):
            findings.append(f"private signing/SSH key: {name!r}")
        if TOKEN.search(body):
            findings.append(f"GitHub credential: {name!r}")
    if not seen:
        findings.append("empty archive")
    return findings


def check_artifact(path: Path) -> list[str]:
    """Check a source tarball or USB/OTA zip with bounded member reads."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            return check_members(
                (item.filename, item.file_size,
                 not item.is_dir() and stat.S_IFMT(item.external_attr >> 16) in (0, stat.S_IFREG),
                 lambda item=item: archive.read(item))
                for item in archive.infolist()
            )
    with tarfile.open(path) as archive:
        return check_members(
            (item.name, item.size, item.isfile(),
             lambda item=item: archive.extractfile(item).read(MAX_MEMBER_BYTES + 1))
            for item in archive
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args()
    failed = False
    for path in args.artifacts:
        try:
            findings = check_artifact(path)
        except (OSError, tarfile.TarError, zipfile.BadZipFile, RuntimeError):
            findings = ["unreadable or invalid archive"]
        print(f"{path.name}: {'FAIL' if findings else 'PASS'}")
        for finding in findings:
            print(f"  {finding}")
        failed |= bool(findings)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
