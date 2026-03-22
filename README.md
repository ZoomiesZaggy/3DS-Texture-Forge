# 3DS Texture Forge

Extract textures from Nintendo 3DS game ROMs (.3ds, .cia) and save them as PNG files.

## Download

Download the latest release from the [Releases page](https://github.com/ZoomiesZaggy/3DS-Texture-Forge/releases).

- **3DS Texture Forge.exe** — GUI app (recommended)
- **3ds-tex-extract.exe** — Command-line tool

No installation needed. Just download and run.

## How to Use (GUI)

1. **Get a decrypted 3DS ROM** — Use GodMode9 to dump and decrypt your game
2. **Open 3DS Texture Forge** — Double-click the .exe
3. **Drop your ROM file** onto the window (or click Browse)
4. **Click "Extract Textures"** — Wait 10–600 seconds depending on game size
5. **Click "Open Output Folder"** — Your textures are there as .png files

## How to Use (CLI)

```
3ds-tex-extract extract "game.3ds" -o output_folder --verbose
3ds-tex-extract extract "game.3ds" -o output_folder --dedup
3ds-tex-extract scan "game.3ds" --verbose
3ds-tex-extract extract "game.3ds" --scan-all
```

## Tested Games

| Game | Textures | Unique | Status |
|------|----------|--------|--------|
| Pokemon Y | 126,690 | 39,025 | ✅ |
| Kid Icarus: Uprising | 58,210 | — | ✅ |
| Kirby: Triple Deluxe | 51,059 | 16,498 | ✅ |
| Pokemon Omega Ruby | 36,433 | 14,467 | ✅ |
| Monster Hunter 4 Ultimate | 25,685 | — | ✅ |
| Animal Crossing: New Leaf | 19,206 | 14,762 | ✅ |
| Picross 3D: Round 2 | 12,631 | 1,265 | ✅ |
| Cooking Mama: Sweet Shop | 12,050 | — | ✅ |
| Kirby: Planet Robobot | 10,623 | 5,437 | ✅ |
| Bravely Default | 8,626 | 1,566 | ✅ |
| Super Mario 3D Land | 6,097 | 1,780 | ✅ |
| Theatrhythm Final Fantasy | 4,076 | 3,621 | ✅ |
| Zelda: Ocarina of Time 3D | 3,584 | 2,834 | ✅ |
| Mario Kart 7 | 2,770 | 2,222 | ✅ |
| Mario & Luigi: Dream Team | 2,849 | 1,661 | ✅ |
| Corpse Party | 2,788 | 1,981 | ✅ |
| Zelda: Majora's Mask 3D | 1,780 | — | ✅ |
| Resident Evil: Revelations | 1,137 | 1,047 | ✅ |
| Fire Emblem: Awakening | 868 | — | ✅ |
| Nano Assault | 638 | 611 | ✅ |
| RE: The Mercenaries 3D | 121 | 105 | ✅ |
| Puzzle & Dragons Z | 4 | 3 | ✅ |

Many other 3DS games should also work.

## What's New in v1.1-beta

### New Game Support
- **Kid Icarus: Uprising** — 58,210 textures (darc archive parser)
- **Monster Hunter 4 Ultimate** — 25,685 textures (Capcom ARC parser + TEX profiles)
- **Cooking Mama: Sweet Shop** — 12,050 textures (LZ-compressed BCH support)
- **Super Mario 3D Land** — 6,097 textures (NARC archive parser)
- **Zelda: Majora's Mask 3D** — 1,780 textures (GAR archive parser + CMB bugfix)
- **Fire Emblem: Awakening** — 868 textures (FE ARC parser)
- **Bravely Default** — 8,626 textures
- **Animal Crossing: New Leaf** — 19,206 textures
- **Kirby: Triple Deluxe** — 51,059 textures
- **Pokemon Omega Ruby** — 36,433 textures

### Parser Improvements
- BCH struct parser with proper header/GPU command parsing (replaces heuristic)
- LZ-compressed files inside GARC archives now processed
- GARC streaming for large (1 GB+) archives
- CMB section count bugfix for Zelda games
- MH4U Capcom TEX format profiles

### New Archive Formats
- NARC (Nintendo ARChive) — used by Super Mario 3D Land, Kirby
- GAR (Grezzo Archive v2) — used by Zelda: Majora's Mask 3D
- darc (Data ARChive) — used by Kid Icarus: Uprising
- Capcom ARC — used by Monster Hunter series
- FE ARC — used by Fire Emblem: Awakening

### New Features
- Texture deduplication reporting (unique count in every extraction summary)
- `--dedup` flag to skip writing duplicate textures (saves disk space)
- `raw_data_hash_xxh64` in manifest for Azahar/Citra texture pack scripting

## For Azahar/Citra Custom Textures

This tool extracts textures organized by source file. To use them as custom textures in Azahar (Citra fork):

1. Extract textures with this tool
2. In Azahar, enable "Dump Textures" and play the game briefly
3. Use `import-dump` to match runtime hashes to extracted textures
4. Run `build-pack` to produce a ready-to-use texture pack folder
5. Enable "Load Custom Textures" in Azahar

```
3ds-tex-extract import-dump ~/azahar/dump/textures/TITLEID output_folder/
3ds-tex-extract build-pack output_folder/
```

The `raw_data_hash_xxh64` field in `manifest.json` can also be used to write custom matching scripts.

## Supported Formats

### ROM Containers
- NCSD (.3ds cartridge dumps)
- CIA (.cia installable titles)
- NCCH, RomFS (internal containers)

### Archive Formats
- SARC / GARC (Nintendo archives)
- NARC (Nintendo ARChive)
- GAR (Grezzo Archive v2)
- darc (Nintendo Data ARChive)
- Capcom MT Framework ARC
- Fire Emblem ARC
- ZAR / SZS / Yaz0
- Nintendo LZ10/LZ11/LZ13 compression

### Texture Formats
- All 14 PICA200 GPU formats (RGBA8, RGB8, RGB565, ETC1, ETC1A4, etc.)
- CGFX (Nintendo standard 3D textures)
- BFLIM / BCLIM (UI textures)
- BCH (Binary CTR textures)
- CTPK (CTR Texture Package)
- CTXB / CMB (Grezzo textures)
- Capcom MT Framework TEX
- Shin'en TEX CTR

## Requirements

- Windows 10/11 (64-bit)
- A decrypted 3DS ROM file (.3ds or .cia)
- ROMs must be decrypted — use GodMode9 to decrypt if needed

## Building from Source

```
pip install PySide6 Pillow numpy xxhash
python gui_entry.py          # Run GUI
python main.py extract game.3ds -o output/  # Run CLI
```

To build .exe files:

```
pip install pyinstaller
build.bat
```

## Credits

Built with Claude (Anthropic) assistance.

## License

MIT
