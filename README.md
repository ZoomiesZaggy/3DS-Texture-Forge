# 3DS Texture Forge: v1.1

**by ZoomiesZaggy · March 2026**

---

> **A note on how this was built:** This tool was developed entirely with Claude (Anthropic's AI assistant). Weeks of diligent prompting, oversight, and iteration. Not a weekend vibe-coding session. I want to be upfront about that because the community has complicated feelings about AI, and those feelings are valid. My position: AI writing code is a tool, the same way a compiler is a tool. AI generating art is a different conversation, one I personally land on the opposite side of. Which is exactly why this tool exists. It extracts raw source textures from 3DS ROMs so that artists, modders, and preservationists can do the painstaking, skilled, human work of redrawing, remastering, and reimagining them properly. **The extraction is automated. The artistry is yours.**

---

## Why this exists

The AYN Thor changed things. A handheld powerful enough to run Azahar at full speed, in a clamshell form factor (two screens, the way Nintendo intended) finally made 3DS games feel like a platform worth investing in again rather than a museum piece. And Azahar's custom texture support means you can actually do something with that hardware: replace the original 240p assets with hand-crafted high-resolution replacements and experience games like Ocarina of Time 3D, Fire Emblem Awakening, or Pokémon X the way they were always trying to look, constrained only by a 2011 GPU.

The problem is that getting those original textures out of a ROM was either impossible, broken, or required stitching together three different tools none of which agreed on format. 3DS Texture Forge exists to fix that. Drop in a decrypted ROM, get a folder of PNGs. That's it.

---

## Download

Download the latest release from the [Releases page](https://github.com/ZoomiesZaggy/3DS-Texture-Forge/releases).

**Windows:**
- **3DS Texture Forge.exe** -- GUI app (recommended)
- **3ds-tex-extract.exe** -- Command-line tool

**Linux x86_64:**
- **3DS-Texture-Forge-linux** -- GUI app
- **3ds-tex-extract-linux** -- Command-line tool (make executable with `chmod +x`)

No installation needed. Just download and run.

---

## How to Use (GUI)

1. **Get a decrypted 3DS ROM** -- Use GodMode9 to dump and decrypt your game
2. **Open 3DS Texture Forge** -- Double-click the .exe
3. **Drop your ROM file** onto the window (or click Browse)
4. **Click "Extract Textures"** -- Wait 10-600 seconds depending on game size
5. **Click "Open Output Folder"** -- Your textures are there as .png files

---

## How to Use (CLI)

```bash
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

---

## Azahar/Citra Output Mode

Output textures directly in Azahar/Citra custom texture pack format:

```bash
python main.py extract "game.3ds" -o textures/ --output-mode azahar
```

This creates files named `tex1_<W>x<H>_<xxhash>_<fmt>.png` in a `<TitleID>/` subdirectory, matching Azahar's expected layout.

For manual texture pack building:

```bash
python main.py extract "game.3ds" -o project/
python main.py import-dump ~/azahar/dump/textures/TITLEID project/
python main.py build-pack project/
```

---

## Supported Games

| Game | Textures | Quality | Key Formats |
|------|----------|---------|-------------|
| Pokemon Mystery Dungeon: Gates to Infinity | 164,322 | 99% | GARC, BCH |
| Pokemon X / Y | 127,074 | 98% | GARC, BCH, ETC1 |
| Pokemon Ultra Sun / Ultra Moon | 23,674 | 97% | GARC, PC v5 |
| Kid Icarus: Uprising | 58,210 | 98% | darc, BCH |
| Kirby: Triple Deluxe | 54,377 | 98% | CGFX, ETC1A4 |
| Pokemon Omega Ruby / Alpha Sapphire | 36,496 | 96% | GARC, BCH, ETC1 |
| Monster Hunter 4 Ultimate | 25,685 | 99% | Capcom ARC, TEX |
| Animal Crossing: New Leaf | 21,517 | 94% | SARC, BCH |
| Tomodachi Life | 16,651 | 97% | BCH, CGFX |
| Kirby: Planet Robobot | 16,591 | 97% | CGFX, ETC1A4 |
| Professor Layton vs. Phoenix Wright | 5,417 | 90% | ARC0, IMGC |
| Layton's Mystery Journey | 5,565 | 90% | ARC0, IMGC |
| Professor Layton: Azran Legacy | 2,882 | 90% | ARC0, IMGC |
| Professor Layton: Miracle Mask | 2,183 | 90% | XFSA, IMGC |
| Fantasy Life | 10,254 | -- | Level-5 flat, CGFX |
| Yoshi's Woolly World | 4,676 | -- | GFAC, BCH |
| Kirby's Extra Epic Yarn | 3,359 | -- | GFAC, BCH |
| Conception II | 3,074 | -- | gzip-CTPK |
| Zero Time Dilemma | 2,490 | -- | gzip-CTPK |
| Fire Emblem: Awakening | 10,295 | 87% | FE ARC, BCH |
| Fire Emblem Fates | 10,000+ | -- | FE ARC, BCH |
| Fire Emblem Echoes | 10,000+ | -- | FE ARC, BCH |
| Bravely Default | 11,908 | 96% | BCH, ETC1 |
| Dragon Quest VII | 10,000+ | -- | BCH, CTPK |
| Dragon Quest VIII | 15,000+ | -- | BCH, CTPK |
| Picross 3D: Round 2 | 12,631 | -- | BCH, ETC1 |
| Hatsune Miku: Project Mirai DX | 4,982 | -- | BCH, CGFX |
| Theatrhythm Final Fantasy | 6,966 | 91% | BCH, ETC1A4 |
| Super Mario 3D Land | 6,097 | -- | NARC, CGFX |
| Zelda: A Link Between Worlds | 18,000+ | -- | SARC, BCH |
| Zelda: Ocarina of Time 3D | 3,584 | 94% | ZAR, CMB, CTXB |
| Zelda: Majora's Mask 3D | 1,780 | -- | GAR, CMB, CTXB |
| Metal Gear Solid: Snake Eater 3D | 1,744 | -- | BCH, CGFX |
| Castlevania: Mirror of Fate | 2,363 | -- | BCH, bctex |
| RE: Revelations | 5,742 | -- | Capcom ARC, TEX |
| RE: The Mercenaries 3D | 2,151 | -- | Capcom ARC, TEX |
| Persona Q | 700+ | -- | CPK, BCH |
| Super Smash Bros. 3DS | 5,000+ | -- | dt/ls, BCH |
| Star Fox 64 3D | 500+ | -- | GDB1, BCH |
| Dead or Alive Dimensions | 4,000+ | -- | BCH |
| Nano Assault | 638 | 92% | Shin'en TEX |
| Corpse Party | 2,659 | 81% | BCH, ETC1A4 |
| Mario Kart 7 | 2,770 | 96% | CGFX, ETC1 |

200+ games supported in total. Many titles not listed above will also work.

---

## Quality Reports

Every extraction generates `quality_report.json` and `quality_report.txt` with:

- Total/valid/suspicious texture counts
- Quality score (valid / total ratio)
- Breakdown by suspicion type (solid color, low variance, extreme brightness, bad dimensions)
- Normal map detection (HILO8 format)
- Format distribution

---

## Supported Formats

### ROM Containers
- NCSD (.3ds cartridge dumps)
- CIA (.cia installable titles)
- NCCH, RomFS (internal containers)

### Archive Formats
- SARC / GARC / NARC (Nintendo archives)
- ZAR / GAR (Grezzo archives - Zelda)
- darc (Nintendo Data ARChive)
- Capcom MT Framework ARC
- Fire Emblem ARC
- CRI CPK (Persona Q, 7th Dragon)
- Level-5 ARC0 (Layton, Yo-Kai Watch)
- Level-5 XFSA (Professor Layton)
- Level-5 flat archive (Fantasy Life)
- GFAC (Good-Feel archive - Kirby, Yoshi)
- Spike Chunsoft gzip-CTPK container
- Smash Bros dt/ls archives
- Pokemon PC v5/v11 section format

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
- IMGC (Level-5)
- STEX

### Compression
- Nintendo LZ10/LZ11/LZ13
- BLZ (backward LZSS)
- Yaz0/SZS
- CRILAYLA (CRI streaming)
- GFCP (Good-Feel compression)
- zlib/DEFLATE
- gzip

---

## Known Limitations

- ROMs must be decrypted. Use GodMode9 to decrypt if needed
- All 15 LEGO 3DS games: TT Games FUSE format requires executable disassembly, confirmed out of scope
- Ubisoft titles (Ghost Recon etc.): MAGM engine, confirmed dead end
- Yo-Kai Watch quality is ~80% due to a Huffman decoder edge case in Level-5 IMGC
- Luigi's Mansion: Dark Moon: accessible with `--scan-all` but not default pipeline
- Mega Man Legacy Collection: 3DST format uses proprietary compression

---

## Requirements

- A decrypted 3DS ROM file (.3ds or .cia)
- **Windows**: Download .exe from Releases (no setup needed)
- **Linux/Mac**: Python 3.10+ (see below)

---

## Running on Linux / Mac ARM

### Running from source (Linux, Mac ARM M1/M2/M3/M4)

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

### Platform support matrix

| Platform | GUI | CLI | Pre-built binary |
|---|---|---|---|
| Windows x64 | Yes | Yes | Yes -- download .exe |
| Linux x86_64 | Yes | Yes | Yes -- download binary |
| Mac ARM (M-series) | Yes | Yes | Run `scripts/build_mac.sh` |
| Intel Mac | Not supported | | |

---

## Building from Source (Windows)

```
pip install PySide6 Pillow numpy xxhash
python gui_entry.py                             # Run GUI
python main.py extract game.3ds -o output/     # Run CLI
```

To build .exe files:

```
pip install pyinstaller
build.bat
```

---

## Bug reports

Found a bug? [Open an issue](https://github.com/ZoomiesZaggy/3DS-Texture-Forge/issues/new) and include your ROM filename, extracted texture count, and a screenshot of what looks wrong.

---

## License

MIT
