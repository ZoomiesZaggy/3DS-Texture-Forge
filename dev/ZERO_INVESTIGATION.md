# Zero-Texture Game Investigation — 2026-03-31

## Summary

Started: 134 zero-texture games
After fixes: 123 zero-texture games
**11 games cracked, 20,524 new textures**

## Fixes Applied

### Fix 1: Magic-based file detection for unknown extensions
`main.py:should_process_file()` now checks magic bytes for ALL files with unknown extensions, not just extensionless files. Also fixed LZ magic check (was comparing 1-byte values against 4-byte magic4).

**Games unlocked:**
- Fossil Fighters: Frontier (`.1` extension → CGFX, 1 GB)
- DK Country Returns 3D (`.bcma` → darc, `.cro` → LZ10)
- F1 2011 (`.gpu` → CTPK, 209 files)
- Ultimate NES Remix (`.carc` → LZ11+SARC, `.crsm` → LZ11)
- Etrian Odyssey Untold (`.hpb` → ACMP contains LZ data)
- Generator Rex (`.irarc` → embedded CGFX)

### Fix 2: Gzip-prefixed CTPK containers
Spike Chunsoft games wrap CTPKs in: 4-byte LE decompressed_size + gzip data.
Added `gzip_container` type to scanner with decompression + recursive extraction.

**Games unlocked:**
- Conception II: 3,074 textures
- Zero Escape: Zero Time Dilemma: 2,490 textures

### Fix 3: GFAC archive parser (Good-Feel)
Good-Feel games use GFAC archives containing GFCP-compressed BCH files.
GFCP = 20-byte header + raw LZ10 data (no Nintendo LZ header).

**Games unlocked:**
- Kirby's Extra Epic Yarn: 3,359 textures
- Poochy & Yoshi's Woolly World: 4,676 textures

## Newly Working Games

| Game | Textures | Quality | Fix |
|------|----------|---------|-----|
| Poochy & Yoshi's Woolly World | 4,676 | 99% | GFAC |
| Kirby's Extra Epic Yarn | 3,359 | 99% | GFAC |
| Conception II | 3,074 | 93% | gzip-CTPK |
| Zero Escape: Zero Time Dilemma | 2,490 | 91% | gzip-CTPK |
| Generator Rex | 2,358 | 96% | magic detect |
| Fossil Fighters: Frontier | 2,216 | 100% | magic detect |
| Ultimate NES Remix | 1,753 | 94% | magic detect |
| F1 2011 | 365 | 98% | magic detect |
| Etrian Odyssey Untold | 117 | 97% | magic detect |
| DK Country Returns 3D | 115 | 100% | magic detect |
| Kingdom Hearts 3D | 1 | 100% | magic detect |

## Investigated But Not Cracked

### Pokemon Ultra Sun / Ultra Moon
- Engine: Game Freak
- DOM file type: extensionless GARC (333 files)
- Magic bytes: CRAG (GARC)
- Status: OPAQUE
- Notes: GARC files contain LZ-compressed PC v5 wrappers. Our unwrapper handles PC v1 (BCH at 0x80) but v5 has different layout. BCH not found at expected offset.

### 3DST Format (Mega Man Legacy Collection)
- Engine: Digital Eclipse / Capcom
- DOM file type: .3dst (1,324 files)
- Magic bytes: 3DST
- Status: OPAQUE
- Notes: Standard PICA200 tiled textures with additional compression layer. Header has format/width/height at fixed offsets, but pixel data sizes don't match any raw format — data is compressed. Need to reverse-engineer the compression algorithm (not zlib, not LZ, not gzip).

### Hyrule Warriors Legends (Koei Tecmo)
- DOM file type: .g1l (1 file, 415 MB) + .bin/.idx pair (924 MB)
- Magic bytes: _L1G0000
- Status: OPAQUE — Koei Tecmo proprietary G1L archive

### Kingdom Hearts 3D (Square Enix)
- DOM file type: .rbin (23 files, 639 MB)
- Magic bytes: CRAR
- Status: PARTIAL (1 texture from .ctp file)
- Notes: Bulk data in CRAR archives not yet parsed

