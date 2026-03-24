"""Full quality audit across all games."""
import sys, os, subprocess, json, time, hashlib, random
from collections import Counter
from PIL import Image
import numpy as np

ROMS = [
    (r'D:\3ds\Resident Evil - Revelations (USA) (En,Ja,Fr,De,Es,It) (Rev 1).3ds', 'rer'),
    (r'D:\3ds\Corpse Party (USA).3ds', 'corpse_party'),
    (r'D:\3ds\Pokemon Y (USA) (En,Ja,Fr,De,Es,It,Ko).3ds', 'pokemon_y'),
    (r'D:\3ds\Mario Kart 7 (USA) (En,Fr,Es) (Rev 1).3ds', 'mk7'),
    (r'D:\3ds\Legend of Zelda, The - Ocarina of Time 3D (USA) (En,Fr,Es) (Rev 1).3ds', 'zelda_oot'),
    (r'D:\3ds\Picross 3D - Round 2 (Europe) (En,Fr,De,Es,It).3ds', 'picross'),
    (r'D:\3ds\Kirby - Planet Robobot (USA).3ds', 'kirby_robobot'),
    (r'D:\3ds\Nano Assault (USA).3ds', 'nano'),
    (r'D:\3ds\Theatrhythm Final Fantasy (USA).3ds', 'theatrhythm'),
    (r'D:\3ds\Mario & Luigi - Dream Team (USA) (En,Fr,Es) (Rev 1).3ds', 'dream_team'),
    (r'D:\3ds\Kid Icarus - Uprising (USA) (En,Fr,Es).3ds', 'kid_icarus'),
    (r'D:\3ds\Resident Evil - The Mercenaries 3D (USA) (En,Fr) (Rev 1).3ds', 're_mercs'),
    (r'D:\3ds\Cooking Mama - Sweet Shop (USA).3ds', 'cooking_mama'),
    (r'D:\3ds\Fire Emblem - Awakening (USA).3ds', 'fire_emblem'),
    (r'D:\3ds\Super Mario 3D Land (USA) (En,Fr,Es) (Rev 1).3ds', 'sm3dl'),
    (r'D:\3ds\Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds', 'pokemon_or'),
    (r'D:\3ds\Legend of Zelda, The - Majora\'s Mask 3D (USA) (En,Fr,Es) (Rev 1).3ds', 'zelda_mm'),
    (r'D:\3ds\Monster Hunter 4 Ultimate (USA).3ds', 'mh4u'),
    (r'D:\3ds\Kirby - Triple Deluxe (USA) (En,Fr,Es).3ds', 'kirby_td'),
    (r'D:\3ds\Animal Crossing - New Leaf (USA) (En,Fr,Es).3ds', 'animal_crossing'),
    (r'D:\3ds\Bravely Default (USA) (En,Ja,Fr,De,Es,It).3ds', 'bravely_default'),
    (r'D:\3ds\Puzzle & Dragons Z + Puzzle & Dragons Super Mario Bros. Edition (USA).3ds', 'puzzle_dragons'),
]

OUT_BASE = "out/quality_audit"
os.makedirs(OUT_BASE, exist_ok=True)

# Step 1: Extract all games
print("=" * 70)
print("STEP 1: EXTRACTING GAMES")
print("=" * 70)

for rom_path, short in ROMS:
    out_dir = os.path.join(OUT_BASE, short)
    tex_dir = os.path.join(out_dir, "textures")
    manifest = os.path.join(out_dir, "manifest.json")

    if os.path.exists(manifest):
        png_count = 0
        if os.path.isdir(tex_dir):
            for r, d, f in os.walk(tex_dir):
                png_count += sum(1 for x in f if x.endswith('.png'))
        if png_count > 0:
            print(f"SKIP {short}: already extracted ({png_count:,} PNGs)")
            continue

    if not os.path.exists(rom_path):
        print(f"MISSING {short}: {rom_path}")
        continue

    print(f"EXTRACTING {short}...", flush=True)
    t0 = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, "main.py", "extract", rom_path, "-o", out_dir, "--verbose"],
            capture_output=True, text=True, timeout=1800
        )
        elapsed = time.time() - t0
        png_count = 0
        if os.path.isdir(tex_dir):
            for r, d, f in os.walk(tex_dir):
                png_count += sum(1 for x in f if x.endswith('.png'))
        print(f"  Done: {png_count:,} PNGs in {elapsed:.0f}s")
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT after 1800s")
    except Exception as e:
        print(f"  ERROR: {e}")

# Step 2: Quality analysis
print("\n" + "=" * 70)
print("STEP 2: QUALITY ANALYSIS")
print("=" * 70)

results = []

