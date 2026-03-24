"""Debug BCH GPU command parsing on a single file."""
import sys, os, struct
sys.path.insert(0, os.path.dirname(__file__))
import logging
logging.basicConfig(level=logging.DEBUG)

from parsers.ncsd import NCSDParser
from parsers.ncch import NCCHParser
from parsers.romfs import RomFSParser
from utils import read_u32_le
from textures.bch import (
    BCHHeader, _parse_gpu_commands, _extract_texture_from_regs,
    PICA_TEX0_DIM, PICA_TEX0_TYPE, PICA_TEX0_ADDR,
    _extract_bch_textures_struct, _extract_textures_gpu_multiblock,
    _heuristic_scan,
)

# Load one BCH file from Picross
rom_path = r"D:\3ds\Picross 3D - Round 2 (Europe) (En,Fr,De,Es,It).3ds"
with open(rom_path, 'rb') as f:
    rom_data = f.read()

ncsd = NCSDParser(rom_data)
ncch_data = ncsd.get_partition(0)
ncch = NCCHParser(ncch_data)
romfs_data = ncch_data[ncch.romfs_offset:ncch.romfs_offset + ncch.romfs_size]
from parsers.romfs import RomFSParser
romfs = RomFSParser(romfs_data)

# Find a BCH file with textures (model file)
bch_files = []
for path, offset, size in romfs.list_files():
    d = romfs_data[offset:offset+size]
    if d[:4] == b'BCH\x00' and size > 10000:
        bch_files.append((path, d))

print(f"Found {len(bch_files)} BCH files > 10KB")

# Take one model file with textures
for path, bch_data in bch_files[:3]:
    print(f"\n{'='*60}")
    print(f"File: {path} ({len(bch_data):,} bytes)")

    hdr = BCHHeader(bch_data)
    print(f"  content=0x{hdr.content_addr:X} strings=0x{hdr.strings_addr:X}")
    print(f"  commands=0x{hdr.commands_addr:X} data=0x{hdr.data_addr:X}")

    # Check section [3] (textures)
    tex_off = hdr.content_addr + 3 * 12
    if tex_off + 12 <= len(bch_data):
        ptr = read_u32_le(bch_data, tex_off)
        cnt = read_u32_le(bch_data, tex_off + 4)
        dct = read_u32_le(bch_data, tex_off + 8)
        print(f"  Section[3] (textures): ptr_table=content+0x{ptr:X}, count={cnt}, dict=content+0x{dct:X}")

    # Scan GPU commands for TEX0_DIM writes
    cmd_start = hdr.commands_addr
    cmd_end = hdr.data_addr if hdr.data_addr > cmd_start else len(bch_data)

    dim_writes = []
    pos = cmd_start
    while pos + 8 <= cmd_end:
        param = read_u32_le(bch_data, pos)
        header = read_u32_le(bch_data, pos + 4)
        reg_id = header & 0xFFFF
        extra_params = (header >> 20) & 0xFF

        if reg_id == PICA_TEX0_DIM:
            w = (param >> 16) & 0x7FF
            h = param & 0x7FF
            dim_writes.append((pos, w, h, param))

        entry_size = 8 + extra_params * 4
        if entry_size % 8 != 0:
            entry_size += 4
        pos += max(entry_size, 8)

    print(f"  TEX0_DIM writes found: {len(dim_writes)}")
    for i, (off, w, h, raw) in enumerate(dim_writes[:10]):
        print(f"    [{i}] @0x{off:X}: {w}x{h} (raw=0x{raw:08X})")

    # Now scan for TYPE and ADDR near each DIM write
    for off, w, h, raw in dim_writes[:5]:
        print(f"\n    Scanning near DIM @0x{off:X} ({w}x{h}):")
        # Parse commands in a window around this DIM write
        block_start = off
        block_end = min(off + 128, cmd_end)
        regs = _parse_gpu_commands(bch_data, block_start, block_end)

        type_val = regs.get(PICA_TEX0_TYPE, None)
        addr_val = regs.get(PICA_TEX0_ADDR, None)
        print(f"      TYPE (0x008E): {type_val} (fmt={type_val & 0xF if type_val is not None else '?'})")
        print(f"      ADDR (0x0085): {addr_val} (offset={(addr_val & 0x0FFFFFFF) << 3 if addr_val is not None else '?'})")
        print(f"      All regs: {sorted(hex(r) for r in regs.keys())[:20]}")

    # Compare: struct parser
    struct_textures = _extract_bch_textures_struct(bch_data)
    print(f"\n  Struct parser found: {len(struct_textures)} textures")

    # Compare: multiblock GPU scan
    multiblock_textures = _extract_textures_gpu_multiblock(bch_data, hdr)
    print(f"  GPU multiblock found: {len(multiblock_textures)} textures")

    # Compare: heuristic
    heuristic_textures = _heuristic_scan(bch_data)
    print(f"  Heuristic found: {len(heuristic_textures)} textures")
