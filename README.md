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
4. **Click "Extract Textures"** — Wait 10-60 seconds
5. **Click "Open Output Folder"** — Your textures are there as .png files

## How to Use (CLI)

```
3ds-tex-extract extract "game.3ds" -o output_folder --verbose
3ds-tex-extract scan "game.3ds" --verbose
3ds-tex-extract extract "game.3ds" --scan-all
```

## Tested Games

| Game | Textures | Status |
|------|----------|--------|
| Picross 3D: Round 2 | 10,914 | :white_check_mark: |
| Pokemon Y | 8,015 | :white_check_mark: |
| Kirby: Planet Robobot | 5,250 | :white_check_mark: |
| Theatrhythm Final Fantasy | 4,076 | :white_check_mark: |
| Zelda: Ocarina of Time 3D | 3,584 | :white_check_mark: |
| Corpse Party | 2,781 | :white_check_mark: |
| Mario Kart 7 | 2,770 | :white_check_mark: |
| Resident Evil: Revelations | 1,137 | :white_check_mark: |
| Nano Assault | 638 | :white_check_mark: |
| Kid Icarus: Uprising | 199 | :white_check_mark: |
| RE: The Mercenaries 3D | 121 | :white_check_mark: |

Many other 3DS games should also work — the tool supports standard Nintendo texture formats (CGFX, BFLIM, BCLIM, BCH, CTPK, CTXB, CMB) plus Capcom TEX and Shin'en TEX CTR.

## Supported Formats

### ROM Containers
- NCSD (.3ds cartridge dumps)
- CIA (.cia installable titles)
- NCCH, RomFS (internal containers)

### Archive Formats
- SARC (.arc archives)
- GARC (Pokemon archives)
- ZAR (Zelda/Grezzo archives)
- Yaz0/SZS (compressed SARC)
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

## For Azahar/Citra Custom Textures

This tool extracts textures organized by source file. To use them as custom textures in Azahar (Citra fork):

1. Extract textures with this tool
2. In Azahar, enable "Dump Textures" and play the game briefly
3. Match the dumped hash-named textures to the extracted ones
4. Replace the dumped textures with your modified versions

## Requirements

- Windows 10/11 (64-bit)
- A decrypted 3DS ROM file (.3ds or .cia)
- ROMs must be decrypted — use GodMode9 to decrypt if needed

## Building from Source

```
pip install PySide6 Pillow numpy
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
