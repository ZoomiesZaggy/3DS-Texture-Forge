"""Regression tests for 3DS Texture Forge extraction pipeline.

Run with: pytest tests/regression.py -v --rom-dir "D:\\3ds"
Requires ROM files at the specified path.

Options:
  --rom-dir PATH       Directory containing ROM files (default: D:\\3ds)
  --update-baselines   Write current counts to tests/baselines.json
"""

import os
import sys
import json
import time
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASELINES_PATH = os.path.join(os.path.dirname(__file__), "baselines.json")

# Default ROM directories to search
DEFAULT_ROM_DIRS = [
    r"D:\3ds",
    r"D:\3ds Rom set\No-Intro\Nintendo - Nintendo 3DS (Decrypted)",
]

# Game name pattern -> (minimum textures, minimum quality score)
# Pattern is a substring match against ROM filenames
REGRESSION_GAMES = [
    # Core regression (MUST NEVER DROP)
    ("Mario Kart 7", 2700, 0.70),
    ("Kirby - Triple Deluxe", 10000, 0.70),
    ("Kirby - Planet Robobot", 5000, 0.70),
    ("Resident Evil - Revelations", 1100, 0.70),
    ("Resident Evil - The Mercenaries 3D", 1700, 0.60),
    ("Pac-Man and the Ghostly Adventures", 500, 0.60),
    ("Fire Emblem - Awakening", 10000, 0.70),
    ("Persona Q", 700, 0.60),
    ("Dragon Quest VIII", 15000, 0.60),
    ("Bravely Default", 10000, 0.70),
    ("Legend of Zelda, The - A Link Between Worlds", 18000, 0.60),
    ("Legend of Zelda, The - Ocarina of Time 3D", 3000, 0.70),
    ("Legend of Zelda, The - Majora's Mask 3D", 1500, 0.70),
    ("Dead or Alive Dimensions", 4000, 0.60),
    ("Pokemon Y", 7000, 0.70),
    ("Picross 3D - Round 2", 10000, 0.70),
    ("Theatrhythm Final Fantasy", 3500, 0.60),
    ("Corpse Party", 2500, 0.60),
    ("Nano Assault", 500, 0.60),
    ("Dragon Quest VII", 10000, 0.60),

    # Expanded games (Phase 3)
    ("Pokemon Omega Ruby", 8000, 0.70),
    ("Animal Crossing - New Leaf", 3000, 0.60),
    ("Monster Hunter 4 Ultimate", 8000, 0.60),
    ("Super Smash Bros. for Nintendo 3DS", 5000, 0.60),
    ("Super Mario 3D Land", 2000, 0.60),
    ("Star Fox 64 3D", 200, 0.60),
    ("Fire Emblem Fates", 10000, 0.60),
    ("Fire Emblem Echoes", 10000, 0.60),
    ("Xenoblade Chronicles 3D", 10000, 0.60),

    # Phase 4 newly-working games
    ("Fantasy Life", 8000, 0.60),
    ("Hatsune Miku", 4000, 0.60),
    ("Metal Gear Solid - Snake Eater", 1400, 0.60),
    ("Castlevania", 1800, 0.60),
]


@pytest.fixture(scope="session")
def rom_dir(request):
    """Find the ROM directory."""
    explicit = request.config.getoption("--rom-dir")
    if explicit and os.path.isdir(explicit):
        return explicit
    for d in DEFAULT_ROM_DIRS:
        if os.path.isdir(d):
            return d
    pytest.skip("No ROM directory found. Use --rom-dir to specify.")


def _find_rom(rom_dir: str, pattern: str) -> str:
    """Find a ROM file matching the pattern substring."""
    for fname in os.listdir(rom_dir):
        if not fname.lower().endswith(".3ds"):
            continue
        if pattern.lower() in fname.lower():
            return os.path.join(rom_dir, fname)
    return ""


def _extract_count_and_quality(rom_path: str):
    """Extract textures from a ROM and return (count, quality_score)."""
    from main import parse_rom, should_process_file
    from parsers.romfs import RomFSParser
    from textures.scanner import extract_textures_with_confidence
    from textures.decoder import decode_texture_fast
    from quality import compute_quality_metrics

    romfs_data, title_id, product_code, chain = parse_rom(rom_path)
    romfs = RomFSParser(romfs_data)
    files = romfs.list_files()

    total = 0
    suspicious = 0
    for idx, (path, offset, size) in enumerate(files):
        if not should_process_file(path, scan_all=False):
            continue
        _, file_data = romfs.read_file_by_index(idx)
        if len(file_data) < 8:
            continue
        textures, _ = extract_textures_with_confidence(
            file_data, path, scan_all=False, title_id=title_id,
        )
        for tex in textures:
            total += 1
            # Quick quality check on a sample
            if total % 20 == 0:  # Sample every 20th texture
                fmt = tex.get("format", 0)
                w = tex.get("width", 0)
                h = tex.get("height", 0)
                pixel_data = tex.get("data", b"")
                if w > 0 and h > 0 and pixel_data:
                    rgba = decode_texture_fast(pixel_data, w, h, fmt)
                    if rgba is not None:
                        qm = compute_quality_metrics(rgba, pica_format=fmt)
                        if qm["is_suspicious"]:
                            suspicious += 1

    # Estimate quality from sampled textures
    sampled = total // 20
    if sampled > 0:
        quality_score = 1.0 - (suspicious / sampled)
    else:
        quality_score = 1.0 if total > 0 else 0.0

    return total, quality_score


@pytest.mark.parametrize(
    "game_pattern,min_textures,min_quality",
    REGRESSION_GAMES,
    ids=[g[0] for g in REGRESSION_GAMES],
)
def test_regression(rom_dir, game_pattern, min_textures, min_quality, request):
    rom_path = _find_rom(rom_dir, game_pattern)
    if not rom_path:
        pytest.skip(f"ROM not found for: {game_pattern}")

    t0 = time.time()
    count, quality = _extract_count_and_quality(rom_path)
    elapsed = time.time() - t0

    # Print result for visibility
    status = "PASS" if count >= min_textures else "FAIL"
    print(f"\n  {game_pattern}: {count:,} textures (>={min_textures:,}) "
          f"quality={quality:.2f} (>={min_quality}) [{elapsed:.1f}s] [{status}]")

    assert count >= min_textures, (
        f"{game_pattern}: got {count} textures, expected >= {min_textures}"
    )

    # Quality check (warning only, not hard failure for now)
    if quality < min_quality:
        print(f"  WARNING: quality {quality:.2f} < {min_quality}")


def test_update_baselines(rom_dir, request):
    """Write current counts to baselines.json (only runs with --update-baselines)."""
    if not request.config.getoption("--update-baselines"):
        pytest.skip("Use --update-baselines to run this test")

    baselines = {}
    for game_pattern, min_textures, min_quality in REGRESSION_GAMES:
        rom_path = _find_rom(rom_dir, game_pattern)
        if not rom_path:
            continue
        count, quality = _extract_count_and_quality(rom_path)
        baselines[game_pattern] = {
            "count": count,
            "quality": round(quality, 3),
            "rom": os.path.basename(rom_path),
            "threshold": min_textures,
        }
        print(f"  {game_pattern}: {count:,} (quality={quality:.2f})")

    with open(BASELINES_PATH, "w") as f:
        json.dump(baselines, f, indent=2)
    print(f"\nWrote baselines to {BASELINES_PATH}")
