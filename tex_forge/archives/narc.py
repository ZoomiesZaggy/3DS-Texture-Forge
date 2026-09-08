"""NARC (Nitro ARChive) -- legacy DS format that crops up in 3DS bundles.

Layout:
    16-byte NARC header (magic + BOM + version + sizes)
    BTAF section: file allocation table (start, end) per entry
    BTNF section: filenames (we ignore -- index-based naming is fine)
    GMIF section: "Game Image File" -- the actual file data
"""

from __future__ import annotations

import logging
import struct
from typing import Iterator

from tex_forge.archives.registry import register_archive
from tex_forge.core.types import ArchiveEntry

logger = logging.getLogger(__name__)


def _is_narc(data: bytes) -> bool:
    return len(data) >= 16 and data[:4] == b"NARC"


def _iter(data: bytes) -> Iterator[ArchiveEntry]:
    if not _is_narc(data):
        return

    bom = struct.unpack_from("<H", data, 4)[0]
    fmt = "<" if bom == 0xFFFE else ">"

    fatb_off = 0x10
    if fatb_off + 12 > len(data) or data[fatb_off:fatb_off + 4] != b"BTAF":
        return
    fatb_size  = struct.unpack_from(f"{fmt}I", data, fatb_off + 4)[0]
    file_count = struct.unpack_from(f"{fmt}I", data, fatb_off + 8)[0]
    if file_count == 0 or file_count > 100_000:
        return

    entries = []
    for i in range(file_count):
        eo = fatb_off + 12 + i * 8
        if eo + 8 > len(data):
            break
        s, e = struct.unpack_from(f"{fmt}II", data, eo)
        entries.append((s, e))

    fntb_off = fatb_off + fatb_size
    if fntb_off + 8 > len(data) or data[fntb_off:fntb_off + 4] != b"BTNF":
        return
    fntb_size = struct.unpack_from(f"{fmt}I", data, fntb_off + 4)[0]

    fimg_off = fntb_off + fntb_size
    if fimg_off + 8 > len(data) or data[fimg_off:fimg_off + 4] != b"GMIF":
        return

    data_start = fimg_off + 8

    for i, (s, e) in enumerate(entries):
        a, b = data_start + s, data_start + e
        if a < len(data) and b <= len(data) and b > a:
            yield ArchiveEntry(name=f"{i:04d}.bin", data=bytes(data[a:b]))


@register_archive("narc", priority=95)
class _NARC:
    @staticmethod
    def detect(data: bytes) -> bool:
        return _is_narc(data)

    @staticmethod
    def iter_entries(data: bytes) -> Iterator[ArchiveEntry]:
        try:
            yield from _iter(data)
        except Exception as e:
            logger.warning("NARC parse error: %s", e)
