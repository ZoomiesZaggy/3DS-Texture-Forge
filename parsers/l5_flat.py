"""Level-5 flat file archive parser.

Used by Fantasy Life and potentially other Level-5 games.

Format:
  u32  entry_count
  u32  padding (0)
  u32[entry_count]  file offsets (monotonically increasing)
  ...file data...

Each file entry is typically LZ11-compressed. Decompressed entries may
contain CGFX, BCH, CTPK, or IMGC texture containers.
"""

import struct
import logging
from typing import Iterator, Tuple

logger = logging.getLogger(__name__)


def is_l5_flat(data: bytes) -> bool:
    """Check if data looks like a Level-5 flat file archive."""
    if len(data) < 16:
        return False
    entry_count = struct.unpack_from('<I', data, 0)[0]
    padding = struct.unpack_from('<I', data, 4)[0]
    if padding != 0:
        return False
    if entry_count < 10 or entry_count > 200000:
        return False
    # Verify first offset is plausible (after the offset table)
    min_data_start = 8 + entry_count * 4
    if min_data_start > len(data):
        return False
    first_offset = struct.unpack_from('<I', data, 8)[0]
    # First offset should be >= table end and within file bounds
    if first_offset < min_data_start or first_offset >= len(data):
        return False
    return True


def iter_l5_flat(data: bytes) -> Iterator[Tuple[str, bytes]]:
    """Iterate over entries in a Level-5 flat file archive.

    Yields (name, entry_data) tuples.
    """
    if len(data) < 16:
        return
    entry_count = struct.unpack_from('<I', data, 0)[0]
    if entry_count > 200000:
        return

    # Read offset table
    offsets = []
    for i in range(entry_count):
        table_off = 8 + i * 4
        if table_off + 4 > len(data):
            break
        off = struct.unpack_from('<I', data, table_off)[0]
        offsets.append(off)

    if not offsets:
        return

    # Compute sizes from consecutive offsets
    for i in range(len(offsets)):
        start = offsets[i]
        if i + 1 < len(offsets):
            end = offsets[i + 1]
        else:
            end = len(data)

        size = end - start
        if size <= 0 or start >= len(data):
            continue
        if size > 50 * 1024 * 1024:  # 50MB safety limit per entry
            continue

        entry_data = data[start:start + size]
        name = f"entry_{i:05d}.bin"
        yield name, entry_data
