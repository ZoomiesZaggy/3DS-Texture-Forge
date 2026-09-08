"""darc (Data ARChive) -- Kid Icarus: Uprising and other 3DS titles.

Header (0x1C bytes):
    +0x00 'darc'
    +0x04 BOM (LE here, 0xFFFE byte sequence on disk)
    +0x06 header_size u16 (0x1C)
    +0x18 data_offset u32

Entry table starts right after the header. The ROOT entry's w2 holds the
total entry count. Each entry is 12 bytes:
    name_word u32 (low24=name offset in name table, high8=is_dir flag)
    w1 u32  (file: absolute data offset, dir: first child)
    w2 u32  (file: size, dir: one-past-last child)

Name table immediately follows the entry table; names are UTF-16LE.
"""

from __future__ import annotations

import logging
import struct
from typing import Iterator

from tex_forge.archives.registry import register_archive
from tex_forge.core.types import ArchiveEntry

logger = logging.getLogger(__name__)


def _is_darc(data: bytes) -> bool:
    return len(data) >= 8 and data[:4] == b"darc" and data[4:6] == b"\xff\xfe"


def _iter(data: bytes) -> Iterator[ArchiveEntry]:
    if not _is_darc(data):
        return

    hdr_size = struct.unpack_from("<H", data, 6)[0]
    if len(data) < hdr_size + 12:
        return

    num_entries = struct.unpack_from("<I", data, hdr_size + 8)[0]
    if num_entries < 1 or num_entries > 100_000:
        return

    entry_table_end = hdr_size + num_entries * 12
    name_table_start = entry_table_end
    if name_table_start > len(data):
        return

    def get_name(name_off: int) -> str:
        pos = name_table_start + name_off
        end = pos
        while end + 1 < len(data) and (data[end] != 0 or data[end + 1] != 0):
            end += 2
        return data[pos:end].decode("utf-16-le", errors="replace")

    for idx in range(1, num_entries):  # skip root
        eoff = hdr_size + idx * 12
        if eoff + 12 > len(data):
            break

        w0 = struct.unpack_from("<I", data, eoff)[0]
        w1 = struct.unpack_from("<I", data, eoff + 4)[0]
        w2 = struct.unpack_from("<I", data, eoff + 8)[0]

        is_dir = (w0 >> 24) & 0xFF == 0x01
        if is_dir:
            continue

        name_off = w0 & 0x00FFFFFF
        name = get_name(name_off) or f"darc_{idx:04d}"

        if w2 == 0 or w1 + w2 > len(data):
            continue
        yield ArchiveEntry(name=name, data=bytes(data[w1:w1 + w2]))


@register_archive("darc", priority=85)
class _DARC:
    @staticmethod
    def detect(data: bytes) -> bool:
        return _is_darc(data)

    @staticmethod
    def iter_entries(data: bytes) -> Iterator[ArchiveEntry]:
        try:
            yield from _iter(data)
        except Exception as e:
            logger.warning("darc parse error: %s", e)
