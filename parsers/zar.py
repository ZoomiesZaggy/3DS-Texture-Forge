"""ZAR (Grezzo ARchive) parser for Nintendo 3DS.

ZAR v1 format (used by OoT3D, MM3D):
  Header: 'ZAR\\x01' magic, file_size, num_types, num_files,
          type_table_offset, file_table_offset, data_offset
  File table: entries of (file_size: u32, name_offset: u32)
  Data: files packed sequentially starting at data_offset
"""

import logging
import struct
from typing import List, Tuple

logger = logging.getLogger(__name__)

MAX_ZAR_SIZE = 100 * 1024 * 1024  # 100 MB


def is_zar(data: bytes) -> bool:
    """Check if data is a ZAR archive."""
    return len(data) >= 0x18 and data[0:4] == b'ZAR\x01'


def parse_zar(data: bytes) -> List[Tuple[str, bytes]]:
    """Parse a ZAR archive and return inner files as (name, data) tuples."""
    if not is_zar(data):
        return []

    file_len = len(data)
    if file_len > MAX_ZAR_SIZE:
        logger.info(f"ZAR: skipping {file_len / 1024 / 1024:.0f} MB archive")
        return []

    try:
        return _parse_zar_inner(data)
    except Exception as e:
        logger.warning(f"ZAR parse error: {e}")
        return []


def _parse_zar_inner(data: bytes) -> List[Tuple[str, bytes]]:
    file_len = len(data)

    # Header
    zar_file_size = struct.unpack_from('<I', data, 0x04)[0]
    num_types = struct.unpack_from('<H', data, 0x08)[0]
    num_files = struct.unpack_from('<H', data, 0x0A)[0]
    type_table_off = struct.unpack_from('<I', data, 0x0C)[0]
    file_table_off = struct.unpack_from('<I', data, 0x10)[0]
    data_off = struct.unpack_from('<I', data, 0x14)[0]

    if num_files == 0 or num_files > 10000:
        return []
    if file_table_off >= file_len or data_off >= file_len:
        return []

    results = []
    current_data_off = data_off

    for i in range(num_files):
        entry_off = file_table_off + i * 8
        if entry_off + 8 > file_len:
            break

        fsize = struct.unpack_from('<I', data, entry_off)[0]
        name_off = struct.unpack_from('<I', data, entry_off + 4)[0]

        # Read name
        name = ""
        if name_off < file_len:
            name_end = name_off
            while name_end < min(name_off + 256, file_len) and data[name_end] != 0:
                name_end += 1
            try:
                name = data[name_off:name_end].decode('ascii', errors='replace')
            except Exception:
                pass

        if not name:
            name = f"{i:04d}.bin"

        # Bounds check: reject entries that exceed file bounds
        if fsize > file_len or current_data_off + fsize > file_len:
            logger.warning(f"ZAR entry {i} ({name}): fsize {fsize} exceeds file bounds, stopping")
            break

        # Extract file data
        if current_data_off + fsize > file_len:
            inner_data = data[current_data_off:file_len]
        else:
            inner_data = data[current_data_off:current_data_off + fsize]

        if fsize > 0:
            results.append((name, inner_data))

        current_data_off += fsize

    logger.debug(f"ZAR: {num_files} entries, {len(results)} files extracted")
    return results
