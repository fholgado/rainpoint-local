"""Read-only native views of public stock pairing captures; never a TX recipe.

Run ``python3 -m research.pairing_native_transcripts`` for per-row Markdown.
Endpoint identities and original raw packets are deliberately omitted from output.
The source fixtures remain authoritative for carrier, timing and wire bytes.
"""
from __future__ import annotations

import binascii
import argparse
from dataclasses import dataclass, field
import json
import math
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
    # Only for offline candidate correlation. Never print installation IDs.
    route: tuple[bytes, bytes] = field(default=(b"", b""), repr=False)

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
    return PacketShape(payload[10], payload[9] & 63, payload[12:12 + length],
                       (frame[5:9], frame[9:13]))


def valve_settings_fields(data: bytes) -> dict[str, int]:
    """Stock class-1F fourteen-byte layout; raw values, not qualified units.

    Caller must establish the model. Offsets exclude the native-85 result.
    Evidence: STOCK_HUB_CONFIGURATION_LIFECYCLE.md, stock function 42040510.
    """
    if len(data) != 14:
        raise ValueError("expected fourteen configuration bytes, excluding result")
    return {
        "work_time_raw": int.from_bytes(data[0:2], "little"),
        "mist_open_raw": int.from_bytes(data[2:4], "little"),
        "interval_raw": int.from_bytes(data[4:6], "little"),
        "soil_address": data[6],
        "humidity_threshold_raw": data[7] & 127,
        "rainday_flag": data[7] >> 7,
        "delay_raw": int.from_bytes(data[8:12], "little"),
        "cali_raw": data[12],
        "press_raw": data[13],
    }


def semantics(packet: PacketShape, request: PacketShape | None = None) -> str:
    """Bounded field labels, not universal product decoding or acceptance."""
    command, data = packet.command, packet.data
    if command == 1:
        return "connection announcement"
    if command == 0x81:
        return "assignment response; not a generic result-byte layout"
    if command == 2 and len(data) >= 3:
        flags = data[1]
        return (f"controller report; port={data[2]}; flags={flags:02x}; "
                f"requests version={bool(flags & 2)}, time={bool(flags & 4)}, "
                f"units={bool(flags & 128)}")
    if command in (3, 10):
        return "device report; model-specific fields"
    if command == 5 and len(data) == 2:
        return f"settings read; transport selector={data[0]}; port={data[1]}"
    if command == 6 and len(data) == 3:
        return (f"plan read; transport selector={data[0]}; "
                f"port={data[1]}; page={data[2]}")
    if command == 0x59 and data:
        if data == b"\0":
            return "parameter read; all parameters"
        return "parameter read; IDs=" + ",".join(f"{value:02x}" for value in data)
    if command == 0x20 and len(data) in (2, 3):
        text = f"configuration notification; version={data[0]}; kind={data[1]}"
        if len(data) == 3:
            label = "new receive selector" if data[1] == 4 else "extra value"
            text += f"; {label}={data[2]}"
        return text
    if command in (0x82, 0x83, 0x85, 0x86, 0xA0, 0xD9) and data:
        text = f"result={data[0]}"
        if command == 0x86:
            if data[0] == 1:
                text += "; more plan data (not generic failure)"
            elif data[0] == 0:
                text += "; empty/final plan page (not pairing completion)"
            return text
        if data[0] != 0:
            return text + "; interpret within command/model"
        if (command == 0x82 and request is not None and request.command == 2
                and len(request.data) >= 3 and request.data[1] & 2 and len(data) >= 2):
            text += f"; configuration version={data[1]}"
        elif command == 0x85:
            text += f"; stored settings bytes={len(data) - 1}"
            if len(data) == 15:
                settings = valve_settings_fields(data[1:])
                # Length alone cannot prove the model. Do not print soil IDs.
                soil_linked = bool(settings.pop("soil_address"))
                text += "; candidate class-1F layout (units unqualified): "
                text += ", ".join(f"{name}={value}" for name, value in settings.items())
                text += f", soil_linked={soil_linked}"
        elif command == 0xD9 and len(data) >= 2:
            text += f"; first parameter ID={data[1]:02x}; model-specific value"
        return text
    return "unqualified command/body shape"


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
                          "| Row | Device → gateway | Gateway → device | Interpretation |",
                          "| --- | --- | --- | --- |"])
        labels = []
        if row.device:
            labels.append(semantics(row.device))
        if row.gateway:
            labels.append(semantics(row.gateway, row.device))
        lines.append(f"| {row.row} | {row.device.describe() if row.device else '—'} | "
                     f"{row.gateway.describe() if row.gateway else '—'} | {'; '.join(labels)} |")
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class TraceEvent:
    time_s: float
    direction: str
    packet: PacketShape


