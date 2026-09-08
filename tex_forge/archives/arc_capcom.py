"""Capcom MT Framework ARC -- RE:Revelations, Monster Hunter 4U/Gen, etc.

Format reference: https://lukascone.wordpress.com/2017/06/18/mt-framework-tools/

Header (8 bytes):
    +0x00 'ARC\\x00'
    +0x04 version u16 (0x0010-0x0019 in retail)
    +0x06 num_entries u16

Entry (80 bytes):
    +0x00  data_offset u32
    +0x04  filename[64]  (no extension; 0-terminated)
    +0x44  ext_hash u32  (CRC of original extension)
    +0x48  csize u32     (or "next entry's compressed size" in v0x13)
    +0x4C  info u32      (0x40000000 bit = "compressed" in v0x10/0x11,
                          0x20000000 bit = compressed in v0x13)

The size-field-layout flips between MH3U/MHGen ("self") and MH4U ("prev"),
so we autodetect on the first TEX entry and apply uniformly.

We yield only TEX entries (ext_hash == MH4U_TEX_HASH and decompressed
content starts with 'TEX\\x00') -- the rest are model / shader / etc data
we don't decode.
"""

from __future__ import annotations

import logging
import struct
import zlib
from typing import Iterator

from tex_forge.archives.registry import register_archive
from tex_forge.core.types import ArchiveEntry

logger = logging.getLogger(__name__)

#: Hash for the ".tex" extension across MH4U / RE:Revelations / MHGen.
MH4U_TEX_HASH = 0x241F5DEB
_ENTRY_SIZE = 80


def _is_capcom_arc(data: bytes) -> bool:
    return len(data) >= 8 and data[:4] == b"ARC\x00"


def _detect_layout(data: bytes, eoff: int, idx: int, file_len: int) -> bool:
    """Return True if this ARC's csize/info live in the *current* entry's fields."""
    data_offset = struct.unpack_from("<I", data, eoff)[0]

    # Attempt 1: self-fields.
    self_csize = struct.unpack_from("<I", data, eoff + 0x48)[0]
    self_info  = struct.unpack_from("<I", data, eoff + 0x4C)[0]
    self_comp  = bool(self_info & 0x40000000)
    if self_csize > 0 and data_offset + self_csize <= file_len:
        try:
            raw = data[data_offset:data_offset + self_csize]
            dec = zlib.decompress(raw) if self_comp else raw
            if dec[:4] == b"TEX\x00":
                return True
        except Exception:
            pass

    # Attempt 2: prev-entry fields.
    if idx > 0:
        peoff = 8 + (idx - 1) * _ENTRY_SIZE
        pcsize = struct.unpack_from("<I", data, peoff + 0x48)[0]
        pinfo  = struct.unpack_from("<I", data, peoff + 0x4C)[0]
        pcomp  = bool(pinfo & 0x20000000)
        if pcsize > 0 and data_offset + pcsize <= file_len:
            try:
                raw = data[data_offset:data_offset + pcsize]
                dec = zlib.decompress(raw) if pcomp else raw
                if dec[:4] == b"TEX\x00":
                    return False
            except Exception:
                pass

    return True  # default: self-fields layout


def _iter(data: bytes, tex_hash: int = MH4U_TEX_HASH) -> Iterator[ArchiveEntry]:
    if not _is_capcom_arc(data):
        return

    num_entries = struct.unpack_from("<H", data, 6)[0]
    if num_entries == 0 or num_entries > 65535:
        return

    file_len = len(data)
    use_self = None
    count = 0

    for idx in range(num_entries):
        eoff = 8 + idx * _ENTRY_SIZE
        if eoff + _ENTRY_SIZE > file_len:
            break
        if struct.unpack_from("<I", data, eoff + 0x44)[0] != tex_hash:
            continue

        data_offset = struct.unpack_from("<I", data, eoff)[0]
        if data_offset == 0:
            continue

        if use_self is None and idx > 0:
            use_self = _detect_layout(data, eoff, idx, file_len)

        if use_self is None or use_self:
            csize = struct.unpack_from("<I", data, eoff + 0x48)[0]
            info  = struct.unpack_from("<I", data, eoff + 0x4C)[0]
            is_comp = bool(info & 0x40000000)
        else:
            if idx == 0:
                continue
            peoff = 8 + (idx - 1) * _ENTRY_SIZE
            csize = struct.unpack_from("<I", data, peoff + 0x48)[0]
            info  = struct.unpack_from("<I", data, peoff + 0x4C)[0]
            is_comp = bool(info & 0x20000000)

        if csize == 0 or data_offset + csize > file_len:
            continue

        try:
            raw = data[data_offset:data_offset + csize]
            dec = zlib.decompress(raw) if is_comp else raw
        except Exception:
            continue

        if not dec or dec[:4] != b"TEX\x00":
            continue

        fname_raw = data[eoff + 4:eoff + 68]
        null_pos = fname_raw.find(b"\x00")
        fname = (fname_raw[:null_pos] if null_pos >= 0 else fname_raw).decode("latin1", errors="replace")
        yield ArchiveEntry(name=fname + ".tex", data=bytes(dec))
        count += 1

    if count:
        logger.debug("Capcom ARC: %d TEX entries", count)


@register_archive("capcom_arc", priority=80)
class _CapcomARC:
    @staticmethod
    def detect(data: bytes) -> bool:
        return _is_capcom_arc(data)

    @staticmethod
    def iter_entries(data: bytes) -> Iterator[ArchiveEntry]:
        try:
            yield from _iter(data)
        except Exception as e:
            logger.warning("Capcom ARC parse error: %s", e)
