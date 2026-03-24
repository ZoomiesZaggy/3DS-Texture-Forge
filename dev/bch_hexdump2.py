"""Phase 2: Focused BCH texture descriptor analysis."""
import sys, os, struct, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(__file__))

from parsers.ncsd import NCSDParser
from parsers.ncch import NCCHParser
from parsers.romfs import RomFSParser
from parsers.garc import is_garc, parse_garc
from parsers.lz import is_lz_compressed, decompress_lz
from utils import read_u32_le, read_u16_le, read_u8

PICA_FMTS = ['RGBA8','RGB8','RGBA5551','RGB565','RGBA4','LA8','HILO8','L8','A8','LA4','L4','A4','ETC1','ETC1A4']

def hexdump(data, offset, length, label=""):
    end = min(offset + length, len(data))
    if label:
        print(f"  [{label}]")
    for i in range(offset, end, 16):
        hex_part = " ".join(f"{data[j]:02X}" for j in range(i, min(i+16, end)))
        ascii_part = "".join(chr(data[j]) if 32 <= data[j] < 127 else "." for j in range(i, min(i+16, end)))
        print(f"    0x{i-offset:04X}: {hex_part:<48s} {ascii_part}")

def analyze_bch_textures(data, label=""):
    """Deep analysis of BCH texture data."""
    if len(data) < 0x20 or data[:3] != b'BCH':
        return

    print(f"\n{'='*70}")
    print(f"BCH: {label} ({len(data):,} bytes)")
    print(f"{'='*70}")

    content_ptr = read_u32_le(data, 0x08)
    string_ptr = read_u32_le(data, 0x0C)
    gpu_cmd_ptr = read_u32_le(data, 0x10)
    data_ptr = read_u32_le(data, 0x14)
    data_ext_ptr = read_u32_le(data, 0x18)
    reloc_ptr = read_u32_le(data, 0x1C)
    backward = data[4]
    version = struct.unpack_from('<H', data, 6)[0]

    print(f"  backward=0x{backward:02X} version=0x{version:04X}")
    print(f"  content=0x{content_ptr:X} strings=0x{string_ptr:X} gpu=0x{gpu_cmd_ptr:X}")
    print(f"  data=0x{data_ptr:X} data_ext=0x{data_ext_ptr:X} reloc=0x{reloc_ptr:X}")

    # Read content table (12-byte entries)
    print(f"\n  Content table at 0x{content_ptr:X} (12-byte entries):")
    sections = []
    for i in range(20):
        off = content_ptr + i * 12
        if off + 12 > len(data):
            break
        e_off = read_u32_le(data, off)
        e_cnt = read_u32_le(data, off + 4)
        e_dict = read_u32_le(data, off + 8)
        sections.append((e_off, e_cnt, e_dict))
        if e_cnt > 0 and e_cnt < 1000:
            print(f"    [{i:2d}] ptr_table=content+0x{e_off:X}  count={e_cnt}  dict=content+0x{e_dict:X}")
        # Stop if we've clearly gone past the content table
        if off + 12 >= string_ptr or off + 12 >= gpu_cmd_ptr:
            break

    # The texture section: according to Ohana3DS, section layout depends on version.
    # Common pattern: textures are the section with texture names.
    # Let's check each section's dictionary for texture-like names.
    print(f"\n  === Searching sections for texture data ===")
    for idx, (e_off, e_cnt, e_dict) in enumerate(sections):
        if e_cnt == 0 or e_cnt > 500:
            continue

        # The dict field points to a Patricia tree dictionary
        dict_abs = content_ptr + e_dict
        if dict_abs + 8 > len(data):
            continue

        # Parse dictionary
        dict_entries = []
        # Dict header: skip 8 bytes (usually count + padding or sig + count)
        # Then entries of 16 bytes each
        # But let's also try: first u32 = count itself
        test_cnt = read_u32_le(data, dict_abs)

        # Standard dictionary: entries start at dict_abs + 8, each 16 bytes
        # Entry 0 is root, entries 1..N are real entries
        for j in range(min(e_cnt + 1, 20)):
            ent = dict_abs + 8 + j * 16
            if ent + 16 > len(data):
                break
            ref = read_u32_le(data, ent)
            left = read_u16_le(data, ent + 4)
            right = read_u16_le(data, ent + 6)
            name_off = read_u32_le(data, ent + 8)
            data_off = read_u32_le(data, ent + 12)

            name = ""
            str_abs = string_ptr + name_off
            if str_abs < len(data):
                end_pos = data.find(b'\x00', str_abs)
                if end_pos > 0 and end_pos - str_abs < 256:
                    name = data[str_abs:end_pos].decode('ascii', errors='replace')

            dict_entries.append((ref, left, right, name_off, data_off, name))

        if not dict_entries:
            continue

        # Check if any names look texture-like
        names = [e[5] for e in dict_entries[1:]]  # skip root
        print(f"\n  Section [{idx}] count={e_cnt} dict@content+0x{e_dict:X}: names={names[:5]}")

        # For each non-root entry, follow data_off to find the descriptor
        for j, (ref, left, right, name_off, data_off, name) in enumerate(dict_entries):
            if j == 0:
                continue  # skip root
            if data_off == 0:
                continue

            desc_abs = content_ptr + data_off
            if desc_abs + 0x20 > len(data):
                continue

            print(f"\n    Entry \"{name}\" -> descriptor at content+0x{data_off:X} (abs 0x{desc_abs:X})")
            hexdump(data, desc_abs, min(0x40, len(data) - desc_abs), f"Descriptor")

            # Dump as u32 values with annotations
            print(f"    u32 dump:")
            for k in range(min(16, (len(data) - desc_abs) // 4)):
                v = read_u32_le(data, desc_abs + k * 4)
                notes = ""
                if v <= 0xD:
                    notes = f" *** PICA: {PICA_FMTS[v]}"
                elif 4 <= v <= 2048 and v > 0 and (v & (v-1)) == 0:
                    notes = f" *** pow2 ({v})"
                elif v > 0 and v < len(data) and v > content_ptr:
                    notes = f" (ptr?)"
                print(f"      +0x{k*4:02X}: 0x{v:08X} ({v:10d}){notes}")

            # Also check: does the descriptor contain a pointer to GPU commands?
            # The texture descriptor might reference GPU command blocks
            # that contain the actual width/height/format
            for k in range(min(8, (len(data) - desc_abs) // 4)):
                v = read_u32_le(data, desc_abs + k * 4)
                # Check if this looks like an offset into the GPU command section
                if gpu_cmd_ptr > 0 and v > 0 and gpu_cmd_ptr + v < len(data):
                    gpu_abs = gpu_cmd_ptr + v
                    if gpu_abs + 0x20 <= len(data):
                        # Dump GPU commands at this offset
                        print(f"\n    GPU commands at gpu+0x{v:X} (abs 0x{gpu_abs:X}) [from desc+0x{k*4:X}]:")
                        # GPU commands are pairs: u32 value, u32 command_id
                        # Command format: bits [19:16] = param count, bits [15:0] = register id
                        for ci in range(8):
                            cmd_off = gpu_abs + ci * 8
                            if cmd_off + 8 > len(data):
                                break
                            cmd_val = read_u32_le(data, cmd_off)
                            cmd_id = read_u32_le(data, cmd_off + 4)
                            reg = cmd_id & 0xFFFF
                            param_cnt = (cmd_id >> 16) & 0xF
                            notes = ""
                            # Known PICA200 texture registers
                            if reg == 0x008E:
                                notes = f" TEX0 size: w={cmd_val & 0xFFFF} h={cmd_val >> 16}"
                            elif reg == 0x0085:
                                notes = f" TEX0 format/type"
                            elif reg == 0x0083:
                                notes = f" TEX0 addr"
                            elif reg == 0x0092:
                                notes = f" TEX1 size"
                            elif reg == 0x0096:
                                notes = f" TEX2 size"
                            elif cmd_val <= 0xD:
                                notes = f" (={PICA_FMTS[cmd_val]}?)"
                            elif 4 <= cmd_val <= 2048 and (cmd_val & (cmd_val-1)) == 0:
                                notes = f" ({cmd_val} pow2)"
                            print(f"      cmd[{ci}]: val=0x{cmd_val:08X} id=0x{cmd_id:08X} (reg=0x{reg:04X} params={param_cnt}){notes}")

            if j >= 3:
                print(f"    ... (first 3 entries shown)")
                break

    # Also dump the GPU commands section header for reference
    if gpu_cmd_ptr > 0 and gpu_cmd_ptr < len(data):
        hexdump(data, gpu_cmd_ptr, min(0x80, len(data) - gpu_cmd_ptr), f"GPU commands section at 0x{gpu_cmd_ptr:X}")


def extract_bch_from_rom(rom_path, max_tex_files=3):
    print(f"\n{'#'*70}")
    print(f"ROM: {os.path.basename(rom_path)}")
    print(f"{'#'*70}")

    with open(rom_path, 'rb') as f:
        rom_data = f.read()

    ncsd = NCSDParser(rom_data)
    ncch_data = ncsd.get_partition(0)
    ncch = NCCHParser(ncch_data)

    romfs_off = ncch.romfs_offset
    romfs_size = ncch.romfs_size
    romfs_data = ncch_data[romfs_off:romfs_off + romfs_size]
    romfs = RomFSParser(romfs_data)
    file_list = romfs.list_files()

    bch_files = []
    for file_path, file_offset, file_size in file_list:
        file_data = romfs_data[file_offset:file_offset + file_size]
        if len(file_data) < 8:
            continue
        if file_data[:4] == b'BCH\x00':
            bch_files.append((file_path, file_data))
        elif is_garc(file_data):
            inner = parse_garc(file_data)
            if inner:
                for iname, idata in inner:
                    if idata[:4] == b'BCH\x00':
                        bch_files.append((f"{file_path}>{iname}", idata))
                    elif is_lz_compressed(idata, iname):
                        try:
                            d = decompress_lz(idata)
                            if d and d[:4] == b'BCH\x00':
                                bch_files.append((f"{file_path}>{iname}[d]", d))
                        except:
                            pass
        elif is_lz_compressed(file_data, file_path):
            try:
                d = decompress_lz(file_data)
                if d and d[:4] == b'BCH\x00':
                    bch_files.append((f"{file_path}[d]", d))
            except:
                pass

    print(f"\nFound {len(bch_files)} BCH files")

    # Pick files that are likely to have textures (medium-large, not just models)
    # Filter for files with "tex" in name or larger files
    tex_candidates = [(p, d) for p, d in bch_files if any(k in p.lower() for k in ['tex', 'sticker', 'image', 'bg', 'effect'])]
    if not tex_candidates:
        # Pick the 3 largest, they likely have textures
        bch_files.sort(key=lambda x: len(x[1]), reverse=True)
        tex_candidates = bch_files[:max_tex_files]
    else:
        tex_candidates = tex_candidates[:max_tex_files]

    # Also pick one model file for comparison
    model_files = [(p, d) for p, d in bch_files if any(k in p.lower() for k in ['model', 'cm_', 'chr'])]
    if model_files:
        tex_candidates.append(model_files[0])

    for path, bdata in tex_candidates[:max_tex_files + 1]:
        analyze_bch_textures(bdata, path)


if __name__ == "__main__":
    games = [
        r"D:\3ds\Picross 3D - Round 2 (Europe) (En,Fr,De,Es,It).3ds",
        r"D:\3ds\Mario & Luigi - Dream Team (USA) (En,Fr,Es) (Rev 1).3ds",
        r"D:\3ds\Kirby - Planet Robobot (USA).3ds",
    ]
    for rom_path in games:
        if os.path.exists(rom_path):
            extract_bch_from_rom(rom_path, max_tex_files=2)
        else:
            print(f"ROM not found: {rom_path}")
