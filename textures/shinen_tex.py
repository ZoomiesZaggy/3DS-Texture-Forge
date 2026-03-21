"""Shin'en TEX CTR texture parser for Nano Assault and other Shin'en 3DS games.

TEX CTR format:
  Offset 0x00: "TEX CTR " magic (8 bytes)
  Offset 0x08: version/checksum (4 bytes, typically A2 B7 32 01)
  Offset 0x0C: width (u16 LE)
  Offset 0x0E: height (u16 LE)
  Offset 0x10: PICA200 format (u32 LE)
  Offset 0x14: reserved (4 bytes, zeros)
  Offset 0x18: data offset (u32 LE, typically 0x80)
  Offset 0x1C: additional mip levels (u32 LE)
  Offset 0x20-0x7F: padding
  Offset 0x80+: pixel data (PICA200 morton-tiled)

CMPR wrapper:
  Some TEX files are wrapped in Shin'en's CMPR container.
  CMPR = 4-byte magic + Nintendo LZ10 compressed stream.
  After decompression, the inner data is a standard TEX CTR file.
"""

import struct
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

SHINEN_TEX_MAGIC = b'TEX CTR '
SHINEN_CMPR_MAGIC = b'CMPR'


def is_shinen_tex(data: bytes) -> bool:
    """Check if data is a Shin'en TEX CTR texture file."""
    if len(data) >= 0x20 and data[:8] == SHINEN_TEX_MAGIC:
        return True
    # Also detect CMPR-wrapped TEX files
    if len(data) >= 16 and data[:4] == SHINEN_CMPR_MAGIC:
        # Check if first byte after CMPR looks like LZ10/LZ11 prefix
        if data[4] in (0x10, 0x11):
            return True
    return False


def _parse_tex_header(data: bytes) -> Optional[Dict[str, Any]]:
    """Parse a raw TEX CTR header. Returns None on failure."""
    if len(data) < 0x20 or data[:8] != SHINEN_TEX_MAGIC:
        return None

    width = struct.unpack_from('<H', data, 0x0C)[0]
    height = struct.unpack_from('<H', data, 0x0E)[0]
    pica_format = struct.unpack_from('<I', data, 0x10)[0] & 0xFF
    data_offset = struct.unpack_from('<I', data, 0x18)[0]
    mip_extra = struct.unpack_from('<I', data, 0x1C)[0]

    if width == 0 or height == 0 or width > 2048 or height > 2048:
        return None
    if pica_format > 0x0D:
        return None
    if data_offset == 0:
        data_offset = 0x80  # Default
    if data_offset > len(data):
        return None

    return {
        'width': width,
        'height': height,
        'format': pica_format,
        'data_offset': data_offset,
        'mip_count': mip_extra + 1,
        'data_size': len(data) - data_offset,
    }


def parse_shinen_tex(data: bytes) -> List[Dict[str, Any]]:
    """Parse a Shin'en TEX CTR file (with optional CMPR decompression).

    Returns list of texture dicts with: name, format, width, height,
    data_offset, data_size, mip_count, and 'data' (pixel bytes).
    """
    tex_data = data
    is_compressed = False

    # Handle CMPR wrapper
    if len(data) >= 8 and data[:4] == SHINEN_CMPR_MAGIC:
        from parsers.lz import decompress_lz
        decompressed = decompress_lz(data[4:])
        if decompressed is None:
            logger.debug("CMPR: LZ decompression failed")
            return []
        tex_data = decompressed
        is_compressed = True

    info = _parse_tex_header(tex_data)
    if info is None:
        return []

    offset = info['data_offset']
    size = info['data_size']
    if offset + size > len(tex_data):
        size = len(tex_data) - offset
    if size <= 0:
        return []

    pixel_data = tex_data[offset:offset + size]

    result = {
        'width': info['width'],
        'height': info['height'],
        'format': info['format'],
        'data_offset': offset,
        'data_size': size,
        'mip_count': info['mip_count'],
        'data': pixel_data,
        'name': '',
        'compressed': is_compressed,
    }

    return [result]
