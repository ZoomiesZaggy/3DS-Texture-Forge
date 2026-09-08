"""Yaz0 / SZS decompressor.

Format: https://www.3dbrew.org/wiki/SZS

    0x00  "Yaz0" magic
    0x04  decompressed size (BIG-endian u32)
    0x08  unused (zero)
    0x10  start of compressed payload

Payload uses the same 8-token-per-flag-byte structure as Nintendo LZ but with
slightly different backref encoding:

    bit set -> literal byte
    bit clear -> 2 bytes:
        b1 = data[src]; b2 = data[src+1]
        length = b1 >> 4
        if length == 0:
            length = data[src+2] + 0x12   (3-byte form for big copies)
        else:
            length += 2
        distance = ((b1 & 0xF) << 8) | b2 ; back = pos - distance - 1

Used by .szs files in many 3DS games.
"""

from __future__ import annotations

import logging
import struct
from typing import Optional

from tex_forge.compression.registry import register_compression

logger = logging.getLogger(__name__)

MAX_DECOMP = 50 * 1024 * 1024


def _detect(data: bytes) -> bool:
    return len(data) >= 16 and data[:4] == b"Yaz0"


def _decompress(data: bytes) -> Optional[bytes]:
    if not _detect(data):
        return None
    decomp_size = struct.unpack(">I", data[4:8])[0]
    if decomp_size <= 0 or decomp_size > MAX_DECOMP:
        logger.warning("Yaz0: implausible decompressed size %d", decomp_size)
        return None

    out = bytearray()
    src = 16
    n = len(data)

    try:
        while len(out) < decomp_size and src < n:
            code = data[src]; src += 1
            for bit in range(7, -1, -1):
                if len(out) >= decomp_size:
                    break
                if code & (1 << bit):
                    if src >= n:
                        break
                    out.append(data[src]); src += 1
                else:
                    if src + 1 >= n:
                        break
                    b1 = data[src]; b2 = data[src + 1]; src += 2
                    distance = ((b1 & 0x0F) << 8) | b2
                    length = b1 >> 4
                    if length == 0:
                        if src >= n:
                            break
                        length = data[src] + 0x12; src += 1
                    else:
                        length += 2
                    back = len(out) - distance - 1
                    for j in range(length):
                        if len(out) >= decomp_size:
                            break
                        out.append(out[back + j] if back + j >= 0 else 0)
    except IndexError as e:
        logger.debug("Yaz0 IndexError at src=%d out=%d: %s", src, len(out), e)
        return None

    return bytes(out)


@register_compression("yaz0", priority=90)
class _Yaz0:
    @staticmethod
    def detect(data: bytes) -> bool:
        return _detect(data)

    @staticmethod
    def decompress(data: bytes) -> Optional[bytes]:
        return _decompress(data)
