# Unsupported / Partially Supported Games

Games that use proprietary or unusual formats not fully supported.

## Partially Supported (use --scan-all)

| Game | Textures (--scan-all) | Issue | Format |
|------|-----------------------|-------|--------|
| Luigi's Mansion: Dark Moon | 869 | Custom Next Level Games format (magic: 01130002) | .data files with NLG containers, some have zlib-compressed PICA200 data |

To extract: `python main.py extract "game.3ds" -o output --scan-all`

## Not Investigated

| Game | Notes |
|------|-------|
| Metroid: Samus Returns | MercurySteam proprietary formats |
| Donkey Kong Country Returns 3D | Retro Studios TXTR format (GameCube-derived) |
| Castlevania: Mirror of Fate | MercurySteam proprietary formats |
