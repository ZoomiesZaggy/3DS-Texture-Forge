"""Level-5 method-byte compression wrapper (LZ10/Huffman/RLE).

4-byte header: u32 LE where method = val & 7, decompressed_size = val >> 3.
Methods: 0 = none, 1 = LZ10, 2 = Huffman 4-bit, 3 = Huffman 8-bit, 4 = RLE.

The actual implementation lives in textures.containers._v1_level5 alongside
the IMGC parser (because IMGC also depends on it). This module re-exports
it as a registered codec so other Level-5 game data can be decompressed via
the standard pipeline.
"""

from __future__ import annotations

import struct
from typing import Optional

from tex_forge.compression.registry import register_compression
from tex_forge.textures.containers._v1_level5 import decompress_l5

#: 32 MB cap (mirrors the v1 implementation).
MAX_DECOMP = 32 * 1024 * 1024


def _detect(data: bytes) -> bool:
    """Heuristic: 4-byte LE header with valid method nibble + plausible size.

    There's no magic, so detection is based on plausibility:
      * method must be 0..4
      * decomp_size must be > 0 and < 32 MB
      * decomp_size should be at least as large as the input minus header
    """
    if len(data) < 8:
        return False
    val = struct.unpack_from("<I", data, 0)[0]
    method = val & 7
    if method == 0 or method > 4:
        return False
    dec_size = val >> 3
    if dec_size == 0 or dec_size > MAX_DECOMP:
        return False
    # Compressed payload should be smaller than decompressed; reject otherwise.
    return dec_size > (len(data) - 4)


@register_compression("level5", priority=30, note="Level-5 method-byte wrapper")
class _Level5:
    @staticmethod
    def detect(data: bytes) -> bool:
        return _detect(data)

    @staticmethod
    def decompress(data: bytes) -> Optional[bytes]:
        return decompress_l5(data)
