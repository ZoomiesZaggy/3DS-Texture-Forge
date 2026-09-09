# 3DS Texture Forge: Comprehensive Code Overview

Date: 2026-07-01. Scope: full read-only audit of the v2 codebase at `C:\Users\Zagre\Downloads\3ds-tex-extract` (3DS Texture Forge 2.0), covering architecture, format correctness, quality, security, performance, and roadmap readiness.

## Executive summary

3DS Texture Forge 2.0 is a well-architected v2 rewrite: a clean core/rom/compression/archives/textures/pipeline/output/commands/gui layering wired by three plugin registries, with a thin non-leaky GUI seam and a genuinely strong, well-tested path-traversal defense. The architecture is ready for the roadmap. The problems are concentrated in the vendored v1 parser internals (`_v1_*.py`) and in one class of silent failure that matters more than any other for this specific tool: the Azahar hash is computed over the wrong bytes, so packs can decode to perfect PNGs and still never match in the emulator. Two format codecs (CRILAYLA, Level-5 Huffman) are effectively broken, and the Level-5 path is also a catastrophic performance cliff.

Health grade per section:

| Section | Grade | One-line justification |
|---|---|---|
| 1. Architecture | A- | Clean layering, plugin registries, no core-imports-GUI; minor docstring drift, one layering inversion, dead adapter seams |
| 2. Format correctness | C | CityHash64 verified exact, but the hash covers full payloads not mip0; CRILAYLA and Level-5 Huffman decode to garbage |
| 3. Quality | B- | 106 tests pass fast and path-traversal coverage is excellent, but container parsers, archives, and half the codecs are untested; asymmetric error handling |
| 4. Security | B+ | Traversal fix HOLDS on all 3ds write sinks with one mapped-mode gap; gx code (if merged) would regress it hard |
| 5. Performance | D | 97.7% of a 585s baseline run is interpreted bit-by-bit Level-5 Huffman; batch at scale is not viable until fixed |
| 6. Roadmap readiness | B | Batch is done, registries make new formats cheap; Pokemon adapters are written but unwired, hash bug blocks v3.0's whole value |

Top 5 risks:
1. Azahar hash is computed over each parser's full payload including mip chains and padding, not the mip0 surface bytes Azahar hashes (2.2). Any CTPK/Shin'en texture with mipmaps produces a pack filename that silently never matches in-game. This undermines the tool's primary output.
2. The CRILAYLA decompressor implements a different algorithm than CRILAYLA (2.3); all compressed CPK-game content is silently lost, and the self-referential test hides it.
3. The Level-5 Huffman decoder is 97.7% of the profiled runtime (~571 of 585s, ~2.3 billion interpreted `read_bit` calls) AND has a suspected child-offset bug, so it is both catastrophically slow and probably producing rejected garbage (5.2, 2.3).
4. Texture container parsers are not defensively wrapped (3.3), so one malformed container aborts the entire content extraction, while the same class of failure in an archive plugin is caught and skipped. Combined with near-zero container-parser test coverage (3.1), corrupt real-world ROMs can silently truncate output.
5. Failed PNG/raw writes are recorded as successful `decoded_ok` manifest rows with non-existent paths (3.2), so the tool can report a clean run while silently dropping output files.

