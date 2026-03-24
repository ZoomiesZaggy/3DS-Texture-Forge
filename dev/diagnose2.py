"""Diagnose MH4U, Kid Icarus, Fire Emblem, Cooking Mama."""
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

def analyze_rom(rom_path, game_name, extra_fn=None):
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
    for ext, c in ext_count.most_common(20):
        magic, path, size = ext_magic.get(ext, (b'????', '', 0))
        try: mlabel = magic.decode('ascii').strip()
        except: mlabel = magic.hex()
        known = '' if ext in KNOWN_EXTS else ' ***UNKNOWN***'
        print(f"  .{ext}: {c:5d}  magic={mlabel:12s}{known}")

    print(f"\nTop magic bytes:")
    for m, c in magic_count.most_common(12):
        try: label = m.decode('ascii')
        except: label = m.hex()
        print(f"  {label:12s} ({m.hex()}): {c}")

    lz_count = sum(1 for p, o, s in files if s >= 4 and rd[o] in (0x10, 0x11, 0x13))
    print(f"\nLZ-compressed (0x10/11/13 header): {lz_count}")

    large = sorted([(s, p, o) for p, o, s in files if s > 5*1024*1024], reverse=True)
    if large:
        print(f"\nLargest files (>5MB):")
        for s, p, o in large[:5]:
            magic = rd[o:o+4]
            try: mlabel = magic.decode('ascii')
            except: mlabel = magic.hex()
            print(f"  {p}: {s/1024/1024:.1f}MB  magic={mlabel}")

    if extra_fn:
        extra_fn(files, rd, ext_count, magic_count, ext_magic)

    return files, rd, ext_count, magic_count, ext_magic

# ─── MH4U ───
def mh4u_extra(files, rd, ext_count, magic_count, ext_magic):
    tex_files = [(p, o, s) for p, o, s in files if p.lower().endswith('.tex')]
    print(f"\n.tex files: {len(tex_files)}")
    for p, o, s in tex_files[:3]:
        print(f"  {p}: {s:,} bytes  magic={rd[o:o+4].hex()}")

    arc_files = [(p, o, s) for p, o, s in files if p.lower().endswith('.arc')]
    print(f".arc files: {len(arc_files)}")

    # MH proprietary formats
    for ext in ['mca','gmd','mhp','mod','lmd','pac','mtxt']:
        c = ext_count.get(ext, 0)
        if c > 0:
            magic, path, size = ext_magic.get(ext, (b'', '', 0))
            print(f"  .{ext}: {c} files, magic={magic.hex()}, example={path} ({size:,})")

    # Check CTPK files specifically
    ctpk_files = [(p, o, s) for p, o, s in files if p.lower().endswith('.ctpk')]
    tex_magic = [(p, o, s) for p, o, s in files if s >= 4 and rd[o:o+4] == b'CTPK']
    print(f"\nCTPK by extension: {len(ctpk_files)}, by magic: {len(tex_magic)}")

    # Sample arc to see what's inside
    if arc_files:
        p, o, s = arc_files[0]
        data = rd[o:o+min(128, s)]
        print(f"\nFirst .arc: {p} ({s:,} bytes)")
        for i in range(0, min(64, len(data)), 16):
            hex_vals = ' '.join(f'{data[i+j]:02X}' for j in range(min(16, len(data)-i)))
            ascii_vals = ''.join(chr(data[i+j]) if 32 <= data[i+j] < 127 else '.' for j in range(min(16, len(data)-i)))
            print(f"  {i:04X}: {hex_vals:<48} {ascii_vals}")
        # Scan for known magic
        full = rd[o:o+s]
        for off in range(0, min(len(full), s), 4):
            chunk = full[off:off+4]
            if chunk in (b'CTPK', b'BCH\x00', b'CGFX', b'SARC'):
                print(f"  >>> Found {chunk} at offset 0x{off:X}!")
                break

analyze_rom(r'D:\3ds\Monster Hunter 4 Ultimate (USA).3ds', 'Monster Hunter 4 Ultimate', mh4u_extra)

