"""`tex-forge import-dump DUMP_FOLDER PROJECT_DIR` -- merge runtime hashes.

When Azahar / Citra dumps textures from a running game, the resulting PNG
filenames carry the GPU upload hash. This subcommand pairs those dumps
with rows in our manifest (matching by dimensions + format) and stamps
the runtime hash into each record so a subsequent build-pack run can
emit a fully-mapped pack.

Filename patterns we recognise:
  tex1_256x256_DEADBEEF_ETC1_mip0.png
  DEADBEEF01234567.png
  0xDEADBEEF_256x256.png

Mirrors v1's `import-dump` subcommand.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict

from tex_forge.commands._common import setup


def add_subparser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("import-dump", help="Import emulator texture dump")
    p.add_argument("dump_folder", help="Folder with dumped PNGs")
    p.add_argument("project_dir", help="Extraction output directory")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--quiet",   action="store_true")
    p.set_defaults(_handler=_run)


def _run(args: argparse.Namespace) -> int:
    setup(args.verbose, args.quiet)

    if not os.path.isdir(args.dump_folder):
        print(f"Dump folder not found: {args.dump_folder}")
        return 1
    manifest_path = os.path.join(args.project_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        print(f"No manifest.json in {args.project_dir}")
        return 1

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    textures = manifest.get("textures", [])

    dumps: list[Dict[str, Any]] = []
    for fname in os.listdir(args.dump_folder):
        if not fname.lower().endswith(".png"):
            continue
        info = _parse_dump_filename(fname)
        info["full_path"] = os.path.join(args.dump_folder, fname)
        dumps.append(info)

    print(f"Found {len(dumps)} dumped textures in {args.dump_folder}")

    matched = 0
    unmatched: list[Dict[str, Any]] = []
    for d in dumps:
        dump_w = d.get("width", 0)
        dump_h = d.get("height", 0)
        dump_hash = d.get("hash", "")
        dump_fmt = d.get("format", "")

        best = None
        for tex in textures:
            tw = tex.get("width", 0)
            th = tex.get("height", 0)
            if tw == dump_w and th == dump_h:
                if dump_fmt and dump_fmt.upper() in tex.get("detected_format", "").upper():
                    best = tex
                    break
                if best is None:
                    best = tex

        if best and dump_hash:
            best["dump_hash"] = dump_hash
            matched += 1
        else:
            unmatched.append(d)

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    report = {
        "dump_folder": args.dump_folder,
        "dump_files_found": len(dumps),
        "matched_to_manifest": matched,
        "unmatched": len(unmatched),
        "unmatched_files": [d.get("filename", "") for d in unmatched],
    }
    report_path = os.path.join(args.project_dir, "import_dump_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"Matched {matched} of {len(dumps)} to manifest entries")
    print(f"Unmatched: {len(unmatched)}")
    print(f"Report: {report_path}")
    if matched:
        print("Run 'tex-forge build-pack' again for a mapped pack with real hashes.")
    return 0


def _parse_dump_filename(fname: str) -> Dict[str, Any]:
    """Parse one of the common dump filename patterns into structured fields."""
    info = {"filename": fname, "hash": "", "width": 0, "height": 0, "format": "", "mip": 0}

    base = fname.rsplit(".", 1)[0]
    parts = base.replace("-", "_").split("_")

    from tex_forge.textures.formats import FORMAT_NAMES
    known_fmts = {v.upper() for v in FORMAT_NAMES.values()}

    for part in parts:
        if "x" in part:
            try:
                wh = part.lower().split("x")
                if len(wh) == 2 and wh[0].isdigit() and wh[1].isdigit():
                    info["width"] = int(wh[0]); info["height"] = int(wh[1])
                    continue
            except ValueError:
                pass
        if part.lower().startswith("mip"):
            try:
                info["mip"] = int(part[3:]); continue
            except ValueError:
                pass
        if part.upper() in known_fmts:
            info["format"] = part.upper(); continue

        clean = part.lower().lstrip("0x")
        if len(clean) >= 8 and all(c in "0123456789abcdef" for c in clean):
            info["hash"] = clean; continue

    if not info["hash"] and len(base) >= 8:
        clean = base.lower().lstrip("0x")
        if all(c in "0123456789abcdef" for c in clean):
            info["hash"] = clean

    return info
