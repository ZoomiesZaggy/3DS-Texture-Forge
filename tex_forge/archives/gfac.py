"""GFAC (Good-Feel Archive Container) -- Kirby's Extra Epic Yarn etc.

Header:
    +0x00 'GFAC'
    +0x2C entry_count u32
    +0x30 entries[] : 16 bytes each
        +0x00  hash u32
        +0x04  name_off_flags u32  (high bit = compressed; low 31 = name offset)
        +0x08  decomp_size u32
        +0x0C  data_offset u32

Compressed entries are wrapped in a GFCP block:
    +0x00 'GFCP'
    +0x04 version u32
    +0x08 compression type u32 (3 = LZ)
    +0x0C decomp_size u32
    +0x10 comp_size u32
    +0x14 raw LZ payload (no Nintendo LZ header)

We synthesise a Nintendo LZ10/LZ11 header and dispatch to compression.lz_nintendo.
"""

from __future__ import annotations

import logging
import struct
from typing import Iterator

from tex_forge.archives.registry import register_archive
from tex_forge.compression.lz_nintendo import decompress_lz
from tex_forge.core.types import ArchiveEntry

logger = logging.getLogger(__name__)


def _is_gfac(data: bytes) -> bool:
    return len(data) >= 0x30 and data[:4] == b"GFAC"


def _decompress_gfcp(data: bytes, offset: int, expected_size: int) -> bytes:
    if offset + 0x14 >= len(data):
        return b""
    if data[offset:offset + 4] != b"GFCP":
        return data[offset:offset + expected_size]

    decomp_size = struct.unpack_from("<I", data, offset + 0x0C)[0]
    comp_size   = struct.unpack_from("<I", data, offset + 0x10)[0]
    if decomp_size == 0:
        return b""

    payload = data[offset + 0x14:offset + 0x14 + comp_size]
    if not payload:
        return b""

    for type_byte in (0x10, 0x11):
        if decomp_size <= 0xFFFFFF:
            fake_hdr = bytes([type_byte]) + struct.pack("<I", decomp_size)[:3]
        else:
            fake_hdr = bytes([type_byte, 0x00, 0x00, 0x00]) + struct.pack("<I", decomp_size)
        try:
            out = decompress_lz(fake_hdr + payload)
            if out:
                return out
        except Exception:
            pass
    return b""


def _iter(data: bytes) -> Iterator[ArchiveEntry]:
    if not _is_gfac(data):
        return

    entry_count = struct.unpack_from("<I", data, 0x2C)[0]
    if entry_count == 0 or entry_count > 10_000:
        return

    for i in range(entry_count):
        eo = 0x30 + i * 16
        if eo + 16 > len(data):
            break

        name_off_flags = struct.unpack_from("<I", data, eo + 4)[0]
        decomp_size    = struct.unpack_from("<I", data, eo + 8)[0]
        data_off       = struct.unpack_from("<I", data, eo + 12)[0]
        compressed = bool(name_off_flags & 0x80000000)
        name_off   = name_off_flags & 0x7FFFFFFF

        name = ""
        if name_off < len(data):
            end = data.find(b"\x00", name_off, name_off + 128)
            if end < 0:
                end = name_off + 32
            name = data[name_off:end].decode("ascii", errors="replace")
        if not name:
            name = f"gfac_{i:04d}"

        if data_off >= len(data):
            continue

        if compressed:
            blob = _decompress_gfcp(data, data_off, decomp_size)
        else:
            # Run to next entry's data start, capped by decomp_size and EOF.
            next_off = len(data)
            if i + 1 < entry_count:
                neo = eo + 16 + 12
                if neo + 4 <= len(data):
                    cand = struct.unpack_from("<I", data, neo)[0]
                    if data_off < cand <= len(data):
                        next_off = cand
            raw_size = max(0, min(decomp_size, next_off - data_off, len(data) - data_off))
            blob = data[data_off:data_off + raw_size]

        if blob and len(blob) >= 4:
            yield ArchiveEntry(name=name, data=bytes(blob))


@register_archive("gfac", priority=85)
class _GFAC:
    @staticmethod
    def detect(data: bytes) -> bool:
        return _is_gfac(data)

    @staticmethod
    def iter_entries(data: bytes) -> Iterator[ArchiveEntry]:
        try:
            yield from _iter(data)
        except Exception as e:
            logger.warning("GFAC parse error: %s", e)
