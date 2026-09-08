"""CTPK (CTR Texture Package) -- a small container of one or more textures.

Used by Pokemon (X/Y subordinates), Zelda LBW, Dragon Quest VII/VIII, and
Fire Emblem: Awakening.

Reference: https://www.3dbrew.org/wiki/CTPK
"""

from __future__ import annotations

from typing import Iterator

from tex_forge.core.types import Texture
from tex_forge.textures.containers._dict_to_texture import dicts_to_textures
from tex_forge.textures.containers._v1_ctpk import is_ctpk, parse_ctpk
from tex_forge.textures.registry import register_texture


@register_texture("ctpk", priority=92)
class _CTPK:
    @staticmethod
    def detect(data: bytes) -> bool:
        return is_ctpk(data)

    @staticmethod
    def iter_textures(data: bytes, source_path: str = "") -> Iterator[Texture]:
        yield from dicts_to_textures(parse_ctpk(data), data, source_path, parser="ctpk")
