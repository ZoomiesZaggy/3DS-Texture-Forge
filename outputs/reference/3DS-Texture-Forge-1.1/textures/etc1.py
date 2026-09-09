"""Full ETC1 and ETC1A4 texture decoder for 3DS PICA200 GPU."""

import numpy as np

# ETC1 modifier tables (from the ETC1 specification)
ETC1_MODIFIER_TABLE = [
    [2, 8],
    [5, 17],
    [9, 29],
    [13, 42],
    [18, 60],
    [24, 80],
    [33, 106],
    [47, 183],
]

# Pixel index to modifier mapping
# The 2-bit pixel index selects from: [+large, +small, -small, -large]
# msb=0,lsb=0 -> +large; msb=0,lsb=1 -> +small; msb=1,lsb=0 -> -small; msb=1,lsb=1 -> -large
PIXEL_INDEX_MODIFIERS = [
    # (msb, lsb) -> modifier index: [+b, +a, -a, -b]
    # where a = table[idx][0], b = table[idx][1]
    2, 3, 1, 0  # msb<<1|lsb: 0->+b(idx2), 1->+a(idx3), 2->-a(idx1), 3->-b(idx0)
]


def _clamp(val: int) -> int:
    """Clamp value to [0, 255]."""
    if val < 0:
        return 0
    if val > 255:
        return 255
    return val


def _sign_extend_3bit(val: int) -> int:
    """Sign-extend a 3-bit value to a signed integer."""
    if val >= 4:
        return val - 8
    return val


def _expand_5to8(val: int) -> int:
    """Expand a 5-bit color value to 8-bit."""
    return (val << 3) | (val >> 2)


def _expand_4to8(val: int) -> int:
    """Expand a 4-bit color value to 8-bit."""
    return val * 17  # Equivalent to (val << 4) | val


def decode_etc1_block(block_data: bytes) -> np.ndarray:
    """
    Decode a single 4x4 ETC1 block from 8 bytes.
    Returns a 4x4x3 uint8 array (RGB).

    3DS PICA200 stores ETC1 blocks as little-endian u64:
    - Bits 63-40: color data (R, G, B)
    - Bits 39-37: table index 1
    - Bits 36-34: table index 2
    - Bit 33: differential mode
    - Bit 32: flip
    - Bits 31-16: negation flags (MSB of pixel indices)
    - Bits 15-0: table sub-indices (LSB of pixel indices)
    """
    # Read as little-endian u64 (3DS PICA200 native format)
    block_u64 = int.from_bytes(block_data[0:8], 'little')

    # Extract the two logical 32-bit words from the u64
    # word1 = upper 32 bits (color/table/flags), word2 = lower 32 bits (pixel indices)
    word1 = (block_u64 >> 32) & 0xFFFFFFFF
    word2 = block_u64 & 0xFFFFFFFF

    # diff_bit at block bit 33 = word1 bit 1
    # flip_bit at block bit 32 = word1 bit 0
    diff_bit = (word1 >> 1) & 1
    flip_bit = word1 & 1

    if diff_bit == 0:
        # Individual mode: two independent 4-bit colors
        r1 = _expand_4to8((word1 >> 28) & 0xF)
        g1 = _expand_4to8((word1 >> 20) & 0xF)
        b1 = _expand_4to8((word1 >> 12) & 0xF)
        r2 = _expand_4to8((word1 >> 24) & 0xF)
        g2 = _expand_4to8((word1 >> 16) & 0xF)
        b2 = _expand_4to8((word1 >> 8) & 0xF)
    else:
        # Differential mode: base + delta
        r1_5 = (word1 >> 27) & 0x1F
        dr = _sign_extend_3bit((word1 >> 24) & 0x7)
        g1_5 = (word1 >> 19) & 0x1F
        dg = _sign_extend_3bit((word1 >> 16) & 0x7)
        b1_5 = (word1 >> 11) & 0x1F
        db = _sign_extend_3bit((word1 >> 8) & 0x7)

        r1 = _expand_5to8(r1_5)
        g1 = _expand_5to8(g1_5)
        b1 = _expand_5to8(b1_5)

        r2_5 = r1_5 + dr
        g2_5 = g1_5 + dg
        b2_5 = b1_5 + db

        # Clamp to [0, 31] before expanding
        r2 = _expand_5to8(max(0, min(31, r2_5)))
        g2 = _expand_5to8(max(0, min(31, g2_5)))
        b2 = _expand_5to8(max(0, min(31, b2_5)))

    table_idx1 = (word1 >> 5) & 0x7
    table_idx2 = (word1 >> 2) & 0x7

    base_colors = [(r1, g1, b1), (r2, g2, b2)]
    table_indices = [table_idx1, table_idx2]

    result = np.zeros((4, 4, 3), dtype=np.uint8)

    for py in range(4):
        for px in range(4):
            # Determine sub-block
            if flip_bit == 0:
                # Vertical split: left 2 cols = sub1, right 2 cols = sub2
                sub = 0 if px < 2 else 1
            else:
                # Horizontal split: top 2 rows = sub1, bottom 2 rows = sub2
                sub = 0 if py < 2 else 1

            base_r, base_g, base_b = base_colors[sub]
            table_idx = table_indices[sub]
            modifiers = ETC1_MODIFIER_TABLE[table_idx]

            # Get pixel index bits
            # The pixel index for pixel at (px, py) in the 4x4 block:
            # Bit position in the 32-bit word2:
            # MSB: bit (px * 4 + py + 16) from LSB of word2
            # LSB: bit (px * 4 + py) from LSB of word2
            bit_pos = px * 4 + py
            msb = (word2 >> (bit_pos + 16)) & 1
            lsb = (word2 >> bit_pos) & 1

            # Determine modifier value (per Khronos ETC1 spec table)
            idx = (msb << 1) | lsb
            if idx == 0:
                modifier = modifiers[0]   # +a (small positive)
            elif idx == 1:
                modifier = modifiers[1]   # +b (large positive)
            elif idx == 2:
                modifier = -modifiers[0]  # -a (small negative)
            else:
                modifier = -modifiers[1]  # -b (large negative)

            result[py, px, 0] = _clamp(base_r + modifier)
            result[py, px, 1] = _clamp(base_g + modifier)
            result[py, px, 2] = _clamp(base_b + modifier)

    return result


