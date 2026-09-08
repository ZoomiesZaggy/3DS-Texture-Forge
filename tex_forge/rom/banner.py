"""Read-only accessor: a title's HOME Menu banner image.

The ExeFS "banner" entry is a CBMD container: a 0x88-byte header pointing at
an LZ11-compressed CGFX (the 3D banner model) plus a CWAV jingle. The banner
ART is just CGFX textures inside that model, so this module writes NO new
swizzle, format, or texture-parsing code: it slices the CBMD, hands the
payload to the existing compression registry (LZ11) and the existing CGFX
texture plugin, decodes candidates with the existing decoder, and returns
the largest one (the banner image proper; small textures are shading ramps
and logos).

CBMD layout (3dbrew, https://www.3dbrew.org/wiki/3DS_Virtual_Console#CBMD,
and the banner spec at https://www.3dbrew.org/wiki/Banner):
  0x00  "CBMD" magic
  0x08  u32 common CGFX offset (usually 0x88)
  0x0C  u32 x13 region-specific CGFX offsets (0 when absent)
  0x84  u32 CWAV offset (end of the CGFX region)

Never raises for expected failure modes (encrypted ExeFS, no banner entry,
odd container): logs and returns None so the GUI can fall back to the SMDH
icon. No em dashes (house rule).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from tex_forge.core.exceptions import EncryptedROMError, ROMParseError
from tex_forge.rom.icon import find_exefs_entry
from tex_forge.rom.loader import _route
from tex_forge.rom.ncch import NCCHParser

logger = logging.getLogger(__name__)

CBMD_MAGIC = b"CBMD"
CBMD_HEADER_SIZE = 0x88
_COMMON_OFFSET_AT = 0x08
_REGION_OFFSETS_AT = 0x0C
_REGION_OFFSET_COUNT = 13
_CWAV_OFFSET_AT = 0x84


def parse_cbmd(data: bytes) -> Optional[bytes]:
    """Slice the (usually LZ11-compressed) CGFX payload out of a CBMD blob.

    Prefers the common model; falls back to the first region-specific one.
    The payload runs from its offset to the CWAV offset (or to end of blob
    when the CWAV offset is absent/zero). Returns None on a non-CBMD or
    inconsistent header.
    """
    if len(data) < CBMD_HEADER_SIZE or data[:4] != CBMD_MAGIC:
        return None

    def _u32(at: int) -> int:
        return int.from_bytes(data[at:at + 4], "little")

    candidates = [_u32(_COMMON_OFFSET_AT)]
    candidates += [_u32(_REGION_OFFSETS_AT + 4 * i)
                   for i in range(_REGION_OFFSET_COUNT)]
    start = next((c for c in candidates
                  if CBMD_HEADER_SIZE <= c < len(data)), 0)
    if not start:
        return None

    cwav = _u32(_CWAV_OFFSET_AT)
    end = cwav if start < cwav <= len(data) else len(data)
    payload = data[start:end]
    return payload or None


def _iter_cgfx_textures(cgfx_data: bytes):
    """Registry seam (separate function so tests can stub it)."""
    from tex_forge.textures.registry import detect_texture
    hit = detect_texture(cgfx_data)
    if hit is None:
        return iter(())
    return hit.plugin.iter_textures(cgfx_data, source_path="banner")


def decode_banner_cgfx(payload: bytes):
    """Decompress (if needed) and decode the banner CGFX; largest texture wins.

    Returns an RGBA8 (H, W, 4) ndarray or None. Decode failures on
    individual textures are skipped, not fatal.
    """
    from tex_forge.compression.registry import try_decompress
    from tex_forge.textures.decoder import decode

    dec = try_decompress(payload, hint="lz_nintendo_lz11")
    cgfx = dec.data if dec is not None else payload  # lenient: raw CGFX too

    best = None
    best_area = 0
    for tex in _iter_cgfx_textures(cgfx):
        if not tex.data or tex.width < 1 or tex.height < 1:
            continue
        area = tex.width * tex.height
        if area <= best_area:
            continue
        try:
            rgba = decode(tex.data, tex.width, tex.height, tex.format)
        except Exception:
            continue
        if rgba is None:
            continue
        best, best_area = rgba, area
    return best


def extract_title_banner(path: str):
    """Decode a title's HOME Menu banner image to an RGBA8 ndarray, or None."""
    name = os.path.basename(path)
    try:
        with open(path, "rb") as f:
            rom = f.read()
        ext = os.path.splitext(path)[1].lower()
        ncch_data, _title_id, _chain = _route(rom, ext)
        if ncch_data is None:
            logger.info("banner: %s no NCCH container", name)
            return None
        exefs = NCCHParser(ncch_data).get_exefs()
    except EncryptedROMError:
        logger.info("banner: %s ExeFS encrypted", name)
        return None
    except ROMParseError as e:
        logger.info("banner: %s no usable ExeFS (%s)", name, e)
        return None
    except Exception as e:  # defensive: a banner must never crash the UI
        logger.info("banner: %s unexpected container error (%s)", name, e)
        return None

    blob = find_exefs_entry(exefs, b"banner")
    if not blob:
        logger.info("banner: %s has no 'banner' ExeFS entry", name)
        return None
    payload = parse_cbmd(blob)
    if payload is None:
        logger.info("banner: %s banner entry is not CBMD (magic=%r)",
                    name, blob[:4])
        return None
    try:
        rgba = decode_banner_cgfx(payload)
    except Exception as e:
        logger.info("banner: %s CGFX decode failed (%s)", name, e)
        return None
    if rgba is None:
        logger.info("banner: %s no decodable banner texture", name)
    return rgba
