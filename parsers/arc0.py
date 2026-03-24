"""Level-5 ARC0 archive parser for 3DS games.

ARC0 is Level-5's main archive format, used in Professor Layton, Yo-Kai Watch,
and Layton vs Phoenix Wright.  The archive structure is:

  [0x00]  Header (variable size, typically 0x48+ bytes)
          magic: "ARC0" (4)
          header_size u32 LE
          ... metadata offsets ...
          data_section_offset at +0x14

  [header_size .. data_offset]  Compressed metadata sections
          (directory table, file table, name table — Level-5 custom compression)

  [data_offset ..]  File data, stored as XPCK sub-containers

Level-5 games store most textures in their proprietary IMGC/.xi format,
but some also contain standard 3DS texture formats (BCH, CGFX, CTPK) embedded
in the data section.  This parser extracts those standard-format textures by
scanning the raw archive data for known magic bytes.

For files that are LZ10-compressed within XPCK entries, the parser also
attempts decompression and checks the result for texture magics.
"""

import struct
import logging
from typing import Iterator, Tuple

logger = logging.getLogger(__name__)

ARC0_MAGIC = b'ARC0'
XPCK_MAGIC = b'XPCK'

# Standard 3DS texture magics we scan for within ARC0 data
_TEXTURE_MAGICS = (
    b'BCH\x00',
    b'CGFX',
    b'CTPK',
)

# BFLIM/BCLIM are footer-based so harder to scan for; skip in scan mode.

# Minimum size for a texture blob to be worth extracting
_MIN_BLOB = 64


def is_arc0(data: bytes) -> bool:
    """Check if data starts with ARC0 magic."""
    return len(data) >= 8 and data[:4] == ARC0_MAGIC


def _lz10_try_decompress(data: bytes) -> bytes:
    """Attempt Nintendo LZ10 decompression with Level-5 4-byte header.

    Level-5 encodes: u32 LE where method = val & 7, dec_size = val >> 3.
    Method 1 = standard LZ10 bitstream.
    Returns decompressed data or empty bytes on failure.
    """
    if len(data) < 8:
        return b''
    val = struct.unpack_from('<I', data, 0)[0]
    method = val & 7
    if method != 1:
        return b''
    dec_size = val >> 3
    if dec_size == 0 or dec_size > 16 * 1024 * 1024:
        return b''

    pos = 4
    output = bytearray()
    try:
        while len(output) < dec_size and pos < len(data):
            flags = data[pos]
            pos += 1
            for bit in range(8):
                if len(output) >= dec_size:
                    break
                if flags & (0x80 >> bit):
                    if pos + 1 >= len(data):
                        break
                    b0 = data[pos]
                    b1 = data[pos + 1]
                    pos += 2
                    length = (b0 >> 4) + 3
                    disp = ((b0 & 0x0F) << 8) | b1
                    for _ in range(length):
                        if len(output) >= dec_size:
                            break
                        idx = len(output) - disp - 1
                        output.append(output[idx] if 0 <= idx < len(output) else 0)
                else:
                    if pos >= len(data):
                        break
                    output.append(data[pos])
                    pos += 1
    except Exception:
        pass
    return bytes(output[:dec_size])


