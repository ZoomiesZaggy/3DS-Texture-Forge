"""CGFX (CTR Graphics) texture extractor.

Extracts texture data from CGFX files by finding Image TXOB entries.
CGFX files contain a scene graph with models, materials, and textures.
We only care about the texture image data.

Image TXOB structure (CGFX v5, used by Pokemon X/Y):
  +0x00: Magic 'TXOB' (4 bytes)
  +0x04: Revision (u32)
  +0x08: Name offset (u32, self-relative)
  +0x14: Height (u32)
  +0x18: Width (u32)
  +0x30: PICA200 format (u32)
  +0x40: Data size (u32)
  +0x44: Data offset (u32, self-relative from this field's position)

Image TXOBs are distinguished from Reference TXOBs by NOT having
'SHDR' magic at +0x40.
"""

import logging
import struct
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# Valid PICA200 format IDs
VALID_PICA_FORMATS = set(range(0x0E))


def is_cgfx(data: bytes) -> bool:
    """Check if data is a CGFX file."""
    return len(data) >= 0x14 and data[0:4] == b'CGFX'


def extract_cgfx_textures(data: bytes) -> List[Dict[str, Any]]:
    """Extract texture info from a CGFX file.

    Returns list of dicts with: name, format, width, height, data_offset, data_size
    """
    if not is_cgfx(data):
        return []

    textures = []
    file_len = len(data)

    # Find all TXOB entries
    pos = 0
    tex_idx = 0
    while pos < file_len - 4:
        idx = data.find(b'TXOB', pos)
        if idx < 0:
            break
        pos = idx + 1

        # Need at least 0x48 bytes for an Image TXOB
        if idx + 0x48 > file_len:
            continue

        # Skip Reference TXOBs (they have 'SHDR' at +0x40)
        if data[idx + 0x40:idx + 0x44] == b'SHDR':
            continue

        # Read Image TXOB fields
        height = struct.unpack_from('<I', data, idx + 0x14)[0]
        width = struct.unpack_from('<I', data, idx + 0x18)[0]

        # Validate dimensions
        if width < 4 or width > 2048 or height < 4 or height > 2048:
            continue
        if (width & (width - 1)) != 0 or (height & (height - 1)) != 0:
            continue

        pica_format = struct.unpack_from('<I', data, idx + 0x30)[0]
        data_size = struct.unpack_from('<I', data, idx + 0x40)[0]
        data_offset_raw = struct.unpack_from('<I', data, idx + 0x44)[0]

        # Data offset is self-relative from field position (+0x44)
        data_offset = idx + 0x44 + data_offset_raw

        # Validate format
        if pica_format not in VALID_PICA_FORMATS:
            continue

        # Validate data bounds
        if data_offset + data_size > file_len or data_size == 0 or data_offset < 0:
            continue

        # Try to read texture name from self-relative offset at +0x08
        name = ""
        name_rel = struct.unpack_from('<I', data, idx + 0x08)[0]
        if name_rel > 0:
            name_abs = idx + 0x08 + name_rel
            if name_abs < file_len:
                end = name_abs
                while end < min(name_abs + 256, file_len) and data[end] != 0:
                    end += 1
                try:
                    name = data[name_abs:end].decode('ascii', errors='replace')
                except Exception:
                    pass

        if not name:
            name = f"cgfx_tex_{tex_idx:04d}"

        textures.append({
            'name': name,
            'format': pica_format,
            'width': width,
            'height': height,
            'data_offset': data_offset,
            'data_size': data_size,
            'mip_count': 1,
        })
        tex_idx += 1

    if textures:
        logger.debug(f"CGFX: found {len(textures)} image textures")

    return textures
