"""BFLIM/BCLIM (Binary FLexible/CTR Layout IMage) parser for 3DS UI/2D textures.

BFLIM: footer at end with FLIM magic, imag section at footer+0x14
BCLIM: footer at end with CLIM magic, imag section at footer+0x14
Both share the same pixel format enum and decode logic.
"""

import logging
import math
from typing import Optional, Dict, Any
from utils import read_u16_le, read_u16_be, read_u32_le, read_u32_be

logger = logging.getLogger(__name__)

# BFLIM format mapping to PICA200 format IDs
# Reference: 3DS NW4C library, Switch Toolbox, Ohana3DS
BFLIM_FORMAT_MAP = {
    0x00: 0x07,  # L8
    0x01: 0x08,  # A8
    0x02: 0x09,  # LA4
    0x03: 0x05,  # LA8
    0x04: 0x06,  # HILO8
    0x05: 0x03,  # RGB565
    0x06: 0x01,  # RGB8
    0x07: 0x02,  # RGBA5551
    0x08: 0x04,  # RGBA4
    0x09: 0x00,  # RGBA8
    0x0A: 0x0C,  # ETC1
    0x0B: 0x0D,  # ETC1A4
    0x0C: 0x0A,  # L4
    0x0D: 0x08,  # A4 (mapped to A8, closest available)
}

# BPP for each BFLIM format (used to compute storage dimensions)
_BFLIM_BPP = {
    0x00: 8, 0x01: 8, 0x02: 8, 0x03: 16, 0x04: 16,
    0x05: 16, 0x06: 24, 0x07: 16, 0x08: 16, 0x09: 32,
    0x0A: 4, 0x0B: 8, 0x0C: 4, 0x0D: 4,
}


def _next_pow2(v: int) -> int:
    """Round up to next power of 2."""
    if v <= 0:
        return 1
    v -= 1
    v |= v >> 1
    v |= v >> 2
    v |= v >> 4
    v |= v >> 8
    v |= v >> 16
    return v + 1


def is_bflim(data: bytes) -> bool:
    """Check if data is a BFLIM or BCLIM file. The header is at the END of the file."""
    if len(data) < 0x28:
        return False
    footer_offset = len(data) - 0x28
    magic = data[footer_offset:footer_offset + 4]
    return magic in (b'FLIM', b'CLIM')


def parse_bflim(data: bytes) -> Optional[Dict[str, Any]]:
    """
    Parse a BFLIM or BCLIM file.
    Returns dict with: format, width, height, data (raw pixel bytes)
    """
    if not is_bflim(data):
        return None

    try:
        footer_offset = len(data) - 0x28
        footer_magic = data[footer_offset:footer_offset + 4]
        is_bclim = (footer_magic == b'CLIM')

        # FLIM/CLIM header (at end of file)
        bom = read_u16_be(data, footer_offset + 4)

        is_le = (bom == 0xFFFE)
        read_u16 = read_u16_le if is_le else read_u16_be
        read_u32 = read_u32_le if is_le else read_u32_be

        # imag section follows FLIM/CLIM header at footer + 0x14
        imag_offset = footer_offset + 0x14
        if imag_offset + 4 > len(data):
            return None

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

        display_width = read_u16(data, imag_offset + 0x08)
        display_height = read_u16(data, imag_offset + 0x0A)

        if is_bclim:
            # BCLIM imag layout:
            # 0x08: width (u16), 0x0A: height (u16)
            # 0x0C: format (u32) — same enum as BFLIM but stored as u32
            # 0x10: data_size (u32)
            bflim_format = read_u32(data, imag_offset + 0x0C)
            swizzle = 0
        else:
            # BFLIM imag layout:
            # 0x08: width (u16), 0x0A: height (u16)
            # 0x0C: alignment (u16)
            # 0x0E: format (u8)
            # 0x0F: swizzle (u8)
            if imag_offset + 0x0F > len(data):
                return None
            bflim_format = data[imag_offset + 0x0E]
            swizzle = data[imag_offset + 0x0F]

        # Map to PICA200 format
        pica_format = BFLIM_FORMAT_MAP.get(bflim_format)
        if pica_format is None:
            logger.warning(f"BFLIM: unknown format 0x{bflim_format:02X}")
            return None

        # Pixel data is at the start of the file, before the footer
        pixel_data = data[0:footer_offset]

        # Compute storage dimensions: texture memory is power-of-2 padded
        # The display dimensions may be non-pow2 but the stored data is pow2-aligned
        bpp = _BFLIM_BPP.get(bflim_format, 32)
        storage_width = _next_pow2(display_width) if display_width & (display_width - 1) else display_width
        storage_height = _next_pow2(display_height) if display_height & (display_height - 1) else display_height

        # Ensure minimum alignment to 8 (Morton tile size)
        if storage_width < 8:
            storage_width = 8
        if storage_height < 8:
            storage_height = 8

        # Verify: does the pixel data size match the storage dimensions?
        from textures.decoder import calculate_texture_size
        expected_storage = calculate_texture_size(storage_width, storage_height, pica_format)
        expected_display = calculate_texture_size(display_width, display_height, pica_format)

        if expected_storage > 0 and len(pixel_data) >= expected_storage:
            # Use storage dimensions for decoding, will crop later
            decode_width = storage_width
            decode_height = storage_height
        elif expected_display > 0 and len(pixel_data) >= expected_display:
            # Display dims work directly
            decode_width = display_width
            decode_height = display_height
        else:
            # Try storage dims anyway (may be slightly off)
            decode_width = storage_width
            decode_height = storage_height

        fmt_label = "BCLIM" if is_bclim else "BFLIM"
        logger.info(
            f"{fmt_label}: display={display_width}x{display_height} "
            f"storage={storage_width}x{storage_height} "
            f"format=0x{bflim_format:02X}->PICA 0x{pica_format:X} "
            f"swizzle=0x{swizzle:02X} data={len(pixel_data)}"
        )

        return {
            'format': pica_format,
            'width': decode_width,
            'height': decode_height,
            'display_width': display_width,
            'display_height': display_height,
            'data': pixel_data,
            'name': '',
            'bflim_format': bflim_format,
            'swizzle': swizzle,
        }

    except Exception as e:
        logger.warning(f"Error parsing BFLIM: {e}")
        return None
