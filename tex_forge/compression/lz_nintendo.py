"""Nintendo LZ10 / LZ11 / LZ13 decompressors.

Format:
    type byte (0x10/0x11/0x13) | size[24-bit LE] | <payload>

If the 24-bit size is zero, an extra 32-bit LE size follows (used by GARC's
big payloads).

LZ10 (= "LZ-0x10" in DSDecmp):
    Each 8-token group prefixed by a flag byte. Flag bits set MSB-first.
    Literal bit -> copy 1 byte from input.
    Backref bit -> 2 bytes:  [length-3:4][distance-1:12].

LZ11 (= "LZ-0x11"):
    Flag byte same. Backref encoding has *three* size variants chosen by
    the high nibble of the indicator byte:
      top == 0:   3-byte backref encoding longer matches up to 0x110
      top == 1:   4-byte backref for matches up to 0x10110
      top  > 1:   2-byte backref (top + 1 length, like LZ10 but bias=0)

LZ13:
    Type byte 0x13 with an outer size; payload is a complete LZ11 stream
    (often with its own 0x11 type byte). For odd cases we fall back to a
    reverse-LZ11 interpretation -- some Atlus games store LZ13 backwards.

References:
    - DSDecmp source:  https://github.com/einstein95/dsdecmp/blob/master/CSharp/DSDecmp/Formats/Nitro/LZ10.cs
    - GBATEK swizzle / LZSS docs (Nintendo NDS variants).
"""

from __future__ import annotations

import logging
import struct
from typing import Optional, Tuple

from tex_forge.compression.registry import register_compression

logger = logging.getLogger(__name__)

#: 50 MB safety cap. Real-world LZ-compressed assets in 3DS games are well under 32 MB.
MAX_DECOMP = 50 * 1024 * 1024


def _read_header(data: bytes) -> Optional[Tuple[int, int]]:
    """Return (decompressed_size, payload_start). None if implausible."""
    if len(data) < 4:
        return None
    size = struct.unpack_from("<I", data, 0)[0] >> 8
    start = 4
    if size == 0:
        if len(data) < 8:
            return None
        size = struct.unpack_from("<I", data, 4)[0]
        start = 8
    if size <= 0 or size > MAX_DECOMP:
        return None
    return size, start


def _is_lz_byte_plausible(data: bytes, expected_byte: int) -> bool:
    """Cheap pre-test: leading byte matches and decoded size is plausible."""
    if len(data) < 4 or data[0] != expected_byte:
        return False
    hdr = _read_header(data)
    if hdr is None:
        return False
    decomp_size, _ = hdr
    if len(data) < 5:
        return False
    ratio = decomp_size / len(data)
    # Compressed payload should expand at least a bit, but not by 20x+.
    return 0.5 <= ratio <= 20.0


def _decompress_lz10(data: bytes) -> Optional[bytes]:
    hdr = _read_header(data)
    if hdr is None:
        return None
    decomp_size, src = hdr

    out = bytearray(decomp_size)
    out_pos = 0
    n = len(data)

    while out_pos < decomp_size and src < n:
        flags = data[src]; src += 1
        for bit in range(7, -1, -1):
            if out_pos >= decomp_size or src >= n:
                break
            if flags & (1 << bit):
                if src + 1 >= n:
                    return None
                b1 = data[src]; b2 = data[src + 1]; src += 2
                length = (b1 >> 4) + 3
                distance = (((b1 & 0x0F) << 8) | b2) + 1
                copy_len = min(length, decomp_size - out_pos)
                ref = out_pos - distance
                if ref < 0:
                    return None
                if distance >= copy_len:
                    out[out_pos:out_pos + copy_len] = out[ref:ref + copy_len]
                else:
                    pat = bytes(out[ref:ref + distance])
                    reps = (copy_len + distance - 1) // distance
                    out[out_pos:out_pos + copy_len] = (pat * reps)[:copy_len]
                out_pos += copy_len
            else:
                out[out_pos] = data[src]; src += 1; out_pos += 1

    return bytes(out) if out_pos >= decomp_size else None


