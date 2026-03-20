"""Morton-order (Z-order) de-tiling and pixel format decoding for 3DS PICA200 textures."""

import numpy as np
import logging
from typing import Optional
from textures.etc1 import decode_etc1, decode_etc1a4

logger = logging.getLogger(__name__)

# Format IDs
FMT_RGBA8 = 0x0
FMT_RGB8 = 0x1
FMT_RGBA5551 = 0x2
FMT_RGB565 = 0x3
FMT_RGBA4 = 0x4
FMT_LA8 = 0x5
FMT_HILO8 = 0x6
FMT_L8 = 0x7
FMT_A8 = 0x8
FMT_LA4 = 0x9
FMT_L4 = 0xA
FMT_A4 = 0xB
FMT_ETC1 = 0xC
FMT_ETC1A4 = 0xD

FORMAT_NAMES = {
    FMT_RGBA8: "RGBA8",
    FMT_RGB8: "RGB8",
    FMT_RGBA5551: "RGBA5551",
    FMT_RGB565: "RGB565",
    FMT_RGBA4: "RGBA4",
    FMT_LA8: "LA8",
    FMT_HILO8: "HILO8",
    FMT_L8: "L8",
    FMT_A8: "A8",
    FMT_LA4: "LA4",
    FMT_L4: "L4",
    FMT_A4: "A4",
    FMT_ETC1: "ETC1",
    FMT_ETC1A4: "ETC1A4",
}

# Bits per pixel for each format
FORMAT_BPP = {
    FMT_RGBA8: 32,
    FMT_RGB8: 24,
    FMT_RGBA5551: 16,
    FMT_RGB565: 16,
    FMT_RGBA4: 16,
    FMT_LA8: 16,
    FMT_HILO8: 16,
    FMT_L8: 8,
    FMT_A8: 8,
    FMT_LA4: 8,
    FMT_L4: 4,
    FMT_A4: 4,
    FMT_ETC1: 4,
    FMT_ETC1A4: 8,
}


def get_format_name(fmt: int) -> str:
    return FORMAT_NAMES.get(fmt, f"UNKNOWN_0x{fmt:X}")


def get_format_bpp(fmt: int) -> int:
    return FORMAT_BPP.get(fmt, 0)


def calculate_texture_size(width: int, height: int, fmt: int) -> int:
    """Calculate the expected data size for a texture."""
    bpp = FORMAT_BPP.get(fmt, 0)
    if bpp == 0:
        return 0
    return (width * height * bpp + 7) // 8


# Pre-computed morton order lookup table for 8x8 blocks
# Maps (x, y) where x,y in [0,7] to the morton-order index
MORTON_TABLE = [
    0, 1, 4, 5, 16, 17, 20, 21,
    2, 3, 6, 7, 18, 19, 22, 23,
    8, 9, 12, 13, 24, 25, 28, 29,
    10, 11, 14, 15, 26, 27, 30, 31,
    32, 33, 36, 37, 48, 49, 52, 53,
    34, 35, 38, 39, 50, 51, 54, 55,
    40, 41, 44, 45, 56, 57, 60, 61,
    42, 43, 46, 47, 58, 59, 62, 63,
]


def _morton_index(x: int, y: int) -> int:
    """Get morton index for local coordinates within an 8x8 tile."""
    return MORTON_TABLE[y * 8 + x]


def _decode_pixel_rgba8(data: bytes, offset: int) -> tuple:
    """Decode RGBA8 pixel (stored as ABGR on 3DS)."""
    if offset + 4 > len(data):
        return (0, 0, 0, 0)
    a = data[offset]
    b = data[offset + 1]
    g = data[offset + 2]
    r = data[offset + 3]
    return (r, g, b, a)


def _decode_pixel_rgb8(data: bytes, offset: int) -> tuple:
    """Decode RGB8 pixel (stored as BGR)."""
    if offset + 3 > len(data):
        return (0, 0, 0, 255)
    b = data[offset]
    g = data[offset + 1]
    r = data[offset + 2]
    return (r, g, b, 255)


def _decode_pixel_rgba5551(data: bytes, offset: int) -> tuple:
    if offset + 2 > len(data):
        return (0, 0, 0, 0)
    val = data[offset] | (data[offset + 1] << 8)
    r5 = (val >> 11) & 0x1F
    g5 = (val >> 6) & 0x1F
    b5 = (val >> 1) & 0x1F
    a1 = val & 1
    r = (r5 << 3) | (r5 >> 2)
    g = (g5 << 3) | (g5 >> 2)
    b = (b5 << 3) | (b5 >> 2)
    a = a1 * 255
    return (r, g, b, a)


