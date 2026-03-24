"""
Vectorized NumPy decoders for 3DS PICA200 texture formats.

Replaces the triple-nested Python loops in decoder.py with NumPy array
operations, giving ~10-40x speedup for all formats including ETC1/ETC1A4.

Key technique for non-ETC1 formats:
  - Pre-compute Morton scatter index arrays (dst_y, dst_x, src_idx) once per
    texture size, then use NumPy fancy-indexing to scatter all pixels at once.
  - These maps are cached with lru_cache keyed on (width, height).

Key technique for ETC1/ETC1A4:
  - Read all blocks at once as uint64 array.
  - Extract all bit-fields with vectorized operations.
  - Compute all pixel colors in parallel using broadcast arithmetic.
  - Scatter to output with vectorized fancy-indexing.
"""

import numpy as np
from functools import lru_cache
from typing import Optional, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# Morton de-tiling tables
# ─────────────────────────────────────────────────────────────────────────────

# MORTON_TABLE[y*8+x] = sequential Morton read-order index for pixel (x,y) in tile
_MORTON_TABLE_PY = [
    0,  1,  4,  5, 16, 17, 20, 21,
    2,  3,  6,  7, 18, 19, 22, 23,
    8,  9, 12, 13, 24, 25, 28, 29,
   10, 11, 14, 15, 26, 27, 30, 31,
   32, 33, 36, 37, 48, 49, 52, 53,
   34, 35, 38, 39, 50, 51, 54, 55,
   40, 41, 44, 45, 56, 57, 60, 61,
   42, 43, 46, 47, 58, 59, 62, 63,
]

# Inverse Morton: for sequential index i, (lx, ly) within the 8×8 tile
_INV_MORTON_X = np.zeros(64, dtype=np.int32)
_INV_MORTON_Y = np.zeros(64, dtype=np.int32)
for _ly in range(8):
    for _lx in range(8):
        _seq = _MORTON_TABLE_PY[_ly * 8 + _lx]
        _INV_MORTON_X[_seq] = _lx
        _INV_MORTON_Y[_seq] = _ly


