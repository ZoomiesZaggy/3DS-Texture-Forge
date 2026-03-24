"""Bandai Namco jIMG texture parser for 3DS (One Piece: Unlimited World Red, etc.)

Header layout (128 bytes = 0x80):
  +0x00  magic      bytes[4]  "jIMG"
  +0x04  file_size  u32 LE    total file size
  +0x08  width      u16 LE    texture width
  +0x0A  height     u16 LE    texture height
  +0x0C  fmt_code   u8        jIMG format code
  +0x0D  flags      u8        misc flags
  +0x0E  pad        u16 LE
  +0x10-0x7F        reserved/mip descriptors
  +0x80  pixel_data starts here
"""

import struct
import logging
from typing import List, Dict, Any, Optional

from textures.decoder import (
    FORMAT_BPP, FORMAT_NAMES, FMT_ETC1, FMT_ETC1A4,
    FMT_RGBA8, FMT_RGB8, FMT_RGBA5551, FMT_RGB565,
    FMT_RGBA4, FMT_LA8, FMT_L8, FMT_A8, FMT_LA4, FMT_L4, FMT_A4,
    calculate_texture_size,
)

logger = logging.getLogger(__name__)

JIMG_MAGIC = b'jIMG'
HEADER_SIZE = 0x80

# Known jIMG format byte → PICA200 format mapping.
# Derived by cross-referencing pixel data sizes with expected PICA200 sizes.
# 0x08 = ETC1 (confirmed: 256×256 files → 32768 bytes = 256×256×4/8)
# 0x0F = ETC1 (confirmed: 256×128 files → 16384 bytes)
# 0x10 = ETC1A4 (confirmed: 256×128 files → 32768 bytes = 256×128×8/8)
_JIMG_FMT_MAP = {
    0x00: FMT_RGBA8,
    0x01: FMT_RGB8,
    0x02: FMT_RGBA5551,
    0x03: FMT_RGB565,
    0x04: FMT_RGBA4,
    0x05: FMT_LA8,
    0x07: FMT_L8,
    0x08: FMT_ETC1,
    0x09: FMT_LA4,
    0x0A: FMT_L4,
    0x0B: FMT_RGBA4,   # confirmed by size inference: 64×64 → 8192 bytes = 64×64×16/8
    0x0C: FMT_A8,
    0x0D: FMT_ETC1A4,
    0x0E: FMT_ETC1,
    0x0F: FMT_ETC1,
    0x10: FMT_ETC1A4,
}


def is_jimg(data: bytes) -> bool:
    return len(data) >= HEADER_SIZE and data[:4] == JIMG_MAGIC


def parse_jimg(data: bytes, file_path: str = "") -> List[Dict[str, Any]]:
    """Extract a single PICA200 texture from a jIMG file."""
    if not is_jimg(data):
        return []

    if len(data) < HEADER_SIZE + 4:
        return []

    w = struct.unpack_from('<H', data, 0x08)[0]
    h = struct.unpack_from('<H', data, 0x0A)[0]
    fmt_code = data[0x0C]

    if w == 0 or h == 0 or w > 4096 or h > 4096:
        logger.debug(f"jIMG {file_path}: bad dimensions {w}×{h}")
        return []

    pixel_data = data[HEADER_SIZE:]
    actual_size = len(pixel_data)

    # Resolve PICA200 format — try the mapped format first, then infer from size.
    pica_fmt = _resolve_format(w, h, fmt_code, actual_size, file_path)
    if pica_fmt is None:
        return []

    return [{
        'width': w,
        'height': h,
        'format': pica_fmt,
        'data': pixel_data,
        'source_file': file_path,
        'parser_used': 'jimg',
        'confidence': 'high',
    }]


def _resolve_format(w: int, h: int, fmt_code: int, actual_size: int,
                    file_path: str) -> Optional[int]:
    """Return the PICA200 format that matches width×height×bpp == actual_size."""
    # Try the mapped format first.
    if fmt_code in _JIMG_FMT_MAP:
        pica_fmt = _JIMG_FMT_MAP[fmt_code]
        expected = calculate_texture_size(w, h, pica_fmt)
        if expected == actual_size:
            return pica_fmt
        # Mapped format doesn't fit — fall through to size inference.
        logger.debug(
            f"jIMG {file_path}: mapped fmt 0x{fmt_code:02X}→PICA200 0x{pica_fmt:02X} "
            f"expected {expected} bytes but got {actual_size}"
        )

    # Infer format by matching actual_size against every known PICA200 format.
    # Prefer ETC1A4 > ETC1 > others when multiple match (quality priority).
    candidates = []
    for pica_fmt in range(0x0E):
        expected = calculate_texture_size(w, h, pica_fmt)
        if expected == actual_size:
            candidates.append(pica_fmt)

    if not candidates:
        logger.debug(
            f"jIMG {file_path}: cannot infer format for {w}×{h} size={actual_size}"
        )
        return None

    # Prefer ETC1A4, then ETC1, then first candidate.
    for preferred in (FMT_ETC1A4, FMT_ETC1):
        if preferred in candidates:
            return preferred
    return candidates[0]
