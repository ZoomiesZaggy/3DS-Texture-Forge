"""Compute Azahar's runtime custom-texture lookup hash from raw GPU bytes.

Background: Azahar (and its parent Citra) hashes textures at upload
time, using CityHash64 over the bytes the game wrote to texture memory.
For 3DS textures those bytes are byte-identical to what Forge already
has in `Texture.data` before decoding -- tiled ETC1/ETC1A4/RGBA8/etc.
in 3DS Morton order. So `CityHash64(tex.data)` matches Azahar's runtime
hash exactly, with no need for the user to first run the emulator's
"Dump Custom Textures" feature.

Backend selection at import time:
  1. native `cityhash` PyPI module (fast C extension)
  2. bundled pure-Python fallback (`_cityhash_pure`)

The pure-Python implementation is byte-exact identical to the C++
reference; it is ~100x slower but at microseconds per texture this is
invisible at extract time.

Reference: Azahar's `src/video_core/rasterizer_cache/rasterizer_cache.h`,
function `ComputeHash`:

    return Common::ComputeHash64<Common::HashAlgo64::CityHash>(
        upload_data.data(), upload_data.size());
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# Backend resolution: prefer native, fall back to bundled pure-Python.
try:
    from cityhash import CityHash64 as _CityHash64  # type: ignore
    _BACKEND = "native"
except ImportError:
    try:
        from tex_forge.textures._cityhash_pure import CityHash64 as _CityHash64
        _BACKEND = "pure"
    except ImportError:
        _CityHash64 = None  # type: ignore
        _BACKEND = "none"


# Azahar's PixelFormat enum, from
# `src/video_core/rasterizer_cache/pixel_format.h`. The custom-texture
# filename uses the integer code; values 0..13 are stable across builds.
#
# The mapping covers both Azahar's canonical names and the names that
# Forge's `tex_forge.textures.formats.name()` emits for the same
# numeric format IDs (RGBA5551 == RGB5A1, LA8 == IA8, L8 == I8, LA4 ==
# IA4, L4 == I4, HILO8 maps to slot 6 == RG8). HILO8 is a non-standard
# normal-map remap of RG8 in some 3DS engines -- the byte layout is the
# same, so the same code applies.
PIXEL_FORMAT_CODE: dict[str, int] = {
    # Azahar canonical names
    "RGBA8":   0,
    "RGB8":    1,
    "RGB5A1":  2,
    "RGB565":  3,
    "RGBA4":   4,
    "IA8":     5,
    "RG8":     6,
    "I8":      7,
    "A8":      8,
    "IA4":     9,
    "I4":     10,
    "A4":     11,
    "ETC1":   12,
    "ETC1A4": 13,
    # Forge aliases (same numeric IDs, different names)
    "RGBA5551": 2,
    "LA8":      5,
    "HILO8":    6,
    "L8":       7,
    "LA4":      9,
    "L4":      10,
}


def is_available() -> bool:
    """True if any CityHash64 backend (native or pure) is loadable."""
    return _CityHash64 is not None


def is_supported_format(fmt_name: str) -> bool:
    """True if `fmt_name` (output of textures.formats.name()) maps to a
    known Azahar pixel format code."""
    return fmt_name in PIXEL_FORMAT_CODE


def compute_azahar_hash(raw_gpu_bytes: bytes) -> Optional[int]:
    """Return the 64-bit Azahar lookup hash of the raw GPU bytes,
    or None if no CityHash64 backend is available."""
    if _CityHash64 is None:
        return None
    return _CityHash64(raw_gpu_bytes)


def azahar_hash_hex(raw_gpu_bytes: bytes) -> Optional[str]:
    """Return the hash as a 16-char uppercase hex string -- the
    representation Azahar expects in custom-texture filenames and what
    Forge stores in the manifest. Returns None if no backend is
    available."""
    h = compute_azahar_hash(raw_gpu_bytes)
    if h is None:
        return None
    return f"{h:016X}"


def azahar_filename(
    width: int,
    height: int,
    hash_u64: int,
    fmt_name: str,
    mip_level: int = 0,
) -> Optional[str]:
    """Build the drop-in Azahar filename `tex1_<W>x<H>_<HASH>_<code>_mip<N>.png`.

    Returns None if `fmt_name` is not a supported Azahar pixel format.

    The `_mip<N>` suffix matches exactly what Azahar/Citra's own texture
    dumper writes and what every shipped pack on disk uses (e.g.
    `tex1_512x256_D34F6476B900856D_13_mip0.png`). Emitting it removes any
    doubt about the loader's filename parser accepting the name.
    """
    code = PIXEL_FORMAT_CODE.get(fmt_name)
    if code is None:
        return None
    return f"tex1_{width}x{height}_{hash_u64:016X}_{code}_mip{mip_level}.png"
