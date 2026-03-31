# 3DS Texture Forge

Extract textures from Nintendo 3DS game ROMs (.3ds, .cia) and save them as PNG files. Supports 35+ games with over 1 million textures across all supported titles. Includes quality reports, contact sheets, deduplication, and Azahar/Citra custom texture pack output.

## Download

Download the latest release from the [Releases page](https://github.com/ZoomiesZaggy/3DS-Texture-Forge/releases).

**Windows:**
- **3DS Texture Forge.exe** -- GUI app (recommended)
- **3ds-tex-extract.exe** -- Command-line tool

**Linux x86_64:**
- **3DS-Texture-Forge-linux** -- GUI app
- **3ds-tex-extract-linux** -- Command-line tool (make executable with `chmod +x`)

No installation needed. Just download and run.

## How to Use (GUI)

1. **Get a decrypted 3DS ROM** -- Use GodMode9 to dump and decrypt your game
2. **Open 3DS Texture Forge** -- Double-click the .exe
3. **Drop your ROM file** onto the window (or click Browse)
4. **Click "Extract Textures"** -- Wait 10-600 seconds depending on game size
5. **Click "Open Output Folder"** -- Your textures are there as .png files

## How to Use (CLI)

```
# Basic extraction
python main.py extract "game.3ds" -o output_folder

# With deduplication (saves disk space)
python main.py extract "game.3ds" -o output_folder --dedup

# Generate machine-readable report
python main.py extract "game.3ds" -o output_folder --report

# Scan ROM contents without extracting
python main.py scan "game.3ds" --verbose

# Deep scan (process all files, not just known extensions)
python main.py extract "game.3ds" --scan-all
```

## Azahar/Citra Output Mode

Output textures directly in Azahar/Citra custom texture pack format:

```
python main.py extract "game.3ds" -o textures/ --output-mode azahar
```

This creates files named `tex1_<W>x<H>_<xxhash>_<fmt>.png` in a `<TitleID>/` subdirectory, matching Azahar's expected layout.

For manual texture pack building:

```
python main.py extract "game.3ds" -o project/
python main.py import-dump ~/azahar/dump/textures/TITLEID project/
python main.py build-pack project/
```

## Supported Games

| Game | Textures | Quality | Key Formats |
|------|----------|---------|-------------|
| Pokemon Y | 127,074 | 98.8% | GARC, BCH, ETC1 |
| Kirby: Triple Deluxe | 54,377 | 98.4% | CGFX, ETC1A4 |
| Pokemon Omega Ruby | 36,496 | 95.6% | GARC, BCH, ETC1 |
| Animal Crossing: New Leaf | 21,517 | 93.7% | SARC, BCH |
| Kirby: Planet Robobot | 16,591 | 96.9% | CGFX, ETC1A4 |
| Bravely Default | 11,908 | 96.3% | BCH, ETC1 |
| Fire Emblem: Awakening | 10,295 | 89.9% | FE ARC, BCH |
| Theatrhythm Final Fantasy | 6,966 | 91.1% | BCH, ETC1A4 |
| Zelda: Ocarina of Time 3D | 3,584 | -- | ZAR, CMB, CTXB |
| Mario Kart 7 | 2,770 | 96.0% | CGFX, ETC1 |
| Corpse Party | 2,659 | 81.3% | BCH, ETC1A4 |
| Resident Evil: Revelations | 1,137 | -- | Capcom ARC, TEX |
| Nano Assault | 638 | 91.5% | Shin'en TEX |
| RE: The Mercenaries 3D | 2,151 | -- | Capcom ARC, TEX |
| Fantasy Life | 10,254 | -- | Level-5 flat, CGFX |
| Hatsune Miku: Project Mirai DX | 4,982 | -- | BCH, CGFX |
| Metal Gear Solid: Snake Eater 3D | 1,744 | -- | BCH, CGFX |
| Castlevania: Mirror of Fate | 2,363 | -- | BCH, bctex |
| Kid Icarus: Uprising | 58,210 | -- | darc, BCH |
| Monster Hunter 4 Ultimate | 25,685 | -- | Capcom ARC, TEX |
| Picross 3D: Round 2 | 12,631 | -- | BCH, ETC1 |
| Super Mario 3D Land | 6,097 | -- | NARC, CGFX |
| Pokemon Sun/Moon | 10,000+ | -- | GARC, BCH |
| Zelda: Majora's Mask 3D | 1,780 | -- | GAR, CMB, CTXB |
| Zelda: A Link Between Worlds | 18,000+ | -- | SARC, BCH |
| Dragon Quest VII | 10,000+ | -- | BCH, CTPK |
| Dragon Quest VIII | 15,000+ | -- | BCH, CTPK |
| Dead or Alive Dimensions | 4,000+ | -- | BCH |
| Persona Q | 700+ | -- | CPK, BCH |
| Super Smash Bros. 3DS | 5,000+ | -- | dt/ls, BCH |
| Star Fox 64 3D | 500+ | -- | GDB1, BCH |
| Fire Emblem Fates | 10,000+ | -- | FE ARC, BCH |
| Fire Emblem Echoes | 10,000+ | -- | FE ARC, BCH |

Many other 3DS games should also work.

## Quality Reports

Every extraction generates `quality_report.json` and `quality_report.txt` with:
- Total/valid/suspicious texture counts
- Quality score (valid / total ratio)
- Breakdown by suspicion type (solid color, low variance, extreme brightness, bad dimensions)
- Normal map detection (HILO8 format)
- Format distribution

## Supported Formats

### ROM Containers
- NCSD (.3ds cartridge dumps)
- CIA (.cia installable titles)
- NCCH, RomFS (internal containers)

### Archive Formats
- SARC / GARC / NARC (Nintendo archives)
- ZAR / GAR (Grezzo Archives - Zelda)
- darc (Nintendo Data ARChive)
- Capcom MT Framework ARC
- Fire Emblem ARC
- CRI CPK (Persona Q, 7th Dragon)
- Level-5 ARC0 (Layton, Yo-Kai Watch)
- Level-5 flat archive (Fantasy Life)
- Smash Bros dt/ls archives

### Texture Formats
- All 14 PICA200 GPU formats (RGBA8, RGB8, RGB565, RGBA4, ETC1, ETC1A4, etc.)
- BCH (Binary CTR H3D textures)
- CGFX (NintendoWare graphics)
- BFLIM / BCLIM (UI textures)
- CTPK (CTR Texture Package)
- CTXB / CMB (Grezzo containers)
- Capcom MT Framework TEX
- Shin'en TEX CTR
- jIMG (Bandai Namco)
- GDB1 (texture database)

### Compression
- Nintendo LZ10/LZ11/LZ13
- BLZ (backward LZSS)
- Yaz0/SZS
- CRILAYLA (CRI streaming)
- zlib/DEFLATE

## Known Limitations

- ROMs must be decrypted. Use GodMode9 to decrypt if needed
- Some proprietary formats (MercurySteam, Retro Studios, TT Games LEGO) are not supported
- Texture quality depends on correct format identification from game headers

## Requirements

- A decrypted 3DS ROM file (.3ds or .cia)
- **Windows**: Download .exe from Releases (no setup needed)
- **Linux/Mac**: Python 3.10+ (see below)

## Running on Linux / Mac ARM

### Running from Source (Linux, Mac ARM M1/M2/M3/M4)

Requirements: Python 3.10+, pip

```bash
# Linux GUI prerequisite
sudo apt-get install python3-tk    # Debian/Ubuntu (only needed for GUI)
sudo pacman -S tk                  # Arch

# Clone and install
git clone https://github.com/ZoomiesZaggy/3DS-Texture-Forge.git
cd 3DS-Texture-Forge
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run
python main.py --help      # CLI
python gui_entry.py        # GUI
```

### Platform Support Matrix

| Platform           | GUI | CLI | Pre-built binary                   |
|--------------------|-----|-----|------------------------------------|
| Windows x64        | Yes | Yes | Yes -- download .exe               |
| Linux x86_64       | Yes | Yes | Yes -- download binary             |
| Mac ARM (M-series) | Yes | Yes | Run `scripts/build_mac.sh`         |
| Intel Mac          | Not supported                               |

## Building from Source (Windows)

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
