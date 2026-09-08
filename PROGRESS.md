# 3DS Texture Forge: PROGRESS

Canonical running state for the project. Append a `RESUMING TOMORROW` section
when you stop. No em dashes anywhere (house rule): use commas, colons,
semicolons, or parentheses.

Created 2026-06-07 during the GUI reskin handoff (the repo had no PROGRESS.md or
HANDOFF.md), reconstructed from the live code state.

## What the project is

3DS Texture Forge extracts textures from decrypted Nintendo 3DS ROMs (.3ds,
.cci, .cia, .cxi, .app, .ncch) and emits PNGs plus optional Azahar/Citra
custom-texture packs. v2.0 is a modular refactor of v1.1; same coverage,
single-purpose modules wired by three registries (compression, archives,
textures).

## Backend architecture (v2, load-bearing, do NOT refactor for the UI)

- `tex_forge/rom/`: NCSD/NCCH/CIA/RomFS parsers. `rom/loader.py` exposes
  `parse_rom()` (content 0 only) and `iter_rom_contents()` (walks CIA content 0
  plus update/DLC CFAs). `content_label_from_chain()` pulls the provenance token.
- `tex_forge/compression/`: 9 codecs + registry (`try_decompress`).
- `tex_forge/archives/`: 12 archive plugins + registry (`detect_archive`).
- `tex_forge/textures/`: `formats.PicaFormat` enum (single source of truth for
  Pica200 formats), `morton.py` (Z-order de-tiling), `decoder/` (numpy +
  python paths), `containers/` (12 texture plugins), `azahar_hash.py`
  (CityHash64; native module or bundled pure-Python fallback).
- `tex_forge/pipeline/extractor.ExtractionPipeline`: top-level extraction,
  multi-content aware. `pipeline/progress.py` defines the progress protocol.
- `tex_forge/output/`: manifest, png_writer, contact_sheet, pack_builder,
  reports, filenames.
- `tex_forge/metadata/games.py`: `KNOWN_GAMES` dict + `get_game_name()`.
- `tex_forge/cli.py` + `tex_forge/commands/`: CLI (extract/scan/report/
  build-pack/import-dump).

### Fragile, validated, off-limits for UI convenience

- The CityHash64 Azahar hash pipeline (validated against NSMB2). Azahar packs
  are drop-in: `tex1_<W>x<H>_<CityHash64>_<code>_mip0.png` filenames + a minimal
  `pack.json` pinning `use_new_hash: false`; Forge metadata lives separately in
  `forge_pack_meta.json`.
- The Pica200 format enums and the Morton swizzle logic.
- The ROM/RomFS parsers.

If the UI needs data the backend does not expose, add a thin read-only accessor;
do not change hash, format, swizzle, or parser behavior.

## GUI backend contract (already exists, use as-is)

`tex_forge/gui/backend.py` (plain dicts, scan never raises):

- `scan_rom(filepath)` -> `success, title_id, product_code, file_count,
  content_count, chain, romfs_files_preview, is_encrypted, error_message`.
- `run_extraction(filepath, output_dir, options, progress_callback)` ->
  `success, summary, record_count, failure_count, content_count, elapsed,
  is_encrypted, error_message`. options keys: `output_mode` ("normal"/"azahar"),
  `scan_all`, `dedup`, `dump_raw`, `verbose`.
- `get_output_previews(output_dir, max_count)` -> list of PNG paths.

`progress_callback` real signature is 4-arg: `(current, total, path,
decoded_ok)` (see `pipeline/progress.py` CallableProgress). NOTE: the vendored
v1 worker `ExtractWorker._on_progress` declares a stale 6-arg signature, so its
progress updates are silently swallowed by CallableProgress's try/except. The
new UI must use the 4-arg form.

`tex_forge/gui/config.py` persists `~/.3ds-texture-forge/config.json`
(`load_config`/`save_config`).

## GUI state

- `tex_forge/gui/entry.py` is the entry point: `python -m tex_forge.gui.entry`.
  It installs `config`/`backend` shims under legacy top-level module names so
  the vendored v1 UI imports resolve, then launches `_gui_app_v1.MainWindow`.
- `tex_forge/gui/_gui_app_v1.py` (1925 lines): the current PySide6 UI. Dark
  three-panel layout (sidebar tabs: Extract/Library/Queue/Pack/History/Settings;
  main stack; details panel; status bar). Verified to construct cleanly headless
  (QT_QPA_PLATFORM=offscreen) on 2026-06-07 with PySide6 6.11.0.