Top 5 quick wins (all S, high value):
1. Slice `tex.data` to the mip0 encoded size before hashing (fixes risk 1, the highest correctness-per-effort change in the codebase).
2. Wrap texture-plugin iteration in the same try/except the archive side already uses (fixes risk 4's blast radius in one small change).
3. Plumb the writer-future results so failed writes stop being logged as decoded_ok (fixes risk 5).
4. Fix the BFLIM A4-to-A8 mismap and the post-crop dimension overwrite so cropped BFLIMs ship usable, correctly-typed PNGs (2.1, 2.2).
5. Add the mapped-mode dump_hash commonpath guard and the generic zlib/gzip output caps (4.4).

The single most important non-quick-win is fixing the Level-5 codec (detect gating + word-chunked bit reading), which removes ~500s from the baseline run and is the real prerequisite for batch and Pokemon at scale.

Scope caveats: the requested `wii-gc-support` branch and its `platforms/gx/` do not exist on the GitHub remote (only v1.1 on `main`), so that diff was assessed against the standalone `wii-tex-extract` project instead (sections 1.6, 4.3); the brief's ROM path did not exist, so profiling used the on-disk NSMB2 copy; and the brief's "70 tests" is now 106.

Full detail follows in sections 1 through 6.

---


## 0. Scope notes and deviations

- The GitHub repository `ZoomiesZaggy/3DS-Texture-Forge` contains only the v1.1 code on a single `main` branch. There is no `wii-gc-support` branch on the remote, and the local v2 working copy is not a git repository, so a `platforms/gx/` vs `main` diff is not possible. The closest artifact is the standalone project at `C:\Users\Zagre\Desktop\wii-tex-extract` (Wii/GC extractor with `src/decoders/gx_decoder.py`), which this report assesses as the likely source of a future gx merge (integration risk and security surface).
- The ROM set path given in the brief (`D:\3ds Rom set\No-Intro\...`) does not exist on this machine. Profiling used the available copy: `D:\Roms\3DS\n3ds\New Super Mario Bros. 2 (USA) (En,Fr,Es).cci` (512 MiB, decrypted).
- The brief mentions 70 tests; the current tree has 15 test files with 93 test functions.

## 1. Architecture map

Root: `C:\Users\Zagre\Downloads\3ds-tex-extract` (not a git repo). Package version `2.0.0` (`tex_forge/__init__.py:13`). The codebase is a v2 rewrite of a monolithic v1: v1 parser internals are vendored as `_v1_*.py` / `_cpk_v1.py` / `_gui_app_v1.py` files and wrapped by thin v2 plugin shims.

### 1.1 Module and package inventory

#### Top level
| File | Purpose |
|---|---|
| `forge_gui.py` | PyInstaller entry script, delegates to `tex_forge.gui.entry.main` (PyInstaller wants a script, not a module) |
| `forge.spec` | PyInstaller onefile windowed build (`dist/3DS-Texture-Forge.exe`); `collect_submodules("tex_forge")` guarantees all import-side-effect plugins are frozen in; excludes QtWebEngine/QML/Multimedia |
| `Launch-Forge.bat` | 4-line launcher: `python -m tex_forge.gui.entry` from the script's own directory |
| `pyproject.toml`, `requirements.txt` | Packaging; PySide6 is an optional `[gui]` extra, cityhash is optional (pure-Python fallback exists) |
| `README.md`, `PROGRESS.md` | Docs and running work log |
| `tex_forge/cli.py` | argparse CLI entry (`tex-forge`), builds subparsers from `commands/*` and dispatches via an `args._handler` attribute (cli.py:53-60) |
| `tex_forge/__init__.py` | Docstring-only public-surface pointer, `__version__` |

#### tex_forge/core (bottom of the dependency graph)
Cross-cutting primitives; `core/__init__.py:3` states the rule "must NOT import from another tex_forge package" (which holds).
- `binio.py`: bounds-checked struct read helpers (`read_u32_le` etc.), 0x200 media-unit constant.
- `exceptions.py`: `TexForgeError`, `ROMParseError`, `EncryptedROMError` (the latter triggers the GodMode9 hint in CLI/GUI).
- `logging.py`: `setup_logging(verbose, quiet)` shared by CLI and GUI.
- `types.py`: the inter-layer dataclasses `ArchiveEntry`, `Texture`, `FilePeek`, plus `sanitise_archive_name` (types.py:93), the single chokepoint that neutralizes attacker-controlled archive entry names (path separators, `..`, control chars, Windows-reserved basenames). `ArchiveEntry.__post_init__` sanitizes automatically.

#### tex_forge/rom
Outermost container parsers: file path in, RomFS bytes out.
- `loader.py`: `parse_rom(path)` (loader.py:44) and multi-content `iter_rom_contents(path)` (loader.py:73); `_route` (loader.py:164) picks NCSD/CIA/NCCH by extension then magic; exports `ROM_EXTENSIONS` (loader.py:38) as the single source of ROM discovery truth for GUI and `batch`; `content_label_from_chain` (loader.py:114).
- `ncsd.py`: `NCSDParser`, .3ds/.cci cartridge image, partition table at 0x120, `get_partition(0)`.
- `ncch.py`: `NCCHParser`, reads title ID / product code / RomFS offset; raises `EncryptedROMError` when the NoCrypto flag (0x18F bit2) is clear.
- `cia.py`: `CIAParser`, parses TMD content chunk records, `get_content(i)` / `iter_contents()` including update/DLC CFAs (64-byte content alignment).
- `romfs.py`: `RomFSParser`, IVFC level-3 walk, BFS builds a flat `(path, offset, size)` list; `list_files()`, `read_file_by_index()`.
- `icon.py` / `banner.py`: read-only GUI accessors for the SMDH 48x48 icon and CBMD banner CGFX; deliberately reuse the existing decoder/codec/plugin stack, never raise (return None).

#### tex_forge/compression
Self-registering decompression codecs; `compression/__init__.py` re-exports `try_decompress` and performs the side-effect imports that register every codec.
- `registry.py`: `register_compression` decorator, `_CODECS` list sorted descending by priority, `try_decompress(data, hint=)` (registry.py:92), `decompress_by_name`.
- `lz_nintendo.py`: LZ10/LZ11/LZ13 (priorities 70/65/60).
- `blz.py`: backward LZSS with end-of-file footer (priority 80).
- `yaz0.py`: Yaz0/SZS (priority 90).
- `zlib_helpers.py`: raw zlib (40) and Spike Chunsoft 4-byte-size-prefixed gzip (50).
- `crilayla.py`: CRI's backward LZSS used inside CPK (priority 95, highest).
- `level5.py`: Level-5 method-byte wrapper (priority 30); re-exports `decompress_l5` which actually lives in `textures/containers/_v1_level5.py` (a layering inversion, see 1.5).

#### tex_forge/archives
Container plugins yielding `ArchiveEntry`; `archives/__init__.py` does the side-effect registration imports.
- `registry.py`: `ArchivePlugin` Protocol, `register_archive`, `detect_archive(data)` (registry.py:74).
- `garc.py` (prio 100): Game Freak GARC (Pokemon); also exposes `has_cgfx()` helper (garc.py:92).
- `sarc.py` (95): Nintendo SARC/SFAT/SFNT.
- `narc.py` (95): legacy DS NARC.
- `zar.py` (90): Grezzo ZAR (OoT3D/MM3D).
- `gar.py` (85): Grezzo GAR v2, scans for embedded ctxb/cmb rather than decoding the table.
- `darc.py` (85): darc (Kid Icarus).
- `gfac.py` (85): Good-Feel GFAC with GFCP-wrapped LZ entries (synthesizes a Nintendo LZ header and dispatches to `lz_nintendo`).
- `arc_capcom.py` (80): MT Framework ARC with per-version size-field autodetection.
- `cpk.py` (78): CRI CPK plugin shim wrapping `_cpk_v1.py` (the full @UTF/TOC/CRILAYLA parser, verbatim from v1).
- `arc_fe.py` (75): Intelligent Systems ARC (Fire Emblem), feeds candidate offsets to the LZ decompressor.
- `arc0.py` (70): Level-5 ARC0/XFSA, pragmatic magic-scan instead of full table decode.
- `l5_flat.py` (55): Level-5 flat offset-table archive (Fantasy Life).
- `smash_dt.py`: deliberately NOT registered (docstring states this); exposes `parse_ls()` + `decompress_resource()` for the pipeline adapter.

#### tex_forge/textures
- `formats.py`: `PicaFormat` IntEnum, single source of truth for PICA200 format IDs, bpp, names, vendor aliases (`resolve()`).
- `morton.py`: lru-cached Z-order scatter tables for 8x8 tiles and ETC1 4x4 macro-tiles (inverse maps for NumPy scatter writes).
- `registry.py`: `TexturePlugin` Protocol, `register_texture`, `detect_texture(data)` (registry.py:63).
- `azahar_hash.py`: `compute_azahar_hash` (CityHash64 of raw GPU bytes, matching Azahar's `ComputeHash`), `azahar_hash_hex` (azahar_hash.py:102), `azahar_filename` (azahar_hash.py:113) which formats `tex1_<W>x<H>_<HASH>_<code>_mip0.png`; picks native `cityhash` at import, else the pure fallback.
- `_cityhash_pure.py`: vendored byte-exact pure-Python CityHash64.
- `_compat_decoder.py`: shim re-exporting v1's `FMT_*` constants and `decode_texture_fast` names for the vendored v1 parsers.
- `decoder/`: `dispatch.py` `decode(data, w, h, fmt)` (numpy first, python fallback, None on failure; the separate file exists explicitly to avoid a circular import, dispatch.py:8-11); `pica_numpy.py` vectorized decoders (fancy-indexed Morton scatter, block-parallel ETC1); `pica_python.py` scalar correctness-first fallback for tiny textures.
- `containers/`: 12 registered plugin shims, each pairing a `detect` and `iter_textures` around a vendored `_v1_*` parser, converted via `_dict_to_texture.py`: `ctpk` (prio 92), `ctxb` (92), `cgfx` (90), `bflim` (88, footer-magic detection), `cmb` (88), `jimg` (88), `shinen_tex` (86), `capcom_tex` (85), `imgc`/`level5_imgc.py` (82, tile-map + tile-palette reconstruction), `bch` (80, heuristic parser, known false-positive source), `stex` (70), `gdb1` (70, detection only; paired-file logic lives in pipeline adapters). The `_v1_*.py` files hold the actual binary parsing (BCH struct+heuristic, CGFX TXOB walk, CTPK, CTXB/CMB DMP-GL format maps, BFLIM/BCLIM footers, jIMG, IMGC + `decompress_l5`, Shin'en TEX/CMPR, STEX, Capcom TEX strict multi-profile parser, GDB1 node tree).

#### tex_forge/pipeline
Orchestration layer.
- `extractor.py` (633 lines): `ExtractOptions` (extractor.py:81), `ContentSource` (103), `ExtractionPipeline` (123) with `run()` (166), `_process_content()` (255), `_handle_texture()` (355), `_build_output_path()` (540), `_write_outputs()` (593). PNG writes go through a `ThreadPoolExecutor` (173); cooperative cancellation via `cancel_event` (157); multi-content CIA support with shared dedup and a shared tex counter.
- `scanner.py`: `classify_file()` (scanner.py:39) and the recursive `extract_textures()` (scanner.py:118, depth cap 8), plus `_has_texture_payload` fast-reject (107) and `_scan_embedded` (186, scan_all only).
- `filter.py`: `FileFilter` (filter.py:81), skip/process extension sets, process-dir substrings, `is_definitely_not_texture` (139) audio-magic rejector.
- `dedup.py`: `Deduper`, tier 1 xxhash64 on raw bytes (optional dependency, disabled with a log line if missing, dedup.py:35-39), tier 2 md5 on decoded RGBA.
- `adapters.py`: game-specific seams: `smash_virtual_entries` (adapters.py:46) + `decompress_smash_resource` (91) for the Smash dt/ls bank, `build_texturebin_index` (115) + `parse_gdb1_pair_from_index` (124) for Star Fox GDB1 pairs, `unwrap_pokemon_container` (156), `parse_pokemon_pc_v5` (171), `garc_should_suppress_bch` (241).
- `progress.py`: `ProgressCallback` Protocol, `NullProgress`, `CLIBarProgress`, `CallableProgress` (the GUI bridge).

#### tex_forge/quality
- `metrics.py`: `compute_quality_metrics(rgba, pica_format)` (per-texture suspicion flags: transparency, variance, format-category thresholds) and `generate_quality_report` (aggregate JSON+TXT).

#### tex_forge/output
Writers, split from v1's mixed-concern `output.py`.
- `png_writer.py`: `save_png` with the alpha-visibility heuristic (constant RGB + varying alpha gets remapped so glyph/shadow textures are inspectable).
- `filenames.py`: `generate_filename` (filenames.py:31), `build_output_path` (53) with realpath/commonpath traversal defense (raises `ValueError` on escape), `sanitise_subdir` (107).
- `manifest.py`: schema-v2 `make_record` (manifest.py:29), `write_manifest` / `write_failures` / `write_summary` / `write_unknowns`, `sha1_bytes` / `sha1_rgba`.
- `pack_builder.py`: `build_pack` (pack_builder.py:59), modes azahar > mapped > staging (auto-selected), writes `tex1_*` PNGs plus a deliberately minimal Azahar `pack.json` (pack_builder.py:281; Forge audit metadata goes to `forge_pack_meta.json` instead because a large pack.json can crash Azahar, pack_builder.py:256-267).
- `contact_sheet.py`: PIL thumbnail grid `contact_sheet.png` for visual proof.
- `reports.py`: thin `write_quality_report` wrapper delegating computation to `quality/`.

#### tex_forge/commands
One module per CLI subcommand, each exposing `add_subparser(sub)`.
- `_common.py`: `setup()`, `load_rom_or_die()`, `load_all_contents_or_die()` (_common.py:30), `_print_encrypted_help()` (GodMode9 banner).
- `extract.py`: wires `load_all_contents_or_die` into `ExtractionPipeline` with `CLIBarProgress`.
- `batch.py`: walks folders via `ROM_EXTENSIONS`, per-title output dirs, duplicate-title skip, `batch_summary.json`, continue-on-error.
- `scan.py`: RomFS listing + `classify_file` breakdown, no extraction.
- `verify.py`: audits manifest vs disk (missing PNGs, shared-path collision signature, orphans), exit code 0/1.
- `report.py`: summarizes manifest/failures/unknowns of a past run.
- `build_pack.py`: CLI front for `output.pack_builder.build_pack`.
- `import_dump.py`: matches emulator-dumped filenames (three regex patterns) to manifest rows, stamps `dump_hash`.

#### tex_forge/metadata
- `games.py`: hand-curated `KNOWN_GAMES` title-ID dict + `get_game_name` (games.py:36), shared by manifest and GUI.

#### tex_forge/gui
- `entry.py`: `main()` lazily imports PySide6 (friendly error if missing), launches `home_menu.main` (entry.py:21).
- `home_menu.py` (2121 lines): the current UI, a 3DS HOME Menu styled window; QThread workers `DiscoverWorker` (home_menu.py:225), `ScanWorker` (240), `BannerWorker` (252), `ExtractWorker` (275), `IconLoader` (314); game grid, queue model, settings dialog, activity log.
- `backend.py`: the GUI-to-core seam: `scan_rom` (backend.py:34), `run_extraction` (83), `get_rom_icon_rgba` (170), `get_rom_banner_rgba` (187), `get_output_previews` (204); never raises, returns result dicts.
- `config.py`: JSON settings persistence at `~/.3ds-texture-forge/config.json` (`load_config`/`save_config`, `DEFAULT_CONFIG` including `output_mode`, `new_folder_per_run`).
- `_gui_app_v1.py` / `_gui_entry_v1.py`: vendored v1 UI kept for reference; not importable as-is (see 1.5).
- `assets/`: bundled font.

#### tests/
15 test files, 93 test functions; `conftest.py` adds the repo root to `sys.path`. Groups: unit tests per layer (`test_morton`, `test_decoder`, `test_compression`, `test_crilayla`, `test_archives`, `test_cia`), pipeline end-to-end and smoke tests on synthetic ROMs (`test_pipeline_e2e`, `test_pipeline_smoke`, `test_pipeline_multicontent`, `test_extractor_fixes`), output/pack correctness (`test_azahar_output`, `test_batch_verify`), security (`test_path_traversal`, 24 tests), and GUI-adjacent loader/backend tests (`test_loader_gui`, `test_banner`).

### 1.2 Data flow diagram

```
 game.3ds / .cci / .cia / .cxi / .app / .ncch   (decrypted ROM file)
        |
        v
 rom/loader.py: parse_rom() [44] / iter_rom_contents() [73]
        |  _route() [164] picks by extension, then magic
        |--- .3ds/.cci --> NCSDParser.get_partition(0)        (rom/ncsd.py)
        |--- .cia -----> CIAParser.get_content/iter_contents  (rom/cia.py)
        |--- .cxi/.app -> raw NCCH
        v
 NCCHParser.get_romfs()  (rom/ncch.py; raises EncryptedROMError if NoCrypto clear)
        v
 RomFSParser(romfs_bytes)  (rom/romfs.py)  .list_files() -> [(path, off, size)]
        |
        v
 ExtractionPipeline.run() ----------------------------- (pipeline/extractor.py:166)
   for each ContentSource (main + CIA update/DLC contents):
   _process_content() [255]
        |
        |  FileFilter.should_peek(path, head, tail)      (pipeline/filter.py:81)
        |  FileFilter.is_definitely_not_texture(peek4)   (audio fast-skip)
        |  [special seams, pipeline/adapters.py:
        |    smash_virtual_entries()/decompress_smash_resource()  (dt/ls bank)
        |    .texturegdb -> parse_gdb1_pair_from_index() -> gdb1.parse_pair ]
        v
 extract_textures(data, path)  RECURSIVE, depth<=8 ----- (pipeline/scanner.py:118)
        |
        |  classify_file() [39]
        |     |-- detect_archive(data)  <== ARCHIVE REGISTRY (archives/registry.py:74)
        |     |-- detect_texture(data)  <== TEXTURE REGISTRY (textures/registry.py:63)
        |     |-- iter_codecs().detect  <== COMPRESSION REGISTRY (compression/registry.py)
        |     '-- extension fallback map [81]
        |
        |-- "compressed:<codec>" --> try_decompress(data, hint=codec) [registry.py:92]
        |        _has_texture_payload() fast-reject [scanner.py:107]
        |        '--> recurse extract_textures(decompressed, path+"[decompressed]")
        |
        |-- archive --> plugin.iter_entries(data) -> ArchiveEntry(name sanitised)
        |        '--> recurse extract_textures(entry.data, "path>entry")
        |
        |-- texture container --> plugin.iter_textures(data, path)
        |        (bch/cgfx/ctpk/bflim/... wrap _v1_* parsers, _dict_to_texture)
        |        '--> yields core.types.Texture (raw morton-tiled GPU bytes)
        |
        '-- scan_all only: _scan_embedded() [186] (CTPK/BCH/CGFX magic hunt)
        v
 _handle_texture()  ------------------------------------ (extractor.py:355)
        |  azahar_hash_hex(tex.data)   CityHash64 of raw GPU bytes
        |                              (textures/azahar_hash.py:102)
        |  Deduper.check_raw (xxhash64) --> duplicate record, skip decode
        v
 decode(data, w, h, fmt) ------------------- (textures/decoder/dispatch.py)
        |   pica_numpy.decode_numpy (Morton scatter maps from textures/morton.py,
        |   block-vectorised ETC1) with pica_python fallback  -> RGBA8 ndarray
        |  crop (BFLIM), BCH solid-colour/thin-strip filter [extractor.py:462-472]
        |  Deduper.check_content (md5 of RGBA)
        v
 compute_quality_metrics(rgba, fmt) ------- (quality/metrics.py)  QUALITY FILTER
        |  (suspicious flags counted; BCH false positives already rejected above)
        v
 _build_output_path() [540]
        |-- normal mode: generate_filename() + build_output_path()
        |     (output/filenames.py:31,53; traversal-checked, per-content subdir)
        '-- azahar mode: azahar_filename(W, H, CityHash64, fmt)
              "tex1_<W>x<H>_<HASH>_<code>_mip0.png" (azahar_hash.py:113)
        v
 save_png via ThreadPoolExecutor ---------- (output/png_writer.py, alpha remap)
 make_record -> manifest.json, failures.json, summary
 _write_outputs() [593]: write_manifest/write_failures/write_summary,
   write_quality_report (output/reports.py), generate_contact_sheet
        |
        v  (separate subcommand, later)
 tex-forge build-pack  (commands/build_pack.py)
   -> output/pack_builder.build_pack() [59]
      azahar mode: copies/links PNGs under load_pack/load/textures/<title_id>/
      with CityHash64 filenames + minimal pack.json [281] + forge_pack_meta.json
```

### 1.3 Entry points and GUI/core coupling

**CLI**: `tex_forge/cli.py` (`tex-forge` console script). `build_parser()` imports the seven `commands/*` modules and each contributes `add_subparser(sub)`; handlers are attached as `args._handler`. Commands call `_common.load_all_contents_or_die` then `ExtractionPipeline` with `CLIBarProgress` or `NullProgress`.

**GUI**: three equivalent launch paths converge on `tex_forge.gui.entry.main`: `Launch-Forge.bat`, `python -m tex_forge.gui.entry`, and the frozen `forge_gui.py`/`forge.spec` exe. `entry.main` launches `home_menu.HomeMenuWindow`.

**Library API**: documented in `tex_forge/__init__.py` and `extractor.py:9-19`: `parse_rom` + `ExtractionPipeline(ExtractOptions).run()`, plus `Texture`/`ArchiveEntry`/`PicaFormat` from their canonical modules. The root `__init__` intentionally re-exports nothing (docstring-only), so `from tex_forge import ExtractionPipeline` shown in extractor.py:11 does not actually work; you must import from `tex_forge.pipeline.extractor` (minor doc drift).

**GUI-to-core coupling**: clean and thin. The GUI never touches the pipeline directly; all core access goes through `gui/backend.py`, which builds `ExtractOptions`, wraps the pipeline's `ProgressCallback` in `CallableProgress`, and returns plain dicts (never raises). Threading is QThread-per-task in `home_menu.py`: `ExtractWorker` (home_menu.py:275) runs `backend.run_extraction` in `QThread.run`, forwarding the 4-arg progress callback into a `Signal(int, int, str, int)`; cancellation is a `threading.Event` handed down to `ExtractionPipeline.cancel_event` (cooperative, checked between files; `QThread.terminate()` deliberately never used, home_menu.py:282-285 and 1568). `ScanWorker`, `DiscoverWorker`, `IconLoader`, `BannerWorker` keep RomFS parsing and icon decoding off the UI thread. No queues; communication is Qt signals only. GUI-side business logic that lives outside the core: output-directory composition and per-run timestamping in `_output_dir_for` (home_menu.py:1880-1901, including its own Windows-reserved-name sanitizer `_WIN_RESERVED`, duplicating logic that also exists in `core/types.py:50`), ROM discovery caps, and config persistence. None of it bypasses the extraction core itself.

### 1.4 Registry system

Three structurally identical registries, one per plugin kind:
- `compression/registry.py`: `@register_compression(name, priority=, note=)` appends a `_Codec(name, priority, detect, decompress)` to module-global `_CODECS` and re-sorts descending by priority (registry.py:80-81). Dispatch: `try_decompress` (92) tries an optional `hint` codec first (by name, detect skipped), then walks `detect()` then `decompress()` in priority order, returning the first non-None as `Decompressed`.
- `archives/registry.py`: `@register_archive` appends to `_PLUGINS` (`_Registered(name, priority, plugin)`); `detect_archive` (74) returns the first plugin whose `detect(data)` is True, exceptions in detect swallowed.
- `textures/registry.py`: mirror image with `iter_textures(data, source_path)`; the docstring (16-20) explains why two registries exist: archive plugins emit more files (recursed), texture plugins emit decodable images.

Plugins are static-method classes matching a `Protocol` (`ArchivePlugin`, `TexturePlugin`); the decorator registers the class object itself, decoration is purely a registration side effect.

**Priority ordering** (descending; ties broken by import order since `list.sort` is stable):
- Archives: garc 100, sarc 95, narc 95, zar 90, gfac/gar/darc 85, capcom_arc 80, cpk 78, fe_arc 75, arc0 70, l5_flat 55. `smash_dt` intentionally unregistered.
- Compression: crilayla 95, yaz0 90, blz 80, lz11 70, lz10 65, lz13 60, gzip_prefix 50, zlib 40, level5 30 (specific magics high, one-byte heuristics low).
- Textures: ctpk/ctxb 92, cgfx 90, bflim/cmb/jimg 88, shinen_tex 86, capcom_tex 85, imgc 82, bch 80 (heuristic, deliberately below the magic-based formats), stex 70, gdb1 70.

**Where registration happens**: import side effects. `tex_forge/archives/__init__.py` and `tex_forge/compression/__init__.py` end with explicit `from ... import <plugin>  # noqa: F401` blocks; `tex_forge/textures/containers/__init__.py` does the same for the 12 texture plugins. Any `from tex_forge.archives.registry import ...` also executes the package `__init__`, so importing the registry module transitively registers everything. `pipeline/scanner.py` triggers all three chains via its top imports (scanner.py:20-24).

**Coupling risks**: (a) registries are mutable module-level globals with no unregister/reset, so test isolation and plugin overriding rely on process-wide state; (b) correctness depends on the package `__init__` import lists staying in sync with the plugin files, a silent failure mode acknowledged by the belt-and-braces import at scanner.py:23 and by forge.spec's `collect_submodules` note; (c) `try_decompress` may call `decompress()` on a codec whose `detect()` was never consulted (hint path), so codecs must be safe on arbitrary bytes.

### 1.5 Architectural observations and oddities

1. No circular imports found, and one is explicitly designed away: `textures/decoder/dispatch.py:8-11` exists solely to break a cycle between the two decoder backends and `textures/formats`.
2. Layering inversion, compression depends on textures: `compression/level5.py:22` imports `decompress_l5` from `tex_forge.textures.containers._v1_level5`. The compression layer depending on the textures layer is backwards (acknowledged in the docstring, level5.py:6-9); the decompressor should live in `compression/` with IMGC importing it.
3. Dead adapter seams: `pipeline/adapters.py` defines `unwrap_pokemon_container` (156), `parse_pokemon_pc_v5` (171), and `garc_should_suppress_bch` (241), and `archives/garc.py:92` defines `has_cgfx` "used by the pipeline's GARC adapter", but none of these has any call site in the repo. The GARC-BCH suppression and Pokemon PC handling documented in `pipeline/__init__.py:8-10` are currently not wired into `extractor.py` (which imports only the Smash and GDB1 adapters, extractor.py:48-53). This matters directly for the v2.5 Pokemon milestone (see section 6).
4. Docstring drift: `pipeline/__init__.py:12` lists `raw_heuristic.py` which does not exist (and `scanner.py:12` mentions "the raw heuristic" that is likewise absent, only `_scan_embedded` exists); `textures/__init__.py:10` lists `base.py TexturePlugin ABC` which does not exist (the Protocol lives in `registry.py`); `extractor.py:11` shows `from tex_forge import ExtractionPipeline` which the root `__init__` does not export.
5. Vendored v1 GUI is broken as packaged code: `_gui_app_v1.py:38-39` uses flat `from config import ...` / `from backend import ...`, and `_gui_entry_v1.py:5` uses `from gui_app import MainWindow`; these only worked in v1's flat layout. Harmless (reference-only per entry.py docstring) but they are 1941 lines of unreachable code shipped inside the package, and `forge.spec`'s `collect_submodules` will try to freeze them.
6. God modules on the GUI side: `home_menu.py` is 2121 lines (workers + widgets + queue model + settings dialog + theming in one file). Core-side, `extractor.py` at 633 lines is reasonable, but `_handle_texture` carries format-specific business logic (the BCH solid-color/thin-strip filter, extractor.py:462-472) that arguably belongs in the bch plugin or quality layer.
7. Duplicated Windows-filename sanitization: three independent implementations: `core/types.py:45-90`, `output/filenames.py`, and `home_menu.py` `_WIN_RESERVED`/`_output_dir_for` (1880). Drift risk.
8. Config globals: `gui/config.py` module-level `CONFIG_DIR`/`CONFIG_FILE` constants pinned to `Path.home()`; fine for a desktop app. The core has no config object, all knobs flow through `ExtractOptions`, which is clean. The registries (1.4) are the only true global mutable state in the core.
9. No core-imports-GUI violations: `tex_forge.gui` is imported only by `forge_gui.py` and within `gui/` itself; `metadata`, `rom.icon`, `rom.banner` were factored so the GUI-facing features live below the GUI. Dependency direction is consistently core, then rom/compression/archives/textures, then pipeline, then output, then commands/gui (with the single exception in point 2).
10. Two decode paths guaranteed consistent by construction: GUI icon/banner previews (`rom/icon.py`, `rom/banner.py`) deliberately route through the same `decode()`/plugin/codec stack as extraction, so preview and output can never disagree about Morton order or formats: a property worth preserving.

### 1.6 wii-gc-support branch status

The requested diff of the `wii-gc-support` branch's `platforms/gx/` additions against `main` could not be performed: the branch does not exist on the GitHub remote (only `main`, holding v1.1), and the local v2 tree is not under git. The Wii/GC work exists as a separate project, `C:\Users\Zagre\Desktop\wii-tex-extract`, structured as `src/{core,decoders,gui,parsers,workers}` with its own `disc_reader.py`, `filesystem.py`, `archive_walker.py`, and a GX decoder (`src/decoders/gx_decoder.py`, `cmpr.py`, `palette.py`). Integration risk assessment of that code as a future `platforms/gx` package appears in section 4.3 (security) and section 6 (roadmap). Headline risks: it duplicates the archive walking and output writing concerns that tex_forge already owns via registries, uses a different GUI shell, and its filename sanitization is weaker than `core/types.sanitise_archive_name`, so a merge should adopt tex_forge's registries and output layer rather than porting its own.

## 2. Format and pipeline correctness

### 2.1 Texture decode path

Entry point: `tex_forge/textures/decoder/dispatch.py:22` (`decode`). NumPy path is tried first for W,H >= 4 (`dispatch.py:34`), pure-Python is the fallback. Both emit (H, W, 4) uint8 RGBA.

**Swizzle model**
- 8x8 Morton tiles: `tex_forge/textures/morton.py:34` (`MORTON_TABLE`, bit interleave y0x0y1x1y2x2, matches citro3d/GBATEK). NumPy builds a whole-texture scatter map (`morton.py:59-85`) with tiles emitted row-major, dropping destination pixels outside W,H for non-tile-multiple sizes; the source stream is assumed to contain FULL padded tiles (correct for GPU data).
- ETC macro order: 4x4 blocks grouped into 2x2 macro-tiles, Z-order (0,0),(1,0),(0,1),(1,1), macros row-major: `morton.py:92-116` (numpy) and `pica_python.py:233-244` (python). The two implementations agree.

**Per-format decode (both paths, unless noted)**

| Format | ID | Decode | Where |
|---|---|---|---|
| RGBA8 | 0x0 | bytes stored A,B,G,R; reversed to RGBA | `pica_numpy.py:47-57`, `pica_python.py:36-40` |
| RGB8 | 0x1 | stored B,G,R; alpha forced 255 | `pica_numpy.py:60-70`, `pica_python.py:43-47` |
| RGBA5551 | 0x2 | LE u16, R@11 G@6 B@1 A@0; 5-to-8 via `(v<<3)\|(v>>2)`, A = a1*255 | `pica_numpy.py:73-86`, `pica_python.py:50-63` |
| RGB565 | 0x3 | LE u16; 6-bit G via `(g<<2)\|(g>>4)` | `pica_numpy.py:89-101`, `pica_python.py:66-78` |
| RGBA4 | 0x4 | LE u16, R@12 G@8 B@4 A@0; nibble replicate `(n<<4)\|n` | `pica_numpy.py:104-117`, `pica_python.py:81-89` |
| LA8 | 0x5 | byte0=A, byte1=L | `pica_numpy.py:120-131`, `pica_python.py:92-96` |
| HILO8 | 0x6 | byte0 to R, byte1 to G, B=A=255 | `pica_numpy.py:134-144`, `pica_python.py:99-102` |
| L8 | 0x7 | grayscale, A=255 | `pica_numpy.py:147-157` |
| A8 | 0x8 | RGB=255, A=byte | `pica_numpy.py:160-169` |
| LA4 | 0x9 | high nibble L, low nibble A, replicated | `pica_numpy.py:172-185`, `pica_python.py:118-124` |
| L4 / A4 | 0xA/0xB | 2 px/byte; EVEN Morton-sequential index = LOW nibble, odd = high; replicate | `pica_numpy.py:188-216`, `pica_python.py:145-166` (agree) |
| ETC1 | 0xC | 8-byte block read as LE u64, word1 = high 32 (colors/flags), word2 = low 32 (pixel indices); pixel j = px*4+py column-major, msb at bit j+16; standard modifier table; diff mode 5+3-bit with sign extend and clamp to 0..31 | `pica_numpy.py:229-354`, `pica_python.py:173-261` |
| ETC1A4 | 0xD | 16-byte block: first LE u64 = alpha (4 bits per pixel, nibble j at bits 4j, replicated to 8), second u64 = ETC1 color | `pica_numpy.py:357-374`, `pica_python.py:264-279` |

Aliases 0x14 = RGBA8, 0x19/0x1A = ETC1/ETC1A4 resolved in `tex_forge/textures/formats.py:82-102`.

**Fragile / divergent / suspect**

1. HILO8 channel order is likely swapped vs hardware. Both decoders map byte0 to R, byte1 to G (`pica_numpy.py:140-141`, `pica_python.py:102`). Citra/Azahar decode RG8 as r = byte1, g = byte0 (the same low-byte-first convention as LA8, which this codebase does honor at `pica_python.py:95`). Internally consistent between the two paths, so no numpy/python drift, but normal maps will have R and G exchanged (also B is filled with 255 where Citra uses 0; cosmetic). Does not affect hashing.
2. Truncated-input divergence between numpy and python paths. NumPy zero-pads the stream and decodes zeros (`pica_numpy.py:32-36`), python skips writes and leaves transparent black (`pica_python.py:313`). Observable differences on short data: A8 gives (255,255,255,0) in numpy vs (0,0,0,0) in python; HILO8 gives (0,0,255,255) vs (0,0,0,0); L8/RGB formats give opaque black vs transparent black; L4 gives (0,0,0,255) vs (0,0,0,0). ETC1: numpy decodes a zero block to (2,2,2,255) (modifier +2), python pre-fills alpha and breaks, leaving (0,0,0,255) (`pica_python.py:249-253`). Since which path runs depends on the numpy path not throwing, the same corrupt file can render differently across environments.
3. `decode_numpy` swallows every exception and returns None (`pica_numpy.py:413-416`), silently rerouting to the slow path. Real decoder bugs (bad reshape, index overflow) are indistinguishable from unsupported input; nothing is logged.
4. ETC tile-edge assumption is inconsistent with the 8x8 tile path. The Morton path assumes the stream contains full padded tiles; the ETC path assumes the stream contains ONLY visible blocks: invalid (bx,by) are removed from the order and consume no bytes (`morton.py:115-116`, `pica_python.py:243`). For an ETC texture whose block dimensions are odd (W or H congruent to 4 mod 8), GPU data is padded to full 2x2 macro-tiles, so the decoder will consume the wrong bytes for every block after the first skipped padding block. Same bug in both paths, so it is consistent but wrong. Related: `formats.py:130-134` (`encoded_size`) rounds ETC sizes to 4x4 blocks, not 8x8 macro-tiles, so BCH slices sized by it (`_v1_bch.py:401,427`) can under-read GPU padding for such dimensions (this also feeds the hash, see 2.2).
5. Mip levels are never decoded. `decode()` has no mip parameter; `mip_count` is metadata only (`pipeline/extractor.py:397,421,520`). Decoding mip0 from the head of the buffer is correct because 3DS stores mip0 first, and trailing mip bytes are ignored by the decoder. Correct for PNGs, but see the hash section.
6. The "W or H < 4 must use python" rule (`dispatch.py:28-30`, `pica_numpy.py:404-406`) is asserted, not derived; `scatter_map` actually handles any size. Harmless, but the two paths are not cross-tested: `tests/test_decoder.py` only checks zero-input round trips and one solid RGBA8 tile; there is no random-data parity test between `decode_numpy` and `decode_python`.
7. BFLIM format map bug: A4 mapped to A8. `_v1_bflim.py:31` maps BFLIM format 0x0D (A4) to PICA 0x08 (A8) with the comment "closest available", although PICA A4 = 0x0B exists and is fully implemented. Because the bpp then mismatches (8 declared vs 4 actual), an A4 BFLIM decodes to garbage covering only half the image. Note `_BFLIM_BPP[0x0D] = 4` (`_v1_bflim.py:41`) is right while the format map is wrong, so the storage-size verification will also disagree with the decode format.
8. BFLIM swizzle/orientation is read and discarded. `_v1_bflim.py:123` reads the swizzle byte (0 = none, 4 = 90-degree rotation, 8 = transpose in NW4C) but nothing rotates the output; rotated BFLIMs decode transposed/mirrored.
9. Rounding of component expansion (bit replication) is identical in both paths and matches common tooling; alpha 1-bit uses a1*255 in both. No drift there.

### 2.2 CityHash64 / Azahar hash pipeline

**What is hashed, and where.** The hash input is `tex.data`, whole and unsliced: `tex_forge/pipeline/extractor.py:385` (`azahar_h = azahar_hash_hex(tex.data)`). `tex.data` is whatever the container parser emitted (`core/types.py:168`), sliced by `textures/containers/_dict_to_texture.py:27-38`. Azahar/Citra with `use_new_hash=false` computes CityHash64 over the raw tiled bytes of one surface upload, i.e. exactly the mip-level's encoded byte range, nothing more. So Forge's hash matches only when `tex.data` is byte-exactly the mip0 upload.

**Silent mismatch inventory (every place the hash can be wrong without any error):**

1. Mip chains included in the hashed bytes.
   - CTPK: entry `data_size` (`_v1_ctpk.py:52,71`) is the total texture data size including all mip levels (mip_levels read at `_v1_ctpk.py:75`, `mip_count` propagated at `:102`). For any CTPK texture with mips, `tex.data` = mip0+mip1+..., so CityHash64(tex.data) != Azahar's mip0 hash. No warning is emitted; the pack file simply never matches in-game.
   - Shinen TEX: `data_size = len(data) - data_offset` (`_v1_shinen_tex.py:69`), includes mips (`mip_extra`, `:52,68`) and any trailing padding.
   - CGFX: TXOB `data_size` at +0x40 is trusted (`_v1_cgfx.py:75`) and `mip_count` is hardcoded 1 (`:113`); if the field covers the full mip chain the same mismatch occurs.
   - BCH is the one parser that is exact: it slices `calculate_texture_size(w,h,fmt)` = mip0 only (`_v1_bch.py:401,427,487,501`).
2. Trailing padding / over-long slices.
   - BFLIM: `pixel_data = data[0:footer_offset]` (`_v1_bflim.py:132`), i.e. the whole file body. If the body carries alignment padding beyond the storage-size surface, extra bytes are hashed.
   - `_dict_to_texture.py:33-36`: if `offset + size > len(source)` the fallback takes `source_data[offset:]` (a silently truncated buffer), and a parser that emits `data_size = 0` (the BCH heuristic fallback entries at `_v1_bch.py:643,831`) gets EVERYTHING from offset to EOF. Both decode fine (decoder reads only the leading bytes) but hash garbage. This is the worst class: the PNG looks perfect, the filename hash is silently wrong.
   - ETC textures with odd block dimensions: `encoded_size` under-counts GPU macro-tile padding (2.1 item 4), so even the exact BCH slice can be shorter than the real upload for W or H = 4 mod 8.
3. Width/height in the filename are post-crop, and the shipped PNG is cropped. The crop is applied and `tex.width/height` are overwritten (`extractor.py:456-459`) BEFORE `_build_output_path` composes `tex1_<W>x<H>_<hash>_<code>_mip0.png` (`extractor.py:488, 543-572`); `pack_builder.py:174` does the same from manifest dims. For a BFLIM with display 500x300 inside a 512x512 atlas, Azahar's surface is 512x512: the filename dims disagree with the dump name, and, more fatally, the PNG (500x300) is not an integer scale of the surface (512x512), which Citra/Azahar's custom-texture size check rejects. The hash itself (computed pre-crop over the full atlas) may be right while the PNG is still unusable.
4. Mip level is always 0. `azahar_filename(..., mip_level=0)` is never called with anything else (`azahar_hash.py:113-132`; call sites `extractor.py:557`, `pack_builder.py:174`). No `_mipN` variants are ever produced; benign for lookup fallback, but mip0 itself is wrong whenever item 1 applies.
5. Native vs fallback backend divergence. Backend selection at import time (`azahar_hash.py:35-44`) prefers any importable module named `cityhash`. The mainstream PyPI `cityhash` wraps CityHash v1.1, matching both the pure port and Citra's vendored `common/cityhash.cpp`; but any same-named module implementing a different variant would silently change every hash. There is no cross-backend test vector: the only self-check is `CityHash64(b"") == K2` (`_cityhash_pure.py:204-207`), and `tests/test_azahar_output.py` compares Forge against Forge, never against a known Citra dump hash.
6. Format-code map (`azahar_hash.py:57-80`) is correct against Azahar's `PixelFormat` enum (RGBA8=0 ... ETC1A4=13), including RGBA5551=2, LA8=5, HILO8=6, L8=7, LA4=9, L4=10. Two soft spots: (a) HILO8 is emitted as code 6 (RG8), fine; (b) a texture that reached the pipeline through the BFLIM A4-to-A8 remap (2.1 item 7) is filed under code 8 (A8) although the game uploads A4, so both the format code and the hash byte-length basis are wrong for that class.
7. Endianness: all CityHash fetches are explicit `<Q`/`<I` (`_cityhash_pure.py:34-39`), and the hex filename is produced with `f"{h:016X}"` (`azahar_hash.py:110`), matching the emulator's `%016llX` uppercase form. No issue.
8. Pack-side degradations (not hash-value errors but silent behavior changes): `_autodetect_mode` requires a CityHash backend at pack time even though hashes are already stored in the manifest (`pack_builder.py:298-299`), silently downgrading to mapped/staging; azahar-mode records lacking a hash or with an unsupported format are skipped with only counters (`pack_builder.py:160-177`); filename collisions are first-write-wins (`pack_builder.py:208-215`). `pack.json` correctly pins `use_new_hash: false` (`pack_builder.py:271-283`).

**Pure-Python CityHash64 verification** (`tex_forge/textures/_cityhash_pure.py`, checked line by line against canonical CityHash v1.1 `city.cc`):
- Constants k0/k1/k2 = 0xC3A5C85C97CB3127 / 0xB492B66FBE98F273 / 0x9AE16A3B2F90404F, kMul = 0x9DDFEA08EB382D69 (`:28-31`). Correct.
- `HashLen16` (both forms), `Rotate`, `ShiftMix`: correct; every right shift or rotate is pre-masked to 64 bits (`:42-60`), so Python big-int semantics cannot leak.
- `HashLen0to16` (`:63-86`), `HashLen17to32` (`:89-99`), `HashLen33to64` (`:125-143`), `WeakHashLen32WithSeeds` (`:102-122`): all match v1.1 exactly, including the bswap64 sites, the mul = k2 + len*2 rule, and the c-capture ordering (data-flow equivalent to the C++).
- Main loop (`:169-196`): seed setup, v/w seeds, `remaining = (length - 1) & ~63` while-loop reproducing the C++ do-while, z/x swap, final combine: all match.
- Input handling converts memoryview/bytearray to bytes (`:151-158`).

Conclusion: the fallback is a faithful CityHash64 v1.1 and agrees with the algorithm Citra/Azahar vendor. The realistic mismatch risks are entirely in what bytes get hashed (above), not the hash function.

### 2.3 Parser assumption inventory

Legend: V = VALIDATED (bounds/sanity checked), T = TRUSTED (used unchecked or only clamped after the fact). Python ints cannot overflow, so count*entry_size issues manifest as huge loops or misreads, not wraparound.

**ROM containers (`tex_forge/rom/`).** Shared helper: `core/binio.py` gives raise-on-OOB scalar reads (`:29-68`) and `safe_slice` which clamps and returns short/empty instead of raising (`:98-110`). Everything using `safe_slice` therefore degrades to silently short data on truncation.

| Parser | Assumption | Status |
|---|---|---|
| NCSD `rom/ncsd.py` | "NCSD" magic at 0x100 | V (`:52`) |
| | partition offset/size (media units) from table | T for value, reads clamped by `safe_slice` (`:75`); a lying header yields a short partition silently |
| | at least one nonzero partition | V (`:68`) |
| NCCH `rom/ncch.py` | "NCCH" magic at 0x100 | V (`:53`) |
| | crypto flag bit2 semantics (NoCrypto) | V logic (`:59-61`); raises EncryptedROMError before slicing |
| | RomFS/ExeFS offset*0x200, size*0x200 | T, clamped by `safe_slice` (`:87,93`); truncated ROM gives short RomFS with no error |
| CIA `rom/cia.py` | header section sizes chain to offsets via align_up | T (`:109-116`); a corrupt header_size relocates everything, later reads just clamp |
| | TMD signature type maps to header start | T with fallback assumption "RSA-2048" for unknown types (`:139-140`); wrong guess silently shifts the whole chunk table, then the count sanity check usually trips the single-content fallback |
| | content count and chunk table extent | V: count <= 0x10000 and `needed <= len(tmd)` (`:161`) |
| | per-chunk 64-bit size fields | T; offsets accumulate with align 64 (`:183`), get_content clamps `min(offset+size, len)` (`:219`), so oversized sizes give short blobs, never OOB |
| RomFS `rom/romfs.py` | IVFC magic | V (`:73`) |
| | Level 3 at 0x1000/2000/3000/4000, header_length==0x28 | heuristic V (`:98-103`), plus header-driven fallback (`:105-117`) |
| | dir/file meta offsets from L3 header | T (`:81-84`); per-entry reads are bounds-checked (`:134,174`) |
| | name_len <= 1024 | V (`:145,182`) |
| | 64-bit file data offset/size | T at parse time (`:178-179`); may point past EOF, `safe_slice` at read time returns short/empty bytes silently (`:68`) |
| | tree cycles | V, seen-sets for dirs and files (`:122-131,169-171`) |
| loader `rom/loader.py` | extension routing, magic fallback at 0x100, final "try CIA" probe (`:164-193`) | heuristic; encrypted signal preserved (`:101-102`) |

**Archives (`tex_forge/archives/`).** All plugins wrap iteration in try/except that logs and stops (e.g. `garc.py:116-120`), so a raise mid-archive silently truncates the entry list.

| Parser | Key assumptions | Status |
|---|---|---|
| GARC `garc.py` | magic+BOM (`:35,45`); count <= 100k (`:59`); per-entry `base+16 <= len` (`:66`); start/end within file (`:71-74`) | V |
| | FATB entries are exactly 16 bytes (single-subfile vector) (`:63-65`) | T. GARC v6 entries with multiple bits set in the vector carry 12 bytes per subfile; the fixed stride silently misparses every subsequent entry in such archives |
| SARC `sarc.py` | unknown BOM defaults to LE (`:41`) | T |
| | data_offset <= len (`:45`), SFAT/SFNT magic and header lengths (`:50-60`) | V, but `sfat_hdr_len`/`sfnt_hdr_len` values themselves are T |
| | node file_start/file_end | start > len skipped, end clamped (`:84-89`); `file_end < file_start` NOT checked, yields empty entries (filtered later by the scanner's len<4 rule) |
| darc `darc.py` | magic+BOM (`:31`), num_entries 1..100k (`:43`), per-entry bounds (`:60`), `w1 + w2 <= len` (`:74`) | V |
| | name table starts exactly at entry-table end (`:47`) | T; name scan walks to EOF per name worst-case (`:54-56`), bounded |
| ZAR `zar.py` | 100 MB archive cap, num_files <= 10k, table/data offsets < len (`:39-51`) | V |
| | files packed sequentially from data_offset, per-file `cursor + fsize <= len` (`:72-74`) | V; sequential-packing itself is T (a ZAR with gaps between files misslices everything after the first gap) |
| GAR `gar.py` | no table parse: sliding 4-byte scan for `ctxb`/`cmb ` with size at +4 bounded by remaining (`:31-47`) | heuristic by design; misaligned chunks missed; false positives possible |
| NARC `narc.py` | BTAF/BTNF/GMIF chain, fatb_size trusted to locate BTNF (`:49`) | T for size fields, V for section magics; per-entry slice bounds checked (`:60-63`) |
| GFAC `gfac.py` | entry_count <= 10k (`:74`); entry bounds (`:79`); data_off < len (`:97`) | V |
| | GFCP decomp_size trusted to synthesize an LZ header (`:46-59`) | T but capped by lz MAX_DECOMP 50 MB downstream |
| | uncompressed entry size = min(decomp_size, next entry offset, EOF) (`:104-112`) | V-ish heuristic, assumes entries sorted by offset |
| Capcom ARC `arc_capcom.py` | num_entries u16 (`:86-88`); `data_offset + csize <= len` (`:55,70,120`) | V |
| | self vs prev size-field layout autodetected on first TEX entry, applied uniformly (`:47-79,105-106`) | T assumption that the layout is uniform per archive |
| | `zlib.decompress(raw)` with no output cap (`:58,73,125`) | T: a crafted entry is a decompression bomb; same pattern in `smash_dt.py:66` and `zlib_helpers.py:41,61` |
| FE ARC `arc_fe.py` | file_size field must equal actual size (`:32`), 1..64 entries (`:39`), LZ type byte probe at 0x20/0x24 (`:36`) | V (good detect discipline) |
| | entries found by probing every 4-byte offset with the LZ decoder (`:49-54`) | heuristic; cost bounded by 64-entry cap |
| L5 flat `l5_flat.py` | count 10..200k, pad word zero, table fits, first offset sane (`:28-40`) | V |
| | offsets ascending (size = next - this) (`:57-60`) | T; unsorted table gives negative sizes which are skipped silently |
| ARC0/XFSA `arc0.py` | no real table decode; magic carving of BCH/CGFX/CTPK/IMGC with per-magic size guesses and caps (`:67-101`), plus XPCK LZ10 probing (`:115-144`) | heuristic by design; header_size/data_offset T with fallback (`:108-111`) |
| CPK `cpk.py` + `_cpk_v1.py` | @UTF magic and table_size (clamped to EOF, `:90-96`); per-value reads return 0/"" past EOF instead of raising (`:160-184`) | V-lite: corrupt tables produce zero-filled rows silently |
| | TocOffset/ContentOffset trusted; FileOffset base ambiguity resolved by try-content-then-toc fallback (`:423,468-475`) | T with fallback |
| | CRILAYLA decompression: wrong algorithm (see below), plus grouped-entry prefix probing (`:275-308`) and preceding-stream search (`:328-372`) which can attach the WRONG decompressed container to an entry name silently | T/heuristic |
| Smash dt/ls `smash_dt.py` | ls magic, count <= 100k, 12-byte entries bounds-checked (`:39-52`) | V |
| | dt resource: scan first 512 bytes for a zlib header, decompress unbounded (`:55-69`) | T (bomb risk), failures return b"" silently |

**Compression (`tex_forge/compression/`).**

| Codec | Assumptions | Status |
|---|---|---|
| LZ10/11/13 `lz_nintendo.py` | 24-bit (or extended 32-bit) size header, capped 50 MB (`:45-58`) | V: output preallocated at declared size, cap prevents huge allocation |
| | backref `ref >= 0` checked (`:99,187`); truncated stream returns None (`:111,195`) | V |
| | detect() requires expansion ratio 0.5..20 (`:73`) | T heuristic: valid streams compressing better than 20x are silently never decompressed |
| | LZ13 fallback: reinterpret payload reversed as LZ11 (`:208-221`) | T heuristic |
| BLZ `blz.py` | footer plausibility, size cap, expansion <= 5x (`:46-61`); dst/rp bounds checked (`:100-113`), final `dst == uncomp_len` check (`:118`) | V |
| Yaz0 `yaz0.py` | magic + BE size, cap (`:40-49`) | V |
| | truncated stream returns PARTIAL output as success (`:86` returns `out` even when `len(out) < decomp_size`) | T: silent truncation propagates downstream |
| | negative back-reference writes 0 instead of failing (`:81`) | T: corrupt data decodes to silently wrong bytes |
| CRILAYLA `crilayla.py` and `_cpk_v1.py:189-245` | The algorithm does not match CRILAYLA at all. Canonical CRILAYLA (CriFsV2Lib, cpktools, both cited in the module docstrings) is a backward BIT stream: 1 flag bit, 13-bit offsets, variable-length lengths in 2/3/5/8-bit chunks, minimum length 3, plus an exactly 0x100-byte uncompressed header stored after the body, output = header + body. This implementation uses byte-aligned flag bytes with 2-byte backrefs, length `(hi>>3)+3`, 11-bit distance (`crilayla.py:60-80`), and treats everything after the body as a variable-length prefix (`:51-52`). Real CPK CRILAYLA data will decompress to garbage; the downstream container-magic checks then reject it, so all CRILAYLA-compressed textures in CPK games (Persona Q, 7th Dragon, etc.) are silently lost. `tests/test_crilayla.py` only round-trips streams built in the same invented format (`tests/test_crilayla.py:24-38`), so the suite cannot catch this. Highest-severity finding in the compression layer. | broken vs spec |
| Level-5 `level5.py`, `_v1_level5.py` | method/size plausibility in detect (`level5.py:24-42`) | V |
| | LZ10 variant accepts half-decompressed output as success: `return ... if len(out) >= dec_size // 2 else None` (`_v1_level5.py:94`) | T: silently truncated payloads flow onward |
| | Huffman child pointer: `child_base = (aligned) + child_rel + 2` (`_v1_level5.py:143`); the standard Nintendo/Level-5 Huffman formula is `(addr & ~1) + offset*2 + 2` (offset counted in node PAIRS). The missing *2 means any tree whose child offset is nonzero walks the wrong nodes; only trivial trees decode correctly. Suspect bug, silently produces wrong bytes | broken vs spec (likely) |
| | `read_bit` past EOF returns 0 forever (`_v1_level5.py:121-131`) | T: truncated stream pads with fabricated symbols |
| zlib/gzip `zlib_helpers.py` | magic pairs only (`:29,54`); `zlib.decompress`/`gzip.decompress` with no output limit (`:41,61`); the 4-byte size prefix in gzip_prefix is never compared to the result | T: decompression-bomb allocation; declared size unused as a sanity check |
| registry `registry.py` | first codec whose detect+decompress succeeds wins (`:107-112`); a false-positive detect that "successfully" produces garbage (e.g. the CRILAYLA byte-decoder, priority 95, above every LZ codec) shadows correct codecs | structural T |

**Texture containers (hash-relevant slicing recap)**
- CTPK: dims validated (<=2048), format <= 0xD, count <= 10k (`_v1_ctpk.py:45,86-91`); `data_offset` and `data_size` T (bounds only enforced later by `_dict_to_texture.py:31`, whose fallbacks are the silent-truncation/EOF-slice hazards in 2.2).
- CGFX: TXOB found by raw `find(b'TXOB')` scan (`_v1_cgfx.py:51`), dims must be pow2 4..2048 (`:69-72`), `data_offset + data_size <= len` V (`:86`).
- CTXB/CMB: `actual_length` clamped to available bytes (`_v1_ctxb.py:103-118`, `_v1_cmb.py:108-125`) V.
- BFLIM: storage-vs-display size resolution tries storage then display then "storage anyway" (`_v1_bflim.py:151-162`) T; footer `imag` search fallback scans the file (`:97-102`).
- BCH: heuristic GPU-command parsing; slices exactly mip0 size, offset fallback raw-vs-relative (`_v1_bch.py:405-414`) T heuristic; solid-color/thin-strip post-filters in the pipeline (`extractor.py:461-472`) mitigate false positives.

### 2.4 Top correctness findings by severity

1. CRILAYLA decompressor implements a different algorithm than CRILAYLA (`compression/crilayla.py:60-80`, `archives/_cpk_v1.py:222-245`); all compressed CPK content is silently lost; tests are self-referential.
2. Azahar hash is computed over the full parser payload, not the mip0 surface bytes: guaranteed wrong for CTPK/Shinen textures with mips, at risk for CGFX and BFLIM padding, and definitively wrong for the `_dict_to_texture` size-0/truncation fallbacks. All failures are silent: the PNG decodes fine, the filename hash just never matches in the emulator.
3. Cropped BFLIM output uses post-crop dims in the Azahar filename and ships a non-proportional PNG (`extractor.py:456-459` before `:488`), which the emulator rejects.
4. BFLIM A4 mapped to A8 (`_v1_bflim.py:31`) despite native A4 support: garbage decode plus wrong Azahar format code.
5. Level-5 Huffman child-offset math likely missing the *2 (`_v1_level5.py:143`) and LZ10 half-output acceptance (`:94`); Yaz0 partial-output acceptance (`yaz0.py:86`).
6. HILO8 R/G order swapped vs Citra's RG8 decode; consistent across both paths, output-only.
7. numpy/python decoder divergence on truncated input (zero-pad vs skip) and the blanket exception swallow in `pica_numpy.py:413-416`; no parity tests.
8. GARC fixed 16-byte FATB entry stride breaks on multi-subfile v6 vectors (`garc.py:63-65`); unbounded zlib/gzip decompression in `arc_capcom.py:125`, `smash_dt.py:66`, `zlib_helpers.py:41,61`.
9. The pure-Python CityHash64 is verified correct against CityHash v1.1; the only backend risk is an off-brand module shadowing the `cityhash` import name, uncovered by any test vector beyond the empty string.

## 3. Quality audit

### 3.1 Test coverage

Suite run: 106 passed, 0 failed, 0.34s (`python -m pytest tests/ -q`, Python 3.14). The brief's "70 tests" is stale; the tree now has 15 test files (17 counting `__init__.py`/`conftest.py`) and 106 test functions. coverage.py / pytest-cov are NOT installed, so per-line coverage numbers are unavailable; the mapping below is derived by hand from what each test imports and exercises.

What the tests cover, by file:

| Test file | Tests | Covers |
|---|---|---|
| test_archives.py | 4 | `detect_archive` magic detection (garc, sarc), no-match None, priority ordering. Detection only, not extraction |
| test_compression.py | 5 | LZ10/LZ11 literal + one backref, `try_decompress` dispatch, unknown None. Docstring claims Yaz0 but no Yaz0 test exists |
| test_crilayla.py | 5 | crilayla round-trip on hand-built all-literal streams (in the invented format, so cannot catch the spec mismatch in 2.3) |
| test_morton.py | 5 | Morton table vs bit-interleave, INV tables, etc1 block order, scatter_map |
| test_decoder.py | 5 | `decode` for all 14 PICA formats on zero/solid input, ETC1/ETC1A4 alpha, sub-4 python fallback. Shape/dtype, minimal pixel checks |
| test_banner.py | 5 | `parse_cbmd` on hand-built CBMD, `decode_banner_cgfx` via the registry seam |
| test_cia.py | 5 | CIA multi-content chunk-record walk, alignment, type flags, index bounds |
| test_loader_gui.py | 7 | `iter_rom_contents` preserving EncryptedROMError; `backend.scan_rom` count summing, `run_extraction` forwarding (pipeline stubbed) |
| test_pipeline_smoke.py | 3 | `classify_file` magics, graceful unknown/scan-all handling |
| test_pipeline_e2e.py | 6 | Decoder to save_png to quality, manifest writers, quality report, build_pack staging, imgc + crilayla registration |
| test_pipeline_multicontent.py | 3 | `run` over primary + extra contents, shared counter/deduper, per-content manifest tagging (RomFS/extract stubbed) |
| test_extractor_fixes.py | 5 | Regression: normal-mode filename collisions, dump_raw pathing, list_only, cancel_event, FileFilter tail peek |
| test_azahar_output.py | 4 | Azahar filename shape, CityHash64 (not xxhash) naming parity extract vs build-pack, pack.json pins use_new_hash=false |
| test_batch_verify.py | 7 | `batch` discovery, continue-on-error, dup-title skip, exit codes; `verify_project` clean/collision/missing/orphan |
| test_path_traversal.py | 24 | Path-traversal property tests: name sanitiser, filenames, pack_builder, png_writer cannot escape output_dir. Largest, most rigorous file |

Ranked untested critical paths (risk = P(corrupt real-world input) x blast radius):
1. Container parsers `textures/containers/*.py` (3800 lines) have essentially no direct tests. Only BCH/RGBA8 is touched indirectly via pipeline e2e; CTPK, BFLIM, CGFX, CMB, CTXB, GDB1, JIMG, Level5-IMGC, Shinen-TEX, STEX, TEX-Capcom are unexercised on real-shaped headers. These are the primary consumers of untrusted game data and, per 3.3, are NOT wrapped defensively, so a parser bug aborts the whole content extraction. Highest risk.
2. Archive extraction bodies (`archives/*.py`, 1904 lines). Tests cover only magic detection for 2 of 13 formats. The `iter_entries` decompress-and-yield paths are untested against corrupt entries.
3. Compression codecs beyond LZ10/LZ11/CRILAYLA. Yaz0, BLZ, the Level-5 LZSS/Huffman/RLE, and zlib helpers have zero round-trip tests. Yaz0 is falsely advertised as covered. (Note: the Level-5 Huffman path is both the performance bottleneck in section 5 and a suspected correctness bug in 2.3, and it has no test.)
4. The two decoder paths are never differentially tested. test_decoder asserts shape/dtype on zero input only; it never compares `pica_numpy` vs `pica_python` on the same bytes, so the truncation drift in 2.1 is invisible.
5. ROM container chain NCCH/NCSD/ROMFS/ICON. Only CIA and banner are tested; crypto checks and lv3 offset heuristics are untested against malformed headers.
6. RomFS-driven extractor internals with a real RomFS. Every pipeline test stubs `RomFSParser`/`extract_textures`, so file-index reading and the numpy/python decode dispatch never run end to end on bytes.
7. GUI (4372 lines) is only touched via `backend.py` wiring; `home_menu.py` (2121 lines) and worker threads are untested (lower blast radius).
8. Lowest: `quality/metrics.py`, `output/contact_sheet.py`, `metadata/games.py` (thin, partly exercised by e2e).

### 3.2 Error handling

127 except clauses in package code. 0 bare `except:`, 0 `except BaseException`. 80 broad `except Exception` (39 fully silent), 47 narrow (~11 silent). All 80 broad catches also swallow MemoryError and programming errors (AttributeError/TypeError/IndexError).

Smells (hide real bugs):

| Location | Catches | What it hides |
|---|---|---|
| `pipeline/extractor.py:213` (+ `:493-495,502-506`) | `Exception: pass` in the async writer drain | `save_png`/`_write_raw` future bools are never checked; `rel_png` is recorded before the write is known to succeed. A failed PNG write still lands in manifest.json with a `decoded_png_path` that does not exist, counted as decoded_ok. Highest-value fix |
| `textures/containers/_v1_level5.py:92,172,199` | `Exception: pass` in LZSS/Huffman/RLE | Each returns `out[:dec_size] if len(out) >= dec_size//2 else None`: half-size output accepted as success, truncated pixel data flows downstream as a valid texture |
| `gui/home_menu.py:235` | `Exception` to `([], False)` | A bug in `discover_roms` shows zero ROMs with no message and no log |
| `gui/config.py:59` | `Exception: pass` in `save_config` | User settings silently never persist |
| `gui/_gui_app_v1.py:496` | `Exception: pass` in `_save_history` | History silently not saved (legacy, but bundled into the exe) |
| `pipeline/progress.py:46` | `Exception: pass` in CallableProgress | Broken progress callback freezes the UI at 0% with zero diagnostics |
| `archives/arc_capcom.py:126` | `Exception` to `continue` | Corrupt/compressed entry silently dropped, no counter, no debug log |
| `gui/home_menu.py:1528` | `OSError: pass` opening output folder | User action silently no-ops |
| `gui/config.py:49`; `gui/_gui_app_v1.py:487` | `Exception: pass` in load/history | Defaults fallback reasonable but silent and broad enough to hide bugs |

Borderline (logged/visible but overly broad): `extractor.py:625,632` (quality report / contact sheet), `output/pack_builder.py:220` (shutil.copy2 with no copy-failure counter, so a pack missing files still reports success), `extractor.py:314` (read_file_by_index).

Justified (grouped): archive `iter_entries` boundary wrappers (broad catch + warning, one bad archive must not kill the scan); plugin `detect()` probe loops; format/container probing (failure = not this format); compression codecs returning None per contract with debug logging; domain exceptions with user-facing messages (`_common`, `batch`, `verify`, `import_dump`, `backend`, `banner`, `icon`, `loader`); optional-dependency imports (xxhash, cityhash, numpy, Pillow, PySide6); UI boundaries that surface to the user; numpy fast-path fallback to the python decoder.

Dead defensive code (unreachable, `.decode('ascii', errors='replace')` cannot raise): `_cpk_v1.py:156`, `_v1_bch.py:220,238`, `_v1_cgfx.py:100`, `_v1_cmb.py:97`, `_v1_ctxb.py:89`, `_v1_stex.py:91`.

### 3.3 Dead code and duplication

Dead code:
- High impact, lost functionality: three pipeline adapters are defined and advertised in the `adapters.py:12-17` docstring but never wired in: `unwrap_pokemon_container` (`adapters.py:156`), `parse_pokemon_pc_v5` (`adapters.py:171`), `garc_should_suppress_bch` (`adapters.py:241`). `extractor.py:48-52` imports only four other names. Transitively dead: `archives/garc.py:92 has_cgfx`. This is a direct v2.5 Pokemon blocker (section 6).
- Broken Capcom profile threading: `scanner.py:118-171` accepts `title_id` but never passes it to any texture plugin; `tex_capcom.py:31` hardcodes `title_id=""`, so `_get_profile` always returns None and the RER/MH4U profile path (`_v1_tex_capcom.py:285-290`) is dead in practice.
- Truly dead modules: `gui/_gui_app_v1.py` (1924 lines, no imports), `gui/_gui_entry_v1.py` (17 lines, broken import at line 5). Both still bundled into the exe via `forge.spec:19 collect_submodules`.
- Dead functions/classes: `parse_capcom_tex`/`scan_capcom_textures` (`_v1_tex_capcom.py:996,1015`); `is_cgfx` in `_v1_bch.py:60` (duplicate of the live one in `_v1_cgfx.py:31`); `DecodeError`/`CompressionError` (`core/exceptions.py:24,33`, never raised); `read_i32_le` (`binio.py:65`); `get_logger` (`logging.py:43`); `decompress_by_name` (`registry.py:117`); dead exports in `_compat_decoder.py`. All verified zero-reference by grep.
- Unreachable branches: per-pixel OOB fallbacks in `pica_python.py:37-38,113-114` cannot fire because `decode_python` already guards at :313.

Duplication / drift:
- Two live LZ10 decompressors that disagree: strict `lz_nintendo.py:76-111` (None unless fully decompressed) vs lenient `_v1_level5.py:63-95` (accepts half output, treats bad backrefs as zero bytes). Same input can succeed with garbage on one path and fail cleanly on the other.
- Two live CRILAYLA decompressors: `compression/crilayla.py:42-86` vs `archives/_cpk_v1.py:189-247`, near-identical; a fix to one misses the other (both implement the wrong algorithm per 2.3).
- Level-5 method-byte header parsed in three places with cap drift: `_v1_level5.py:44-47` (32 MB), `compression/level5.py:33-42` (32 MB), `arc0.py:41-64` (16 MB, different LZ10 backend).
- Decoder truncation drift (see 2.1): numpy zero-pads, python skips; same corrupt texture decodes differently by path.
- Zlib magic scan duplicated: `adapters.py:101-108` re-declares constants/scan already present in `smash_dt.py`.
- binio bypassed wholesale: `binio.py:1-3` says all byte-poking should import from it, but no `archives/*.py` module does (all use raw `struct.unpack_from`, raising `struct.error` masked only by the blanket except). `banner.py:56-57` defines a local `_u32` despite importing from core elsewhere.
- Morton is clean (single table); mild hazard: `_iter_etc_blocks` restates the etc1 block order if either is edited alone.

Inconsistent conventions:
- Archive parsers: convention is generator-returns-early + `iter_entries` wrapping in `except Exception` + warning. Deviations: `cpk.py:52-53` guards inside `_iter`; `smash_dt.py` is not a plugin and returns `[]`/`b""`.
- Texture container parsers: convention is return `[]`/`None`, never raise, but they are NOT defensively wrapped. Key asymmetry: archive plugins are wrapped, texture plugins are not (`scanner.py:177`, `extractor.py:326-331` catch nothing), so any uncaught error in a container parser aborts the whole content extraction while the same class of bug in an archive plugin is logged and skipped.
- Compression codecs: fully consistent, all return `Optional[bytes]`, None on failure; the documented `CompressionError` escape hatch is never used.

### 3.4 Type hints

mypy is NOT installed; this is a manual + AST-scripted pass. Fully annotated means return annotation plus all non-self/cls params annotated.

| Package | Funcs | Fully annotated | Percent |
|---|---|---|---|
| core | 19 | 18 | 95% |
| rom | 40 | 35 | 88% |
| compression | 38 | 35 | 92% |
| archives | 65 | 64 | 98% |
| textures (top) | 34 | 33 | 97% |
| textures/containers | 27 | 27 | 100% |
| textures/decoder | 36 | 24 | 67% |
| pipeline | 30 | 29 | 97% |
| output | 20 | 18 | 90% |
| gui | 130 | 23 | 18% |
| commands | 23 | 22 | 96% |
| quality | 2 | 2 | 100% |
| metadata | 1 | 1 | 100% |
| cli.py | 2 | 1 | 50% |
| Total non-legacy | 467 | 332 | 71% |
| Legacy `_v1_*` | 166 | 72 | 43% |

Debt is concentrated in `gui/home_menu.py` (121 funcs, 15%) and the decoder `_px_*` helper family; the parsing/pipeline core is essentially fully annotated. The bytes-receiving-memoryview/None and hidden-None classes came up essentially empty in non-legacy code (every codec/`Texture.data` input is `bytes(...)`-wrapped; the AST scan found zero hidden-None returns; no annotation references an unresolvable name). The real debt is Optional/Callable contracts kept in docstrings instead of signatures:
- `rom/loader.py:164` `_route` no return annotation; the None case is load-bearing for `icon.py:84`, `banner.py:119`.
- `rom/banner.py:82,112`, `rom/icon.py:72`, `rom/banner.py:73`: Optional ndarray / Iterator[Texture] promised in docstrings, not signatures.
- `gui/backend.py:170,187` Optional ndarray unannotated; `gui/backend.py:83` `run_extraction` bare `Callable` erases the 4-arg `Callable[[int,int,str,int],None]` that `progress.py:41` declares; `cancel_event` unannotated.
- `pipeline/extractor.py:176` `png_futures: list` bare (holds `Future[bool]`); `pipeline/adapters.py:128` read_file_by_index callback unannotated.
- Decoder: `pica_numpy.py:251` return missing; the twelve `pica_python.py:36-124 _px_*` decoders and `_iter_etc_blocks` missing returns; `pica_python.py:183` `-> list` degenerate.
- `compression/blz.py:36` `_peek_footer` missing `-> Optional[Tuple...]`; `compression/registry.py:87` `iter_codecs` missing `-> Iterator[_Codec]`; the three register decorators typed `-> Callable` erase the class-in/class-out plugin contract.
- The one genuine default-None lie: `gui/_gui_app_v1.py:438` `set_value(..., color: str = None)` declares `str` with a None default (legacy; should be `Optional[str]`). Only such hit across all 110 files.

## 4. Security posture

Every finding is classified CONFIRMED (data flow traced statically) or POTENTIAL (needs runtime confirmation).

### 4.1 Path traversal re-verification (3ds-tex-extract)

**Sanitization architecture.** Two independent defensive layers exist, and both are real:
- Layer 1, at the source: `ArchiveEntry.__post_init__` runs `sanitise_archive_name` on every inner archive entry name (`tex_forge/core/types.py:142-145`). That function drops `..`/`.`/empty segments, normalizes `\` to `/`, strips leading `/`, removes null bytes and control chars (< 0x20, 0x7F), replaces the Windows-invalid set `<>:"|?*` with `_`, and neutralizes Windows reserved device names (CON, NUL, LPT1, etc.) by trailing underscore (`tex_forge/core/types.py:45-119`). Confirmed applied by all archive plugins (arc0, arc_capcom, arc_fe, cpk, darc, gar, garc, gfac, l5_flat, narc, sarc, zar all emit via `ArchiveEntry(...)`).
- Layer 2, at the sink: `build_output_path` re-drops traversal segments AND performs a realpath + `os.path.commonpath` boundary check against `output_dir`, raising `ValueError` on escape, with explicit Windows handling for cross-drive `commonpath` errors and `\\?\` long-path prefixes (`tex_forge/output/filenames.py:53-104`).

**Per-sink verdicts**

| Sink | File:line | Verdict | Notes |
|---|---|---|---|
| Normal extract PNG path | `pipeline/extractor.py:578-589` into `output/filenames.py:53-104` | HOLDS (CONFIRMED) | `generate_filename` alnum-filters the texture name (`filenames.py:42-44`); final path goes through the `build_output_path` commonpath guard. `source_content` namespace is alnum-filtered (`extractor.py:586`). |
| Azahar pack output (extract `--output-mode azahar`) | `pipeline/extractor.py:543-572` | HOLDS (CONFIRMED) | Filename is either `azahar_filename` (fully int/hex-formatted, `azahar_hash.py:132`) or `UNRESOLVED_{tex_id}_{w}x{h}.png` where `tex_id` = `tex_NNNN`. No attacker string reaches the name. |
| dump-raw mode | `pipeline/extractor.py:499-506`, `_write_raw` at `:65-74` | HOLDS (CONFIRMED) | `raw_name = f"{tex_id}_{w}x{h}_{fmt}.bin"`; all components are internal. Written under `output_dir/raw/`. |
| Manifest / failures / summary writers | `output/manifest.py:118-147` | HOLDS (CONFIRMED) | Fixed filenames joined to `output_dir`. `rom_file` passes through `os.path.basename` (`manifest.py:110`). |
| Contact sheet output | `output/contact_sheet.py:119-121` | HOLDS (CONFIRMED) | Fixed default filename `contact_sheet.png`. |
| Contact sheet input read | `output/contact_sheet.py:42-43` | PARTIAL (POTENTIAL) | Reads `decoded_png_path` from records; absolute paths are honored and there is no commonpath guard. In-pipeline records are trusted, but run against a hand-tampered `manifest.json` this is an arbitrary-file read (Image.open), not a write. Low severity. |
| Pack builder source PNG (build-pack) | `output/pack_builder.py:114-148` | HOLDS (CONFIRMED) | `decoded_png_path` from the manifest is realpath+commonpath-checked against project dir and against `upscaled_dir`; escape raises `IOError`. This is the F048 fix, enforced on both the original and upscaled trees. |
| Pack builder destination filename | `output/pack_builder.py:186,217-219` | PARTIAL (CONFIRMED gap) | azahar mode dest name is hash/int-built (safe). staging mode uses `_safe_filename` (alnum+`_-` filtered, `pack_builder.py:325-333`, safe). But mapped mode builds `dest_name = f"{dump_hash}.png"` directly from the manifest `dump_hash` field with no re-validation, then `shutil.copy2(src_png, os.path.join(pack_dir, dest_name))`. `import-dump` only ever writes hex-validated hashes (`import_dump.py:135-142`), so the normal flow is safe, but a hand-edited manifest with `dump_hash: "../../evil"` would write outside `pack_dir`. The source side has an F048 guard; the dest side does not. Apply the same commonpath check to `dest_path`. |
| import-dump manifest rewrite | `commands/import_dump.py:86-87,96-98` | HOLDS (CONFIRMED) | Writes fixed filenames into `project_dir`. Dump filenames are parsed, not used as output paths. |
| GUI azahar copy (legacy v1 file) | `gui/_gui_app_v1.py:1821-1838` | POTENTIAL | Legacy v1 GUI copies files by `os.path.join(tex_dir, f)` from a listing of the tool's own output. Not reachable in the normal flow (file is unreferenced), lacks the layer-2 guard. Low priority. |

**RomFS / adapter name flow.** RomFS directory and file names are UTF-16LE decoded with `errors="replace"` and a `name_len > 1024` cap (`rom/romfs.py:145-147,182-184`). These paths become `source_file` breadcrumbs, consumed only by `build_output_path` (guarded) and `sanitise_subdir` (drops `..`). CONFIRMED safe for the write sinks. Note: RomFS names are NOT run through `sanitise_archive_name` (only ArchiveEntry names are); the sink guard is what protects RomFS-derived paths. Defense-in-depth-by-one-layer rather than two: a RomFS directory literally named `NUL` is only neutralized when it flows through an ArchiveEntry. POTENTIAL minor Windows-only write failure, not a traversal escape.

**Archive-entry-to-disk.** No mode writes raw archive entries to disk by their entry name. Entries are recursively re-scanned in memory (`pipeline/scanner.py:163-173`); only decoded textures and internally named raw GPU blobs are written. CONFIRMED.

**Regression coverage.** `tests/test_path_traversal.py` asserts the actual property (result under output_dir via commonpath), covering F028/F030/F031/F048, reserved names, null bytes, backslashes, and deep `../` chains. The mapped-mode dest-side gap above is not covered by these tests.

### 4.2 Other attack surface (3ds-tex-extract)

- Unsafe deserialization: none. No `pickle`, `eval`, `exec`, `yaml`, or `marshal` on untrusted data. All persisted state is JSON via `json.load`/`json.dump`. The `.exec()` hits are Qt event loops (`gui/home_menu.py:1501,1771,2117`), not code execution. CONFIRMED clean.
- Subprocess: only in the GUI, opening the output folder: `subprocess.Popen(["open", job.output_dir])` / `["xdg-open", ...]` (`gui/home_menu.py:1524,1527`). Argument-list form, no `shell=True` anywhere in the tree, and `output_dir` is user-selected, not ROM-derived. CONFIRMED low risk.
- Temp files: none in the extraction core (no `tempfile`/`mktemp` usage in `tex_forge/`). CONFIRMED not applicable.
- Decompression bombs: codecs cap decompressed size before allocating: BLZ 50 MB (`compression/blz.py:33,58,77`), CRILAYLA 64 MB (`crilayla.py:35,48`), Level5 32 MB (`level5.py:21,39`), LZ Nintendo 50 MB (`lz_nintendo.py:42,56`), Yaz0 50 MB (`yaz0.py:36,47`). CONFIRMED mitigated. Exception: bare `zlib.decompress` / `gzip.decompress` in `compression/zlib_helpers.py:41,61` and `archives/smash_dt.py:66` have no output cap. Smash use is bounded upstream (`pipeline/adapters.py:73`, `archives/smash_dt.py:44`), but the generic `_Zlib`/`_GzipPrefix` codecs invoked during scanning are not. POTENTIAL memory amplification from a small crafted zlib stream.
- Recursion depth: archive/compression recursion capped at depth 8 (`pipeline/scanner.py:136-138`), with cycle guards in the RomFS walker (`rom/romfs.py:122-131,169-171`). CONFIRMED mitigated.
- Unbounded count/dimension fields: texture dimensions are capped (2048 or 4096) in every container parser, and `decoder/dispatch.py:31` rejects non-positive dims. Count fields are bounded. Reads are bounds-checked in `core/binio.py`. CONFIRMED generally mitigated; no giant-allocation path found on the 3ds side.

### 4.3 gx / wii-tex-extract assessment (new attack surface if merged)

The `C:\Users\Zagre\Desktop\wii-tex-extract` codebase is materially weaker than the 3ds side. Core gap: NO filename sanitization and NO output-boundary check anywhere. Merged as a `platforms/gx` package as-is, it would reintroduce the exact traversal class the 3ds code already closed.

CONFIRMED vulnerabilities:

1. Path traversal into output writes (CRITICAL). `write_texture` composes `output_dir / game_subpath / filename` and calls `out_path.parent.mkdir(parents=True, ...)` + `img.save(out_path)` with zero validation (`src/core/output_writer.py:112-116`). `game_subpath` derives from disc FST paths and archive entry names: `path_prefix + name` in the Wii FST walk (`src/core/filesystem.py:308,322`), `path_hint + "/" + name` in the U8 walker (`src/core/archive_walker.py:108`), and `f"{leaf_path}/{t.name}"` for BRRES sub-textures (`extraction_worker.py:156`). None strip `..`, leading `/`, drive letters, or backslashes; a crafted FST name like `../../../../x` escapes `output_dir`. This is an arbitrary PNG-content file-write primitive, strictly worse than the 3ds pre-fix state because there is no commonpath backstop. The only sanitizer present, `make_game_dir_name` (`output_writer.py:120-135`), covers only the top-level game directory name.
2. Unbounded decompression allocation, Yaz0 (HIGH). `src/parsers/yaz0.py:30-31` reads a big-endian u32 `dec_size` and immediately allocates `bytearray(dec_size)` with no cap: a crafted `.szs` header can request up to 4 GB. The 3ds Yaz0 rejects > 50 MB; the gx port dropped that check. LZ11 has the same shape (`src/parsers/lz11.py:29,33`, 24-bit size so max 16 MB, less severe); ASH decompressed size (`src/parsers/ash.py:8`) also unbounded.
3. Unbounded texture allocation (HIGH). `decode_gx` allocates `np.zeros((ph, pw, 4))` where dims come from TPL/BTI/GVR headers read as u16 with no upper bound (`src/decoders/gx_decoder.py:77-80`, `src/parsers/tpl.py:72-73`, `src/parsers/bti.py:48-49`). A crafted 65535x65535 RGBA8 descriptor forces a ~17 GB allocation. `_pad_to_output` (`gx_decoder.py:269-276`) pads to next power of two, further inflating. The 3ds parsers cap every dimension; the gx parsers cap nothing.
4. Subprocess on RVZ conversion (MEDIUM/POTENTIAL). `DiscReader._convert_rvz` runs DolphinTool via `subprocess.run([...], check=True)` (`src/core/disc_reader.py:230-238`). Argument-list form, `dolphin_exe` from `shutil.which`, so no classic injection, but it is a new external-process dependency with user-controlled input paths.
5. Predictable temp file (LOW/POTENTIAL). `NamedTemporaryFile(suffix=".iso", delete=False)` then manual unlink on close (`disc_reader.py:118-124,226-241`); if conversion raises before `_close`, a large decrypted IS

## 5. Performance

### 5.1 Method

Profiled a full azahar-mode extraction with cProfile:
`tex-forge extract "D:\Roms\3DS\n3ds\New Super Mario Bros. 2 (USA) (En,Fr,Es).cci" -o <scratch> --output-mode azahar --dedup --quiet`. ROM is 512 MiB decrypted. Run produced 1761 PNGs. Wall time 584.7s. Environment note: on this machine the native `cityhash` module is NOT installed, so the pure-Python CityHash64 fallback ran; `xxhash` IS installed, so raw-byte dedup was active. cProfile's call counters overflowed 32-bit on the hottest function (read_bit shows a negative ncall), so raw call counts below are reconstructed (`2**32 - reported`).

### 5.2 Top 3 bottlenecks (measured)

| Rank | Function | Self time | Cumulative | Calls | Share of wall |
|---|---|---|---|---|---|
| 1 | `_v1_level5.py:133 decode_symbol` (Level-5 Huffman symbol decode) | 359.2s | 556.1s | 51,463,220 | ~95% cumulative |
| 2 | `_v1_level5.py:121 read_bit` (single-bit reader inside decode_symbol) | 196.4s | 196.4s | ~2.33 billion | ~34% self |
| 3 | `_v1_level5.py:97 _decompress_huffman` (driver) | 11.3s | 571.1s | 213 | wraps 1+2 |

The entire runtime is the pure-Python Level-5 Huffman decompressor. `try_decompress -> compression/level5.py:51 -> _v1_level5.decompress_l5 -> _decompress_huffman` accounts for 571 of 585 seconds (97.7%). The decoder walks the Huffman tree one bit at a time in interpreted Python: 213 Huffman blocks drive 51.5 million `decode_symbol` calls and roughly 2.3 billion `read_bit` calls. Everything else is noise by comparison:
- Pure-Python CityHash64 fallback: ~5.4s total across 2824 texture hashes (`_cityhash_pure.py`), dominated by `_fetch64`/`_rotate`/`_weak_hash_len_32_with_seeds` at ~10M/5.9M/1.7M calls. With the native `cityhash` module installed this drops toward zero.
- ETC1 numpy decode (`pica_numpy.py:251 _decode_etc1_blocks` + `_scatter_blocks`): ~1.0s over 1523 textures. The vectorized decoder is not a bottleneck.
- Quality metrics (`quality/metrics.py:19`): ~3.7s over 1760 textures.
- Contact-sheet font rendering: ~0.8s (1200 glyph renders), one-time at the end.

Two things compound rank 1. First, from 2.3, the Level-5 Huffman child-offset math is a suspected bug (missing `*2`), so a large share of those 571 seconds may be producing bytes that downstream container-magic checks then reject: slow AND possibly wrong. Second, the `level5` codec is priority 30 (lowest) with a permissive method-byte heuristic detect, so it is plausibly being invoked on files it should not decompress; 377 `decompress_l5` calls for a Nintendo (non-Level-5) title is a signal worth confirming with a per-file trace. Either way, the fix is the same: this codec must not run interpreted bit-by-bit at scale.

Recommended remediations, in order: (a) gate the Level-5 codec behind a stricter detect so it stops firing on non-Level-5 data; (b) rewrite `decode_symbol`/`read_bit` to consume bits in word-sized chunks (or vectorize the tree walk), which alone should cut 500s+ from this ROM; (c) fix the child-offset math per 2.3 so the work is correct; (d) ship/require the native `cityhash` wheel so the hash fallback never runs in batch.

### 5.3 Memory behavior at ~1M texture scale (estimated, not run)

Per-texture decode is transient: one RGBA `ndarray` exists at a time and is freed after the PNG write is submitted, so peak transient memory is bounded by a few in-flight textures times the `ThreadPoolExecutor` width, on the order of tens of MB. The scaling concern is accumulation, not transients. Two structures grow with the total texture count and are held until the very end of the run (nothing is streamed to disk incrementally):

1. `ExtractionPipeline.records` / `.failures` (`extractor.py:160-161`): one dict per texture with ~17 fields, including two 40-char SHA1 hex strings and several path strings. Realistic CPython cost is ~1.2 to 1.8 KB per record. At 1M textures that is roughly 1.2 to 1.8 GB retained.
2. `Deduper.seen_raw` and `seen_content` (`dedup.py:43-45`), populated when `--dedup` is on: per unique texture, one xxhash hex key plus a two-string tuple, and one md5 hex key plus a tex_id string. Roughly 0.4 to 0.6 KB per unique texture across both dicts, so ~0.4 to 0.6 GB at 1M unique.

Estimated resident Python heap for a 1M-texture run is therefore on the order of 2 to 2.5 GB, growing linearly and monotonically, released only at process exit. On a 32-bit build or a memory-constrained machine this is a hard ceiling; on a normal 64-bit desktop it is large but survivable. The batch command extracts one title at a time to `<out>/<title_id>/` with a fresh pipeline per ROM (`commands/batch.py`), so the accumulation resets per title and the 1M figure is only reached within a single enormous title, not across a batch. The mitigations if single-title scale grows: stream manifest records to a JSONL file as they are produced instead of buffering the whole list, and cap or externalize the dedup maps (for example an on-disk key store or a bounded LRU) so they do not grow without bound.

## 6. Roadmap readiness

### 6.1 v2.5 (batch processing, Pokemon support)

Batch processing is essentially DONE and the architecture helped it: `tex-forge batch` (`commands/batch.py`) already walks folders via the single `ROM_EXTENSIONS` source of truth, runs the real per-ROM pipeline (multi-content CIAs included), extracts each title to `<out>/<title_id>/`, skips duplicate title IDs, supports `--limit`, writes `batch_summary.json`, and continues on error. A fresh `ExtractionPipeline` per ROM means the O(texture-count) memory accumulation from 5.3 resets per title, so batch scales across a set even though a single title does not stream. The remaining batch gaps are non-blocking: no cross-title dedup (each title dedups independently), no parallelism across titles (one ROM at a time), and the Level-5 performance cliff from section 5 will make any batch that touches Level-5 or Level-5-false-positive content unacceptably slow. Fixing the Level-5 bottleneck is the real prerequisite for batch at scale, more than any missing batch feature.

Pokemon support is where the architecture both helps and actively blocks:
- Helps: GARC (the Pokemon archive) is already a registered plugin at top priority (`archives/garc.py`, prio 100), the compression codecs Pokemon needs (LZ11, BLZ) exist, and the plugin registries mean a new Pokemon texture container is a single `@register_texture` module with no pipeline surgery.
- Blocks: the three Pokemon/GARC adapter functions are written but NOT wired in. `unwrap_pokemon_container` (`adapters.py:156`), `parse_pokemon_pc_v5` (`adapters.py:171`), `garc_should_suppress_bch` (`adapters.py:241`), and `garc.has_cgfx` (`garc.py:92`) are all dead code with zero call sites (see 3.3); `extractor.py:48-52` imports only the Smash and GDB1 adapters. The BCH heuristic parser is a known false-positive source (2.3), and the whole point of `garc_should_suppress_bch` is to stop BCH from misfiring inside GARC archives, so shipping Pokemon without wiring these in will produce a flood of BCH false positives. This is an integration task, not new-parser work: the seams exist, they just are not called. The PROGRESS.md log confirms Pokemon is "parser work; needs real GARC content validation on the dev box," so real-ROM GARC v6 validation is also outstanding (and note the GARC v6 multi-subfile FATB stride bug from 2.3, `garc.py:63-65`, will bite exactly the Pokemon archives).

v2.5 recommended path: fix Level-5 performance (unblocks batch at scale), wire in the three Pokemon adapters and add GARC v6 FATB support, then validate against a real Pokemon ROM.

### 6.2 v3.0 (.texproj authoring pipeline)

Nothing named `.texproj` exists yet; this is greenfield. An authoring pipeline (import a dump, edit/replace/upscale textures, re-emit a pack) implies a persistent, round-trippable project document that survives re-extraction and records provenance. What the current architecture already gives it:
- The manifest is already a schema-v2 provenance record (`output/manifest.py`) tying each PNG to source ROM, container chain, offset, format, and two SHA1s, and `import-dump` (`commands/import_dump.py`) already matches emulator-dumped filenames back to manifest rows and stamps `dump_hash`. That is the skeleton of a project format.
- The pack builder already separates Azahar's `pack.json` from Forge's own `forge_pack_meta.json`, so Forge-side authoring metadata has a home that will not collide with the emulator's config.
- `build-pack --upscaled` already exists as the handoff point to an external upscaler (`output/pack_builder.py` upscaled_dir), which is the natural authoring input.

What needs refactoring, and when:
- Refactor NOW (cheap while the code is young, expensive later): the three duplicated filename sanitizers (`core/types.py`, `output/filenames.py`, `home_menu.py`) and the two disagreeing LZ10 / two CRILAYLA decompressors (3.3). A `.texproj` pipeline that reads and rewrites paths and re-decompresses source blobs will multiply this drift into correctness bugs; consolidate to one sanitizer and one codec per format first.
- Refactor NOW: fix the Azahar hash-input bug (2.2). A `.texproj` pipeline whose entire value is that replaced textures match in the emulator is worthless if the stored hash covers mip chains instead of mip0. This is the single most load-bearing correctness fix for v3.0.
- Refactor LATER (only when authoring lands): the manifest is currently write-once at end of run (buffered in `records`). Authoring implies incremental read-modify-write of a project document; that wants the streaming/externalized store from 5.3 and a stable project schema with versioning. Do this when `.texproj` is actually designed, not preemptively.
- Refactor LATER: the pipeline currently couples extraction and output tightly (`_handle_texture` both decodes and decides output paths, and carries format-specific business logic like the BCH filter, extractor.py:462-472). A clean authoring pipeline wants extraction to produce a neutral texture+provenance stream that an output/authoring layer consumes separately. Worth doing as part of v3.0 design, not before.

### 6.3 Prioritized recommendations

Effort: S = under a day, M = a few days, L = a week or more. Ordered by recommended execution sequence (correctness and the things that block everything else first, then performance, then cleanup, then roadmap enablers).

1. (S) Fix the Azahar hash input to cover exactly the mip0 surface bytes, not the full parser payload. Slice `tex.data` to `encoded_size(mip0)` before hashing in CTPK/CGFX/Shin'en/BFLIM, and reject the `_dict_to_texture` size-0/EOF fallbacks from hashing. This is the difference between packs that work in the emulator and packs that silently never match (2.2). Highest correctness-per-effort.
2. (S) Add a defensive try/except around texture-plugin iteration in `scanner.py:177` mirroring the archive side, so one malformed container parser cannot abort an entire content's extraction (3.3). Small change, large blast-radius reduction.
3. (S) Plumb the PNG/raw writer future results (`extractor.py:213,493-506`) so a failed write stops being recorded as `decoded_ok` with a non-existent `decoded_png_path` in the manifest (3.2). Corrupt-output-as-success is the worst kind of silent failure for a tool whose output feeds an emulator.
4. (M) Fix the Level-5 performance cliff: gate the codec behind a stricter detect so it stops firing on non-Level-5 data, and rewrite `decode_symbol`/`read_bit` to read bits in word chunks. This alone should cut ~500s from the NSMB2 baseline and is the real prerequisite for batch at scale (5.2).
5. (M) Rewrite the CRILAYLA decompressor to the real backward-bit-stream algorithm (2.3). As written it decodes all compressed CPK content to garbage, so every CPK-based game silently loses its textures; the self-referential test masks it. Add a real CRILAYLA test vector.
6. (S) Fix the Level-5 Huffman child-offset math (missing `*2`, `_v1_level5.py:143`) and remove the half-output-accepted-as-success paths in `_v1_level5.py` and `yaz0.py` (2.3, 3.2). Do this together with item 4 since it is the same file.
7. (S) Fix the BFLIM A4-to-A8 mismap (`_v1_bflim.py:31`) to use native PICA A4, and stop overwriting `tex.width/height` with post-crop dims before composing the Azahar filename so cropped BFLIMs ship a proportional PNG (2.1, 2.2).
8. (S) Close the security gaps: add a commonpath guard to the mapped-mode `dump_hash` destination (`pack_builder.py:186`) and an output cap to the generic zlib/gzip codecs (`zlib_helpers.py:41,61`) (4.4).
9. (M) Wire in the three dead Pokemon/GARC adapters and add GARC v6 multi-subfile FATB support, then validate on a real Pokemon ROM. This is the v2.5 Pokemon milestone and is mostly integration, not new parsing (6.1, 3.3).
10. (S) Consolidate the three filename sanitizers and the duplicated LZ10/CRILAYLA/Level-5-header logic into one implementation each (3.3). Cheap now, and a prerequisite for a clean v3.0 authoring pipeline.
11. (S) Delete the dead v1 GUI modules (`gui/_gui_app_v1.py`, `_gui_entry_v1.py`, ~1941 lines) and the other verified-dead functions (3.3), and exclude them from `forge.spec` so they stop being frozen into the exe.
12. (M) Add the missing test surface: differential numpy-vs-python decoder parity, round-trip tests for Yaz0/BLZ/Level-5/CRILAYLA (with real vectors), header-level tests for the container parsers, and at least one real-RomFS end-to-end test (3.1). This is the safety net that makes items 1 to 10 verifiable.
13. (M/L, roadmap) For v3.0, stream manifest records to JSONL and externalize the dedup maps (5.3), then separate extraction from output/authoring so `.texproj` can consume a neutral texture+provenance stream (6.2). Defer until v3.0 is actually designed.
14. (M, if merging gx) Before any `platforms/gx` merge, route gx path components through `sanitise_archive_name` and `build_output_path`, and add decomp-size and dimension caps to the gx parsers (4.3). Do not merge as-is; it regresses the 3ds security posture.

## Finding 1 verification (2026-07-01)

Verdict: CONFIRMED, with a severity refinement. The decisive evidence is a single real texture from the NSMB2 validation baseline itself: `cobKoopaCastle.bcres`, a 64x256 ETC1 CGFX texture whose stored data is a genuine mip pyramid (mip0 8192 + mip1 2048 + mip2 512 = 10752 bytes). Forge hashes the whole 10752-byte slice and gets `592469595A7667CB` (byte-for-byte the value in the run manifest, so this is what Forge writes into the `tex1_..._mip0.png` filename). Azahar hashes only the mip0 surface (8192 bytes), which is `99D5874C5F9C5F8C`. The two differ, so Azahar never loads this texture. Finding 1 is real and it is sitting inside the "validated" title.

How the tension resolves: NSMB2 matched in Azahar for the textures anyone spot-checked because those were mip0-only, not because the pipeline is correct on mipmapped input. Both halves of the apparent contradiction are true at once, just about different textures.

Step 1 (NSMB2 CTPK mip counts, hex-dump-first). All 167 CTPK entries across NSMB2 have `mip_levels == 1` and `data_size == encoded_size(mip0)` exactly (0 mismatches). Verbatim header of the first entry (`J_Chika.sarc > BG_tex/coin_red.ctpk`):

```
000000  43 54 50 4B 01 00 01 00 80 00 00 00 00 40 00 00   CTPK.........@..   ver=1 count=1 data_off=0x80 data_size=0x4000
000020  44 00 00 00 00 40 00 00 00 00 00 00 0D 00 00 00   entry: data_size=0x4000 fmt=0x0D(ETC1A4)
000030  20 00 00 02 01 02 00 00 ...                        w=0x20(32) h=0x200(512) mip_levels=0x01
```

`data_size 0x4000 = 16384 = encoded_size(32,512,ETC1A4)`, so for CTPK the full slice IS mip0. These are case (a): they matched by coincidence. Widening the CTPK check to 23 available titles (about 795 CTPK entries, including Captain Toad's 299) found ZERO CTPK entries with `mip_levels > 1`. So the CTPK mip-chain hazard named in finding 1 is real in the code but essentially never occurs in practice for CTPK.

Where finding 1 actually bites: CGFX, not CTPK. The CGFX parser hardcodes `mip_count = 1` (`_v1_cgfx.py:113`) while slicing the full TXOB `data_size`, which does include the mip chain. That is why the manifest shows `mip_count = 1` for every texture (my first-pass check looked clean) even though 35 CGFX textures in NSMB2 carry a real mip pyramid. The reliable signal is `len(tex.data) > encoded_size(width, height, format)`, not the manifest mip_count. Classifying the 103 NSMB2 records where the hashed slice exceeds mip0:
- CGFX: 35 are genuine mip pyramids (real hash mismatches), 4 other padding.
- BFLIM: 61 are power-of-2 storage-surface padding, 3 look like pyramids. The BFLIM storage-padding cases are NOT hash mismatches: Azahar uploads and hashes the full storage surface, which equals Forge's full slice, so the bytes agree (the BFLIM problem is instead the display-vs-storage dimension mismatch in the filename, section 2.2 item 3, a separate axis).

So the corrected severity: finding 1's CTPK claim is latent-only (0 real occurrences observed), but the same root cause produces ~35 silently-broken textures per title through the CGFX path, in the validation baseline itself. Net: CONFIRMED, and the CGFX manifestation is more common than the CTPK one it was originally attributed to.

Step 2 (Azahar ground truth, source not inference). From Azahar `src/video_core/rasterizer_cache/rasterizer_cache.h`, the hash is computed per surface interval and the level is taken from that same interval:

```cpp
const u64 hash = ComputeHash(load_info, upload_data);
const u32 level = surface.LevelOf(load_info.addr);
Material* material = custom_tex_manager.GetMaterial(hash);
```

and `src/video_core/custom_textures/custom_tex_manager.cpp` writes one file per level:

```cpp
dump_path += fmt::format("tex1_{}x{}_{:016X}_{}_mip{}.png", width, height, data_hash, format, level);
```

So each mip level is hashed and dumped independently over that level's own bytes; the `_mip0` file's hash covers mip0 only, never the whole chain. That is the authoritative basis for the verdict.

Adjacent discovery, flagged separately and NOT folded into finding 1 (needs its own verification pass): the same `ComputeHash` shows the legacy path that Forge pins hashes DECODED bytes, while the new path hashes raw tiled bytes:

```cpp
if (!custom_tex_manager.UseNewHash()) {
    auto decoded = std::vector<u8>(width * height * bpp);
    DecodeTexture(load_info, load_info.addr, load_info.end, upload_data, decoded, false);
    return Common::ComputeHash64<...CityHash>(decoded.data(), decoded.size());
} else {
    return Common::ComputeHash64<...CityHash>(upload_data.data(), upload_data.size());
}
```

Forge hashes raw tiled `tex.data`, which matches the NEW branch, yet `pack.json` pins `use_new_hash: false` (the legacy/decoded branch) on current Azahar master. That NSMB2 mip0-only textures nonetheless matched implies the validated Azahar was effectively using the raw-bytes hash regardless of the pin (either the user had new-hash on, or the validated build's legacy branch hashed raw bytes). This is potentially a larger correctness issue than the mip slice and should be verified on its own before any hash fix ships. It does not change the finding 1 verdict, because per-level hashing holds in both branches.

Step 3 (decisive numeric cross-check on real data): `cobKoopaCastle.bcres` 64x256 ETC1, backend = pure-Python CityHash64 (native `cityhash` not installed here):

| Candidate | Bytes hashed | CityHash64 |
|---|---|---|
| Full payload (Forge stores this, goes in the filename) | 10752 (mip0+mip1+mip2) | `592469595A7667CB` |
| Mip0 only (Azahar `_mip0` lookup) | 8192 | `99D5874C5F9C5F8C` |

Different. Forge names the file `tex1_64x256_592469595A7667CB_12_mip0.png`; Azahar looks up `99D5874C5F9C5F8C` and finds nothing.

Proposed fix (NOT applied, awaiting go-ahead): hash exactly the mip0 surface. The clean form is to have each container parser emit an explicit `mip0_size` (or per-level offsets) and hash `tex.data[:mip0_size]` in `_handle_texture` (`extractor.py:385`), rather than the whole slice. Do NOT compute the truncation from `encoded_size(width, height, format)` in the pipeline: that is wrong for BFLIM (where width/height are display dims but the surface is the larger power-of-2 storage size, so truncating would BREAK the BFLIM textures that currently work) and for ETC odd dimensions (section 2.1 item 4). Affected parsers, in priority order: CGFX (`_v1_cgfx.py`, the primary real-world manifestation, hardcoded mip_count=1 but full-chain slice), CTPK (`_v1_ctpk.py`, latent), Shin'en TEX (`_v1_shinen_tex.py`, `data_size = len - data_offset` includes mips and trailing padding). BCH already slices mip0 only and is safe. Prerequisite: resolve the Step 2 adjacent discovery (decoded-vs-raw / use_new_hash) first, since if the pinned legacy hash truly decodes, the correct fix is to change both the pinned mode and the slice, not the slice alone.

---

## 2026-09-08 targeted correctness pass (tasks 1-5)

Four audit findings that survived the v1 to v2 refactor unchanged, plus a README house-rule restore. Every binary-parsing change was made hex-dump-first against real ROM bytes, not from reasoning alone.

### Environment reconciliation (before any code change)

The task's stated setup did not match this machine, so the following was resolved and recorded up front:

- Working tree is `C:\Users\Zagre\Downloads\3ds-tex-extract` (the Desktop only holds a zip whose four target files are byte-identical to this tree).
- The reference audit was not present in-repo. Recovered from `D:\Program Files\3DS-Texture-Forge-1.1.zip` and placed at `outputs/reference/3DS-Texture-Forge-1.1/dev/audit_results.json`.
- ROMs are under `D:\Roms\3DS\3ds-decrypted-roms321com\all` (numbers + A-H only), not `D:\3ds\`. The dumps carry plaintext RomFS (IVFC magic) but leave the NCCH NoCrypto flag unset, which trips Forge's encryption guard; a working copy with that flag set (dev_patch_nocrypto.py) was used for gating. The production crypto check was left untouched (out of scope, and correct for genuinely-encrypted input).
- Three named gate ROMs are absent (Mario Kart 7, Persona Q, Pokemon Y). Substitutes used and noted: Dragon Ball Fusions (CRILAYLA), NSMB2 + Kirby (CGFX), Corpse Party / Bravely Default / FE Awakening (ETC1/ETC1A4 regression).

### Task 1 - Level-5 Huffman child-offset (correctness)

Hex-dump findings: Fantasy Life's `_file_archive.bin` is a Level-5 flat archive of 38,204 entries, all method-1 LZ. They decompress to `zmdl`/`ztex` Level-5 containers (raw PICA data with `tex\x02` sub-blocks), NOT IMGC, and contain zero method-2/3 Huffman blobs. v2 has no `ztex` parser, so it extracts 0 textures from this ROM and never calls `_decompress_huffman`. Layton's files are not recognised as archives either. No ROM reachable in this environment exercises the Level-5 Huffman path.

Fix: corrected `decode_symbol` to the canonical GBATEK form `child_base = (node_off & ~1) + (node & 0x3F) * 2 + 2` (left child at child_base, right at +1). The v1 code added the offset as a byte count (not 16-bit words) and aligned on the tree-relative offset (`node_off - tree_start`), which differs because the tree starts at the odd offset 1. Both errors fixed.

Gate: two hand-laid canonical-format fixtures in `tests/test_compression.py`, each isolating one sub-bug (word-multiply at the root; alignment at an odd node offset). Both round-trip through the fixed decoder and produce wrong output under the old formula. The Fantasy Life count gate could not be reproduced (0 textures, ztex unhandled - a separate, larger gap than the child-offset bug, and outside this pass's scope).

### Task 2 - Level-5 Huffman performance

Replaced the per-bit `struct.unpack_from` + Python-call `read_bit` with a one-shot numpy bit expansion handed to a plain Python list (list indexing beat numpy scalar indexing in a micro-benchmark). Pure-Python fallback retained for numpy-less environments.

Timing (micro-benchmark, this machine): isolated bit-read loop 0.335s (orig struct) vs 0.046s (list) over 2,000,000 bits = ~7.3x. End-to-end synthetic decode with shallow 1-bit codes was 1.47x (read_bit is a smaller share when codes are short; real deeper codes gain more). The on-ROM Fantasy-Life wall-clock gate is outstanding because no reachable ROM exercises the path.

### Task 3 - CRILAYLA is the wrong algorithm (correctness)

Hex-dump findings: 7th Dragon III's RomFS is a single 1.65 GB CPK with zero CRILAYLA entries (uncompressed). Dragon Ball Fusions has 6,494 CRILAYLA entries; a real entry (decomp=68, comp=32, +0x100 raw header) was dumped and its original file starts with `jMOT`.

Fix: replaced the fixed 2-byte backref decode with the real algorithm - an MSB-first bitstream read backward from the body end, a 13-bit distance (+3), and a variable-length length assembled from 2/3/5/8-bit chunks (each all-ones chunk means read the next wider chunk and keep adding; base 3). Verified byte-exact against the real entry and cross-checked two independent reference ports over 500 real DBF entries (0 mismatches). `_cpk_v1._decompress_crilayla` now delegates to the shared codec so the two copies cannot drift. `tests/test_crilayla.py` rewritten: real DBF fixture with known-good output (`tests/fixtures/crilayla_dbf_*.bin`), a both-copies-agree assertion, and human-auditable synthetic backref streams.

Gate: Dragon Ball Fusions extracts 1,235 textures via 2,427 successful CRILAYLA decompressions (0 failures), output magics jMDL/jMOT/jIMG/JGCL. Previously the CPK content decoded to garbage (~0). Persona Q (the named gate) is absent; DBF uses the same CRI CPK + CRILAYLA path.

### Task 4 - CGFX mip0 slice for the Azahar hash (correctness)

Fix at `extractor.py` `_handle_texture`: hash `tex.data[:width*height*bpp//8]` (bpp from `FORMAT_BPP`) instead of the whole buffer, falling back to the whole buffer if the computed size is implausible or exceeds the data. The BFLIM regression the earlier audit warned about does not materialise here: `_v1_bflim.py` emits storage (power-of-2) dims as width/height, so `width*height*bpp//8` equals `len(tex.data)` for BFLIM and the slice is a no-op. dedup, raw_data_size, and the PNG decode still use the full buffer.

Gate: NSMB2 (000400000007AE00) - 39 mipped CGFX textures now hash mip0 only; all 2,785 single-surface textures hash identically to before. The cobKoopaCastle.bcres 64x256 ETC1 texture now hashes to 99D5874C5F9C5F8C, the value this document's own reverse-engineering identified as Azahar's runtime lookup (was 592469595A7667CB). The emulator drop-in confirmation is the one step that requires Azahar itself; the hash now equals the reverse-engineered target. Root-cause CGFX parser cleanup (report real mip0_size / mip_count) deferred.

### Task 5 - README house-rule sections

Restored the 'A note on how this was built' blockquote and the 'Why this exists' AYN Thor section verbatim from the published GitHub README (raw main branch), placed above the '3DS Texture Forge 2.0' heading. Status block corrected: CRILAYLA is now a correct codec (accurate check), the CPK path shares that codec, the Level-5 Huffman and Azahar mip0 fixes are listed, and the deferred items are marked honestly. Removed the one pre-existing em dash on the title line.

### Regression gate (final)

- pytest: 112 passed (was 106; +2 Huffman, +3 CRILAYLA net, +1 azahar mip0).
- Counts vs reference audit (list_only find counts; small positive skew is expected since these are pre-decode finds):
  - Corpse Party: 2,786 vs 2,656 (+4.9%)
  - Bravely Default: 11,958 vs 11,908 (+0.4%)
  - Fire Emblem Awakening: 10,269 vs 10,295 (-0.3%)
  - Dragon Ball Fusions (CRILAYLA gate): 1,235 (no reference row; was ~0 pre-fix)
  - NSMB2 (azahar gate): 2,824 textures, 39 mipped hashes corrected, 2,785 unchanged
- Fantasy Life remains 0 in v2 (unhandled ztex container). This predates and is unrelated to this pass; flagged here as the biggest single gap for a future task.

Deferred: (a) CGFX parser reporting real mip0_size/mip_count; (b) on-ROM Level-5 Huffman wall-clock gate (no Huffman-bearing ROM reachable); (c) ztex/zmdl texture support (blocks Fantasy Life's ~10,254).

---

## 2026-09-08 pass 2: Fantasy Life zero - diagnosis

### Task 1 verdict: Case A (v1 -> v2 regression)

ROM: `D:\Roms\3DS\3ds-decrypted-roms321com\all\Fantasy Life (USA) Decrypted.3ds` (the stated `D:\3ds\` and No-Intro paths are absent this pass too). Title ID `0004000000113200`. Both v1 and v2 carry the same NoCrypto guard, so both were run against a working copy with the NCCH NoCrypto flag set (`C:\temp\roms\FL_patched.3ds`); the RomFS is genuinely plaintext (IVFC).

- v1 reference (`outputs/reference/3DS-Texture-Forge-1.1/main.py extract`): **10,254** textures decoded OK (220 unique, 97.9% dupes), quality 99.7%, 55.1s, files scanned 2, recognized containers 2. Matches the reference audit row exactly.
- v2 current tree: **0** textures, files scanned 2, 46.8s.

Both scan the same 2 files (`_file_archive.bin` is the payload) and both recognize 2 containers, so file scanning and archive detection are NOT the regression. The loss is downstream: v1 turns the Level-5 flat archive entries into 10,254 textures and v2 turns them into nothing. This is a genuine regression in the Level-5 flat / IMGC extraction path, not a missing brand-new container. Proceeding to task 2A. (The earlier "missing ztex/zmdl support" note from pass 1 was wrong: v1 never needed a ztex parser either, yet extracted 10,254 from the same bytes.)

### Task 2A: Level-5 flat regression fixed

Root cause (hex-dump confirmed): Fantasy Life's `_file_archive.bin` is a Level-5 flat archive of ~38,204 entries. Texture-bearing entries (from ~index 4208) are raw Nintendo LZ11 streams (lead byte 0x11) that decompress to 300-450 KB Level-5 resource buffers with a real CGFX container embedded at offset 0x100 or 0x180 (within the first 0x1000 bytes). v1's `_extract_l5_flat` (reference `textures/scanner.py`) LZ-decompressed each entry and scanned the first 0x1000 bytes for CGFX/BCH/CTPK/CTXB. The v2 refactor turned l5_flat into a plain archive plugin that yields raw entries and relies on the generic scanner; the generic scanner decompresses correctly (verified: entry 4210 -> 377,476 bytes, CGFX at 0x180) but only probes for embedded magics under `--scan-all`, so the containers were never found and Fantasy Life produced 0.

Dumps that pinned this down:
- entry 4210 lead bytes `11 84 c2 05 ...`; v2 classify = `compressed:lz_nintendo_lz11`; try_decompress -> 377,476 bytes; CGFX at 0x180; v2 `extract_textures` on the entry -> 0.
- (Aside: `decompress_l5` mis-parses these because it reads a 4-byte Level-5 method header and dispatches `0x11 & 7 = 1` to the LZ10 decoder, truncating the output. The scanner does not use it here; it uses `lz_nintendo` correctly. Left unchanged.)

Fix: `tex_forge/archives/l5_flat.py` now decompresses each entry (raw LZ when the lead byte is 0x10/0x11/0x13) and yields the texture container found at offset 0 or embedded within the first 0x1000 bytes, matching v1's exact magic set (CGFX/BCH/CTPK/CTXB). The generic texture dispatch handles it from there. Added three unit tests (`tests/test_archives.py`) covering compressed-embedded, direct-uncompressed, and non-texture entries.

Acceptance: Fantasy Life now extracts **10,254** textures (v1 reference 10,254; reference audit 10,254), format distribution ETC1 7626 / ETC1A4 1976 / RGBA8 632 / A8 20 - byte-for-byte the reference audit row. Wall-clock 45.3s (list mode).

Important correction to the pass-1 and task-2A premise: **Fantasy Life does NOT exercise the Level-5 Huffman path.** Instrumenting `_decompress_huffman` across the full FL extraction shows 0 calls. FL entries are LZ11-compressed and its textures are CGFX; the Level-5 Huffman method (method nibble 2/3 in the 4-byte header) is used by IMGC tilemap/pixel blobs and some other Level-5 titles, not this game. So restoring FL does NOT retroactively validate the child-offset fix, and the on-ROM Huffman wall-clock gate is still outstanding (no reachable ROM exercises it). Task 3's independent cross-check is therefore the real validation of the Huffman math.

### Task 3: independent Huffman cross-check

The two canonical fixtures (HUFF8_BLOB / HUFF4_BLOB in tests/test_compression.py, reused as module constants) were decoded with a decompressor written fresh from the GBATEK BIOS HuffUnComp spec, without reading _v1_level5.py (ndspy ships no Huffman codec, so the from-spec option was used). The independent decoder uses a stateless index-based bit reader and a fresh node walk, structured differently from the shipped stateful read_bit / decode_symbol. Result: byte-identical to the shipped decoder AND to the hand-derived expected outputs (b"AB", b"\x21") on both fixtures. No disagreement, so no decoder change needed. Added as `test_huffman_fixtures_match_independent_gbatek_decoder`.
