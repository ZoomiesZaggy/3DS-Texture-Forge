"""
Nintendo SARC (Simple ARChive) parser.

Used by many 3DS/Wii U games to bundle assets (textures, layouts, animations).
Common extensions: .arc, .sarc, .szs (compressed), .bars

Structure:
  SARC header (0x14 bytes)
  SFAT section (file allocation table)
  SFNT section (filename table)
  File data (at data_offset from SARC header)

Byte order determined by BOM field in SARC header.
"""

import logging
import struct
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


def is_sarc(data: bytes) -> bool:
    """Check if data starts with SARC magic."""
    return len(data) >= 0x14 and data[0:4] == b'SARC'


def parse_sarc(data: bytes) -> List[Tuple[str, bytes]]:
    """
    Parse a SARC archive and return list of (filename, file_data) tuples.

    Returns empty list on parse failure.
    """
    if not is_sarc(data):
        return []

    try:
        return _parse_sarc_inner(data)
    except Exception as e:
        logger.warning(f"SARC parse error: {e}")
        return []


def _parse_sarc_inner(data: bytes) -> List[Tuple[str, bytes]]:
    # SARC header (0x14 bytes)
    # 0x00: magic 'SARC'
    # 0x04: header_length (u16)
    # 0x06: BOM (u16) - 0xFEFF=BE, 0xFFFE=LE
    # 0x08: file_size (u32)
    # 0x0C: data_offset (u32)
    # 0x10: version (u16)
    # 0x12: reserved (u16)

    bom_bytes = data[6:8]
    if bom_bytes == b'\xFF\xFE':
        bo = '<'  # little-endian
    elif bom_bytes == b'\xFE\xFF':
        bo = '>'  # big-endian
    else:
        logger.warning(f"Unknown SARC BOM: {bom_bytes.hex()}")
        bo = '<'  # default to LE for 3DS

    hdr_len = struct.unpack_from(bo + 'H', data, 4)[0]
    file_size = struct.unpack_from(bo + 'I', data, 8)[0]
    data_offset = struct.unpack_from(bo + 'I', data, 0x0C)[0]

    if data_offset > len(data):
        logger.warning(f"SARC data_offset 0x{data_offset:X} > file size {len(data)}")
        return []

    # SFAT section (immediately after SARC header)
    sfat_off = hdr_len
    if sfat_off + 0x0C > len(data):
        return []

    sfat_magic = data[sfat_off:sfat_off + 4]
    if sfat_magic != b'SFAT':
        logger.warning(f"Expected SFAT, got {sfat_magic!r}")
        return []

    sfat_hdr_len = struct.unpack_from(bo + 'H', data, sfat_off + 4)[0]
    node_count = struct.unpack_from(bo + 'H', data, sfat_off + 6)[0]
    # hash_multiplier at sfat_off + 8 (u32), not needed for extraction

    nodes_start = sfat_off + sfat_hdr_len
    sfat_end = nodes_start + node_count * 16

    # SFNT section (after SFAT nodes)
    if sfat_end + 8 > len(data):
        return []

    sfnt_magic = data[sfat_end:sfat_end + 4]
    if sfnt_magic != b'SFNT':
        logger.warning(f"Expected SFNT, got {sfnt_magic!r}")
        return []

    sfnt_hdr_len = struct.unpack_from(bo + 'H', data, sfat_end + 4)[0]
    strings_start = sfat_end + sfnt_hdr_len

    # Parse nodes
    results = []
    for i in range(node_count):
        node_off = nodes_start + i * 16
        if node_off + 16 > len(data):
            break

        # name_hash = struct.unpack_from(bo + 'I', data, node_off)[0]
        attrs = struct.unpack_from(bo + 'I', data, node_off + 4)[0]
        file_start = struct.unpack_from(bo + 'I', data, node_off + 8)[0]
        file_end = struct.unpack_from(bo + 'I', data, node_off + 12)[0]

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
                name = data[noff:end].decode('utf-8', errors='replace')

        abs_start = data_offset + file_start
        abs_end = data_offset + file_end

        if abs_start > len(data):
            logger.debug(f"SARC node {i} ({name}): start 0x{abs_start:X} out of bounds")
            continue
        if abs_end > len(data):
            abs_end = len(data)

        file_data = data[abs_start:abs_end]
        results.append((name, file_data))

    logger.info(f"SARC: parsed {len(results)} files from {node_count} nodes")
    return results
