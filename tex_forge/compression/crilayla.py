"""CRILAYLA -- CRI Middleware's LZSS variant used inside CPK archives.

Format:
    +0x00  "CRILAYLA" magic (8 bytes)
    +0x08  decompressed_body_size u32 LE
    +0x0C  compressed_body_size   u32 LE
    +0x10  compressed body, read BACKWARDS (comp_size bytes)
    +0x10 + comp_size  uncompressed prefix (original file's leading bytes)

The final output is `prefix + reversed-decompression(body)`.

Bit-level flags + 2-byte backref encoding:
    flag byte (8 bits, MSB-first):
        bit set -> backref: read 2 bytes BACKWARD; length = (hi >> 3) + 3,
                   distance = ((hi & 7) << 8) | lo
        bit clear -> literal byte (1 byte backward)

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


def _decompress(data: bytes) -> Optional[bytes]:
    if not _detect(data):
        return None

    decomp_size = struct.unpack_from("<I", data, 8)[0]
    comp_size   = struct.unpack_from("<I", data, 0x0C)[0]
    if decomp_size <= 0 or decomp_size > MAX_DECOMP:
        return None

    prefix_off = 0x10 + comp_size
    prefix = data[prefix_off:] if prefix_off < len(data) else b""

    out = bytearray(decomp_size)
    out_pos = decomp_size
    # Read body in reverse: from the last byte before prefix down to 0x10.
    in_pos = min(0x10 + comp_size - 1, len(data) - 1)

    try:
        while out_pos > 0 and in_pos >= 0x10:
            flag = data[in_pos]; in_pos -= 1
            for bit in range(8):
                if out_pos <= 0 or in_pos < 0x10:
                    break
                if flag & (0x80 >> bit):
                    if in_pos < 0x11:
                        break
                    hi = data[in_pos]; in_pos -= 1
                    lo = data[in_pos]; in_pos -= 1
                    length = (hi >> 3) + 3
                    dist   = ((hi & 0x07) << 8) | lo
                    for _ in range(length):
                        if out_pos <= 0:
                            break
                        out_pos -= 1
                        rp = out_pos + dist + 1
                        out[out_pos] = out[rp] if rp < decomp_size else 0
                else:
                    out_pos -= 1
                    out[out_pos] = data[in_pos]; in_pos -= 1
    except (IndexError, ValueError) as e:
        logger.debug("CRILAYLA decode failed at out_pos=%d in_pos=%d: %s",
                     out_pos, in_pos, e)
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
