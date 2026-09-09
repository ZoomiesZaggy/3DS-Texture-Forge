"""
Super Smash Bros. for Nintendo 3DS — dt/ls archive extractor.

The game stores almost all resources in a monolithic 'dt' file indexed by
a companion 'ls' file.

ls format (magic b'of\x01\x00'):
  Header:  4 bytes magic + uint32 entry_count
  Entries: entry_count × 12 bytes each
    uint32 hash       — CRC/hash of the resource name (used as ID)
    uint32 dt_offset  — byte offset of the resource inside 'dt'
    uint32 comp_size  — byte length of the compressed resource

dt format:
  Each resource starts with optional CC-padding, then a zlib-compressed
  payload beginning with 0x78 0x9C (or 0x78 0xDA / 0x78 0x01).
  The decompressed data can be BCH\x00, CGFX, CTPK, or game-specific
  formats (ATKD, ACMD, EFCC, etc. — only texture containers are kept).
"""

import struct
import zlib
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

LS_MAGIC = b"of\x01\x00"
_ZLIB_MAGIC = {b"\x78\x9C", b"\x78\xDA", b"\x78\x01", b"\x78\x5E"}
_TEX_MAGIC = {b"BCH\x00", b"CGFX", b"CTPK"}


def parse_ls(ls_data: bytes) -> List[Tuple[int, int, int]]:
    """Parse ls index file.

    Returns list of (hash, dt_offset, comp_size) tuples.
    Returns [] if the data does not look like a valid ls file.
    """
    if len(ls_data) < 8 or ls_data[:4] != LS_MAGIC:
        return []
    count = struct.unpack_from("<I", ls_data, 4)[0]
    if count == 0 or count > 100_000:
        return []
    entries: List[Tuple[int, int, int]] = []
    for i in range(count):
        off = 8 + i * 12
        if off + 12 > len(ls_data):
            break
        h, dt_off, comp_sz = struct.unpack_from("<III", ls_data, off)
        entries.append((h, dt_off, comp_sz))
    return entries


def decompress_resource(resource: bytes) -> bytes:
    """Decompress one dt resource.

    Scans the first 512 bytes for a zlib magic word, then decompresses.
    Returns the decompressed bytes, or b'' on failure.
    """
    if len(resource) < 4:
        return b""
    scan_limit = min(512, len(resource) - 1)
    for i in range(scan_limit):
        if resource[i : i + 2] in _ZLIB_MAGIC:
            try:
                return zlib.decompress(resource[i:])
            except zlib.error:
                pass
    return b""


def is_texture_resource(decompressed: bytes) -> bool:
    """Return True if the decompressed bytes start with a known texture magic."""
    return len(decompressed) >= 4 and decompressed[:4] in _TEX_MAGIC
