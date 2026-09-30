"""Offline normalized-envelope helpers; no device or transport access."""
import binascii
from dataclasses import dataclass
import sqlite3


@dataclass(frozen=True)
class PacketShape:
    command: int
    phase: int
    data: bytes
    route: tuple[bytes, bytes]


def decode(frame):
    raw = bytes.fromhex(frame)
    if (len(raw) != 38 or raw[:5] != bytes.fromhex("79f4882f28") or
            binascii.crc_hqx(raw[:36], 0) ^ int.from_bytes(raw[36:], "big") not in (0xc713, 0x4f03)):
        raise ValueError("invalid normalized envelope")
    native = bytes(((raw[i+4] << 1) | (raw[i+5] >> 7)) & 255 for i in range(32))
    length = native[11] & 31
    if native[0] != 0x51 or length > 20:
        raise ValueError("invalid native header")
    return PacketShape(native[10], native[9] & 63, native[12:12+length], (raw[5:9], raw[9:13]))


def alter(frame, *, command=None, phase=None, data=None):
    raw = bytearray.fromhex(frame)
    native = bytearray(((raw[i+4] << 1) | (raw[i+5] >> 7)) & 255 for i in range(32))
    if command is not None:
        native[10] = command
    if phase is not None:
        native[9] = (native[9] & 192) | phase
    if data is not None:
        native[11] = (native[11] & 224) | len(data)
        native[12:] = data + bytes(20-len(data))
    for i, value in enumerate(native):
        raw[i+4] = (raw[i+4] & 128) | (value >> 1)
        raw[i+5] = (raw[i+5] & 127) | ((value & 1) << 7)
    raw[-2:] = (binascii.crc_hqx(raw[:-2], 0) ^ 0xc713).to_bytes(2, "big")
    return raw.hex()


class FailCommit:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, *args):
        return self.connection.execute(*args)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.connection.rollback()
        raise sqlite3.OperationalError("simulated failed commit")