def _decompress_lz11(data: bytes) -> Optional[bytes]:
    """LZ11 with a fast-path for all-literal flag bytes."""
    hdr = _read_header(data)
    if hdr is None:
        return None
    decomp_size, src = hdr

    out = bytearray(decomp_size)
    out_pos = 0
    n = len(data)

    while out_pos < decomp_size and src < n:
        flags = data[src]; src += 1

        # Fast path: 8 consecutive literals.
        if flags == 0:
            take = min(8, decomp_size - out_pos, n - src)
            if take <= 0:
                break
            out[out_pos:out_pos + take] = data[src:src + take]
            out_pos += take
            src += take
            continue

        bit = 7
        while bit >= 0:
            if out_pos >= decomp_size or src >= n:
                break
            if not (flags & (1 << bit)):
                # Coalesce consecutive literal bits.
                lit = 1
                b2 = bit - 1
                while b2 >= 0 and not (flags & (1 << b2)):
                    lit += 1
                    b2 -= 1
                lit = min(lit, decomp_size - out_pos, n - src)
                out[out_pos:out_pos + lit] = data[src:src + lit]
                out_pos += lit
                src += lit
                bit -= lit
                continue

            bit -= 1

            # Variable-length backref.
            if src >= n:
                return None
            ind = data[src]; src += 1
            top = ind >> 4

            if top == 0:
                if src + 1 >= n:
                    return None
                b2 = data[src]; b3 = data[src + 1]; src += 2
                length = (((ind & 0x0F) << 4) | (b2 >> 4)) + 0x11
                distance = (((b2 & 0x0F) << 8) | b3) + 1
            elif top == 1:
                if src + 2 >= n:
                    return None
                b2 = data[src]; b3 = data[src + 1]; b4 = data[src + 2]; src += 3
                length = (((ind & 0x0F) << 12) | (b2 << 4) | (b3 >> 4)) + 0x111
                distance = (((b3 & 0x0F) << 8) | b4) + 1
            else:
                if src >= n:
                    return None
                b2 = data[src]; src += 1
                length = top + 1
                distance = (((ind & 0x0F) << 8) | b2) + 1

            copy_len = min(length, decomp_size - out_pos)
            ref = out_pos - distance
            if ref < 0:
                return None
            if distance >= copy_len:
                out[out_pos:out_pos + copy_len] = out[ref:ref + copy_len]
            else:
                pat = bytes(out[ref:ref + distance])
                reps = (copy_len + distance - 1) // distance
                out[out_pos:out_pos + copy_len] = (pat * reps)[:copy_len]
            out_pos += copy_len

    return bytes(out) if out_pos >= decomp_size else None


def _decompress_lz13(data: bytes) -> Optional[bytes]:
    hdr = _read_header(data)
    if hdr is None:
        return None
    decomp_size, hdr_size = hdr

    inner = data[hdr_size:]
    if len(inner) >= 4 and inner[0] == 0x11:
        return _decompress_lz11(inner)

    # Fallback: payload stored backwards. Reconstruct an LZ11 stream and
    # reverse the result.
    rev = bytearray()
    if decomp_size <= 0xFFFFFF:
        rev.extend(struct.pack("<I", 0x11 | (decomp_size << 8)))
    else:
        rev.append(0x11)
        rev.extend(b"\x00\x00\x00")
        rev.extend(struct.pack("<I", decomp_size))
    rev.extend(reversed(inner))
    inner_decomp = _decompress_lz11(bytes(rev))
    if inner_decomp is None:
        return None
    return bytes(reversed(inner_decomp))


# ─────────────────────────────────────────────────────────────────────────────
# Registrations
# ─────────────────────────────────────────────────────────────────────────────

@register_compression("lz_nintendo_lz11", priority=70)
class _LZ11:
    @staticmethod
    def detect(data: bytes) -> bool:
        return _is_lz_byte_plausible(data, 0x11)

    @staticmethod
    def decompress(data: bytes) -> Optional[bytes]:
        if len(data) < 4 or data[0] != 0x11:
            return None
        try:
            return _decompress_lz11(data)
        except Exception as e:  # pragma: no cover -- defensive
            logger.debug("LZ11 decompress error: %s", e)
            return None


@register_compression("lz_nintendo_lz10", priority=65)
class _LZ10:
    @staticmethod
    def detect(data: bytes) -> bool:
        return _is_lz_byte_plausible(data, 0x10)

    @staticmethod
    def decompress(data: bytes) -> Optional[bytes]:
        if len(data) < 4 or data[0] != 0x10:
            return None
        try:
            return _decompress_lz10(data)
        except Exception as e:
            logger.debug("LZ10 decompress error: %s", e)
            return None


@register_compression("lz_nintendo_lz13", priority=60)
class _LZ13:
    @staticmethod
    def detect(data: bytes) -> bool:
        return _is_lz_byte_plausible(data, 0x13)

    @staticmethod
    def decompress(data: bytes) -> Optional[bytes]:
        if len(data) < 4 or data[0] != 0x13:
            return None
        try:
            return _decompress_lz13(data)
        except Exception as e:
            logger.debug("LZ13 decompress error: %s", e)
            return None


# ─────────────────────────────────────────────────────────────────────────────
# Convenience for callers that don't want to go through the registry.
# ─────────────────────────────────────────────────────────────────────────────

def decompress_lz(data: bytes) -> Optional[bytes]:
    """Single-shot dispatcher for LZ10/LZ11/LZ13 streams.

    Used by the GARC parallel-decompression worker (which can't easily reach
    into the registry from a multiprocessing pool).
    """
    if not data:
        return None
    t = data[0]
    if t == 0x10:
        return _decompress_lz10(data)
    if t == 0x11:
        return _decompress_lz11(data)
    if t == 0x13:
        return _decompress_lz13(data)
    return None