- `tex_forge/gui/_gui_entry_v1.py`: older vendored entry (superseded by
  entry.py).

## Known broken/stale bits (fix opportunistically, not load-bearing)

- `Launch-Forge.bat` cd's to `C:\claude\3ds-tex-extract`; the repo actually
  lives at `C:\Software\3ds-tex-extract`. Launcher is broken until fixed.
- `pyproject.toml` `[project.gui-scripts]` points at `tex_forge.gui_entry:main`,
  which does not exist; the real entry is `tex_forge.gui.entry:main`.
- README claims a reference copy at `outputs/reference/3DS-Texture-Forge-1.1/`;
  that directory does NOT exist on this machine. This repo is also not a git
  repo (no `.git`), so v1 history is unavailable here.

## Goal of the current work: 3DS HOME Menu reskin

Replace the v1 UI with a new PySide6 UI that looks/feels like the 3DS HOME Menu,
reusing `backend.py` unchanged. Keep `_gui_app_v1.py` until the new UI reaches
parity, then switch `entry.py` over.

Design pillars: (1) top stage (look) + bottom workbench (touch); (2) glossy
rounded-square game-grid tiles, one per discovered ROM; (3) an inhabited system
with a heartbeat (hinge LED + Activity Log lifetime stats); (4) themeable.

