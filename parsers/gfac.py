"""Good-Feel Archive Container (GFAC) parser.

Used by Good-Feel games: Kirby's Extra Epic Yarn, Yoshi's Woolly World, etc.
Archives contain named entries, optionally compressed with GFCP (Good-Feel Compression).
"""

import struct
import logging
from typing import Iterator, Tuple

logger = logging.getLogger(__name__)


def is_gfac(data: bytes) -> bool:
    """Check if data starts with GFAC magic."""
    return len(data) >= 0x30 and data[:4] == b'GFAC'


def iter_gfac(data: bytes) -> Iterator[Tuple[str, bytes]]:
    """Iterate over entries in a GFAC archive, yielding (name, data) tuples.

    Handles GFCP-compressed entries by decompressing with LZ10/LZ11.
    """
    if not is_gfac(data):
        return

    entry_count = struct.unpack_from('<I', data, 0x2C)[0]
    if entry_count == 0 or entry_count > 10000:
        return

    for i in range(entry_count):
        e_off = 0x30 + i * 16
        if e_off + 16 > len(data):
            break

        name_off_flags = struct.unpack_from('<I', data, e_off + 4)[0]
        decomp_size = struct.unpack_from('<I', data, e_off + 8)[0]
        data_off = struct.unpack_from('<I', data, e_off + 12)[0]

        compressed = bool(name_off_flags & 0x80000000)
        name_off = name_off_flags & 0x7FFFFFFF

        # Read null-terminated name
        name = ""
        if name_off < len(data):
            end = data.find(b'\x00', name_off, name_off + 128)
            if end < 0:
                end = name_off + 32
            name = data[name_off:end].decode('ascii', errors='replace')

        if data_off >= len(data):
            continue

        if compressed:
            entry_data = _decompress_gfcp(data, data_off, decomp_size)
        else:
            # Uncompressed: calculate size from gap to next entry or end
            next_off = len(data)
            if i + 1 < entry_count:
                next_off = struct.unpack_from('<I', data, e_off + 16 + 12)[0]
            raw_size = min(decomp_size, next_off - data_off, len(data) - data_off)
            entry_data = data[data_off:data_off + raw_size]

        if entry_data and len(entry_data) >= 4:
            yield (name, entry_data)


def _decompress_gfcp(data: bytes, offset: int, expected_size: int) -> bytes:
    """Decompress a GFCP (Good-Feel Compression) block.

    GFCP header (20 bytes):
      +0x00: "GFCP" magic
      +0x04: version (u32)
      +0x08: compression type (u32) — 3 = LZ
      +0x0C: decompressed size (u32)
      +0x10: compressed size (u32)
    Followed by raw LZ-compressed data (no Nintendo LZ header).
    """
    if offset + 0x14 >= len(data):
        return b''
    if data[offset:offset + 4] != b'GFCP':
        # Not GFCP compressed — try reading raw
        return data[offset:offset + expected_size]

    decomp_size = struct.unpack_from('<I', data, offset + 0x0C)[0]
    comp_size = struct.unpack_from('<I', data, offset + 0x10)[0]

    if decomp_size == 0:
        return b''

    payload_start = offset + 0x14
    payload_end = min(payload_start + comp_size, len(data))
    payload = data[payload_start:payload_end]

    if not payload:
        return b''

    from parsers.lz import decompress_lz

    # Build fake Nintendo LZ header — use extended 8-byte header for sizes > 16MB
    for type_byte in (0x10, 0x11):
        if decomp_size <= 0xFFFFFF:
            fake_header = bytes([type_byte]) + struct.pack('<I', decomp_size)[:3]
        else:
            fake_header = bytes([type_byte, 0x00, 0x00, 0x00]) + struct.pack('<I', decomp_size)
        try:
            result = decompress_lz(fake_header + payload)
            if result and len(result) > 0:
                return result
        except Exception:
            pass

    return b''
