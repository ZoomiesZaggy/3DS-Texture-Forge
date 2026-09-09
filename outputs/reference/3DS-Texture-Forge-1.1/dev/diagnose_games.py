"""Diagnose low-count games to identify texture extraction blockers."""
import sys, struct, collections
sys.path.insert(0, '.')
from parsers.ncsd import NCSDParser
from parsers.ncch import NCCHParser
from parsers.romfs import RomFSParser

KNOWN_EXTS = {
    'bch','cgfx','ctpk','bflim','bclim','ctxb','cmb','tex','arc','sarc','szs',
    'lz','cmp','garc','narc','zar','bcmdl','bcmcla','bctex','bccam','bcsdr',
    'bcptl','bhres','bhtex','cbres','bin','bcres','zan','zsi'
}

def analyze_rom(rom_path, game_name):
    print(f"\n{'='*70}")
    print(f"ANALYZING: {game_name}")
    print(f"{'='*70}")

    with open(rom_path, 'rb') as f:
        rom = f.read()
    ncsd = NCSDParser(rom)
    ncch = NCCHParser(ncsd.get_partition(0))
    rd = ncch.get_romfs()
    romfs = RomFSParser(rd)
    files = romfs.list_files()

    print(f"Total RomFS files: {len(files)}")

    ext_count = collections.Counter()
    magic_count = collections.Counter()
    ext_magic = {}

    for p, o, s in files:
        ext = p.rsplit('.', 1)[-1].lower() if '.' in p else 'no_ext'
        ext_count[ext] += 1
        if s >= 4:
            magic = rd[o:o+4]
            magic_count[magic] += 1
            if ext not in ext_magic:
                ext_magic[ext] = (magic, p, s)

    print(f"\nTop extensions:")
    for ext, c in ext_count.most_common(25):
        magic, path, size = ext_magic.get(ext, (b'????', '', 0))
        try: mlabel = magic.decode('ascii').strip()
        except: mlabel = magic.hex()
        known = '' if ext in KNOWN_EXTS else ' ***UNKNOWN***'
        print(f"  .{ext}: {c:5d}  magic={mlabel:10s}{known}")

    print(f"\nTop magic bytes (all files):")
    for m, c in magic_count.most_common(15):
        try: label = m.decode('ascii')
        except: label = m.hex()
        print(f"  {label:12s} ({m.hex()}): {c}")

    # Check LZ files
    lz_count = sum(1 for p, o, s in files if s >= 4 and rd[o] in (0x10, 0x11, 0x13))
    print(f"\nLZ-compressed (header byte 0x10/0x11/0x13): {lz_count}")

    # Large files
    large = sorted([(s, p, o) for p, o, s in files if s > 2*1024*1024], reverse=True)
    print(f"\nLargest files (>2MB):")
    for s, p, o in large[:8]:
        magic = rd[o:o+4]
        try: mlabel = magic.decode('ascii')
        except: mlabel = magic.hex()
        print(f"  {p}: {s/1024/1024:.1f}MB  magic={mlabel}")

    return files, rd, ext_count, magic_count, ext_magic

# ─── Zelda MM3D ───
mm_files, mm_rd, mm_ext, mm_magic, mm_ext_magic = analyze_rom(
    r"D:\3ds\Legend of Zelda, The - Majora's Mask 3D (USA) (En,Fr,Es) (Rev 1).3ds",
    "Zelda: Majora's Mask 3D"
)

# Check Grezzo formats
zar_count = sum(1 for p, o, s in mm_files if s >= 4 and mm_rd[o:o+4] == b'ZAR\x01')
cmb_count = mm_ext.get('cmb', 0)
ctxb_count = mm_ext.get('ctxb', 0)
zan_count = mm_ext.get('zan', 0)
zsi_count = mm_ext.get('zsi', 0)
print(f"\nGrezzo formats: ZAR={zar_count}, cmb={cmb_count}, ctxb={ctxb_count}, zan={zan_count}, zsi={zsi_count}")

# Sample a ZAR file to see its inner structure
zar_files = [(p, o, s) for p, o, s in mm_files if s >= 4 and mm_rd[o:o+4] == b'ZAR\x01']
if zar_files:
    p, o, s = zar_files[0]
    data = mm_rd[o:o+min(256, s)]
    print(f"\nFirst ZAR: {p} ({s:,} bytes)")
    print("Header (first 128 bytes):")
    for i in range(0, min(128, len(data)), 16):
        hex_vals = ' '.join(f'{data[i+j]:02X}' for j in range(min(16, len(data)-i)))
        ascii_vals = ''.join(chr(data[i+j]) if 32 <= data[i+j] < 127 else '.' for j in range(min(16, len(data)-i)))
        print(f"  {i:04X}: {hex_vals:<48} {ascii_vals}")

# Check for BCRES/CRES inside no_ext files
no_ext = [(p, o, s) for p, o, s in mm_files if '.' not in p.split('/')[-1]]
print(f"\nFiles with no extension: {len(no_ext)}")
if no_ext:
    magic_ctr = collections.Counter()
    for p, o, s in no_ext:
        if s >= 4:
            magic_ctr[mm_rd[o:o+4]] += 1
    print("Magic bytes in no-ext files:")
    for m, c in magic_ctr.most_common(10):
        try: label = m.decode('ascii')
        except: label = m.hex()
        print(f"  {label} ({m.hex()}): {c}")
