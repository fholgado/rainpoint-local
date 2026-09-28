"""Read-only native views of public stock pairing captures; never a TX recipe.

Run ``python3 -m research.pairing_native_transcripts`` for per-row Markdown.
Endpoint identities and original raw packets are deliberately omitted from output.
The source fixtures remain authoritative for carrier, timing and wire bytes.
"""
from __future__ import annotations

import binascii
from dataclasses import dataclass
import json
from pathlib import Path


FIXTURES = Path(__file__).resolve().parent / "fixtures"
SENSOR_FIXTURE = "hcs026_gateway_pairing_replies.json"
VALVE_FIXTURES = (
    ("HTV145 counter-2", "htv145_counter2_stock_enrollment_20260901.json"),
    ("HTV145 Aug-25", "htv145_gateway_pairing_replies.json"),
    ("HTV405 Aug-17", "htv405_gateway_pairing_replies.json"),
)


@dataclass(frozen=True)
class PacketShape:
    command: int
    phase: int
    data: bytes

    @property
    def length(self) -> int:
        return len(self.data)

    def describe(self) -> str:
        return (f"`{self.command:02x}` / {self.phase} / {self.length} / "
                f"`{self.data.hex(' ') or '-'}`")


@dataclass(frozen=True)
class Exchange:
    profile: str
    source: str
    row: str
    device: PacketShape | None
    gateway: PacketShape | None


def decode(frame_hex: str) -> PacketShape:
    """Validate the legacy window, then extract native fields, without encoding.

    The legacy trailer omits one physical CRC bit. Its two accepted residues
    validate this captured representation, not an independently complete RF CRC.
    """
    frame = bytes.fromhex(frame_hex)
    if len(frame) != 38 or frame[:5] != bytes.fromhex("79f4882f28"):
        raise ValueError("expected normalized 38-byte RainPoint frame")
    residue = binascii.crc_hqx(frame[:36], 0) ^ int.from_bytes(frame[36:], "big")
    if residue not in (0xC713, 0x4F03):
        raise ValueError("invalid normalized integrity residue")
    payload = bytes(((frame[i + 4] << 1) | (frame[i + 5] >> 7)) & 255
                    for i in range(32))
    length = payload[11] & 31
    if payload[0] != 0x51 or length > 20:
        raise ValueError("invalid native header or declared data length")
    return PacketShape(payload[10], payload[9] & 63, payload[12:12 + length])


def exchanges() -> tuple[Exchange, ...]:
    result = []
    sensor = json.loads((FIXTURES / SENSOR_FIXTURE).read_text())
    # These explicitly stock-labelled captures have both sides of all rows.
    # Later three-reply profiles have no request array; do not fabricate one.
    for sequence in sensor["sequences"]:
        if sequence["name"] not in ("sensor_a_first_enrollment", "sensor_b_first_enrollment"):
            continue
        for index, (request, response) in enumerate(zip(
            sequence["request_frames"], sequence["frames"], strict=True
        )):
            result.append(Exchange("HCS026 " + sequence["name"], SENSOR_FIXTURE,
                                   str(index), decode(request), decode(response)))
    for profile, source in VALVE_FIXTURES:
        fixture = json.loads((FIXTURES / source).read_text())
        for index, row in enumerate(fixture["exchanges"]):
            result.append(Exchange(
                profile, source, str(row.get("stage", row.get("step", index))),
                decode(row["request_frame"]) if row.get("request_frame") else None,
                decode(row["reply_frame"]) if row.get("reply_frame") else None,
            ))
    return tuple(result)


def markdown(rows: tuple[Exchange, ...]) -> str:
    lines = ["# Captured native pairing rows", "",
             "Each cell is command / six-bit phase / declared data length / data.",
             "A dash means no frame in this fixture row, not a universal no-reply rule.",
             "Directions follow the fixture, not opcode polarity. No identities are printed.", ""]
    profile = None
    for row in rows:
        if row.profile != profile:
            profile = row.profile
            lines.extend(["", f"## {profile}", "", f"Source: `{row.source}`", "",
                          "| Row | Device → gateway | Gateway → device |",
                          "| --- | --- | --- |"])
        lines.append(f"| {row.row} | {row.device.describe() if row.device else '—'} | "
                     f"{row.gateway.describe() if row.gateway else '—'} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(markdown(exchanges()), end="")