def _decode_pixel_rgb565(data: bytes, offset: int) -> tuple:
    if offset + 2 > len(data):
        return (0, 0, 0, 255)
    val = data[offset] | (data[offset + 1] << 8)
    r5 = (val >> 11) & 0x1F
    g6 = (val >> 5) & 0x3F
    b5 = val & 0x1F
    r = (r5 << 3) | (r5 >> 2)
    g = (g6 << 2) | (g6 >> 4)
    b = (b5 << 3) | (b5 >> 2)
    return (r, g, b, 255)


def _decode_pixel_rgba4(data: bytes, offset: int) -> tuple:
    if offset + 2 > len(data):
        return (0, 0, 0, 0)
    val = data[offset] | (data[offset + 1] << 8)
    r4 = (val >> 12) & 0xF
    g4 = (val >> 8) & 0xF
    b4 = (val >> 4) & 0xF
    a4 = val & 0xF
    r = (r4 << 4) | r4
    g = (g4 << 4) | g4
    b = (b4 << 4) | b4
    a = (a4 << 4) | a4
    return (r, g, b, a)


def _decode_pixel_la8(data: bytes, offset: int) -> tuple:
    if offset + 2 > len(data):
        return (0, 0, 0, 0)
    a = data[offset]
    l = data[offset + 1]
    return (l, l, l, a)


def _decode_pixel_hilo8(data: bytes, offset: int) -> tuple:
    if offset + 2 > len(data):
        return (0, 0, 255, 255)
    hi = data[offset]
    lo = data[offset + 1]
    return (hi, lo, 255, 255)


def _decode_pixel_l8(data: bytes, offset: int) -> tuple:
    if offset + 1 > len(data):
        return (0, 0, 0, 255)
    l = data[offset]
    return (l, l, l, 255)


def _decode_pixel_a8(data: bytes, offset: int) -> tuple:
    if offset + 1 > len(data):
        return (255, 255, 255, 0)
    a = data[offset]
    return (255, 255, 255, a)


def _decode_pixel_la4(data: bytes, offset: int) -> tuple:
    if offset + 1 > len(data):
        return (0, 0, 0, 0)
    val = data[offset]
    a4 = val & 0xF
    l4 = (val >> 4) & 0xF
    l = (l4 << 4) | l4
    a = (a4 << 4) | a4
    return (l, l, l, a)


def decode_texture(data: bytes, width: int, height: int, fmt: int) -> Optional[np.ndarray]:
    """
    Decode a 3DS PICA200 texture from raw data.

    Handles morton-order de-tiling and pixel format conversion.
    Returns an RGBA8 numpy array (height x width x 4) or None on failure.
    """
    if width <= 0 or height <= 0:
        logger.warning(f"Invalid texture dimensions: {width}x{height}")
        return None

    # ETC1 and ETC1A4 use block compression, not morton tiling at pixel level
    if fmt == FMT_ETC1:
        return decode_etc1(data, width, height)
    elif fmt == FMT_ETC1A4:
        return decode_etc1a4(data, width, height)

    # For non-compressed formats, decode with morton de-tiling
    bpp = FORMAT_BPP.get(fmt)
    if bpp is None:
        logger.warning(f"Unknown format: 0x{fmt:X}")
        return None

    output = np.zeros((height, width, 4), dtype=np.uint8)

    # Select pixel decoder
    pixel_decoders = {
        FMT_RGBA8: (_decode_pixel_rgba8, 4),
        FMT_RGB8: (_decode_pixel_rgb8, 3),
        FMT_RGBA5551: (_decode_pixel_rgba5551, 2),
        FMT_RGB565: (_decode_pixel_rgb565, 2),
        FMT_RGBA4: (_decode_pixel_rgba4, 2),
        FMT_LA8: (_decode_pixel_la8, 2),
        FMT_HILO8: (_decode_pixel_hilo8, 2),
        FMT_L8: (_decode_pixel_l8, 1),
        FMT_A8: (_decode_pixel_a8, 1),
        FMT_LA4: (_decode_pixel_la4, 1),
    }

    if fmt in (FMT_L4, FMT_A4):
        return _decode_4bpp_texture(data, width, height, fmt, output)

    if fmt not in pixel_decoders:
        logger.warning(f"No decoder for format 0x{fmt:X}")
        return None

    decoder_func, bytes_per_pixel = pixel_decoders[fmt]

    # Process 8x8 tiles in morton order
    tiles_x = (width + 7) // 8
    tiles_y = (height + 7) // 8

    data_offset = 0

    for tile_y in range(tiles_y):
        for tile_x in range(tiles_x):
            for morton_idx in range(64):
                # Find (local_x, local_y) for this morton index
                # We need the inverse of the morton table
                local_x = -1
                local_y = -1
                for ly in range(8):
                    for lx in range(8):
                        if MORTON_TABLE[ly * 8 + lx] == morton_idx:
                            local_x = lx
                            local_y = ly
                            break
                    if local_x >= 0:
                        break

                pixel_x = tile_x * 8 + local_x
                pixel_y = tile_y * 8 + local_y

                if pixel_x < width and pixel_y < height:
                    if data_offset + bytes_per_pixel <= len(data):
                        r, g, b, a = decoder_func(data, data_offset)
                        output[pixel_y, pixel_x] = [r, g, b, a]

                data_offset += bytes_per_pixel

    return output


