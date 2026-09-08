"""Level-5 flat-file archive (Fantasy Life and friends).

Format:
    +0x00 entry_count u32
    +0x04 padding (0)
    +0x08 entry_count * u32  -- absolute file offsets
    Each entry's size = next_offset - this_offset, last entry runs to EOF.

Most entries are LZ11-compressed; the pipeline scanner re-runs on each
decompressed chunk to find CGFX/BCH/CTPK inside.
"""

from __future__ import annotations

import logging
import struct
from typing import Iterator

from tex_forge.archives.registry import register_archive
from tex_forge.core.types import ArchiveEntry

logger = logging.getLogger(__name__)

_MAX_ENTRY = 50 * 1024 * 1024
_MAX_ENTRIES = 200_000


def _is_l5_flat(data: bytes) -> bool:
    if len(data) < 16:
        return False
    if struct.unpack_from("<I", data, 4)[0] != 0:
        return False
    n = struct.unpack_from("<I", data, 0)[0]
    if not (10 <= n <= _MAX_ENTRIES):
        return False
    table_end = 8 + n * 4
    if table_end > len(data):
        return False
    first = struct.unpack_from("<I", data, 8)[0]
    return table_end <= first < len(data)


def _iter(data: bytes) -> Iterator[ArchiveEntry]:
    if not _is_l5_flat(data):
        return
    n = struct.unpack_from("<I", data, 0)[0]

    offsets = []
    for i in range(n):
        eo = 8 + i * 4
        if eo + 4 > len(data):
            break
        offsets.append(struct.unpack_from("<I", data, eo)[0])
    if not offsets:
        return

    for i, start in enumerate(offsets):
        end = offsets[i + 1] if i + 1 < len(offsets) else len(data)
        size = end - start
        if size <= 0 or start >= len(data) or size > _MAX_ENTRY:
            continue
        yield ArchiveEntry(name=f"entry_{i:05d}.bin", data=bytes(data[start:start + size]))


@register_archive("l5_flat", priority=55, note="Level-5 flat archive (Fantasy Life)")
class _L5Flat:
    @staticmethod
    def detect(data: bytes) -> bool:
        return _is_l5_flat(data)

    @staticmethod
    def iter_entries(data: bytes) -> Iterator[ArchiveEntry]:
        try:
            yield from _iter(data)
        except Exception as e:
            logger.warning("Level-5 flat parse error: %s", e)
