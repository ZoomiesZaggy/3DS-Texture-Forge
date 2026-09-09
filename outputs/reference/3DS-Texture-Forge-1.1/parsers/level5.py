"""Level-5 compression and IMGC texture format for 3DS.

Level-5 uses a custom compression header (u32 LE):
  method = val & 7  (0=none, 1=LZ10, 2=Huffman4, 3=Huffman8, 4=RLE)
  decompressed_size = val >> 3

Used by Yo-Kai Watch, Professor Layton, Fantasy Life, etc.
"""

import struct
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

IMGC_MAGIC = b'IMGC'

# IMGC format field -> PICA200 format
IMGC_FORMAT_MAP = {
    0: 0x00,   # RGBA8
    1: 0x01,   # RGB8
    2: 0x02,   # RGBA5551
    3: 0x03,   # RGB565
    4: 0x04,   # RGBA4
    5: 0x05,   # LA8
    7: 0x07,   # L8
    8: 0x08,   # A8
    9: 0x09,   # LA4
    10: 0x0A,  # L4
    11: 0x0B,  # A4
    12: 0x0C,  # ETC1
    13: 0x0D,  # ETC1A4
}


def decompress_l5(data: bytes) -> Optional[bytes]:
    """Decompress Level-5 compressed data.

    Reads the 4-byte header to determine method and output size,
    then dispatches to the appropriate decompressor.
    """
    if len(data) < 8:
        return None
    val = struct.unpack_from('<I', data, 0)[0]
    method = val & 7
    dec_size = val >> 3
    if dec_size == 0 or dec_size > 32 * 1024 * 1024:
        return None

    if method == 0:
        return data[4:4 + dec_size]
    elif method == 1:
        return _decompress_lz10(data[4:], dec_size)
    elif method == 2:
        return _decompress_huffman(data[4:], dec_size, bits=4)
    elif method == 3:
        return _decompress_huffman(data[4:], dec_size, bits=8)
    elif method == 4:
        return _decompress_rle(data[4:], dec_size)
    return None


def _decompress_lz10(data: bytes, dec_size: int) -> Optional[bytes]:
    """Level-5 / Nintendo LZ10 decompression."""
    out = bytearray()
    pos = 0
    try:
        while len(out) < dec_size and pos < len(data):
            flags = data[pos]
            pos += 1
            for bit in range(8):
                if len(out) >= dec_size:
                    break
                if flags & (0x80 >> bit):
                    if pos + 1 >= len(data):
                        return bytes(out[:dec_size]) if out else None
                    b0 = data[pos]
                    b1 = data[pos + 1]
                    pos += 2
                    length = (b0 >> 4) + 3
                    disp = ((b0 & 0x0F) << 8) | b1
                    for _ in range(length):
                        if len(out) >= dec_size:
                            break
                        idx = len(out) - disp - 1
                        out.append(out[idx] if 0 <= idx < len(out) else 0)
                else:
                    if pos >= len(data):
                        return bytes(out[:dec_size]) if out else None
                    out.append(data[pos])
                    pos += 1
    except Exception:
        pass
    return bytes(out[:dec_size]) if len(out) >= dec_size // 2 else None


def _decompress_huffman(data: bytes, dec_size: int, bits: int = 4) -> Optional[bytes]:
    """Nintendo/Level-5 Huffman decompression (4-bit or 8-bit).

    Standard Nintendo format: tree_size byte, tree data, then u32-LE bitstream.
    """
    if len(data) < 5:
        return None

    tree_size_declared = ((data[0] & 0xFF) + 1) * 2  # tree data in bytes
    tree_start = 1
    # Bitstream starts after tree, aligned to 4 bytes from start of compressed data
    # Use declared size for alignment, but allow tree reads beyond it
    # (leaf values can be stored past the node area in Nintendo Huffman)
    bitstream_off = (tree_start + tree_size_declared + 3) & ~3
    # The tree can extend up to the bitstream start
    tree_end = bitstream_off
    if bitstream_off >= len(data):
        return None

    # Build output
    out = bytearray()
    bit_pos = 0
    data_len = len(data)

    def read_bit():
        nonlocal bit_pos
        word_idx = bit_pos >> 5
        byte_off = bitstream_off + word_idx * 4
        if byte_off + 4 > data_len:
            bit_pos += 1
            return 0
        word = struct.unpack_from('<I', data, byte_off)[0]
        bit_in_word = 31 - (bit_pos & 31)
        bit_pos += 1
        return (word >> bit_in_word) & 1

    def decode_symbol():
        """Walk tree from root, return leaf value."""
        # Root is at tree[tree_start]
        node_off = tree_start  # byte offset in data[]
        for _ in range(64):
            if node_off >= tree_end:
                return None
            node = data[node_off]
            child_rel = node & 0x3F
            # Child pair base: relative offset in bytes from aligned position
            child_base = ((node_off - tree_start) & ~1) + tree_start + child_rel + 2

            b = read_bit()
            if b == 0:
                # Left
                if node & 0x80:  # left is leaf
                    return data[child_base] if child_base < tree_end else None
                node_off = child_base
            else:
                # Right
                if node & 0x40:  # right is leaf
                    return data[child_base + 1] if child_base + 1 < tree_end else None
                node_off = child_base + 1
        return None

    try:
        if bits == 4:
            while len(out) < dec_size:
                lo = decode_symbol()
                hi = decode_symbol()
                if lo is None or hi is None:
                    break
                out.append(((hi & 0xF) << 4) | (lo & 0xF))
        else:
            while len(out) < dec_size:
                val = decode_symbol()
                if val is None:
                    break
                out.append(val & 0xFF)
    except Exception:
        pass

    return bytes(out[:dec_size]) if len(out) >= dec_size // 2 else None


