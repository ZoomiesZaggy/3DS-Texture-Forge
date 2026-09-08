"""jIMG -- Bandai Namco's texture format (One Piece etc)."""

from __future__ import annotations

from typing import Iterator

from tex_forge.core.types import Texture
from tex_forge.textures.containers._dict_to_texture import dicts_to_textures
from tex_forge.textures.containers._v1_jimg import is_jimg, parse_jimg
from tex_forge.textures.registry import register_texture


@register_texture("jimg", priority=88)
class _JIMG:
    @staticmethod
    def detect(data: bytes) -> bool:
        return is_jimg(data)

    @staticmethod
    def iter_textures(data: bytes, source_path: str = "") -> Iterator[Texture]:
        yield from dicts_to_textures(parse_jimg(data, source_path), data, source_path,
                                     parser="jimg")