ROM library default paths to wire into discovery:
- `D:\3ds\`
- `D:\3ds Rom set\No-Intro\Nintendo - Nintendo 3DS (Decrypted)\`
Configurable in the UI; persisted via config.py.

Two new read-only accessors the UI wants (add without touching parser
internals):
- Per-ROM icon/banner from NCCH ExeFS SMDH (48x48 large icon, RGB565 tiled).
  Cap at 45 min; ship a placeholder plate + TODO stub if it runs long.
- Persistent lifetime stats (textures extracted, games processed) in config.json,
  incremented after each successful run. May seed with a clearly-labelled
  placeholder constant until real history accrues.

## Open blocker

- README protected section: the "A note on how this was built" blockquote must
  open the README verbatim, restored from the v1 source. It is NOT recoverable
  on this machine (no `outputs/reference/...`, no git history, no copy found
  under C:\Software or C:\Users\Zagre). Must NOT be fabricated. Waiting on Zag
  to paste the authentic text.

## Build target

No PyInstaller `.spec` exists in the repo; `pyinstaller` is only an optional
dependency and `Launch-Forge.bat` just runs the module. Producing a working
spec + confirming the standalone exe runs is an explicit deliverable, not an
assumed-passing check.

## Machine note (this dev box)

The handoff's default library paths (`D:\3ds`, `D:\3ds Rom set\...`) do NOT
exist here; the real decrypted ROMs live under `D:\Roms\3D\` and
`D:\Roms\3DS\3ds-decrypted-roms321com\all\` (NSMB2, the validation title, is at
`D:\Roms\3D\New Super Mario Bros. 2 (USA) (En,Fr,Es).3ds`). The UI keeps the
handoff defaults but is path-configurable, so testing points the library at
`D:\Roms\3D`.

## Pass 1 (DONE, 2026-06-07): HOME Menu shell + game grid

New module `tex_forge/gui/home_menu.py` (does not touch `_gui_app_v1.py`; run it
with `python -m tex_forge.gui.home_menu`). Implements:

- Window = top StatusStrip (live clock/date + decorative signal bars + a
  HingeLED + battery glyph) over a vertical QSplitter with a seam-styled handle.
- Top "stage": CheckerPreview (alpha checkerboard) + a metadata readout
  (game name, title ID, product, file count, content count, ROM size, chain).
- Bottom "workbench": a path bar (Add folder / Rescan, paths persisted to
  config), a scrollable 5-column game grid of GameTile widgets (placeholder
  plates with initials; real SMDH icons are a later pass), and a queue column
  with Start/Stop (disabled until Pass 2) + Clear Queue.
- Discovery runs off-thread (DiscoverWorker, walks library paths, de-dups,
  capped at 600 with a visible "showing first N" note). Rapid Rescans are not
  dropped: a pending-paths relaunch picks up the latest request.
- Selecting a tile runs scan_rom off-thread (ScanWorker) and loads the metadata
  into the stage, and adds the ROM to the queue (no duplicates). LED turns red
  on a failed/encrypted scan.

Config additions (config.py DEFAULT_CONFIG, all additive/backward compatible):
`library_paths`, `theme`, `lifetime_textures`, `lifetime_games`,
`lifetime_seeded`.

Also added NSMB2 (`000400000007AE00`) to `metadata/games.py` KNOWN_GAMES (the
validation title resolved to a fallback slug before).

Verified headless (QT_QPA_PLATFORM=offscreen) against `D:\Roms\3D`: 3 tiles
populate, selecting NSMB2 shows title 000400000007AE00 / CTR-P-ABEE / 992 files,
queue de-dups on repeat clicks.

NOT yet done in Pass 1 (by design): extraction wiring, real LED job states,
3DS visual polish, Activity Log, theme switching, SMDH icons, entry.py switch,
PyInstaller spec.

## Pass 2 (DONE, 2026-06-07): extraction wiring + LED + stage preview

In `home_menu.py`:

- Job model (`Job` class): states QUEUED / RUNNING / COMPLETE / FAILED /
  CANCELED, rendered in the queue list with colored badges. The workbench keeps
  `self.jobs`; selecting/clicking a tile enqueues it (no duplicates).
- `ExtractWorker(QThread)` runs `run_extraction` off-thread and forwards the
  correct 4-arg progress callback `(current, total, path, decoded_ok)` into a Qt
  signal. The window orchestrates the queue sequentially (`_start_queue` ->
  `_run_next` -> `_on_extract_done` -> next).
- Start / Stop / Clear Queue wired. Start runs all QUEUED jobs; Stop terminates
  the in-flight worker (run_extraction has no cancel hook, same as v1) and marks
  it CANCELED; Clear Queue removes only terminal jobs (COMPLETE/FAILED/CANCELED)
  per project convention. Controls enable/disable from queue + running state.
- HingeLED upgraded to real states: steady cyan idle, pulsing green while
  extracting (QTimer breathing animation), brief orange milestone flash every
  5000 decoded textures, steady red on FAILED.
- Stage drives a real texture preview on completion: reads the job's
  manifest.json, picks the first non-duplicate record with an on-disk
  decoded_png_path, and shows the PNG on the checkerboard plus real metadata
  (dimensions, detected_format, Azahar CityHash64 when in azahar mode). Swizzle
  is reported as "Morton (Z-order), de-tiled" because PICA200 textures are
  universally Morton-tiled (see core/types.Texture) and the decoder de-tiles
  them; there is no per-texture swizzle flag to read.
- Output dir per job: `<last_output_path or ./output>/<sanitized game name>`,
  using the cached scan result for the name. Extract options come from config
  (output_mode/scan_all/dedup/dump_raw/verbose); a settings surface in the new
  UI is a later pass.

Verified: queue add/dedup, control enablement, Clear Queue (terminal-only) all
pass headless. Full NSMB2 extraction through the new UI validated separately.

## HOME Menu icons (DONE, 2026-06-07): read-only SMDH accessor

New module `tex_forge/rom/icon.py`, `extract_title_icon(path)`:

- Reuses `loader._route()` for NCSD/CIA -> main NCCH routing, then
  `NCCHParser.get_exefs()`, finds the ExeFS "icon" entry (10-entry, 0x200-byte
  header; offsets relative to header end), slices the SMDH, takes the 48x48
  large icon at SMDH offset 0x24C0 (RGB565 tiled, 0x1200 bytes), and decodes it
  by calling the EXISTING decoder: `decode(tiled, 48, 48, PicaFormat.RGB565)`.
  No new swizzle or format code; returns an RGBA8 (48,48,4) ndarray or None.
- Fails to None (never raises) for encrypted ExeFS, missing icon entry,
  non-SMDH magic, or truncated/odd data; logs and moves on.
- Verified visually: NSMB2 icon decodes to the correct Mario+Luigi art with
  correct colors and Morton de-tiling (saved to PNG, eyeballed, then removed).

Backend: `gui/backend.get_rom_icon_rgba(path)` is a thin pass-through.
GUI: `IconLoader(QThread)` decodes icons sequentially off-thread (one ROM at a
time on purpose: extract_title_icon reads the whole ROM file, so parallel reads
would thrash IO), emits only successful icons, and skips paths already cached.
The window caches decoded QPixmaps in memory keyed by path (`_icon_cache`), so
rescans reapply instantly and only new ROMs are decoded. Tiles render the icon
via `GameTile.set_icon`, keeping the 2-letter placeholder plate as the fallback.

Caveat (noted, within scope): icon loading reads each full ROM, so first-time
population of a very large library is slow. Mitigated by background loading,
progressive tile updates, and the in-memory cache. A partial-read fast path
would need new routing and was out of scope (45-min cap, reuse-core rule).

## Pass 3 (DONE, 2026-06-07): 3DS visual language

In `home_menu.py`:

- Bundled font: Nunito (rounded humanist sans, OFL) at
  `tex_forge/gui/assets/fonts/Nunito-VariableFont_wght.ttf` (+ OFL.txt).
  `load_app_font()` registers it via QFontDatabase and main() sets it as the app
  font; `_asset()` resolves the path for both source and frozen (PyInstaller)
  runs. The PyInstaller spec (later) must bundle assets/fonts as datas.
- Glossy tiles: new `IconPlate` widget paints a white-to-pale rounded gradient,
  the real icon (or 2-letter initials fallback), and a soft top sheen (gloss).
  Each `GameTile` has a soft drop shadow (QGraphicsDropShadowEffect) that lifts
  and turns into a cyan accent glow when selected.
- Motion: selecting a tile runs a quick shadow "lift" pop (QPropertyAnimation on
  blurRadius, OutBack easing); the stage preview fades in on every swap
  (QGraphicsOpacityEffect 0.3 -> 1.0, OutCubic, 200ms). Both are short and
  non-blocking.
- Verified by rendering the window offscreen to PNG and eyeballing: cohesive 3DS
  HOME Menu look (sky gradient workbench, lit top-screen stage with checkerboard
  + metadata, hinge seam, glossy rounded tiles with real icons + gloss + shadow,
  selected-tile cyan glow, rounded font, rounded queue panel + pill buttons).

Perf note: drop shadows use one QGraphicsDropShadowEffect per tile; fine for the
typical few-dozen library, may warrant a lighter painted shadow if someone runs
the full 600-tile cap. Not changed now.

## Pass 4 (DONE, 2026-06-07): Activity Log heartbeat + live themes

In `home_menu.py`:

- Theme system: SKY / DARK / CORAL palettes in a `THEMES` registry. The active
  `THEME` is now a mutable dict whose identity stays stable; `set_theme(name)`
  swaps its contents in place so every THEME[...] lookup (stylesheets we re-run,
  and paint-time reads) picks up the new palette. `_lighten()` derives button
  hover colors from the accent so they work in every palette.
- Live switching: each surface gained an `apply_theme()` that re-runs its
  stylesheet from THEME (StatusStrip, Stage, Workbench incl. inputs/list/buttons
  /labels/tiles, ActivityShelf) and repaints custom-painted widgets. The window
  `apply_theme()` re-styles the splitter seam and calls the children. IMPORTANT:
  the window calls `apply_theme()` once at the end of __init__ so a non-sky saved
  theme is honored at startup (construction-time styles are otherwise only
  refreshed on a change). Theme persists via cfg["theme"]; the picker is a combo
  in the ActivityShelf.
- ActivityShelf (the heartbeat): brand label + three stat cards (Lifetime
  textures, Games processed, This session) + the theme picker, across the top of
  the workbench. Warm, always visible.
- Persistent lifetime stats in config.json (config.py keys lifetime_textures /
  lifetime_games / lifetime_seeded). Seeded ONCE with a clearly labelled
  PLACEHOLDER baseline (SEED_LIFETIME_TEXTURES = 1,000,000 and
  SEED_LIFETIME_GAMES = 35, matching the project's claimed figures) so the panel
  is not empty; real successful runs add on top via `_record_run()` in
  `_on_extract_done` (session + lifetime, saved immediately). Session counters
  reset each launch.
- Verified headless: seeding shows 1,000,000 / 35; a run incremented lifetime to
  1,002,824 and session to 2,824; live sky->dark switch restyled every surface
  (rendered to PNG and eyeballed: dark queue panel, dark inputs, readable light
  tile labels, combo in sync); fixed a startup bug where a saved dark theme left
  the queue panel/inputs white. Config reset to a clean state afterwards
  (theme=sky, lifetime 1,000,000 / 35).

## Finish line (in progress, 2026-06-07)

- Item 1 DONE: entry.py now launches the HOME Menu UI. It keeps the PySide6
  import guard and delegates to `home_menu.main()`; the legacy config/backend
  shims and the _gui_app_v1 launch path were removed (the new UI imports v2
  modules directly). _gui_app_v1.py stays in the tree for reference.
- Item 3 DONE: Launch-Forge.bat now does `cd /d "%~dp0"` (runs from wherever the
  repo lives, no more hardcoded C:\claude path) then `python -m
  tex_forge.gui.entry`. pyproject [project.gui-scripts] fixed to
  `tex_forge.gui.entry:main`.
- Item 2 DONE: PyInstaller spec authored (forge.spec) with launcher
  forge_gui.py. Bundles tex_forge/gui/assets (the font) as datas,
  collect_submodules('tex_forge') for plugin coverage, excludes unused big Qt
  modules (WebEngine/QML/Multimedia), onefile + windowed, UPX off (it can
  corrupt Qt). pyinstaller 6.20 installed (Python 3.14). Built
  `dist/3DS-Texture-Forge.exe` (66 MB, matches the handoff's expected size).
  Verified it runs: process launches and stays alive, the onefile _MEI bundle
  extracts cleanly, and the font (Nunito ttf + OFL.txt) is present inside at
  tex_forge/gui/assets/fonts so _asset() resolves it at runtime. Build it with
  `pyinstaller forge.spec --noconfirm --clean`; outputs land in build/ + dist/.
  FULL EXTRACTION THROUGH THE EXE VALIDATED: drove the running exe with
  synthesized clicks (NSMB2 tile -> Start), the GUI ran the pipeline to COMPLETE
  (manifest.json written), the stage showed a real decoded texture (the NSMB2
  Super Mushroom), and the Activity shelf lifetime counter incremented from
  1,000,000 to 1,002,824 (persistent stats work in the frozen build). Output at
  output/New Super Mario Bros. 2/: manifest (2824 decoded, 1760 unique, 301s),
  1760 tex1_<W>x<H>_<CityHash64>_<fmt>_mip0.png Azahar drop-in files, plus
  contact_sheet.png, quality_report.{json,txt}, summary.json, failures.json.
  (Driving needed forcing the window topmost; SetForegroundWindow alone loses to
  the Windows foreground lock and clicks hit occluding windows. The throwaway
  drive_exe.py driver was removed after use.)
- Item 4 PARKED: README "A note on how this was built" blockquote awaiting Zag's
  paste. Do not fabricate.

## Status log

- 2026-06-07: Oriented; created PROGRESS.md; verified v1 GUI headless; confirmed
  README blocker. Built + verified Pass 1 (shell + grid). Built + verified
  Pass 2 (extraction wiring, LED states, stage texture preview). Added the
  read-only SMDH icon accessor (rom/icon.py) and wired real icons onto tiles.
  Built + verified Pass 3 (Nunito font, glossy rounded tiles with shadow/gloss,
  selection pop + stage fade motion). Built + verified Pass 4 (Activity Log
  lifetime/session stats with persistent placeholder seed, live theme switching
  sky/dark/coral with startup honoring). Finish line items 1-3 done: entry.py
  switched to the HOME Menu UI; Launch-Forge.bat + pyproject gui-script fixed;
  PyInstaller spec authored and dist/3DS-Texture-Forge.exe (66 MB) built and
  confirmed to launch with the font bundled. Item 4 (README blockquote) parked.
- 2026-06-09: Full codebase review (Claude, web). FIXED a critical normal-mode
  bug: _build_output_path passed a hardcoded index 0 to generate_filename, so
  unnamed textures sharing a format and size in one source dir composed the
  same filename and silently overwrote each other (manifest pointed N records
  at 1 file); repro'd, fixed by threading the pipeline-wide counter through,
  regression-tested. Implemented the three dead CLI flags: --dump-raw (raw GPU
  bytes to raw/<tex_id>_<W>x<H>_<fmt>.bin, raw_dump_path in the manifest, kept
  out of pack folders), --list-files (manifest-only scan, no decode/PNG/
  quality/contact sheet), --report (report.json breakdowns). Added cooperative
  cancellation: ExtractionPipeline.cancel_event checked per file, partial
  outputs written with summary["canceled"]; backend run_extraction passes it
  through. GUI: Stop and closeEvent now cancel cooperatively (terminate only
  as a last-resort on app exit; it could not stop the PNG pool and risked
  interpreter corruption); ScanWorker terminate removed (workers tracked to
  completion, stale results dropped by selected path); canceled jobs no longer
  bump lifetime stats; terminal queue jobs re-queue on tile click; queue
  double-click opens a finished job's output folder; Settings dialog added
  (output mode normal/azahar, dedup, scan-all, dump-raw, new-folder-per-run,
  verbose, output base folder), so Azahar mode no longer requires hand-editing
  config.json; output_mode added to DEFAULT_CONFIG; _output_dir_for hardened
  for Windows reserved names (CON/NUL/COM1...) and trailing dots/spaces;
  new_folder_per_run honored in normal mode via run_<timestamp> subfolders
  (Azahar keeps ONE stable drop-in folder by design); HingeLED milestone flash
  generation-guarded so a flash ending after queue completion cannot resurrect
  the busy pulse. FileFilter.should_peek gained tail_data: BFLIM/BCLIM footers
  (magic at file end) were previously unreachable by the head-only peek; the
  extractor now passes the last 0x28 bytes. Tests 89 -> 94 (new
  tests/test_extractor_fixes.py), all passing; GUI verified headless
  (construction, settings round-trip, re-queue, reserved names, per-run vs
  stable folders, LED guard, stop-with-no-worker). NOT rebuilt: the exe
  (dist/ predates all of this; rebuild with `pyinstaller forge.spec
  --noconfirm --clean`). README blockquote still parked (item 4): not on
  GitHub search either, must come from Zag.
- 2026-06-09 (second pass): feature work toward v2.5. NEW `tex-forge batch`
  (the v2.5 batch-processing target): takes files and/or folders, walks for
  every loader extension, extracts each title to <out>/<title_id>/ through
  the real per-ROM pipeline (multi-content CIAs included), continues on
  encrypted/parse/unexpected errors, skips duplicate title IDs within a run
  (same game as .3ds AND .cia extracts once), --limit N for slicing huge
  sets, writes batch_summary.json plus a results table; exit 1 if anything
  failed. NEW `tex-forge verify`: audits an output dir against its manifest;
  flags missing PNGs, orphan tex*.png files, missing raw dumps, and 2+
  records sharing one decoded_png_path (the exact signature of the pre-fix
  filename-collision bug, so old outputs can be triaged for re-extraction);
  skips load_pack/ by design; --json writes verify_report.json; pure
  verify_project() is importable for tooling. ROM_EXTENSIONS moved to
  rom/loader.py as the single source of truth (additive constant only); GUI
  and batch both import it. CLI gained --version. GUI batch ergonomics: a
  library filter box (live, re-packs the grid contiguously, survives
  rescans, uses isHidden so it works pre-show), a Queue All button (queues
  every visible tile, respects the filter), and drag-and-drop of ROM files
  anywhere onto the window (queued by path; works for ROMs outside the
  library folders, no tile needed). GUI now writes a rotating log to
  ~/.3ds-texture-forge/forge.log (1 MB x3, level follows verbose_logging)
  and chains a sys.excepthook that logs uncaught exceptions: the windowed
  exe finally leaves evidence when something breaks. Checked build-pack
  --upscaled: already present and wired to pack_builder upscaled_dir (the
  3ds-upscaler handoff point), no change needed. Tests 94 -> 101
  (tests/test_batch_verify.py); both GUI smoke suites pass headless.
- 2026-06-09 (third pass): stage banner art. The "Queue this game" stage now
  shows the selected title's HOME Menu BANNER image. New rom/banner.py
  (read-only accessor, reuse-core rule kept): the ExeFS "banner" entry is a
  CBMD container; parse_cbmd slices the LZ11-compressed CGFX out of it
  (common model first, region-specific fallback, bounded by the CWAV
  offset), the EXISTING lz_nintendo_lz11 codec decompresses it, the
  EXISTING cgfx plugin iterates its textures, the EXISTING decoder decodes
  candidates, and the largest decodable texture wins (small ones are
  shading ramps/logos; the banner image proper is the big one, typically
  256x128). No new swizzle/format/parser code. icon.py's ExeFS entry walk
  generalised to find_exefs_entry(exefs, name) and shared. Backend gained
  get_rom_banner_rgba (never raises). GUI: BannerWorker decodes the
  selected title off-thread on scan success; results (including None)
  cached by path so no title is re-read; while it runs the stage shows the
  SMDH icon pre-scaled 4x nearest-neighbour (crisp pixel look, not blur);
  the banner swaps in when ready; stale results for unselected paths and
  mid-extraction arrivals never stomp the stage; closeEvent waits for
  banner workers. NOT validated against a real ROM yet (sandbox has none):
  the CBMD slice + selection logic is unit-tested synthetically
  (tests/test_banner.py), the decompress/CGFX/decode path is entirely
  pre-validated components. First real-ROM check is on the dev box. Tests
  101 -> 106; all three GUI smoke suites pass headless.
- 2026-06-09 (fix): Clear Queue was a no-op on a fresh queue. The Pass 2
  convention removed only terminal jobs (COMPLETE/FAILED/CANCELED) and kept
  QUEUED ones, so clearing a just-built queue did nothing (Zag hit this
  live). Clear Queue now removes every job except the one RUNNING, which is
  what the button says. Also added a right-click context menu on queue
  items: "Remove from queue" for any non-running job, and "Open output
  folder" when the job has one. Smoke-verified headless (fresh-queue clear,
  mixed-state clear keeps only RUNNING, re-queue after clear).

## RESUMING TOMORROW

Two review/feature passes (2026-06-09) are in source and tested: 101 tests
passing, both GUI smoke suites pass headless. The exe has NOT been rebuilt;
dist/ still holds the pre-review build. First actions on the dev box:

1. Rebuild the exe: `pyinstaller forge.spec --noconfirm --clean`. Then:
   spot-check Stop mid-run (cooperative cancel, job goes CANCELED, partial
   manifest kept), the Settings dialog (switch to Azahar, run, confirm one
   stable hash-named folder), the filter box + Queue All, and drag-drop a
   ROM from outside the library onto the window.
2. NEW, validate the stage banner on a real ROM: select NSMB2; the stage
   should show the crisp-scaled icon immediately, then swap to the actual
   banner art (the CBMD -> LZ11 -> CGFX path is synthetic-tested only; if a
   real banner misbehaves, forge.log has the reason at INFO level).
2. Run the new batch command against the real set as the v2.5 batch
   validation, e.g.:
   `tex-forge batch "D:\Roms\3D" -o D:\Textures\batch --output-mode azahar
   --dedup --limit 3`
   then inspect batch_summary.json and one title folder.
3. Audit old extractions for the collision bug:
   `tex-forge verify <old output dir>`; any "shared paths" hits mean that
   title needs re-extraction with the fixed build.
4. README protected blockquote (UNCHANGED, the only content blocker):
   pending Zag's paste of the authentic "A note on how this was built"
   text. Restore VERBATIM above the `# 3DS Texture Forge 2.0` heading. Do
   not fabricate.

