"""Game-specific adapters that don't fit the generic plugin model.

Some games store textures in patterns that the registry can't see from a
single file's bytes:

  * Smash Bros 3DS:  one giant 'dt' file indexed by an 'ls' file in RomFS.
                     We have to parse 'ls' first, then synthesise virtual
                     entries for each 'dt' resource.
  * Star Fox 64 3D:  paired .texturegdb (metadata) + .texturebin (pixels)
                     files. Neither alone is a valid texture; both must
                     be supplied together to gdb1.parse_pair().
  * Pokemon Ultra S/M: the v5+ "PC" container format inside a GARC -- not
                     a recognised magic, just a 2-byte 'PC' prefix and a
                     section table with PC-specific format IDs.
  * GARC + BCH:      when a GARC contains BOTH .cgfx and .bch entries, the
                     .bch entries are usually false positives (model data
                     misidentified by BCH's heuristic parser). Suppress.

Each adapter is a small function called from the extractor at the right
seam. They're kept here (rather than scattered through the plugins) so the
plugin code stays generic and the game-specific quirks are findable.
"""

from __future__ import annotations

import logging
import struct
from typing import Dict, Iterator, List, Optional, Tuple

from tex_forge.archives.smash_dt import (
    LS_MAGIC,
    decompress_resource,
    is_texture_resource,
    parse_ls,
)
from tex_forge.core.types import Texture
from tex_forge.textures.containers.gdb1 import parse_pair as _gdb1_parse_pair

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Smash Bros dt/ls adapter
# ─────────────────────────────────────────────────────────────────────────────

def smash_virtual_entries(
    files: List[Tuple[str, int, int]],
    romfs_data: bytes,
) -> Optional[Dict[int, Tuple[int, int, int]]]:
    """If this RomFS contains a Smash dt/ls pair, return a virtual-entry map.

    Returns:
      None if the ROM isn't Smash Bros for 3DS.
      Otherwise: dict mapping virtual_file_index -> (dt_rom_offset, dt_entry_offset, comp_size).

    The caller appends placeholder entries to the file list at indices
    matching the dict, then reads each via decompress_smash_resource().
    """
    ls_entry = next(((p, o, s) for p, o, s in files if p.lower().lstrip("/") == "ls"), None)
    dt_entry = next(((p, o, s) for p, o, s in files if p.lower().lstrip("/") == "dt"), None)
    if ls_entry is None or dt_entry is None:
        return None

    ls_raw = romfs_data[ls_entry[1]:ls_entry[1] + ls_entry[2]]
    if ls_raw[:4] != LS_MAGIC:
        return None

    dt_rom_off = dt_entry[1]
    virtual: Dict[int, Tuple[int, int, int]] = {}
    v_base = len(files)

    for si, (h, dt_off, comp_sz) in enumerate(parse_ls(ls_raw)):
        if comp_sz < 100 or comp_sz > 50 * 1024 * 1024:
            continue

        # Probe: don't index anything that doesn't look zlib-compressed.
        probe = romfs_data[dt_rom_off + dt_off:
                           dt_rom_off + dt_off + min(comp_sz, 600)]
        if not _has_zlib_magic(probe):
            continue

        v_idx = v_base + si
        virtual[v_idx] = (dt_rom_off, dt_off, comp_sz)
        files.append((f"dt_smash_{h:08X}.bch", 0, comp_sz))

    if virtual:
        logger.info("Smash dt/ls: indexed %d virtual entries", len(virtual))
    return virtual


def decompress_smash_resource(romfs_data: bytes, params: Tuple[int, int, int]) -> bytes:
    """Pull and decompress one virtual Smash dt entry. Returns b'' on failure."""
    dt_rom_off, dt_off, comp_sz = params
    raw = romfs_data[dt_rom_off + dt_off:dt_rom_off + dt_off + comp_sz]
    out = decompress_resource(raw)
    if not is_texture_resource(out):
        return b""
    return out


_ZLIB_MAGICS = (b"\x78\x9C", b"\x78\xDA", b"\x78\x01", b"\x78\x5E")


def _has_zlib_magic(probe: bytes) -> bool:
    for i in range(min(512, len(probe) - 1)):
        if probe[i:i + 2] in _ZLIB_MAGICS:
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Star Fox 64 3D paired GDB1 / texturebin adapter
# ─────────────────────────────────────────────────────────────────────────────

def build_texturebin_index(files: List[Tuple[str, int, int]]) -> Dict[str, int]:
    """Map {lowercase_basename: file_idx} for every .texturebin in RomFS."""
    idx: Dict[str, int] = {}
    for i, (path, _o, _s) in enumerate(files):
        if path.lower().endswith(".texturebin"):
            idx[path.rsplit(".", 1)[0].lower()] = i
    return idx


