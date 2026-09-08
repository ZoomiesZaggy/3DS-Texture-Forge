"""Read-only accessor: a title's HOME Menu icon (the SMDH large icon).

This sits strictly on top of the existing ROM routing and the existing PICA200
texture decoder. It writes NO new swizzle or format code: the 48x48 RGB565 icon
is de-tiled by the same decode() path every other texture uses, so it can never
disagree with the core about Morton order or RGB565 layout.

Layout (3dbrew, https://www.3dbrew.org/wiki/SMDH):
  main NCCH -> ExeFS -> "icon" entry == SMDH (0x36C0 bytes)
  ExeFS header is 0x200 bytes: 10 entries of (name[8], offset u32, size u32);
  entry offsets are relative to the end of the header.
  SMDH large icon: offset 0x24C0, 48x48, RGB565, tiled, 0x1200 bytes.
  SMDH small icon: offset 0x2040, 24x24, RGB565, tiled (not used here).

Never raises for the expected failure modes (encrypted ExeFS, missing icon
entry, non-SMDH or truncated data): it logs and returns None so the caller can
fall back to a placeholder. No em dashes (house rule).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from tex_forge.core.exceptions import EncryptedROMError, ROMParseError
from tex_forge.rom.loader import _route
from tex_forge.rom.ncch import NCCHParser
from tex_forge.textures.decoder.dispatch import decode
from tex_forge.textures.formats import PicaFormat

logger = logging.getLogger(__name__)

SMDH_MAGIC = b"SMDH"
EXEFS_HEADER_SIZE = 0x200
EXEFS_ENTRY_COUNT = 10
EXEFS_ENTRY_SIZE = 0x10
LARGE_ICON_OFFSET = 0x24C0
LARGE_ICON_SIZE = 0x1200
LARGE_ICON_DIM = 48


def find_exefs_entry(exefs: bytes, entry_name: bytes) -> Optional[bytes]:
    """Return the bytes of a named ExeFS entry, or None.

    Generalised from the icon lookup so the banner accessor (rom/banner.py)
    shares one header walk; the 10-entry, 0x200-byte ExeFS header layout and
    the offsets-relative-to-header-end rule live here only.
    """
    if len(exefs) < EXEFS_HEADER_SIZE:
        return None
    for i in range(EXEFS_ENTRY_COUNT):
        base = i * EXEFS_ENTRY_SIZE
        name = exefs[base:base + 8].split(b"\x00", 1)[0]
        if name != entry_name:
            continue
        off = int.from_bytes(exefs[base + 8:base + 12], "little")
        size = int.from_bytes(exefs[base + 12:base + 16], "little")
        start = EXEFS_HEADER_SIZE + off
        end = start + size
        if size <= 0 or end > len(exefs):
            return None
        return exefs[start:end]
    return None


def _find_icon_blob(exefs: bytes) -> Optional[bytes]:
    """Return the bytes of the ExeFS 'icon' entry (the SMDH), or None."""
    return find_exefs_entry(exefs, b"icon")


def extract_title_icon(path: str):
    """Decode a title's 48x48 HOME Menu icon to an RGBA8 ndarray, or None.

    Returns a (48, 48, 4) uint8 numpy array on success. Returns None (without
    raising) when the ExeFS is encrypted, there is no icon entry, the entry is
    not a valid SMDH, or the icon is not the expected RGB565 large icon.
    """
    name = os.path.basename(path)
    try:
        with open(path, "rb") as f:
            rom = f.read()
        ext = os.path.splitext(path)[1].lower()
        ncch_data, _title_id, _chain = _route(rom, ext)
        if ncch_data is None:
            logger.info("icon: %s no NCCH container, using placeholder", name)
            return None
        ncch = NCCHParser(ncch_data)
        exefs = ncch.get_exefs()  # raises on encrypted / missing ExeFS
    except EncryptedROMError:
        logger.info("icon: %s ExeFS encrypted, using placeholder", name)
        return None
    except ROMParseError as e:
        logger.info("icon: %s no usable ExeFS (%s)", name, e)
        return None
    except Exception as e:  # defensive: never crash a tile over an icon
        logger.info("icon: %s unexpected container error (%s)", name, e)
        return None

    smdh = _find_icon_blob(exefs)
    if not smdh:
        logger.info("icon: %s has no 'icon' ExeFS entry", name)
        return None
    if smdh[:4] != SMDH_MAGIC:
        logger.info("icon: %s icon entry is not SMDH (magic=%r)", name, smdh[:4])
        return None
    if len(smdh) < LARGE_ICON_OFFSET + LARGE_ICON_SIZE:
        logger.info("icon: %s SMDH too short for the large icon", name)
        return None

    tiled = smdh[LARGE_ICON_OFFSET:LARGE_ICON_OFFSET + LARGE_ICON_SIZE]
    try:
        rgba = decode(tiled, LARGE_ICON_DIM, LARGE_ICON_DIM,
                      int(PicaFormat.RGB565))
    except Exception as e:
        logger.info("icon: %s RGB565 decode failed (%s)", name, e)
        return None
    if rgba is None:
        logger.info("icon: %s decoder returned no data", name)
        return None
    return rgba
