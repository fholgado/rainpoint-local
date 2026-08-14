"""Strict local firmware release catalog and artifact integrity boundary."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CATALOG_SCHEMA_VERSION = 1
RELEASE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,95}\Z")
VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+-]{0,47}\Z")
PROFILE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAXIMUM_ARTIFACT_BYTES = 2 * 1024 * 1024
MINIMUM_ARTIFACT_BYTES = 64 * 1024


@dataclass(frozen=True)
class FirmwareRelease:
    """One immutable locally staged firmware release."""

    release_id: str
    version: str
    channel: str
    hardware_profile: str
    firmware_variant: str
    required_capability: str
    artifact_path: Path
    size_bytes: int
    sha256: str
    release_summary: str
    release_notes: str
    release_url: str | None

    def public(self, *, artifact_ready: bool) -> dict[str, Any]:
        """Return metadata that is safe to expose through the local API."""
        return {
            "release_id": self.release_id,
            "version": self.version,
            "channel": self.channel,
            "hardware_profile": self.hardware_profile,
            "firmware_variant": self.firmware_variant,
            "required_capability": self.required_capability,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "release_summary": self.release_summary,
            "release_notes": self.release_notes,
            "release_url": self.release_url,
            "artifact_ready": artifact_ready,
        }


class FirmwareCatalog:
    """Load a bounded catalog and verify every artifact before use."""

    def __init__(self, releases: list[FirmwareRelease] | None = None) -> None:
        self._releases = {
            release.release_id: release for release in (releases or [])
        }

    @classmethod
    def load(cls, catalog_path: str | Path | None) -> FirmwareCatalog:
        """Load a local catalog; an omitted path intentionally disables OTA UI."""
        if not catalog_path:
            return cls()
        path = Path(catalog_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("unsupported firmware catalog schema")
        raw_releases = payload.get("releases")
        if not isinstance(raw_releases, list) or len(raw_releases) > 32:
            raise ValueError("firmware catalog releases must be a bounded list")
        releases = [cls._parse_release(item, path.parent) for item in raw_releases]
        if len({item.release_id for item in releases}) != len(releases):
            raise ValueError("firmware catalog release IDs must be unique")
        return cls(releases)

    @staticmethod
    def _parse_release(raw: Any, root: Path) -> FirmwareRelease:
        if not isinstance(raw, dict):
            raise ValueError("firmware release must be an object")
        release_id = str(raw.get("release_id", ""))
        version = str(raw.get("version", ""))
        channel = str(raw.get("channel", ""))
        hardware_profile = str(raw.get("hardware_profile", ""))
        firmware_variant = str(raw.get("firmware_variant", ""))
        required_capability = str(raw.get("required_capability", ""))
        filename = str(raw.get("artifact", ""))
        sha256 = str(raw.get("sha256", "")).lower()
        try:
            size_bytes = int(raw.get("size_bytes", 0))
        except (TypeError, ValueError) as error:
            raise ValueError("invalid firmware artifact size") from error
        if (
            not RELEASE_ID.fullmatch(release_id)
            or not VERSION.fullmatch(version)
            or not PROFILE.fullmatch(channel)
            or not PROFILE.fullmatch(hardware_profile)
            or not PROFILE.fullmatch(firmware_variant)
            or not PROFILE.fullmatch(required_capability)
            or not filename
            or Path(filename).name != filename
            or not SHA256.fullmatch(sha256)
            or not MINIMUM_ARTIFACT_BYTES <= size_bytes <= MAXIMUM_ARTIFACT_BYTES
        ):
            raise ValueError("invalid firmware release metadata")
        summary = str(raw.get("release_summary", ""))
        notes = str(raw.get("release_notes", summary))
        release_url = raw.get("release_url")
        if len(summary) > 255 or len(notes) > 16_384:
            raise ValueError("firmware release notes exceed limits")
        if release_url is not None and (
            not isinstance(release_url, str)
            or not release_url.startswith("https://")
            or len(release_url) > 512
        ):
            raise ValueError("invalid firmware release URL")
        return FirmwareRelease(
            release_id=release_id,
            version=version,
            channel=channel,
            hardware_profile=hardware_profile,
            firmware_variant=firmware_variant,
            required_capability=required_capability,
            artifact_path=root / filename,
            size_bytes=size_bytes,
            sha256=sha256,
            release_summary=summary,
            release_notes=notes,
            release_url=release_url,
        )

    @property
    def enabled(self) -> bool:
        return bool(self._releases)

    def releases(self) -> list[dict[str, Any]]:
        """Return sorted public release metadata."""
        return [
            release.public(artifact_ready=self.artifact_ready(release.release_id))
            for release in sorted(
                self._releases.values(), key=lambda item: item.release_id
            )
        ]

    def get(self, release_id: str) -> FirmwareRelease:
        try:
            return self._releases[release_id]
        except KeyError as error:
            raise ValueError("unknown firmware release") from error

    def artifact_ready(self, release_id: str) -> bool:
        try:
            self.verified_artifact(release_id)
        except (OSError, ValueError):
            return False
        return True

    def verified_artifact(self, release_id: str) -> Path:
        """Return an artifact only after exact size and digest verification."""
        self.verified_artifact_content(release_id)
        return self.get(release_id).artifact_path

    def verified_artifact_content(self, release_id: str) -> bytes:
        """Read and return the exact bytes whose catalog digest was verified."""
        release = self.get(release_id)
        try:
            content = release.artifact_path.read_bytes()
        except OSError as error:
            raise ValueError("firmware artifact is not staged") from error
        if len(content) != release.size_bytes:
            raise ValueError("firmware artifact size mismatch")
        if hashlib.sha256(content).hexdigest() != release.sha256:
            raise ValueError("firmware artifact digest mismatch")
        return content

    def latest_for_node(self, node: dict[str, Any]) -> dict[str, Any] | None:
        """Return the newest ready release compatible with a node contract."""
        capabilities = set(node.get("capabilities", []))
        hardware_profile = str(
            node.get("hardware_profile")
            or (
                "esp32dev-cc1101-v1"
                if "firmware_update_trial" in capabilities
                else ""
            )
        )
        channel = str(
            node.get("firmware_channel")
            or (
                "experimental"
                if "firmware_update_trial" in capabilities
                else "stable"
            )
        )
        firmware_variant = str(
            node.get("firmware_variant")
            or (
                "pairing-ota"
                if "firmware_update_trial" in capabilities
                else "base"
            )
        )
        candidates = [
            release
            for release in self._releases.values()
            if release.required_capability in capabilities
            and release.hardware_profile == hardware_profile
            and release.firmware_variant == firmware_variant
            and release.channel == channel
            and self.artifact_ready(release.release_id)
        ]
        if not candidates:
            return None
        release = max(candidates, key=lambda item: _version_key(item.version))
        result = release.public(artifact_ready=True)
        result["installed_version"] = node.get("firmware_version")
        result["update_available"] = (
            isinstance(node.get("firmware_version"), str)
            and _version_key(release.version)
            > _version_key(str(node["firmware_version"]))
        )
        return result

    def compatible(self, release_id: str, node: dict[str, Any]) -> bool:
        latest = self.latest_for_node(node)
        return latest is not None and latest["release_id"] == release_id


def _version_key(version: str) -> tuple[tuple[int, ...], tuple[Any, ...]]:
    """Compare the project's numeric versions and test suffixes deterministically."""
    main, separator, suffix = version.partition("-")
    numbers = tuple(int(item) if item.isdigit() else -1 for item in main.split("."))
    if not separator:
        return numbers, ((2, ""),)
    suffix_key: list[tuple[int, Any]] = []
    for item in re.split(r"[.-]", suffix):
        suffix_key.append((1, int(item)) if item.isdigit() else (0, item))
    return numbers, tuple(suffix_key)
