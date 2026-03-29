# 3DS Texture Forge: v1.0-beta Release
**by ZoomiesZaggy · March 2026**

---

> **A note on how this was built:** This tool was developed entirely with Claude (Anthropic's AI assistant). Weeks of diligent prompting, oversight, and iteration. Not a weekend vibe-coding session. I want to be upfront about that because the community has complicated feelings about AI, and those feelings are valid. My position: AI writing code is a tool, the same way a compiler is a tool. AI generating art is a different conversation, one I personally land on the opposite side of. Which is exactly why this tool exists. It extracts raw source textures from 3DS ROMs so that artists, modders, and preservationists can do the painstaking, skilled, human work of redrawing, remastering, and reimagining them properly. **The extraction is automated. The artistry is yours.**

---

## Why this exists

The AYN Thor changed things. A handheld powerful enough to run Azahar at full speed, in a clamshell form factor (two screens, the way Nintendo intended) finally made 3DS games feel like a platform worth investing in again rather than a museum piece. And Azahar's custom texture support means you can actually do something with that hardware: replace the original 240p assets with hand-crafted high-resolution replacements and experience games like Ocarina of Time 3D, Fire Emblem Awakening, or Pokémon X the way they were always trying to look, constrained only by a 2011 GPU.

The problem is that getting those original textures out of a ROM was either impossible, broken, or required stitching together three different tools none of which agreed on format. 3DS Texture Forge exists to fix that. Drop in a decrypted ROM, get a folder of PNGs. That's it.

---

## What v1.0-beta can do

| Metric | Value |
|--------|-------|
| Games supported | 180+ |
| Textures extracted (full library run) | 1,527,047 |
| Average quality score | ~97% |
| Parsers implemented | 25+ |

The tool ships as a standalone Windows executable with no Python, no dependencies, and no command line required unless you want it. Drop a ROM onto the GUI or run the CLI with a path. It scans the ROM's filesystem, identifies every texture container it knows about, decodes the pixels, and saves everything as PNGs organized by source file.

### Archive formats handled

BCH, CGFX, CTPK, SARC, GARC, NARC, ZAR, GAR, darc, Capcom ARC/TEX, Fire Emblem ARC, CRI CPK (CRILAYLA streaming), Level-5 ARC0, Smash Bros dt/ls, BFLIM, BCLIM, CMB, CTXB, Shin'en TEX CTR, jIMG, STEX, IMGC, and more. Every major Nintendo first-party format is covered. Several third-party formats too.

### Compression layers

Nintendo LZ10/LZ11/LZ13, BLZ, CRILAYLA, zlib/DEFLATE, Shin'en CMPR, all handled transparently. If a texture is compressed inside an archive inside a compressed archive, the tool recurses through all of it automatically.

### Pixel formats

All 14 PICA200 GPU formats (RGBA8, RGB8, RGB565, ETC1, ETC1A4, and the rest), plus format aliases used by Capcom and Atlus tools. Normal maps (HILO8) are detected and labeled separately so they don't pollute your texture count.

### Output modes

Standard mode organizes textures by source file. Azahar mode outputs textures with the exact filename format Azahar's custom texture replacement system expects: `tex1_WxH_hash_fmt.png` in a folder named after the game's title ID, so you can drop the output directly into your Azahar load directory.

### Quality reports

After every extraction, the tool generates a quality report (JSON and plain text) that breaks down how many textures decoded cleanly versus how many look suspicious: solid color, low variance, extreme brightness, bad dimensions. A visual contact sheet gives you a thumbnail grid of everything extracted, with red borders on flagged textures so you can see at a glance where the problem areas are.

---

## Numbers from the first full library run

| Game | Textures | Quality |
|------|----------|---------|
| Pokémon Mystery Dungeon: Gates to Infinity | 164,322 | 99% |
| Pokémon X / Y | 127,074 each | 98% |
| Mario Sports Superstars | 70,595 | 97% |
| Kid Icarus: Uprising | 58,144 | 98% |
| Kirby: Triple Deluxe | 54,377 | 98% |
| Pokémon Omega Ruby / Alpha Sapphire | 36,496 each | 96% |
| Monster Hunter 4 Ultimate | 24,295 | 99% |
| Animal Crossing: New Leaf | 21,517 | 94% |
| Tomodachi Life | 16,651 | 97% |
| Fire Emblem: Awakening | 10,295 | 90% |
| Yo-Kai Watch 3 | 14,188 | 81% |
| Super Smash Bros. for Nintendo 3DS | 4,519 | 95% |
| Zelda: Ocarina of Time 3D | 3,584 | 94% |
| Nano Assault | 638 | 92% |

---

## Known limitations: read this before filing a bug

> **This is a beta. Broken and missing textures are expected.** If a game you care about has issues, that's useful signal, but please check below before assuming it's a bug.

### Unsupported games

These formats require executable reverse engineering to crack and are out of scope for this tool:

- **All 15 LEGO 3DS titles:** TT Games uses a proprietary streaming compression format (FUSE) that would require disassembling the game executable to reverse engineer.
- **Ghost Recon: Shadow Wars and other Ubisoft 3DS titles:** Ubisoft's MAGM engine leaves nothing recognizable in the ROM. Confirmed dead end.
- **Various EA and Activision titles:** fully proprietary engines, no standard texture containers present.

### Partially supported games

- **Luigi's Mansion: Dark Moon:** 869 textures accessible via deep scan (`--scan-all` flag) but the normal pipeline misses them. Next Level Games' container format isn't fully parsed.
- **Yo-Kai Watch series:** IMGC format is decoded but the Huffman compression has edge cases that produce tile artifacts in some textures. Quality sits around 80% instead of 95%+.
- **Professor Layton: Azran Legacy:** similar Huffman edge case issue, some textures show glitch blocks.
- **RE: Mercenaries 3D:** only ~155 textures extracted vs the expected ~1,300+. Same Capcom engine as Revelations but a different internal layout variant not yet handled.

### Thin-strip textures

You'll see some textures with dimensions like 512x8 or 256x8. These come from BCH files where the GPU command parser finds no dimension data and the fallback heuristic guesses wrong. The pixel data exists but the dimensions are misread. These are flagged in the quality report.

### Encrypted ROMs

The tool requires **decrypted ROMs**. Use GodMode9 on a hacked 3DS to dump and decrypt your cartridges. Encrypted dumps will produce zero textures. That's not a bug, that's DRM.

### Quality score interpretation

A quality score of 93% doesn't mean 7% of textures are broken. It means 7% triggered a heuristic flag: solid color, low variance, very dark or very bright. Many of those are legitimate: shadow maps, palette swatches, gradient fills, tiny UI elements. The score is a starting point for investigation, not a verdict.

---

## What this tool is for

To be direct: this tool extracts raw source assets so that human artists can work with them. The intended workflow for an Azahar texture pack (on your AYN Thor, your Steam Deck, your PC) is:

1. Extract textures with this tool
2. Use the originals as reference and scale guides
3. Redraw them at whatever resolution you want
4. Drop the results into Azahar's `load/textures/<TitleID>/` directory

The extraction is the easy part. The art is yours.

The 3DS library deserves better than being forgotten. A lot of these games have never been experienced on anything larger than a 4-inch screen. Some of them are genuinely beautiful (Bravely Default, Ocarina of Time 3D, Fire Emblem Awakening) and they would look extraordinary at 1080p with hand-crafted textures. That's what this is for.

---

## Bug reports

Found a bug? [Open an issue](https://github.com/ZoomiesZaggy/3DS-Texture-Forge/issues/new) and include your ROM filename, extracted texture count, and a screenshot of what looks wrong.

---

## Download

Two Windows builds, no installation required:

- **`3DS Texture Forge.exe`** (66 MB): GUI, drag-and-drop
- **`3ds-tex-extract.exe`** (28 MB): CLI for batch extractions

→ [Download from GitHub Releases](https://github.com/ZoomiesZaggy/3DS-Texture-Forge/releases/tag/v1.0-beta)

Source code and full supported games list: [github.com/ZoomiesZaggy/3DS-Texture-Forge](https://github.com/ZoomiesZaggy/3DS-Texture-Forge)
