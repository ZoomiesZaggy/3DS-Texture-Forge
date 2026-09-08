"""SARC (Simple ARChive) -- Nintendo's bundle format for 3DS / Wii U / Switch.

Format: https://mk8.tockdom.com/wiki/SARC_(File_Format)

Layout:
    SARC header (0x14 bytes)
        +0x00 'SARC'
        +0x04 header_length u16
        +0x06 BOM u16  (0xFEFF=BE, 0xFFFE=LE)
        +0x08 file_size u32
        +0x0C data_offset u32
        +0x10 version u16
    SFAT section ('SFAT' + 0x0C bytes header, then node_count*16 nodes)
    SFNT section ('SFNT' + header, then string table)
    Data: starting at data_offset.

The 24-bit SFAT name-offset is in *4-byte words* relative to the string table.
"""

from __future__ import annotations

import logging
import struct
from typing import Iterator

from tex_forge.archives.registry import register_archive
from tex_forge.core.types import ArchiveEntry

logger = logging.getLogger(__name__)


def _is_sarc(data: bytes) -> bool:
    return len(data) >= 0x14 and data[:4] == b"SARC"


def _iter(data: bytes) -> Iterator[ArchiveEntry]:
    if not _is_sarc(data):
        return

    bom_bytes = data[6:8]
    bo = "<" if bom_bytes == b"\xFF\xFE" else (">" if bom_bytes == b"\xFE\xFF" else "<")

    hdr_len     = struct.unpack_from(bo + "H", data, 4)[0]
    data_offset = struct.unpack_from(bo + "I", data, 0x0C)[0]
    if data_offset > len(data):
        logger.warning("SARC data_offset 0x%X > file size %d", data_offset, len(data))
        return

    sfat_off = hdr_len
    if sfat_off + 0x0C > len(data) or data[sfat_off:sfat_off + 4] != b"SFAT":
        return
    sfat_hdr_len = struct.unpack_from(bo + "H", data, sfat_off + 4)[0]
    node_count   = struct.unpack_from(bo + "H", data, sfat_off + 6)[0]
    nodes_start  = sfat_off + sfat_hdr_len
    sfat_end     = nodes_start + node_count * 16

    if sfat_end + 8 > len(data) or data[sfat_end:sfat_end + 4] != b"SFNT":
        return
    sfnt_hdr_len = struct.unpack_from(bo + "H", data, sfat_end + 4)[0]
    strings_start = sfat_end + sfnt_hdr_len

    for i in range(node_count):
        node_off = nodes_start + i * 16
        if node_off + 16 > len(data):
            break

        attrs      = struct.unpack_from(bo + "I", data, node_off + 4)[0]
        file_start = struct.unpack_from(bo + "I", data, node_off + 8)[0]
        file_end   = struct.unpack_from(bo + "I", data, node_off + 12)[0]

        has_name = (attrs >> 24) & 1
        name_off_words = attrs & 0xFFFFFF

        name = f"file_{i:04d}"
        if has_name:
            noff = strings_start + name_off_words * 4
            if noff < len(data):
                end = noff
                limit = min(noff + 512, len(data))
                while end < limit and data[end] != 0:
                    end += 1
                name = data[noff:end].decode("utf-8", errors="replace")

        a = data_offset + file_start
        b = data_offset + file_end
        if a > len(data):
            continue
        if b > len(data):
            b = len(data)
        yield ArchiveEntry(name=name, data=bytes(data[a:b]))


@register_archive("sarc", priority=95)
class _SARC:
    @staticmethod
    def detect(data: bytes) -> bool:
        return _is_sarc(data)

    @staticmethod
    def iter_entries(data: bytes) -> Iterator[ArchiveEntry]:
        try:
            yield from _iter(data)
        except Exception as e:
            logger.warning("SARC parse error: %s", e)
