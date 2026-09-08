"""BCH (Binary CTR H3D) -- the workhorse texture format on 3DS.

BCH appears in nearly every supported game. It's a section-based binary
container; the v1 parser (`_v1_bch.extract_bch_textures`) is heuristic
because the texture section pointer is fragile across game versions, so
expect this plugin to occasionally produce false positives that the
pipeline filters by checking pixel variance.

Reference: https://deepwiki.com/dnasdw/Ohana3DS/7.1-3d-model-formats-(bch-cgfx)
"""

from __future__ import annotations

from typing import Iterator

from tex_forge.core.types import Texture
from tex_forge.textures.containers._dict_to_texture import dicts_to_textures
from tex_forge.textures.containers._v1_bch import extract_bch_textures, is_bch
from tex_forge.textures.registry import register_texture


@register_texture("bch", priority=80, note="3DS BCH model/texture container")
class _BCH:
    @staticmethod
    def detect(data: bytes) -> bool:
        return is_bch(data)

    @staticmethod
    def iter_textures(data: bytes, source_path: str = "") -> Iterator[Texture]:
        # BCH parser is heuristic; emit medium confidence so the pipeline
        # knows to apply BCH-specific quality filters.
        yield from dicts_to_textures(extract_bch_textures(data), data,
                                     source_path, parser="bch", confidence="medium")
