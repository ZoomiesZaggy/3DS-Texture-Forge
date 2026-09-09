"""CTPK (CTR Texture PacKage) parser for 3DS textures."""

import logging
from typing import List, Dict, Any
from utils import read_u32_le, read_u16_le, read_u8, read_string

logger = logging.getLogger(__name__)


def is_ctpk(data: bytes) -> bool:
    """Check if data is a CTPK file."""
    if len(data) < 4:
        return False
    return data[0:4] == b'CTPK'


def parse_ctpk(data: bytes) -> List[Dict[str, Any]]:
    """
    Parse a CTPK texture package.
    Returns list of dicts with: name, format, width, height, data_offset, data_size, mip_count
    """
    if not is_ctpk(data):
        return []

    textures = []

    try:
        # CTPK header:
        # 0x00: magic "CTPK" (4 bytes)
        # 0x04: version (u16)
        # 0x06: texture count (u16)
        # 0x08: texture data offset (u32)
        # 0x0C: texture data size (u32)
        # 0x10: hash section offset (u32)
        # 0x14: texture info section size (u32)

        version = read_u16_le(data, 0x04)
        tex_count = read_u16_le(data, 0x06)
        tex_data_offset = read_u32_le(data, 0x08)
        tex_data_size = read_u32_le(data, 0x0C)

        logger.info(f"CTPK: version={version}, textures={tex_count}, "
                     f"data_offset=0x{tex_data_offset:X}")

        if tex_count == 0 or tex_count > 10000:
            logger.warning(f"Suspicious texture count: {tex_count}")
            return []

        # Texture entries start at offset 0x20
        # Each entry is 0x20 bytes:
        # 0x00: name offset (u32) - relative to start of file
        # 0x04: data size (u32)
        # 0x08: data offset (u32) - relative to texture data section
        # 0x0C: format (u32)
        # 0x10: width (u16)
        # 0x12: height (u16)
        # 0x14: mip levels (u8)
        # 0x15: type (u8)
        # 0x16: padding (u16)
        # 0x18: BMP size offset (u32)
        # 0x1C: UNIX timestamp (u32)

        entry_start = 0x20
        for i in range(tex_count):
            entry_off = entry_start + i * 0x20
            if entry_off + 0x20 > len(data):
                break

            name_offset = read_u32_le(data, entry_off + 0x00)
            data_size = read_u32_le(data, entry_off + 0x04)
            data_offset = read_u32_le(data, entry_off + 0x08) + tex_data_offset
            tex_format = read_u32_le(data, entry_off + 0x0C)
            width = read_u16_le(data, entry_off + 0x10)
            height = read_u16_le(data, entry_off + 0x12)
            mip_levels = read_u8(data, entry_off + 0x14)

            # Read name from string table
            name = ""
            if name_offset > 0 and name_offset < len(data):
                name = read_string(data, name_offset)

            logger.debug(f"CTPK tex {i}: {name!r} {width}x{height} fmt=0x{tex_format:X} "
                          f"offset=0x{data_offset:X} size=0x{data_size:X}")

            # Validate
            if width == 0 or height == 0 or width > 2048 or height > 2048:
                logger.warning(f"Skipping texture {i} with invalid dimensions: {width}x{height}")
                continue

            if tex_format > 0xD:
                logger.warning(f"Unknown texture format 0x{tex_format:X} for texture {i}")
                continue

            textures.append({
                'index': i,
                'name': name,
                'format': tex_format,
                'width': width,
                'height': height,
                'data_offset': data_offset,
                'data_size': data_size,
                'mip_count': max(1, mip_levels),
            })

    except Exception as e:
        logger.warning(f"Error parsing CTPK: {e}")

    logger.info(f"CTPK: found {len(textures)} textures")
    return textures
