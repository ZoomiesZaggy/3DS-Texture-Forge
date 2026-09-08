"""Vectorised PICA200 pixel decoders.

For each non-ETC format we precompute a Morton scatter map (cached per W,H),
read the encoded bytes as a flat ndarray, and use NumPy fancy-indexing to
write the decoded pixels into the output image in one shot. This is roughly
20-40x faster than the per-pixel loops in pica_python.

For ETC1 / ETC1A4 we vectorise across blocks: read all blocks as uint64 and
extract the bit-fields in parallel.

Reference for the format internals:
  - PICA200 register format: https://www.3dbrew.org/wiki/GPU/Internal_Registers
  - GBATEK swizzling docs:   http://problemkaputt.de/gbatek-3ds-video-texture-swizzling.htm
  - citro3d source:          https://github.com/devkitPro/citro3d/blob/master/source/texture.c
  - ETC1 spec (Khronos):     https://registry.khronos.org/OpenGL/extensions/OES/OES_compressed_ETC1_RGB8_texture.txt
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from tex_forge.textures.formats import PicaFormat, resolve
from tex_forge.textures.morton import scatter_map, etc1_block_order


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _pad(data: bytes, needed: int) -> bytes:
    """Right-pad with zeros so we can frombuffer a known size without bounds checks."""
    if len(data) < needed:
        return data + bytes(needed - len(data))
    return data


def _N_total(width: int, height: int) -> int:
    return ((width + 7) // 8) * ((height + 7) // 8) * 64


# ─────────────────────────────────────────────────────────────────────────────
# Non-ETC pixel formats -- one function per format
# ─────────────────────────────────────────────────────────────────────────────

def _decode_rgba8(data: bytes, width: int, height: int) -> np.ndarray:
    dst_y, dst_x, src_idx = scatter_map(width, height)
    N = _N_total(width, height)
    src = np.frombuffer(_pad(data, N * 4), dtype=np.uint8, count=N * 4).reshape(N, 4)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    # Stored A,B,G,R -> output R,G,B,A
    out[dst_y, dst_x, 0] = src[src_idx, 3]
    out[dst_y, dst_x, 1] = src[src_idx, 2]
    out[dst_y, dst_x, 2] = src[src_idx, 1]
    out[dst_y, dst_x, 3] = src[src_idx, 0]
    return out


def _decode_rgb8(data: bytes, width: int, height: int) -> np.ndarray:
    dst_y, dst_x, src_idx = scatter_map(width, height)
    N = _N_total(width, height)
    src = np.frombuffer(_pad(data, N * 3), dtype=np.uint8, count=N * 3).reshape(N, 3)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    # Stored B,G,R
    out[dst_y, dst_x, 0] = src[src_idx, 2]
    out[dst_y, dst_x, 1] = src[src_idx, 1]
    out[dst_y, dst_x, 2] = src[src_idx, 0]
    out[dst_y, dst_x, 3] = 255
    return out


def _decode_rgba5551(data: bytes, width: int, height: int) -> np.ndarray:
    dst_y, dst_x, src_idx = scatter_map(width, height)
    N = _N_total(width, height)
    vals = np.frombuffer(_pad(data, N * 2), dtype="<u2", count=N)[src_idx]
    out = np.zeros((height, width, 4), dtype=np.uint8)
    r5 = ((vals >> 11) & 0x1F).astype(np.uint8)
    g5 = ((vals >> 6) & 0x1F).astype(np.uint8)
    b5 = ((vals >> 1) & 0x1F).astype(np.uint8)
    a1 = (vals & 1).astype(np.uint8)
    out[dst_y, dst_x, 0] = (r5 << 3) | (r5 >> 2)
    out[dst_y, dst_x, 1] = (g5 << 3) | (g5 >> 2)
    out[dst_y, dst_x, 2] = (b5 << 3) | (b5 >> 2)
    out[dst_y, dst_x, 3] = a1 * 255
    return out


def _decode_rgb565(data: bytes, width: int, height: int) -> np.ndarray:
    dst_y, dst_x, src_idx = scatter_map(width, height)
    N = _N_total(width, height)
    vals = np.frombuffer(_pad(data, N * 2), dtype="<u2", count=N)[src_idx]
    out = np.zeros((height, width, 4), dtype=np.uint8)
    r5 = ((vals >> 11) & 0x1F).astype(np.uint8)
    g6 = ((vals >> 5) & 0x3F).astype(np.uint8)
    b5 = (vals & 0x1F).astype(np.uint8)
    out[dst_y, dst_x, 0] = (r5 << 3) | (r5 >> 2)
    out[dst_y, dst_x, 1] = (g6 << 2) | (g6 >> 4)
    out[dst_y, dst_x, 2] = (b5 << 3) | (b5 >> 2)
    out[dst_y, dst_x, 3] = 255
    return out


def _decode_rgba4(data: bytes, width: int, height: int) -> np.ndarray:
    dst_y, dst_x, src_idx = scatter_map(width, height)
    N = _N_total(width, height)
    vals = np.frombuffer(_pad(data, N * 2), dtype="<u2", count=N)[src_idx]
    out = np.zeros((height, width, 4), dtype=np.uint8)
    r4 = ((vals >> 12) & 0xF).astype(np.uint8)
    g4 = ((vals >> 8) & 0xF).astype(np.uint8)
    b4 = ((vals >> 4) & 0xF).astype(np.uint8)
    a4 = (vals & 0xF).astype(np.uint8)
    out[dst_y, dst_x, 0] = (r4 << 4) | r4
    out[dst_y, dst_x, 1] = (g4 << 4) | g4
    out[dst_y, dst_x, 2] = (b4 << 4) | b4
    out[dst_y, dst_x, 3] = (a4 << 4) | a4
    return out


def _decode_la8(data: bytes, width: int, height: int) -> np.ndarray:
    dst_y, dst_x, src_idx = scatter_map(width, height)
    N = _N_total(width, height)
    src = np.frombuffer(_pad(data, N * 2), dtype=np.uint8, count=N * 2).reshape(N, 2)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    A = src[src_idx, 0]
    L = src[src_idx, 1]
    out[dst_y, dst_x, 0] = L
    out[dst_y, dst_x, 1] = L
    out[dst_y, dst_x, 2] = L
    out[dst_y, dst_x, 3] = A
    return out


def _decode_hilo8(data: bytes, width: int, height: int) -> np.ndarray:
    """HILO8 normal map: two channels are tangent-space xy, blue/alpha forced to 255."""
    dst_y, dst_x, src_idx = scatter_map(width, height)
    N = _N_total(width, height)
    src = np.frombuffer(_pad(data, N * 2), dtype=np.uint8, count=N * 2).reshape(N, 2)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    out[dst_y, dst_x, 0] = src[src_idx, 0]
    out[dst_y, dst_x, 1] = src[src_idx, 1]
    out[dst_y, dst_x, 2] = 255
    out[dst_y, dst_x, 3] = 255
    return out


def _decode_l8(data: bytes, width: int, height: int) -> np.ndarray:
    dst_y, dst_x, src_idx = scatter_map(width, height)
    N = _N_total(width, height)
    src = np.frombuffer(_pad(data, N), dtype=np.uint8, count=N)
    L = src[src_idx]
    out = np.zeros((height, width, 4), dtype=np.uint8)
    out[dst_y, dst_x, 0] = L
    out[dst_y, dst_x, 1] = L
    out[dst_y, dst_x, 2] = L
    out[dst_y, dst_x, 3] = 255
    return out


def _decode_a8(data: bytes, width: int, height: int) -> np.ndarray:
    dst_y, dst_x, src_idx = scatter_map(width, height)
    N = _N_total(width, height)
    src = np.frombuffer(_pad(data, N), dtype=np.uint8, count=N)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    out[dst_y, dst_x, 0] = 255
    out[dst_y, dst_x, 1] = 255
    out[dst_y, dst_x, 2] = 255
    out[dst_y, dst_x, 3] = src[src_idx]
    return out


def _decode_la4(data: bytes, width: int, height: int) -> np.ndarray:
    dst_y, dst_x, src_idx = scatter_map(width, height)
    N = _N_total(width, height)
    src = np.frombuffer(_pad(data, N), dtype=np.uint8, count=N)
    l4 = ((src[src_idx] >> 4) & 0xF).astype(np.uint8)
    a4 = (src[src_idx] & 0xF).astype(np.uint8)
    L = (l4 << 4) | l4
    A = (a4 << 4) | a4
    out = np.zeros((height, width, 4), dtype=np.uint8)
    out[dst_y, dst_x, 0] = L
    out[dst_y, dst_x, 1] = L
    out[dst_y, dst_x, 2] = L
    out[dst_y, dst_x, 3] = A
    return out


def _decode_4bpp(data: bytes, width: int, height: int, is_alpha: bool) -> np.ndarray:
    """L4 (is_alpha=False) and A4 (is_alpha=True): two pixels per byte.

    Even sequential pixels go in the LOW nibble, odd in the high nibble. The
    even/odd here refers to the *Morton* sequential index, not the (x,y)
    coordinate -- so we lay nibbles out in sequential order then scatter.
    """
    dst_y, dst_x, src_idx = scatter_map(width, height)
    N = _N_total(width, height)
    n_bytes = (N + 1) // 2
    raw = np.frombuffer(_pad(data, n_bytes), dtype=np.uint8, count=n_bytes)

    nibbles = np.empty(N, dtype=np.uint8)
    nibbles[0::2] = raw[: ((N + 1) // 2)] & 0xF
    nibbles[1::2] = (raw[: (N // 2)] >> 4) & 0xF

    val8 = (nibbles[src_idx] << 4) | nibbles[src_idx]
    out = np.zeros((height, width, 4), dtype=np.uint8)
    if is_alpha:
        out[dst_y, dst_x, 0] = 255
        out[dst_y, dst_x, 1] = 255
        out[dst_y, dst_x, 2] = 255
        out[dst_y, dst_x, 3] = val8
    else:
        out[dst_y, dst_x, 0] = val8
        out[dst_y, dst_x, 1] = val8
        out[dst_y, dst_x, 2] = val8
        out[dst_y, dst_x, 3] = 255
    return out


# ─────────────────────────────────────────────────────────────────────────────
# ETC1 vectorised decoder -- all blocks decoded in parallel
#
# Reference: Khronos OES_compressed_ETC1_RGB8_texture (modulation tables come
# from there). 3DS twist: each 8-byte block is read as a *little-endian* u64
# rather than big-endian, and 4x4 blocks are arranged in 2x2 macro-tiles in
# Z-order rather than scanline order.
# ─────────────────────────────────────────────────────────────────────────────

# ETC1 modulation table: index -> (small_mag, large_mag)
_ETC1_MOD = np.array([
    [2, 8], [5, 17], [9, 29], [13, 42],
    [18, 60], [24, 80], [33, 106], [47, 183],
], dtype=np.int32)

# pix_idx in [0..3]: 0=+small, 1=+large, 2=-small, 3=-large
_ETC1_SIGN  = np.array([1, 1, -1, -1], dtype=np.int32)
_ETC1_LARGE = np.array([0, 1,  0,  1], dtype=np.int32)

# Within each 4x4 block, j in [0..16); pixel coords (px, py).
# Bit position for pixel index = px*4 + py  (column-major).
_ETC1_J  = np.arange(16, dtype=np.int32)
_ETC1_PX = (_ETC1_J >> 2).astype(np.int32)   # px = j // 4
_ETC1_PY = (_ETC1_J & 3).astype(np.int32)    # py = j  % 4

# Sub-block selection per pixel:
#   flip=0 -> vertical split: left two columns are sub0, right two are sub1
#   flip=1 -> horizontal split: top two rows are sub0, bottom two are sub1
_ETC1_SUB_F0 = (_ETC1_PX >= 2).astype(np.int32)
_ETC1_SUB_F1 = (_ETC1_PY >= 2).astype(np.int32)


def _decode_etc1_blocks(word1: np.ndarray, word2: np.ndarray):
    """Vectorised decode of N ETC1 blocks. Returns (R, G, B) shape (N, 16) uint8."""
    n = len(word1)

    diff_bit = (word1 >> 1) & 1
    flip_bit = word1 & 1

    # Individual mode: two 4-bit base colors, each expanded x17 to 8 bits.
    r1_ind = (((word1 >> 28) & 0xF) * 17).astype(np.uint8)
    g1_ind = (((word1 >> 20) & 0xF) * 17).astype(np.uint8)
    b1_ind = (((word1 >> 12) & 0xF) * 17).astype(np.uint8)
    r2_ind = (((word1 >> 24) & 0xF) * 17).astype(np.uint8)
    g2_ind = (((word1 >> 16) & 0xF) * 17).astype(np.uint8)
    b2_ind = (((word1 >>  8) & 0xF) * 17).astype(np.uint8)

    # Differential mode: 5-bit base + 3-bit signed delta.
    r1_5 = (word1 >> 27) & 0x1F
    g1_5 = (word1 >> 19) & 0x1F
    b1_5 = (word1 >> 11) & 0x1F
    dr_raw = (word1 >> 24) & 0x7
    dg_raw = (word1 >> 16) & 0x7
    db_raw = (word1 >>  8) & 0x7
    dr = np.where(dr_raw >= 4, dr_raw.astype(np.int32) - 8, dr_raw.astype(np.int32))
    dg = np.where(dg_raw >= 4, dg_raw.astype(np.int32) - 8, dg_raw.astype(np.int32))
    db = np.where(db_raw >= 4, db_raw.astype(np.int32) - 8, db_raw.astype(np.int32))

    # 5-bit -> 8-bit: (v << 3) | (v >> 2)
    r1_5i = r1_5.astype(np.int32); g1_5i = g1_5.astype(np.int32); b1_5i = b1_5.astype(np.int32)
    r1_diff = ((r1_5i << 3) | (r1_5i >> 2)).astype(np.uint8)
    g1_diff = ((g1_5i << 3) | (g1_5i >> 2)).astype(np.uint8)
    b1_diff = ((b1_5i << 3) | (b1_5i >> 2)).astype(np.uint8)
    r2_5 = np.clip(r1_5i + dr, 0, 31).astype(np.int32)
    g2_5 = np.clip(g1_5i + dg, 0, 31).astype(np.int32)
    b2_5 = np.clip(b1_5i + db, 0, 31).astype(np.int32)
    r2_diff = ((r2_5 << 3) | (r2_5 >> 2)).astype(np.uint8)
    g2_diff = ((g2_5 << 3) | (g2_5 >> 2)).astype(np.uint8)
    b2_diff = ((b2_5 << 3) | (b2_5 >> 2)).astype(np.uint8)

    # Pick per-block color mode.
    r1 = np.where(diff_bit, r1_diff, r1_ind).astype(np.int32)
    g1 = np.where(diff_bit, g1_diff, g1_ind).astype(np.int32)
    b1 = np.where(diff_bit, b1_diff, b1_ind).astype(np.int32)
    r2 = np.where(diff_bit, r2_diff, r2_ind).astype(np.int32)
    g2 = np.where(diff_bit, g2_diff, g2_ind).astype(np.int32)
    b2 = np.where(diff_bit, b2_diff, b2_ind).astype(np.int32)

    table_idx1 = (word1 >> 5) & 0x7
    table_idx2 = (word1 >> 2) & 0x7

    # Per-pixel sub-block selection (n, 16).
    sub = np.where(flip_bit[:, None], _ETC1_SUB_F1[None, :], _ETC1_SUB_F0[None, :])
    t_idx  = np.where(sub == 0, table_idx1[:, None], table_idx2[:, None])
    base_r = np.where(sub == 0, r1[:, None], r2[:, None])
    base_g = np.where(sub == 0, g1[:, None], g2[:, None])
    base_b = np.where(sub == 0, b1[:, None], b2[:, None])

    # Pixel index bits: msb at word2[j+16], lsb at word2[j].
    msb = (word2[:, None] >> (_ETC1_J[None, :] + 16)) & 1
    lsb = (word2[:, None] >>  _ETC1_J[None, :]) & 1
    pix_idx = ((msb << 1) | lsb).astype(np.int32)

    t_flat    = t_idx.ravel()
    small_mod = _ETC1_MOD[t_flat, 0].reshape(n, 16)
    large_mod = _ETC1_MOD[t_flat, 1].reshape(n, 16)
    sign       = _ETC1_SIGN[pix_idx]
    large_flag = _ETC1_LARGE[pix_idx]
    modifier   = sign * np.where(large_flag, large_mod, small_mod)

    R = np.clip(base_r + modifier, 0, 255).astype(np.uint8)
    G = np.clip(base_g + modifier, 0, 255).astype(np.uint8)
    B = np.clip(base_b + modifier, 0, 255).astype(np.uint8)
    return R, G, B


def _scatter_blocks(out: np.ndarray, bxs: np.ndarray, bys: np.ndarray,
                    R: np.ndarray, G: np.ndarray, B: np.ndarray, A: np.ndarray,
                    width: int, height: int) -> None:
    """Place (n, 16) per-block decoded colors into the output image at (bxs*4, bys*4)."""
    out_x = (bxs[:, None] * 4 + _ETC1_PX[None, :]).ravel()
    out_y = (bys[:, None] * 4 + _ETC1_PY[None, :]).ravel()
    R = R.ravel(); G = G.ravel(); B = B.ravel(); A = A.ravel()

    valid = (out_x < width) & (out_y < height)
    if not np.all(valid):
        out_x = out_x[valid]; out_y = out_y[valid]
        R = R[valid]; G = G[valid]; B = B[valid]; A = A[valid]

    out[out_y, out_x, 0] = R
    out[out_y, out_x, 1] = G
    out[out_y, out_x, 2] = B
    out[out_y, out_x, 3] = A


def _decode_etc1(data: bytes, width: int, height: int) -> np.ndarray:
    bxs, bys = etc1_block_order(width, height)
    n = len(bxs)
    raw = np.frombuffer(_pad(data, n * 8), dtype="<u8", count=n)
    word1 = (raw >> 32).astype(np.uint32)
    word2 = (raw & 0xFFFFFFFF).astype(np.uint32)
    R, G, B = _decode_etc1_blocks(word1, word2)
    A = np.full((n, 16), 255, dtype=np.uint8)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    _scatter_blocks(out, bxs, bys, R, G, B, A, width, height)
    return out


def _decode_etc1a4(data: bytes, width: int, height: int) -> np.ndarray:
    bxs, bys = etc1_block_order(width, height)
    n = len(bxs)
    raw16 = np.frombuffer(_pad(data, n * 16), dtype="<u8", count=n * 2).reshape(n, 2)
    alpha_u64 = raw16[:, 0]
    color_u64 = raw16[:, 1]

    word1 = (color_u64 >> 32).astype(np.uint32)
    word2 = (color_u64 & 0xFFFFFFFF).astype(np.uint32)
    R, G, B = _decode_etc1_blocks(word1, word2)

    # Alpha is 4 bits per pixel, column-major (j = px*4 + py), packed into LE u64.
    alpha_nibble = ((alpha_u64[:, None] >> (_ETC1_J[None, :].astype(np.uint64) * 4)) & 0xF).astype(np.uint8)
    A = (alpha_nibble << 4) | alpha_nibble

    out = np.zeros((height, width, 4), dtype=np.uint8)
    _scatter_blocks(out, bxs, bys, R, G, B, A, width, height)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Public dispatch
# ─────────────────────────────────────────────────────────────────────────────

_NUMPY_DECODERS = {
    PicaFormat.RGBA8:    _decode_rgba8,
    PicaFormat.RGB8:     _decode_rgb8,
    PicaFormat.RGBA5551: _decode_rgba5551,
    PicaFormat.RGB565:   _decode_rgb565,
    PicaFormat.RGBA4:    _decode_rgba4,
    PicaFormat.LA8:      _decode_la8,
    PicaFormat.HILO8:    _decode_hilo8,
    PicaFormat.L8:       _decode_l8,
    PicaFormat.A8:       _decode_a8,
    PicaFormat.LA4:      _decode_la4,
    PicaFormat.L4:       lambda d, w, h: _decode_4bpp(d, w, h, False),
    PicaFormat.A4:       lambda d, w, h: _decode_4bpp(d, w, h, True),
    PicaFormat.ETC1:     _decode_etc1,
    PicaFormat.ETC1A4:   _decode_etc1a4,
}


def decode_numpy(data: bytes, width: int, height: int, fmt: int) -> Optional[np.ndarray]:
    """Decode a PICA200 texture using the vectorised path. Returns None on failure.

    Tiny textures (W or H < 4) hit edge cases in the morton scatter map -- the
    pure-python fallback handles those.
    """
    if width < 4 or height < 4:
        return None
    f = resolve(fmt)
    if f is None:
        return None
    decoder = _NUMPY_DECODERS.get(f)
    if decoder is None:
        return None
    try:
        return decoder(data, width, height)
    except Exception:
        return None
