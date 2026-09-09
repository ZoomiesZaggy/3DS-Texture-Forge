"""Nintendo darc (Data ARChive) parser for 3DS games.

darc is Nintendo's data archive format used in Kid Icarus: Uprising
and other 3DS titles. Magic bytes: 'darc' + BOM 0xFEFF (little-endian).

Header (0x1C bytes):
  0x00  magic 'darc'
  0x04  BOM u16 (0xFEFF = LE)
  0x06  header_size u16 (typically 0x1C)
  0x08  version u32 (0x01000000)
  0x0C  file_size u32
  0x10  entry_table_offset u32 (= header_size)
  0x14  name_table_size u32
  0x18  data_offset u32 (absolute file offset to data region)

Entry table starts at header_size. Root entry (index 0) gives total entry count.
Each entry (12 bytes):
  u32 name_word:  low 24 bits = UTF-16LE name offset in name table,
                  high byte = 0x01 for directory
  u32 w1:  file = absolute data offset, dir = first child index
  u32 w2:  file = size in bytes,         dir = one-past-last child index

Name table starts right after entry table (hdr_size + num_entries * 12).
Names are UTF-16LE, null-terminated (2 zero bytes).
"""

import struct
import logging

logger = logging.getLogger(__name__)


def is_darc(data: bytes) -> bool:
    """Check if data starts with darc magic and LE BOM."""
    if len(data) < 8:
        return False
    return data[:4] == b'darc' and data[4:6] == b'\xff\xfe'


def parse_darc(data: bytes):
    """Parse a darc archive, yielding (name, file_data) for each file entry.

    Skips directory entries; yields only file entries.
    Nested .arc sub-archives are yielded as-is (caller can recurse).
    """
    if not is_darc(data):
        return

    hdr_size = struct.unpack_from('<H', data, 6)[0]
    data_offset_base = struct.unpack_from('<I', data, 24)[0]

    if len(data) < hdr_size + 12:
        return

    # Root entry (index 0): w2 = total entry count
    num_entries = struct.unpack_from('<I', data, hdr_size + 8)[0]
    if num_entries < 1 or num_entries > 100000:
        return

    entry_table_end = hdr_size + num_entries * 12
    name_table_start = entry_table_end

    if name_table_start > len(data):
        return

    def get_name(name_off: int) -> str:
        pos = name_table_start + name_off
        end = pos
        while end + 1 < len(data) and (data[end] != 0 or data[end + 1] != 0):
            end += 2
        try:
            return data[pos:end].decode('utf-16-le', errors='replace')
        except Exception:
            return ''

    count = 0
    for idx in range(1, num_entries):  # Skip index 0 (root dir)
        eoff = hdr_size + idx * 12
        if eoff + 12 > len(data):
            break

        w0 = struct.unpack_from('<I', data, eoff)[0]
        w1 = struct.unpack_from('<I', data, eoff + 4)[0]
        w2 = struct.unpack_from('<I', data, eoff + 8)[0]

        is_dir = (w0 >> 24) & 0xFF == 0x01
        if is_dir:
            continue

        name_off = w0 & 0x00FFFFFF
        name = get_name(name_off) or f'darc_{idx:04d}'
        file_abs = w1   # absolute offset in the darc file
        file_size = w2

        if file_size == 0 or file_abs + file_size > len(data):
            continue

        yield (name, data[file_abs:file_abs + file_size])
        count += 1

    if count > 0:
        logger.debug(f"darc: yielded {count} files")
