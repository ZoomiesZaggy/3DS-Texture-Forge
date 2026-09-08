"""Smash Bros for 3DS dt/ls -- huge resource bank indexed by a companion file.

Smash stores nearly every asset in one giant 'dt' blob. The 'ls' file is the
index: a 4-byte magic + entry count, then 12-byte entries (hash, dt_offset,
comp_size). Each dt resource is a zlib-compressed blob whose decompressed
content is BCH / CGFX / CTPK (or game-specific data we ignore).

This archive is unusual because the 'dt' file is enormous (hundreds of MB)
and we shouldn't decompress every entry up-front. The pipeline's smash
adapter handles that -- it parses the ls index and feeds individual dt
slices into the registry one at a time. So this plugin's job is just to
expose parse_ls() and a single-resource decompressor, not to walk the whole
archive itself.

NB: We do NOT register this as an auto-detect plugin -- the 'ls' magic is
tiny and ambiguous, and the dt blob has no magic at all. The pipeline's
smash adapter explicitly checks for an 'ls' / 'dt' file pair in RomFS.
"""

from __future__ import annotations

import logging
import struct
import zlib
from typing import List, Tuple

logger = logging.getLogger(__name__)

LS_MAGIC = b"of\x01\x00"

_ZLIB_HEADERS = (b"\x78\x9C", b"\x78\xDA", b"\x78\x01", b"\x78\x5E")
_TEX_MAGICS = (b"BCH\x00", b"CGFX", b"CTPK")


def is_ls(data: bytes) -> bool:
    return len(data) >= 8 and data[:4] == LS_MAGIC


def parse_ls(ls_data: bytes) -> List[Tuple[int, int, int]]:
    """Return (hash, dt_offset, comp_size) for each entry in ls."""
    if not is_ls(ls_data):
        return []
    count = struct.unpack_from("<I", ls_data, 4)[0]
    if count == 0 or count > 100_000:
        return []
    out: List[Tuple[int, int, int]] = []
    for i in range(count):
        eo = 8 + i * 12
        if eo + 12 > len(ls_data):
            break
        out.append(struct.unpack_from("<III", ls_data, eo))
    return out


def decompress_resource(blob: bytes) -> bytes:
    """Find the leading zlib stream in a dt resource and decompress it.

    Returns b'' on failure.
    """
    if len(blob) < 4:
        return b""
    scan = min(512, len(blob) - 1)
    for i in range(scan):
        if blob[i:i + 2] in _ZLIB_HEADERS:
            try:
                return zlib.decompress(blob[i:])
            except zlib.error:
                pass
    return b""


def is_texture_resource(decompressed: bytes) -> bool:
    return len(decompressed) >= 4 and decompressed[:4] in _TEX_MAGICS
