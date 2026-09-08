"""`tex-forge batch INPUTS... -o OUT` -- extract a whole library in one run.

Inputs are any mix of ROM files and folders; folders are walked recursively
for every extension parse_rom understands (loader.ROM_EXTENSIONS). Each ROM
extracts into `<OUT>/<title_id>/` with the same per-ROM behavior as
`tex-forge extract` (multi-content CIAs included). One failing or encrypted
ROM never aborts the batch: it is recorded and the run continues.

Within one batch, a title ID is processed once; later ROMs resolving to the
same title (e.g. the same game present as both .3ds and .cia) are recorded
as skipped duplicates rather than overwriting the first extraction.

A machine-readable `batch_summary.json` lands in OUT next to the per-title
folders, and a human table prints at the end.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from typing import Iterable, List, Tuple

from tex_forge.commands._common import setup
from tex_forge.core.exceptions import EncryptedROMError, ROMParseError
from tex_forge.pipeline.extractor import (
    ContentSource,
    ExtractionPipeline,
    ExtractOptions,
)
from tex_forge.pipeline.progress import CLIBarProgress, NullProgress
from tex_forge.rom.loader import (
    ROM_EXTENSIONS,
    content_label_from_chain as _content_label,
    iter_rom_contents,
)


def add_subparser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "batch",
        help="Extract every ROM in the given files/folders (continue on error)",
    )
    p.add_argument("inputs", nargs="+",
                   help="ROM files and/or folders to walk recursively")
    p.add_argument("-o", "--output", metavar="DIR", default="output",
                   help="Batch root; each title extracts to <DIR>/<title_id>/ "
                        "(default: output)")
    p.add_argument("--output-mode", choices=["normal", "azahar"],
                   default="normal")
    p.add_argument("--dedup",    action="store_true",
                   help="Skip writing duplicate textures (per title)")
    p.add_argument("--scan-all", action="store_true")
    p.add_argument("--dump-raw", action="store_true")
    p.add_argument("--limit", type=int, default=0, metavar="N",
                   help="Stop after N ROMs (0 = no limit; handy for testing "
                        "a slice of a large set)")
    p.add_argument("--no-contact-sheet",  action="store_true")
    p.add_argument("--no-quality-report", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--quiet",   action="store_true")
    p.set_defaults(_handler=_run)


def discover_rom_files(inputs: Iterable[str]) -> Tuple[List[str], List[str]]:
    """Expand files/folders into a sorted, de-duplicated ROM path list.

    Returns (rom_paths, missing_inputs). Folders are walked recursively;
    plain files are accepted only with a known ROM extension. De-dup is by
    normalized absolute path, so overlapping input folders are harmless.
    """
    found: List[str] = []
    missing: List[str] = []
    seen = set()

    def _add(path: str) -> None:
        key = os.path.normcase(os.path.abspath(path))
        if key not in seen:
            seen.add(key)
            found.append(path)

    for item in inputs:
        if os.path.isdir(item):
            for root, _dirs, files in os.walk(item):
                for f in sorted(files):
                    if f.lower().endswith(ROM_EXTENSIONS):
                        _add(os.path.join(root, f))
        elif os.path.isfile(item):
            if item.lower().endswith(ROM_EXTENSIONS):
                _add(item)
            else:
                missing.append(item + " (not a recognised ROM extension)")
        else:
            missing.append(item)
    return found, missing


def _extract_one(rom_path: str, out_dir: str, args: argparse.Namespace,
                 contents: list) -> dict:
    """Run the standard extraction pipeline for preloaded ROM contents."""
    romfs0, title_id, product_code, chain0 = contents[0]
    multi = len(contents) > 1

    options = ExtractOptions(
        output_dir=out_dir,
        output_mode=args.output_mode,
        scan_all=args.scan_all,
        dedup=args.dedup,
        dump_raw=args.dump_raw,
        verbose=args.verbose,
        quiet=args.quiet,
        write_contact_sheet=not args.no_contact_sheet,
        write_quality_report=not args.no_quality_report,
    )
    pipe = ExtractionPipeline(
        romfs_data=romfs0,
        title_id=title_id,
        product_code=product_code,
        chain=chain0,
        rom_path=rom_path,
        options=options,
        progress=NullProgress() if args.quiet else CLIBarProgress(),
        content_source=_content_label(chain0) if multi else "",
        extra_contents=[
            ContentSource(romfs_data=c[0], chain=c[3],
                          source_content=_content_label(c[3]))
            for c in contents[1:]
        ],
    )
    return pipe.run()


def _run(args: argparse.Namespace) -> int:
    setup(args.verbose, args.quiet)
    roms, missing = discover_rom_files(args.inputs)
    for m in missing:
        print(f"  skipping input: {m}")
    if not roms:
        print("No ROMs found in the given inputs.")
        return 1
    if args.limit > 0:
        roms = roms[:args.limit]

    os.makedirs(args.output, exist_ok=True)
    t0 = time.time()
    results: List[dict] = []
    done_titles: dict = {}  # title_id -> rom basename that claimed it

    for i, rom in enumerate(roms, 1):
        base = os.path.basename(rom)
        if not args.quiet:
            print(f"\n[{i}/{len(roms)}] {base}")

        entry = {"rom": base, "title_id": "", "status": "",
                 "output_dir": "", "textures_decoded_ok": 0,
                 "textures_failed": 0, "elapsed_seconds": 0.0, "error": ""}
        try:
            contents = list(iter_rom_contents(rom))  # one read per ROM
            if not contents:
                raise ROMParseError("no readable content")
            title_id = contents[0][1]
            entry["title_id"] = title_id

            if title_id in done_titles:
                entry.update(status="skipped_duplicate",
                             duplicate_of=done_titles[title_id])
                if not args.quiet:
                    print(f"  skipped: title {title_id} already extracted "
                          f"from {done_titles[title_id]}")
                results.append(entry)
                continue

            out_dir = os.path.join(args.output, title_id or
                                   os.path.splitext(base)[0])
            summary = _extract_one(rom, out_dir, args, contents)
            entry.update(
                status="ok",
                output_dir=out_dir,
                textures_decoded_ok=summary.get("textures_decoded_ok", 0),
                textures_failed=summary.get("textures_failed", 0),
                elapsed_seconds=summary.get("elapsed_seconds", 0.0),
            )
            done_titles[title_id] = base
        except EncryptedROMError as e:
            entry.update(status="encrypted", error=str(e))
            if not args.quiet:
                print("  encrypted: decrypt with GodMode9 first")
        except (ROMParseError, OSError) as e:
            entry.update(status="failed", error=str(e))
            if not args.quiet:
                print(f"  failed: {e}")
        except Exception as e:  # one bad ROM must never kill the batch
            entry.update(status="failed", error=f"unexpected: {e}")
            if not args.quiet:
                print(f"  failed (unexpected): {e}")
        results.append(entry)

    elapsed = round(time.time() - t0, 1)
    ok = [r for r in results if r["status"] == "ok"]
    enc = [r for r in results if r["status"] == "encrypted"]
    failed = [r for r in results if r["status"] == "failed"]
    skipped = [r for r in results if r["status"] == "skipped_duplicate"]
    total_tex = sum(r.get("textures_decoded_ok", 0) for r in ok)

    batch_summary = {
        "schema_version": 1,
        "rom_count": len(roms),
        "extracted": len(ok),
        "encrypted": len(enc),
        "failed": len(failed),
        "skipped_duplicates": len(skipped),
        "textures_decoded_total": total_tex,
        "elapsed_seconds": elapsed,
        "output_root": os.path.abspath(args.output),
        "options": {
            "output_mode": args.output_mode, "dedup": args.dedup,
            "scan_all": args.scan_all, "dump_raw": args.dump_raw,
        },
        "results": results,
    }
    summary_path = os.path.join(args.output, "batch_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(batch_summary, f, indent=2)

    print()
    print("=" * 56)
    print("  Batch Results")
    print("=" * 56)
    print(f"  ROMs processed:      {len(roms)}")
    print(f"  Extracted OK:        {len(ok)}")
    if skipped:
        print(f"  Duplicate titles:    {len(skipped)} (skipped)")
    if enc:
        print(f"  Encrypted (skipped): {len(enc)}")
    if failed:
        print(f"  Failed:              {len(failed)}")
        for r in failed[:10]:
            print(f"    - {r['rom']}: {r['error'][:60]}")
    print(f"  Textures decoded:    {total_tex:,}")
    print(f"  Elapsed:             {elapsed:.1f}s")
    print(f"  Summary:             {summary_path}")
    print("=" * 56)
    return 0 if not failed else 1
