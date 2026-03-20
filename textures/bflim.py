"""BFLIM (Binary FLexible IMage) parser for 3DS UI/2D textures."""

import logging
from typing import Optional, Dict, Any
from utils import read_u16_le, read_u16_be, read_u32_le, read_u32_be

logger = logging.getLogger(__name__)

# BFLIM format mapping to PICA200 format IDs
BFLIM_FORMAT_MAP = {
    0x00: 0x07,  # L8
    0x01: 0x08,  # A8
    0x02: 0x09,  # LA4
    0x03: 0x05,  # LA8
    0x04: 0x06,  # HILO8
    0x05: 0x03,  # RGB565
    0x06: 0x04,  # RGBA4 (called RGB8 in some docs but actually RGBA4 on 3DS)
    0x07: 0x02,  # RGBA5551
    0x08: 0x00,  # RGBA8
    0x09: 0x0C,  # ETC1
    0x0A: 0x0D,  # ETC1A4
    0x0B: 0x07,  # L4
    0x0C: 0x08,  # A4
    0x0D: 0x01,  # RGB8 (or BGR8)
}


def is_bflim(data: bytes) -> bool:
    """Check if data is a BFLIM file. The FLIM header is at the END of the file."""
    if len(data) < 0x28:
        return False
    # Check for FLIM magic at the end of the file
    footer_offset = len(data) - 0x28
    magic = data[footer_offset:footer_offset + 4]
    return magic == b'FLIM'


def parse_bflim(data: bytes) -> Optional[Dict[str, Any]]:
    """
    Parse a BFLIM file.
    Returns dict with: format, width, height, data (raw pixel bytes)
    """
    if not is_bflim(data):
        return None

    try:
        footer_offset = len(data) - 0x28

        # FLIM header (at end of file)
        magic = data[footer_offset:footer_offset + 4]
        bom = read_u16_be(data, footer_offset + 4)

        is_le = (bom == 0xFFFE)
        read_u16 = read_u16_le if is_le else read_u16_be
        read_u32 = read_u32_le if is_le else read_u32_be

        header_size = read_u16(data, footer_offset + 6)
        version = read_u32(data, footer_offset + 8)
        file_size = read_u32(data, footer_offset + 0x0C)
        section_count = read_u16(data, footer_offset + 0x10) if footer_offset + 0x12 <= len(data) else 1

        # imag section follows FLIM header
        imag_offset = footer_offset + 0x14
        if imag_offset + 4 > len(data):
            # Try right after FLIM header
            imag_offset = footer_offset + header_size

        imag_magic = data[imag_offset:imag_offset + 4]
        if imag_magic != b'imag':
            logger.warning(f"Expected 'imag' section, got {imag_magic!r}")
            # Try to find it
            for search_off in range(footer_offset + 0x10, len(data) - 4):
                if data[search_off:search_off + 4] == b'imag':
                    imag_offset = search_off
                    break
            else:
                return None

        # imag section:
        # 0x00: magic 'imag' (4 bytes)
        # 0x04: section size (4 bytes)
        # 0x08: width (u16)
        # 0x0A: height (u16)
        # 0x0C: alignment (u32) or format(u16) + padding
        # 0x10: format (u8 or u16)

        # Layout varies by version; try common layouts
        width = read_u16(data, imag_offset + 0x08)
        height = read_u16(data, imag_offset + 0x0A)

        # Format byte location
        bflim_format = data[imag_offset + 0x0C] if imag_offset + 0x0D <= len(data) else 0

        # Map to PICA200 format
        pica_format = BFLIM_FORMAT_MAP.get(bflim_format, 0x00)

        logger.info(f"BFLIM: {width}x{height}, format=0x{bflim_format:02X} -> PICA 0x{pica_format:X}")

        # Pixel data is at the start of the file
        data_size = footer_offset
        pixel_data = data[0:data_size]

        return {
            'format': pica_format,
            'width': width,
            'height': height,
            'data': pixel_data,
            'name': '',
        }

    except Exception as e:
        logger.warning(f"Error parsing BFLIM: {e}")
        return None
