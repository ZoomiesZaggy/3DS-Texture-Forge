#!/usr/bin/env python3
"""Quick triage of zero-texture games — profile file types and magic bytes."""
import os, sys, struct, collections

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parsers.ncsd import NCSDParser
from parsers.ncch import NCCHParser
from parsers.romfs import RomFSParser

ROM_DIR = r"D:\3ds Rom set\No-Intro\Nintendo - Nintendo 3DS (Decrypted)"

def profile_rom(rom_path):
    """Return file extension counts and magic bytes for a ROM."""
    try:
        with open(rom_path, 'rb') as f:
            rom = f.read()
    except Exception as e:
        return None, str(e)

    # Parse ROM structure
    try:
        if rom[0x100:0x104] == b'NCSD':
            ncsd = NCSDParser(rom)
            ncch_data = ncsd.get_partition(0)
        elif rom[0x100:0x104] == b'NCCH':
            ncch_data = rom
        else:
            return None, "Unknown ROM format"

        ncch = NCCHParser(ncch_data)
        if ncch.romfs_size == 0:
            return None, "No RomFS"

        rd = ncch.get_romfs()
        romfs = RomFSParser(rd)
    except RuntimeError as e:
        if "encrypted" in str(e).lower():
            return None, "Encrypted"
        return None, f"Parse error: {e}"
    except Exception as e:
        return None, f"Parse error: {e}"

    # Collect stats
    ext_counts = collections.Counter()
    ext_sizes = collections.Counter()
    magic_samples = {}  # ext -> (magic_bytes, size, path)
    total_files = 0

    for path, off, sz in romfs.list_files():
        total_files += 1
        ext = path.rsplit('.', 1)[-1].lower() if '.' in path else 'noext'
        ext_counts[ext] += 1
        ext_sizes[ext] += sz

        if ext not in magic_samples and sz > 32:
            data = rd[off:off + min(64, sz)]
            magic_samples[ext] = (data, sz, path)

    return {
        'total_files': total_files,
        'ext_counts': ext_counts,
        'ext_sizes': ext_sizes,
        'magic_samples': magic_samples,
    }, None


def format_magic(data, max_bytes=32):
    """Format magic bytes as hex + ASCII."""
    hex_str = ' '.join(f'{b:02x}' for b in data[:max_bytes])
    ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data[:max_bytes])
    return f'{hex_str}  |{ascii_str}|'


def main():
    games = sys.argv[1:] if len(sys.argv) > 1 else []
    if not games:
        # Profile all ROMs in directory
        games = sorted(f for f in os.listdir(ROM_DIR) if f.endswith(('.3ds', '.cia')))

    for rom_name in games:
        rom_path = os.path.join(ROM_DIR, rom_name)
        if not os.path.exists(rom_path):
            print(f"\n{'='*60}")
            print(f"SKIP: {rom_name} — not found")
            continue

        print(f"\n{'='*60}")
        print(f"GAME: {rom_name}")
        print(f"{'='*60}")

        result, error = profile_rom(rom_path)
        if error:
            print(f"  ERROR: {error}")
            continue

        print(f"  Total files: {result['total_files']}")
        print(f"  Top extensions:")
        for ext, count in result['ext_counts'].most_common(10):
            size_mb = result['ext_sizes'][ext] / (1024*1024)
            magic_data = result['magic_samples'].get(ext)
            magic_str = ""
            if magic_data:
                magic_str = f"  magic: {format_magic(magic_data[0], 16)}"
            print(f"    .{ext:12s} {count:5d} files  ({size_mb:8.1f} MB){magic_str}")


if __name__ == '__main__':
    main()
