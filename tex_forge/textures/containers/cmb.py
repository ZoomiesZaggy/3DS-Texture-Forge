"""CMB -- Grezzo's model container with embedded textures.

Found inside ZAR and GAR archives in Zelda OOT3D / MM3D.
"""

from __future__ import annotations

from typing import Iterator

from tex_forge.core.types import Texture
from tex_forge.textures.containers._dict_to_texture import dicts_to_textures
from tex_forge.textures.containers._v1_cmb import extract_cmb_textures, is_cmb
from tex_forge.textures.registry import register_texture


@register_texture("cmb", priority=88)
class _CMB:
    @staticmethod
    def detect(data: bytes) -> bool:
        return is_cmb(data)

    @staticmethod
    def iter_textures(data: bytes, source_path: str = "") -> Iterator[Texture]:
        yield from dicts_to_textures(extract_cmb_textures(data), data, source_path,
                                     parser="cmb")
