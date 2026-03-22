"""Capcom MT Framework ARC archive parser for 3DS games (MH4U, etc.).

ARC format (version 0x13/0x19):
  Header (8 bytes):
    0x00  magic 'ARC\x00'
    0x04  version u16 (0x0013 for MH4U 3DS)
    0x06  num_entries u16

  Entry (80 bytes):
    0x00  data_offset u32  (absolute file offset; 0 = no in-archive data)
    0x04  filename[64]     (null-terminated, no extension — extension via hash)
    0x44  ext_hash u32     (hash of extension string)
    0x48  next_csize u32   (compressed size of the NEXT entry)
    0x4C  next_info u32    (0x20000000 | decompressed_size of the NEXT entry)

  Layout: entry N stores size info for entry N+1.
  Entry N's compressed size = prev_entry.next_csize
  Entry N's decompressed size = prev_entry.next_info & 0x1FFFFFFF
  Compression: zlib if next_info bit 29 set.

TEX extension hash (MH4U): 0x241F5DEB
"""

import struct
import logging
import zlib

logger = logging.getLogger(__name__)

# Known ext_hash for TEX format in MH4U
MH4U_TEX_HASH = 0x241F5DEB

MAGIC = b'ARC\x00'
ENTRY_SIZE = 80


def is_capcom_arc(data: bytes) -> bool:
    """Check if data starts with Capcom ARC magic."""
    return len(data) >= 8 and data[:4] == MAGIC


def parse_capcom_arc(data: bytes, tex_hash: int = MH4U_TEX_HASH):
    """Parse a Capcom ARC archive, yielding decompressed TEX file data.

    Yields (filename, decompressed_data) for each entry whose ext_hash
    matches tex_hash and whose decompressed content starts with 'TEX\x00'.

    The ARC stores size info for entry N in entry N-1's fields:
      entry[N].csize   = entry[N-1].next_csize
      entry[N].deco    = entry[N-1].next_info & 0x1FFFFFFF
      entry[N].is_comp = bool(entry[N-1].next_info & 0x20000000)
    """
    if not is_capcom_arc(data):
        return

    num_entries = struct.unpack_from('<H', data, 6)[0]
    if num_entries == 0 or num_entries > 65535:
        return

    file_len = len(data)
    count = 0

    for idx in range(num_entries):
        eoff = 8 + idx * ENTRY_SIZE
        if eoff + ENTRY_SIZE > file_len:
            break

        ext_hash = struct.unpack_from('<I', data, eoff + 0x44)[0]
        if ext_hash != tex_hash:
            continue

        data_offset = struct.unpack_from('<I', data, eoff)[0]
        if data_offset == 0 or idx == 0:
            continue  # No in-archive data or no predecessor

        # Get csize/deco from the preceding entry's fields
        prev_eoff = 8 + (idx - 1) * ENTRY_SIZE
        csize = struct.unpack_from('<I', data, prev_eoff + 0x48)[0]
        next_info = struct.unpack_from('<I', data, prev_eoff + 0x4C)[0]
        is_compressed = bool(next_info & 0x20000000)

        if csize == 0 or data_offset + csize > file_len:
            continue

        try:
            raw = data[data_offset:data_offset + csize]
            if is_compressed:
                dec = zlib.decompress(raw)
            else:
                dec = raw

            if not dec or dec[:4] != b'TEX\x00':
                continue

            fname_raw = data[eoff + 4:eoff + 68]
            null_p = fname_raw.find(b'\x00')
            fname = (fname_raw[:null_p] if null_p >= 0 else fname_raw).decode(
                'latin1', errors='replace'
            )

            yield fname, dec
            count += 1

        except Exception:
            continue

    if count > 0:
        logger.debug(f"Capcom ARC: extracted {count} TEX files")
