"""Atlus STEX texture format parser.

Used by Radiant Historia: Perfect Chronology, Etrian Odyssey series,
and other Atlus 3DS games.

Header layout (0x80 bytes):
  +0x00: magic 'STEX' (4 bytes)
  +0x04: version/flags (u32)
  +0x08: unknown constant (u32)
  +0x0C: width (u32)
  +0x10: height (u32)
  +0x14: unknown (u32)
  +0x18: format code (u32) — DMP GL-like constant, mapped to PICA200
  +0x1C: data size (u32)
  +0x20: data offset (u32) — typically 0x80
  +0x28: filename string (null-terminated)
  +0x80: pixel data
"""

import struct
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

STEX_MAGIC = b'STEX'

# STEX format codes -> PICA200 format IDs
# Empirically determined from Radiant Historia data size analysis
STEX_FORMAT_MAP = {
    0x6750: 0x00,  # RGBA8
    0x6751: 0x01,  # RGB8
    0x6752: 0x00,  # RGBA8 (confirmed by decode test)
    0x6753: 0x03,  # RGB565
    0x6754: 0x01,  # RGB8 (confirmed 24bpp)
    0x6755: 0x05,  # LA8
    0x6756: 0x02,  # RGBA5551
    0x6757: 0x07,  # L8
    0x6758: 0x03,  # RGB565 (confirmed 16bpp) or RGBA4/LA8
    0x6759: 0x09,  # LA4
    0x675A: 0x0C,  # ETC1 (confirmed 4bpp)
    0x675B: 0x0D,  # ETC1A4 (confirmed 8bpp)
}


def is_stex(data: bytes) -> bool:
    """Check if data starts with STEX magic."""
    return len(data) >= 0x24 and data[:4] == STEX_MAGIC


def parse_stex(data: bytes) -> List[Dict[str, Any]]:
    """Parse an STEX texture file.

    Returns a list with one texture dict (STEX is single-texture),
    or empty list on failure.
    """
    if not is_stex(data):
        return []

    try:
        width = struct.unpack_from('<I', data, 0x0C)[0]
        height = struct.unpack_from('<I', data, 0x10)[0]
        fmt_code = struct.unpack_from('<I', data, 0x18)[0]
        data_size = struct.unpack_from('<I', data, 0x1C)[0]
        data_offset = struct.unpack_from('<I', data, 0x20)[0]
    except struct.error:
        return []

    if width == 0 or height == 0 or width > 4096 or height > 4096:
        return []
    if data_offset == 0 or data_offset >= len(data):
        return []
    if data_size == 0 or data_offset + data_size > len(data) + 1024:
        return []

    pica_fmt = STEX_FORMAT_MAP.get(fmt_code)
    if pica_fmt is None:
        # Try interpreting as direct PICA200 format ID
        if 0 <= fmt_code <= 0x0D:
            pica_fmt = fmt_code
        else:
            logger.debug(f"STEX: unknown format code 0x{fmt_code:04X}")
            return []

    # Extract filename if available
    name = ""
    if data_offset >= 0x30:
        try:
            name_bytes = data[0x28:data_offset]
            name = name_bytes.split(b'\x00')[0].decode('ascii', errors='replace')
        except Exception:
            pass

    pixel_data = data[data_offset:data_offset + data_size]

    return [{
        "width": width,
        "height": height,
        "format": pica_fmt,
        "data": pixel_data,
        "name": name or "stex_texture",
        "mip_count": 1,
    }]
