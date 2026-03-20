"""BCH / BCRES (Binary CTR model/texture format) texture extractor."""

import logging
from typing import List, Dict, Any
from utils import read_u32_le, read_u16_le, read_u8, read_string

logger = logging.getLogger(__name__)


def is_bch(data: bytes) -> bool:
    """Check if data is a BCH file."""
    if len(data) < 4:
        return False
    return data[0:4] == b'BCH\x00'


def is_cgfx(data: bytes) -> bool:
    """Check if data is a CGFX file."""
    if len(data) < 4:
        return False
    return data[0:4] == b'CGFX'


def extract_bch_textures(data: bytes) -> List[Dict[str, Any]]:
    """
    Extract texture info from a BCH file.
    Returns a list of dicts with keys: name, format, width, height, data_offset, data_size, mip_count
    """
    if not is_bch(data):
        return []

    textures = []

    try:
        # BCH header structure:
        # 0x00: Magic "BCH\0" (4 bytes)
        # 0x04: Backward compatibility (1 byte)
        # 0x05: Forward compatibility (1 byte)
        # 0x06: Version (2 bytes)
        # 0x08: Main header offset (4 bytes) - usually 0x44
        # 0x0C: String table offset (4 bytes)
        # 0x10: Relocation table offset (4 bytes)
        # 0x14: Content data offset (4 bytes)
        # 0x18: Data extended offset (4 bytes)
        # 0x1C: Relocation table (unresolved) offset (4 bytes)

        main_header_off = read_u32_le(data, 0x08)
        string_table_off = read_u32_le(data, 0x0C)
        content_data_off = read_u32_le(data, 0x14)

        logger.debug(f"BCH: main_header=0x{main_header_off:X}, strings=0x{string_table_off:X}, "
                      f"content=0x{content_data_off:X}")

        # The main header contains section pointers
        # At main_header_off:
        # Section entries for: Models, Materials, Shaders, Textures, etc.
        # Each section entry is typically: dict_offset (4), dict_count (4)

        # Texture section is typically the 5th section (index 4) but varies by version
        # We'll look for the texture dictionary

        # Alternative approach: scan for texture-like patterns in the file
        # BCH textures have a specific structure in their entries

        # Try to find texture entries by scanning the content
        _extract_bch_textures_scan(data, textures, string_table_off, content_data_off)

    except Exception as e:
        logger.warning(f"Error parsing BCH: {e}")

    return textures


def _extract_bch_textures_scan(data: bytes, textures: list,
                                string_table_off: int, content_data_off: int):
    """Scan BCH file for texture entries."""
    # BCH stores texture metadata with specific patterns
    # Each texture entry contains: format, width, height, and a data offset
    # We scan for the texture section pointer table

    file_len = len(data)

    # Look for the textures section in the BCH header
    # The header at offset 0x08 points to the main header
    # Main header has section offsets, the texture section pointer table
    # is at a specific offset within the main header

    # Approach: look for texture metadata patterns
    # A texture entry typically has:
    # - height (u16) at some offset
    # - width (u16) at some offset
    # - format (u32 or u8) matching known PICA200 format IDs

    # BCH dictionary structure:
    # Each dict starts with a magic or count, then entries
    # Try parsing from the main header

    main_header_off = read_u32_le(data, 0x08)

    # The main header has offsets to different section dictionaries
    # Typical layout of the main header (at main_header_off):
    # 0x00: models dict offset
    # 0x04: models dict count
    # 0x08: materials dict offset / or other sections
    # ...
    # The exact layout depends on the BCH version

    # For BCRES/BCH, textures are typically stored with their metadata
    # Let's try a different approach: find texture data by looking for
    # PICA200 texture command sequences

    # Scan for texture parameter blocks
    # PICA200 textures in BCH files typically have this structure in the metadata:
    # - height (u32)
    # - width (u32)
    # - data_offset (u32) - relative to content section
    # - format and other params

    # Use a heuristic: look for pairs of dimensions that are powers of 2
    # followed by valid format IDs

    tex_idx = 0
    checked_offsets = set()

    # Method 1: Look for texture section via BCH header
    # In BCH, there's typically a texture list at a specific header offset
    # The texture list pointer is usually at main_header_off + 0x24 (varies)
    for section_ptr_offset in [0x24, 0x28, 0x2C, 0x30, 0x34, 0x38, 0x20, 0x1C, 0x18]:
        abs_offset = main_header_off + section_ptr_offset
        if abs_offset + 8 > file_len:
            continue

        section_offset = read_u32_le(data, abs_offset)
        section_count = read_u32_le(data, abs_offset + 4)

        if section_count == 0 or section_count > 1000 or section_offset == 0:
            continue
        if section_offset >= file_len:
            continue

        # Try to parse this as a texture section
        found = _try_parse_texture_section(data, section_offset, section_count,
                                            string_table_off, content_data_off,
                                            textures, tex_idx)
        if found > 0:
            tex_idx += found
            break

    if tex_idx == 0:
        # Fallback: scan entire file for recognizable texture metadata
        _scan_for_texture_metadata(data, textures, content_data_off)


