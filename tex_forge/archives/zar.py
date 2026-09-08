"""ZAR (Grezzo ARchive) -- Ocarina of Time 3D, Majora's Mask 3D.

Format docs: https://wiki.cloudmodding.com/oot/3D:ZAR_format

Header (0x18 bytes):
    +0x00 'ZAR\\x01'
    +0x04 file_size u32
    +0x08 num_types u16
    +0x0A num_files u16
    +0x0C type_table_offset u32
    +0x10 file_table_offset u32
    +0x14 data_offset u32

File table entries (8 bytes each): file_size u32, name_offset u32.
Files are packed sequentially starting at data_offset.
"""

from __future__ import annotations

import logging
import struct
from typing import Iterator

from tex_forge.archives.registry import register_archive
from tex_forge.core.types import ArchiveEntry

logger = logging.getLogger(__name__)

_MAX_BYTES = 100 * 1024 * 1024


def _is_zar(data: bytes) -> bool:
    return len(data) >= 0x18 and data[:4] == b"ZAR\x01"


def _iter(data: bytes) -> Iterator[ArchiveEntry]:
    if not _is_zar(data):
        return
    if len(data) > _MAX_BYTES:
        logger.info("ZAR: skipping %.0f MB archive", len(data) / 1024 / 1024)
        return

    file_len = len(data)
    num_files       = struct.unpack_from("<H", data, 0x0A)[0]
    file_table_off  = struct.unpack_from("<I", data, 0x10)[0]
    data_off        = struct.unpack_from("<I", data, 0x14)[0]

    if num_files == 0 or num_files > 10_000:
        return
    if file_table_off >= file_len or data_off >= file_len:
        return

    cursor = data_off
    for i in range(num_files):
        eo = file_table_off + i * 8
        if eo + 8 > file_len:
            break

        fsize    = struct.unpack_from("<I", data, eo)[0]
        name_off = struct.unpack_from("<I", data, eo + 4)[0]

        name = ""
        if name_off < file_len:
            end = name_off
            limit = min(name_off + 256, file_len)
            while end < limit and data[end] != 0:
                end += 1
            name = data[name_off:end].decode("ascii", errors="replace")
        if not name:
            name = f"{i:04d}.bin"

        if fsize > file_len or cursor + fsize > file_len:
            logger.warning("ZAR entry %d (%s): size %d out of bounds", i, name, fsize)
            break

        if fsize > 0:
            yield ArchiveEntry(name=name, data=bytes(data[cursor:cursor + fsize]))
        cursor += fsize


@register_archive("zar", priority=90)
class _ZAR:
    @staticmethod
    def detect(data: bytes) -> bool:
        return _is_zar(data)

    @staticmethod
    def iter_entries(data: bytes) -> Iterator[ArchiveEntry]:
        try:
            yield from _iter(data)
        except Exception as e:
            logger.warning("ZAR parse error: %s", e)
