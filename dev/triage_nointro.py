import sys, os, subprocess, json, time, struct, collections
from pathlib import Path

ROM_DIR = r"D:\3ds Rom set\No-Intro\Nintendo - Nintendo 3DS (Decrypted)"
OUT_BASE = "out/nointro_triage"
os.makedirs(OUT_BASE, exist_ok=True)

GAMES = [
    "New Super Mario Bros. 2",
    "Paper Mario - Sticker Star",
    "Donkey Kong Country Returns 3D",
    "Captain Toad - Treasure Tracker",
    "Yoshi's New Island",
    "Poochy & Yoshi's Woolly World",
    "Hey! Pikmin",
    "Chibi-Robo! Zip Lash",
    "WarioWare Gold",
    "Metroid - Samus Returns",
    "Miitopia",
    "Tomodachi Life",
    "Detective Pikachu",
    "Code Name - S.T.E.A.M.",
    "Mario Golf - World Tour",
    "Mario Tennis Open",
    "Mario Party - Island Tour",
    "Nintendogs + Cats - French Bulldog",
    "Hyrule Warriors Legends",
    "Sushi Striker - The Way of Sushido",
    "Dragon Quest VIII",
    "Dragon Quest VII",
    "Final Fantasy Explorers",
    "Shin Megami Tensei IV",
    "Persona Q - Shadow of the Labyrinth",
    "Etrian Odyssey IV",
    "Radiant Historia - Perfect Chronology",
    "Bravely Second - End Layer",
    "Alliance Alive, The",
    "7th Dragon III Code",
    "Stella Glow",
    "Ace Combat - Assault Horizon Legacy",
    "Dead or Alive - Dimensions",
    "Fantasy Life",
    "Professor Layton and the Azran Legacy",
    "Professor Layton vs. Phoenix Wright",
    "Yo-Kai Watch",
    "Layton's Mystery Journey",
    "Sonic Generations",
    "Sonic Lost World",
    "Hatsune Miku - Project Mirai DX",
    "Rhythm Thief",
    "Pac-Man and the Ghostly Adventures",
    "One Piece - Unlimited World Red",
    "Dragon Ball Fusions",
    "Tales of the Abyss",
    "Batman - Arkham Origins Blackgate",
    "Castlevania - Lords of Shadow - Mirror of Fate",
    "LEGO City Undercover",
    "LEGO Star Wars - The Force Awakens",
    "Skylanders Swap Force",
    "Disney Epic Mickey",
    "Rayman Origins",
    "Cave Story 3D",
    "Shovel Knight",
    "Rune Factory 4",
    "Story of Seasons",
    "Senran Kagura 2 - Deep Crimson",
    "Ridge Racer 3D",
    "Metal Gear Solid - Snake Eater 3D",
    "Kingdom Hearts 3D",
]


def find_rom(name):
    rom_dir = Path(ROM_DIR)
    words = [w.lower() for w in name.replace("'", "").replace(".", "").split() if len(w) > 1]
    best = None
    best_score = 0
    best_has_rev = False
    for f in rom_dir.iterdir():
        if f.suffix.lower() != ".3ds":
            continue
        if "beta" in f.stem.lower():
            continue
        stem = f.stem.lower().replace("'", "").replace(".", "")
        score = sum(1 for w in words if w in stem)
        has_rev = "rev" in f.stem.lower()
        # Prefer higher rev
        if score > best_score or (score == best_score and has_rev and not best_has_rev):
            best_score = score
            best = f
            best_has_rev = has_rev
    if best_score >= min(3, len(words)):
        return best
    return None


found = []
missing = []
for name in GAMES:
    rom = find_rom(name)
    if rom:
        found.append((name, rom))
    else:
        missing.append(name)

print(f"Found: {len(found)}/{len(GAMES)} ROMs")
if missing:
    print(f"Missing ({len(missing)}): {', '.join(missing)}")
print()

