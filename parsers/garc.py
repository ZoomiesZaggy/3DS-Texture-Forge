"""GARC (Game Freak ARChive) parser for Nintendo 3DS.

GARC v4 format (used by Pokemon X/Y):
  GARC header (0x1C) -> FATO section -> FATB section -> FIMB section -> data

Magic bytes are reversed: CRAG, OTAF, BTAF, BMIF.
Each FATB entry is fixed 16 bytes: vector(4) + start(4) + end(4) + length(4).
"""

import logging
import struct
from typing import List, Tuple

logger = logging.getLogger(__name__)

# Skip GARCs larger than this to avoid excessive memory use
MAX_GARC_SIZE = 500 * 1024 * 1024  # 500 MB


def is_garc(data: bytes) -> bool:
    """Check if data starts with GARC magic (stored as 'CRAG' in LE)."""
    return len(data) >= 0x1C and data[0:4] == b'CRAG'


def parse_garc(data: bytes) -> List[Tuple[str, bytes]]:
    """
    Parse a GARC archive and return inner files as (name, data) tuples.
    GARC files don't have filenames, so names are generated as index-based.
    """
    if not is_garc(data):
        return []

    file_len = len(data)
    if file_len > MAX_GARC_SIZE:
        logger.info(f"GARC: skipping {file_len / 1024 / 1024:.0f} MB archive (limit {MAX_GARC_SIZE // 1024 // 1024} MB)")
        return []

    try:
        return _parse_garc_inner(data)
    except Exception as e:
        logger.warning(f"GARC parse error: {e}")
        return []


def _parse_garc_inner(data: bytes) -> List[Tuple[str, bytes]]:
    file_len = len(data)

    # GARC header (0x1C bytes)
    hdr_size = struct.unpack_from('<I', data, 4)[0]
    bom = struct.unpack_from('<H', data, 8)[0]

    if bom not in (0xFEFF, 0xFFFE):
        logger.warning(f"GARC: unexpected BOM 0x{bom:04X}")
        return []

    data_offset = struct.unpack_from('<I', data, 16)[0]

    # FATO section
    fato_off = hdr_size
    if fato_off + 12 > file_len:
        return []
    if data[fato_off:fato_off + 4] != b'OTAF':
        logger.warning(f"GARC: expected OTAF, got {data[fato_off:fato_off+4]!r}")
        return []

    fato_size = struct.unpack_from('<I', data, fato_off + 4)[0]

    # FATB section
    fatb_off = fato_off + fato_size
    if fatb_off + 12 > file_len:
        return []
    if data[fatb_off:fatb_off + 4] != b'BTAF':
        logger.warning(f"GARC: expected BTAF, got {data[fatb_off:fatb_off+4]!r}")
        return []

    fatb_entry_count = struct.unpack_from('<I', data, fatb_off + 8)[0]

    # Each FATB entry is fixed 16 bytes: vector(4) + start(4) + end(4) + length(4)
    entries_start = fatb_off + 12
    results = []

    for i in range(fatb_entry_count):
        base = entries_start + i * 16
        if base + 16 > file_len:
            break

        start = struct.unpack_from('<I', data, base + 4)[0]
        end = struct.unpack_from('<I', data, base + 8)[0]

        if end <= start:
            continue

        abs_start = data_offset + start
        abs_end = data_offset + end

        if abs_end > file_len or abs_start >= file_len:
            continue

        inner_data = data[abs_start:abs_end]
        ext = _guess_extension(inner_data)
        name = f"{i:04d}{ext}"
        results.append((name, inner_data))

    logger.debug(f"GARC: {fatb_entry_count} entries, {len(results)} files extracted")
    return results


def _guess_extension(data: bytes) -> str:
    """Guess file extension from magic bytes."""
    if len(data) < 4:
        return ".bin"
    magic = data[0:4]
    if magic == b'CGFX':
        return ".cgfx"
    if magic == b'BCH\x00':
        return ".bch"
    if magic == b'CTPK':
        return ".ctpk"
    if magic == b'SARC':
        return ".sarc"
    return ".bin"
