"""GDB1 -- texturedb format used by Star Fox 64 3D.

GDB1 uses a *paired* file layout: a .texturegdb file holds the metadata
table and a sibling .texturebin file holds the pixel data. The pipeline's
adapter detects the pair and feeds both blobs into parse_gdb1_pair().

This plugin handles the .texturegdb file alone (header detection only) --
it does not produce textures by itself. The actual paired-file handling
lives in tex_forge.pipeline.adapters.
"""

from __future__ import annotations

from typing import Iterator

from tex_forge.core.types import Texture
from tex_forge.textures.containers._dict_to_texture import dicts_to_textures
from tex_forge.textures.containers._v1_gdb1 import is_gdb1, parse_gdb1_pair
from tex_forge.textures.registry import register_texture


@register_texture("gdb1", priority=70, note="Star Fox 64 3D paired GDB1")
class _GDB1:
    @staticmethod
    def detect(data: bytes) -> bool:
        return is_gdb1(data)

    @staticmethod
    def iter_textures(data: bytes, source_path: str = "") -> Iterator[Texture]:
        # No paired bin available here -- pipeline adapter handles the real case.
        return iter(())


def parse_pair(gdb_data: bytes, bin_data: bytes, source_path: str = "") -> Iterator[Texture]:
    """Public helper for the pipeline adapter: decode .texturegdb + .texturebin."""
    yield from dicts_to_textures(
        parse_gdb1_pair(gdb_data, bin_data, source_path),
        bin_data, source_path, parser="gdb1",
    )
