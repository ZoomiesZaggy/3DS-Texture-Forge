"""Texture quality audit for Pokemon Y and ORAS."""
import sys, os, random, json, hashlib
from pathlib import Path
from collections import Counter
from PIL import Image
import numpy as np

def audit_game(name, tex_dir, manifest_path):
    print(f"\n{'='*70}")
    print(f"AUDIT: {name}")
    print(f"{'='*70}")

    with open(manifest_path) as f:
        manifest = json.load(f)
    textures = manifest.get("textures", [])
    print(f"Total textures in manifest: {len(textures)}")

    # Parser breakdown
    parsers = Counter(t.get("source_parser", "unknown") for t in textures)
    print(f"\nParser breakdown:")
    for p, c in parsers.most_common():
        print(f"  {p}: {c}")

    # Dimension breakdown
    dims = Counter(f"{t.get('width', '?')}x{t.get('height', '?')}" for t in textures)
    print(f"\nTop 15 dimensions:")
    for d, c in dims.most_common(15):
        print(f"  {d}: {c}")

    # LZ vs non-LZ sources
    lz_sources = 0
    non_lz_sources = 0
    for t in textures:
        source = t.get("source_file", "")
        if "[d]" in source or "[lz]" in source or ".bin[" in source or "[unwrap]" in source:
            lz_sources += 1
        else:
            non_lz_sources += 1
    print(f"\nFrom LZ/unwrapped GARC entries: {lz_sources}")
    print(f"From direct entries: {non_lz_sources}")

    # Find all PNGs
    pngs = []
    for root, dirs, files in os.walk(tex_dir):
        for f in files:
            if f.endswith(".png"):
                pngs.append(os.path.join(root, f))
    print(f"\nTotal PNGs on disk: {len(pngs)}")

    # Hash for duplicates
    print(f"\nHashing PNGs for duplicates...")
    hashes = {}
    for p in pngs:
        try:
            with open(p, 'rb') as f:
                h = hashlib.md5(f.read()).hexdigest()
            hashes.setdefault(h, []).append(p)
        except:
            pass
    unique_hashes = len(hashes)
    duplicate_files = len(pngs) - unique_hashes
    print(f"Unique textures (by content hash): {unique_hashes}")
    print(f"Exact duplicates: {duplicate_files} ({100*duplicate_files/max(len(pngs),1):.1f}%)")

    # Most duplicated
    most_duped = sorted(hashes.items(), key=lambda x: -len(x[1]))
    print(f"\nMost duplicated textures:")
    for h, paths in most_duped[:10]:
        try:
            img = Image.open(paths[0])
            w, h_px = img.size
        except:
            w, h_px = 0, 0
        short = os.path.basename(paths[0])
        print(f"  {short} ({w}x{h_px}): {len(paths)} copies")

    # Sample quality
    random.seed(42)
    sample = random.sample(pngs, min(200, len(pngs)))

    good = 0
    solid = 0
    tiny = 0
    strip = 0
    error = 0

    for path in sample:
        try:
            img = Image.open(path)
            arr = np.array(img)
            w, h = img.size

            if w < 8 or h < 8:
                tiny += 1
                continue

            aspect = max(w, h) / max(min(w, h), 1)
            if aspect > 8:
                strip += 1
                continue

            if arr.ndim >= 3 and arr.shape[2] >= 3:
                rgb = arr[:, :, :3]
                flat = rgb.reshape(-1, 3)
            else:
                flat = arr.reshape(-1, 1)

            unique_colors = len(np.unique(flat, axis=0))

            if unique_colors <= 3:
                solid += 1
            else:
                good += 1
        except:
            error += 1

    total_sample = len(sample)
    print(f"\n=== SAMPLE QUALITY ({total_sample} random PNGs) ===")
    print(f"  good: {good} ({100*good/total_sample:.0f}%)")
    print(f"  solid_color (<=3 colors): {solid} ({100*solid/total_sample:.0f}%)")
    print(f"  tiny (<8x8): {tiny} ({100*tiny/total_sample:.0f}%)")
    print(f"  strip (aspect>8:1): {strip} ({100*strip/total_sample:.0f}%)")
    print(f"  error: {error} ({100*error/total_sample:.0f}%)")

    # Largest textures
    sized = []
    for p in pngs:
        try:
            sized.append((os.path.getsize(p), p))
        except:
            pass
    sized.sort(reverse=True)
    print(f"\nLargest textures (most likely real content):")
    for sz, path in sized[:10]:
        try:
            img = Image.open(path)
            w, h = img.size
            short = os.path.basename(path)
            print(f"  {short}: {w}x{h}, {sz:,} bytes")
        except:
            pass

    return {
        "total": len(pngs),
        "unique": unique_hashes,
        "duplicates": duplicate_files,
        "dup_pct": round(100*duplicate_files/max(len(pngs),1), 1),
        "good_pct": round(100*good/total_sample),
        "solid_pct": round(100*solid/total_sample),
        "tiny_pct": round(100*tiny/total_sample),
        "strip_pct": round(100*strip/total_sample),
        "lz_sources": lz_sources,
        "non_lz_sources": non_lz_sources,
        "pngs": pngs,
    }


# Run audits
pky = audit_game(
    "Pokemon Y",
    "out/oras_reg/pokemon_y/textures",
    "out/oras_reg/pokemon_y/manifest.json"
)

oras = audit_game(
    "Pokemon Omega Ruby",
    "out/oras_v2/textures",
    "out/oras_v2/manifest.json"
)

# Generate contact sheet for Pokemon Y
print(f"\n{'='*70}")
print("GENERATING CONTACT SHEET")
print(f"{'='*70}")

candidates = []
for p in pky["pngs"]:
    try:
        img = Image.open(p)
        if img.size[0] >= 32 and img.size[1] >= 32:
            candidates.append(p)
    except:
        pass

random.seed(123)
picks = random.sample(candidates, min(48, len(candidates)))

CELL = 128
COLS, ROWS = 8, 6
sheet = Image.new('RGBA', (COLS * CELL, ROWS * CELL), (30, 30, 30, 255))

for i, path in enumerate(picks):
    try:
        img = Image.open(path).convert('RGBA')
        img.thumbnail((CELL - 4, CELL - 4), Image.LANCZOS)
        col = i % COLS
        row = i // COLS
        x = col * CELL + (CELL - img.width) // 2
        y = row * CELL + (CELL - img.height) // 2
        sheet.paste(img, (x, y), img)
    except:
        pass

sheet.save("out/oras_reg/pokemon_y/quality_sample_sheet.png")
print("Saved: out/oras_reg/pokemon_y/quality_sample_sheet.png")

# Summary
print(f"\n{'='*70}")
print("TEXTURE QUALITY AUDIT SUMMARY")
print(f"{'='*70}")
print(f"""
Pokemon Y (126,690 textures):
  Sample quality (200 random): {pky['good_pct']}% good, {pky['solid_pct']}% solid, {pky['tiny_pct']}% tiny, {pky['strip_pct']}% strip
  Unique textures: {pky['unique']:,} ({pky['dup_pct']}% are duplicates)
  From LZ-GARC entries: {pky['lz_sources']:,}
  From non-LZ entries: {pky['non_lz_sources']:,}

Pokemon Omega Ruby (36,433 textures):
  Sample quality: {oras['good_pct']}% good, {oras['solid_pct']}% solid
  Unique textures: {oras['unique']:,} ({oras['dup_pct']}% are duplicates)
  From LZ-GARC entries: {oras['lz_sources']:,}
  From non-LZ entries: {oras['non_lz_sources']:,}
""")
