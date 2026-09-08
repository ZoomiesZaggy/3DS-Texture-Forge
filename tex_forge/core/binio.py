"""Tiny, dependency-free binary helpers.

Everything in tex_forge that pokes at byte buffers should import from here.
Two reasons:

  1. Bounds-checked reads catch malformed ROMs early instead of returning garbage.
  2. The 0x200 NCCH "media unit" constant lives somewhere central.

These helpers are deliberately not a class -- they're cheap module-level functions
so the JIT can inline them and the call sites stay readable.
"""

from __future__ import annotations

import struct

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

#: NCCH/NCSD partition offsets are stored in *media units* of 512 bytes.
MEDIA_UNIT = 0x200


# ─────────────────────────────────────────────────────────────────────────────
# Bounds-checked scalar reads
# ─────────────────────────────────────────────────────────────────────────────

def read_u8(data: bytes, offset: int) -> int:
    if offset + 1 > len(data):
        raise ValueError(f"u8 read out of bounds: offset={offset}, len={len(data)}")
    return data[offset]


def read_u16_le(data: bytes, offset: int) -> int:
    if offset + 2 > len(data):
        raise ValueError(f"u16_le read out of bounds: offset={offset}, len={len(data)}")
    return struct.unpack_from("<H", data, offset)[0]


def read_u16_be(data: bytes, offset: int) -> int:
    if offset + 2 > len(data):
        raise ValueError(f"u16_be read out of bounds: offset={offset}, len={len(data)}")
    return struct.unpack_from(">H", data, offset)[0]


def read_u32_le(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise ValueError(f"u32_le read out of bounds: offset={offset}, len={len(data)}")
    return struct.unpack_from("<I", data, offset)[0]


def read_u32_be(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise ValueError(f"u32_be read out of bounds: offset={offset}, len={len(data)}")
    return struct.unpack_from(">I", data, offset)[0]


def read_u64_le(data: bytes, offset: int) -> int:
    if offset + 8 > len(data):
        raise ValueError(f"u64_le read out of bounds: offset={offset}, len={len(data)}")
    return struct.unpack_from("<Q", data, offset)[0]


def read_i32_le(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise ValueError(f"i32_le read out of bounds: offset={offset}, len={len(data)}")
    return struct.unpack_from("<i", data, offset)[0]


def read_cstring(data: bytes, offset: int, max_len: int = 256, encoding: str = "ascii") -> str:
    """Read a null-terminated string at *offset*, capped at *max_len* bytes."""
    end = offset
    limit = min(offset + max_len, len(data))
    while end < limit and data[end] != 0:
        end += 1
    return data[offset:end].decode(encoding, errors="replace")


def read_utf16le(data: bytes, offset: int, length_bytes: int) -> str:
    """Read a UTF-16LE string of exactly *length_bytes* bytes."""
    end = min(offset + length_bytes, len(data))
    return data[offset:end].decode("utf-16-le", errors="replace")


# ─────────────────────────────────────────────────────────────────────────────
# Tiny utilities
# ─────────────────────────────────────────────────────────────────────────────

def align_up(value: int, alignment: int) -> int:
    """Round *value* up to the next multiple of *alignment*."""
    if alignment <= 1:
        return value
    rem = value % alignment
    return value if rem == 0 else value + (alignment - rem)


def safe_slice(data: bytes, offset: int, size: int) -> bytes:
    """Slice with bounds checking; returns "" rather than raising on overflow.

    Use this when the *header* says the slice should be N bytes but the file
    might be truncated -- we'd rather return a short slice than crash. Use
    plain `data[offset:offset+size]` if you want raise-on-overflow behaviour.
    """
    if offset < 0 or size < 0:
        return b""
    if offset >= len(data):
        return b""
    end = min(offset + size, len(data))
    return data[offset:end]


def memcmp_at(data: bytes, offset: int, expected: bytes) -> bool:
    """Return True iff data[offset:offset+len(expected)] == expected, bounds-safe."""
    if offset + len(expected) > len(data):
        return False
    return data[offset:offset + len(expected)] == expected


# ─────────────────────────────────────────────────────────────────────────────
# Legacy alias kept for v1 parsers ported into textures.containers._v1_*
# ─────────────────────────────────────────────────────────────────────────────

read_string = read_cstring
