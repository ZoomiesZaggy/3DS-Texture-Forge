"""Capcom MT Framework TEX -- RE:Revelations, MH4U, MHGen.

The Capcom TEX format has many version-specific quirks. The v1 parser
(`_v1_tex_capcom.parse_capcom_tex_strict`) returns a *result object*
rather than a list of dicts -- success / partial / failure plus the
single decoded image -- so this wrapper unpacks that explicitly.
"""

from __future__ import annotations

from typing import Iterator

from tex_forge.core.types import Texture
from tex_forge.textures.containers._v1_tex_capcom import (
    is_capcom_tex,
    parse_capcom_tex_strict,
)
from tex_forge.textures.registry import register_texture


@register_texture("capcom_tex", priority=85, note="Capcom MT Framework TEX")
class _CapcomTex:
    @staticmethod
    def detect(data: bytes) -> bool:
        return is_capcom_tex(data)

    @staticmethod
    def iter_textures(data: bytes, source_path: str = "") -> Iterator[Texture]:
        # title_id is needed for game-profile dispatch; pipeline.adapters
        # passes it via Texture.extra when it has it. Default to empty here.
        pr = parse_capcom_tex_strict(data, source_path, title_id="")
        if pr.status not in ("parsed", "partial") or not pr.pixel_data:
            return
        yield Texture(
            name="",
            width=int(pr.width),
            height=int(pr.height),
            format=int(pr.format_pica),
            data=bytes(pr.pixel_data),
            mip_count=int(pr.mip_count),
            parser_used=f"capcom_tex/{pr.parser_variant}",
            confidence=pr.confidence,
            source_file=source_path,
            notes=list(pr.notes),
        )