results = []
for name, rom_path in found:
    safe = name[:35].replace(" ", "_").replace("'", "").replace("-", "").replace("!", "").replace(".", "").replace(",", "")
    out_dir = os.path.join(OUT_BASE, safe)
    manifest = os.path.join(out_dir, "manifest.json")
    summary_path = os.path.join(out_dir, "summary.json")

    if os.path.exists(summary_path):
        try:
            with open(summary_path) as f:
                s = json.load(f)
            tex_count = s.get("textures_decoded_ok", 0)
            parsers_info = s.get("parser_breakdown", {})
            print(f"CACHED {name[:45]}: {tex_count} textures")
            results.append({"game": name, "textures": tex_count, "parsers": parsers_info,
                             "cached": True, "rom": str(rom_path)})
            continue
        except Exception:
            pass

    os.makedirs(out_dir, exist_ok=True)
    print(f"\n{'='*60}")
    print(f"TESTING: {name}")
    print(f"ROM: {rom_path.name}")
    print(f"{'='*60}")

    t0 = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, "main.py", "extract", str(rom_path), "-o", out_dir],
            capture_output=True, text=True, timeout=300,
        )
        elapsed = time.time() - t0

        png_count = 0
        tex_dir = os.path.join(out_dir, "textures")
        if os.path.isdir(tex_dir):
            for root, dirs, files in os.walk(tex_dir):
                png_count += sum(1 for fn in files if fn.endswith(".png"))

        parsers_info = {}
        if os.path.exists(summary_path):
            try:
                with open(summary_path) as f:
                    s = json.load(f)
                parsers_info = s.get("parser_breakdown", {})
            except Exception:
                pass

        result = {
            "game": name,
            "textures": png_count,
            "parsers": parsers_info,
            "time": round(elapsed, 1),
            "exit_code": proc.returncode,
            "rom": str(rom_path),
        }
        results.append(result)
        status = "PASS" if png_count > 0 else "ZERO"
        print(f"  {status}: {png_count} textures in {elapsed:.1f}s")
        if parsers_info:
            top3 = sorted(parsers_info.items(), key=lambda x: -x[1])[:3]
            print(f"  Parsers: {', '.join(f'{k}:{v}' for k, v in top3)}")
        if proc.returncode != 0 and png_count == 0:
            print(f"  stderr: {proc.stderr[-300:]}")

    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        print(f"  TIMEOUT after {elapsed:.0f}s")
        results.append({"game": name, "textures": 0, "error": "timeout", "rom": str(rom_path)})
    except Exception as e:
        print(f"  ERROR: {e}")
        results.append({"game": name, "textures": 0, "error": str(e), "rom": str(rom_path)})

# Format recon for zero-texture games
print(f"\n\n{'='*60}")
print("FORMAT RECON ON ZERO-TEXTURE GAMES")
print(f"{'='*60}")

zero_games = [r for r in results if r.get("textures", 0) == 0 and "error" not in r]
for r in zero_games:
    rom_path_str = r["rom"]
    name = r["game"]
    print(f"\n--- {name} ---")
    try:
        with open(rom_path_str, "rb") as f:
            rom_bytes = f.read()
        sys.path.insert(0, ".")
        from parsers.ncsd import NCSDParser
        from parsers.ncch import NCCHParser
        from parsers.romfs import RomFSParser

        ncsd = NCSDParser(rom_bytes)
        ncch = NCCHParser(ncsd.get_partition(0))
        rd = ncch.get_romfs()
        romfs = RomFSParser(rd)
        files = romfs.list_files()

        ext_count = collections.Counter()
        magic_count = collections.Counter()
        for p, o, s in files:
            ext = p.rsplit(".", 1)[-1].lower() if "." in p else "no_ext"
            ext_count[ext] += 1
            if s >= 4:
                magic_count[rd[o:o+4]] += 1

        print(f"  Files: {len(files)}")
        print(f"  Top extensions: {', '.join(f'.{e}:{c}' for e, c in ext_count.most_common(6))}")
        top_magic = []
        for m, c in magic_count.most_common(5):
            try:
                label = m.decode("ascii")
            except Exception:
                label = m.hex()
            top_magic.append(f"{label}:{c}")
        print(f"  Top magic: {', '.join(top_magic)}")
        r["romfs_files"] = len(files)
        r["top_extensions"] = dict(ext_count.most_common(6))
        r["top_magic"] = {m.hex(): c for m, c in magic_count.most_common(5)}
    except Exception as e:
        print(f"  Recon failed: {e}")

