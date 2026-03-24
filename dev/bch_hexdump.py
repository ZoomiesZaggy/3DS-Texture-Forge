"""Hex dump BCH files from real game ROMs to understand the format."""
import sys, os, struct
sys.path.insert(0, os.path.dirname(__file__))

from parsers.ncsd import NCSDParser
from parsers.ncch import NCCHParser
from parsers.romfs import RomFSParser
from parsers.garc import is_garc, parse_garc
from parsers.lz import is_lz_compressed, decompress_lz
from utils import read_u32_le, read_u16_le, read_u8

def hexdump(data, offset, length, label=""):
    end = min(offset + length, len(data))
    if label:
        print(f"\n  [{label}]")
    for i in range(offset, end, 16):
        hex_part = " ".join(f"{data[j]:02X}" for j in range(i, min(i+16, end)))
        ascii_part = "".join(chr(data[j]) if 32 <= data[j] < 127 else "." for j in range(i, min(i+16, end)))
        print(f"    0x{i-offset:04X}: {hex_part:<48s} {ascii_part}")

def analyze_bch(data, label=""):
    if len(data) < 0x20 or data[:3] != b'BCH':
        return

    print(f"\n{'='*70}")
    print(f"BCH: {label} ({len(data):,} bytes)")
    print(f"{'='*70}")

    backward_compat = data[4]
    forward_compat = data[5]
    version = struct.unpack_from('<H', data, 6)[0]

    content_ptr = read_u32_le(data, 0x08)
    string_ptr = read_u32_le(data, 0x0C)
    field_0x10 = read_u32_le(data, 0x10)
    data_ptr = read_u32_le(data, 0x14)
    data_ext_ptr = read_u32_le(data, 0x18)
    reloc_ptr = read_u32_le(data, 0x1C)

    print(f"  Backward compat: 0x{backward_compat:02X}")
    print(f"  Forward compat:  0x{forward_compat:02X}")
    print(f"  Version:         0x{version:04X}")
    print(f"  Content ptr:     0x{content_ptr:08X}")
    print(f"  String ptr:      0x{string_ptr:08X}")
    print(f"  Field 0x10:      0x{field_0x10:08X}")
    print(f"  Data ptr:        0x{data_ptr:08X}")
    print(f"  Data ext ptr:    0x{data_ext_ptr:08X}")
    print(f"  Reloc ptr:       0x{reloc_ptr:08X}")

    hexdump(data, 0, 0x24, "Full header")

    if content_ptr >= len(data):
        print(f"  INVALID content_ptr!")
        return

    ct_size = min(0xC0, len(data) - content_ptr)
    hexdump(data, content_ptr, ct_size, f"Content section at 0x{content_ptr:X}")

    # Try 12-byte stride entries
    print(f"\n  Content table (12-byte entries):")
    for i in range(min(12, (len(data) - content_ptr) // 12)):
        off = content_ptr + i * 12
        if off + 12 > len(data):
            break
        e_off = read_u32_le(data, off)
        e_cnt = read_u32_le(data, off + 4)
        e_unk = read_u32_le(data, off + 8)
        marker = ""
        if e_cnt > 0 and e_cnt < 1000 and e_off < len(data):
            marker = " <-- VALID"
        print(f"    [{i:2d}] off=0x{e_off:08X} cnt={e_cnt:5d} unk=0x{e_unk:08X}{marker}")

    # String table
    if string_ptr < len(data):
        hexdump(data, string_ptr, min(0x100, len(data) - string_ptr), "String table")
        print(f"\n  Strings:")
        pos = string_ptr
        cnt = 0
        while pos < min(string_ptr + 0x300, len(data)) and cnt < 30:
            end_pos = data.find(b'\x00', pos)
            if end_pos < 0 or end_pos == pos:
                pos += 1
                continue
            s = data[pos:end_pos].decode('ascii', errors='replace')
            if len(s) >= 2 and all(c.isprintable() for c in s):
                print(f"    @0x{pos-string_ptr:04X}: \"{s}\"")
                cnt += 1
            pos = end_pos + 1

    # Explore content table entries
    print(f"\n  === Exploring content entries for textures ===")
    for i in range(min(12, (len(data) - content_ptr) // 12)):
        off = content_ptr + i * 12
        e_off = read_u32_le(data, off)
        e_cnt = read_u32_le(data, off + 4)
        if e_cnt == 0 or e_cnt > 500 or e_off == 0:
            continue
        abs_off = content_ptr + e_off
        if abs_off >= len(data):
            continue
        print(f"\n  Entry [{i}]: {e_cnt} items at content+0x{e_off:X} = abs 0x{abs_off:X}")
        dump_size = min(0x60, len(data) - abs_off)
        hexdump(data, abs_off, dump_size, f"Entry [{i}] data")

        # Try to parse as Patricia tree dictionary
        # Dictionary header: u32 count (or sig), then entries
        # Standard BCH dict: first u32 = signature/magic, second u32 = entry count
        # Each entry = 16 bytes: u32(ref_bit | name_off?), u16 left, u16 right, u32 name_off, u32 data_off
        val0 = read_u32_le(data, abs_off)
        val1 = read_u32_le(data, abs_off + 4) if abs_off + 8 <= len(data) else 0

        # Check if this is a dictionary (first entry is root node)
        dict_count = val1 if val1 == e_cnt else val0 if val0 == e_cnt else 0
        dict_header_size = 8 if val1 == e_cnt else 4 if val0 == e_cnt else 8

        if dict_count > 0 and dict_count < 500:
            print(f"    Looks like a dictionary with {dict_count} entries (header={dict_header_size})")
            dict_start = abs_off + dict_header_size
            for j in range(min(dict_count + 1, 8)):
                ent = dict_start + j * 16
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
                    if end_pos > 0:
                        name = data[str_abs:end_pos].decode('ascii', errors='replace')
                print(f"    Dict[{j}]: ref=0x{ref:08X} L={left} R={right} name_off=0x{name_off:X}(\"{name}\") data_off=0x{data_off:X}")

                if data_off > 0 and j > 0 and content_ptr + data_off < len(data):
                    tex_abs = content_ptr + data_off
                    tex_dump = min(0x40, len(data) - tex_abs)
                    hexdump(data, tex_abs, tex_dump, f"Descriptor at content+0x{data_off:X}")
                    print(f"      u32 dump:")
                    for k in range(min(16, (len(data) - tex_abs) // 4)):
                        v = read_u32_le(data, tex_abs + k * 4)
                        notes = ""
                        if v <= 0xD:
                            fmts = ['RGBA8','RGB8','RGBA5551','RGB565','RGBA4','LA8','HILO8','L8','A8','LA4','L4','A4','ETC1','ETC1A4']
                            notes = f" (PICA: {fmts[v]})"
                        elif 4 <= v <= 2048 and (v & (v-1)) == 0:
                            notes = f" (pow2 dim)"
                        print(f"        +0x{k*4:02X}: 0x{v:08X} ({v:10d}){notes}")
                    # Stop after first 2 entries to keep output manageable
                    if j >= 3:
                        print(f"    ... (showing first 3 entries only)")
                        break


def extract_bch_from_rom(rom_path, max_files=3):
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
    file_list = romfs.list_files()  # returns (path, offset, size) tuples

    bch_files = []
    for file_path, file_offset, file_size in file_list:
        file_data = romfs_data[file_offset:file_offset + file_size]
        if len(file_data) < 8:
            continue
        if file_data[:4] == b'BCH\x00':
            bch_files.append((file_path, file_data))
        elif is_garc(file_data):
            inner_files = parse_garc(file_data)
            if inner_files:
                for inner_name, inner_data in inner_files:
                    if inner_data[:4] == b'BCH\x00':
                        bch_files.append((f"{file_path}>{inner_name}", inner_data))
                    elif is_lz_compressed(inner_data, inner_name):
                        try:
                            decomp = decompress_lz(inner_data)
                            if decomp and decomp[:4] == b'BCH\x00':
                                bch_files.append((f"{file_path}>{inner_name}[d]", decomp))
                        except:
                            pass
        elif is_lz_compressed(file_data, file_path):
            try:
                decomp = decompress_lz(file_data)
                if decomp and decomp[:4] == b'BCH\x00':
                    bch_files.append((f"{file_path}[d]", decomp))
            except:
                pass

    print(f"\nFound {len(bch_files)} BCH files total")

    # Pick diverse samples
    bch_files.sort(key=lambda x: len(x[1]))
    if len(bch_files) <= max_files:
        selected = bch_files
    else:
        selected = [bch_files[0], bch_files[len(bch_files)//2], bch_files[-1]]

    for path, bdata in selected:
        analyze_bch(bdata, path)

    return len(bch_files)


if __name__ == "__main__":
    games = [
        r"D:\3ds\Picross 3D - Round 2 (Europe) (En,Fr,De,Es,It).3ds",
        r"D:\3ds\Kirby - Planet Robobot (USA).3ds",
        r"D:\3ds\Mario & Luigi - Dream Team (USA) (En,Fr,Es) (Rev 1).3ds",
    ]
    for rom_path in games:
        if os.path.exists(rom_path):
            extract_bch_from_rom(rom_path, max_files=3)
        else:
            print(f"ROM not found: {rom_path}")
