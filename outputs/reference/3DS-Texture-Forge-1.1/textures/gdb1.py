"""
GDB1 texture parser for Star Fox 64 3D.

Pairs:
  <basename>.texturegdb  — metadata (GDB1 header + node tree)
  <basename>.texturebin  — raw PICA200 pixel data

Node layout (12 nodes × 16 bytes, starting at offset 0x48):
  +0  uint32  type/tag
  +4  uint32  unknown
  +8  uint32  hash/key
  +12 uint32  value   ← the one we care about

Node indices:
  0 = Width       1 = Height
  2 = GDB1Format  5 = PixOffset   6 = PixSize

GDB1Format → approximate bpp:
  0x11 (17) = 4 bpp   0x12 (18) = 8 bpp
  (actual PICA200 fmt is determined by matching PixSize)
"""

import struct
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

_MAGIC = b"GDB1"


def is_gdb1(data: bytes) -> bool:
    return len(data) >= 8 and data[:4] == _MAGIC


def parse_gdb1_pair(
    texturegdb_data: bytes,
    texturebin_data: bytes,
    source_path: str = "",
) -> List[Dict[str, Any]]:
    """
    Parse a .texturegdb/.texturebin pair and return a list of texture dicts
    compatible with extract_textures_with_confidence() output.
    Returns [] on any parse failure.
    """
    if not is_gdb1(texturegdb_data):
        return []

    file_len = len(texturegdb_data)
    node_values: List[int] = []

    for i in range(12):
        off = 0x48 + i * 0x10
        if off + 16 > file_len:
            break
        val = struct.unpack_from("<I", texturegdb_data, off + 12)[0]
        node_values.append(val)

    if len(node_values) < 7:
        logger.debug("GDB1: not enough nodes in %s", source_path)
        return []

    width = node_values[0]
    height = node_values[1]
    pix_offset = node_values[5]
    pix_size = node_values[6]

    if width == 0 or height == 0 or pix_size == 0:
        logger.debug("GDB1: zero dims/size in %s", source_path)
        return []

    pixel_data = texturebin_data[pix_offset:pix_offset + pix_size]
    if len(pixel_data) != pix_size:
        logger.debug(
            "GDB1: pixel data truncated in %s (want %d, got %d)",
            source_path, pix_size, len(pixel_data),
        )
        return []

    # Find PICA200 format code by matching expected texture size
    from textures.decoder import calculate_texture_size
    matched_fmt = None
    for fmt in range(14):
        if calculate_texture_size(width, height, fmt) == pix_size:
            matched_fmt = fmt
            break

    if matched_fmt is None:
        logger.debug(
            "GDB1: no PICA200 format matches size=%d for %dx%d in %s",
            pix_size, width, height, source_path,
        )
        return []

    return [{
        "width": width,
        "height": height,
        "format": matched_fmt,
        "data": pixel_data,
        "mip_count": 1,
        "parser_used": "gdb1",
        "confidence": "medium",
    }]