def _decompress_rle(data: bytes, dec_size: int) -> Optional[bytes]:
    """Nintendo/Level-5 RLE decompression."""
    out = bytearray()
    pos = 0
    try:
        while len(out) < dec_size and pos < len(data):
            flag = data[pos]
            pos += 1
            if flag & 0x80:
                # Compressed run: repeat next byte (flag & 0x7F) + 3 times
                length = (flag & 0x7F) + 3
                if pos >= len(data):
                    break
                val = data[pos]
                pos += 1
                out.extend([val] * length)
            else:
                # Literal run: copy (flag & 0x7F) + 1 bytes
                length = (flag & 0x7F) + 1
                out.extend(data[pos:pos + length])
                pos += length
    except Exception:
        pass
    return bytes(out[:dec_size]) if len(out) >= dec_size // 2 else None


def is_imgc(data: bytes) -> bool:
    """Check if data starts with IMGC magic."""
    return len(data) >= 0x48 and data[:4] == IMGC_MAGIC


def parse_imgc(data: bytes) -> List[Dict[str, Any]]:
    """Parse an IMGC tiled texture.

    IMGC uses a tile-based system:
      1. Tile map: array of u16 tile indices (0xFFFF = empty)
      2. Tile pixel data: unique 8x8 tile pixel data in PICA200 format

    Header (0x48 bytes):
      +0x00: magic 'IMGC'
      +0x10: width (u16), height (u16)
      +0x20: format (u32) — PICA200 enum
      +0x34: compressed tile-map size (u32)
      +0x38: compressed pixel-data size (u32)
      +0x3C: total compressed data size (u32)
      +0x48: [tile-map blob][pixel-data blob] — both Level-5 compressed

    Returns list with one texture dict, or empty list.
    """
    if not is_imgc(data):
        return []

    try:
        width = struct.unpack_from('<H', data, 0x10)[0]
        height = struct.unpack_from('<H', data, 0x12)[0]
        fmt_code = struct.unpack_from('<I', data, 0x20)[0]
        comp_tilemap_sz = struct.unpack_from('<I', data, 0x34)[0]
        comp_pixel_sz = struct.unpack_from('<I', data, 0x38)[0]
        total_comp_sz = struct.unpack_from('<I', data, 0x3C)[0]
    except struct.error:
        return []

    if width == 0 or height == 0 or width > 2048 or height > 2048:
        return []

    pica_fmt = IMGC_FORMAT_MAP.get(fmt_code)
    if pica_fmt is None:
        return []

    from textures.decoder import FORMAT_BPP
    bpp = FORMAT_BPP.get(pica_fmt, 0)
    if bpp == 0:
        return []

    tile_w, tile_h = 8, 8
    tiles_x = (width + tile_w - 1) // tile_w
    tiles_y = (height + tile_h - 1) // tile_h
    tile_byte_size = tile_w * tile_h * bpp // 8

    # Decompress tile map
    tilemap_blob = data[0x48:0x48 + comp_tilemap_sz + 16]
    tile_map_raw = decompress_l5(tilemap_blob)
    if tile_map_raw is None:
        return []

    # Tile map is array of u16 indices
    num_tiles = tiles_x * tiles_y
    tile_indices = []
    for i in range(min(num_tiles, len(tile_map_raw) // 2)):
        idx = struct.unpack_from('<H', tile_map_raw, i * 2)[0]
        tile_indices.append(idx)

    # Decompress pixel data (tile palette)
    pixel_blob = data[0x48 + comp_tilemap_sz:0x48 + total_comp_sz + 16]
    tile_pixels = decompress_l5(pixel_blob)
    if tile_pixels is None:
        return []

    # Reconstruct full pixel data by placing tiles
    full_pixel_data = bytearray(tiles_x * tile_w * tiles_y * tile_h * bpp // 8)

    for ty in range(tiles_y):
        for tx in range(tiles_x):
            tile_idx_pos = ty * tiles_x + tx
            if tile_idx_pos >= len(tile_indices):
                continue
            tile_idx = tile_indices[tile_idx_pos]
            if tile_idx == 0xFFFF:
                continue  # empty tile

            src_off = tile_idx * tile_byte_size
            if src_off + tile_byte_size > len(tile_pixels):
                continue

            # Copy tile data row by row into the full image
            # PICA200 tiles are already in morton order within 8x8 blocks,
            # so we just need to place each tile's bytes at the right position
            # in the linear tile stream (tiles are sequential in the output)
            dst_tile_idx = ty * tiles_x + tx
            dst_off = dst_tile_idx * tile_byte_size
            if dst_off + tile_byte_size <= len(full_pixel_data):
                full_pixel_data[dst_off:dst_off + tile_byte_size] = \
                    tile_pixels[src_off:src_off + tile_byte_size]

    return [{
        "width": tiles_x * tile_w,  # may be padded to tile boundary
        "height": tiles_y * tile_h,
        "format": pica_fmt,
        "data": bytes(full_pixel_data),
        "name": f"imgc_{width}x{height}",
        "mip_count": 1,
    }]
