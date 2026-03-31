# Session Log — Multi-Day Optimization + Parser Completion

## Session Start: 2026-03-30

### Phase 1: Profiling

#### 1A — Extraction Speed Baselines

| Game | Time | Files | Scanned | Containers | Textures |
|------|------|-------|---------|------------|----------|
| Mario Kart 7 | 13.8s | 621 | 474 | 357 | 2,770 |
| Fire Emblem Awakening | 38.8s | 7,368 | 7,023 | 5,301 | 10,295 |
| Pokemon Y | 38.6s | 653 | 272 | 27 | 57,681 |

#### 1B — cProfile Results (Pokemon Y, top bottlenecks)

| Function | tottime | cumtime | Calls | Notes |
|----------|---------|---------|-------|-------|
| _scan_section_numpy | 8.75s | 13.55s | 95,490 | Biggest hotspot |
| _decompress_lz11 | 13.07s | 13.07s | 766 | Pure Python LZ11 |
| np.any() | 0.62s | 4.07s | 1,118,792 | Called from _scan_section_numpy |
| read_u32_le | 1.42s | 2.34s | 4,112,820 | Hot utility function |
| Pickle (dump+loads) | 3.48s | 3.48s | ~1100 | Multiprocessing overhead |
| _heuristic_scan | 2.29s | 16.76s | 4,415 | BCH heuristic scanning |
| _extract_textures_gpu_multiblock | 0.86s | 3.12s | 2,498 | BCH struct parser |
| _parse_gpu_commands | 0.36s | 0.90s | 31,197 | GPU command parsing |

Key insight: `_scan_section_numpy` is the #1 target. The nested Python for-loops
over word indices generate 1.1M np.any() calls. Vectorizing the full scan would
eliminate most of this overhead.

#### 1C — Memory Profiling

Fire Emblem Awakening: ROM is loaded fully into memory (~300MB).
No obvious leaks — textures are processed and discarded per-file.
Peak memory is dominated by the romfs_data buffer.

#### 1D — Quality False Positive Audit

| Game | Textures | Sampled | Suspicious | Quality | Dominant Flag |
|------|----------|---------|------------|---------|---------------|
| Mario Kart 7 | 2,770 | 277 | 2 (0.7%) | 0.993 | EXTREME |
| Fire Emblem Awakening | 10,295 | 1,029 | 173 (16.8%) | 0.832 | EXTREME/SOLID |
| Pokemon Y | 57,681 | 5,768 | 360 (6.2%) | 0.938 | LOW_VARIANCE |
| Kirby Triple Deluxe | 12,820 | 1,282 | 9 (0.7%) | 0.993 | EXTREME |
| Dragon Quest VIII | 16,275 | 1,627 | 132 (8.1%) | 0.919 | LOW_VARIANCE |

Key findings:
- Fire Emblem Awakening has highest false positive rate (16.8%)
  - SUSPICIOUS_EXTREME is the dominant flag (168 of 173)
  - Many FE textures are legitimately dark (shadow maps, night textures)
- LOW_VARIANCE is the most common false positive across all games
  - Many legitimate gradient/shadow textures have stddev 3-5
- SUSPICIOUS_SOLID threshold at 95% is reasonable — few false positives
- Recommendation: Raise EXTREME threshold or add format-aware exceptions

---

### Phase 2: Speed Optimization

#### 2A — BCH heuristic scan optimization (COMMITTED)
Optimization: skip Method 1 (section probing via _scan_section_numpy) when
struct parser already found valid textures. Method 1 only produces data_size=0
results that get filtered out by the merge anyway.

Impact:
- _heuristic_scan: 16.76s → 5.09s (-70%)
- _scan_section_numpy: 95,490 calls → 32,180 (-67%)
- 1.1M np.any() calls eliminated
- Total function calls: 24.6M → 17.2M (-30%)

#### 2B — LZ11 literal batching (COMMITTED)
Rewrote inner loop as while-based to batch consecutive literal bytes.
Fast path for flags=0x00 copies 8 bytes in one slice operation.

