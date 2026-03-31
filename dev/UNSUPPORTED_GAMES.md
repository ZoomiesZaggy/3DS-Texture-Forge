# Unsupported / Partially Supported Games

Games that use proprietary or unusual formats not fully supported by 3DS Texture Forge.

## Zero-Texture Games by Engine/Publisher

### Level-5 Engine (IMGC/XOR-encrypted CTPK)
Games: Yo-Kai Watch (all 5 titles), Professor Layton (3 titles), Fantasy Life, LBX
Issue: Level-5 uses proprietary IMGC texture format and XOR-encrypted CTPK files (key: 0x59CE repeating)
ARC0 archives are parsed but inner textures are in IMGC format, not standard PICA200 containers.

### TT Games Engine (GHG archives)
Games: All 15 LEGO titles
Issue: Uses .fib proprietary blob archives. One GHG parser would unlock all 15 games.

### Atlus Engine (STEX/HPB archives)
Games: Etrian Odyssey (4 titles), Radiant Historia, SMT Devil Summoner Soul Hackers
Issue: Uses .stex texture format and .hpb/.hpi paired archives.
Note: Some Atlus games DO work (Persona Q, SMT IV) because they use standard BCH/CPK.

### Square Enix (.rbin archives)
Games: Kingdom Hearts 3D
Issue: Uses proprietary .rbin container format.

### WayForward Engine (.vol archives)
Games: Shantae and the Pirate's Curse, Adventure Time (3 titles)
Issue: Uses .vol archive format wrapping all game data.

### Koei Tecmo (.g1l archives)
Games: Hyrule Warriors Legends
Issue: Single 436MB .g1l blob contains all game data. Proprietary format.

### NIS America (N3D format)
Games: Cave Story 3D
Issue: Uses .n3ddta/.n3dhdr paired model/texture files.

### Game Freak CM v6 (Pokemon Sun/Moon/Ultra)
Games: Pokemon Sun, Moon, Ultra Sun, Ultra Moon
Issue: Textures embedded in CM v6 model containers inside GARCs. Not standard BCH/CGFX.
Note: Pokemon X/Y/OR/AS work because they use standard BCH inside GARCs.

### Other Proprietary
- Donkey Kong Country Returns 3D: Retro Studios format
- Sonic games: Some use standard CGFX, others use Sega proprietary
- Skylanders: Vicarious Visions .pak format
- Various licensed games: Third-party engines with custom formats

## Partially Supported (use --scan-all)

| Game | Textures (--scan-all) | Issue |
|------|-----------------------|-------|
| Luigi's Mansion: Dark Moon | 869 | NLG bundle: concatenated zlib streams → LZ13 chunks. No standard texture magics found in decompressed data. Proprietary NLG engine format. |

## Statistics from Full Library Scan (319 games)

- 165 games produce textures (52%)
- 144 games produce zero textures (48%)
- 1,412,672 total textures extracted
- 93.0% average quality score
- Most impactful missing parsers: GHG (15 games), IMGC (8 games), STEX (6 games)
