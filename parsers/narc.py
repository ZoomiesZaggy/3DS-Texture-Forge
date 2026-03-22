"""Nintendo NARC (Nitro ARChive) parser for 3DS/DS game archives."""

import struct
from typing import List, Tuple, Optional


def is_narc(data: bytes) -> bool:
    """Check if data is a NARC archive."""
    return len(data) >= 16 and data[:4] == b'NARC'


def parse_narc(data: bytes) -> List[Tuple[str, bytes]]:
    """Parse a NARC archive and return list of (name, file_data) tuples.

    NARC layout:
      Header (16 bytes): magic "NARC", BOM, version, file_size, header_size, chunk_count
      BTAF section: file allocation table with (start, end) offset pairs
      BTNF section: file name table (skipped — we use index-based names)
      GMIF section: file image data

    FATB offsets are relative to GMIF+8 (start of file data).
    """
    if not is_narc(data):
        return []

    # Determine endianness from BOM
    bom = struct.unpack_from('<H', data, 4)[0]
    le = (bom == 0xFFFE)
    fmt = '<' if le else '>'

    # BTAF section starts after 16-byte NARC header
    fatb_off = 0x10
    if fatb_off + 12 > len(data):
        return []
    if data[fatb_off:fatb_off + 4] != b'BTAF':
        return []

    fatb_size = struct.unpack_from(f'{fmt}I', data, fatb_off + 4)[0]
    file_count = struct.unpack_from(f'{fmt}I', data, fatb_off + 8)[0]

    if file_count == 0 or file_count > 100000:
        return []

    # Read file entry table (start, end pairs)
    entries = []
    for i in range(file_count):
        off = fatb_off + 12 + i * 8
        if off + 8 > len(data):
            break
        start, end = struct.unpack_from(f'{fmt}II', data, off)
        entries.append((start, end))

    # BTNF section follows BTAF
    fntb_off = fatb_off + fatb_size
    if fntb_off + 8 > len(data):
        return []
    if data[fntb_off:fntb_off + 4] != b'BTNF':
        return []
    fntb_size = struct.unpack_from(f'{fmt}I', data, fntb_off + 4)[0]

    # GMIF section follows BTNF
    fimg_off = fntb_off + fntb_size
    if fimg_off + 8 > len(data):
        return []
    if data[fimg_off:fimg_off + 4] != b'GMIF':
        return []

    data_start = fimg_off + 8  # Skip GMIF magic + section size

    result = []
    for i, (start, end) in enumerate(entries):
        abs_start = data_start + start
        abs_end = data_start + end
        if abs_start < len(data) and abs_end <= len(data) and abs_end > abs_start:
            result.append((f'{i:04d}', data[abs_start:abs_end]))

    return result
