"""CityHash64 helpers for Azahar custom-texture filenames.

Azahar (and Citra before it) looks a replacement texture up by CityHash64.
Which buffer is hashed depends on the pack's ``use_new_hash`` flag
(``CustomTexManager::UseNewHash``, read from ``pack.json`` ``options``):

  * ``use_new_hash: false`` (legacy, and the mode Forge packs pin) hashes
    the *decoded* linear buffer. ``ComputeHash`` calls ``DecodeTexture``
    with ``convert=false`` into ``width * height * GetFormatBytesPerPixel``
    bytes. Color formats stay in native GPU packing; texture formats
    (IA8, RG8, I8, A8, IA4, I4, A4, ETC1, ETC1A4) expand to RGBA8. The
    linear buffer is bottom-up (OpenGL origin): tiles are placed from the
    bottom of the image and each tile's rows are flipped. See
    ``src/video_core/rasterizer_cache/texture_codec.h`` (``MortonCopy``).
  * ``use_new_hash: true`` hashes the raw tiled upload bytes.

Forge packs advertise the legacy mode, so filenames must use
``azahar_legacy_hash_hex`` (decoded buffer). ``azahar_hash_hex`` remains
the raw/new-hash primitive.

Backend selection at import time:
  1. native ``cityhash`` PyPI module (fast C extension; optional extra)
  2. bundled pure-Python fallback (``_cityhash_pure``)

The pure-Python implementation is byte-exact with the C++ reference and
about 100x slower.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from tex_forge.textures.formats import PicaFormat, resolve

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


def compute_azahar_hash(data: bytes) -> Optional[int]:
    """CityHash64 of ``data``, or None if no backend is available.

    This hashes the bytes it is given. The legacy lookup key is *not*
    the raw GPU buffer; build that with ``legacy_hash_input`` first.
    """
    if _CityHash64 is None:
        return None
    return _CityHash64(data)


def azahar_hash_hex(data: bytes) -> Optional[str]:
    """CityHash64 of ``data`` as a 16-char uppercase hex string.

    Azahar filenames and the manifest use this encoding. Returns None
    if no backend is available.
    """
    h = compute_azahar_hash(data)
    if h is None:
        return None
    return f"{h:016X}"


def _flip_bytes(image: np.ndarray) -> bytes:
    """Bottom-up byte order, matching Azahar's OpenGL-origin linear buffer."""
    return np.ascontiguousarray(image[::-1]).tobytes()


def legacy_hash_input(rgba: np.ndarray, fmt: int) -> bytes:
    """Bytes Azahar CityHash64's when ``use_new_hash`` is false.

    ``rgba`` is Forge's top-down decoded image, shape ``(H, W, 4)``.
    The returned buffer matches ``DecodeTexture(..., convert=false)``:

      * RGBA8 stays native ABGR (4 bytes), vertically flipped.
      * RGB8 stays native BGR (3 bytes), vertically flipped.
      * RGB565 / RGB5A1 / RGBA4 stay packed little-endian u16, row-flipped.
      * A8 / A4 expand to RGBA with RGB forced to 0 (not Forge's 255 fill).
      * HILO8 / RG8 expands to ``(byte1, byte0, 0, 255)``.
      * LA8, L8, LA4, L4, ETC1, ETC1A4 match Forge's RGBA and are only flipped.
    """
    f = resolve(int(fmt))
    if f is None or rgba.ndim != 3 or rgba.shape[2] != 4:
        return _flip_bytes(rgba)

    if f is PicaFormat.RGBA8:
        native = rgba[..., [3, 2, 1, 0]]
        return _flip_bytes(native)
    if f is PicaFormat.RGB8:
        native = rgba[..., [2, 1, 0]]
        return _flip_bytes(native)
    if f is PicaFormat.RGB565:
        r = rgba[..., 0].astype(np.uint16) >> 3
        g = rgba[..., 1].astype(np.uint16) >> 2
        b = rgba[..., 2].astype(np.uint16) >> 3
        pix = (r << 11) | (g << 5) | b
        return _flip_bytes(pix.astype("<u2"))
    if f is PicaFormat.RGBA5551:
        r = rgba[..., 0].astype(np.uint16) >> 3
        g = rgba[..., 1].astype(np.uint16) >> 3
        b = rgba[..., 2].astype(np.uint16) >> 3
        a = (rgba[..., 3].astype(np.uint16) >= 128).astype(np.uint16)
        pix = (r << 11) | (g << 6) | (b << 1) | a
        return _flip_bytes(pix.astype("<u2"))
    if f is PicaFormat.RGBA4:
        r = rgba[..., 0].astype(np.uint16) >> 4
        g = rgba[..., 1].astype(np.uint16) >> 4
        b = rgba[..., 2].astype(np.uint16) >> 4
        a = rgba[..., 3].astype(np.uint16) >> 4
        pix = (r << 12) | (g << 8) | (b << 4) | a
        return _flip_bytes(pix.astype("<u2"))
    if f in (PicaFormat.A8, PicaFormat.A4):
        out = np.zeros_like(rgba)
        out[..., 3] = rgba[..., 3]
        return _flip_bytes(out)
    if f is PicaFormat.HILO8:
        # Azahar RG8: {stored[1], stored[0], 0, 255}. Forge stores
        # stored[0] in R and stored[1] in G.
        out = np.zeros_like(rgba)
        out[..., 0] = rgba[..., 1]
        out[..., 1] = rgba[..., 0]
        out[..., 3] = 255
        return _flip_bytes(out)
    # LA8, L8, LA4, L4, ETC1, ETC1A4: Forge's RGBA matches the expanded buffer.
    return _flip_bytes(rgba)


def azahar_legacy_hash_hex(rgba: np.ndarray, fmt: int) -> Optional[str]:
    """Legacy (``use_new_hash: false``) filename hash of a decoded image."""
    return azahar_hash_hex(legacy_hash_input(rgba, fmt))


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