v2.5 remaining after this: Pokemon support (parser work; needs real GARC
content validation on the dev box, hex-dump-first, 45-min caps per the
Claude Code workflow). v3.0 (.texproj authoring pipeline) untouched.

Behavior notes for the next session:

- `tex-forge batch` extracts to <out>/<title_id>/ and skips duplicate title
  IDs within one run; exit code 1 means at least one ROM failed (the rest
  still extracted).
- `tex-forge verify --json` writes verify_report.json;
  commands/verify.verify_project() is the importable pure API.
- GUI logs to ~/.3ds-texture-forge/forge.log (rotating, 1 MB x3); uncaught
  GUI exceptions land there too.
- ROM extensions now come from rom/loader.ROM_EXTENSIONS everywhere.
- Normal-mode output filenames carry the real running index (tex_0000,
  tex_0001, ...). Outputs from before 2026-06-09 may be missing collided
  textures; verify finds them.
- manifest records gained optional raw_dump_path (only when --dump-raw);
  summary gains "canceled": true on stopped runs.
- FileFilter.should_peek now takes (path, peek_data, tail_data).

Optional follow-ups if desired later (not requested):
- GUI surface for batch_summary.json after a Queue All run (per-job stats
  already show in the queue; an aggregate card could sit on the shelf).
- Lighter painted tile shadow if anyone runs the full 600-tile discovery cap.
- Consider deleting _gui_app_v1.py / _gui_entry_v1.py once the new UI is locked.
- A cancel checkpoint INSIDE huge single files (the per-file check means one
  giant CPK can still take a while to stop).

To rebuild the exe: `pyinstaller forge.spec --noconfirm --clean` (outputs to
build/ + dist/). Remember: kill and relaunch the app after editing (no hot
reload). Test ROM: D:\Roms\3D\New Super Mario Bros. 2 (USA) (En,Fr,Es).3ds.
