"""Shared binary reading helpers and utilities."""

import struct
import logging

logger = logging.getLogger(__name__)


def read_u8(data: bytes, offset: int) -> int:
    if offset + 1 > len(data):
        raise ValueError(f"Read u8 out of bounds: offset={offset}, len={len(data)}")
    return data[offset]


def read_u16_le(data: bytes, offset: int) -> int:
    if offset + 2 > len(data):
        raise ValueError(f"Read u16 out of bounds: offset={offset}, len={len(data)}")
    return struct.unpack_from('<H', data, offset)[0]


def read_u16_be(data: bytes, offset: int) -> int:
    if offset + 2 > len(data):
        raise ValueError(f"Read u16 out of bounds: offset={offset}, len={len(data)}")
    return struct.unpack_from('>H', data, offset)[0]


def read_u32_le(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise ValueError(f"Read u32 out of bounds: offset={offset}, len={len(data)}")
    return struct.unpack_from('<I', data, offset)[0]


def read_u32_be(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise ValueError(f"Read u32 out of bounds: offset={offset}, len={len(data)}")
    return struct.unpack_from('>I', data, offset)[0]


def read_u64_le(data: bytes, offset: int) -> int:
    if offset + 8 > len(data):
        raise ValueError(f"Read u64 out of bounds: offset={offset}, len={len(data)}")
    return struct.unpack_from('<Q', data, offset)[0]


def read_string(data: bytes, offset: int, max_len: int = 256) -> str:
    """Read a null-terminated string."""
    end = offset
    while end < min(offset + max_len, len(data)) and data[end] != 0:
        end += 1
    return data[offset:end].decode('ascii', errors='replace')


def align(value: int, alignment: int) -> int:
    """Align value up to the given alignment."""
    if alignment <= 0:
        return value
    remainder = value % alignment
    if remainder == 0:
        return value
    return value + (alignment - remainder)


def safe_slice(data: bytes, offset: int, size: int) -> bytes:
    """Safely slice data with bounds checking."""
    if offset < 0 or size < 0:
        raise ValueError(f"Invalid slice: offset={offset}, size={size}")
    if offset > len(data):
        raise ValueError(f"Slice offset {offset} beyond data length {len(data)}")
    end = min(offset + size, len(data))
    return data[offset:end]


MEDIA_UNIT = 0x200
