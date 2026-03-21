"""Nintendo LZ10/LZ11/LZ13 decompression for 3DS compressed files.

3DS games use LZ compression to wrap standard texture formats (BCLIM,
CGFX, CTPK, BCH, CMB). Files are identified by the first byte:
  0x10 = LZ10 (standard LZSS)
  0x11 = LZ11 (extended LZSS with variable-length encoding, most common)
  0x13 = LZ13 (LZ11 applied in reverse)
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

    out = bytearray()
    while len(out) < decomp_size and src < len(data):
        flags = data[src]; src += 1
        for bit in range(7, -1, -1):
            if len(out) >= decomp_size:
                break
            if flags & (1 << bit):
                # Back-reference
                if src + 1 >= len(data):
                    break
                b1 = data[src]; b2 = data[src + 1]; src += 2
                length = (b1 >> 4) + 3
                distance = ((b1 & 0x0F) << 8) | b2
                distance += 1
                for _ in range(length):
                    if len(out) >= decomp_size:
                        break
                    pos = len(out) - distance
                    out.append(out[pos] if pos >= 0 else 0)
            else:
                # Literal byte
                if src >= len(data):
                    break
                out.append(data[src]); src += 1

    if len(out) >= decomp_size:
        return bytes(out[:decomp_size])
    # Allow slightly short output (some files have trailing garbage)
    if len(out) >= decomp_size * 0.9:
        return bytes(out)
    return None


def _decompress_lz11(data: bytes) -> bytes | None:
    """Decompress LZ11 (extended LZSS with variable-length encoding)."""
    header = _read_header(data)
    if header is None:
        return None
    decomp_size, src = header

    out = bytearray()
    while len(out) < decomp_size and src < len(data):
        flags = data[src]; src += 1
        for bit in range(7, -1, -1):
            if len(out) >= decomp_size:
                break
            if flags & (1 << bit):
                # Back-reference with variable length encoding
                if src >= len(data):
                    break
                indicator = data[src]; src += 1
                top = indicator >> 4

                if top == 0:
                    # 3-byte back-ref: length 0x11-0x110
                    if src >= len(data):
                        break
                    b2 = data[src]; src += 1
                    if src >= len(data):
                        break
                    b3 = data[src]; src += 1
                    length = ((indicator & 0x0F) << 4) | (b2 >> 4)
                    length += 0x11
                    distance = ((b2 & 0x0F) << 8) | b3
                    distance += 1

                elif top == 1:
                    # 4-byte back-ref: length 0x111-0x10110
                    if src + 2 > len(data):
                        break
                    b2 = data[src]; src += 1
                    b3 = data[src]; src += 1
                    b4 = data[src]; src += 1
                    length = ((indicator & 0x0F) << 12) | (b2 << 4) | (b3 >> 4)
                    length += 0x111
                    distance = ((b3 & 0x0F) << 8) | b4
                    distance += 1

                else:
                    # 2-byte back-ref: length 1-0x10
                    if src >= len(data):
                        break
                    b2 = data[src]; src += 1
                    length = top + 1
                    distance = ((indicator & 0x0F) << 8) | b2
                    distance += 1

                for _ in range(length):
                    if len(out) >= decomp_size:
                        break
                    pos = len(out) - distance
                    out.append(out[pos] if pos >= 0 else 0)
            else:
                # Literal byte
                if src >= len(data):
                    break
                out.append(data[src]); src += 1

    if len(out) >= decomp_size:
        return bytes(out[:decomp_size])
    if len(out) >= decomp_size * 0.9:
        return bytes(out)
    return None


def _decompress_lz13(data: bytes) -> bytes | None:
    """Decompress LZ13 (reverse LZ11).

    The compressed data is stored backwards. We read from the end,
    decompress using LZ11 algorithm, then reverse the output.
    """
    header = _read_header(data)
    if header is None:
        return None
    decomp_size, hdr_size = header

    # Build reversed compressed data (excluding header)
    reversed_data = bytearray()
    # Fake an LZ11 header for the reversed stream
    reversed_data.append(0x11)
    size_le = decomp_size & 0xFFFFFF
    reversed_data.append(size_le & 0xFF)
    reversed_data.append((size_le >> 8) & 0xFF)
    reversed_data.append((size_le >> 16) & 0xFF)
    # Append the compressed payload in reverse
    payload = data[hdr_size:]
    reversed_data.extend(reversed(payload))

    result = _decompress_lz11(bytes(reversed_data))
    if result is None:
        return None
    # Reverse the output
    return bytes(reversed(result))