def _try_parse_texture_section(data: bytes, section_offset: int, section_count: int,
                                string_table_off: int, content_data_off: int,
                                textures: list, start_idx: int) -> int:
    """Try to parse a BCH section as a texture section. Returns count of textures found."""
    found = 0

    # BCH dictionary format: entries with name hash and data offset
    # Each dictionary entry is typically 4 words:
    # - reference bit + name offset
    # - left node, right node
    # - data offset

    # Try different entry sizes
    for entry_size in [24, 16, 32, 20]:
        found = 0
        valid = True

        for i in range(section_count):
            entry_off = section_offset + i * entry_size
            if entry_off + entry_size > len(data):
                valid = False
                break

            # Try to find width, height, format in this entry
            # Look at various offsets within the entry for plausible texture params
            tex_info = _extract_tex_params_from_entry(data, entry_off, entry_size,
                                                       string_table_off, content_data_off)
            if tex_info:
                tex_info['index'] = start_idx + found
                textures.append(tex_info)
                found += 1

        if found >= section_count // 2 and found > 0:
            return found

    return 0


def _extract_tex_params_from_entry(data: bytes, entry_off: int, entry_size: int,
                                    string_table_off: int, content_data_off: int) -> dict:
    """Try to extract texture parameters from a BCH entry."""
    # This is heuristic-based since BCH format varies
    # Look for width/height pairs that are powers of 2

    best = None
    for off in range(0, entry_size - 8, 4):
        abs_off = entry_off + off
        if abs_off + 8 > len(data):
            continue

        val1 = read_u32_le(data, abs_off)
        val2 = read_u32_le(data, abs_off + 4)

        # Check if these look like height x width
        if (_is_valid_dimension(val1) and _is_valid_dimension(val2) and
                val1 >= 4 and val2 >= 4):
            # Look for format nearby
            for fmt_off in range(-8, entry_size - off, 4):
                fmt_abs = abs_off + fmt_off
                if fmt_abs < entry_off or fmt_abs + 4 > len(data):
                    continue
                fmt_val = read_u32_le(data, fmt_abs)
                if fmt_val <= 0xD:
                    best = {
                        'width': val2,
                        'height': val1,
                        'format': fmt_val,
                        'data_offset': content_data_off,
                        'data_size': 0,
                        'mip_count': 1,
                        'name': '',
                    }
                    break

    return best


def _is_valid_dimension(val: int) -> bool:
    """Check if value is a valid texture dimension (power of 2, reasonable range)."""
    if val < 1 or val > 2048:
        return False
    return (val & (val - 1)) == 0


def _scan_for_texture_metadata(data: bytes, textures: list, content_data_off: int):
    """Fallback: scan entire BCH file for texture metadata patterns."""
    # Look for sequences that look like: height(u16), width(u16), 0, 0, format(u32)
    # or similar patterns
    tex_idx = len(textures)

    for offset in range(0, len(data) - 16, 4):
        # Pattern: width(u32), height(u32) where both are powers of 2
        w = read_u32_le(data, offset)
        h = read_u32_le(data, offset + 4)

        if not (_is_valid_dimension(w) and _is_valid_dimension(h)):
            continue
        if w < 8 or h < 8:
            continue

        # Check if there's a valid format ID nearby
        for fmt_off in [8, 12, -4, -8, 16]:
            check_off = offset + fmt_off
            if check_off < 0 or check_off + 4 > len(data):
                continue
            fmt = read_u32_le(data, check_off)
            if 0 <= fmt <= 0xD:
                from textures.decoder import calculate_texture_size, FORMAT_BPP
                expected_size = calculate_texture_size(w, h, fmt)
                if expected_size > 0 and expected_size < len(data):
                    # Look for a data offset
                    for data_off_off in [12, 16, 20, -8, -12]:
                        data_check = offset + data_off_off
                        if data_check < 0 or data_check + 4 > len(data):
                            continue
                        potential_offset = read_u32_le(data, data_check)
                        if (potential_offset + content_data_off + expected_size <= len(data) and
                                potential_offset < len(data)):
                            textures.append({
                                'index': tex_idx,
                                'width': w,
                                'height': h,
                                'format': fmt,
                                'data_offset': potential_offset + content_data_off,
                                'data_size': expected_size,
                                'mip_count': 1,
                                'name': f'bch_tex_{tex_idx:04d}',
                            })
                            tex_idx += 1
                            break
                break

    logger.info(f"BCH scan found {len(textures)} potential textures")