with open(os.path.join(OUT_BASE, "triage_results.json"), "w") as f:
    json.dump(results, f, indent=2)

# Summary table
print(f"\n\n{'='*80}")
print("NO-INTRO TRIAGE RESULTS")
print(f"{'='*80}")
results.sort(key=lambda x: -x.get("textures", 0))
print(f"\n{'Game':<43} {'Tex':>8} {'Time':>6}  Notes")
print("-" * 85)

for r in results:
    name = r["game"][:43]
    tex = r.get("textures", 0)
    if "error" in r:
        print(f"{name:<43} {'ERR':>8}         {r['error']}")
    elif tex == 0:
        exts = r.get("top_extensions", {})
        ext_str = ", ".join(f".{e}" for e in list(exts.keys())[:3])
        print(f"{name:<43} {0:>8}         formats: {ext_str}")
    else:
        time_str = f"{r.get('time', 0):.0f}s"
        parsers = r.get("parsers", {})
        pstr = ", ".join(f"{k}:{v}" for k, v in sorted(parsers.items(), key=lambda x: -x[1])[:2]) if parsers else ""
        print(f"{name:<43} {tex:>8,} {time_str:>6}  {pstr}")

working = [r for r in results if r.get("textures", 0) > 50]
partial = [r for r in results if 0 < r.get("textures", 0) <= 50]
zero = [r for r in results if r.get("textures", 0) == 0 and "error" not in r]
errors = [r for r in results if "error" in r]
total_new = sum(r.get("textures", 0) for r in results)

print(f"\n{'='*40}")
print("SUMMARY")
print(f"{'='*40}")
print(f"ROMs found:        {len(found)}/{len(GAMES)}")
print(f"Working (>50 tex): {len(working)}")
print(f"Partial (1-50):    {len(partial)}")
print(f"Zero textures:     {len(zero)}")
print(f"Errors/timeouts:   {len(errors)}")
print(f"New textures:      {total_new:,}")
compat = len(found)
rate = 100 * (len(working) + len(partial)) / max(compat, 1)
print(f"Compatibility:     {len(working)+len(partial)}/{compat} = {rate:.0f}%")

if zero:
    print(f"\nZERO-TEXTURE FORMAT GROUPS:")
    format_groups = collections.defaultdict(list)
    for r in zero:
        exts = r.get("top_extensions", {})
        magic = r.get("top_magic", {})
        key_fmt = "unknown"
        for ext in list(exts.keys())[:3]:
            if ext in ("data", "dict"):
                key_fmt = "NLG .data/.dict"
                break
            elif ext == "arc":
                key_fmt = "proprietary .arc"
                break
            elif ext == "bin":
                fm = list(magic.keys())[0] if magic else "?"
                key_fmt = f".bin (magic={fm})"
                break
            elif ext in ("cmp", "lz", "lzs"):
                key_fmt = "compressed (.cmp/.lz)"
                break
            elif ext == "bntx":
                key_fmt = "Switch BNTX"
                break
            elif ext in ("dat", "no_ext"):
                fm = list(magic.keys())[0] if magic else "?"
                key_fmt = f".dat/raw (magic={fm})"
                break
        format_groups[key_fmt].append(r["game"])
    for fmt, games in sorted(format_groups.items(), key=lambda x: -len(x[1])):
        print(f"  [{len(games)}] {fmt}: {', '.join(games[:4])}{'...' if len(games) > 4 else ''}")

print(f"\nFull results: {OUT_BASE}/triage_results.json")
