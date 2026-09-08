"""Morton (Z-order) de-tiling tables for PICA200 textures.

The 3DS GPU stores all uncompressed textures in 8x8 pixel *tiles*, with the
pixels inside each tile arranged in a Z-order curve so that 2x2 neighbours
land on consecutive cache lines. ETC1 / ETC1A4 use a coarser 2x2-of-4x4
macro-tile pattern.

Both layouts are documented:
  - https://www.3dbrew.org/wiki/GPU/External_Registers
  - http://problemkaputt.de/gbatek-3ds-video-texture-swizzling.htm
  - https://github.com/devkitPro/citro3d  (source of truth: see texture.c)

We only ever need the *inverse* tables: "given the i-th byte in the encoded
stream, where does it land in the (y, x) output?" -- which is what the
NumPy decoders use for fancy-indexed scatter writes.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Tuple

import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# 8x8 tile, per-pixel morton order
#
# MORTON_TABLE[y * 8 + x] = sequential read-order index for pixel (x, y).
# It interleaves the bits:  morton(x,y) = y0 x0 y1 x1 y2 x2.
#
# Validation lives in tests/test_morton.py.
# ─────────────────────────────────────────────────────────────────────────────

MORTON_TABLE: tuple[int, ...] = (
     0,  1,  4,  5, 16, 17, 20, 21,
     2,  3,  6,  7, 18, 19, 22, 23,
     8,  9, 12, 13, 24, 25, 28, 29,
    10, 11, 14, 15, 26, 27, 30, 31,
    32, 33, 36, 37, 48, 49, 52, 53,
    34, 35, 38, 39, 50, 51, 54, 55,
    40, 41, 44, 45, 56, 57, 60, 61,
    42, 43, 46, 47, 58, 59, 62, 63,
)

# Inverse: INV_MORTON[i] = (lx, ly) for sequential index i in [0,64)
INV_MORTON_X = np.zeros(64, dtype=np.int32)
INV_MORTON_Y = np.zeros(64, dtype=np.int32)
for _ly in range(8):
    for _lx in range(8):
        _seq = MORTON_TABLE[_ly * 8 + _lx]
        INV_MORTON_X[_seq] = _lx
        INV_MORTON_Y[_seq] = _ly


# ─────────────────────────────────────────────────────────────────────────────
# Whole-texture scatter map (cached -- one entry per (W, H) ever seen)
# ─────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=512)
def scatter_map(width: int, height: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (dst_y, dst_x, src_idx) arrays mapping encoded pixels to output coords.

    The decoder reads N raw pixels (one per byte/u16/u32 unit) and uses these
    arrays to fancy-index-write them into the (height, width, 4) output.

    For non-power-of-two textures we drop pixels whose dst would land outside
    the visible region -- the GPU still reads padded full-tile data but we
    don't put it in the output image.
    """
    tiles_x = (width + 7) // 8
    tiles_y = (height + 7) // 8
    total = tiles_x * tiles_y * 64

    k = np.arange(total, dtype=np.int32)
    tile_idx = k >> 6        # k // 64
    morton_idx = k & 63      # k %  64

    tile_x = tile_idx % tiles_x
    tile_y = tile_idx // tiles_x

    dst_x = tile_x * 8 + INV_MORTON_X[morton_idx]
    dst_y = tile_y * 8 + INV_MORTON_Y[morton_idx]

    valid = (dst_x < width) & (dst_y < height)
    return dst_y[valid], dst_x[valid], k[valid]


# ─────────────────────────────────────────────────────────────────────────────
# ETC1 macro-tile order: 2x2 macro-tiles of 4x4 blocks, in Z-order within macro.
# ─────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=128)
def etc1_block_order(width: int, height: int) -> Tuple[np.ndarray, np.ndarray]:
    """Return (block_x, block_y) arrays for each 4x4 ETC1 block in PICA macro-tile order.

    Macro-tiles are 2x2 blocks (8x8 pixels). Within each macro the Z-order
    is (0,0), (1,0), (0,1), (1,1). Macros are emitted left-to-right then
    top-to-bottom.
    """
    block_w = (width + 3) >> 2     # ceil(W / 4)
    block_h = (height + 3) >> 2    # ceil(H / 4)
    macro_w = (block_w + 1) >> 1   # ceil(block_w / 2)
    macro_h = (block_h + 1) >> 1

    sub_bx = np.array([0, 1, 0, 1], dtype=np.int32)
    sub_by = np.array([0, 0, 1, 1], dtype=np.int32)

    my = np.arange(macro_h, dtype=np.int32)
    mx = np.arange(macro_w, dtype=np.int32)
    MY, MX = np.meshgrid(my, mx, indexing="ij")

    bx = (MX[:, :, None] * 2 + sub_bx[None, None, :]).ravel()
    by = (MY[:, :, None] * 2 + sub_by[None, None, :]).ravel()

    valid = (bx < block_w) & (by < block_h)
    return bx[valid], by[valid]