def read_events(path: Path) -> tuple[TraceEvent, ...]:
    """Read an explicitly labelled local JSON array, never contact a radio."""
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("trace exceeds 16 MiB")
    records = json.loads(path.read_text())
    if not isinstance(records, list) or len(records) > 10000:
        raise ValueError("expected at most 10000 trace records")
    events = []
    for record in records:
        if not isinstance(record, dict) or set(record) != {"time_s", "direction", "frame"}:
            raise ValueError("trace requires time_s, direction and frame only")
        time_s = record["time_s"]
        if (type(time_s) not in (int, float) or time_s < 0 or time_s > 1e12 or not math.isfinite(time_s)
                or record["direction"] not in ("device", "gateway")
                or not isinstance(record["frame"], str)):
            raise ValueError("invalid trace time, direction or frame")
        events.append(TraceEvent(time_s, record["direction"], decode(record["frame"])))
    return tuple(events)


def _route_key(packet: PacketShape) -> tuple[bytes, bytes]:
    # Captured companion/paired aliases differ in this flag. This is only a
    # candidate grouping, not a runtime association/authentication decision.
    return tuple(bytes((part[0] & 127,)) + part[1:] if part else b""
                 for part in packet.route)


def analyze_events(events: tuple[TraceEvent, ...], *, window_s: float = 10.0) -> str:
    """Correlate candidates within an explicit analysis window; no TX policy."""
    if (type(window_s) not in (int, float) or window_s <= 0 or window_s > 1e12
            or not math.isfinite(window_s)):
        raise ValueError("analysis window must be positive and finite")
    pending = {}
    previous = {}
    lines = ["# Offline trace candidates", "",
             f"Analysis window: {window_s:g} seconds; not a discovered protocol timeout.",
             "Routes use captured high-bit aliases. Matching is not authentication or device acceptance.",
             "Missing means not observed in this capture/window, not proof of RF loss.",
             "Factory assignments are not automatically correlated across changed identities.", "",
             "| Time (s) | Sender | Command / phase | Fields | Observation |",
             "| --- | --- | --- | --- | --- |"]
    ordered = sorted(events, key=lambda event: event.time_s)
    for event in ordered:
        if (type(event.time_s) not in (int, float) or event.time_s < 0 or event.time_s > 1e12
                or not math.isfinite(event.time_s)):
            raise ValueError("invalid event timestamp")
        packet = event.packet
        route = _route_key(packet)
        # Reject synthetic/empty routes rather than matching every unknown sender.
        if event.direction not in ("device", "gateway") or any(len(part) != 4 for part in route):
            raise ValueError("event needs a labelled direction and decoded route")
        observation = "request observed"
        request = None
        if packet.command & 128:
            opposite = "gateway" if event.direction == "device" else "device"
            key = (opposite, route[::-1], packet.command & 127, packet.phase)
            candidate = pending.get(key)
            if candidate is not None and 0 <= event.time_s - candidate.time_s <= window_s:
                request = candidate.packet
                del pending[key]
                observation = f"matching response candidate; delta={event.time_s - candidate.time_s:.6f}s"
            else:
                observation = "unmatched response in capture/window"
        else:
            semantic_key = (event.direction, route, packet.command, packet.data)
            prior = previous.get(semantic_key)
            if prior is not None and event.time_s - prior.time_s <= window_s:
                variation = "same phase" if packet.phase == prior.packet.phase else "changed phase"
                observation = f"repeated request ({variation}); possible retry"
            previous[semantic_key] = event
            key = (event.direction, route, packet.command, packet.phase)
            if key in pending:
                observation += "; repeated phase is ambiguous, timing uses latest request"
            pending[key] = event
        lines.append(f"| {event.time_s:.6f} | {event.direction} | "
                     f"{packet.command:02x} / {packet.phase} | {semantics(packet, request)} | {observation} |")
    lines.extend(["", "## Requests with no matching response observed", ""])
    if not pending:
        lines.append("None within the selected candidate rules; this does not establish completed pairing.")
    for event in sorted(pending.values(), key=lambda event: event.time_s):
        lines.append(f"- {event.time_s:.6f}s {event.direction}: "
                     f"{event.packet.command:02x} phase {event.packet.phase}; {semantics(event.packet)}")
    lines.extend(["", "Terminal 59 request observed: " + str(any(
        event.direction == "device" and event.packet.command == 0x59 for event in ordered)),
        "This report does not declare enrollment or control success."])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, help="local labelled JSON capture events")
    parser.add_argument("--window-seconds", type=float, default=10.0,
                        help="candidate correlation window, not a protocol deadline")
    args = parser.parse_args()
    try:
        report = (analyze_events(read_events(args.events), window_s=args.window_seconds)
                  if args.events else markdown(exchanges()))
    except (OSError, ValueError, TypeError):
        parser.exit(2, "Invalid/unreadable capture; no packet contents printed.\n")
    print(report, end="")


if __name__ == "__main__":
    main()
