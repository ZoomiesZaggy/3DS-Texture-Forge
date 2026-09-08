"""STEX (and variants) -- generic texture container used by some indies."""

from __future__ import annotations

from typing import Iterator

from tex_forge.core.types import Texture
from tex_forge.textures.containers._dict_to_texture import dicts_to_textures
from tex_forge.textures.containers._v1_stex import is_stex, parse_stex
from tex_forge.textures.registry import register_texture


@register_texture("stex", priority=70)
class _STEX:
    @staticmethod
    def detect(data: bytes) -> bool:
        return is_stex(data)

    @staticmethod
    def iter_textures(data: bytes, source_path: str = "") -> Iterator[Texture]:
        yield from dicts_to_textures(parse_stex(data), data, source_path, parser="stex")
