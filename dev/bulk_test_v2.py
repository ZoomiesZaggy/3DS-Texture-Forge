import sys, os, json, time, subprocess, shutil
from pathlib import Path

ROM_DIR = r"D:\3ds"
OUT_BASE = "out/bulk_v2"
os.makedirs(OUT_BASE, exist_ok=True)

# Games already tested — match by substring
SKIP_SUBSTRINGS = [
    "Resident Evil - Revelations (USA)",
    "Corpse Party",
    "Pokemon Y",
    "Mario Kart 7",
    "Ocarina of Time 3D",
    "Picross 3D",
    "Planet Robobot",
    "Nano Assault",
    "Theatrhythm",
    "Kid Icarus",
    "Mercenaries 3D",
    "Cooking Mama",
    "Fire Emblem - Awakening",
    "Ghost Recon",
    "Dream Team",
    "Puzzle & Dragons",
    "Puzzle and Dragons",
]

# Find all ROMs
roms = []
for f in sorted(Path(ROM_DIR).iterdir()):
    if f.suffix.lower() in ('.3ds', '.cia'):
        skip = any(sub.lower() in f.name.lower() for sub in SKIP_SUBSTRINGS)
        if not skip:
            roms.append(f)

print(f"Found {len(roms)} untested ROMs:")
for r in roms:
    print(f"  {r.name} ({r.stat().st_size / 1024 / 1024:.0f} MB)")

results = []
for rom in roms:
    short = rom.stem[:40].replace(" ", "_")
    out_dir = os.path.join(OUT_BASE, short)
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"TESTING: {rom.name}")
    print(f"{'='*60}")

    t0 = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, "main.py", "extract", str(rom), "-o", out_dir, "--verbose"],
            capture_output=True, text=True, timeout=600
        )
        elapsed = time.time() - t0

        # Count PNGs
        png_count = 0
        tex_dir = os.path.join(out_dir, "textures")
        if os.path.isdir(tex_dir):
            for root, dirs, files in os.walk(tex_dir):
                png_count += sum(1 for f in files if f.endswith(".png"))

        # Read manifest for parser breakdown
        parsers = {}
        manifest_path = os.path.join(out_dir, "manifest.json")
        if os.path.exists(manifest_path):
            with open(manifest_path) as f:
                manifest = json.load(f)
            from collections import Counter
            parsers = dict(Counter(
                t.get("source_parser", "unknown")
                for t in manifest.get("textures", [])
            ))

        result = {
            "game": rom.name,
            "textures": png_count,
            "parsers": parsers,
            "time": round(elapsed, 1),
            "exit_code": proc.returncode,
        }
        results.append(result)

        status = "PASS" if png_count > 0 else "ZERO"
        print(f"  {status}: {png_count} textures in {elapsed:.1f}s")
        if parsers:
            print(f"  Parsers: {parsers}")

    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT after 600s")
        results.append({"game": rom.name, "textures": 0, "error": "timeout"})
    except Exception as e:
        print(f"  ERROR: {e}")
        results.append({"game": rom.name, "textures": 0, "error": str(e)})

# Save results
with open(os.path.join(OUT_BASE, "results.json"), "w") as f:
    json.dump(results, f, indent=2)

# Print summary table
print(f"\n\n{'='*80}")
print("BULK TEST RESULTS")
print(f"{'='*80}")
print(f"{'Game':<45} {'Tex':>6} {'Time':>6}  Parsers")
print(f"{'-'*45} {'-'*6} {'-'*6}  {'-'*25}")
for r in sorted(results, key=lambda x: -x.get("textures", 0)):
    if "error" in r:
        print(f"{r['game'][:45]:<45} {'ERR':>6} {r['error']}")
    else:
        pstr = ", ".join(f"{k}:{v}" for k, v in sorted(
            r["parsers"].items(), key=lambda x: -x[1]
        )[:3]) if r["parsers"] else "none"
        print(f"{r['game'][:45]:<45} {r['textures']:>6} {r['time']:>5}s  {pstr}")

working = [r for r in results if r.get("textures", 0) > 50]
partial = [r for r in results if 0 < r.get("textures", 0) <= 50]
zero = [r for r in results if r.get("textures", 0) == 0]

print(f"\nWorking ({len(working)}): {', '.join(r['game'][:30] for r in working)}")
if partial:
    print(f"Partial ({len(partial)}): {', '.join(r['game'][:30] for r in partial)}")
if zero:
    print(f"Zero ({len(zero)}): {', '.join(r['game'][:30] for r in zero)}")

total_new = sum(r.get("textures", 0) for r in results)
print(f"\nTotal new textures: {total_new:,}")
print(f"Previously: 44,736 across 15 games")
print(f"New total: {44736 + total_new:,} across {15 + len(working) + len(partial)} games")