#### 2C — File skip-list (COMMITTED)
Added _SKIP_EXTENSIONS for audio (.bcstm), video (.moflex), fonts, scripts etc.

### Phase 3: Quality Filtering (COMMITTED)

Format-aware quality thresholds:
- ETC1/ETC1A4: SOLID→99%, LOW_VARIANCE→3.0, EXTREME→2.0/253.0
- Grayscale (LA/L): SOLID→97%, LOW_VARIANCE→3.0
- Expanded tiny exemption: 8×8 → 16×16
- Removed aggressive aspect ratio check

Results:
| Game | Before | After | Change |
|------|--------|-------|--------|
| FE Awakening | 0.832 | 0.867 | +3.5% |
| DQ8 | 0.919 | 0.933 | +1.4% |
| Pokemon Y | 0.938 | 0.940 | +0.2% |

### Phase 4: Parser Fixes

#### 4A — RE Mercenaries 3D (COMMITTED)
Problem: Version byte 0xA4 vs 0xA5 difference. Hardcoded header size 0x14
but Merc uses 0x10. Also missing mip chain support.

Fix: Iterate profile header_offsets + added _find_mipchain_dims() for
payloads containing concatenated mip levels.

Result: 155 → 2,151 textures (+13.9x)

#### 4H — Fantasy Life (COMMITTED)
Problem: Game uses proprietary Level-5 flat file archive (_file_archive.bin,
372MB) not recognized by any parser.

Fix: New parsers/l5_flat.py for the flat offset-table format. CGFX
containers are embedded at ~0x180 offset within LZ11-compressed entries.
Scanner now scans first 4KB of each entry for texture magic.

Result: 0 → 10,254 textures

#### Other Phase 4 games checked:
- Kingdom Hearts 3D: .rbin (CRAR) proprietary format. Documented, skipped.
- Sonic Generations: 10 textures via CPK (most content in CPK, working)
- Sonic Lost World: 38 textures via CPK
- Metal Gear Solid: 1,744 textures (already working!)
- Castlevania: 2,363 textures (already working!)
- Hatsune Miku: 4,982 textures (already working!)
- Luigi's Mansion Dark Moon: NLG bundle format, documented, skipped

### Phase 5: Cross-Platform Support

#### 5A — Platform audit (DONE)
Codebase is already cross-platform:
- os.path.join for all path construction
- Path.home() for config directory
- PySide6 for GUI (cross-platform)
- No Windows-specific APIs in core logic

#### 5F — README updated (COMMITTED)
- Added Linux/Mac ARM instructions
- Added platform support matrix
- Updated game counts and supported formats

### Phase 6: Final Release

#### 6A — Full regression: ALL PASS
All 11 available core regression games pass.

#### 6B — Regression suite updated (COMMITTED)
- RE:Mercenaries threshold: 100 → 1,700
- Added 4 new games: Fantasy Life, Hatsune Miku, MGS, Castlevania

#### 6D — Executables rebuilding (in progress)

---

## Session Summary

### Achievements:
1. **Speed**: BCH heuristic scan 70% faster, 30% fewer function calls
2. **Quality**: Format-aware thresholds (+3.5% FE Awakening, +1.4% DQ8)
3. **RE:Mercenaries**: 155 → 2,151 textures (mip chain support + header fix)
4. **Fantasy Life**: 0 → 10,254 textures (new Level-5 flat archive parser)
5. **Cross-platform**: README with Linux/Mac instructions
6. **Regression**: All games pass, 4 new games added

### Commits (6 total):
1. Speed optimizations: skip BCH section probing, batch LZ11, file skip-list
2. Quality filtering: format-aware thresholds
3. RE:Mercenaries TEX fix: header offset iteration + mipchain support
4. Fantasy Life: Level-5 flat file archive parser
5. README: cross-platform docs, new game counts
6. Regression: updated thresholds and new games

