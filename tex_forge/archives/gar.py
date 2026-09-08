"""GAR (Grezzo) v2 archive.

Used by Majora's Mask 3D. We don't fully decode the GAR table; instead we
scan for embedded ctxb/cmb chunks (their headers carry total_size at +4),
which is what every released tool (Gar/Zar Unpacker, Switch Toolbox) does.
"""

from __future__ import annotations

import logging
import struct
from typing import Iterator

from tex_forge.archives.registry import register_archive
from tex_forge.core.types import ArchiveEntry

logger = logging.getLogger(__name__)


def _is_gar(data: bytes) -> bool:
    return len(data) >= 4 and data[:3] == b"GAR"


def _iter(data: bytes) -> Iterator[ArchiveEntry]:
    if not _is_gar(data) or len(data) < 0x20:
        return

    idx = 0
    off = 0
    n = len(data)
    while off < n - 8:
        magic = data[off:off + 4]
        if magic == b"ctxb":
            total = struct.unpack_from("<I", data, off + 4)[0]
            if 8 < total <= n - off:
                yield ArchiveEntry(name=f"gar_ctxb_{idx:04d}.ctxb", data=bytes(data[off:off + total]))
                idx += 1
                off += total
                continue
        elif magic == b"cmb ":
            total = struct.unpack_from("<I", data, off + 4)[0]
            if 8 < total <= n - off:
                yield ArchiveEntry(name=f"gar_cmb_{idx:04d}.cmb", data=bytes(data[off:off + total]))
                idx += 1
                off += total
                continue
        off += 4


@register_archive("gar", priority=85)
class _GAR:
    @staticmethod
    def detect(data: bytes) -> bool:
        return _is_gar(data)

    @staticmethod
    def iter_entries(data: bytes) -> Iterator[ArchiveEntry]:
        try:
            yield from _iter(data)
        except Exception as e:
            logger.warning("GAR parse error: %s", e)
