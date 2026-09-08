"""PICA200 GPU texture format catalogue -- the single source of truth.

Replaces the scattered FMT_* int constants, FORMAT_NAMES dict, FORMAT_BPP dict,
and FORMAT_ALIASES dict from the v1 codebase. Now they're all attributes on
the PicaFormat enum, so a single import gives you everything.

Format IDs are defined by the PICA200 hardware, documented on 3dbrew:
    https://www.3dbrew.org/wiki/GPU/Internal_Registers#GPUREG_TEXUNITi_FORMAT
and cross-checked against Ohana3DS, citro3d, and tex3ds source.

Some Capcom and Atlus engines remap the same pixel layout to non-standard
IDs. Those are listed in ALIASES and resolved transparently by `resolve()`.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Optional


class PicaFormat(IntEnum):
    """All texture formats the 3DS GPU's texture units can read.

    Values match the hardware GPUREG_TEXUNITi_FORMAT register:
        https://www.3dbrew.org/wiki/GPU/Internal_Registers
    """

    RGBA8     = 0x0   # 32 bpp, stored as A,B,G,R bytes (decoder reverses)
    RGB8      = 0x1   # 24 bpp, stored as B,G,R bytes
    RGBA5551  = 0x2   # 16 bpp LE: [15:11]=R5, [10:6]=G5, [5:1]=B5, [0]=A1
    RGB565    = 0x3   # 16 bpp LE: [15:11]=R5, [10:5]=G6, [4:0]=B5
    RGBA4     = 0x4   # 16 bpp LE: [15:12]=R4, [11:8]=G4, [7:4]=B4, [3:0]=A4
    LA8       = 0x5   # 16 bpp:    byte0=A, byte1=L
    HILO8     = 0x6   # 16 bpp normal map: R=H, G=L, B=255
    L8        = 0x7   # 8 bpp grayscale
    A8        = 0x8   # 8 bpp alpha-only
    LA4       = 0x9   # 8 bpp: high-nibble=L, low-nibble=A
    L4        = 0xA   # 4 bpp grayscale (two pixels per byte, even=low nibble)
    A4        = 0xB   # 4 bpp alpha-only (same nibble packing as L4)
    ETC1      = 0xC   # 4 bpp: 8-byte 4x4 blocks, 3DS macro-tile order
    ETC1A4    = 0xD   # 8 bpp: 16 bytes per 4x4 block (8 alpha + 8 ETC1 color)


# ─────────────────────────────────────────────────────────────────────────────
# Per-format metadata
#
# bpp        - bits per pixel; (w*h*bpp+7)//8 = encoded byte size
# is_etc     - True for ETC1 / ETC1A4 (block compression, 4x4 macro-tile order)
# has_alpha  - True if alpha is meaningfully encoded (not just 255 fill)
# ─────────────────────────────────────────────────────────────────────────────

_BPP = {
    PicaFormat.RGBA8:    32,
    PicaFormat.RGB8:     24,
    PicaFormat.RGBA5551: 16,
    PicaFormat.RGB565:   16,
    PicaFormat.RGBA4:    16,
    PicaFormat.LA8:      16,
    PicaFormat.HILO8:    16,
    PicaFormat.L8:        8,
    PicaFormat.A8:        8,
    PicaFormat.LA4:       8,
    PicaFormat.L4:        4,
    PicaFormat.A4:        4,
    PicaFormat.ETC1:      4,
    PicaFormat.ETC1A4:    8,
}

_IS_ETC = frozenset({PicaFormat.ETC1, PicaFormat.ETC1A4})

_HAS_ALPHA = frozenset({
    PicaFormat.RGBA8, PicaFormat.RGBA5551, PicaFormat.RGBA4,
    PicaFormat.LA8, PicaFormat.A8, PicaFormat.LA4, PicaFormat.A4,
    PicaFormat.ETC1A4,
})

#: Non-standard format IDs used by some game engines, mapped to canonical PICA IDs.
#:
#: - 0x14 (RGBA8) appears in Capcom MT Framework TEX files (RE:Revelations,
#:   Monster Hunter 4U, etc.) — same byte layout as standard RGBA8.
#: - 0x19 / 0x1A (ETC1 / ETC1A4) appear in some Atlus games.
ALIASES = {
    0x14: PicaFormat.RGBA8,
    0x19: PicaFormat.ETC1,
    0x1A: PicaFormat.ETC1A4,
}


# ─────────────────────────────────────────────────────────────────────────────
# Public helpers
# ─────────────────────────────────────────────────────────────────────────────

def resolve(fmt: int) -> Optional[PicaFormat]:
    """Resolve a raw format ID (possibly an engine-specific alias) to a canonical PicaFormat.

    Returns None for unknown IDs -- callers should treat None as "skip / fail",
    not as a default.
    """
    try:
        return PicaFormat(fmt)
    except ValueError:
        return ALIASES.get(fmt)


def name(fmt: int) -> str:
    """Human-readable name -- defaults to "UNKNOWN_0xNN" for unknown IDs."""
    f = resolve(fmt)
    return f.name if f is not None else f"UNKNOWN_0x{fmt:X}"


def bpp(fmt: int) -> int:
    """Bits per pixel. Returns 0 for unknown formats."""
    f = resolve(fmt)
    return _BPP.get(f, 0) if f is not None else 0


def encoded_size(width: int, height: int, fmt: int) -> int:
    """Byte size of a tightly-packed (no mipmaps, no padding) texture of these dims.

    For ETC1/ETC1A4 the result is rounded up to whole 4x4 blocks; for other
    formats to whole 8x8 PICA tiles.
    """
    f = resolve(fmt)
    if f is None:
        return 0
    b = _BPP.get(f, 0)
    if b == 0:
        return 0
    # Round up to next tile boundary so the size matches what the GPU actually reads.
    if f in _IS_ETC:
        # 4x4 blocks
        bw = (width + 3) // 4
        bh = (height + 3) // 4
        return bw * bh * (16 if f == PicaFormat.ETC1A4 else 8)
    # 8x8 tiles, byte-packed
    tw = (width + 7) // 8
    th = (height + 7) // 8
    return tw * th * 64 * b // 8


def is_etc(fmt: int) -> bool:
    """True for ETC1 / ETC1A4 -- they use 4x4 block tiling, not the 8x8 morton table."""
    f = resolve(fmt)
    return f is not None and f in _IS_ETC


def has_alpha(fmt: int) -> bool:
    """True if the format encodes per-pixel alpha (vs. an opaque-only format)."""
    f = resolve(fmt)
    return f is not None and f in _HAS_ALPHA


# ─────────────────────────────────────────────────────────────────────────────
# Backwards-compat aliases (so existing code reading FORMAT_NAMES[fmt] works)
# ─────────────────────────────────────────────────────────────────────────────

FORMAT_NAMES = {int(f): f.name for f in PicaFormat}
FORMAT_BPP = {int(f): _BPP[f] for f in PicaFormat}