# ─── Kid Icarus ───
def ki_extra(files, rd, ext_count, magic_count, ext_magic):
    # Check for SARC/CGFX/BCH
    cgfx = sum(1 for p, o, s in files if s >= 4 and rd[o:o+4] == b'CGFX')
    bch = sum(1 for p, o, s in files if s >= 4 and rd[o:o+3] == b'BCH')
    sarc = sum(1 for p, o, s in files if s >= 4 and rd[o:o+4] == b'SARC')
    print(f"\nKnown texture containers: CGFX={cgfx}, BCH={bch}, SARC={sarc}")

    # Check for .bin files (often packed containers)
    bin_files = [(p, o, s) for p, o, s in files if p.lower().endswith('.bin')]
    print(f".bin files: {len(bin_files)}")
    bin_magic = collections.Counter()
    for p, o, s in bin_files:
        if s >= 4:
            bin_magic[rd[o:o+4]] += 1
    print("Magic in .bin files:")
    for m, c in bin_magic.most_common(10):
        try: label = m.decode('ascii')
        except: label = m.hex()
        print(f"  {label} ({m.hex()}): {c}")

    # Check no-ext files
    no_ext = [(p, o, s) for p, o, s in files if '.' not in p.split('/')[-1]]
    print(f"\nNo-extension files: {len(no_ext)}")
    if no_ext:
        ne_magic = collections.Counter()
        for p, o, s in no_ext:
            if s >= 4:
                ne_magic[rd[o:o+4]] += 1
        for m, c in ne_magic.most_common(10):
            try: label = m.decode('ascii')
            except: label = m.hex()
            print(f"  {label} ({m.hex()}): {c}")

analyze_rom(r'D:\3ds\Kid Icarus - Uprising (USA) (En,Fr,Es).3ds', 'Kid Icarus: Uprising', ki_extra)

# ─── Fire Emblem ───
def fe_extra(files, rd, ext_count, magic_count, ext_magic):
    from parsers.lz import decompress_lz

    lz_files = [(p, o, s) for p, o, s in files
                if s >= 4 and rd[o] in (0x10, 0x11, 0x13)]
    print(f"\nLZ files by magic byte: {len(lz_files)}")

    # Sample decompress
    inner_magics = collections.Counter()
    for p, o, s in lz_files[:50]:
        data = rd[o:o+s]
        try:
            dec = decompress_lz(data)
            if dec and len(dec) >= 4:
                inner_magics[dec[:4]] += 1
        except:
            pass

    print("Inner formats after LZ decompress (sample 50):")
    for m, c in inner_magics.most_common(10):
        try: label = m.decode('ascii')
        except: label = m.hex()
        print(f"  {label} ({m.hex()}): {c}")

    # Check specific file types
    for ext in ['lz','bin','arc','pack']:
        c = ext_count.get(ext, 0)
        if c:
            magic, path, size = ext_magic.get(ext, (b'', '', 0))
            print(f"  .{ext}: {c} files, magic={magic.hex()}, e.g. {path}")

    # Check for .bin.lz or similar
    lz_ext = [(p, o, s) for p, o, s in files if p.lower().endswith('.lz')]
    print(f"\n.lz extension files: {len(lz_ext)}")
    if lz_ext:
        for p, o, s in lz_ext[:5]:
            data = rd[o:o+s]
            try:
                dec = decompress_lz(data)
                inner = dec[:4] if dec else b''
                try: ilabel = inner.decode('ascii')
                except: ilabel = inner.hex()
                print(f"  {p}: {s} -> {len(dec) if dec else 0}, inner={ilabel}")
            except Exception as e:
                print(f"  {p}: decompress error: {e}")

analyze_rom(r'D:\3ds\Fire Emblem - Awakening (USA).3ds', 'Fire Emblem: Awakening', fe_extra)

# ─── Cooking Mama ───
def cm_extra(files, rd, ext_count, magic_count, ext_magic):
    for ext_target in ['chres', 'chtex', 'chspr']:
        matches = [(p, o, s) for p, o, s in files if p.lower().endswith(f'.{ext_target}')]
        if matches:
            print(f"\n.{ext_target}: {len(matches)} files")
            p, o, s = matches[0]
            print(f"  First: {p} ({s:,} bytes)")
            data = rd[o:o+min(128, s)]
            for i in range(0, min(64, len(data)), 16):
                hex_vals = ' '.join(f'{data[i+j]:02X}' for j in range(min(16, len(data)-i)))
                ascii_vals = ''.join(chr(data[i+j]) if 32 <= data[i+j] < 127 else '.' for j in range(min(16, len(data)-i)))
                print(f"    {i:04X}: {hex_vals:<48} {ascii_vals}")
            # Scan full file for known magic
            full = rd[o:o+s]
            for off in range(0, len(full)-3, 4):
                chunk = full[off:off+4]
                if chunk in (b'BCH\x00', b'CGFX', b'CTPK', b'SARC', b'NARC', b'CRAG'):
                    print(f"  >>> Found {chunk} at offset 0x{off:X}!")
                    break
            else:
                print(f"  No known texture magic found in first file")

    # Sample a few different sizes
    chres_files = [(p, o, s) for p, o, s in files if p.lower().endswith('.chres')]
    if chres_files:
        sizes = sorted(set(s for _, _, s in chres_files), reverse=True)
        print(f"\n.chres size distribution: min={min(sizes)}, max={max(sizes)}, median={sizes[len(sizes)//2]}")
        print(f"Top 10 sizes: {sizes[:10]}")

analyze_rom(r'D:\3ds\Cooking Mama - Sweet Shop (USA).3ds', 'Cooking Mama: Sweet Shop', cm_extra)