def _decode_4bpp_texture(data: bytes, width: int, height: int, fmt: int,
                         output: np.ndarray) -> np.ndarray:
    """Decode 4-bit per pixel textures (L4, A4) with morton de-tiling."""
    tiles_x = (width + 7) // 8
    tiles_y = (height + 7) // 8

    # Build inverse morton table
    inv_morton = [None] * 64
    for ly in range(8):
        for lx in range(8):
            inv_morton[MORTON_TABLE[ly * 8 + lx]] = (lx, ly)

    pixel_index = 0

    for tile_y in range(tiles_y):
        for tile_x in range(tiles_x):
            for morton_idx in range(64):
                local_x, local_y = inv_morton[morton_idx]

                pixel_x = tile_x * 8 + local_x
                pixel_y = tile_y * 8 + local_y

                byte_offset = pixel_index // 2
                is_high_nibble = pixel_index % 2

                if byte_offset < len(data):
                    byte_val = data[byte_offset]
                    if is_high_nibble:
                        nibble = (byte_val >> 4) & 0xF
                    else:
                        nibble = byte_val & 0xF

                    val8 = (nibble << 4) | nibble

                    if pixel_x < width and pixel_y < height:
                        if fmt == FMT_L4:
                            output[pixel_y, pixel_x] = [val8, val8, val8, 255]
                        else:  # A4
                            output[pixel_y, pixel_x] = [255, 255, 255, val8]

                pixel_index += 1

    return output


# Pre-compute inverse morton table for performance
_INV_MORTON = [None] * 64
for _ly in range(8):
    for _lx in range(8):
        _INV_MORTON[MORTON_TABLE[_ly * 8 + _lx]] = (_lx, _ly)


def decode_texture_fast(data: bytes, width: int, height: int, fmt: int) -> Optional[np.ndarray]:
    """
    Optimized texture decoder using pre-computed inverse morton table.
    This is the preferred entry point.
    """
    if width <= 0 or height <= 0:
        return None

    # ETC formats don't use per-pixel morton tiling
    if fmt == FMT_ETC1:
        return decode_etc1(data, width, height)
    elif fmt == FMT_ETC1A4:
        return decode_etc1a4(data, width, height)

    if fmt in (FMT_L4, FMT_A4):
        output = np.zeros((height, width, 4), dtype=np.uint8)
        return _decode_4bpp_texture(data, width, height, fmt, output)

    bpp = FORMAT_BPP.get(fmt)
    if bpp is None:
        return None

    bytes_per_pixel = bpp // 8
    if bytes_per_pixel == 0:
        return None

    pixel_decoders = {
        FMT_RGBA8: _decode_pixel_rgba8,
        FMT_RGB8: _decode_pixel_rgb8,
        FMT_RGBA5551: _decode_pixel_rgba5551,
        FMT_RGB565: _decode_pixel_rgb565,
        FMT_RGBA4: _decode_pixel_rgba4,
        FMT_LA8: _decode_pixel_la8,
        FMT_HILO8: _decode_pixel_hilo8,
        FMT_L8: _decode_pixel_l8,
        FMT_A8: _decode_pixel_a8,
        FMT_LA4: _decode_pixel_la4,
    }

    decoder_func = pixel_decoders.get(fmt)
    if decoder_func is None:
        return None

    output = np.zeros((height, width, 4), dtype=np.uint8)
    tiles_x = (width + 7) // 8
    tiles_y = (height + 7) // 8

    data_offset = 0
    data_len = len(data)

    for tile_y in range(tiles_y):
        for tile_x in range(tiles_x):
            for morton_idx in range(64):
                local_x, local_y = _INV_MORTON[morton_idx]
                pixel_x = tile_x * 8 + local_x
                pixel_y = tile_y * 8 + local_y

                if data_offset + bytes_per_pixel <= data_len:
                    if pixel_x < width and pixel_y < height:
                        r, g, b, a = decoder_func(data, data_offset)
                        output[pixel_y, pixel_x] = [r, g, b, a]

                data_offset += bytes_per_pixel

    return output
