"""CMB (CTR Model Binary) texture extractor for Grezzo 3DS games.

CMB files contain embedded textures in a 'tex ' section with the same
per-entry format as standalone CTXB files. Pixel data is stored at
the end of the file, starting at the last section offset in the header.

Used by OoT3D, MM3D, Luigi's Mansion 3DS.
"""

import logging
import struct
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# Same format mapping as CTXB (DMP OpenGL extension constants)
CMB_FORMAT_MAP = {
    0x6750: 0x00,  # RGBA8
    0x6751: 0x01,  # RGB8
    0x6752: 0x02,  # RGBA5551
    0x6753: 0x03,  # RGB565
    0x6754: 0x04,  # RGBA4
    0x6755: 0x05,  # LA8
    0x6756: 0x06,  # HILO8
    0x6757: 0x07,  # L8
    0x6758: 0x08,  # A8
    0x6759: 0x09,  # LA4
    0x675A: 0x0C,  # ETC1
    0x675B: 0x0D,  # ETC1A4
}


def is_cmb(data: bytes) -> bool:
    """Check if data contains a CMB file (search for 'cmb ' magic)."""
    return len(data) >= 0x40 and data.find(b'cmb ') >= 0


def extract_cmb_textures(data: bytes) -> List[Dict[str, Any]]:
    """Extract texture info from a CMB file.

    Returns list of dicts with: name, format, width, height, data_offset, data_size
    """
    cmb_idx = data.find(b'cmb ')
    if cmb_idx < 0:
        return []

    textures = []
    file_len = len(data)

    try:
        cmb_size = struct.unpack_from('<I', data, cmb_idx + 4)[0]
        num_sections = struct.unpack_from('<I', data, cmb_idx + 8)[0]

        if num_sections < 1 or num_sections > 20:
            return []

        # Read section offsets to find the last one (texture data section)
        offsets = []
        for i in range(min(num_sections + 3, 12)):
            off_pos = cmb_idx + 0x20 + i * 4
            if off_pos + 4 > file_len:
                break
            offsets.append(struct.unpack_from('<I', data, off_pos)[0])

        if not offsets:
            return []

        # Find 'tex ' section
        tex_idx = data.find(b'tex ', cmb_idx)
        if tex_idx < 0:
            return []

        tex_section_size = struct.unpack_from('<I', data, tex_idx + 4)[0]
        tex_count = struct.unpack_from('<I', data, tex_idx + 8)[0]

        if tex_count == 0 or tex_count > 500:
            return []

        # Texture data starts at the last section offset
        tex_data_base = offsets[-1]

        for i in range(tex_count):
            entry_off = tex_idx + 0x0C + i * 0x24
            if entry_off + 0x24 > file_len:
                break

            data_length = struct.unpack_from('<I', data, entry_off + 0x00)[0]
            width = struct.unpack_from('<H', data, entry_off + 0x08)[0]
            height = struct.unpack_from('<H', data, entry_off + 0x0A)[0]
            pixel_format = struct.unpack_from('<H', data, entry_off + 0x0C)[0]
            data_offset_rel = struct.unpack_from('<I', data, entry_off + 0x10)[0]

            # Read name (16 bytes, null-terminated)
            name_bytes = data[entry_off + 0x14:entry_off + 0x24]
            try:
                name = name_bytes.split(b'\x00')[0].decode('ascii', errors='replace')
            except Exception:
                name = ""

            pica_format = CMB_FORMAT_MAP.get(pixel_format)
            if pica_format is None:
                logger.debug(f"CMB: unknown pixel format 0x{pixel_format:04X} for texture {i}")
                continue

            if width == 0 or height == 0 or width > 2048 or height > 2048:
                continue

            abs_data_offset = tex_data_base + data_offset_rel
            if abs_data_offset >= file_len:
                continue

            available = file_len - abs_data_offset
            actual_length = min(data_length, available) if data_length > 0 else available

            if not name:
                name = f"cmb_tex_{i:04d}"

            textures.append({
                'index': i,
                'name': name,
                'format': pica_format,
                'width': width,
                'height': height,
                'data_offset': abs_data_offset,
                'data_size': actual_length,
                'mip_count': 1,
            })

    except Exception as e:
        logger.warning(f"Error parsing CMB textures: {e}")

    if textures:
        logger.debug(f"CMB: found {len(textures)} textures")
    return textures