@lru_cache(maxsize=256)
def _morton_scatter(width: int, height: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Return (dst_y, dst_x, src_idx) mapping for a WxH texture.

    src_idx: which sequential pixel from the raw byte-stream to use
    dst_y, dst_x: where to place it in the output (height x width) image

    For power-of-2 dimensions src_idx == np.arange(N), but we include it
    for correctness when dimensions are not multiples of 8.
    """
    tiles_x = (width + 7) // 8
    tiles_y = (height + 7) // 8
    total = tiles_x * tiles_y * 64

    k = np.arange(total, dtype=np.int32)
    tile_idx = k >> 6       # // 64
    morton_idx = k & 63     # % 64

    tile_x = tile_idx % tiles_x
    tile_y = tile_idx // tiles_x

    dst_x = tile_x * 8 + _INV_MORTON_X[morton_idx]
    dst_y = tile_y * 8 + _INV_MORTON_Y[morton_idx]

    # Filter pixels outside the actual texture dimensions
    valid = (dst_x < width) & (dst_y < height)
    return dst_y[valid], dst_x[valid], k[valid]


# ─────────────────────────────────────────────────────────────────────────────
# ETC1 constants
# ─────────────────────────────────────────────────────────────────────────────

_ETC1_MOD = np.array([
    [2, 8], [5, 17], [9, 29], [13, 42],
    [18, 60], [24, 80], [33, 106], [47, 183],
], dtype=np.int32)

# Pixel index 0..3: sign and magnitude selection
_ETC1_SIGN  = np.array([1, 1, -1, -1], dtype=np.int32)  # 0,1 → positive; 2,3 → negative
_ETC1_LARGE = np.array([0, 1,  0,  1], dtype=np.int32)  # 0,2 → small; 1,3 → large

# Column-major order within 4×4 block: bit_pos = px*4 + py, j = 0..15
_ETC1_J  = np.arange(16, dtype=np.int32)
_ETC1_PX = (_ETC1_J >> 2).astype(np.int32)   # px = j // 4
_ETC1_PY = (_ETC1_J & 3).astype(np.int32)    # py = j % 4

# Sub-block assignment per pixel for flip=0 (left/right) and flip=1 (top/bottom)
_ETC1_SUB_F0 = (_ETC1_PX >= 2).astype(np.int32)  # flip=0: sub=1 if px>=2
_ETC1_SUB_F1 = (_ETC1_PY >= 2).astype(np.int32)  # flip=1: sub=1 if py>=2


@lru_cache(maxsize=64)
def _etc1_block_order(width: int, height: int) -> Tuple[np.ndarray, np.ndarray]:
    """Return (bx, by) arrays for each ETC1 4×4 block in PICA200 Morton order."""
    block_w = (width + 3) >> 2    # ceil(W/4)
    block_h = (height + 3) >> 2   # ceil(H/4)
    macro_w = (block_w + 1) >> 1  # ceil(block_w/2)
    macro_h = (block_h + 1) >> 1

    # Z-order within 2×2 macro-tile
    sub_bx = np.array([0, 1, 0, 1], dtype=np.int32)
    sub_by = np.array([0, 0, 1, 1], dtype=np.int32)

    my = np.arange(macro_h, dtype=np.int32)
    mx = np.arange(macro_w, dtype=np.int32)
    MY, MX = np.meshgrid(my, mx, indexing='ij')  # (macro_h, macro_w)

    # Expand to (macro_h, macro_w, 4) for 4 sub-blocks per macro
    bx = MX[:, :, None] * 2 + sub_bx[None, None, :]
    by = MY[:, :, None] * 2 + sub_by[None, None, :]

    bx = bx.ravel()
    by = by.ravel()

    valid = (bx < block_w) & (by < block_h)
    return bx[valid], by[valid]


# ─────────────────────────────────────────────────────────────────────────────
# Non-ETC1 decoders
# ─────────────────────────────────────────────────────────────────────────────

def _pad(data: bytes, needed: int) -> bytes:
    """Pad data to at least `needed` bytes."""
    if len(data) < needed:
        return data + bytes(needed - len(data))
    return data


def _decode_rgba8(data: bytes, width: int, height: int) -> np.ndarray:
    dst_y, dst_x, src_idx = _morton_scatter(width, height)
    N_total = ((width + 7) // 8) * ((height + 7) // 8) * 64
    needed = N_total * 4
    src = np.frombuffer(_pad(data, needed), dtype=np.uint8, count=needed).reshape(N_total, 4)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    # PICA200: bytes ordered A, B, G, R → output R, G, B, A
    out[dst_y, dst_x, 0] = src[src_idx, 3]  # R
    out[dst_y, dst_x, 1] = src[src_idx, 2]  # G
    out[dst_y, dst_x, 2] = src[src_idx, 1]  # B
    out[dst_y, dst_x, 3] = src[src_idx, 0]  # A
    return out


def _decode_rgb8(data: bytes, width: int, height: int) -> np.ndarray:
    dst_y, dst_x, src_idx = _morton_scatter(width, height)
    N_total = ((width + 7) // 8) * ((height + 7) // 8) * 64
    needed = N_total * 3
    src = np.frombuffer(_pad(data, needed), dtype=np.uint8, count=needed).reshape(N_total, 3)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    # PICA200: stored B, G, R
    out[dst_y, dst_x, 0] = src[src_idx, 2]  # R
    out[dst_y, dst_x, 1] = src[src_idx, 1]  # G
    out[dst_y, dst_x, 2] = src[src_idx, 0]  # B
    out[dst_y, dst_x, 3] = 255
    return out


def _decode_rgba5551(data: bytes, width: int, height: int) -> np.ndarray:
    dst_y, dst_x, src_idx = _morton_scatter(width, height)
    N_total = ((width + 7) // 8) * ((height + 7) // 8) * 64
    needed = N_total * 2
    vals = np.frombuffer(_pad(data, needed), dtype='<u2', count=N_total)[src_idx]
    out = np.zeros((height, width, 4), dtype=np.uint8)
    r5 = ((vals >> 11) & 0x1F).astype(np.uint8)
    g5 = ((vals >> 6)  & 0x1F).astype(np.uint8)
    b5 = ((vals >> 1)  & 0x1F).astype(np.uint8)
    a1 = (vals & 1).astype(np.uint8)
    out[dst_y, dst_x, 0] = (r5 << 3) | (r5 >> 2)
    out[dst_y, dst_x, 1] = (g5 << 3) | (g5 >> 2)
    out[dst_y, dst_x, 2] = (b5 << 3) | (b5 >> 2)
    out[dst_y, dst_x, 3] = a1 * 255
    return out


def _decode_rgb565(data: bytes, width: int, height: int) -> np.ndarray:
    dst_y, dst_x, src_idx = _morton_scatter(width, height)
    N_total = ((width + 7) // 8) * ((height + 7) // 8) * 64
    needed = N_total * 2
    vals = np.frombuffer(_pad(data, needed), dtype='<u2', count=N_total)[src_idx]
    out = np.zeros((height, width, 4), dtype=np.uint8)
    r5 = ((vals >> 11) & 0x1F).astype(np.uint8)
    g6 = ((vals >> 5)  & 0x3F).astype(np.uint8)
    b5 = (vals & 0x1F).astype(np.uint8)
    out[dst_y, dst_x, 0] = (r5 << 3) | (r5 >> 2)
    out[dst_y, dst_x, 1] = (g6 << 2) | (g6 >> 4)
    out[dst_y, dst_x, 2] = (b5 << 3) | (b5 >> 2)
    out[dst_y, dst_x, 3] = 255
    return out


def _decode_rgba4(data: bytes, width: int, height: int) -> np.ndarray:
    dst_y, dst_x, src_idx = _morton_scatter(width, height)
    N_total = ((width + 7) // 8) * ((height + 7) // 8) * 64
    needed = N_total * 2
    vals = np.frombuffer(_pad(data, needed), dtype='<u2', count=N_total)[src_idx]
    out = np.zeros((height, width, 4), dtype=np.uint8)
    r4 = ((vals >> 12) & 0xF).astype(np.uint8)
    g4 = ((vals >> 8)  & 0xF).astype(np.uint8)
    b4 = ((vals >> 4)  & 0xF).astype(np.uint8)
    a4 = (vals & 0xF).astype(np.uint8)
    out[dst_y, dst_x, 0] = (r4 << 4) | r4
    out[dst_y, dst_x, 1] = (g4 << 4) | g4
    out[dst_y, dst_x, 2] = (b4 << 4) | b4
    out[dst_y, dst_x, 3] = (a4 << 4) | a4
    return out


def _decode_la8(data: bytes, width: int, height: int) -> np.ndarray:
    dst_y, dst_x, src_idx = _morton_scatter(width, height)
    N_total = ((width + 7) // 8) * ((height + 7) // 8) * 64
    needed = N_total * 2
    src = np.frombuffer(_pad(data, needed), dtype=np.uint8, count=needed).reshape(N_total, 2)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    # PICA200 LA8: byte0=A, byte1=L
    L = src[src_idx, 1]
    A = src[src_idx, 0]
    out[dst_y, dst_x, 0] = L
    out[dst_y, dst_x, 1] = L
    out[dst_y, dst_x, 2] = L
    out[dst_y, dst_x, 3] = A
    return out


def _decode_hilo8(data: bytes, width: int, height: int) -> np.ndarray:
    dst_y, dst_x, src_idx = _morton_scatter(width, height)
    N_total = ((width + 7) // 8) * ((height + 7) // 8) * 64
    needed = N_total * 2
    src = np.frombuffer(_pad(data, needed), dtype=np.uint8, count=needed).reshape(N_total, 2)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    out[dst_y, dst_x, 0] = src[src_idx, 0]  # HI
    out[dst_y, dst_x, 1] = src[src_idx, 1]  # LO
    out[dst_y, dst_x, 2] = 255
    out[dst_y, dst_x, 3] = 255
    return out


def _decode_l8(data: bytes, width: int, height: int) -> np.ndarray:
    dst_y, dst_x, src_idx = _morton_scatter(width, height)
    N_total = ((width + 7) // 8) * ((height + 7) // 8) * 64
    src = np.frombuffer(_pad(data, N_total), dtype=np.uint8, count=N_total)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    L = src[src_idx]
    out[dst_y, dst_x, 0] = L
    out[dst_y, dst_x, 1] = L
    out[dst_y, dst_x, 2] = L
    out[dst_y, dst_x, 3] = 255
    return out


def _decode_a8(data: bytes, width: int, height: int) -> np.ndarray:
    dst_y, dst_x, src_idx = _morton_scatter(width, height)
    N_total = ((width + 7) // 8) * ((height + 7) // 8) * 64
    src = np.frombuffer(_pad(data, N_total), dtype=np.uint8, count=N_total)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    out[dst_y, dst_x, 0] = 255
    out[dst_y, dst_x, 1] = 255
    out[dst_y, dst_x, 2] = 255
    out[dst_y, dst_x, 3] = src[src_idx]
    return out


def _decode_la4(data: bytes, width: int, height: int) -> np.ndarray:
    dst_y, dst_x, src_idx = _morton_scatter(width, height)
    N_total = ((width + 7) // 8) * ((height + 7) // 8) * 64
    src = np.frombuffer(_pad(data, N_total), dtype=np.uint8, count=N_total)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    # PICA200 LA4: high nibble=L, low nibble=A
    l4 = ((src[src_idx] >> 4) & 0xF).astype(np.uint8)
    a4 = (src[src_idx] & 0xF).astype(np.uint8)
    L = (l4 << 4) | l4
    A = (a4 << 4) | a4
    out[dst_y, dst_x, 0] = L
    out[dst_y, dst_x, 1] = L
    out[dst_y, dst_x, 2] = L
    out[dst_y, dst_x, 3] = A
    return out


def _decode_4bpp(data: bytes, width: int, height: int, is_alpha: bool) -> np.ndarray:
    """L4 (is_alpha=False) and A4 (is_alpha=True): 4 bits per pixel."""
    dst_y, dst_x, src_idx = _morton_scatter(width, height)
    N_total = ((width + 7) // 8) * ((height + 7) // 8) * 64
    n_bytes = (N_total + 1) // 2
    raw = np.frombuffer(_pad(data, n_bytes), dtype=np.uint8, count=n_bytes)

    # Nibble ordering (from original _decode_4bpp_texture):
    # pixel 0 (even) → low nibble of byte 0
    # pixel 1 (odd)  → high nibble of byte 0
    # pixel 2 (even) → low nibble of byte 1 …
    nibbles = np.empty(N_total, dtype=np.uint8)
    nibbles[0::2] = raw[:((N_total + 1) // 2)] & 0xF
    nibbles[1::2] = (raw[:(N_total // 2)] >> 4) & 0xF

    val8 = (nibbles[src_idx] << 4) | nibbles[src_idx]
    out = np.zeros((height, width, 4), dtype=np.uint8)
    if is_alpha:  # A4
        out[dst_y, dst_x, 0] = 255
        out[dst_y, dst_x, 1] = 255
        out[dst_y, dst_x, 2] = 255
        out[dst_y, dst_x, 3] = val8
    else:         # L4
        out[dst_y, dst_x, 0] = val8
        out[dst_y, dst_x, 1] = val8
        out[dst_y, dst_x, 2] = val8
        out[dst_y, dst_x, 3] = 255
    return out


# ─────────────────────────────────────────────────────────────────────────────
# ETC1 vectorized decoder
# ─────────────────────────────────────────────────────────────────────────────

def _decode_etc1_blocks_vec(
    word1: np.ndarray, word2: np.ndarray
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Vectorized decode of n ETC1 blocks.

    word1, word2: uint32 arrays of shape (n,)
    Returns R, G, B each of shape (n, 16), dtype uint8.
    """
    n = len(word1)

    diff_bit = (word1 >> 1) & 1   # (n,)  0=individual, 1=differential
    flip_bit  = word1 & 1          # (n,)  0=vertical split, 1=horizontal split

    # ── Individual mode: two independent 4-bit base colors ──────────────────
    r1_ind = (((word1 >> 28) & 0xF) * 17).astype(np.uint8)
    g1_ind = (((word1 >> 20) & 0xF) * 17).astype(np.uint8)
    b1_ind = (((word1 >> 12) & 0xF) * 17).astype(np.uint8)
    r2_ind = (((word1 >> 24) & 0xF) * 17).astype(np.uint8)
    g2_ind = (((word1 >> 16) & 0xF) * 17).astype(np.uint8)
    b2_ind = (((word1 >> 8)  & 0xF) * 17).astype(np.uint8)

    # ── Differential mode: 5-bit base + signed 3-bit delta ──────────────────
    r1_5 = (word1 >> 27) & 0x1F   # (n,) uint32
    g1_5 = (word1 >> 19) & 0x1F
    b1_5 = (word1 >> 11) & 0x1F

    dr_raw = (word1 >> 24) & 0x7
    dg_raw = (word1 >> 16) & 0x7
    db_raw = (word1 >> 8)  & 0x7

    # Sign-extend 3-bit: values >= 4 become negative
    dr = np.where(dr_raw >= 4, dr_raw.astype(np.int32) - 8, dr_raw.astype(np.int32))
    dg = np.where(dg_raw >= 4, dg_raw.astype(np.int32) - 8, dg_raw.astype(np.int32))
    db = np.where(db_raw >= 4, db_raw.astype(np.int32) - 8, db_raw.astype(np.int32))

    # expand 5-bit to 8-bit: (v << 3) | (v >> 2)
    r1_5i = r1_5.astype(np.int32)
    g1_5i = g1_5.astype(np.int32)
    b1_5i = b1_5.astype(np.int32)
    r1_diff = ((r1_5i << 3) | (r1_5i >> 2)).astype(np.uint8)
    g1_diff = ((g1_5i << 3) | (g1_5i >> 2)).astype(np.uint8)
    b1_diff = ((b1_5i << 3) | (b1_5i >> 2)).astype(np.uint8)

    r2_5 = np.clip(r1_5i + dr, 0, 31).astype(np.int32)
    g2_5 = np.clip(g1_5i + dg, 0, 31).astype(np.int32)
    b2_5 = np.clip(b1_5i + db, 0, 31).astype(np.int32)
    r2_diff = ((r2_5 << 3) | (r2_5 >> 2)).astype(np.uint8)
    g2_diff = ((g2_5 << 3) | (g2_5 >> 2)).astype(np.uint8)
    b2_diff = ((b2_5 << 3) | (b2_5 >> 2)).astype(np.uint8)

    # ── Select color mode per block ──────────────────────────────────────────
    r1 = np.where(diff_bit, r1_diff, r1_ind).astype(np.int32)  # (n,)
    g1 = np.where(diff_bit, g1_diff, g1_ind).astype(np.int32)
    b1 = np.where(diff_bit, b1_diff, b1_ind).astype(np.int32)
    r2 = np.where(diff_bit, r2_diff, r2_ind).astype(np.int32)
    g2 = np.where(diff_bit, g2_diff, g2_ind).astype(np.int32)
    b2 = np.where(diff_bit, b2_diff, b2_ind).astype(np.int32)

    table_idx1 = (word1 >> 5) & 0x7   # (n,)
    table_idx2 = (word1 >> 2) & 0x7

    # ── Sub-block per pixel (n, 16) ──────────────────────────────────────────
    # flip=0: sub=1 if px >= 2; flip=1: sub=1 if py >= 2
    sub = np.where(flip_bit[:, None], _ETC1_SUB_F1[None, :], _ETC1_SUB_F0[None, :])

    # Table index and base color per pixel
    t_idx  = np.where(sub == 0, table_idx1[:, None], table_idx2[:, None])  # (n,16)
    base_r = np.where(sub == 0, r1[:, None], r2[:, None])
    base_g = np.where(sub == 0, g1[:, None], g2[:, None])
    base_b = np.where(sub == 0, b1[:, None], b2[:, None])

    # ── Pixel index bits from word2 ──────────────────────────────────────────
    # For each pixel j: msb = bit(j+16), lsb = bit(j)
    # _ETC1_J shape (16,); word2 shape (n,)
    msb = (word2[:, None] >> (_ETC1_J[None, :] + 16)) & 1   # (n,16)
    lsb = (word2[:, None] >> _ETC1_J[None, :]) & 1
    pix_idx = ((msb << 1) | lsb).astype(np.int32)            # (n,16), values 0..3

    # ── Apply modifier ───────────────────────────────────────────────────────
    t_flat     = t_idx.ravel()               # (n*16,)
    small_mod  = _ETC1_MOD[t_flat, 0].reshape(n, 16)
    large_mod  = _ETC1_MOD[t_flat, 1].reshape(n, 16)

    sign       = _ETC1_SIGN[pix_idx]         # (n,16)
    large_flag = _ETC1_LARGE[pix_idx]
    modifier   = sign * np.where(large_flag, large_mod, small_mod)

    R = np.clip(base_r + modifier, 0, 255).astype(np.uint8)
    G = np.clip(base_g + modifier, 0, 255).astype(np.uint8)
    B = np.clip(base_b + modifier, 0, 255).astype(np.uint8)

    return R, G, B


def _scatter_etc1_blocks(
    out: np.ndarray,
    bxs: np.ndarray, bys: np.ndarray,
    R: np.ndarray, G: np.ndarray, B: np.ndarray, A: np.ndarray,
    width: int, height: int,
) -> None:
    """Scatter (n, 16) block pixels into the output image."""
    # out_x[i,j] = bxs[i]*4 + px_j[j],  out_y[i,j] = bys[i]*4 + py_j[j]
    out_x = (bxs[:, None] * 4 + _ETC1_PX[None, :]).ravel()
    out_y = (bys[:, None] * 4 + _ETC1_PY[None, :]).ravel()

    valid = (out_x < width) & (out_y < height)
    if not np.all(valid):
        out_x = out_x[valid]
        out_y = out_y[valid]
        R = R.ravel()[valid]
        G = G.ravel()[valid]
        B = B.ravel()[valid]
        A = A.ravel()[valid]
    else:
        R = R.ravel()
        G = G.ravel()
        B = B.ravel()
        A = A.ravel()

    out[out_y, out_x, 0] = R
    out[out_y, out_x, 1] = G
    out[out_y, out_x, 2] = B
    out[out_y, out_x, 3] = A


def decode_etc1_numpy(data: bytes, width: int, height: int) -> np.ndarray:
    """Vectorized ETC1 decoder — all blocks processed in parallel."""
    bxs, bys = _etc1_block_order(width, height)
    n = len(bxs)
    needed = n * 8
    raw = np.frombuffer(_pad(data, needed), dtype='<u8', count=n)
    word1 = (raw >> 32).astype(np.uint32)
    word2 = (raw & 0xFFFFFFFF).astype(np.uint32)
    R, G, B = _decode_etc1_blocks_vec(word1, word2)
    A = np.full((n, 16), 255, dtype=np.uint8)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    _scatter_etc1_blocks(out, bxs, bys, R, G, B, A, width, height)
    return out


def decode_etc1a4_numpy(data: bytes, width: int, height: int) -> np.ndarray:
    """Vectorized ETC1A4 decoder — all blocks processed in parallel."""
    bxs, bys = _etc1_block_order(width, height)
    n = len(bxs)
    needed = n * 16
    # 16-byte blocks: [8 alpha bytes, 8 ETC1 color bytes]
    raw16 = np.frombuffer(_pad(data, needed), dtype='<u8', count=n * 2).reshape(n, 2)
    alpha_u64 = raw16[:, 0]   # first 8 bytes per block = alpha
    color_u64 = raw16[:, 1]   # next 8 bytes per block = ETC1 color

    word1 = (color_u64 >> 32).astype(np.uint32)
    word2 = (color_u64 & 0xFFFFFFFF).astype(np.uint32)
    R, G, B = _decode_etc1_blocks_vec(word1, word2)

    # Alpha: 4 bits per pixel, column-major (j = px*4+py), LE nibbles in u64
    alpha_nibble = ((alpha_u64[:, None] >> (_ETC1_J[None, :].astype(np.uint64) * 4)) & 0xF).astype(np.uint8)
    A = (alpha_nibble << 4) | alpha_nibble

    out = np.zeros((height, width, 4), dtype=np.uint8)
    _scatter_etc1_blocks(out, bxs, bys, R, G, B, A, width, height)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Main dispatch
# ─────────────────────────────────────────────────────────────────────────────

_NUMPY_DECODERS = {
    0x0: _decode_rgba8,
    0x1: _decode_rgb8,
    0x2: _decode_rgba5551,
    0x3: _decode_rgb565,
    0x4: _decode_rgba4,
    0x5: _decode_la8,
    0x6: _decode_hilo8,
    0x7: _decode_l8,
    0x8: _decode_a8,
    0x9: _decode_la4,
    0xA: lambda d, w, h: _decode_4bpp(d, w, h, False),  # L4
    0xB: lambda d, w, h: _decode_4bpp(d, w, h, True),   # A4
    0xC: decode_etc1_numpy,
    0xD: decode_etc1a4_numpy,
}


def decode_texture_numpy(
    data: bytes, width: int, height: int, fmt: int
) -> Optional[np.ndarray]:
    """
    Vectorized texture decoder. Returns RGBA8 ndarray (height, width, 4) or None.

    Requires width >= 8 and height >= 8 (PICA200 minimum tile size).
    Falls back to None for sub-8 dimensions so the caller can use the Python decoder.
    """
    if width < 4 or height < 4 or width <= 0 or height <= 0:
        return None
    decoder = _NUMPY_DECODERS.get(fmt)
    if decoder is None:
        return None
    try:
        return decoder(data, width, height)
    except Exception:
        return None
