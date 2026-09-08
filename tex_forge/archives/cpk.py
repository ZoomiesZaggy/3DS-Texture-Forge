"""CRI CPK -- Persona Q, 7th Dragon, Sonic Lost World, etc.

CPK is CRIWARE's streaming archive format. The whole 3DS RomFS is often a
single .cpk holding thousands of files. Decoding the format requires:

  1. Parsing the @UTF table -- a big-endian columnar metadata format.
  2. Following TocOffset / ContentOffset to file data.
  3. Decompressing CRILAYLA-wrapped entries.

The parsing code is intricate and well-tested in v1; this module wraps it
verbatim (re-exporting iter_cpk_textures from _cpk_v1) and exposes the
plugin shape the new pipeline expects.

Reference: https://wiki.vg-resource.com/CPK
           https://github.com/Sewer56/CriFsV2Lib
"""

from __future__ import annotations

import logging
from typing import Iterator

from tex_forge.archives.registry import register_archive
from tex_forge.core.types import ArchiveEntry

# Pull in the verbatim CPK parser (copied from v1, only its internal LZ import
# has been fixed up). Public API: is_cpk, iter_cpk_textures.
from tex_forge.archives._cpk_v1 import is_cpk as _is_cpk
from tex_forge.archives._cpk_v1 import iter_cpk_textures as _iter_v1

logger = logging.getLogger(__name__)


def _iter(data: bytes) -> Iterator[ArchiveEntry]:
    if not _is_cpk(data):
        return
    try:
        for inner_path, inner_data in _iter_v1(data):
            if inner_data and len(inner_data) >= 4:
                yield ArchiveEntry(name=inner_path, data=bytes(inner_data))
    except Exception as e:
        logger.warning("CPK parse error: %s", e)


@register_archive("cpk", priority=78, note="CRIWARE CPK (Persona Q, 7th Dragon)")
class _CPK:
    @staticmethod
    def detect(data: bytes) -> bool:
        return _is_cpk(data)

    @staticmethod
    def iter_entries(data: bytes) -> Iterator[ArchiveEntry]:
        yield from _iter(data)
