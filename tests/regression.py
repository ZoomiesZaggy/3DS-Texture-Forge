"""Regression tests for 3DS Texture Forge extraction pipeline.

Run with: pytest tests/regression.py -v
Requires ROM files in the No-Intro collection at the path below.
"""

import os
import sys
import pytest
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROM_DIR = r"D:\3ds Rom set\No-Intro\Nintendo - Nintendo 3DS (Decrypted)"

REGRESSION_GAMES = [
    ("Mario Kart 7 (USA) (En,Fr,Es) (Rev 1).3ds", 2700),
    ("Kirby - Triple Deluxe (USA) (En,Fr,Es).3ds", 10000),
    ("Resident Evil - Revelations (USA) (En,Ja,Fr,De,Es,It) (Rev 1).3ds", 1100),
    ("Pac-Man and the Ghostly Adventures (USA) (En,Fr,Es).3ds", 500),
    ("Fire Emblem - Awakening (USA).3ds", 10000),
]


def _extract_count(rom_path: str) -> int:
    """Extract textures from a ROM and return the total count."""
    from main import parse_rom, should_process_file
    from parsers.romfs import RomFSParser
    from textures.scanner import extract_textures_with_confidence

    romfs_data, title_id, product_code, chain = parse_rom(rom_path)
    romfs = RomFSParser(romfs_data)
    files = romfs.list_files()

    total = 0
    for idx, (path, offset, size) in enumerate(files):
        if not should_process_file(path, scan_all=False):
            continue
        _, file_data = romfs.read_file_by_index(idx)
        if len(file_data) < 8:
            continue
        textures, _ = extract_textures_with_confidence(
            file_data, path, scan_all=False, title_id=title_id,
        )
        total += len(textures)
    return total


@pytest.mark.parametrize("rom_name,min_textures", REGRESSION_GAMES,
                         ids=[g[0].split("(")[0].strip() for g in REGRESSION_GAMES])
def test_regression(rom_name, min_textures):
    rom_path = os.path.join(ROM_DIR, rom_name)
    if not os.path.exists(rom_path):
        pytest.skip(f"ROM not found: {rom_path}")

    count = _extract_count(rom_path)
    assert count >= min_textures, (
        f"{rom_name}: got {count} textures, expected >= {min_textures}"
    )