def _iterate_blocks_morton(width: int, height: int):
    """
    Yield (block_x, block_y) in 3DS PICA200 Morton order.

    The GPU tiles textures in 8x8-pixel macro-tiles. For ETC1 (4x4 blocks),
    each macro-tile contains 2x2 blocks in Z-order within it.
    Macro-tiles are arranged left-to-right, top-to-bottom.

    Z-order within a 2x2 group: (0,0), (1,0), (0,1), (1,1)
    """
    block_w = (width + 3) // 4
    block_h = (height + 3) // 4
    # Macro-tiles are 2x2 blocks (8x8 pixels)
    macro_w = (block_w + 1) // 2
    macro_h = (block_h + 1) // 2

    for macro_y in range(macro_h):
        for macro_x in range(macro_w):
            # Z-order within the 2x2 block group
            for sub in [(0, 0), (1, 0), (0, 1), (1, 1)]:
                bx = macro_x * 2 + sub[0]
                by = macro_y * 2 + sub[1]
                if bx < block_w and by < block_h:
                    yield bx, by


def decode_etc1(data: bytes, width: int, height: int) -> np.ndarray:
    """
    Decode an ETC1 compressed texture.
    Returns an RGBA8 numpy array (height x width x 4).

    Blocks are in 3DS Morton order (8x8-pixel macro-tiles with Z-order).
    """
    output = np.zeros((height, width, 4), dtype=np.uint8)
    output[:, :, 3] = 255  # Full alpha

    offset = 0
    for bx, by in _iterate_blocks_morton(width, height):
        if offset + 8 > len(data):
            break

        block_rgb = decode_etc1_block(data[offset:offset + 8])
        offset += 8

        # Copy block to output
        for py in range(4):
            for px in range(4):
                out_x = bx * 4 + px
                out_y = by * 4 + py
                if out_x < width and out_y < height:
                    output[out_y, out_x, 0:3] = block_rgb[py, px]

    return output


def decode_etc1a4(data: bytes, width: int, height: int) -> np.ndarray:
    """
    Decode an ETC1A4 compressed texture.
    Each 4x4 block is 16 bytes: 8 bytes alpha (4-bit per pixel) + 8 bytes ETC1 color.
    Returns an RGBA8 numpy array (height x width x 4).

    Blocks are in 3DS Morton order (8x8-pixel macro-tiles with Z-order).
    """
    output = np.zeros((height, width, 4), dtype=np.uint8)

    offset = 0
    for bx, by in _iterate_blocks_morton(width, height):
        if offset + 16 > len(data):
            break

        # First 8 bytes: 4-bit alpha values (16 pixels = 8 bytes)
        alpha_data = data[offset:offset + 8]
        offset += 8

        # Next 8 bytes: ETC1 color block
        if offset + 8 > len(data):
            break
        block_rgb = decode_etc1_block(data[offset:offset + 8])
        offset += 8

        # Read alpha as little-endian u64 for nibble indexing
        alpha_u64 = int.from_bytes(alpha_data, 'little')

        # Decode alpha and combine
        for py in range(4):
            for px in range(4):
                out_x = bx * 4 + px
                out_y = by * 4 + py
                if out_x < width and out_y < height:
                    output[out_y, out_x, 0:3] = block_rgb[py, px]

                    # Alpha: 4 bits per pixel, column-major order (x*4+y)
                    # per PICA200 hardware (confirmed by Citra/Azahar)
                    alpha_idx = px * 4 + py
                    alpha_val = (alpha_u64 >> (alpha_idx * 4)) & 0xF
                    output[out_y, out_x, 3] = (alpha_val << 4) | alpha_val

    return output
