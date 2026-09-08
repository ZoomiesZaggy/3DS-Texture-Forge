"""GARC (Game Freak ARChive) -- Pokemon X/Y/OR/AS/S/M.

Format (v4):
    GARC header (0x1C bytes)
        +0x00 'CRAG' (LE view of 'GARC')
        +0x04 header_size u32 LE
        +0x08 BOM u16
        +0x10 data_offset u32

    FATO section: 'OTAF' + size, contains a small index.
    FATB section: 'BTAF' + size + entry_count(u32), then entry_count * 16 bytes
                  per entry: vector(4) + start(4) + end(4) + length(4).
    FIMB section: file data starting at data_offset.

References:
    https://github.com/kwsch/GARCTool
    https://github.com/MarimeGui/garc
"""

from __future__ import annotations

import logging
import struct
from typing import Iterator

from tex_forge.archives.registry import register_archive
from tex_forge.core.types import ArchiveEntry

logger = logging.getLogger(__name__)

_MAX_ENTRIES = 100_000


def _is_garc(data: bytes) -> bool:
    return len(data) >= 0x1C and data[:4] == b"CRAG"


def _iter(data: bytes) -> Iterator[ArchiveEntry]:
    if not _is_garc(data):
        return

    file_len = len(data)
    hdr_size = struct.unpack_from("<I", data, 4)[0]
    bom = struct.unpack_from("<H", data, 8)[0]
    if bom not in (0xFEFF, 0xFFFE):
        logger.warning("GARC: unexpected BOM 0x%04X", bom)
        return
    data_offset = struct.unpack_from("<I", data, 16)[0]

    fato_off = hdr_size
    if fato_off + 12 > file_len or data[fato_off:fato_off + 4] != b"OTAF":
        return
    fato_size = struct.unpack_from("<I", data, fato_off + 4)[0]

    fatb_off = fato_off + fato_size
    if fatb_off + 12 > file_len or data[fatb_off:fatb_off + 4] != b"BTAF":
        return
    count = struct.unpack_from("<I", data, fatb_off + 8)[0]
    if count > _MAX_ENTRIES:
        logger.warning("GARC: %d entries exceeds limit", count)
        return

    entries_start = fatb_off + 12
    for i in range(count):
        base = entries_start + i * 16
        if base + 16 > file_len:
            break
        start = struct.unpack_from("<I", data, base + 4)[0]
        end   = struct.unpack_from("<I", data, base + 8)[0]
        if end <= start:
            continue
        a, b = data_offset + start, data_offset + end
        if b > file_len or a >= file_len:
            continue
        inner = bytes(data[a:b])
        yield ArchiveEntry(name=f"{i:04d}{_ext_for(inner)}", data=inner)


def _ext_for(data: bytes) -> str:
    """Guess a filename extension from magic bytes -- helps dispatch downstream."""
    if len(data) < 4:
        return ".bin"
    m = data[:4]
    if m == b"CGFX":     return ".cgfx"
    if m == b"BCH\x00":  return ".bch"
    if m == b"CTPK":     return ".ctpk"
    if m == b"SARC":     return ".sarc"
    if m == b"NARC":     return ".narc"
    return ".bin"


def has_cgfx(data: bytes) -> bool:
    """Quick scan: does any GARC entry start with CGFX magic?

    Used by the pipeline's GARC adapter to suppress noisy BCH heuristics
    when better-quality CGFX data is present in the same archive.
    """
    if not _is_garc(data):
        return False
    try:
        for entry in _iter(data):
            if entry.data[:4] == b"CGFX":
                return True
    except Exception:
        pass
    return False


@register_archive("garc", priority=100)
class _GARC:
    @staticmethod
    def detect(data: bytes) -> bool:
        return _is_garc(data)

    @staticmethod
    def iter_entries(data: bytes) -> Iterator[ArchiveEntry]:
        try:
            yield from _iter(data)
        except Exception as e:
            logger.warning("GARC parse error: %s", e)
