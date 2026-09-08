"""CTXB -- Grezzo's texture container for Zelda OOT3D / MM3D."""

from __future__ import annotations

from typing import Iterator

from tex_forge.core.types import Texture
from tex_forge.textures.containers._dict_to_texture import dicts_to_textures
from tex_forge.textures.containers._v1_ctxb import is_ctxb, parse_ctxb
from tex_forge.textures.registry import register_texture


@register_texture("ctxb", priority=92)
class _CTXB:
    @staticmethod
    def detect(data: bytes) -> bool:
        return is_ctxb(data)

    @staticmethod
    def iter_textures(data: bytes, source_path: str = "") -> Iterator[Texture]:
        yield from dicts_to_textures(parse_ctxb(data), data, source_path, parser="ctxb")
