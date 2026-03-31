"""Nintendo LZ10/LZ11/LZ13/BLZ decompression for 3DS compressed files.

3DS games use LZ compression to wrap standard texture formats (BCLIM,
CGFX, CTPK, BCH, CMB). Files are identified by the first byte:
  0x10 = LZ10 (standard LZSS)
  0x11 = LZ11 (extended LZSS with variable-length encoding, most common)
  0x13 = LZ13 (LZ11 applied in reverse)
  BLZ  = Bottom-LZ (backward LZSS, footer at end of file)
"""

import struct
import logging

logger = logging.getLogger(__name__)

MAX_DECOMP_SIZE = 50 * 1024 * 1024  # 50 MB safety limit


def is_lz_compressed(data: bytes, file_path: str = "") -> bool:
    """Check if data looks like Nintendo LZ compressed.

    Uses both magic byte and plausibility checks to avoid false positives.
    File extension (.lz, .cmp) is a strong signal.
    """
    if len(data) < 4:
        return False

    type_byte = data[0]
    if type_byte not in (0x10, 0x11, 0x13):
        return False

    # Read decompressed size from header
    decomp_size = struct.unpack_from('<I', data, 0)[0] >> 8
    header_size = 4

    if decomp_size == 0 and len(data) >= 8:
        decomp_size = struct.unpack_from('<I', data, 4)[0]
        header_size = 8

    if decomp_size <= 0 or decomp_size > MAX_DECOMP_SIZE:
        return False

    # Extension-based detection is reliable
    ext = ""
    if "." in file_path:
        ext = "." + file_path.rsplit(".", 1)[-1].lower()
    if ext in (".lz", ".cmp"):
        return True

    # Without a known extension, require plausible size ratio
    # Decompressed should be larger than compressed, but not absurdly so
    if len(data) < 5:
        return False
    ratio = decomp_size / len(data)
    if ratio < 0.5 or ratio > 20:
        return False

    return True


def decompress_lz(data: bytes) -> bytes | None:
    """Decompress Nintendo LZ10/LZ11/LZ13 data. Returns None on failure."""
    if len(data) < 4:
        return None

    type_byte = data[0]
    try:
        if type_byte == 0x10:
            return _decompress_lz10(data)
        elif type_byte == 0x11:
            return _decompress_lz11(data)
        elif type_byte == 0x13:
            return _decompress_lz13(data)
    except Exception as e:
        logger.debug(f"LZ decompression failed (type 0x{type_byte:02X}): {e}")
        return None

    return None


def _read_header(data: bytes):
    """Read LZ header, return (decomp_size, data_start_offset) or None."""
    if len(data) < 4:
        return None
    decomp_size = struct.unpack_from('<I', data, 0)[0] >> 8
    start = 4
    if decomp_size == 0:
        if len(data) < 8:
            return None
        decomp_size = struct.unpack_from('<I', data, 4)[0]
        start = 8
    if decomp_size <= 0 or decomp_size > MAX_DECOMP_SIZE:
        return None
    return decomp_size, start


def _decompress_lz10(data: bytes) -> bytes | None:
    """Decompress LZ10 (standard LZSS)."""
    header = _read_header(data)
    if header is None:
        return None
    decomp_size, src = header

    out = bytearray(decomp_size)
    out_pos = 0
    data_len = len(data)
    while out_pos < decomp_size and src < data_len:
        flags = data[src]; src += 1
        for bit in range(7, -1, -1):
            if out_pos >= decomp_size or src >= data_len:
                break
            if flags & (1 << bit):
                # Back-reference
                if src + 1 >= data_len:
                    break
                b1 = data[src]; b2 = data[src + 1]; src += 2
                length = (b1 >> 4) + 3
                distance = ((b1 & 0x0F) << 8) | b2
                distance += 1
                ref_pos = out_pos - distance
                copy_len = length if out_pos + length <= decomp_size else decomp_size - out_pos
                if ref_pos >= 0:
                    if distance >= copy_len:
                        out[out_pos:out_pos + copy_len] = out[ref_pos:ref_pos + copy_len]
                    else:
                        pattern = bytes(out[ref_pos:ref_pos + distance])
                        reps = (copy_len + distance - 1) // distance
                        out[out_pos:out_pos + copy_len] = (pattern * reps)[:copy_len]
                    out_pos += copy_len
                else:
                    for _ in range(copy_len):
                        p = out_pos - distance
                        out[out_pos] = out[p] if p >= 0 else 0
                        out_pos += 1
            else:
                out[out_pos] = data[src]; src += 1; out_pos += 1

    if out_pos >= decomp_size:
        return bytes(out)
    return None


