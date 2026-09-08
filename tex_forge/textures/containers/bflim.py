"""BFLIM / BCLIM -- Layout image format used by 3DS UI textures.

Note: header is at the END of the file (last 0x14 / 0x28 bytes), which is
why detect() peeks the trailing bytes rather than the leading bytes.

Reference: https://mk8.tockdom.com/wiki/BFLIM_(File_Format)
"""

from __future__ import annotations

from typing import Iterator

from tex_forge.core.types import Texture
from tex_forge.textures.containers._dict_to_texture import dict_to_texture
from tex_forge.textures.containers._v1_bflim import is_bflim, parse_bflim
from tex_forge.textures.registry import register_texture


@register_texture("bflim", priority=88)
class _BFLIM:
    @staticmethod
    def detect(data: bytes) -> bool:
        return is_bflim(data)

    @staticmethod
    def iter_textures(data: bytes, source_path: str = "") -> Iterator[Texture]:
        result = parse_bflim(data)
        if not result:
            return
        # parse_bflim returns dict | None; promote display dimensions to crop_*
        dw = result.get("display_width", 0)
        dh = result.get("display_height", 0)
        if dw and dh and (dw != result["width"] or dh != result["height"]):
            result["crop_width"] = dw
            result["crop_height"] = dh
        yield dict_to_texture(result, data, source_path, parser="bflim")
