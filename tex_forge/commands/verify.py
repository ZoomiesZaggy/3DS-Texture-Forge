"""`tex-forge verify PROJECT_DIR` -- audit an extraction's output integrity.

Cross-checks manifest.json against what is actually on disk:

  * missing PNGs: records whose decoded_png_path does not exist
  * shared paths: 2+ records pointing at ONE decoded_png_path. This is the
    signature of the pre-fix filename-collision bug (unnamed textures sharing
    a format and size overwrote each other), so verify is the tool for
    auditing outputs extracted before 2026-06-09. Legit dedup duplicates are
    not flagged: those carry duplicate_of and an empty path.
  * orphan PNGs: tex_*.png files on disk that no record references
  * missing raw dumps: raw_dump_path entries with no file behind them

Exit code 0 when clean, 1 when any problem is found (or the manifest is
missing/unreadable). --json additionally writes verify_report.json into the
project dir for tooling.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from typing import Any, Dict, List

from tex_forge.commands._common import setup


def add_subparser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "verify",
        help="Audit an extraction output dir (manifest vs files on disk)",
    )
    p.add_argument("project_dir", help="Extraction output directory")
    p.add_argument("--json", action="store_true",
                   help="Also write verify_report.json into the project dir")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--quiet",   action="store_true")
    p.set_defaults(_handler=_run)


def verify_project(project_dir: str) -> Dict[str, Any]:
    """Pure audit: returns a report dict, never prints, never exits.

    report["ok"] is True only when every check passes.
    """
    report: Dict[str, Any] = {
        "project_dir": os.path.abspath(project_dir),
        "ok": False,
        "manifest_found": False,
        "record_count": 0,
        "missing_pngs": [],
        "shared_paths": {},      # path -> [tex ids] (collision-bug signature)
        "orphan_pngs": [],
        "missing_raw_dumps": [],
    }

    manifest_path = os.path.join(project_dir, "manifest.json")
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError) as e:
        report["error"] = f"cannot read manifest.json: {e}"
        return report
    report["manifest_found"] = True

    records: List[Dict[str, Any]] = manifest.get("textures", [])
    report["record_count"] = len(records)

    referenced = set()
    path_owners: Dict[str, List[str]] = {}
    for rec in records:
        rel = rec.get("decoded_png_path", "")
        if not rel:
            continue
        path_owners.setdefault(rel, []).append(rec.get("id", "?"))
        referenced.add(os.path.normcase(os.path.normpath(rel)))
        full = os.path.join(project_dir, rel)
        if not os.path.isfile(full):
            report["missing_pngs"].append(
                {"id": rec.get("id", "?"), "path": rel})
        raw_rel = rec.get("raw_dump_path", "")
        if raw_rel and not os.path.isfile(os.path.join(project_dir, raw_rel)):
            report["missing_raw_dumps"].append(
                {"id": rec.get("id", "?"), "path": raw_rel})

    report["shared_paths"] = {
        p: ids for p, ids in path_owners.items() if len(ids) > 1
    }

    # Orphans: texture-looking PNGs nothing in the manifest claims. Scoped to
    # tex-prefixed names so contact_sheet.png and user files never false-flag.
    for root, _dirs, files in os.walk(project_dir):
        # never descend into pack output; it duplicates files by design
        _dirs[:] = [d for d in _dirs if d != "load_pack"]
        for f in files:
            if not (f.lower().endswith(".png") and f.startswith("tex")):
                continue
            rel = os.path.relpath(os.path.join(root, f), project_dir)
            if os.path.normcase(os.path.normpath(rel)) not in referenced:
                report["orphan_pngs"].append(rel)

    report["ok"] = not (report["missing_pngs"] or report["shared_paths"]
                        or report["orphan_pngs"]
                        or report["missing_raw_dumps"])
    return report


def _run(args: argparse.Namespace) -> int:
    setup(args.verbose, args.quiet)
    report = verify_project(args.project_dir)

    if not report["manifest_found"]:
        print(report.get("error", "manifest.json not found"))
        return 1

    print()
    print(f"--- Verify: {report['project_dir']} ---")
    print(f"Records:          {report['record_count']}")
    print(f"Missing PNGs:     {len(report['missing_pngs'])}")
    print(f"Shared paths:     {len(report['shared_paths'])}"
          + ("  <- filename-collision signature; re-extract this title"
             if report["shared_paths"] else ""))
    print(f"Orphan PNGs:      {len(report['orphan_pngs'])}")
    print(f"Missing raw dumps: {len(report['missing_raw_dumps'])}")

    if not args.quiet:
        for item in report["missing_pngs"][:10]:
            print(f"  missing: {item['id']} -> {item['path']}")
        shown = 0
        for p, ids in report["shared_paths"].items():
            print(f"  shared:  {p} <- {', '.join(ids[:6])}"
                  + (" ..." if len(ids) > 6 else ""))
            shown += 1
            if shown >= 10:
                break
        for p in report["orphan_pngs"][:10]:
            print(f"  orphan:  {p}")

    if args.json:
        out_path = os.path.join(args.project_dir, "verify_report.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"Report written:   {out_path}")

    print("Result:           " + ("CLEAN" if report["ok"] else "PROBLEMS FOUND"))
    return 0 if report["ok"] else 1