def _lz_extend(out: bytearray, distance: int, length: int, decomp_size: int) -> None:
    """Copy `length` bytes from `distance` bytes back in `out`.

    Handles overlapping copies correctly by using a repeating-pattern trick:
    build the reference pattern (up to `distance` bytes), then tile it to
    cover `length` bytes, and extend in one C-level call.  This is ~10-30x
    faster than the equivalent Python byte-by-byte loop.
    """
    pos = len(out) - distance
    if pos < 0:
        # Rare: reference extends before the start of the buffer.
        # Fall back to the safe byte-by-byte path.
        avail = decomp_size - len(out)
        for _ in range(min(length, avail)):
            p = len(out) - distance
            out.append(out[p] if p >= 0 else 0)
        return

    # Clamp to not exceed decomp_size
    length = min(length, decomp_size - len(out))
    if length <= 0:
        return

    # Build the tile pattern (≤ distance bytes).  Tiling this pattern
    # naturally produces the correct overlapping-copy semantics:
    #   e.g. distance=2, length=6, pattern=AB → ABABAB  ✓
    #        distance=3, length=7, pattern=ABC → ABCABCA ✓
    pattern = bytes(out[pos : pos + distance])
    if len(pattern) >= length:
        out.extend(pattern[:length])
    else:
        reps = (length + len(pattern) - 1) // len(pattern)
        out.extend((pattern * reps)[:length])


def _decompress_lz11(data: bytes) -> bytes | None:
    """Decompress LZ11 (extended LZSS with variable-length encoding).

    Optimized: batches consecutive literal bytes via slice copy,
    uses while-loop for proper bit skipping.
    """
    header = _read_header(data)
    if header is None:
        return None
    decomp_size, src = header

    out = bytearray(decomp_size)
    out_pos = 0
    data_len = len(data)

    while out_pos < decomp_size and src < data_len:
        flags = data[src]; src += 1

        # Fast path: flags == 0x00 means all 8 bits are literals.
        if flags == 0:
            n = min(8, decomp_size - out_pos, data_len - src)
            if n > 0:
                out[out_pos:out_pos + n] = data[src:src + n]
                out_pos += n
                src += n
            continue

        bit = 7
        while bit >= 0:
            if out_pos >= decomp_size or src >= data_len:
                break
            if not (flags & (1 << bit)):
                # Literal — count consecutive literal bits and batch copy
                n_lit = 1
                b2 = bit - 1
                while b2 >= 0 and not (flags & (1 << b2)):
                    n_lit += 1
                    b2 -= 1
                n_lit = min(n_lit, decomp_size - out_pos, data_len - src)
                out[out_pos:out_pos + n_lit] = data[src:src + n_lit]
                out_pos += n_lit
                src += n_lit
                bit -= n_lit
                continue

            bit -= 1

            # Back-reference with variable length encoding
            indicator = data[src]; src += 1
            top = indicator >> 4

            if top == 0:
                if src + 1 >= data_len:
                    break
                b2 = data[src]; b3 = data[src + 1]; src += 2
                length = ((indicator & 0x0F) << 4) | (b2 >> 4)
                length += 0x11
                distance = ((b2 & 0x0F) << 8) | b3
                distance += 1
            elif top == 1:
                if src + 2 >= data_len:
                    break
                b2 = data[src]; b3 = data[src + 1]; b4 = data[src + 2]; src += 3
                length = ((indicator & 0x0F) << 12) | (b2 << 4) | (b3 >> 4)
                length += 0x111
                distance = ((b3 & 0x0F) << 8) | b4
                distance += 1
            else:
                if src >= data_len:
                    break
                b2 = data[src]; src += 1
                length = top + 1
                distance = ((indicator & 0x0F) << 8) | b2
                distance += 1

            ref_pos = out_pos - distance
            copy_len = min(length, decomp_size - out_pos)
            if ref_pos >= 0:
                if distance >= copy_len:
                    out[out_pos:out_pos + copy_len] = out[ref_pos:ref_pos + copy_len]
                else:
                    pattern = bytes(out[ref_pos:ref_pos + distance])
                    reps = (copy_len + distance - 1) // distance
                    out[out_pos:out_pos + copy_len] = (pattern * reps)[:copy_len]
                out_pos += copy_len
            else:
                for _ in range(copy_len):
                    p = out_pos - distance
                    out[out_pos] = out[p] if p >= 0 else 0
                    out_pos += 1

    if out_pos >= decomp_size:
        return bytes(out)
    return None


