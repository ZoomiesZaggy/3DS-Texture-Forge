"""CTXB (CTR Texture Binary) parser for Grezzo 3DS games.

CTXB is used by Grezzo-developed titles (OoT3D, MM3D, Luigi's Mansion 3DS).
Format: ctxb header → 'tex ' chunk → per-texture entries → raw pixel data.

PixelFormat uses PICA200 DMP OpenGL extension constants (0x6750 base).
Reference: Tharsis by xdanieldzd (CTXB.cs)
"""

import logging
import struct
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# CTXB pixel format → PICA200 format mapping
# These are GL_*_NATIVE_DMP OpenGL extension enum values
CTXB_FORMAT_MAP = {
    0x6750: 0x00,  # RGBA8
    0x6751: 0x01,  # RGB8
    0x6752: 0x02,  # RGBA5551
    0x6753: 0x03,  # RGB565
    0x6754: 0x04,  # RGBA4
    0x6755: 0x05,  # LA8
    0x6756: 0x06,  # HILO8
    0x6757: 0x07,  # L8
    0x6758: 0x08,  # A8
    0x6759: 0x09,  # LA4
    0x675A: 0x0C,  # ETC1
    0x675B: 0x0D,  # ETC1A4
}


def is_ctxb(data: bytes) -> bool:
    """Check if data is a CTXB file."""
    return len(data) >= 0x24 and data[0:4] == b'ctxb'


def parse_ctxb(data: bytes) -> List[Dict[str, Any]]:
    """Parse a CTXB texture container.

    Returns list of dicts with: name, format, width, height, data_offset, data_size
    """
    if not is_ctxb(data):
        return []

    textures = []
    file_len = len(data)

    try:
        # CTXB header (0x18 bytes)
        file_size = struct.unpack_from('<I', data, 0x04)[0]
        num_chunks = struct.unpack_from('<I', data, 0x08)[0]
        tex_chunk_offset = struct.unpack_from('<I', data, 0x10)[0]
        texture_data_offset = struct.unpack_from('<I', data, 0x14)[0]

        if tex_chunk_offset + 0x0C > file_len:
            return []

        # tex chunk header
        tex_magic = data[tex_chunk_offset:tex_chunk_offset + 4]
        if tex_magic != b'tex ':
            logger.warning(f"CTXB: expected 'tex ' chunk, got {tex_magic!r}")
            return []

        tex_count = struct.unpack_from('<I', data, tex_chunk_offset + 0x08)[0]
        if tex_count == 0 or tex_count > 1000:
            return []

        # Per-texture entries: 0x24 bytes each, starting after tex chunk header (12 bytes)
        entry_base = tex_chunk_offset + 0x0C

        for i in range(tex_count):
            entry_off = entry_base + i * 0x24
            if entry_off + 0x24 > file_len:
                break

            data_length = struct.unpack_from('<I', data, entry_off + 0x00)[0]
            width = struct.unpack_from('<H', data, entry_off + 0x08)[0]
            height = struct.unpack_from('<H', data, entry_off + 0x0A)[0]
            pixel_format = struct.unpack_from('<H', data, entry_off + 0x0C)[0]
            data_type = struct.unpack_from('<H', data, entry_off + 0x0E)[0]
            data_offset_rel = struct.unpack_from('<I', data, entry_off + 0x10)[0]

            # Read name (16 bytes, null-terminated)
            name_bytes = data[entry_off + 0x14:entry_off + 0x24]
            try:
                name = name_bytes.split(b'\x00')[0].decode('ascii', errors='replace')
            except Exception:
                name = ""

            # Map CTXB format to PICA200 format
            pica_format = CTXB_FORMAT_MAP.get(pixel_format)
            if pica_format is None:
                logger.warning(f"CTXB: unknown pixel format 0x{pixel_format:04X} for texture {i}")
                continue

            # Validate dimensions
            if width == 0 or height == 0 or width > 2048 or height > 2048:
                continue

            # Absolute data offset
            abs_data_offset = texture_data_offset + data_offset_rel

            if abs_data_offset >= file_len:
                continue

            # Clamp data_length to available data
            available = file_len - abs_data_offset
            actual_length = min(data_length, available) if data_length > 0 else available

            if not name:
                name = f"ctxb_tex_{i:04d}"

            logger.debug(
                f"CTXB tex {i}: {name!r} {width}x{height} "
                f"fmt=0x{pixel_format:04X}->PICA 0x{pica_format:X} "
                f"offset=0x{abs_data_offset:X} size=0x{actual_length:X}"
            )

            textures.append({
                'index': i,
                'name': name,
                'format': pica_format,
                'width': width,
                'height': height,
                'data_offset': abs_data_offset,
                'data_size': actual_length,
                'mip_count': 1,
            })

    except Exception as e:
        logger.warning(f"Error parsing CTXB: {e}")

    if textures:
        logger.debug(f"CTXB: found {len(textures)} textures")
    return textures
