"""Shin'en TEX CTR -- Nano Assault.

Magic: "TEX CTR" (7 bytes). Some files use the proprietary CMPR
compression which the v1 parser handles internally.
"""

from __future__ import annotations

from typing import Iterator

from tex_forge.core.types import Texture
from tex_forge.textures.containers._dict_to_texture import dicts_to_textures
from tex_forge.textures.containers._v1_shinen_tex import (
    is_shinen_tex,
    parse_shinen_tex,
)
from tex_forge.textures.registry import register_texture


@register_texture("shinen_tex", priority=86)
class _Shinen:
    @staticmethod
    def detect(data: bytes) -> bool:
        return is_shinen_tex(data)

    @staticmethod
    def iter_textures(data: bytes, source_path: str = "") -> Iterator[Texture]:
        yield from dicts_to_textures(parse_shinen_tex(data), data, source_path,
                                     parser="shinen_tex")
