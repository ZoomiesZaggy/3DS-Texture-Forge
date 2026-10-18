"""GARC (Game Freak ARChive) -- Pokemon X/Y/OR/AS/S/M/US/UM.

Format (pk3DS ``GARC.cs``, versions 0x0400 and 0x0600):
    GARC header
        +0x00 'CRAG' (LE view of 'GARC')
        +0x04 header_size u32 (0x1C for v4, 0x24 for v6)
        +0x08 BOM u16 (0xFEFF)
        +0x0A version u16 (0x0400 or 0x0600)
        +0x10 data_offset u32  -- start of the file bytes, after the FIMB header

    FATO ('OTAF'): header size, entry count (u16), then one u32 per entry.
    FATB ('BTAF'): header size, total subfile count (u32), then one record
        per FATO entry. A record is a bit vector (u32) followed by one
        (start, end, length) triple for each set bit, low bit first.
        A single-subfile entry is 16 bytes; a language pack or a
        model-plus-texture entry is longer. Walking every entry as 16
        bytes drops every subfile after the first and desynchronizes
        the rest of the table.
    File bytes live at data_offset + start. ``length`` is the unpadded
    size; ``end`` includes the 4-byte alignment padding.

References:
    https://github.com/kwsch/pk3DS/blob/master/pk3DS.Core/CTR/GARC.cs
    https://github.com/kwsch/GARCTool
"""

from __future__ import annotations

import logging
import struct
from typing import Iterator

from tex_forge.archives.registry import register_archive
from tex_forge.core.types import ArchiveEntry

logger = logging.getLogger(__name__)

_MAX_ENTRIES = 100_000
_VER_4 = 0x0400
_VER_6 = 0x0600


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
    if file_len >= 0x0C:
        version = struct.unpack_from("<H", data, 0x0A)[0]
        if version not in (_VER_4, _VER_6):
            logger.debug("GARC: unknown version 0x%04X; walking FATB anyway", version)
    data_offset = struct.unpack_from("<I", data, 16)[0]

    fato_off = hdr_size
    if fato_off + 12 > file_len or data[fato_off:fato_off + 4] != b"OTAF":
        return
    fato_size = struct.unpack_from("<I", data, fato_off + 4)[0]
    entry_count = struct.unpack_from("<H", data, fato_off + 8)[0]
    if entry_count > _MAX_ENTRIES:
        logger.warning("GARC: %d entries exceeds limit", entry_count)
        return

    fatb_off = fato_off + fato_size
    if fatb_off + 12 > file_len or data[fatb_off:fatb_off + 4] != b"BTAF":
        return
    fatb_size = struct.unpack_from("<I", data, fatb_off + 4)[0]
    if 12 <= fatb_size <= file_len - fatb_off:
        entries_end = fatb_off + fatb_size
    else:
        entries_end = file_len

    pos = fatb_off + 12
    for i in range(entry_count):
        if pos + 4 > entries_end:
            logger.debug("GARC: FATB ended early at entry %d", i)
            break
        vector = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        subs: list[tuple[int, int, int, int]] = []
        bits = vector
        for bit in range(32):
            if bits == 0:
                break
            if bits & 1:
                if pos + 12 > entries_end:
                    logger.debug("GARC: truncated subfile triple at entry %d bit %d", i, bit)
                    bits = 0
                    break
                start, end, length = struct.unpack_from("<III", data, pos)
                pos += 12
                subs.append((bit, start, end, length))
            bits >>= 1
        multi = len(subs) > 1
        for bit, start, end, length in subs:
            if end <= start:
                continue
            span = end - start
            # pk3DS reads ``length`` bytes; ``end`` includes alignment
            # padding. A zero or oversized length falls back to the span
            # so a writer that left length unset still yields the bytes.
            size = length if 0 < length <= span else span
            a = data_offset + start
            b = a + size
            if a < 0 or b > file_len or a >= file_len:
                continue
            inner = bytes(data[a:b])
            stem = f"{i:04d}_{bit:02d}" if multi else f"{i:04d}"
            yield ArchiveEntry(name=f"{stem}{_ext_for(inner)}", data=inner)


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
    if len(data) >= 0x28:
        footer = data[-0x28:-0x24]
        if footer == b"FLIM":
            return ".bflim"
        if footer == b"CLIM":
            return ".bclim"
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
        logger.debug("GARC CGFX scan failed", exc_info=True)
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
            logger.warning("GARC parse error: %s", e, exc_info=True)