def _decompress_lz13(data: bytes) -> bytes | None:
    """Decompress LZ13.

    LZ13 is a thin 4-byte wrapper around LZ11: the outer header uses type
    byte 0x13 and specifies the decompressed size, then the payload starting
    at offset 4 is a standard LZ11 stream (with its own 0x11 header).
    """
    header = _read_header(data)
    if header is None:
        return None
    decomp_size, hdr_size = header

    inner = data[hdr_size:]
    if len(inner) >= 4 and inner[0] == 0x11:
        # Standard case: LZ11 stream follows immediately after LZ13 header
        return _decompress_lz11(inner)

    # Fallback: reverse-LZ11 interpretation (payload stored backwards)
    reversed_data = bytearray()
    reversed_data.append(0x11)
    size_le = decomp_size & 0xFFFFFF
    reversed_data.append(size_le & 0xFF)
    reversed_data.append((size_le >> 8) & 0xFF)
    reversed_data.append((size_le >> 16) & 0xFF)
    reversed_data.extend(reversed(inner))

    result = _decompress_lz11(bytes(reversed_data))
    if result is None:
        return None
    return bytes(reversed(result))


def is_blz_compressed(data: bytes) -> bool:
    """Check if data uses BLZ (Bottom-LZ / backward LZSS) compression.

    BLZ stores a footer in the last 8 bytes:
      [compressed_len: 3 bytes LE] [header_len: 1 byte] [additional_size: 4 bytes LE signed]
    The header_len is 8 or 11. compressed_len covers the compressed region + footer.
    """
    if len(data) < 12:
        return False
    footer = data[-8:]
    comp_len = footer[0] | (footer[1] << 8) | (footer[2] << 16)
    hdr_len = footer[3]
    additional = struct.unpack_from('<i', footer, 4)[0]

    if hdr_len not in (8, 11):
        return False
    if comp_len <= hdr_len or comp_len > len(data):
        return False
    decomp_size = len(data) + additional
    if decomp_size <= 0 or decomp_size > MAX_DECOMP_SIZE:
        return False
    if additional <= 0:
        return False
    # Sanity: decompressed shouldn't be absurdly larger than compressed
    if additional > len(data) * 5:
        return False
    return True


def decompress_blz(data: bytes) -> bytes | None:
    """Decompress BLZ (Bottom-LZ / backward LZSS) data.

    BLZ compresses the tail of a file using backward LZSS, leaving the
    head uncompressed.  The footer (last 8 bytes) describes the layout.
    Used by NW4C engine games (e.g. Pac-Man and the Ghostly Adventures).
    """
    if len(data) < 12:
        return None

    footer = data[-8:]
    comp_len = footer[0] | (footer[1] << 8) | (footer[2] << 16)
    hdr_len = footer[3]
    additional = struct.unpack_from('<i', footer, 4)[0]

    if comp_len == 0:
        return data  # not actually compressed

    if hdr_len not in (8, 11):
        return None
    if comp_len <= hdr_len or comp_len > len(data):
        return None

    decomp_size = len(data) + additional
    if decomp_size <= 0 or decomp_size > MAX_DECOMP_SIZE:
        return None

    result = bytearray(decomp_size)
    # Copy uncompressed head portion
    uncomp_len = len(data) - comp_len
    result[:len(data)] = data[:len(data)]  # copy entire input first

    # Backward LZSS decompression
    src = len(data) - hdr_len  # read position (end of compressed data, before footer)
    dst = decomp_size          # write position (end of output)

    try:
        while src > uncomp_len and dst > uncomp_len:
            src -= 1
            flags = data[src]
            for bit in range(8):
                if src <= uncomp_len or dst <= uncomp_len:
                    break
                if flags & (0x80 >> bit):
                    # Back-reference: read 2 bytes backward
                    src -= 1
                    b_hi = data[src]
                    src -= 1
                    b_lo = data[src]
                    length = (b_hi >> 4) + 3
                    disp = ((b_hi & 0x0F) << 8) | b_lo
                    disp += 3
                    for _ in range(length):
                        dst -= 1
                        if dst < 0:
                            return None
                        result[dst] = result[dst + disp]
                else:
                    # Literal byte
                    src -= 1
                    dst -= 1
                    if dst < 0 or src < 0:
                        return None
                    result[dst] = data[src]
    except (IndexError, ValueError) as e:
        logger.debug(f"BLZ decompression failed: {e}")
        return None

    if dst != uncomp_len:
        return None
    return bytes(result)
