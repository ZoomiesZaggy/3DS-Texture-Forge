"""BLZ (Bottom-LZ / backward LZSS).

Format:
    Footer (last 8 bytes of the file):
        [comp_len: 3 bytes LE]      -- length of compressed region + footer
        [hdr_len: 1 byte]           -- always 8 or 11 for the games we see
        [additional: 4 bytes LE i32] -- extra bytes added by decompression

    The HEAD of the file is uncompressed; compression begins at
    (file_len - comp_len) and runs to the start of the footer.

Decoder runs *backwards* from the end:
    flags = data[src - 1]; src -= 1
    For each of 8 bits, MSB first:
      bit set: backref = read 2 bytes backward, length=(b_hi>>4)+3,
               disp=((b_hi & 0xF)<<8 | b_lo) + 3
      bit clear: literal byte (read backward)

Used by NW4C-engine games (Pac-Man and the Ghostly Adventures, etc.).
Reference: https://github.com/devkitPro/3dstool/blob/master/src/blz.cpp
"""

from __future__ import annotations

import logging
import struct
from typing import Optional

from tex_forge.compression.registry import register_compression

logger = logging.getLogger(__name__)

MAX_DECOMP = 50 * 1024 * 1024


def _peek_footer(data: bytes):
    if len(data) < 12:
        return None
    footer = data[-8:]
    comp_len = footer[0] | (footer[1] << 8) | (footer[2] << 16)
    hdr_len = footer[3]
    additional = struct.unpack_from("<i", footer, 4)[0]
    return comp_len, hdr_len, additional


def _detect_blz(data: bytes) -> bool:
    info = _peek_footer(data)
    if info is None:
        return False
    comp_len, hdr_len, additional = info
    if hdr_len not in (8, 11):
        return False
    if comp_len <= hdr_len or comp_len > len(data):
        return False
    if additional <= 0:
        return False
    decomp_size = len(data) + additional
    if decomp_size > MAX_DECOMP:
        return False
    # Output shouldn't be 5x+ bigger than input -- catches false positives.
    return additional <= len(data) * 5


def _decompress_blz(data: bytes) -> Optional[bytes]:
    info = _peek_footer(data)
    if info is None:
        return None
    comp_len, hdr_len, additional = info
    if comp_len == 0:
        return data  # not actually compressed -- footer flag

    if hdr_len not in (8, 11):
        return None
    if comp_len <= hdr_len or comp_len > len(data):
        return None
    decomp_size = len(data) + additional
    if decomp_size <= 0 or decomp_size > MAX_DECOMP:
        return None

    out = bytearray(decomp_size)
    # The uncompressed head is just the leading bytes; copy them verbatim.
    out[: len(data)] = data

    uncomp_len = len(data) - comp_len
    src = len(data) - hdr_len     # current read pos (just before footer)
    dst = decomp_size              # current write pos (end of output)

    try:
        while src > uncomp_len and dst > uncomp_len:
            src -= 1
            flags = data[src]
            for bit in range(8):
                if src <= uncomp_len or dst <= uncomp_len:
                    break
                if flags & (0x80 >> bit):
                    src -= 1; b_hi = data[src]
                    src -= 1; b_lo = data[src]
                    length = (b_hi >> 4) + 3
                    disp = ((b_hi & 0x0F) << 8 | b_lo) + 3
                    for _ in range(length):
                        dst -= 1
                        if dst < 0:
                            return None
                        rp = dst + disp
                        if rp >= decomp_size:
                            return None
                        out[dst] = out[rp]
                else:
                    src -= 1
                    dst -= 1
                    if dst < 0 or src < 0:
                        return None
                    out[dst] = data[src]
    except (IndexError, ValueError) as e:
        logger.debug("BLZ decode failed: %s", e)
        return None

    if dst != uncomp_len:
        return None
    return bytes(out)


@register_compression("blz", priority=80)
class _BLZ:
    @staticmethod
    def detect(data: bytes) -> bool:
        return _detect_blz(data)

    @staticmethod
    def decompress(data: bytes) -> Optional[bytes]:
        try:
            return _decompress_blz(data)
        except Exception as e:
            logger.debug("BLZ exception: %s", e)
            return None


# Public alias for callers that can't go through the registry.
decompress_blz = _decompress_blz
