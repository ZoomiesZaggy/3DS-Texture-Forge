"""Compression algorithms used by 3DS games.

Public API: try_decompress(data) -> Decompressed | None.

Each codec self-registers via @register_compression. The dispatcher tries
every codec in priority order (descending), returning the first that
recognises the magic bytes AND produces output that *contains a known
texture magic* -- this filter is what keeps us from chasing 6,000+
non-texture .cmp files in games like Stella Glow.

Codecs implemented:

    LZ10 / LZ11 / LZ13 -- standard Nintendo LZSS variants (parsers/lz.py in v1)
    BLZ                -- backward LZSS, footer at end of file (NW4C engine)
    Yaz0 / SZS         -- standard Nintendo LZ77 variant
    zlib               -- raw zlib stream
    gzip-prefix        -- 4-byte LE size + gzip stream (Spike Chunsoft games)
    CRILAYLA           -- only available inside CPK; registered for completeness

Format references:
  - LZ10/LZ11: https://www.romhacking.net/?page=documents&category=&platform=&game=&author=&perpage=20&letter=&search=&id=2&offset=20  + DSDecmp
  - BLZ:      https://github.com/devkitPro/3dstool/blob/master/src/blz.cpp
  - Yaz0:     https://www.3dbrew.org/wiki/SZS
  - CRILAYLA: https://github.com/Sewer56/CriFsV2Lib
"""

from tex_forge.compression.registry import (  # noqa: F401
    Decompressed,
    register_compression,
    try_decompress,
    iter_codecs,
)

# Importing these registers them with the registry as a side-effect.
from tex_forge.compression import lz_nintendo  # noqa: F401
from tex_forge.compression import blz          # noqa: F401
from tex_forge.compression import yaz0         # noqa: F401
from tex_forge.compression import zlib_helpers # noqa: F401
from tex_forge.compression import crilayla    # noqa: F401
from tex_forge.compression import level5       # noqa: F401

__all__ = [
    "Decompressed",
    "register_compression",
    "try_decompress",
    "iter_codecs",
]
