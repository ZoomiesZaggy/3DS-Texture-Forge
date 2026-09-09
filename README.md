> **A note on how this was built:** This tool was developed entirely with Claude (Anthropic's AI assistant). Weeks of diligent prompting, oversight, and iteration. Not a weekend vibe-coding session. I want to be upfront about that because the community has complicated feelings about AI, and those feelings are valid. My position: AI writing code is a tool, the same way a compiler is a tool. AI generating art is a different conversation, one I personally land on the opposite side of. Which is exactly why this tool exists. It extracts raw source textures from 3DS ROMs so that artists, modders, and preservationists can do the painstaking, skilled, human work of redrawing, remastering, and reimagining them properly. **The extraction is automated. The artistry is yours.**

---

## Why this exists

The AYN Thor changed things. A handheld powerful enough to run Azahar at full speed, in a clamshell form factor (two screens, the way Nintendo intended) finally made 3DS games feel like a platform worth investing in again rather than a museum piece. And Azahar's custom texture support means you can actually do something with that hardware: replace the original 240p assets with hand-crafted high-resolution replacements and experience games like Ocarina of Time 3D, Fire Emblem Awakening, or Pokémon X the way they were always trying to look, constrained only by a 2011 GPU.

The problem is that getting those original textures out of a ROM was either impossible, broken, or required stitching together three different tools none of which agreed on format. 3DS Texture Forge exists to fix that. Drop in a decrypted ROM, get a folder of PNGs. That's it.

---

# 3DS Texture Forge 2.0

A ground-up refactor of [3DS-Texture-Forge 1.1](https://github.com/ZoomiesZaggy/3DS-Texture-Forge): same texture coverage, tighter architecture.

## What's different

The original was a working tool but two files (`main.py` 1247 lines, `textures/scanner.py` 1314 lines) carried most of the load. v2 keeps every working parser and decoder; it just spreads them across single-purpose modules wired together by three small registries.

| Concern | v1 location | v2 location |
|---|---|---|
| ROM containers (NCSD/NCCH/CIA/RomFS) | `parsers/{ncsd,ncch,cia,romfs}.py` | `tex_forge/rom/` + `tex_forge/rom/loader.py` |
| Compression (LZ10/11/13, BLZ, Yaz0, zlib, gzip-prefix, CRILAYLA, Level-5) | `parsers/lz.py` + scattered through `scanner.py` and `cpk.py` | `tex_forge/compression/` + plugin registry |
| Archive formats (GARC/SARC/ZAR/CPK/...) | `parsers/*.py` | `tex_forge/archives/` + `@register_archive` plugins |
| Texture formats (BCH/CGFX/CTPK/IMGC/...) | `textures/*.py` | `tex_forge/textures/containers/` + `@register_texture` |
| PICA200 pixel decode | `textures/decoder.py` + `decoder_numpy.py` + `etc1.py` | `tex_forge/textures/decoder/` (numpy + python paths) |
| Format constants | scattered `FMT_*` ints + dicts | `tex_forge/textures/formats.PicaFormat` enum |
| Top-level extraction | `main.cmd_extract` (1000+ lines) | `tex_forge/pipeline/extractor.ExtractionPipeline` |
| CLI dispatch | `main.py` argparse | `tex_forge/cli.py` + `tex_forge/commands/*.py` |
| Output writers (manifest, PNG, contact sheet, pack builder) | `output.py` + `contact_sheet.py` + `pack_builder.py` | `tex_forge/output/{manifest,png_writer,contact_sheet,pack_builder,reports,filenames}.py` |
| Quality metrics | `quality.py` | `tex_forge/quality/metrics.py` |
| Game metadata (title-id catalogue) | inline in `backend.py` | `tex_forge/metadata/games.py` |
| GUI ↔ pipeline glue | `backend.py` faking argparse via `SimpleNamespace` | `tex_forge/gui/backend.py` calls `ExtractionPipeline` directly |

## Adding a new format

Three pure-decorator entry points:

```python
# A new compression codec
@register_compression("lz_my_game", priority=60)
class _MyLZ:
    @staticmethod
    def detect(data): ...
    @staticmethod
    def decompress(data): ...

# A new archive format
@register_archive("my_arc", priority=80)
class _MyARC:
    @staticmethod
    def detect(data): ...
    @staticmethod
    def iter_entries(data): ...   # yields ArchiveEntry

# A new texture format
@register_texture("my_tex", priority=85)
class _MyTex:
    @staticmethod
    def detect(data): ...
    @staticmethod
    def iter_textures(data, source_path=""): ...   # yields Texture
```

Drop the module under the matching package and import it from the package's `__init__.py`. The pipeline picks it up; nothing else has to change.

## Layout

```
tex_forge/
├── core/                 # bottom of the dep graph
│   ├── binio.py          # bounds-checked u8/u16/u32 readers
│   ├── exceptions.py     # EncryptedROMError, ROMParseError, DecodeError
│   ├── logging.py        # one place to flip verbosity
│   └── types.py          # Texture, ArchiveEntry, FilePeek dataclasses
│
├── rom/                  # outermost containers
│   ├── ncsd.py / ncch.py / cia.py / romfs.py
│   └── loader.py         # parse_rom() entry
│
├── compression/          # 9 codecs + registry
│   ├── lz_nintendo.py    # LZ10 / LZ11 / LZ13
│   ├── blz.py            # backward LZSS
│   ├── yaz0.py           # SZS
│   ├── crilayla.py       # CRI CPK CRILAYLA
│   ├── level5.py         # method-byte multiplexer (LZ10/Huffman/RLE)
│   ├── zlib_helpers.py   # raw zlib + 4-byte-prefix gzip
│   └── registry.py       # try_decompress() dispatcher
│
├── archives/             # 12 archive plugins + registry
│   ├── garc.py / sarc.py / narc.py / zar.py / gar.py / darc.py
│   ├── arc_capcom.py / arc_fe.py / arc0.py
│   ├── cpk.py / l5_flat.py / gfac.py / smash_dt.py
│   └── registry.py       # detect_archive(data)
│
├── textures/
│   ├── formats.py        # PicaFormat enum (single source of truth)
│   ├── morton.py         # Z-order de-tiling tables
│   ├── decoder/
│   │   ├── pica_numpy.py  # vectorised path
│   │   ├── pica_python.py # scalar fallback
│   │   └── dispatch.py    # decode(data, w, h, fmt)
│   ├── containers/        # 12 texture plugins
│   │   ├── bch.py / cgfx.py / ctpk.py / ctxb.py / cmb.py
│   │   ├── bflim.py / jimg.py / shinen_tex.py / stex.py / tex_capcom.py
│   │   ├── gdb1.py / level5_imgc.py
│   │   └── _v1_*.py       # vendored v1 parsers (drive the wrappers)
│   └── registry.py        # detect_texture(data)
│
├── pipeline/
│   ├── extractor.py       # ExtractionPipeline class
│   ├── scanner.py         # classify_file + extract_textures
│   ├── filter.py          # FileFilter (which RomFS files to peek)
│   ├── dedup.py           # Deduper (xxhash + md5)
│   ├── adapters.py        # game-specific tweaks (Smash, GDB1, Pokemon PC)
│   └── progress.py        # CLIBarProgress / CallableProgress
│
├── output/                # all output writers
│   ├── manifest.py        # make_record + write_manifest/failures/summary
│   ├── png_writer.py      # save_png with alpha-visibility heuristic
│   ├── contact_sheet.py   # PNG mosaic for visual review
│   ├── pack_builder.py    # Azahar/Citra texture-pack folder builder
│   ├── reports.py         # quality_report.{json,txt} writer
│   └── filenames.py       # generate_filename / build_output_path
│
├── quality/
│   └── metrics.py         # per-texture suspicion flags + aggregate report
│
├── metadata/
│   └── games.py           # title-id -> friendly name
│
├── commands/              # 5 CLI subcommand handlers
│   ├── extract.py / scan.py / report.py
│   ├── build_pack.py / import_dump.py
│   └── _common.py         # shared rom-loading + error formatting
│
├── gui/                   # PySide6 GUI (optional dependency)
│   ├── backend.py         # ExtractionPipeline-backed scan_rom / run_extraction
│   ├── config.py          # ~/.3ds-texture-forge/config.json
│   ├── entry.py           # `python -m tex_forge.gui.entry`
│   └── _gui_app_v1.py     # vendored v1 PySide6 UI
│
└── cli.py                 # `tex-forge` entry point
```

## Public API

```python
from tex_forge.rom import parse_rom
from tex_forge.pipeline.extractor import ExtractionPipeline, ExtractOptions
from tex_forge.pipeline.progress import CLIBarProgress

romfs, title_id, product_code, chain = parse_rom("game.3ds")
pipeline = ExtractionPipeline(
    romfs_data=romfs,
    title_id=title_id,
    product_code=product_code,
    chain=chain,
    rom_path="game.3ds",
    options=ExtractOptions(output_dir="out/", dedup=True, output_mode="azahar"),
    progress=CLIBarProgress(),
)
summary = pipeline.run()
print(f"Decoded {summary['textures_decoded_ok']} textures in {summary['elapsed_seconds']}s")
```

## CLI

```
tex-forge extract game.3ds -o out/                    # basic
tex-forge extract game.3ds -o out/ --dedup            # skip duplicate textures
tex-forge extract game.3ds -o out/ --output-mode azahar
tex-forge batch "D:\3ds" -o packs/ --output-mode azahar --dedup
                                                       # whole library; one
                                                       # folder per title id,
                                                       # continue on error,
                                                       # batch_summary.json
tex-forge scan game.3ds                                # don't extract, just report
tex-forge verify out/                                  # audit manifest vs disk
                                                       # (flags pre-2026-06-09
                                                       # filename collisions)
tex-forge report out/                                  # summarise a previous extraction
tex-forge build-pack out/                              # produce an Azahar/Citra pack
tex-forge build-pack out/ --upscaled D:\Textures_4k\game
                                                       # ship upscaled PNGs with
                                                       # the same hash mapping
tex-forge import-dump dump_folder/ out/                # merge runtime hashes
```

## Format references

The format docs scattered across the codebase point at:

- 3dbrew (NCCH/NCSD/CIA/RomFS/CTPK/SZS): https://www.3dbrew.org/wiki/
- GBATEK 3DS swizzling: http://problemkaputt.de/gbatek-3ds-video-texture-swizzling.htm
- Ohana3DS deep-wiki (BCH/CGFX texture internals): https://deepwiki.com/dnasdw/Ohana3DS
- citro3d source (PICA200 reference): https://github.com/devkitPro/citro3d
- DSDecmp (LZ10/LZ11): https://github.com/einstein95/dsdecmp
- 3DSkit (BFLIM/SARC/etc.): https://github.com/Tyulis/3DSkit
- CRIWARE CPK + CRILAYLA: https://github.com/Sewer56/CriFsV2Lib , https://github.com/kamikat/cpktools
- ZAR (Grezzo) docs: https://wiki.cloudmodding.com/oot/3D:ZAR_format
- Level-5 .xi / IMGC notes: https://gbatemp.net/threads/level5-xi-file-format.458349/

## Tests

```
python3 -m pytest tests/ -v
```

94 tests cover: morton tables vs. mathematical definition, every PICA200 format
decoding zero-input cleanly, all compressors round-tripping known inputs
(including hand-built CRILAYLA streams), archive detection and priority order,
output writers (manifest / failures / summary / quality report), pack-builder
staging mode, and pipeline graceful-failure paths, multi-content CIA chunk-record parsing, and the multi-content extraction pipeline (per-content manifest tagging, shared dedup, path namespacing), the loader's encrypted-signal handling + GUI multi-content wiring, and Azahar drop-in correctness (CityHash64 filenames, _mip0 suffix, minimal use_new_hash=false pack.json), plus regression coverage for the normal-mode filename collision fix, dump-raw, list-files, cooperative cancellation, and BFLIM tail-peek detection.

## Status

- ✅ All 14 PICA200 pixel formats decode (numpy + python fallback)
- ✅ All compressors from v1 ported (LZ10/11/13, BLZ, Yaz0, zlib, gzip-prefix), plus a correct variable-length **CRILAYLA** codec (real 13-bit-distance + 2/3/5/8-bit length encoding, verified byte-exact against real CPK entries) and the **Level-5 method-byte wrapper**
- ✅ All archive parsers from v1 ported (12 plugins; the CPK path now calls the shared CRILAYLA codec instead of a separate vendored copy, so the two cannot drift)
- ✅ All texture container parsers from v1 ported (12 plugins; BCH/CGFX/CTPK/CTXB/CMB/BFLIM/jIMG/Shinen/STEX/Capcom-TEX/GDB1/IMGC)
- ✅ Level-5 flat archive (Fantasy Life) restored: entries are LZ-decompressed and scanned for the CGFX/BCH/CTPK/CTXB container embedded behind the resource header. Fantasy Life extracts 10,254 textures again (matches the v1 reference exactly)
- ✅ Level-5 Huffman child-offset corrected (byte-vs-word + alignment base) and moved off the pure-Python per-bit path (numpy bit pre-expansion, python fallback retained). Cross-checked byte-for-byte against an independent from-GBATEK-spec decoder. Note: no reachable ROM exercises this path (Fantasy Life uses LZ11 + CGFX, not Huffman), so it has no on-ROM validation yet
- 🟡 Azahar lookup hash now covers the mip0 surface only. The emitted hash equals CityHash64 of the mip0 surface (independently reproduced with the native `cityhash` C extension: cobKoopaCastle 64x256 ETC1 mip0 = `99D5874C5F9C5F8C`). That CityHash64-of-mip0 is what the code audit identifies as Azahar's lookup key, but the end-to-end emulator match is unconfirmed pending an in-emulator load test. Single-surface textures are unchanged
- ✅ CLI parity with v1: `extract`, `scan`, `report`, `build-pack`, `import-dump`
- ✅ Multi-content CIA extraction: `extract` walks content 0 + update/DLC CFAs, tags each manifest record with `source_content`, shares dedup across contents; the GUI (scan + extract) is multi-content aware too
- ✅ GUI uses the new pipeline (vendored v1 UI for now)
- ✅ Manifest writer (schema v2), failures.json, unknown_files.json, summary.json
- ✅ Quality report (JSON + TXT) with format-aware suspicion thresholds
- ✅ Contact sheet generator
- ✅ Pack builder (azahar / mapped / staging). Azahar packs are drop-in: `tex1_<W>x<H>_<CityHash64>_<code>_mip0.png` filenames + a minimal `pack.json` pinning `use_new_hash: false` (legacy hash); Forge's own metadata lives in `forge_pack_meta.json` so it never collides with Azahar's pack config
- 🔧 Deferred: teaching the CGFX parser to report the real `mip0_size` / `mip_count` so the manifest is honest (the Azahar hash-site slice is the correct fix in the meantime)
- 🔧 Deferred gate: the Level-5 Huffman correctness and perf changes are unit-tested against canonical fixtures and an independent decoder, but no reachable ROM exercises the path (a full Fantasy Life extraction was instrumented and made 0 Huffman calls), so the on-ROM wall-clock gate is still outstanding (see `docs/CODE_OVERVIEW.md`)
- 🟡 Deferred confirmation: the Azahar mip0 hash matches Azahar in-emulator (drop the pack in and confirm the previously-missing textures load); the hash math is independently verified but the emulator round-trip is not

The reference v1 codebase still lives at `outputs/reference/3DS-Texture-Forge-1.1/`.