def _find_texture_blobs(data: bytes, base_offset: int = 0) -> Iterator[Tuple[str, bytes]]:
    """Scan data for standard 3DS texture magic bytes and yield (label, blob)."""
    for magic in _TEXTURE_MAGICS:
        offset = 0
        while offset < len(data) - len(magic):
            idx = data.find(magic, offset)
            if idx < 0:
                break

            # Estimate blob size
            remaining = len(data) - idx
            if magic == b'BCH\x00' and remaining >= 0x20:
                # BCH: use data_addr from header to estimate size
                data_addr = struct.unpack_from('<I', data, idx + 0x14)[0]
                if 0 < data_addr < remaining:
                    blob_size = min(data_addr + 8 * 1024 * 1024, remaining)
                else:
                    blob_size = min(remaining, 512 * 1024)
            elif magic == b'CTPK' and remaining >= 0x10:
                # CTPK: header has file size at +0x08
                ctpk_size = struct.unpack_from('<I', data, idx + 0x08)[0]
                blob_size = min(ctpk_size + 0x100, remaining) if 0 < ctpk_size < remaining else min(remaining, 4 * 1024 * 1024)
            elif magic == b'CGFX' and remaining >= 0x10:
                cgfx_size = struct.unpack_from('<I', data, idx + 0x08)[0]
                blob_size = min(cgfx_size + 0x100, remaining) if 0 < cgfx_size < remaining else min(remaining, 4 * 1024 * 1024)
            else:
                blob_size = min(remaining, 4 * 1024 * 1024)

            if blob_size >= _MIN_BLOB:
                label = f"arc0@0x{base_offset + idx:X}[{magic[:4].decode('ascii', errors='replace').strip()}]"
                yield label, data[idx:idx + blob_size]

            offset = idx + max(4, blob_size)


def iter_arc0_textures(data: bytes) -> Iterator[Tuple[str, bytes]]:
    """Yield (path, texture_data) for texture-bearing blobs found in an ARC0 archive.

    Scans the data section for standard 3DS texture magics (BCH, CGFX, CTPK).
    Also attempts LZ10 decompression on sub-entries that might contain compressed textures.
    """
    if not is_arc0(data):
        return

    if len(data) < 0x18:
        return

    header_size = struct.unpack_from('<I', data, 4)[0]
    data_offset = struct.unpack_from('<I', data, 0x14)[0]

    if data_offset == 0 or data_offset >= len(data):
        data_offset = header_size

    logger.debug(f"ARC0: header_size=0x{header_size:X}, data_offset=0x{data_offset:X}, "
                 f"file_size={len(data):,}")

    # Scan the data section for standard texture magics
    data_section = data[data_offset:]
    found = 0
    for label, blob in _find_texture_blobs(data_section, data_offset):
        found += 1
        yield label, blob

    # Also scan for XPCK entries and try LZ decompression on their sub-files
    xpck_count = 0
    offset = data_offset
    while offset < len(data) - 4:
        idx = data.find(XPCK_MAGIC, offset)
        if idx < 0:
            break
        xpck_count += 1

        # Try to find LZ10-compressed blobs within the XPCK data area
        # XPCK entries vary in size; scan a reasonable window
        next_xpck = data.find(XPCK_MAGIC, idx + 4)
        if next_xpck < 0:
            xpck_end = len(data)
        else:
            xpck_end = next_xpck
        xpck_data = data[idx:xpck_end]

        # Look for Level-5 LZ10 headers (method byte & 7 == 1) within XPCK data
        for lz_off in range(16, min(len(xpck_data) - 4, 256), 4):
            lz_val = struct.unpack_from('<I', xpck_data, lz_off)[0]
            if (lz_val & 7) == 1:
                dec_size = lz_val >> 3
                if 256 < dec_size < 4 * 1024 * 1024:
                    decompressed = _lz10_try_decompress(xpck_data[lz_off:])
                    if len(decompressed) >= 64:
                        # Check if decompressed data has a texture magic
                        for magic in _TEXTURE_MAGICS:
                            if decompressed[:4] == magic:
                                label = f"arc0>xpck@0x{idx:X}+0x{lz_off:X}[lz10][{magic[:4].decode('ascii', errors='replace').strip()}]"
                                yield label, decompressed
                                found += 1
                                break

        offset = idx + 4

    if found:
        logger.info(f"ARC0: found {found} standard texture blobs in {xpck_count} XPCK entries")
    else:
        logger.debug(f"ARC0: no standard texture blobs in {xpck_count} XPCK entries "
                     f"(Level-5 games typically use proprietary IMGC format)")
