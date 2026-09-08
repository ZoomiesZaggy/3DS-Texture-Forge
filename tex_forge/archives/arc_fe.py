"""IS ARC -- Fire Emblem: Awakening / Fates / Echoes (Intelligent Systems).

Format:
    Header (16 bytes):
        +0x00 file_size u32 (matches actual file size)
        +0x08 num_entries u32
    16 bytes of zero padding.
    Entries from 0x20 onwards: each is a complete LZ-compressed file
    (LZ10/LZ11/LZ13 header + payload). In FE:A entry 1 at +0x24 is
    typically the texture pack (CTPK after decompression).

We don't have a per-entry size field, so we just feed the LZ decompressor
each candidate offset and let it self-terminate.
"""

from __future__ import annotations

import logging
import struct
from typing import Iterator

from tex_forge.archives.registry import register_archive
from tex_forge.compression.lz_nintendo import decompress_lz
from tex_forge.core.types import ArchiveEntry

logger = logging.getLogger(__name__)


def _is_fe_arc(data: bytes) -> bool:
    if len(data) < 0x28:
        return False
    if struct.unpack_from("<I", data, 0)[0] != len(data):
        return False
    if data[:4] == b"ARC\x00":
        return False  # that's MT Framework, not IS
    if data[0x20] not in (0x10, 0x11, 0x13) and data[0x24] not in (0x10, 0x11, 0x13):
        return False
    n = struct.unpack_from("<I", data, 8)[0]
    return 1 <= n <= 64


def _iter(data: bytes) -> Iterator[ArchiveEntry]:
    if not _is_fe_arc(data):
        return

    num_entries = struct.unpack_from("<I", data, 8)[0]
    idx = 0
    end = min(0x20 + num_entries * 4 + 4, len(data) - 3)
    for entry_off in range(0x20, end, 4):
        if data[entry_off] not in (0x10, 0x11, 0x13):
            continue
        dec = decompress_lz(data[entry_off:])
        if dec is None:
            continue

        magic = dec[:4]
        if magic == b"CTPK":
            yield ArchiveEntry(name=f"fe_arc_{idx:04d}.ctpk", data=dec)
            idx += 1
        elif magic == b"CGFX":
            yield ArchiveEntry(name=f"fe_arc_{idx:04d}.cgfx", data=dec)
            idx += 1
        elif magic == b"BCH\x00":
            yield ArchiveEntry(name=f"fe_arc_{idx:04d}.bch", data=dec)
            idx += 1


@register_archive("fe_arc", priority=75)
class _FEArc:
    @staticmethod
    def detect(data: bytes) -> bool:
        return _is_fe_arc(data)

    @staticmethod
    def iter_entries(data: bytes) -> Iterator[ArchiveEntry]:
        try:
            yield from _iter(data)
        except Exception as e:
            logger.warning("FE ARC parse error: %s", e)
