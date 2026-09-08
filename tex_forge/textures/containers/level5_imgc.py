"""IMGC -- Level-5's tile-deduplicated texture format.

Used by Layton, Yo-Kai Watch, Fantasy Life. The file stores:
  1. A tile map (u16 per 8x8 tile, indexing into the palette below)
  2. A palette of unique 8x8 tiles in PICA200 morton order

Both halves are wrapped in Level-5's custom compression header (method byte
+ 24-bit decomp size; methods 1=LZ10, 2/3=Huffman, 4=RLE). The decompressor
is part of this module.

References:
  - https://gbatemp.net/threads/level5-xi-file-format.458349/  (offset notes)
  - v1 reference: parsers/level5.py
  - https://github.com/MeltyPlayer/MeltyTool  (Metanoia-based parsers)

Single-image format -- registered as a texture plugin, yielding one Texture
per file (with reconstructed pixel bytes ready for the standard PICA decoder).
"""

from __future__ import annotations

from typing import Iterator

from tex_forge.core.types import Texture
from tex_forge.textures.containers._dict_to_texture import dicts_to_textures
from tex_forge.textures.containers._v1_level5 import is_imgc, parse_imgc
from tex_forge.textures.registry import register_texture


@register_texture("imgc", priority=82, note="Level-5 IMGC tile-dedup texture")
class _IMGC:
    @staticmethod
    def detect(data: bytes) -> bool:
        return is_imgc(data)

    @staticmethod
    def iter_textures(data: bytes, source_path: str = "") -> Iterator[Texture]:
        yield from dicts_to_textures(parse_imgc(data), data, source_path,
                                     parser="imgc")
