"""CRILAYLA -- CRI Middleware's LZSS variant used inside CPK archives.

Format:
    +0x00  "CRILAYLA" magic (8 bytes)
    +0x08  decompressed_body_size u32 LE
    +0x0C  compressed_body_size   u32 LE
    +0x10  compressed body, comp_size bytes; its bitstream is read
           BACKWARDS (from the last body byte toward 0x10), MSB-first
    +0x10 + comp_size  uncompressed prefix (original file's leading bytes,
           usually the 0x100-byte raw header)

The final output is `prefix + reversed-decompression(body)`. The body region
is filled from its high address downward.

Bitstream token encoding (MSB-first within each byte, bytes consumed backward):
    1 bit:
        0 -> literal: the next 8 bits are one output byte
        1 -> back-reference:
                distance = 13 bits + 3
                length   = 3 + a variable-length count assembled from
                           successive 2, 3, 5, then 8-bit chunks. Each chunk
                           is added to the length; while a chunk holds its
                           all-ones maximum, read the next wider chunk and keep
                           adding. After the 8-bit chunk, keep reading 8-bit
                           chunks while each equals 255.
                The copy source is `dest + distance` (already-written bytes at
                a higher address).

This is a genuine variable-length LZSS, not the fixed 2-byte scheme the v1
code implemented. Verified byte-exact against Dragon Ball Fusions CPK entries
and cross-checked against two independent reference ports.

References:
    https://github.com/Sewer56/CriFsV2Lib
    https://github.com/kamikat/cpktools/blob/master/cpk/crilayla.py
"""

from __future__ import annotations

import logging
import struct
from typing import Optional

from tex_forge.compression.registry import register_compression

logger = logging.getLogger(__name__)

#: 64 MB cap. Game data this big never appears in practice; defends against
#: corrupt headers triggering huge allocations.
MAX_DECOMP = 64 * 1024 * 1024


def _detect(data: bytes) -> bool:
    return len(data) >= 0x10 and data[:8] == b"CRILAYLA"


#: Variable-length count chunk widths (bits), read in this order.
_VLE_WIDTHS = (2, 3, 5, 8)


def _decompress(data: bytes) -> Optional[bytes]:
    if not _detect(data):
        return None

    decomp_size = struct.unpack_from("<I", data, 8)[0]
    comp_size   = struct.unpack_from("<I", data, 0x0C)[0]
    if decomp_size <= 0 or decomp_size > MAX_DECOMP:
        return None

    prefix_off = 0x10 + comp_size
    prefix = data[prefix_off:] if prefix_off < len(data) else b""

    # Body bitstream state: consumed from the last body byte backward, MSB
    # first. `bit_pool`/`bits_left` buffer the current byte.
    in_pos = min(0x10 + comp_size - 1, len(data) - 1)
    bit_pool = 0
    bits_left = 0

    def get_bits(n: int) -> int:
        nonlocal in_pos, bit_pool, bits_left
        value = 0
        got = 0
        while got < n:
            if bits_left == 0:
                if in_pos < 0x10:
                    # Ran off the front of the body: feed zero bits, matching
                    # the reference decoders' behaviour on truncated streams.
                    bit_pool = 0
                else:
                    bit_pool = data[in_pos]
                    in_pos -= 1
                bits_left = 8
            take = min(bits_left, n - got)
            value = (value << take) | (
                (bit_pool >> (bits_left - take)) & ((1 << take) - 1)
            )
            bits_left -= take
            got += take
        return value

    out = bytearray(decomp_size)
    oend = decomp_size - 1
    produced = 0

    try:
        while produced < decomp_size:
            if get_bits(1):
                distance = get_bits(13) + 3
                length = 3
                for width in _VLE_WIDTHS:
                    chunk = get_bits(width)
                    length += chunk
                    if chunk != (1 << width) - 1:
                        break
                else:
                    while True:
                        chunk = get_bits(8)
                        length += chunk
                        if chunk != 0xFF:
                            break
                for _ in range(length):
                    if produced >= decomp_size:
                        break
                    dst = oend - produced
                    src = dst + distance
                    out[dst] = out[src] if src < decomp_size else 0
                    produced += 1
            else:
                out[oend - produced] = get_bits(8)
                produced += 1
    except (IndexError, ValueError) as e:
        logger.debug("CRILAYLA decode failed at produced=%d in_pos=%d: %s",
                     produced, in_pos, e)
        return None

    return bytes(prefix) + bytes(out)


@register_compression("crilayla", priority=95, note="CRI CPK CRILAYLA wrapper")
class _Crilayla:
    @staticmethod
    def detect(data: bytes) -> bool:
        return _detect(data)

    @staticmethod
    def decompress(data: bytes) -> Optional[bytes]:
        return _decompress(data)


# Public alias for callers that bypass the registry (the vendored CPK code).
decompress_crilayla = _decompress
