"""`tex-forge scan ROM` -- inspect ROM contents without extracting."""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter

from tex_forge.commands._common import load_rom_or_die, setup
from tex_forge.pipeline.filter import FileFilter
from tex_forge.pipeline.scanner import classify_file
from tex_forge.rom.romfs import RomFSParser


def add_subparser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("scan", help="Scan ROM and report contents")
    p.add_argument("input")
    p.add_argument("--scan-all", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--quiet",   action="store_true")
    p.set_defaults(_handler=_run)


def _run(args: argparse.Namespace) -> int:
    setup(args.verbose, args.quiet)
    t0 = time.time()
    romfs_data, title_id, product_code, chain = load_rom_or_die(args.input)

    romfs = RomFSParser(romfs_data)
    files = romfs.list_files()

    flt = FileFilter(scan_all=args.scan_all)
    ext_counts = Counter()
    type_counts = Counter()
    candidates = 0

    for path, off, size in files:
        ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
        ext_counts[ext or "(none)"] += 1
        if not flt.should_peek(path):
            continue
        candidates += 1
        peek = romfs_data[off:off + min(size, 0x30)] if size and off else b""
        peek_obj = classify_file(peek, path)
        type_counts[peek_obj.detected_type or "unknown"] += 1

    elapsed = time.time() - t0

    print()
    print("--- Scan Results ---")
    print(f"ROM:        {args.input}")
    print(f"Title ID:   {title_id}")
    print(f"Product:    {product_code}")
    print(f"Container:  {chain}")
    print(f"Total files: {len(files)}")
    print(f"Texture candidates: {candidates}")
    print()
    print("Extension breakdown:")
    for ext, n in ext_counts.most_common(20):
        print(f"  {ext:14s} {n:6d}")
    print()
    print("Detected container types:")
    for t, n in type_counts.most_common():
        print(f"  {t:18s} {n:6d}")
    print(f"\nElapsed: {elapsed:.1f}s")
    return 0
