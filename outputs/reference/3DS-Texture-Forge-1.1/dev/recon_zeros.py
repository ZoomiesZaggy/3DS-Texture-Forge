import sys, struct, collections
sys.path.insert(0, '.')
from parsers.ncsd import NCSDParser
from parsers.ncch import NCCHParser
from parsers.romfs import RomFSParser

games = [
    ("Luigi's Mansion - Dark Moon", r"D:\3ds\Luigi's Mansion - Dark Moon (USA) (En,Fr,Es).3ds"),
    ("Star Fox 64 3D", r"D:\3ds\Star Fox 64 3D (USA) (En,Fr,Es) (Rev 3).3ds"),
    ("Super Mario 3D Land", r"D:\3ds\Super Mario 3D Land (USA) (En,Fr,Es) (Rev 1).3ds"),
    ("Super Smash Bros 3DS", r"D:\3ds\Super Smash Bros. for Nintendo 3DS (USA) (En,Fr,Es) (Rev 11).3ds"),
]

for name, rom_path in games:
    print(f"\n{'='*60}")
    print(f"RECON: {name}")
    print(f"{'='*60}")

    try:
        with open(rom_path, 'rb') as f:
            rom = f.read()

        ncsd = NCSDParser(rom)
        ncch_data = ncsd.get_partition(0)
        ncch = NCCHParser(ncch_data)
        rd = ncch_data[ncch.romfs_offset:ncch.romfs_offset + ncch.romfs_size]
        romfs = RomFSParser(rd)
        files = romfs.list_files()

        print(f'Total files: {len(files)}')

        ext_count = collections.Counter()
        magic_count = collections.Counter()
        size_by_ext = collections.Counter()
        for p, o, s in files:
            ext = p.rsplit('.', 1)[-1].lower() if '.' in p else 'no_ext'
            ext_count[ext] += 1
            size_by_ext[ext] += s
            if s >= 4:
                magic_count[rd[o:o+4]] += 1

        print(f'\nExtensions (top 15):')
        for ext, c in ext_count.most_common(15):
            sz = size_by_ext[ext] / 1024 / 1024
            print(f'  .{ext}: {c} files ({sz:.1f} MB)')

        print(f'\nTop magic bytes:')
        for m, c in magic_count.most_common(10):
            try:
                label = m.decode('ascii')
            except:
                label = m.hex()
            print(f'  {label} ({m.hex()}): {c}')

    except Exception as e:
        print(f'  ERROR: {e}')
