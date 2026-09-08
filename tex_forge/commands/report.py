"""`tex-forge report PROJECT_DIR` -- summarise an extraction project.

Reads manifest.json + failures.json + unknown_files.json from a previous
extraction's output directory and prints a breakdown by confidence /
format / quality.

Mirrors v1's `report` subcommand exactly.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter

from tex_forge.commands._common import setup


def add_subparser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("report", help="Report on a previous extraction")
    p.add_argument("project_dir", help="Extraction output directory")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--quiet",   action="store_true")
    p.set_defaults(_handler=_run)


def _run(args: argparse.Namespace) -> int:
    setup(args.verbose, args.quiet)
    project_dir = args.project_dir

    manifest_path = os.path.join(project_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        print(f"No manifest.json in {project_dir}")
        return 1

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    textures = manifest.get("textures", [])
    print()
    print(f"--- Report for {project_dir} ---")
    print(f"Title ID:     {manifest.get('title_id', '?')}")
    print(f"Game:         {manifest.get('game_title', '?')}")
    print(f"Container:    {manifest.get('container_chain', '?')}")
    print(f"Textures:     {len(textures)}")

    conf = Counter()
    fmt_counts = Counter()
    parser_counts = Counter()
    suspicious = 0
    for t in textures:
        conf[t.get("confidence", "unknown")] += 1
        fmt_counts[t.get("detected_format", "?")] += 1
        parser_counts[t.get("parser_used", "unknown")] += 1
        if t.get("quality", {}).get("is_suspicious"):
            suspicious += 1

    print()
    print("Confidence breakdown:")
    for c, n in sorted(conf.items()):
        print(f"  {c:12s} {n:6d}")

    print()
    print("Format breakdown:")
    for f, n in fmt_counts.most_common():
        print(f"  {f:12s} {n:6d}")

    print()
    print("Parser breakdown:")
    for p, n in parser_counts.most_common():
        print(f"  {p:18s} {n:6d}")

    print()
    print(f"Suspicious:   {suspicious}")

    fail_path = os.path.join(project_dir, "failures.json")
    if os.path.isfile(fail_path):
        with open(fail_path, "r", encoding="utf-8") as f:
            fail_data = json.load(f)
        print(f"Failures:     {fail_data.get('count', 0)}")

    unk_path = os.path.join(project_dir, "unknown_files.json")
    if os.path.isfile(unk_path):
        with open(unk_path, "r", encoding="utf-8") as f:
            unk_data = json.load(f)
        print(f"Unknown files: {unk_data.get('count', 0)}")

    return 0
