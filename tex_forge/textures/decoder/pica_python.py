"""Pure-Python PICA200 pixel decoder -- correctness-first fallback.

Used when the vectorised numpy decoder bails out:
  * tiny textures (W or H < 4) where morton tables don't tile cleanly
  * edge-case shapes that hit a NumPy reshape mismatch
  * environments without a working numpy install (extremely rare)

Slow but obviously correct. Don't optimise this -- if you want speed, fix
pica_numpy. This file's value is its readability when debugging mismatched
output between v1 and v2.

Same format references as pica_numpy.py.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from tex_forge.textures.formats import PicaFormat, resolve
from tex_forge.textures.morton import MORTON_TABLE


# Pre-compute inverse morton table once.
_INV_MORTON = [(0, 0)] * 64
for _ly in range(8):
    for _lx in range(8):
        _INV_MORTON[MORTON_TABLE[_ly * 8 + _lx]] = (_lx, _ly)


# ─────────────────────────────────────────────────────────────────────────────
# Per-pixel decoders
# ─────────────────────────────────────────────────────────────────────────────

def _px_rgba8(data: bytes, off: int):
    if off + 4 > len(data):
        return (0, 0, 0, 0)
    a, b, g, r = data[off], data[off + 1], data[off + 2], data[off + 3]
    return (r, g, b, a)


def _px_rgb8(data: bytes, off: int):
    if off + 3 > len(data):
        return (0, 0, 0, 255)
    b, g, r = data[off], data[off + 1], data[off + 2]
    return (r, g, b, 255)


def _px_rgba5551(data: bytes, off: int):
    if off + 2 > len(data):
        return (0, 0, 0, 0)
    v = data[off] | (data[off + 1] << 8)
    r5 = (v >> 11) & 0x1F
    g5 = (v >> 6) & 0x1F
    b5 = (v >> 1) & 0x1F
    a1 = v & 1
    return (
        (r5 << 3) | (r5 >> 2),
        (g5 << 3) | (g5 >> 2),
        (b5 << 3) | (b5 >> 2),
        a1 * 255,
    )


def _px_rgb565(data: bytes, off: int):
    if off + 2 > len(data):
        return (0, 0, 0, 255)
    v = data[off] | (data[off + 1] << 8)
    r5 = (v >> 11) & 0x1F
    g6 = (v >> 5) & 0x3F
    b5 = v & 0x1F
    return (
        (r5 << 3) | (r5 >> 2),
        (g6 << 2) | (g6 >> 4),
        (b5 << 3) | (b5 >> 2),
        255,
    )


def _px_rgba4(data: bytes, off: int):
    if off + 2 > len(data):
        return (0, 0, 0, 0)
    v = data[off] | (data[off + 1] << 8)
    r4 = (v >> 12) & 0xF
    g4 = (v >> 8) & 0xF
    b4 = (v >> 4) & 0xF
    a4 = v & 0xF
    return ((r4 << 4) | r4, (g4 << 4) | g4, (b4 << 4) | b4, (a4 << 4) | a4)


def _px_la8(data: bytes, off: int):
    if off + 2 > len(data):
        return (0, 0, 0, 0)
    a, l = data[off], data[off + 1]
    return (l, l, l, a)


def _px_hilo8(data: bytes, off: int):
    if off + 2 > len(data):
        return (0, 0, 255, 255)
    return (data[off], data[off + 1], 255, 255)


def _px_l8(data: bytes, off: int):
    if off + 1 > len(data):
        return (0, 0, 0, 255)
    l = data[off]
    return (l, l, l, 255)


def _px_a8(data: bytes, off: int):
    if off + 1 > len(data):
        return (255, 255, 255, 0)
    return (255, 255, 255, data[off])


def _px_la4(data: bytes, off: int):
    if off + 1 > len(data):
        return (0, 0, 0, 0)
    v = data[off]
    a4 = v & 0xF
    l4 = (v >> 4) & 0xF
    return ((l4 << 4) | l4, (l4 << 4) | l4, (l4 << 4) | l4, (a4 << 4) | a4)


_PIXEL_DECODERS = {
    PicaFormat.RGBA8:    (_px_rgba8,    4),
    PicaFormat.RGB8:     (_px_rgb8,     3),
    PicaFormat.RGBA5551: (_px_rgba5551, 2),
    PicaFormat.RGB565:   (_px_rgb565,   2),
    PicaFormat.RGBA4:    (_px_rgba4,    2),
    PicaFormat.LA8:      (_px_la8,      2),
    PicaFormat.HILO8:    (_px_hilo8,    2),
    PicaFormat.L8:       (_px_l8,       1),
    PicaFormat.A8:       (_px_a8,       1),
    PicaFormat.LA4:      (_px_la4,      1),
}


# ─────────────────────────────────────────────────────────────────────────────
# 4-bpp packed (L4 / A4): two pixels per byte, even=low nibble, odd=high.
# ─────────────────────────────────────────────────────────────────────────────

def _decode_4bpp(data: bytes, width: int, height: int, is_alpha: bool) -> np.ndarray:
    out = np.zeros((height, width, 4), dtype=np.uint8)
    tiles_x = (width + 7) // 8
    tiles_y = (height + 7) // 8
    pixel_index = 0
    for ty in range(tiles_y):
        for tx in range(tiles_x):
            for m in range(64):
                lx, ly = _INV_MORTON[m]
                px = tx * 8 + lx
                py = ty * 8 + ly
                byte_off = pixel_index >> 1
                if byte_off < len(data):
                    nb = (data[byte_off] >> 4) & 0xF if (pixel_index & 1) else data[byte_off] & 0xF
                    val = (nb << 4) | nb
                    if px < width and py < height:
                        if is_alpha:
                            out[py, px] = (255, 255, 255, val)
                        else:
                            out[py, px] = (val, val, val, 255)
                pixel_index += 1
    return out


# ─────────────────────────────────────────────────────────────────────────────
# ETC1 / ETC1A4 scalar fallback (delegates to a tiny block decoder)
# ─────────────────────────────────────────────────────────────────────────────

_ETC1_MOD_PY = (
    (2, 8), (5, 17), (9, 29), (13, 42),
    (18, 60), (24, 80), (33, 106), (47, 183),
)


def _clamp(v: int) -> int:
    return 0 if v < 0 else 255 if v > 255 else v


def _decode_etc1_block_rgb(block: bytes) -> list:
    """Decode 8 bytes -> 16 RGB tuples in (px, py) order. Returns flat list[16]."""
    u64 = int.from_bytes(block[:8], "little")
    word1 = (u64 >> 32) & 0xFFFFFFFF
    word2 = u64 & 0xFFFFFFFF
    diff = (word1 >> 1) & 1
    flip = word1 & 1

    if diff == 0:
        r1, g1, b1 = ((word1 >> 28) & 0xF) * 17, ((word1 >> 20) & 0xF) * 17, ((word1 >> 12) & 0xF) * 17
        r2, g2, b2 = ((word1 >> 24) & 0xF) * 17, ((word1 >> 16) & 0xF) * 17, ((word1 >>  8) & 0xF) * 17
    else:
        r1_5, g1_5, b1_5 = (word1 >> 27) & 0x1F, (word1 >> 19) & 0x1F, (word1 >> 11) & 0x1F
        dr, dg, db = (word1 >> 24) & 0x7, (word1 >> 16) & 0x7, (word1 >> 8) & 0x7
        if dr >= 4: dr -= 8
        if dg >= 4: dg -= 8
        if db >= 4: db -= 8
        r1, g1, b1 = (r1_5 << 3) | (r1_5 >> 2), (g1_5 << 3) | (g1_5 >> 2), (b1_5 << 3) | (b1_5 >> 2)
        r2_5 = max(0, min(31, r1_5 + dr))
        g2_5 = max(0, min(31, g1_5 + dg))
        b2_5 = max(0, min(31, b1_5 + db))
        r2, g2, b2 = (r2_5 << 3) | (r2_5 >> 2), (g2_5 << 3) | (g2_5 >> 2), (b2_5 << 3) | (b2_5 >> 2)

    t1 = (word1 >> 5) & 0x7
    t2 = (word1 >> 2) & 0x7

    out = [(0, 0, 0)] * 16
    for j in range(16):
        px, py = j >> 2, j & 3
        sub = (1 if px >= 2 else 0) if flip == 0 else (1 if py >= 2 else 0)
        if sub == 0:
            br, bg, bb, t = r1, g1, b1, t1
        else:
            br, bg, bb, t = r2, g2, b2, t2
        small, large = _ETC1_MOD_PY[t]
        msb = (word2 >> (j + 16)) & 1
        lsb = (word2 >> j) & 1
        idx = (msb << 1) | lsb
        if idx == 0:
            mod = small
        elif idx == 1:
            mod = large
        elif idx == 2:
            mod = -small
        else:
            mod = -large
        out[j] = (_clamp(br + mod), _clamp(bg + mod), _clamp(bb + mod))
    return out


def _iter_etc_blocks(width: int, height: int):
    block_w = (width + 3) // 4
    block_h = (height + 3) // 4
    macro_w = (block_w + 1) // 2
    macro_h = (block_h + 1) // 2
    for my in range(macro_h):
        for mx in range(macro_w):
            for sub_x, sub_y in ((0, 0), (1, 0), (0, 1), (1, 1)):
                bx = mx * 2 + sub_x
                by = my * 2 + sub_y
                if bx < block_w and by < block_h:
                    yield bx, by


def _decode_etc1(data: bytes, width: int, height: int) -> np.ndarray:
    out = np.zeros((height, width, 4), dtype=np.uint8)
    out[:, :, 3] = 255
    off = 0
    for bx, by in _iter_etc_blocks(width, height):
        if off + 8 > len(data):
            break
        rgbs = _decode_etc1_block_rgb(data[off:off + 8])
        off += 8
        for j, (r, g, b) in enumerate(rgbs):
            px, py = j >> 2, j & 3
            ox, oy = bx * 4 + px, by * 4 + py
            if ox < width and oy < height:
                out[oy, ox, 0:3] = (r, g, b)
    return out


def _decode_etc1a4(data: bytes, width: int, height: int) -> np.ndarray:
    out = np.zeros((height, width, 4), dtype=np.uint8)
    off = 0
    for bx, by in _iter_etc_blocks(width, height):
        if off + 16 > len(data):
            break
        alpha_u64 = int.from_bytes(data[off:off + 8], "little")
        rgbs = _decode_etc1_block_rgb(data[off + 8:off + 16])
        off += 16
        for j, (r, g, b) in enumerate(rgbs):
            px, py = j >> 2, j & 3
            ox, oy = bx * 4 + px, by * 4 + py
            if ox < width and oy < height:
                a4 = (alpha_u64 >> (j * 4)) & 0xF
                out[oy, ox] = (r, g, b, (a4 << 4) | a4)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Public dispatch
# ─────────────────────────────────────────────────────────────────────────────

def decode_python(data: bytes, width: int, height: int, fmt: int) -> Optional[np.ndarray]:
    f = resolve(fmt)
    if f is None or width <= 0 or height <= 0:
        return None
    if f == PicaFormat.ETC1:
        return _decode_etc1(data, width, height)
    if f == PicaFormat.ETC1A4:
        return _decode_etc1a4(data, width, height)
    if f in (PicaFormat.L4, PicaFormat.A4):
        return _decode_4bpp(data, width, height, f == PicaFormat.A4)

    spec = _PIXEL_DECODERS.get(f)
    if spec is None:
        return None
    pix_fn, bpp = spec

    out = np.zeros((height, width, 4), dtype=np.uint8)
    tiles_x = (width + 7) // 8
    tiles_y = (height + 7) // 8
    off = 0
    data_len = len(data)
    for ty in range(tiles_y):
        for tx in range(tiles_x):
            for m in range(64):
                lx, ly = _INV_MORTON[m]
                px = tx * 8 + lx
                py = ty * 8 + ly
                if off + bpp <= data_len and px < width and py < height:
                    out[py, px] = pix_fn(data, off)
                off += bpp
    return out
