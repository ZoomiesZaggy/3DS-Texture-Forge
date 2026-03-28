# Format Registry

Complete table of all archive + texture formats supported by 3DS Texture Forge.

## Texture Container Formats

| Format | Magic | Extension | Parser file | Games | Status |
|--------|-------|-----------|-------------|-------|--------|
| BCH | `BCH\x00` | .bch, .bcres | textures/bch.py | Most 3DS games | Working |
| CGFX | `CGFX` | .bcres, .cgfx | textures/cgfx.py | Kirby, MK7, SM3DL | Working |
| CTPK | `CTPK` | .ctpk | textures/ctpk.py | Pokemon, Zelda | Working |
| CTXB | `CTXB` | .ctxb | textures/ctxb.py | Zelda OOT3D/MM3D | Working |
| CMB | `cmb\x20` | .cmb | textures/cmb.py | Zelda OOT3D/MM3D | Working |
| BFLIM | `FLIM` (footer) | .bflim | textures/bflim.py | UI textures | Working |
| BCLIM | `CLIM` (footer) | .bclim | textures/bflim.py | UI textures | Working |
| Capcom TEX | `TEX\x00` | .tex | textures/tex_capcom.py | RE:Rev, MH4U, MHGen | Working |
| Shin'en TEX | `TEX CTR` | .tex | textures/shinen_tex.py | Nano Assault | Working |
| jIMG | `jIMG` | .jtex | textures/jimg.py | One Piece | Working |
| GDB1 | `GDB1` | .texturegdb | textures/gdb1.py | Star Fox 64 3D | Working |

## Archive Formats

| Format | Magic | Extension | Parser file | Games | Status |
|--------|-------|-----------|-------------|-------|--------|
| GARC | `CRAG` | .garc | parsers/garc.py | Pokemon X/Y/OR/AS/S/M | Working |
| SARC | `SARC` | .sarc, .arc | parsers/sarc.py | Zelda ALBW, Splatoon | Working |
| NARC | `NARC` | .narc | parsers/narc.py | Various | Working |
| ZAR | `ZAR\x01` | .zar | parsers/zar.py | Zelda OOT3D/MM3D | Working |
| GAR | `GAR2` | .gar | parsers/gar.py | Zelda MM3D | Working |
| DARC | `darc` | .darc | parsers/darc.py | Kid Icarus | Working |
| Capcom ARC | `ARC\x00` | .arc | parsers/arc_capcom.py | RE, MH series | Working |
| FE ARC | (custom) | .arc | parsers/arc_fe.py | Fire Emblem Awakening/Fates | Working |
| CPK | `CPK\x00` | .cpk | parsers/cpk.py | Persona Q, 7th Dragon | Working |
| ARC0 | `ARC0` | .fa | parsers/arc0.py | Layton, Yo-Kai Watch | Working |
| Smash dt/ls | (custom) | dt, ls | parsers/smash_dt.py | Smash Bros 3DS | Working |

## Compression Formats

| Format | Magic/ID | Parser file | Status |
|--------|----------|-------------|--------|
| LZ10 | `0x10` | parsers/lz.py | Working |
| LZ11 | `0x11` | parsers/lz.py | Working |
| LZ13 | `0x13` | parsers/lz.py | Working |
| BLZ | (footer) | parsers/lz.py | Working |
| Yaz0/SZS | `Yaz0` | textures/scanner.py | Working |
| CRILAYLA | `CRILAYLA` | parsers/cpk.py | Working |
| zlib/DEFLATE | `0x78 0x9C` etc. | textures/scanner.py | Working |

## ROM Container Formats

| Format | Magic | Extension | Parser file | Status |
|--------|-------|-----------|-------------|--------|
| NCSD | `NCSD` | .3ds, .cci | parsers/ncsd.py | Working |
| NCCH | `NCCH` | .cxi, .app | parsers/ncch.py | Working |
| CIA | (header) | .cia | parsers/cia.py | Working |
| RomFS/IVFC | `IVFC` | (internal) | parsers/romfs.py | Working |

## PICA200 Pixel Formats

| ID | Name | BPP | Notes |
|----|------|-----|-------|
| 0x00 | RGBA8 | 32 | Stored as ABGR bytes |
| 0x01 | RGB8 | 24 | Stored as BGR |
| 0x02 | RGBA5551 | 16 | 5R 5G 5B 1A, little-endian |
| 0x03 | RGB565 | 16 | 5R 6G 5B, little-endian |
| 0x04 | RGBA4 | 16 | 4R 4G 4B 4A, little-endian |
| 0x05 | LA8 | 16 | byte0=A, byte1=L |
| 0x06 | HILO8 | 16 | Normal map: R=H, G=L, B=255 |
| 0x07 | L8 | 8 | Grayscale |
| 0x08 | A8 | 8 | Alpha only |
| 0x09 | LA4 | 8 | High nibble=L, low nibble=A |
| 0x0A | L4 | 4 | 4-bit grayscale |
| 0x0B | A4 | 4 | 4-bit alpha |
| 0x0C | ETC1 | 4 | 8 bytes per 4x4 block |
| 0x0D | ETC1A4 | 8 | 16 bytes per 4x4 block (8 alpha + 8 color) |
| 0x14 | RGBA8 (alt) | 32 | Capcom alternate ID |
| 0x19 | ETC1 (alt) | 4 | Atlus alternate ID |
| 0x1A | ETC1A4 (alt) | 8 | Atlus alternate ID |
