"""Grezzo GAR archive parser for 3DS games (Zelda MM3D, etc.).

GAR v2 is Grezzo's second-generation asset container. Instead of parsing
the complex entry table (which has multiple indirection levels), we scan
for known texture container magic bytes and extract them by size.

ctxb format: magic "ctxb" (4 bytes) + total_size (u32 LE) at offset +4.
"""

import struct
import logging

logger = logging.getLogger(__name__)


def is_gar(data: bytes) -> bool:
    """Check if data starts with GAR magic (any version)."""
    return len(data) >= 4 and data[:3] == b'GAR'


def parse_gar(data: bytes):
    """Scan a GAR archive for embedded texture containers.

    Yields (index, name, file_data) for each ctxb found.
    Uses a scan approach since the GAR entry table uses complex indirection.
    """
    if not is_gar(data) or len(data) < 0x20:
        return

    idx = 0
    offset = 0

    while offset < len(data) - 8:
        chunk = data[offset:offset+4]

        if chunk == b'ctxb':
            if offset + 8 <= len(data):
                total_size = struct.unpack_from('<I', data, offset + 4)[0]
                if 8 < total_size <= len(data) - offset:
                    yield (idx, f'gar_ctxb_{idx:04d}.ctxb', data[offset:offset + total_size])
                    idx += 1
                    offset += total_size
                    continue

        elif chunk == b'cmb ':
            if offset + 8 <= len(data):
                total_size = struct.unpack_from('<I', data, offset + 4)[0]
                if 8 < total_size <= len(data) - offset:
                    yield (idx, f'gar_cmb_{idx:04d}.cmb', data[offset:offset + total_size])
                    idx += 1
                    offset += total_size
                    continue

        offset += 4

    if idx > 0:
        logger.debug(f"GAR: extracted {idx} embedded files (ctxb/cmb)")
