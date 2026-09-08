"""CGFX / BCRES / BCMDL -- NintendoWare graphics container.

Used by Kirby (Triple Deluxe, Planet Robobot), Mario Kart 7, Super Mario 3D
Land, and many other 1st-party Nintendo titles.

Reference: https://wiki.vg-resource.com/CGFX
"""

from __future__ import annotations

from typing import Iterator

from tex_forge.core.types import Texture
from tex_forge.textures.containers._dict_to_texture import dicts_to_textures
from tex_forge.textures.containers._v1_cgfx import extract_cgfx_textures, is_cgfx
from tex_forge.textures.registry import register_texture


@register_texture("cgfx", priority=90, note="NintendoWare CGFX/BCRES/BCMDL")
class _CGFX:
    @staticmethod
    def detect(data: bytes) -> bool:
        return is_cgfx(data)

    @staticmethod
    def iter_textures(data: bytes, source_path: str = "") -> Iterator[Texture]:
        yield from dicts_to_textures(extract_cgfx_textures(data), data,
                                     source_path, parser="cgfx")