def parse_gdb1_pair_from_index(
    gdb_data: bytes,
    gdb_path: str,
    bin_index: Dict[str, int],
    read_file_by_index,
) -> Iterator[Texture]:
    """Decode a .texturegdb by finding its .texturebin sibling in *bin_index*.

    *read_file_by_index* is the RomFSParser bound method.
    """
    base = gdb_path.rsplit(".", 1)[0].lower()
    bin_idx = bin_index.get(base)
    if bin_idx is None:
        return iter(())
    try:
        _, bin_data = read_file_by_index(bin_idx)
    except Exception as e:
        logger.warning("gdb1 pair read failed for %s: %s", gdb_path, e)
        return iter(())
    return _gdb1_parse_pair(gdb_data, bin_data, gdb_path)


# ─────────────────────────────────────────────────────────────────────────────
# Pokemon GARC + Ultra S/M PC v5+ section adapter
# ─────────────────────────────────────────────────────────────────────────────

#: PC pixel-format code -> PICA200 format ID (Pokemon Ultra S/M only).
_PC_FORMAT_TO_PICA = {
    3: 0x1, 4: 0x0, 22: 0x2, 35: 0x3, 37: 0xD, 40: 0xC,
}


def unwrap_pokemon_container(data: bytes) -> Optional[bytes]:
    """Older Pokemon games (X/Y, OR/AS) wrap inner BCH in a thin PC/PT/GR shell."""
    if len(data) < 0x84:
        return None
    magic2 = data[:2]
    if magic2 in (b"PC", b"PT"):
        if data[0x80:0x84] == b"BCH\x00":
            return data[0x80:]
    elif magic2 == b"GR":
        bch_off = struct.unpack_from("<I", data, 4)[0]
        if 0 < bch_off < len(data) and data[bch_off:bch_off + 4] == b"BCH\x00":
            return data[bch_off:]
    return None


def parse_pokemon_pc_v5(data: bytes, source_path: str) -> List[Texture]:
    """Pokemon Ultra Sun/Moon v5+ section-based 'PC' container.

    Layout: "PC" + version + section_offsets[version+1]. Each texture
    section has a 128-byte header with width/height/format at +0x68, and
    pixel data starting at section_offset + 0x80.
    """
    if len(data) < 0x10 or data[:2] not in (b"PC", b"PT", b"MM"):
        return []
    version = data[2]
    if not (2 <= version <= 30):
        return []

    offsets: List[int] = []
    for i in range(version + 1):
        off = 4 + i * 4
        if off + 4 > len(data):
            return []
        offsets.append(struct.unpack_from("<I", data, off)[0])

    out: List[Texture] = []
    for si in range(len(offsets) - 1):
        sec_off = offsets[si]
        sec_end = offsets[si + 1]
        if sec_off + 0x80 > len(data) or sec_end > len(data):
            continue

        type_end = data.find(b"\x00", sec_off + 8, sec_off + 32)
        if type_end < 0:
            continue
        type_str = data[sec_off + 8:type_end].decode("ascii", errors="replace")
        if type_str != "texture":
            continue

        w = struct.unpack_from("<H", data, sec_off + 0x68)[0]
        h = struct.unpack_from("<H", data, sec_off + 0x6A)[0]
        pc_fmt = struct.unpack_from("<H", data, sec_off + 0x6C)[0]
        if w == 0 or h == 0 or w > 2048 or h > 2048:
            continue

        pica_fmt = _PC_FORMAT_TO_PICA.get(pc_fmt)
        if pica_fmt is None:
            continue

        pixel_off = sec_off + 0x80
        pixel_size = sec_end - pixel_off
        if pixel_size <= 0:
            continue

        name_end = data.find(b"\x00", sec_off + 0x28, sec_off + 0x60)
        tex_name = (data[sec_off + 0x28:name_end].decode("ascii", "replace")
                    if name_end > sec_off + 0x28 else f"tex_{si}")

        out.append(Texture(
            name=tex_name,
            width=w, height=h, format=pica_fmt,
            data=bytes(data[pixel_off:pixel_off + pixel_size]),
            mip_count=1,
            parser_used="pokemon_pc_v5",
            confidence="high",
            source_file=source_path,
        ))

    return out


# ─────────────────────────────────────────────────────────────────────────────
# GARC: suppress BCH entries when CGFX is present (they're usually false positives)
# ─────────────────────────────────────────────────────────────────────────────

def garc_should_suppress_bch(data: bytes) -> bool:
    """True if this GARC contains both BCH and CGFX entries."""
    from tex_forge.archives.garc import has_cgfx
    return has_cgfx(data)