for _, short in ROMS:
    game_dir = os.path.join(OUT_BASE, short)
    manifest_path = os.path.join(game_dir, "manifest.json")
    tex_dir = os.path.join(game_dir, "textures")

    if not os.path.exists(manifest_path):
        results.append({"game": short, "total": 0, "unique": 0, "good_pct": 0,
                        "solid": 0, "tiny": 0, "strip": 0, "error": 0,
                        "dup_pct": 0, "parsers": "n/a", "note": "not extracted"})
        continue

    with open(manifest_path) as f:
        manifest = json.load(f)
    tex_list = manifest.get("textures", [])

    pngs = []
    if os.path.isdir(tex_dir):
        for root, dirs, files in os.walk(tex_dir):
            for f in files:
                if f.endswith(".png"):
                    pngs.append(os.path.join(root, f))

    if not pngs:
        results.append({"game": short, "total": 0, "unique": 0, "good_pct": 0,
                        "solid": 0, "tiny": 0, "strip": 0, "error": 0,
                        "dup_pct": 0, "parsers": "n/a", "note": "no textures"})
        continue

    print(f"Analyzing {short} ({len(pngs):,} PNGs)...", flush=True)

    # Hash for duplicates
    hashes = {}
    for p in pngs:
        try:
            with open(p, 'rb') as f:
                h = hashlib.md5(f.read()).hexdigest()
            hashes.setdefault(h, []).append(p)
        except:
            pass
    unique_count = len(hashes)
    dup_pct = (len(pngs) - unique_count) / max(len(pngs), 1) * 100

    # Sample quality
    random.seed(42)
    sample = random.sample(pngs, min(300, len(pngs)))
    good = solid = tiny = strip = error = 0

    for p in sample:
        try:
            img = Image.open(p)
            arr = np.array(img)
            w, h = img.size

            if w < 4 or h < 4:
                tiny += 1
                continue

            if arr.ndim >= 3 and arr.shape[2] >= 3:
                rgb = arr[:, :, :3]
                flat = rgb.reshape(-1, 3)
            elif arr.ndim == 2:
                flat = arr.reshape(-1, 1)
            else:
                flat = arr[:, :, 0].reshape(-1, 1)

            unique_colors = len(np.unique(flat, axis=0))
            avg_std = np.std(flat.astype(float))
            aspect = max(w, h) / max(min(w, h), 1)

            if unique_colors <= 2 and avg_std < 5:
                solid += 1
            elif aspect > 8 and unique_colors <= 3:
                strip += 1
            else:
                good += 1
        except:
            error += 1

    sample_total = len(sample)
    good_pct = good / max(sample_total, 1) * 100

    parsers = Counter(t.get("source_parser", "?") for t in tex_list)
    parser_str = ", ".join(f"{k}:{v}" for k, v in parsers.most_common(3))

    result = {
        "game": short, "total": len(pngs), "unique": unique_count,
        "dup_pct": round(dup_pct, 1), "good_pct": round(good_pct, 1),
        "solid": solid, "tiny": tiny, "strip": strip, "error": error,
        "parsers": parser_str,
    }
    results.append(result)

# Sort by total descending
results.sort(key=lambda x: -x.get("total", 0))

# Print report
print(f"\n{'='*120}")
print(f"FULL QUALITY AUDIT — ALL GAMES")
print(f"{'='*120}")
print(f"{'Game':<22} {'Total':>8} {'Unique':>8} {'Dup%':>6} {'Good%':>6} {'Solid':>6} {'Tiny':>5} {'Strip':>6} {'Err':>4}")
print(f"{'-'*22} {'-'*8} {'-'*8} {'-'*6} {'-'*6} {'-'*6} {'-'*5} {'-'*6} {'-'*4}")

total_all = 0
unique_all = 0
for r in results:
    total_all += r.get("total", 0)
    unique_all += r.get("unique", 0)
    note = r.get("note", "")
    if note:
        print(f"{r['game']:<22} {r.get('total',0):>8,} {'':>8} {'':>6} {'':>6} {'':>6} {'':>5} {'':>6} {'':>4}  {note}")
    else:
        print(f"{r['game']:<22} {r.get('total',0):>8,} {r.get('unique',0):>8,} {r.get('dup_pct',0):>5.1f}% {r.get('good_pct',0):>5.1f}% {r.get('solid',0):>6} {r.get('tiny',0):>5} {r.get('strip',0):>6} {r.get('error',0):>4}")

print(f"{'-'*22} {'-'*8} {'-'*8}")
print(f"{'TOTAL':<22} {total_all:>8,} {unique_all:>8,}")

# Flagged games
flagged = [r for r in results if r.get("good_pct", 0) < 80 and r.get("total", 0) > 0]
print(f"\n\nFLAGGED GAMES (< 80% good in sample):")
if flagged:
    for r in flagged:
        print(f"  {r['game']}: {r['good_pct']}% good ({r['solid']} solid, {r['tiny']} tiny, {r['strip']} strip)")
else:
    print(f"  None — all games pass quality threshold")

# Contact sheets for flagged + top 3
print(f"\n\nGENERATING CONTACT SHEETS...")
sheet_targets = list(flagged) + [r for r in results[:3] if r not in flagged]
for r in sheet_targets:
    if r.get("total", 0) == 0:
        continue
    game_dir = os.path.join(OUT_BASE, r["game"])
    tex_dir = os.path.join(game_dir, "textures")
    sheet_path = os.path.join(game_dir, "quality_sheet.png")

    candidates = []
    for root, dirs, files in os.walk(tex_dir):
        for f in files:
            if f.endswith(".png"):
                p = os.path.join(root, f)
                try:
                    img = Image.open(p)
                    if img.size[0] >= 16 and img.size[1] >= 16:
                        candidates.append(p)
                except:
                    pass

    if not candidates:
        continue

    random.seed(789)
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
    sheet.save(sheet_path)
    print(f"  Saved: {sheet_path}")

# Summary
print(f"\n{'='*70}")
print(f"SUMMARY")
print(f"{'='*70}")
print(f"  Games audited: {len([r for r in results if r.get('total', 0) > 0])}")
print(f"  Total textures: {total_all:,}")
print(f"  Unique textures: {unique_all:,} ({100*(total_all-unique_all)/max(total_all,1):.0f}% duplicates overall)")
games_above_90 = sum(1 for r in results if r.get("good_pct", 0) >= 90 and r.get("total", 0) > 0)
games_above_80 = sum(1 for r in results if r.get("good_pct", 0) >= 80 and r.get("total", 0) > 0)
print(f"  Games with >= 90% good: {games_above_90}")
print(f"  Games with >= 80% good: {games_above_80}")
print(f"  Games flagged (< 80%): {len(flagged)}")
