"""Compatibility shim: re-export v1's decoder.py public names.

The v1 texture parsers (BCH, JIMG, etc.) import a handful of constants and
helpers from textures.decoder. Rather than rewrite every parser, this module
exposes those same names backed by the new tex_forge.textures.formats /
.decoder packages.

Symbols:
  FMT_RGBA8, FMT_RGB8, FMT_RGBA5551, FMT_RGB565, FMT_RGBA4, FMT_LA8,
  FMT_HILO8, FMT_L8, FMT_A8, FMT_LA4, FMT_L4, FMT_A4, FMT_ETC1, FMT_ETC1A4
  FORMAT_NAMES, FORMAT_BPP
  decode_texture_fast(data, w, h, fmt) -- now backed by decoder.dispatch.decode
  calculate_texture_size(w, h, fmt)
  get_format_name(fmt), get_format_bpp(fmt), resolve_format(fmt)
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from tex_forge.textures.formats import (
    PicaFormat,
    FORMAT_BPP,
    FORMAT_NAMES,
    bpp as get_format_bpp,
    encoded_size as calculate_texture_size,
    name as get_format_name,
    resolve as _resolve,
)
from tex_forge.textures.decoder.dispatch import decode as _decode

# Re-export the integer format IDs under their v1 FMT_* names.
FMT_RGBA8    = int(PicaFormat.RGBA8)
FMT_RGB8     = int(PicaFormat.RGB8)
FMT_RGBA5551 = int(PicaFormat.RGBA5551)
FMT_RGB565   = int(PicaFormat.RGB565)
FMT_RGBA4    = int(PicaFormat.RGBA4)
FMT_LA8      = int(PicaFormat.LA8)
FMT_HILO8    = int(PicaFormat.HILO8)
FMT_L8       = int(PicaFormat.L8)
FMT_A8       = int(PicaFormat.A8)
FMT_LA4      = int(PicaFormat.LA4)
FMT_L4       = int(PicaFormat.L4)
FMT_A4       = int(PicaFormat.A4)
FMT_ETC1     = int(PicaFormat.ETC1)
FMT_ETC1A4   = int(PicaFormat.ETC1A4)


def resolve_format(fmt: int) -> int:
    f = _resolve(fmt)
    return int(f) if f is not None else fmt


def decode_texture_fast(data: bytes, width: int, height: int, fmt: int) -> Optional[np.ndarray]:
    """v1 alias for the new dispatch.decode entry point."""
    return _decode(data, width, height, fmt)


# ETC1 module-level helpers some v1 code expects via `from textures.etc1 import ...`
# These come from the python decoder.
from tex_forge.textures.decoder.pica_python import (
    _decode_etc1 as decode_etc1,        # noqa: F401, internal name re-export
    _decode_etc1a4 as decode_etc1a4,    # noqa: F401
)