### Etrian Odyssey V (Atlus)
- DOM file type: .hpb/.hpi pair (303 MB)
- Magic bytes: ACMP / HPIH
- Status: OPAQUE — Atlus compressed pack archive

### Professor Layton (Level-5)
- DOM file type: .fa (322-390 MB)
- Magic bytes: XFSA
- Status: OPAQUE — Level-5 XFSA archive format, not same as ARC0

### Code of Princess (Agatsuma)
- DOM file type: .rani (897 MB), .rtx (8 MB)
- Magic bytes: RANI, RTEX
- Status: OPAQUE — custom Agatsuma engine

### Harvest Moon: Skytree Village / Lost Valley (Marvelous)
- DOM file type: .tarc (31-41 MB)
- Magic bytes: TBAF
- Status: OPAQUE — Marvelous TBAF archive

### Culdcept Revolt (OmiyaSoft)
- DOM file type: .dat (277 MB, single blob)
- Status: OPAQUE — single large binary, no clear archive structure

### Luigi's Mansion: Dark Moon (NLG)
- DOM file type: .data/.dict pairs (338 MB)
- Magic bytes: LZ-compressed data + BKHD (Wwise audio)
- Status: OPAQUE — NLG bundle format with Wwise audio banks

### DK Country Returns 3D (Retro Studios)
- DOM file type: .lvl (1440 MB), .res (60 MB)
- Magic bytes: 0TSRD
- Status: PARTIAL (115 textures from darc/LZ files)
- Notes: Bulk data in 0TSRD (Retro Studios) format not parsed. Got 115 textures from small darc and LZ-compressed files.

### Mario Party Star Rush / Top 100 (ND Cube)
- DOM file type: .zdat (89-111 MB)
- Magic bytes: RZPK
- Status: OPAQUE — ND Cube RZPK compressed archive

### Blazblue (Arc System Works)
- DOM file type: .bin (805 MB, zlib-compressed) + .cpk (142 MB)
- Status: OPAQUE — zlib data decompresses but doesn't contain texture magic

### Naruto Powerful Shippuden (CyberConnect2)
- DOM file type: .irarc (312 MB)
- Magic bytes: custom (no ASCII magic)
- Status: OPAQUE — CyberConnect2 archive

## Confirmed Dead Ends (Skip List)

- All LEGO games (TT Games FUSE engine)
- Tom Clancy's Ghost Recon (Ubisoft MAGM)
- WWE All Stars (THQ proprietary)
- Amazing Spider-Man 1&2 (Beenox)
- Transformers games (Activision)
- Batman Arkham Origins Blackgate (Armature ARMA engine, 674 MB single blob)
- Angry Birds Trilogy/Star Wars (Exient T3D/XGST format)
- Shantae and the Pirate's Curse (WayForward .vol proprietary)
- Shovel Knight (.pak proprietary)
- Terraria (.otx proprietary)
- Cartoon Network games (proprietary)
- Regular Show (.vol proprietary, same as Shantae)
- Scribblenauts Unlimited (proprietary .p format)
- Asphalt 3D (Gameloft .bar archive)
- Pilotwings Resort / Pac-Man Party 3D (fully proprietary)
- Sega 3D Classics Collection (mfl format, emulated Genesis/Master System)
- Cave Story 3D (n3d format pairs, proprietary)
- Pac-Man & Galaga Dimensions (BMP + proprietary)
- Gravity Falls (Ubisoft .ipk proprietary)
- Skylanders series (Activision proprietary)

## Formats Worth Future Investigation

1. **XFSA** (Level-5) — Would unlock 2+ Professor Layton games
2. **3DST** (Capcom/Digital Eclipse) — Would unlock Mega Man Legacy Collection (1,324 textures)
3. **TBAF** (Marvelous) — Would unlock Harvest Moon games
4. **CRAR** (Square Enix) — Would unlock Kingdom Hearts 3D bulk textures
5. **G1T/G1L** (Koei Tecmo) — Would unlock Hyrule Warriors Legends
6. **ACMP** (Atlus) — Would unlock Etrian Odyssey V
7. **PC v5** (Game Freak) — Would unlock Pokemon Ultra Sun/Moon
