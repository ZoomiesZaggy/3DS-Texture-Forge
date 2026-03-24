"""Intelligent Systems ARC archive parser for Fire Emblem: Awakening (3DS).

IS ARC format (Fire Emblem: Awakening, FE Fates, etc.):
  The archive has a 16-byte header followed by 16 zero bytes of padding,
  then sequential LZ-compressed entries beginning at offset 0x20.

Header (16 bytes):
  0x00  u32 LE  file_size (equals len(data))
  0x04  u32 LE  data_region_end
  0x08  u32 LE  num_entries
  0x0C  u32 LE  reserved/unknown

Entries at 0x20+:
  Each entry is a complete LZ-compressed file (LZ10/11/13 header + payload).
  In FE:A, entry 0 is typically non-texture game data (LZ13),
  and entry 1 at offset 0x24 is typically an LZ-compressed CTPK texture pack.

Detection: first 4 bytes = LE file_size == len(data), offset 0x24 has LZ magic.
"""

import struct
import logging

logger = logging.getLogger(__name__)


def is_fe_arc(data: bytes) -> bool:
    """Check if data looks like a Fire Emblem IS ARC archive."""
    if len(data) < 0x28:
        return False
    # First 4 bytes = LE file_size should match actual file length
    stored_size = struct.unpack_from('<I', data, 0)[0]
    if stored_size != len(data):
        return False
    # Must not be Capcom ARC (ARC\x00)
    if data[:4] == b'ARC\x00':
        return False
    # Offset 0x20 or 0x24 should have an LZ magic byte
    if data[0x20] not in (0x10, 0x11, 0x13) and data[0x24] not in (0x10, 0x11, 0x13):
        return False
    # num_entries at 0x08 should be a small number
    num_entries = struct.unpack_from('<I', data, 8)[0]
    if num_entries < 1 or num_entries > 64:
        return False
    return True


def parse_fe_arc(data: bytes):
    """Parse a Fire Emblem IS ARC archive, yielding (index, name, file_data) for each CTPK found.

    Scans entries at known positions (0x20, 0x24, 0x28, ...) for LZ-compressed
    CTPK texture packs, decompresses them, and yields the results.
    """
    from parsers.lz import decompress_lz

    if not is_fe_arc(data):
        return

    num_entries = struct.unpack_from('<I', data, 8)[0]
    idx = 0

    # Try each candidate entry offset (4-byte stride starting at 0x20)
    # In practice, CTPK entries are always at 0x24 (entry 1), but scan a few
    for entry_off in range(0x20, min(0x20 + num_entries * 4 + 4, len(data) - 3), 4):
        if data[entry_off] not in (0x10, 0x11, 0x13):
            continue
        dec = decompress_lz(data[entry_off:])
        if dec is None:
            continue
        magic4 = dec[:4]
        if magic4 == b'CTPK':
            yield (idx, f'fe_arc_ctpk_{idx:04d}.ctpk', dec)
            idx += 1
        elif magic4 == b'CGFX':
            yield (idx, f'fe_arc_cgfx_{idx:04d}.cgfx', dec)
            idx += 1
        elif magic4 == b'BCH\x00':
            yield (idx, f'fe_arc_bch_{idx:04d}.bch', dec)
            idx += 1

    if idx > 0:
        logger.debug(f"FE ARC: extracted {idx} texture files")
